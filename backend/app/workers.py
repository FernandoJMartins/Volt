"""Workers Arq: coleta, publicacao e retweet.

Rate limit do X: NUNCA é contornado. Ao receber 429 o job reagenda para depois
do reset informado pela propria API.
"""

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from arq import create_pool
from arq.connections import RedisSettings
from arq.worker import func as arq_func
from sqlalchemy import func, select

from app.config import settings
from app.core.security import decrypt, encrypt
from app.db import SessionLocal
from app.models import (
    AuditLog,
    CandidateMedia,
    ContentCandidate,
    MonitoredAccount,
    PostStats,
    RetweetJob,
    ScheduledPost,
    SourcePost,
    XAccount,
)
from app.services import autopilot, media_source, scoring, sources, x_api, x_web
from app.services.browser import SessionExpired, manager as browser_manager
from app.services.dedup import content_hash
from app.services.storage import storage

logging.basicConfig(
    level=logging.INFO, format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
)
log = logging.getLogger("worker")

MAX_ATTEMPTS = 5


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings.REDIS_URL)


async def enqueue(function: str, *args, defer_seconds: int = 0) -> None:
    """Helper usado pelas rotas da API. defer_seconds adia a execucao do job
    (usado para a primeira coleta de engajamento logo apos publicar)."""
    pool = await create_pool(_redis_settings())
    try:
        await pool.enqueue_job(function, *args, _defer_by=defer_seconds)
    finally:
        await pool.aclose()


async def _fresh_access_token(db, account: XAccount) -> str:
    """Renova o token se estiver perto de expirar."""
    expires = account.token_expires_at
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)

    if expires and expires <= datetime.now(timezone.utc) + timedelta(minutes=2):
        refresh = decrypt(account.refresh_token_encrypted)
        if refresh:
            payload = await x_api.refresh_access_token(refresh)
            account.access_token_encrypted = encrypt(payload["access_token"])
            if payload.get("refresh_token"):
                account.refresh_token_encrypted = encrypt(payload["refresh_token"])
            account.token_expires_at = x_api.expires_at(payload)
            await db.commit()
            log.info("Token renovado para @%s", account.username)
    return decrypt(account.access_token_encrypted)


# ---------------- Coleta ----------------


async def collect_account(ctx, account_id: int, max_posts: int | None = None) -> dict:
    async with SessionLocal() as db:
        account = await db.get(MonitoredAccount, account_id)
        if not account or not account.is_active:
            return {"skipped": True}

        limit = sources.clamp_collect_count(max_posts or account.posts_per_collect)
        log.info("Coletando fonte @%s (%s, max=%d)", account.username, account.source_type, limit)
        provider = sources.get_provider(account.source_type)
        try:
            items = await provider.fetch_new(db, account, max_posts=limit)
        except x_api.RateLimited as exc:
            log.warning("Rate limit na coleta de @%s. Reset: %s", account.username, exc.reset_at)
            return {"rate_limited": True}

        saved = 0
        for item in items:
            if await sources.already_seen(db, item["x_post_id"]):
                continue

            rate = scoring.engagement_rate(
                item["likes"], item["reposts"], item["replies"], item["views"]
            )
            score, breakdown = scoring.compute_score(
                likes=item["likes"],
                reposts=item["reposts"],
                replies=item["replies"],
                views=item["views"],
                has_media=item["has_media"],
                posted_at=item["posted_at"],
                baseline=account.engagement_baseline,
            )
            post = SourcePost(
                x_post_id=item["x_post_id"],
                monitored_account_id=account.id,
                user_id=account.user_id,
                text=item["text"],
                author_username=item["author_username"],
                posted_at=item["posted_at"],
                likes=item["likes"],
                reposts=item["reposts"],
                replies=item["replies"],
                views=item["views"],
                has_media=item["has_media"],
                media_metadata=item.get("media_metadata") or {},
                original_url=item["original_url"],
                content_hash=content_hash(item["text"]),
                score=score,
                score_breakdown=breakdown,
            )
            db.add(post)
            await db.flush()
            # Midia do proprio tweet: baixa, tira metadados e liga ao post.
            if item.get("media_entities"):
                asset_ids = await media_source.import_post_media(
                    db, account.user_id, item["media_entities"]
                )
                post.media_metadata = {
                    **item.get("media_metadata", {}),
                    "assets": asset_ids,
                }
            account.engagement_baseline = scoring.update_baseline(account.engagement_baseline, rate)
            if not item["x_post_id"].startswith("manual:"):
                account.last_seen_post_id = max(account.last_seen_post_id or "", item["x_post_id"])
            saved += 1

        account.last_collected_at = datetime.now(timezone.utc)
        await db.commit()
        log.info("Fonte @%s: %d novos posts", account.username, saved)
        return {"saved": saved}


async def collect_all(ctx) -> dict:
    async with SessionLocal() as db:
        ids = (
            await db.execute(
                select(MonitoredAccount.id).where(MonitoredAccount.is_active.is_(True))
            )
        ).scalars().all()
    for account_id in ids:
        await collect_account(ctx, account_id)
    return {"accounts": len(ids)}


async def _upload_candidate_media(db, candidate_id: int, access_token: str) -> list[str]:
    """Sobe as midias anexadas e devolve os media_ids na ordem definida pelo usuario."""
    links = (
        await db.execute(
            select(CandidateMedia)
            .where(CandidateMedia.content_candidate_id == candidate_id)
            .order_by(CandidateMedia.position)
        )
    ).scalars().all()
    if not links:
        return []

    media_ids = []
    for link in links:
        asset = link.asset
        if asset is None or not asset.publishable:
            # Guarda final: midia de terceiro nunca sobe, mesmo se passar pela API.
            log.warning("Midia %s ignorada: origem nao publicavel", getattr(asset, "id", "?"))
            continue
        data = storage.read(asset.storage_key)
        media_ids.append(await x_api.upload_media(access_token, data, asset.mime_type, asset.kind))
        log.info("Midia %s enviada ao X", asset.filename)
    return media_ids


# ---------------- Publicacao ----------------


async def _candidate_media_paths(db, candidate_id: int) -> list[str]:
    """Caminhos locais das midias publicaveis, na ordem definida pelo usuario."""
    links = (
        await db.execute(
            select(CandidateMedia)
            .where(CandidateMedia.content_candidate_id == candidate_id)
            .order_by(CandidateMedia.position)
        )
    ).scalars().all()
    paths = []
    for link in links:
        asset = link.asset
        if asset is None or not asset.publishable:
            log.warning("Midia %s ignorada: origem nao publicavel", getattr(asset, "id", "?"))
            continue
        paths.append(storage.local_path(asset.storage_key))
    return paths


async def _publish_via_web(db, account: XAccount, candidate: ContentCandidate) -> str:
    """Publica pelo navegador, no contexto isolado da conta. Salva o storage_state."""
    if not account.session_valid:
        raise SessionExpired(f"Conta @{account.username} sem sessao valida. Faca login.")
    media_paths = await _candidate_media_paths(db, candidate.id)
    async with browser_manager.session(account) as (page, _ctx):
        if not await x_web.is_logged_in(page):
            account.session_valid = False
            await db.commit()
            raise SessionExpired(f"Conta @{account.username} deslogou. Refaca o login.")
        post_id = await x_web.publish(page, candidate.generated_text, media_paths)
    await db.commit()  # persiste o storage_state renovado
    return post_id


async def _enforce_pacing(db, row: ScheduledPost, account: XAccount, now: datetime) -> bool:
    """Rate limit INTERNO no momento da publicacao (Fase 4).

    O scheduler distribui horarios respeitando a janela, mas isso nao impede dois
    posts de cairem juntos (agendamento manual + auto, retry, relogio do servidor).
    Aqui revalidamos o pacing da conta e, se violar, REAGENDAMOS o post em vez de
    publicar — nunca se publica acima do limite da conta.

    Regras:
      - intervalo minimo entre posts (min_interval_minutes da conta, piso global).
      - teto diario (posts_per_day), contado no fuso da conta.
    """
    interval = timedelta(
        minutes=max(account.min_interval_minutes, settings.MIN_INTERVAL_MINUTES)
    )
    last = (
        await db.execute(
            select(ScheduledPost)
            .where(
                ScheduledPost.x_account_id == account.id,
                ScheduledPost.status == "published",
            )
            .order_by(ScheduledPost.scheduled_at.desc())
            .limit(1)
        )
    ).scalars().first()
    if last and last.scheduled_at.tzinfo is None:
        last.scheduled_at = last.scheduled_at.replace(tzinfo=timezone.utc)

    if last and now - last.scheduled_at < interval:
        row.scheduled_at = last.scheduled_at + interval
        row.status = "queued"
        await db.commit()
        log.info("Post %s reagendado: intervalo minimo de @%s", row.id, account.username)
        return True

    try:
        tz = ZoneInfo(account.timezone or "UTC")
    except Exception:  # noqa: BLE001
        tz = timezone.utc
    day_start = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    published_today = (
        await db.execute(
            select(func.count())
            .select_from(ScheduledPost)
            .where(
                ScheduledPost.x_account_id == account.id,
                ScheduledPost.status == "published",
                ScheduledPost.scheduled_at >= day_start,
            )
        )
    ).scalar() or 0
    cap = max(1, min(account.posts_per_day, settings.MAX_POSTS_PER_DAY))
    if published_today >= cap:
        row.scheduled_at = day_start + timedelta(days=1)
        row.status = "queued"
        await db.commit()
        log.info("Post %s reagendado: teto diario de @%s (%d/dia)", row.id, account.username, cap)
        return True
    return False


async def collect_post_stats(ctx, account_id: int) -> dict:
    """Coleta o engajamento dos posts PUBLICADOS da conta (Fase 5 — analytics).

    Abre o perfil da conta no navegador (1 navegacao por conta, sem custo de
    API) e casa os posts do timeline com os `published_post_id` registrados.
    Atualiza/insere `PostStats` com snapshot do historico.

    Disparos:
      - varredura periodica do scheduler (a cada ANALYTICS_SWEEP_SECONDS);
      - job deferido logo apos cada publicacao (primeira foto do engajamento);
      - manual, via POST /api/analytics/refresh.
    """
    async with SessionLocal() as db:
        account = await db.get(XAccount, account_id)
        if not account or not account.is_active or account.auth_method != "browser":
            return {"skipped": True}
        if not account.session_state_encrypted:
            return {"skipped": True}

        window_start = datetime.now(timezone.utc) - timedelta(days=60)
        rows = (
            await db.execute(
                select(ScheduledPost).where(
                    ScheduledPost.x_account_id == account.id,
                    ScheduledPost.status == "published",
                    ScheduledPost.scheduled_at >= window_start,
                    ScheduledPost.published_post_id != "",
                )
            )
        ).scalars().all()
        wanted = {r.published_post_id: r for r in rows}
        if not wanted:
            return {"skipped": True, "reason": "sem posts publicados"}

        try:
            async with browser_manager.session(account) as (page, _ctx):
                if not await x_web.is_logged_in(page):
                    account.session_valid = False
                    await db.commit()
                    log.warning("Coleta de stats: @%s deslogou.", account.username)
                    return {"session_expired": True}
                posts = await x_web.fetch_timeline(
                    page, account.username, max_posts=40
                )
        except SessionExpired as exc:
            account.session_valid = False
            await db.commit()
            log.warning("Coleta de stats: sessao de @%s expirada (%s)", account.username, exc)
            return {"session_expired": True}

        existing = {
            s.scheduled_post_id: s
            for s in (
                await db.execute(
                    select(PostStats).where(
                        PostStats.scheduled_post_id.in_([r.id for r in rows])
                    )
                )
            ).scalars().all()
        }

        now = datetime.now(timezone.utc)
        updated = 0
        for p in posts:
            row = wanted.get(p["x_post_id"])
            if row is None:
                continue
            stat = existing.get(row.id)
            if stat is None:
                stat = PostStats(
                    user_id=account.user_id,
                    scheduled_post_id=row.id,
                    x_account_id=account.id,
                )
                db.add(stat)
                existing[row.id] = stat
            stat.likes, stat.reposts = p["likes"], p["reposts"]
            stat.replies, stat.views = p["replies"], p["views"]
            snapshots = list(stat.snapshots or [])
            snapshots.append(
                {
                    "at": now.isoformat(),
                    "likes": p["likes"],
                    "reposts": p["reposts"],
                    "replies": p["replies"],
                    "views": p["views"],
                }
            )
            stat.snapshots = snapshots[-20:]
            stat.first_collected_at = stat.first_collected_at or now
            stat.last_collected_at = now
            updated += 1

        await db.commit()
        log.info("Engajamento de @%s: %d/%d posts atualizados", account.username, updated, len(wanted))
        return {"updated": updated, "tracked": len(wanted)}


async def publish_scheduled(ctx, scheduled_id: int) -> dict:
    async with SessionLocal() as db:
        row = await db.get(ScheduledPost, scheduled_id)
        if not row or row.status in ("publishing", "published", "cancelled"):
            # 'publishing' entra no skip: com re-enfileiramento (worker fora do ar,
            # retry manual), dois jobs do MESMO post podem disparar juntos; sem o
            # guarda o segundo publica o texto de novo (post duplicado visto em
            # teste real). Trade-off: se o processo morrer no meio, o post fica
            # preso em 'publishing' e exige intervencao manual — melhor que duplicar.
            return {"skipped": True}
        if row.scheduled_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc) + timedelta(
            seconds=30
        ):
            return {"too_early": True}

        account = await db.get(XAccount, row.x_account_id)
        candidate = await db.get(ContentCandidate, row.content_candidate_id)
        if not account or not candidate or not account.is_active:
            row.status, row.last_error = "failed", "Conta ou conteudo indisponivel"
            await db.commit()
            return {"failed": True}

        # Rate limit interno: se publicar agora violaria o pacing da conta,
        # reagenda e sai sem publicar (o scheduler redespacha quando vencer).
        now = datetime.now(timezone.utc)
        if await _enforce_pacing(db, row, account, now):
            return {"rescheduled": True}

        row.status = "publishing"
        await db.commit()

        try:
            if account.auth_method == "browser":
                # Caminho padrao: publicacao via navegador, sem API oficial.
                post_id = await _publish_via_web(db, account, candidate)
            else:
                token = await _fresh_access_token(db, account)
                if not token:
                    raise x_api.XApiError("Conta sem token valido. Reconecte via OAuth.")
                media_ids = await _upload_candidate_media(db, candidate.id, token)
                post_id = await x_api.publish_tweet(token, candidate.generated_text, media_ids)

            row.status, row.published_post_id, row.last_error = "published", post_id, ""
            candidate.status = "published"
            candidate.published_at = datetime.now(timezone.utc)
            db.add(
                AuditLog(
                    user_id=row.user_id,
                    action="post.published",
                    entity="scheduled_post",
                    entity_id=str(row.id),
                    detail={
                        "account": account.username,
                        "published_post_id": post_id,
                        "source_post_id": candidate.source_post_id,
                        "origin": candidate.origin,
                    },
                )
            )
            await db.commit()
            log.info("Publicado %s por @%s", post_id, account.username)
            # Primeira foto do engajamento ~45min depois: da tempo do post
            # ganhar interacoes iniciais sem sobrecarregar o navegador agora.
            if account.auth_method == "browser" and post_id:
                await enqueue("collect_post_stats", account.id, defer_seconds=2700)
            return {"published_post_id": post_id}

        except x_api.CreditsDepleted as exc:
            # Sem creditos, repetir so queima tentativa. Falha direto e avisa.
            row.status, row.last_error, row.attempts = "failed", str(exc), row.attempts + 1
            await db.commit()
            log.error("Publicacao %s: conta do X sem creditos", row.id)
            return {"credits_depleted": True}

        except x_api.RateLimited as exc:
            # Respeita o limite: reagenda para depois do reset informado pelo X.
            reset = exc.reset_at or datetime.now(timezone.utc) + timedelta(minutes=15)
            row.status, row.scheduled_at = "queued", reset + timedelta(seconds=30)
            row.last_error = f"Rate limit; reagendado para {reset.isoformat()}"
            await db.commit()
            log.warning("Rate limit ao publicar. Reagendado para %s", reset)
            return {"rate_limited": True}

        except SessionExpired as exc:
            # Sessao do navegador expirou: repetir nao adianta ate' o novo login.
            row.status, row.last_error, row.attempts = "failed", str(exc), row.attempts + 1
            await db.commit()
            log.error("Publicacao %s: sessao do navegador expirada", row.id)
            return {"session_expired": True}

        except Exception as exc:  # noqa: BLE001
            row.attempts += 1
            row.last_error = str(exc)[:1000]
            if row.attempts >= MAX_ATTEMPTS:
                row.status = "failed"
                log.error("Publicacao %s falhou definitivamente: %s", row.id, exc)
            else:
                # Backoff exponencial: 2, 4, 8, 16 minutos.
                row.status = "queued"
                row.scheduled_at = datetime.now(timezone.utc) + timedelta(
                    minutes=2**row.attempts
                )
                log.warning("Publicacao %s falhou (tentativa %d): %s", row.id, row.attempts, exc)
            await db.commit()
            return {"error": str(exc)}


async def autopilot_sweep(ctx) -> dict:
    """Varredura periodica do piloto automatico (contas com auto_pilot=True):
    gera rascunhos novos pra quem esta com a fila de hoje abaixo do teto.
    Pode chamar IA local (minutos por post neste hardware) — por isso roda
    aqui no worker (nao no loop de 30s do scheduler) e com timeout proprio
    (ver WorkerSettings.functions)."""
    async with SessionLocal() as db:
        result = await autopilot.sweep(db)
        if result["created"]:
            log.info("autopilot_sweep: %s", result)
        return result


async def run_retweet(ctx, job_id: int) -> dict:
    async with SessionLocal() as db:
        job = await db.get(RetweetJob, job_id)
        if not job or job.status in ("done", "cancelled"):
            return {"skipped": True}

        account = await db.get(XAccount, job.target_x_account_id)
        if not account or not account.is_active:
            job.status, job.last_error = "failed", "Conta indisponivel"
            await db.commit()
            return {"failed": True}

        try:
            token = await _fresh_access_token(db, account)
            ok = await x_api.retweet(token, account.x_user_id, job.source_tweet_id)
            job.status = "done" if ok else "failed"
            job.retweet_id = job.source_tweet_id if ok else ""
            db.add(
                AuditLog(
                    user_id=job.user_id,
                    action="retweet.executed",
                    entity="retweet_job",
                    entity_id=str(job.id),
                    detail={"account": account.username, "tweet_id": job.source_tweet_id},
                )
            )
            await db.commit()
            log.info("Retweet de %s por @%s", job.source_tweet_id, account.username)
            return {"ok": ok}

        except x_api.CreditsDepleted as exc:
            job.status, job.last_error = "failed", str(exc)
            await db.commit()
            log.error("Retweet %s: conta do X sem creditos", job.id)
            return {"credits_depleted": True}

        except x_api.RateLimited as exc:
            reset = exc.reset_at or datetime.now(timezone.utc) + timedelta(minutes=15)
            job.status, job.scheduled_at = "queued", reset + timedelta(seconds=30)
            await db.commit()
            return {"rate_limited": True}

        except Exception as exc:  # noqa: BLE001
            job.attempts += 1
            job.last_error = str(exc)[:1000]
            if job.attempts >= MAX_ATTEMPTS:
                job.status = "failed"
            else:
                job.status = "queued"
                job.scheduled_at = datetime.now(timezone.utc) + timedelta(minutes=2**job.attempts)
            await db.commit()
            return {"error": str(exc)}


class WorkerSettings:
    functions = [
        collect_account,
        collect_all,
        collect_post_stats,
        publish_scheduled,
        run_retweet,
        # Pode chamar IA local varias vezes em sequencia (minutos cada nesse
        # hardware) — timeout bem mais folgado que o padrao dos demais jobs.
        arq_func(autopilot_sweep, timeout=1800),
    ]
    redis_settings = _redis_settings()
    max_jobs = 10
    job_timeout = 300
