"""Workers Arq: coleta, publicacao e retweet.

Rate limit do X: NUNCA é contornado. Ao receber 429 o job reagenda para depois
do reset informado pela propria API.
"""

import logging
from datetime import datetime, timedelta, timezone

from arq import create_pool
from arq.connections import RedisSettings
from sqlalchemy import select

from app.config import settings
from app.core.security import decrypt, encrypt
from app.db import SessionLocal
from app.models import (
    AuditLog,
    CandidateMedia,
    ContentCandidate,
    MonitoredAccount,
    RetweetJob,
    ScheduledPost,
    SourcePost,
    XAccount,
)
from app.services import scoring, sources, x_api, x_web
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


async def enqueue(function: str, *args) -> None:
    """Helper usado pelas rotas da API."""
    pool = await create_pool(_redis_settings())
    try:
        await pool.enqueue_job(function, *args)
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


async def collect_account(ctx, account_id: int) -> dict:
    async with SessionLocal() as db:
        account = await db.get(MonitoredAccount, account_id)
        if not account or not account.is_active:
            return {"skipped": True}

        log.info("Coletando fonte @%s (%s)", account.username, account.source_type)
        provider = sources.get_provider(account.source_type)
        try:
            items = await provider.fetch_new(db, account)
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
            db.add(
                SourcePost(
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
                    original_url=item["original_url"],
                    content_hash=content_hash(item["text"]),
                    score=score,
                    score_breakdown=breakdown,
                )
            )
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
    """Caminhos locais das midias publicaveis, na ordem definida pelo usuario.

    Midia de terceiro (origin='source_reference') e' descartada aqui tambem —
    mesma trava do caminho da API.
    """
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


async def publish_scheduled(ctx, scheduled_id: int) -> dict:
    async with SessionLocal() as db:
        row = await db.get(ScheduledPost, scheduled_id)
        if not row or row.status in ("published", "cancelled"):
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
    functions = [collect_account, collect_all, publish_scheduled, run_retweet]
    redis_settings = _redis_settings()
    max_jobs = 10
    job_timeout = 120
