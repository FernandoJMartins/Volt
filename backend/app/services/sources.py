"""Coleta de posts de contas monitoradas via API oficial do X.

ATENCAO: cada post lido é cobrado (~US$0,005). Use since_id e paginacao minima.
Textos proprios do usuario NAO passam por aqui — vao direto para conteudo
(ver `ManualSourceText` e a tela "Meus Textos"), sem custo nenhum.
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import decrypt
from app.models import MonitoredAccount, SourcePost, XAccount
from app.services import x_api, x_web
from app.services.browser import SessionExpired, manager as browser_manager

log = logging.getLogger("worker")


class SourceProvider(ABC):
    @abstractmethod
    async def fetch_new(self, db: AsyncSession, account: MonitoredAccount) -> list[dict]:
        """Retorna posts normalizados ainda nao vistos."""


class XApiProvider(SourceProvider):
    """Coleta real. Usa since_id para nao repagar por posts ja lidos."""

    async def fetch_new(self, db: AsyncSession, account: MonitoredAccount) -> list[dict]:
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


class PlaywrightProvider(SourceProvider):
    """Coleta via navegador (sem API oficial, sem custo por post lido)."""

    async def fetch_new(self, db: AsyncSession, account: MonitoredAccount) -> list[dict]:
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
                posts = await x_web.fetch_timeline(
                    page, account.username, since_id=account.last_seen_post_id
                )
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
