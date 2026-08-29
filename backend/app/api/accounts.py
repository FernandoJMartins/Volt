"""Contas do X conectadas.

Dois metodos de autenticacao convivem:
  - "browser": login headed uma vez, storage_state salvo criptografado (padrao).
  - "oauth":   API 2.0 PKCE oficial (legado, mantido intacto).
Nunca usuario+senha automatico.
"""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.deps import current_user
from app.core.security import encrypt
from app.db import SessionLocal, get_db
from app.models import AuditLog, User, XAccount
from app.services import x_api, x_web
from app.services.browser import manager as browser_manager

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/x/accounts", tags=["x-accounts"])

# state -> (user_id, code_verifier). Em producao multi-instancia, mover para Redis.
_PENDING: dict[str, tuple[int, str]] = {}


class AccountSettings(BaseModel):
    display_name: str | None = None
    persona_prompt: str | None = None
    timezone: str | None = None
    is_active: bool | None = None
    is_sensitive: bool | None = None
    posts_per_day: int | None = None
    window_start: str | None = None
    window_end: str | None = None
    min_interval_minutes: int | None = None
    categories: list[str] | None = None


def _serialize(acc: XAccount) -> dict:
    """Nunca expoe tokens."""
    return {
        "id": acc.id,
        "x_user_id": acc.x_user_id,
        "username": acc.username,
        "display_name": acc.display_name,
        "avatar_url": acc.avatar_url,
        "timezone": acc.timezone,
        "is_active": acc.is_active,
        "is_sensitive": acc.is_sensitive,
        "persona_prompt": acc.persona_prompt,
        "categories": acc.categories or [],
        "posts_per_day": acc.posts_per_day,
        "window_start": acc.window_start,
        "window_end": acc.window_end,
        "min_interval_minutes": acc.min_interval_minutes,
        "auth_method": acc.auth_method,
        "session_valid": acc.session_valid,
        "session_updated_at": acc.session_updated_at.isoformat() if acc.session_updated_at else None,
        "connected": bool(acc.access_token_encrypted) or acc.session_valid,
    }


@router.get("")
async def list_accounts(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(XAccount).where(XAccount.user_id == user.id).order_by(XAccount.id)
        )
    ).scalars().all()
    return [_serialize(a) for a in rows]


# ---------------- Login via navegador (metodo padrao) ----------------


async def _run_browser_login(account_id: int) -> None:
    """Task de fundo: abre um navegador VISIVEL no contexto isolado desta conta,
    espera o login manual (captcha/2FA na mao) e salva o storage_state.

    Roda com sessao de banco propria — nao compartilha a da request.
    """
    async with SessionLocal() as db:
        account = await db.get(XAccount, account_id)
        if account is None:
            return
        try:
            async with browser_manager.session(account, headed=True) as (page, _ctx):
                ok = await x_web.wait_until_logged_in(page, settings.LOGIN_TIMEOUT_SECONDS)
                if ok:
                    identity = await x_web.resolve_identity(page)
                    if identity.get("username"):
                        account.username = identity["username"]
            # session() ja gravou o storage_state atualizado em account.*
            account.session_valid = ok
            if ok:
                db.add(
                    AuditLog(
                        user_id=account.user_id,
                        action="x_account.browser_login",
                        entity="x_account",
                        entity_id=str(account.id),
                        detail={"username": account.username},
                    )
                )
            await db.commit()
            log.info("Login navegador conta %s: %s", account_id, "ok" if ok else "timeout")
        except Exception:  # noqa: BLE001
            log.exception("Falha no login por navegador da conta %s", account_id)
            account.session_valid = False
            await db.commit()


@router.post("/browser/login")
async def browser_login(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Cria uma conta em modo navegador e dispara o login headed em background.

    Abre uma janela do Chromium NA MAQUINA que roda o worker/API — logue nela e o
    sistema captura a sessao. Consulte o progresso em GET /browser/{id}/status.
    """
    account = XAccount(
        user_id=user.id,
        x_user_id="",
        username="(login pendente)",
        auth_method="browser",
        session_valid=False,
    )
    db.add(account)
    await db.commit()
    asyncio.create_task(_run_browser_login(account.id))
    return {
        "account_id": account.id,
        "status": "waiting_login",
        "connected": False,
        # Abra esta URL, logue no X na janela do servidor; a sessao e' capturada.
        "vnc_url": settings.NOVNC_URL,
    }


@router.get("/browser/{account_id}/status")
async def browser_login_status(
    account_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    acc = await db.get(XAccount, account_id)
    if not acc or acc.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conta nao encontrada")
    return {
        "account_id": acc.id,
        "username": acc.username,
        "session_valid": acc.session_valid,
        "status": "connected" if acc.session_valid else "waiting_login",
    }


@router.post("/{account_id}/browser/relogin")
async def browser_relogin(
    account_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    """Refaz o login de uma conta cuja sessao expirou, no MESMO contexto isolado."""
    acc = await db.get(XAccount, account_id)
    if not acc or acc.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conta nao encontrada")
    asyncio.create_task(_run_browser_login(acc.id))
    return {"account_id": acc.id, "status": "waiting_login", "vnc_url": settings.NOVNC_URL}


@router.post("/connect")
async def connect(user: User = Depends(current_user)):
    if not settings.X_CLIENT_ID:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "X_CLIENT_ID nao configurado. Preencha o .env com as credenciais do developer.x.com",
        )
    url, state, verifier = x_api.build_authorize_url()
    _PENDING[state] = (user.id, verifier)
    return {"authorize_url": url}


@router.get("/callback")
async def callback(request: Request, db: AsyncSession = Depends(get_db)):
    code = request.query_params.get("code")
    state = request.query_params.get("state") or ""
    pending = _PENDING.pop(state, None)
    if not code or not pending:
        return RedirectResponse(f"{settings.FRONTEND_URL}/accounts?error=oauth_state")

    user_id, verifier = pending
    try:
        payload = await x_api.exchange_code(code, verifier)
        access = payload["access_token"]
        profile = await x_api.get_me(access)
    except Exception as exc:  # noqa: BLE001
        log.exception("Falha no OAuth do X")
        return RedirectResponse(f"{settings.FRONTEND_URL}/accounts?error={type(exc).__name__}")

    x_user_id = profile.get("id", "")
    existing = (
        await db.execute(
            select(XAccount).where(XAccount.user_id == user_id, XAccount.x_user_id == x_user_id)
        )
    ).scalars().first()

    account = existing or XAccount(user_id=user_id, x_user_id=x_user_id)
    account.username = profile.get("username", "")
    account.display_name = profile.get("name", "")
    account.avatar_url = profile.get("profile_image_url", "")
    account.access_token_encrypted = encrypt(access)
    account.refresh_token_encrypted = encrypt(payload.get("refresh_token", ""))
    account.token_expires_at = x_api.expires_at(payload)
    if existing is None:
        db.add(account)

    db.add(
        AuditLog(
            user_id=user_id,
            action="x_account.connected",
            entity="x_account",
            entity_id=x_user_id,
            detail={"username": account.username},
        )
    )
    await db.commit()
    return RedirectResponse(f"{settings.FRONTEND_URL}/accounts?connected={account.username}")


@router.patch("/{account_id}")
async def update_account(
    account_id: int,
    body: AccountSettings,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    acc = await db.get(XAccount, account_id)
    if not acc or acc.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conta nao encontrada")

    data = body.model_dump(exclude_none=True)
    # Guarda-corpo anti-spam: nao aceita frequencia absurda.
    if "posts_per_day" in data:
        data["posts_per_day"] = max(1, min(data["posts_per_day"], settings.MAX_POSTS_PER_DAY))
    if "min_interval_minutes" in data:
        data["min_interval_minutes"] = max(settings.MIN_INTERVAL_MINUTES, data["min_interval_minutes"])

    for key, value in data.items():
        setattr(acc, key, value)
    await db.commit()
    return _serialize(acc)


@router.delete("/{account_id}")
async def disconnect(
    account_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    acc = await db.get(XAccount, account_id)
    if not acc or acc.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conta nao encontrada")
    db.add(
        AuditLog(
            user_id=user.id,
            action="x_account.disconnected",
            entity="x_account",
            entity_id=str(account_id),
            detail={"username": acc.username},
        )
    )
    await db.delete(acc)
    await db.commit()
    return {"ok": True}
