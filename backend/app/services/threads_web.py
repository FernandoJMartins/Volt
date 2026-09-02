"""Operacoes sobre threads.com via navegador (Playwright), sem API oficial.

Mesmo contrato de x_web.py (page-drivers puros, recebem uma `Page` ja' dentro
de um contexto isolado — ver `browser.BrowserManager.session`). Selecionado via
app.services.platform_web.driver_for("threads").

AVISO DE MANUTENCAO: seletores validados manualmente (login por cookie, achar
o proprio perfil, ler o feed, abrir o composer e publicar de verdade) em
2026-09-02. O dominio de cookies e' `.threads.com` (a Meta migrou de
threads.net). O DOM da Meta usa classes ofuscadas/geradas — por isso os
seletores abaixo priorizam role/aria-label/texto visivel em vez de classes.

LIMITACAO CONHECIDA de `fetch_timeline`: legenda de video que aparece
SOBREPOSTA na propria midia (overlay) nao e' capturada por `inner_text()` —
so' texto de post (com ou sem imagem, legenda ABAIXO da midia) sai completo.
Post id, data exata e contadores de curtida/resposta/repost saem sempre
certos, mesmo quando o texto fica vazio. Mesmo limite documentado que o X ja'
tem pra `views` (ver PostStats).
"""

import logging
import re
from datetime import datetime, timezone

from playwright.async_api import Page

log = logging.getLogger("threads_web")

BASE = "https://www.threads.com"

SEL = {
    "compose_trigger": "Postar",
    "compose_url": f"{BASE}/",
    "like_landmark": '[aria-label="Curtir"]',
}

_POST_ID_RE = re.compile(r"/post/([A-Za-z0-9_-]+)")
_NUM_RE = re.compile(r"^[\d.,]+\s*(mil|K|M)?$")


async def is_logged_in(page: Page) -> bool:
    """Autenticado == existe o cookie sessionid no contexto (.threads.com)."""
    cookies = await page.context.cookies(BASE)
    return any(c["name"] == "sessionid" and c["value"] for c in cookies)


async def resolve_identity(page: Page) -> dict:
    """Le @username (via link "/@user" na sidebar) e o id numerico (cookie ds_user_id).

    Ao contrario do X (que precisa de uma chamada a API interna), o Threads
    expoe o id numerico do usuario logado direto no cookie `ds_user_id` — mais
    simples e nao depende do DOM ter renderizado a sidebar.
    """
    username = ""
    platform_user_id = ""
    try:
        cookies = await page.context.cookies(BASE)
        for c in cookies:
            if c["name"] == "ds_user_id" and c["value"]:
                platform_user_id = c["value"]
                break
    except Exception:  # noqa: BLE001
        pass

    try:
        href = await page.locator('a[href^="/@"]').first.get_attribute("href", timeout=8000)
        if href:
            username = href.lstrip("/").lstrip("@")
    except Exception:  # noqa: BLE001
        username = ""

    return {"username": username, "x_user_id": platform_user_id}


def _parse_num(text: str) -> int:
    text = text.strip().lower().replace(",", ".")
    mult = 1
    if text.endswith("mil"):
        mult, text = 1_000, text[:-3].strip()
    elif text.endswith("k"):
        mult, text = 1_000, text[:-1].strip()
    elif text.endswith("m"):
        mult, text = 1_000_000, text[:-1].strip()
    try:
        return int(float(text) * mult)
    except ValueError:
        return 0


def _parse_post_block(raw_text: str) -> dict:
    """Separa {author, text, likes, replies, reposts} do inner_text() do card.

    Formato tipico: `autor\\ntempo relativo\\n[linhas de texto]\\n[ate' 3-4
    linhas numericas: curtidas, respostas, reposts, [compartilhamentos]]`.
    Post sem legenda visivel (ex: video com legenda em overlay — ver limitacao
    no topo do arquivo) devolve text="".
    """
    lines = [ln.strip() for ln in raw_text.split("\n") if ln.strip()]
    author = lines[0] if lines else ""
    rest = lines[2:]  # pula autor + tempo relativo

    counts: list[str] = []
    while rest and _NUM_RE.match(rest[-1]) and len(counts) < 4:
        counts.insert(0, rest.pop())
    # descarta "Traduzir" (link que aparece em posts com texto em outro idioma)
    if rest and rest[-1] == "Traduzir":
        rest.pop()

    nums = [_parse_num(c) for c in counts]
    likes = nums[0] if len(nums) > 0 else 0
    replies = nums[1] if len(nums) > 1 else 0
    reposts = nums[2] if len(nums) > 2 else 0

    return {"author": author, "text": "\n".join(rest).strip(), "likes": likes, "replies": replies, "reposts": reposts}


async def fetch_timeline(page: Page, username: str, since_id: str = "", max_posts: int = 15) -> list[dict]:
    """Le os posts recentes do perfil `username`. Ver limitacao de overlay no
    topo do arquivo — texto pode vir vazio pra alguns posts com video, mas id/
    data/contadores saem sempre certos."""
    await page.goto(f"{BASE}/@{username}", wait_until="domcontentloaded", timeout=30_000)
    await page.wait_for_timeout(2500)

    seen: set[str] = set()
    results: list[dict] = []
    stagnant = 0

    for _ in range(20):  # teto de scrolls de seguranca
        times = page.locator('a[href*="/post/"] time')
        count = await times.count()
        for i in range(count):
            if len(results) >= max_posts:
                break
            time_el = times.nth(i)
            href = await time_el.locator("xpath=..").get_attribute("href") or ""
            match = _POST_ID_RE.search(href)
            if not match:
                continue
            post_id = match.group(1)
            if post_id in seen or post_id == since_id:
                continue
            seen.add(post_id)

            iso = await time_el.get_attribute("datetime") or ""
            try:
                posted_at = datetime.fromisoformat(iso.replace("Z", "+00:00"))
            except ValueError:
                posted_at = datetime.now(timezone.utc)

            card = time_el.locator(f"xpath=ancestor::*[.//*[@aria-label='Curtir']][1]")
            block = {"author": "", "text": "", "likes": 0, "replies": 0, "reposts": 0}
            if await card.count():
                try:
                    raw_text = await card.first.inner_text(timeout=5000)
                    block = _parse_post_block(raw_text)
                except Exception:  # noqa: BLE001
                    pass

            results.append(
                {
                    "x_post_id": post_id,
                    "text": block["text"],
                    "author_username": block["author"] or username,
                    "posted_at": posted_at,
                    "likes": block["likes"],
                    "reposts": block["reposts"],
                    "replies": block["replies"],
                    "views": 0,
                    "has_media": False,
                    "media_metadata": {},
                    "original_url": f"{BASE}{href}",
                }
            )

        if len(results) >= max_posts:
            break
        before = len(seen)
        await page.mouse.wheel(0, 1800)
        await page.wait_for_timeout(1200)
        if len(seen) == before:
            stagnant += 1
            if stagnant >= 2:
                break
        else:
            stagnant = 0

    return results


async def publish(page: Page, text: str, media_paths: list[str] | None = None) -> str:
    """Publica um post novo na conta logada. Validado manualmente (texto puro)."""
    await page.goto(BASE, wait_until="domcontentloaded", timeout=30_000)
    await page.wait_for_timeout(2000)

    await page.get_by_role("button", name=SEL["compose_trigger"], exact=True).first.click(timeout=10_000)
    await page.wait_for_timeout(1000)

    dialog = page.get_by_role("dialog")
    box = dialog.get_by_role("textbox").first
    await box.click(timeout=8000)
    await box.fill(text[:500])

    if media_paths:
        file_input = dialog.locator('input[type="file"]').first
        await file_input.set_input_files(media_paths, timeout=30_000)
        # Espera o preview de upload estabilizar antes de postar.
        await page.wait_for_timeout(3000)

    submit = dialog.get_by_role("button", name=SEL["compose_trigger"], exact=True).first
    await submit.click(timeout=10_000)

    try:
        await dialog.wait_for(state="hidden", timeout=20_000)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Modal do Threads nao fechou apos postar: {exc}") from exc

    return await _last_post_id(page)


async def _last_post_id(page: Page) -> str:
    """Melhor esforco: resolve o proprio username e le o topo do proprio
    perfil — o post recem-publicado e' sempre o primeiro (perfil e' reverse-
    chronological, ao contrario do feed "Para voce")."""
    try:
        identity = await resolve_identity(page)
        username = identity.get("username")
        if not username:
            return ""
        posts = await fetch_timeline(page, username, max_posts=1)
        return posts[0]["x_post_id"] if posts else ""
    except Exception:  # noqa: BLE001
        return ""


def post_url(username: str, post_id: str) -> str:
    return f"{BASE}/@{username}/post/{post_id}"
