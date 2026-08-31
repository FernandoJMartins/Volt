"""Coleta de posts de contas monitoradas.

O caminho padrao (e unico usado pela interface) e' o NAVEGADOR — gratis,
sem a API oficial do X. O provedor XApiProvider existe apenas como legado
inativo; a UI nao oferece mais a API oficial.
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import decrypt
from app.models import MediaAsset, MonitoredAccount, SourcePost, XAccount
from app.services import x_api, x_web
from app.services.browser import SessionExpired, manager as browser_manager
from app.services.storage import classify, storage

log = logging.getLogger("worker")

# Limites da quantidade de posts por coleta (a interface respeita o mesmo teto).
MAX_COLLECT_POSTS = 100
DEFAULT_COLLECT_POSTS = 15


def clamp_collect_count(value: int | None) -> int:
    """Quantidade de posts por coleta, limitada a [1, MAX_COLLECT_POSTS]."""
    if value is None:
        return DEFAULT_COLLECT_POSTS
    return max(1, min(int(value), MAX_COLLECT_POSTS))


class SourceProvider(ABC):
    @abstractmethod
    async def fetch_new(
        self, db: AsyncSession, account: MonitoredAccount, max_posts: int = 15
    ) -> list[dict]:
        """Retorna posts normalizados. O chamador deduplica por x_post_id."""


class XApiProvider(SourceProvider):
    """Legado inativo (API oficial e' paga por post lido). Usa since_id para nao
    repagar posts ja' lidos; a interface atual nao o oferece mais."""

    async def fetch_new(
        self, db: AsyncSession, account: MonitoredAccount, max_posts: int = 15
    ) -> list[dict]:
        token_row = (
            await db.execute(
                select(XAccount).where(
                    XAccount.user_id == account.user_id, XAccount.is_active.is_(True)
                )
            )
        ).scalars().first()
        if not token_row or not account.x_user_id:
            return []

        access_token = decrypt(token_row.access_token_encrypted)
        if not access_token:
            log.warning("Fonte @%s: conta do X sem token valido. Reconecte via OAuth.", account.username)
            return []

        # A API de timeline exige o id numerico. Resolve na primeira coleta e guarda.
        if not account.x_user_id:
            profile = await x_api.get_user_by_username(access_token, account.username)
            if not profile.get("id"):
                log.warning("Fonte @%s: usuario nao encontrado na API do X.", account.username)
                return []
            account.x_user_id = profile["id"]
            account.display_name = profile.get("name", account.display_name)
            await db.commit()
            log.info("Fonte @%s resolvida para id %s", account.username, account.x_user_id)

        raw = await x_api.fetch_user_timeline(
            access_token, account.x_user_id, since_id=account.last_seen_post_id
        )
        out = []
        for tweet in raw:
            metrics = tweet.get("public_metrics", {})
            out.append(
                {
                    "x_post_id": tweet["id"],
                    "text": tweet.get("text", ""),
                    "author_username": account.username,
                    "posted_at": _parse_ts(tweet.get("created_at")),
                    "likes": metrics.get("like_count", 0),
                    "reposts": metrics.get("retweet_count", 0),
                    "replies": metrics.get("reply_count", 0),
                    "views": metrics.get("impression_count", 0),
                    "has_media": bool(tweet.get("attachments")),
                    "original_url": f"https://x.com/{account.username}/status/{tweet['id']}",
                }
            )
        return out


def _parse_ts(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def _reader_account(db: AsyncSession, user_id: int) -> XAccount | None:
    """Escolhe uma conta logada (sessao valida) para navegar e ler os perfis.

    A leitura via navegador exige estar logado; usamos a primeira conta do usuario
    com sessao valida como "leitora". Isolamento e' preservado: a coleta abre o
    contexto isolado dessa conta, nunca de outra.
    """
    return (
        await db.execute(
            select(XAccount).where(
                XAccount.user_id == user_id,
                XAccount.is_active.is_(True),
                XAccount.session_valid.is_(True),
            ).order_by(XAccount.id)
        )
    ).scalars().first()


_MIME_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


async def _download_post_media(
    db: AsyncSession, page, user_id: int, post: dict, budget: list[int]
) -> None:
    """Baixa as imagens do post para a biblioteca como 'source_reference'.

    IDEMPOTENTE por fora: o chamador pula posts ja' coletados (already_seen) —
    nunca rebaixamos a midia de um post que ja' entrou. Midia de terceiro NAO
    publica (guarda legal do MediaAsset): existe como referencia visual.
    """
    urls = (post.get("media_metadata") or {}).get("images") or []
    urls = urls[: min(4, max(budget[0], 0))]

    async def grab(i: int, url: str) -> int | None:
        try:
            resp = await page.request.get(url, timeout=15_000)
            if not resp.ok:
                return None
            mime = (resp.headers.get("content-type") or "image/jpeg").split(";")[0]
            data = await resp.body()
            kind = classify(mime, len(data))
            key = storage.save(
                user_id, f"src-{post['x_post_id']}-{i}.{_MIME_EXT.get(mime, 'jpg')}", data
            )
            asset = MediaAsset(
                user_id=user_id,
                filename=f"src-{post['x_post_id']}-{i}",
                storage_key=key,
                mime_type=mime,
                size_bytes=len(data),
                kind=kind,
                origin="source_reference",
            )
            db.add(asset)
            await db.flush()
            return asset.id
        except Exception as exc:  # noqa: BLE001
            log.warning("Midia do post %s nao baixada (%s)", post["x_post_id"], exc)
            return None

    results = await asyncio.gather(*(grab(i, u) for i, u in enumerate(urls)))
    asset_ids = [r for r in results if r is not None]
    if asset_ids:
        budget[0] -= len(asset_ids)
        post["media_metadata"]["assets"] = asset_ids


class PlaywrightProvider(SourceProvider):
    """Coleta via navegador (sem API oficial, sem custo por post lido)."""

    async def fetch_new(
        self, db: AsyncSession, account: MonitoredAccount, max_posts: int = 15
    ) -> list[dict]:
        reader = await _reader_account(db, account.user_id)
        if reader is None:
            log.warning(
                "Fonte @%s: nenhuma conta com sessao valida para ler. Faca login numa conta.",
                account.username,
            )
            return []

        try:
            async with browser_manager.session(reader) as (page, _ctx):
                if not await x_web.is_logged_in(page):
                    reader.session_valid = False
                    await db.commit()
                    raise SessionExpired(f"Conta leitora @{reader.username} deslogou.")
                # Sem since_id: a coleta le os ultimos `max_posts` e quem deduplica
                # e' o chamador (already_seen). Assim aumentar a quantidade puxa
                # posts mais antigos sem duplicar os que ja' entraram.
                posts = await x_web.fetch_timeline(
                    page, account.username, max_posts=clamp_collect_count(max_posts)
                )
                # Baixa a midia do perfil (imagens) como referencia — mesmo
                # contexto do navegador (cookies/referer do X). Posts ja'
                # coletados nao rebaixam midia (idempotencia).
                budget = [min(clamp_collect_count(max_posts) * 4, 48)]
                for post in posts:
                    if await already_seen(db, post["x_post_id"]):
                        continue
                    await _download_post_media(db, page, account.user_id, post, budget)
            # Persiste o storage_state renovado da conta leitora.
            await db.commit()
        except SessionExpired as exc:
            log.warning("Coleta de @%s: %s", account.username, exc)
            return []

        for post in posts:
            post.setdefault("author_username", account.username)
        return posts


_X_API = XApiProvider()
_WEB = PlaywrightProvider()


def get_provider(source_type: str | None = None) -> SourceProvider:
    """Seleciona o provider. Padrao definido por SOURCE_MODE (hoje: 'web')."""
    mode = source_type or settings.SOURCE_MODE
    if mode == "x_api":
        return _X_API
    return _WEB


async def already_seen(db: AsyncSession, x_post_id: str) -> bool:
    found = await db.execute(select(SourcePost.id).where(SourcePost.x_post_id == x_post_id))
    return found.scalar_one_or_none() is not None
