"""Backfill: baixa o VIDEO real (nao a thumb) dos posts de video ja coletados.

Os posts antigos guardaram so a thumbnail do video como imagem. Este script
visita a pagina de cada tweet (sessao logada), captura o manifesto HLS,
remuxa para mp4 sem metadados via ffmpeg e substitui os assets antigos.

Uso: python -m app.backfill_videos   (dentro do container `worker`)
"""

import asyncio
import logging
import sys

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Account, MediaAsset, SourcePost
from app.services import media_source, x_web
from app.services.browser import manager as browser_manager
from app.services.storage import storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("backfill")

SLEEP_BETWEEN = 2.5  # segundos entre tweets (evita throttling)


async def _asset_kinds(db, post: SourcePost) -> set[str]:
    ids = (post.media_metadata or {}).get("assets") or []
    if not ids:
        return set()
    rows = (
        await db.execute(select(MediaAsset).where(MediaAsset.id.in_(ids)))
    ).scalars().all()
    return {a.kind for a in rows}


async def main() -> None:
    async with SessionLocal() as db:
        reader = (
            await db.execute(
                select(Account).where(
                    Account.platform == "x",
                    Account.is_active.is_(True),
                    Account.session_valid.is_(True),
                )
            )
        ).scalars().first()
        if reader is None:
            log.error("Nenhuma conta com sessao valida. Faca login antes.")
            return

        posts = (
            await db.execute(select(SourcePost).where(SourcePost.user_id == reader.user_id))
        ).scalars().all()
        targets = [
            p
            for p in posts
            if (p.media_metadata or {}).get("video") and "video" not in await _asset_kinds(db, p)
        ]
        log.info("Backfill de videos: %d posts para processar (de %d)", len(targets), len(posts))

        done = skipped = failed = 0
        async with browser_manager.session(reader) as (page, _ctx):
            if not await x_web.is_logged_in(page):
                log.error("Sessao expirou. Refaca o login.")
                return

            for i, post in enumerate(targets, 1):
                try:
                    entities = await x_web.fetch_media_entities(
                        page, post.platform_post_id, post.author_username
                    )
                    videos = [
                        e for e in entities if e["mime"] == "application/vnd.apple.mpegurl"
                    ]
                    if not videos:
                        skipped += 1
                        log.info(
                            "[%d/%d] post %s sem video capturado (deletado/restrito?) — pulado",
                            i, len(targets), post.platform_post_id,
                        )
                        await asyncio.sleep(SLEEP_BETWEEN)
                        continue

                    new_ids = await media_source.import_post_media(db, reader.user_id, entities)
                    if not new_ids:
                        raise RuntimeError("import_post_media devolveu vazio")

                    old_ids = list((post.media_metadata or {}).get("assets") or [])
                    # Apaga os assets antigos (thumbs) que ficaram orfaos.
                    for asset in (
                        await db.execute(
                            select(MediaAsset).where(
                                MediaAsset.id.in_(old_ids), MediaAsset.user_id == reader.user_id
                            )
                        )
                    ).scalars().all():
                        if asset.id not in new_ids:
                            storage.delete(asset.storage_key)
                            await db.delete(asset)

                    post.media_metadata = {**(post.media_metadata or {}), "assets": new_ids}
                    await db.commit()
                    done += 1
                    log.info(
                        "[%d/%d] post %s -> assets %s", i, len(targets), post.platform_post_id, new_ids
                    )
                except Exception as exc:  # noqa: BLE001 — um post nao derruba o resto
                    await db.rollback()
                    failed += 1
                    log.error("[%d/%d] post %s falhou: %s", i, len(targets), post.platform_post_id, exc)

                await asyncio.sleep(SLEEP_BETWEEN)

        log.info("FIM: %d ok, %d pulados, %d falhas", done, skipped, failed)


if __name__ == "__main__":
    asyncio.run(main())
