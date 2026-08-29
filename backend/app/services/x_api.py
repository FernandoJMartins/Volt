"""Cliente da API oficial do X. OAuth 2.0 PKCE + publicacao + retweet.

Regras: somente API oficial, nunca browser automation, nunca burlar rate limit.
Ao receber 429 o chamador deve aguardar/reagendar — ver RateLimited.
"""

import asyncio
import base64
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings

AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
API = "https://api.x.com/2"

SCOPES = ["tweet.read", "tweet.write", "users.read", "offline.access", "media.write"]


class XApiError(Exception):
    pass


class RateLimited(XApiError):
    def __init__(self, reset_at: datetime | None):
        self.reset_at = reset_at
        super().__init__(f"Rate limit da API do X. Libera em: {reset_at}")


class CreditsDepleted(XApiError):
    """HTTP 402 — conta de desenvolvedor sem creditos.

    Nao adianta repetir: sem creditos novos a proxima tentativa falha igual.
    O worker marca como `failed` na hora, em vez de gastar as 5 tentativas.
    """

    def __init__(self) -> None:
        super().__init__(
            "Conta de desenvolvedor do X sem creditos. Adicione creditos em "
            "developer.x.com (billing) e reagende este post."
        )


def build_authorize_url() -> tuple[str, str, str]:
    """Retorna (url, state, code_verifier). Guarde state+verifier na sessao."""
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)[:128]
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    params = {
        "response_type": "code",
        "client_id": settings.X_CLIENT_ID,
        "redirect_uri": settings.X_CALLBACK_URL,
        "scope": " ".join(SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    query = "&".join(f"{k}={httpx.QueryParams({k: v})[k]}" for k, v in params.items())
    return f"{AUTHORIZE_URL}?{query}", state, verifier


def _basic_auth() -> tuple[str, str]:
    return settings.X_CLIENT_ID, settings.X_CLIENT_SECRET


async def exchange_code(code: str, verifier: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.X_CALLBACK_URL,
                "code_verifier": verifier,
            },
            auth=_basic_auth(),
        )
    if resp.status_code != 200:
        raise XApiError(f"Falha ao trocar code por token: {resp.status_code} {resp.text}")
    return resp.json()


async def refresh_access_token(refresh_token: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            auth=_basic_auth(),
        )
    if resp.status_code != 200:
        raise XApiError(f"Falha ao renovar token: {resp.status_code} {resp.text}")
    return resp.json()


def expires_at(payload: dict) -> datetime | None:
    seconds = payload.get("expires_in")
    if not seconds:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=int(seconds))


def _check(resp: httpx.Response) -> dict:
    if resp.status_code == 402:
        raise CreditsDepleted()
    if resp.status_code == 429:
        reset = resp.headers.get("x-rate-limit-reset")
        reset_at = (
            datetime.fromtimestamp(int(reset), tz=timezone.utc) if reset and reset.isdigit() else None
        )
        raise RateLimited(reset_at)
    if resp.status_code >= 400:
        raise XApiError(f"{resp.status_code}: {resp.text}")
    if not resp.content:
        return {}  # APPEND responde 204 sem corpo
    try:
        return resp.json()
    except ValueError:
        return {}


async def get_me(access_token: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            f"{API}/users/me",
            params={"user.fields": "profile_image_url,name,username"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
    return _check(resp).get("data", {})


async def get_user_by_username(access_token: str, username: str) -> dict:
    """Resolve @username -> id numerico (a API de timeline exige o id, nao o username)."""
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            f"{API}/users/by/username/{username.lstrip('@')}",
            params={"user.fields": "profile_image_url,name,username"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
    return _check(resp).get("data", {})


async def publish_tweet(access_token: str, text: str, media_ids: list[str] | None = None) -> str:
    """Publica e devolve o id do post criado."""
    payload: dict = {"text": text}
    if media_ids:
        payload["media"] = {"media_ids": media_ids}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{API}/tweets",
            json=payload,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    return _check(resp)["data"]["id"]


# ---------------- Upload de midia (API v2; a v1.1 foi descontinuada em 03/2025) ----------------

_CHUNK = 4 * 1024 * 1024  # segmentos devem ficar abaixo de 5MB

_CATEGORY = {"image": "tweet_image", "gif": "tweet_gif", "video": "tweet_video"}


async def upload_media(access_token: str, data: bytes, mime_type: str, kind: str) -> str:
    """Sobe a midia e devolve o media_id para anexar ao post.

    Imagem usa o upload simples; GIF e video usam o fluxo chunked INIT/APPEND/FINALIZE
    com polling de processamento.
    """
    if kind == "image":
        return await _upload_simple(access_token, data, mime_type)
    return await _upload_chunked(access_token, data, mime_type, kind)


async def _upload_simple(access_token: str, data: bytes, mime_type: str) -> str:
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(
            f"{API}/media/upload",
            files={"media": ("upload", data, mime_type)},
            headers={"Authorization": f"Bearer {access_token}"},
        )
    return _check(resp)["data"]["id"]


async def _upload_chunked(access_token: str, data: bytes, mime_type: str, kind: str) -> str:
    """Fluxo chunked da API v2: initialize -> append(N) -> finalize -> status.

    Usa os endpoints REST dedicados (/2/media/upload/initialize etc). A forma antiga
    com `command=INIT` em form-urlencoded é recusada pela v2 com HTTP 400.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    category = _CATEGORY.get(kind, "tweet_video")

    async with httpx.AsyncClient(timeout=180) as client:
        init = await client.post(
            f"{API}/media/upload/initialize",
            json={
                "total_bytes": len(data),
                "media_type": mime_type,
                "media_category": category,
            },
            headers=headers,
        )
        media_id = _check(init)["data"]["id"]

        for index, start_byte in enumerate(range(0, len(data), _CHUNK)):
            chunk = data[start_byte : start_byte + _CHUNK]
            append = await client.post(
                f"{API}/media/upload/{media_id}/append",
                data={"segment_index": str(index)},
                files={"media": ("chunk", chunk, "application/octet-stream")},
                headers=headers,
            )
            _check(append)

        final = await client.post(
            f"{API}/media/upload/{media_id}/finalize", headers=headers
        )
        info = _check(final).get("data", {})

        # Video e GIF sao processados de forma assincrona: espera ficar pronto.
        state = (info.get("processing_info") or {}).get("state")
        waited = 0
        while state in ("pending", "in_progress") and waited < 240:
            delay = max(int((info.get("processing_info") or {}).get("check_after_secs", 5)), 1)
            await asyncio.sleep(delay)
            waited += delay
            status = await client.get(
                f"{API}/media/upload",
                params={"command": "STATUS", "media_id": media_id},
                headers=headers,
            )
            info = _check(status).get("data", {})
            state = (info.get("processing_info") or {}).get("state")

        if state == "failed":
            reason = (info.get("processing_info") or {}).get("error", {}).get("message", "")
            raise XApiError(f"X falhou ao processar a midia: {reason}")

    return media_id


async def fetch_user_timeline(access_token: str, x_user_id: str, since_id: str = "") -> list[dict]:
    """ATENCAO: cada post lido é cobrado (~US$0,005). Use since_id e paginacao minima."""
    params = {
        "max_results": 10,
        "tweet.fields": "created_at,public_metrics,attachments",
        "exclude": "retweets,replies",
    }
    if since_id:
        params["since_id"] = since_id
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(
            f"{API}/users/{x_user_id}/tweets",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    return _check(resp).get("data", [])
