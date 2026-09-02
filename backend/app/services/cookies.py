"""Parsing de despejo de cookies (cookies.txt / JSON) para storage_state do Playwright.

Motivo de existir
-----------------
O X costuma bloquear login a partir do IP do servidor ("Limitamos temporariamente
seu acesso"). A saida pratica e' o usuario exportar os cookies da conta no
navegador DA MAQUINA DELE (IP residencial, onde o login ja' funcionou) e importar
aqui. O estado salvo passa a ser identico ao de um login headed, sem o servidor
precisar logar.

Formatos aceitos (autodetectados pela primeira linha):
  - Netscape cookies.txt (extensao "Get cookies.txt LOCALLY" e afins), incluindo
    linhas "#HttpOnly_" e linhas de comentario.
  - JSON: lista de cookies (estilo EditThisCookie / Playwright).
  - JSON: storage_state completo do Playwright ({"cookies": [...], "origins": [...]}).

So' cookies do dominio da PLATAFORMA sendo importada (x.com/twitter.com pro X,
threads.com pro Threads) sao aproveitados; todo o resto e' descartado de
proposito — este modulo nao e' um importador generico, e' um cano estreito que
so' deixa passar o que a camada de navegador deste projeto usa.

Este modulo e' puro (so' stdlib): nenhum processo, banco ou rede envolvido.
"""

import json

# Dominios aceitos por plataforma. Cookies do X costumam vir com dominio
# ".x.com" (host-only quando nao); twitter.com ainda existe como legado.
# threads.com e' o dominio atual do Threads (a Meta migrou de threads.net).
_ALLOWED_SUFFIXES_BY_PLATFORM: dict[str, tuple[str, ...]] = {
    "x": ("x.com", "twitter.com"),
    "threads": ("threads.com", "threads.net"),
}

# Cookie que confirma sessao autenticada, por plataforma.
_AUTH_COOKIE_BY_PLATFORM: dict[str, str] = {
    "x": "auth_token",
    "threads": "sessionid",
}

# Teto de defesa (anti-lixo/anti-abuso), NAO limite do que e' aproveitado: um
# export "all cookies" de um navegador com muitos sites pode passar de 256 KB,
# mas quase tudo sera descartado no filtro de dominio. So' o que ficar (x.com)
# entra no storage_state — portanto 2 MB de teto e' folgado e ainda rejeita lixo.
MAX_DUMP_BYTES = 2 * 1024 * 1024


class CookieImportError(ValueError):
    """Despejo ilegivel ou sem nenhum cookie do X aproveitavel."""


def _domain_allowed(domain: str, platform: str) -> bool:
    d = (domain or "").strip().lower().lstrip(".")
    suffixes = _ALLOWED_SUFFIXES_BY_PLATFORM.get(platform, ())
    return any(d == suffix or d.endswith("." + suffix) for suffix in suffixes)


def _same_site_of(raw: dict, secure: bool) -> str:
    value = raw.get("sameSite") or raw.get("SameSite")
    if value in ("Strict", "Lax", "None"):
        return value
    # Formatos sem sameSite (Netscape, EditThisCookie antigo): cookies de sessao
    # seguros do X precisam de "None" para voltarem em request cross-site.
    return "None" if secure else "Lax"


def _to_pw_cookie(raw: dict, platform: str) -> dict | None:
    """Normaliza um cookie dict (qualquer dialeto) para o formato do Playwright.

    Devolve None quando o cookie nao presta (sem nome/valor ou dominio fora da plataforma).
    """
    name = raw.get("name")
    value = raw.get("value")
    if not isinstance(name, str) or not name or value is None or value == "":
        return None
    domain = str(raw.get("domain") or "").strip().lower()
    if not _domain_allowed(domain, platform):
        return None
    if not domain.startswith("."):
        domain = "." + domain

    path = raw.get("path")
    if not isinstance(path, str) or not path:
        path = "/"

    # Playwright usa segundos (float); EditThisCookie usa expirationDate; 0/-1/None
    # = cookie de sessao. Netscape com expiracao invalida vira sessao tambem.
    expires = raw.get("expires")
    if expires is None:
        expires = raw.get("expirationDate", -1)
    try:
        expires = float(expires) if expires not in (None, "", 0) else -1
    except (TypeError, ValueError):
        expires = -1

    secure = bool(raw.get("secure") or raw.get("Secure") or False)
    http_only = bool(raw.get("httpOnly") or raw.get("HttpOnly") or False)
    return {
        "name": name,
        "value": str(value),
        "domain": domain,
        "path": path,
        "expires": expires,
        "httpOnly": http_only,
        "secure": secure,
        "sameSite": _same_site_of(raw, secure),
    }


def _parse_netscape(text: str, platform: str) -> list[dict]:
    """Linhas `domain  flag  path  secure  expiry  name  value` (tab-separadas).

    Extensoes de exportacao marcam cookies httpOnly com o prefixo `#HttpOnly_`;
    demais linhas iniciadas por '#' sao comentarios. Tudo passa pela mesma
    normalizacao dos JSONs (`_to_pw_cookie`) para o dialeto do Playwright.
    """
    cookies: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        http_only = line.startswith("#HttpOnly_")
        if http_only:
            line = line[len("#HttpOnly_") :].strip()
        parts = line.split("\t")
        if len(parts) != 7:
            continue
        domain, _flag, path, secure_flag, expiry, name, value = parts
        if not name or not value:
            continue
        norm = _to_pw_cookie(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": path,
                # expirationDate: _to_pw_cookie aceita o dialeto EditThisCookie;
                # -1 quando for cookie de sessao (expiry vazio ou "0").
                "expirationDate": float(expiry) if expiry not in ("", "0") else -1,
                "httpOnly": http_only,
                "secure": secure_flag.strip().upper() == "TRUE",
            },
            platform,
        )
        if norm:
            cookies.append(norm)
    return cookies


def _looks_like_cookie(data: dict) -> bool:
    return "name" in data and ("value" in data or "Value" in data)


def _parse_json(text: str, platform: str) -> tuple[list[dict], list[dict]]:
    data = json.loads(text)
    cookies_raw: object
    origins_raw: object = []
    if isinstance(data, dict):
        cookies_raw = data.get("cookies")
        if cookies_raw is None and _looks_like_cookie(data):
            cookies_raw = [data]  # um unico cookie solto
        origins_raw = data.get("origins") or []
    elif isinstance(data, list):
        cookies_raw = data
    else:
        raise CookieImportError(
            "JSON inesperado: esperava uma lista de cookies ou um storage_state do Playwright"
        )
    if not isinstance(cookies_raw, list):
        raise CookieImportError("campo 'cookies' do JSON nao e' uma lista")
    cookies = []
    for item in cookies_raw:
        if not isinstance(item, dict):
            continue
        norm = _to_pw_cookie(item, platform)
        if norm:
            cookies.append(norm)
    return cookies, origins_raw if isinstance(origins_raw, list) else []


def _filter_origins(origins: list, platform: str) -> list[dict]:
    """Mantem so' localStorage de origens da plataforma; o resto nao entra no estado."""
    kept: list[dict] = []
    for entry in origins:
        if not isinstance(entry, dict):
            continue
        origin = str(entry.get("origin") or "")
        host = origin.split("://")[-1].split("/")[0].split(":")[0].lower()
        if _domain_allowed(host, platform):
            kept.append(entry)
    return kept


def parse_cookie_dump(text: str, platform: str = "x") -> dict:
    """Converte o despejo colado pelo usuario em storage_state do Playwright.

    `platform` decide o dominio aceito ("x" ou "threads" — ver
    _ALLOWED_SUFFIXES_BY_PLATFORM). Qualquer outra coisa e' descartada.
    Levanta `CookieImportError` (vira HTTP 400) quando nada e' aproveitavel.
    """
    if platform not in _ALLOWED_SUFFIXES_BY_PLATFORM:
        raise CookieImportError(f"plataforma desconhecida: {platform!r}")
    if not text or not text.strip():
        raise CookieImportError("despejo de cookies vazio")
    if len(text.encode("utf-8")) > MAX_DUMP_BYTES:
        domains = "/".join(_ALLOWED_SUFFIXES_BY_PLATFORM[platform])
        raise CookieImportError(
            f"despejo muito grande (max {MAX_DUMP_BYTES // (1024 * 1024)} MB) — "
            f"exporte apenas os cookies de {domains}; cookies de outros sites sao "
            "descartados de qualquer forma"
        )

    stripped = text.strip()
    if stripped.startswith(("{", "[")):
        cookies, origins = _parse_json(stripped, platform)
    else:
        cookies, origins = _parse_netscape(stripped, platform), []

    if not cookies:
        domains = "/".join(_ALLOWED_SUFFIXES_BY_PLATFORM[platform])
        raise CookieImportError(
            f"nenhum cookie de {domains} encontrado — exporte os cookies estando "
            "logado (extensao 'Get cookies.txt LOCALLY' ou equivalente)"
        )

    # Desduplica por (domain, name, path) mantendo a ultima ocorrencia.
    seen: dict[tuple, int] = {}
    unique: list[dict] = []
    for cookie in cookies:
        key = (cookie["domain"], cookie["name"], cookie["path"])
        if key in seen:
            unique[seen[key]] = cookie
        else:
            seen[key] = len(unique)
            unique.append(cookie)

    return {"cookies": unique, "origins": _filter_origins(origins, platform)}


def has_auth_token(state: dict, platform: str = "x") -> bool:
    """O cookie de sessao que autentica requests na plataforma (auth_token no
    X, sessionid no Threads)."""
    cookie_name = _AUTH_COOKIE_BY_PLATFORM.get(platform, "")
    return any(
        c.get("name") == cookie_name and c.get("value")
        for c in state.get("cookies", [])
    )
