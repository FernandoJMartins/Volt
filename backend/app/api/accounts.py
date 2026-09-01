"""Contas do X conectadas.

Dois metodos de autenticacao convivem:
  - "browser": sessao por cookies importados do navegador do usuario
    (exporte no navegador local e cole no painel — storage_state salvo
    criptografado). Metodo padrao: o X bloqueia login pelo IP do servidor.
  - "oauth":   API 2.0 PKCE oficial (legado, mantido intacto).
Nunca usuario+senha automatico.
"""

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.deps import current_user
from app.core.security import decrypt, encrypt
from app.db import get_db
from app.models import AuditLog, User, XAccount
from app.services import x_api, x_web
from app.services.browser import manager as browser_manager, parse_proxy, wrap_state
from app.services.cookies import CookieImportError, has_auth_token, parse_cookie_dump

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
    # Proxy dedicado (http(s)://user:pass@host:port ou socks5://...). String
    # vazia remove o proxy da conta (volta a sair pelo IP do servidor).
    proxy_url: str | None = None


def _proxy_host(acc: XAccount) -> str:
    """So o host:porta, pra UI confirmar sem reexibir credenciais."""
    if not acc.proxy_url_encrypted:
        return ""
    try:
        proxy = parse_proxy(decrypt(acc.proxy_url_encrypted))
    except Exception:  # noqa: BLE001
        return ""
    return proxy["server"].split("://", 1)[-1] if proxy else ""


def _serialize(acc: XAccount) -> dict:
    """Nunca expoe tokens nem credenciais de proxy."""
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
        "has_proxy": bool(acc.proxy_url_encrypted),
        "proxy_host": _proxy_host(acc),
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


# ---------------- Importacao de cookies (metodo padrao) ----------------


class CookieImportBody(BaseModel):
    """Despejo de cookies colado pelo usuario. Nunca e' logado nem devolvido."""

    cookies_text: str = Field(max_length=2_000_000)


async def _import_cookies_into(
    account: XAccount, cookies_text: str, db: AsyncSession
) -> dict:
    """Parseia, salva criptografado e valida a sessao no X (headless, rapido).

    SUBSTITUI a sessao anterior da conta — importar cookies e' um re-login, nao um
    merge. Se os cookies estiverem mortos, a conta fica com session_valid=False
    (mesmo que antes estivesse valida).

    Levanta CookieImportError (vira 400) antes de qualquer efeito colateral.
    """
    state = parse_cookie_dump(cookies_text)
    if not has_auth_token(state):
        log.warning(
            "Conta %s: importacao sem cookie auth_token (sessao provavelmente nao vale)",
            account.id,
        )

    account.session_state_encrypted = wrap_state(account.id, state)
    account.session_updated_at = datetime.now(timezone.utc)

    # Valida de verdade: abre o contexto SEMEADO com os cookies importados e
    # confere identidade no proprio x.com. Tudo com timeout fechado — importacao
    # nunca pode pendurar a request indefinidamente.
    valid = False
    identity: dict = {}
    try:
        async with browser_manager.session(account) as (page, _ctx):
            try:
                await page.goto(
                    f"{x_web.BASE}/home", wait_until="domcontentloaded", timeout=20_000
                )
            except Exception:  # noqa: BLE001
                pass  # mesmo sem carregar a home, o cookie pode existir e valer
            valid = await x_web.is_logged_in(page)
            if "/login" in page.url:
                # X redireciona deslogados de /home para /login: cookie presente
                # mas morto. Nao marque a sessao como valida nesse caso.
                valid = False
            if valid:
                try:
                    identity = await asyncio.wait_for(x_web.resolve_identity(page), timeout=30)
                except Exception:  # noqa: BLE001
                    identity = {}
    except Exception:  # noqa: BLE001
        log.exception("Falha ao validar cookies importados da conta %s", account.id)
        valid = False

    account.session_valid = valid
    if identity and identity.get("username"):
        account.username = identity["username"]
    if identity and identity.get("x_user_id"):
        # Unicidade parcial (user_id, x_user_id): se o id resolvido ja pertence a
        # outra conta do mesmo usuario, mantem o placeholder em vez de explodir.
        dup = await db.execute(
            select(XAccount.id).where(
                XAccount.user_id == account.user_id,
                XAccount.x_user_id == identity["x_user_id"],
                XAccount.id != account.id,
            )
        )
        if dup.first() is None:
            account.x_user_id = identity["x_user_id"]
        else:
            log.warning(
                "Conta %s: identidade %s ja pertence a outra conta do usuario; "
                "x_user_id mantido",
                account.id,
                identity["x_user_id"],
            )

    db.add(
        AuditLog(
            user_id=account.user_id,
            action="x_account.cookies_import",
            entity="x_account",
            entity_id=str(account.id),
            detail={"username": account.username, "session_valid": valid},
        )
    )
    await db.commit()
    log.info("Cookies importados conta %s: %s", account.id, "valida" if valid else "invalida")
    return {"session_valid": valid, "username": account.username}


@router.post("/browser/import-cookies")
async def browser_import_cookies(
    body: CookieImportBody, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    """Importa cookies exportados do navegador LOCAL do usuario.

    Quando o X bloqueia o login pelo IP do servidor (datacenter), exporte os
    cookies estando logado no X na SUA maquina (extensao "Get cookies.txt
    LOCALLY" ou equivalente) e cole aqui. Sem noVNC, sem login manual.

    Reutiliza a conta browser pendente do usuario, se houver; senao cria uma.
    """
    account = (
        await db.execute(
            select(XAccount).where(
                XAccount.user_id == user.id,
                XAccount.auth_method == "browser",
                XAccount.x_user_id == "",
            )
        )
    ).scalars().first()

    if account is None:
        account = XAccount(
            user_id=user.id,
            x_user_id="",
            username="(login pendente)",
            auth_method="browser",
            session_valid=False,
        )
        db.add(account)
        await db.commit()

    try:
        result = await _import_cookies_into(account, body.cookies_text, db)
    except CookieImportError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return {**result, "account": _serialize(account)}


@router.post("/{account_id}/browser/cookies")
async def browser_import_cookies_into(
    account_id: int,
    body: CookieImportBody,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Importa cookies numa conta existente (sessao expirada, metodo trocado, etc.).

    Substitui a sessao da conta pela sessao dos cookies importados; a conta passa
    a usar o metodo "browser" (os tokens OAuth, se houver, ficam intactos).
    """
    acc = await db.get(XAccount, account_id)
    if not acc or acc.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conta nao encontrada")

    try:
        result = await _import_cookies_into(acc, body.cookies_text, db)
    except CookieImportError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    acc.auth_method = "browser"
    await db.commit()
    return {**result, "account": _serialize(acc)}


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

    # Proxy carrega credencial: nunca vai por setattr direto, sempre criptografado.
    # String vazia = remove o proxy da conta (volta a sair pelo IP do servidor).
    if "proxy_url" in data:
        proxy_url = data.pop("proxy_url").strip()
        if proxy_url:
            try:
                parse_proxy(proxy_url)
            except ValueError as exc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
            acc.proxy_url_encrypted = encrypt(proxy_url)
        else:
            acc.proxy_url_encrypted = ""

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
