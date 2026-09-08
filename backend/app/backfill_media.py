"""Repara midia de posts ja coletados que ficaram sem midia valida.

Cobre tres casos, todos com o mesmo sintoma (o post aparece sem foto/video
pra usar em Conteudo, so' o texto): (1) o post nunca teve midia baixada
(ex.: video cuja captura do HLS falhou na epoca — so' o poster/thumb entrou,
ou nem isso); (2) os assets referenciados foram apagados (ex.: usuario usou
"Excluir todas as fotos/videos" na Biblioteca) e a referencia ficou orfa;
(3) post de video cujo asset salvo e' so' o poster, nao o video de verdade.

Como o post ja' esta' em `source_posts` (already_seen bloqueia recoleta),
uma nova coleta NUNCA re-tenta a midia sozinha — so' este script revisita
a pagina do tweet (sessao logada) e refaz o download.

Uso: python -m app.backfill_media   (dentro do container `worker`)
Para testar num lote pequeno antes de rodar tudo: BACKFILL_LIMIT=10 python -m app.backfill_media
"""

import asyncio
import logging
import os
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


async def _valid_asset_kinds(db, post: SourcePost) -> set[str]:
    """Kinds dos assets referenciados que AINDA existem (ids apagados somem)."""
    ids = (post.media_metadata or {}).get("assets") or []
    if not ids:
        return set()
    rows = (
        await db.execute(select(MediaAsset).where(MediaAsset.id.in_(ids)))
    ).scalars().all()
    return {a.kind for a in rows}


async def _needs_repair(db, post: SourcePost) -> bool:
    meta = post.media_metadata or {}
    kinds = await _valid_asset_kinds(db, post)
    if not kinds:
        return True  # nunca teve midia, ou os assets referenciados foram apagados
    if meta.get("video") and "video" not in kinds:
        return True  # so' tem o poster/thumb salvo, nao o video de verdade
    return False


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
            await db.execute(
                select(SourcePost).where(
                    SourcePost.user_id == reader.user_id, SourcePost.has_media.is_(True)
                )
            )
        ).scalars().all()
        targets = [p for p in posts if await _needs_repair(db, p)]
        limit = int(os.environ.get("BACKFILL_LIMIT", "0"))
        if limit:
            targets = targets[:limit]
        log.info("Backfill de midia: %d posts para reparar (de %d com midia)", len(targets), len(posts))

        done = skipped = failed = 0
        async with browser_manager.session(reader) as (page, _ctx):
            if not await x_web.is_logged_in(page):
                log.error("Sessao expirou. Refaca o login.")
                return

            for i, post in enumerate(targets, 1):
                # Guardado ANTES do try: apos um db.rollback() o ORM expira os
                # atributos do objeto, e reler post.platform_post_id no except
                # (fora de um await) explode com MissingGreenlet.
                post_ref = post.platform_post_id
                try:
                    entities = await x_web.fetch_media_entities(
                        page,
                        post.platform_post_id,
                        post.author_username,
                        expect_video=bool((post.media_metadata or {}).get("video")),
                    )
                    if not entities:
                        skipped += 1
                        log.info(
                            "[%d/%d] post %s sem midia capturada (deletado/restrito/sensivel?) — pulado",
                            i, len(targets), post.platform_post_id,
                        )
                        await asyncio.sleep(SLEEP_BETWEEN)
                        continue

                    new_ids = await media_source.import_post_media(db, reader.user_id, entities)
                    if not new_ids:
                        raise RuntimeError("import_post_media devolveu vazio")

                    old_ids = list((post.media_metadata or {}).get("assets") or [])
                    # Apaga os assets antigos (thumbs, ou os que ainda existiam) que
                    # ficaram orfaos depois da troca.
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
                    log.error("[%d/%d] post %s falhou: %s", i, len(targets), post_ref, exc)

                await asyncio.sleep(SLEEP_BETWEEN)

        log.info("FIM: %d ok, %d pulados, %d falhas", done, skipped, failed)


if __name__ == "__main__":
    asyncio.run(main())
