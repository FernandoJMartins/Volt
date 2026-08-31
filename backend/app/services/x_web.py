"""Operacoes sobre x.com via navegador (Playwright), sem API oficial.

Sao *page-drivers* puros: recebem uma `Page` ja` dentro de um contexto isolado
(ver `browser.BrowserManager.session`) e nao sabem nada de banco. Quem abre e
fecha a sessao — e portanto quem salva o storage_state — e' o chamador.

AVISO DE MANUTENCAO: os seletores `data-testid` abaixo sao a superficie fragil
deste modulo. O X muda o DOM sem aviso; quando a coleta/publicacao quebrar, e'
aqui que se ajusta. Concentrei todos num so lugar (`SEL`) de proposito.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone

from playwright.async_api import Page, TimeoutError as PWTimeout

log = logging.getLogger("x_web")

BASE = "https://x.com"

# ---- Seletores (a unica parte que costuma mudar quando o X atualiza o site) ----
SEL = {
    "tweet": 'article[data-testid="tweet"]',
    "tweet_text": '[data-testid="tweetText"]',
    "status_link": 'a[href*="/status/"]',
    "photo": '[data-testid="tweetPhoto"]',
    "video": 'video',
    "composer_box": '[data-testid="tweetTextarea_0"]',
    "file_input": 'input[data-testid="fileInput"]',
    "post_button": '[data-testid="tweetButton"]',
    "compose_url": f"{BASE}/compose/post",
}

_STATUS_RE = re.compile(r"/status/(\d+)")
_NUM_RE = re.compile(r"([\d.,]+)\s*([KMkm]?)")


async def is_logged_in(page: Page) -> bool:
    """Autenticado == existe o cookie auth_token no contexto."""
    cookies = await page.context.cookies("https://x.com")
    return any(c["name"] == "auth_token" and c["value"] for c in cookies)


async def resolve_identity(page: Page) -> dict:
    """Le @username e o id numerico da conta logada, via API interna do proprio site.

    Prefere verify_credentials (tem id_str + screen_name); cai para settings.json
    (so username) se a primeira falhar.
    """
    result: dict | None = None
    try:
        result = await page.evaluate(
            """async () => {
                const r = await fetch('/i/api/1.1/account/verify_credentials.json', {
                    headers: {'x-twitter-active-user': 'yes'},
                    credentials: 'include',
                });
                if (!r.ok) return null;
                const j = await r.json();
                return { username: j.screen_name || '', x_user_id: String(j.id_str || '') };
            }"""
        )
    except Exception:  # noqa: BLE001
        result = None

    if not result or not result.get("username"):
        try:
            result = await page.evaluate(
                """async () => {
                    const r = await fetch('/i/api/1.1/account/settings.json', {
                        headers: {'x-twitter-active-user': 'yes'},
                        credentials: 'include',
                    });
                    if (!r.ok) return null;
                    const j = await r.json();
                    return { username: j.screen_name || '' };
                }"""
            )
        except Exception:  # noqa: BLE001
            result = None

    if not result or not result.get("username"):
        # Plano B sem API interna: o link do proprio perfil na barra de navegacao
        # (data-testid="AppTabBar_Profile_Link") aponta para /<username>. Funciona
        # mesmo quando verify_credentials/settings.json respondem 403 (IP datacenter).
        # Espera o app renderizar a barra antes de ler — logo apos domcontentloaded
        # o DOM ainda nao tem o link (corrida real vista em producao).
        try:
            await page.wait_for_selector(
                'a[data-testid="AppTabBar_Profile_Link"]', timeout=8_000
            )
            username = await page.evaluate(
                """() => {
                    const el = document.querySelector(
                        'a[data-testid="AppTabBar_Profile_Link"]'
                    );
                    const href = el && el.getAttribute('href');
                    if (!href) return null;
                    const name = href.split('/').filter(Boolean).pop();
                    return name || null;
                }"""
            )
            if username:
                result = {"username": username}
        except Exception:  # noqa: BLE001
            pass
    return result or {}


def _parse_count(label: str | None) -> int:
    """"1,234", "12.3K", "2M" -> inteiro. Aria-labels do X vem nesse formato."""
    if not label:
        return 0
    match = _NUM_RE.search(label)
    if not match:
        return 0
    raw, unit = match.group(1), match.group(2).upper()
    if unit in ("K", "M"):
        # Com sufixo, o ponto e' decimal (12.3K = 12.300): remove so' os milhares.
        value = float(raw.replace(",", "")) * (1_000 if unit == "K" else 1_000_000)
    else:
        # Sem sufixo, ponto e virgula sao separadores de milhar (1.234 / 1,234).
        value = float(raw.replace(",", "").replace(".", "") or 0)
    return int(value)


def dedup_media_urls(urls: list[str], limit: int = 4) -> list[str]:
    """Remove duplicatas da MESMA midia (mesmo path sem querystring), preservando
    a ordem e limitando a quantidade. Logica pura — testavel sem navegador."""
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        key = url.split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        out.append(url)
        if len(out) >= limit:
            break
    return out


async def _extract_media_urls(article) -> dict:
    """Urls de midia do post: imagens (ate 4) e poster do video.

    O X serve a mesma imagem em varias resolucoes via query — deduplicamos pela
    url base. Video em si (MSE/blob) nao da' para baixar de forma estavel; o
    poster (thumbnail) representa a midia visual do video.
    """
    images: list[str] = []
    for img in await article.query_selector_all("img"):
        src = (await img.get_attribute("src")) or ""
        if "twimg.com" not in src or "/media/" not in src:
            continue
        # Normaliza para resolucao media (o DOM entrega name=small por padrao).
        images.append(f"{src.split('?')[0]}?format=jpg&name=medium")
    images = dedup_media_urls(images, limit=4)

    poster = ""
    video = await article.query_selector(SEL["video"])
    if video:
        poster = (await video.get_attribute("poster")) or ""
        if poster and "twimg.com" in poster:
            images.append(poster)
            images = dedup_media_urls(images, limit=4)
    return {"images": images, "video_poster": poster}


async def _extract_tweet(article) -> dict | None:
    """Extrai um post do DOM. Retorna None se nao der pra identificar o id."""
    link = await article.query_selector(SEL["status_link"])
    href = await link.get_attribute("href") if link else None
    match = _STATUS_RE.search(href or "")
    if not match:
        return None
    status_id = match.group(1)

    text_el = await article.query_selector(SEL["tweet_text"])
    text = (await text_el.inner_text()) if text_el else ""

    async def metric(testid: str) -> int:
        el = await article.query_selector(f'[data-testid="{testid}"]')
        return _parse_count(await el.get_attribute("aria-label")) if el else 0

    has_photo = await article.query_selector(SEL["photo"]) is not None
    has_video = await article.query_selector(SEL["video"]) is not None
    media = await _extract_media_urls(article)

    time_el = await article.query_selector("time")
    dt_attr = await time_el.get_attribute("datetime") if time_el else None

    return {
        "x_post_id": status_id,
        "text": text,
        "likes": await metric("like"),
        "reposts": await metric("retweet"),
        "replies": await metric("reply"),
        "views": 0,  # views nao vem de forma estavel no DOM; fica 0 nesta camada
        "has_media": has_photo or has_video,
        "posted_at": _parse_iso(dt_attr),
        "media_metadata": {
            "photo": has_photo,
            "video": has_video,
            "images": media["images"],
            "video_poster": media["video_poster"],
        },
    }


def _parse_iso(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


async def fetch_timeline(
    page: Page, username: str, since_id: str = "", max_posts: int = 15
) -> list[dict]:
    """Le os posts recentes de @username. Para ao alcancar `since_id`.

    Exige sessao autenticada (perfis so aparecem logado). Sem custo por post —
    e' navegacao normal, ao contrario da API oficial.
    """
    handle = username.lstrip("@")
    await page.goto(f"{BASE}/{handle}", wait_until="domcontentloaded")
    try:
        await page.wait_for_selector(SEL["tweet"], timeout=15000)
    except PWTimeout:
        log.warning("@%s: nenhum tweet carregou (perfil protegido/inexistente?).", handle)
        return []

    seen: set[str] = set()
    out: list[dict] = []
    stalls = 0
    while len(out) < max_posts and stalls < 4:
        articles = await page.query_selector_all(SEL["tweet"])
        before = len(out)
        for article in articles:
            data = await _extract_tweet(article)
            if not data or data["x_post_id"] in seen:
                continue
            seen.add(data["x_post_id"])
            if since_id and data["x_post_id"] <= since_id:
                return out  # alcancou o ultimo ja visto; nada novo alem daqui
            data["author_username"] = handle
            data["original_url"] = f"{BASE}/{handle}/status/{data['x_post_id']}"
            out.append(data)
            if len(out) >= max_posts:
                break
        stalls = stalls + 1 if len(out) == before else 0
        await page.mouse.wheel(0, 2400)
        await asyncio.sleep(1.2)
    return out


async def publish(page: Page, text: str, media_paths: list[str] | None = None) -> str:
    """Publica um post e devolve o id (best-effort). Levanta em caso de falha."""
    await page.goto(SEL["compose_url"], wait_until="domcontentloaded")
    box = await page.wait_for_selector(SEL["composer_box"], timeout=15000)
    await box.click()
    await box.type(text, delay=15)

    if media_paths:
        file_input = await page.wait_for_selector(SEL["file_input"], timeout=10000, state="attached")
        await file_input.set_input_files(media_paths)
        # Espera o preview subir antes de habilitar o botao.
        await asyncio.sleep(3)

    button = await page.wait_for_selector(SEL["post_button"], timeout=10000)
    await button.click()

    # Confirma pela navegacao/toast e tenta capturar o id do post recem-criado.
    await asyncio.sleep(3)
    return await _last_status_id(page)


async def _last_status_id(page: Page) -> str:
    """Melhor esforco: le o id do post no primeiro link de status apos publicar."""
    try:
        await page.goto(f"{BASE}/home", wait_until="domcontentloaded")
        link = await page.query_selector(SEL["status_link"])
        href = await link.get_attribute("href") if link else ""
        match = _STATUS_RE.search(href or "")
        return match.group(1) if match else ""
    except Exception:  # noqa: BLE001
        return ""
