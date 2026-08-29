"""Biblioteca de midia do usuario."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import current_user
from app.db import get_db
from app.models import CandidateMedia, MediaAsset, User
from app.services.storage import StorageError, classify, storage

router = APIRouter(prefix="/api/media", tags=["media"])


def _serialize(m: MediaAsset) -> dict:
    return {
        "id": m.id,
        "filename": m.filename,
        "mime_type": m.mime_type,
        "kind": m.kind,
        "size_bytes": m.size_bytes,
        "origin": m.origin,
        "publishable": m.publishable,
        "is_sensitive": m.is_sensitive,
        "url": f"/api/media/{m.id}/file",
        "created_at": m.created_at,
    }


@router.get("")
async def list_media(user: User = Depends(current_user), db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(MediaAsset).where(MediaAsset.user_id == user.id).order_by(MediaAsset.id.desc())
        )
    ).scalars().all()
    return [_serialize(m) for m in rows]


@router.post("", status_code=201)
async def upload(
    file: UploadFile = File(...),
    origin: str = Form("owned"),
    usage_rights: str = Form(""),
    is_sensitive: bool = Form(False),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await file.read()
    try:
        kind = classify(file.content_type or "", len(data))
        key = storage.save(user.id, file.filename or "upload", data)
    except StorageError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    if origin not in ("owned", "licensed", "source_reference"):
        origin = "owned"

    asset = MediaAsset(
        user_id=user.id,
        filename=file.filename or "upload",
        storage_key=key,
        mime_type=file.content_type or "",
        size_bytes=len(data),
        kind=kind,
        origin=origin,
        usage_rights=usage_rights,
        is_sensitive=is_sensitive,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return _serialize(asset)


@router.get("/{media_id}/file")
async def serve(
    request: Request,
    media_id: int,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
):
    """Serve a midia. Suporta Range porque <video> precisa disso para exibir preview."""
    asset = await db.get(MediaAsset, media_id)
    if not asset or asset.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Midia nao encontrada")
    try:
        data = storage.read(asset.storage_key)
    except StorageError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    total = len(data)
    base_headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"}

    range_header = request.headers.get("range")
    if range_header and range_header.startswith("bytes="):
        raw = range_header.removeprefix("bytes=").split("-", 1)
        try:
            first = int(raw[0]) if raw[0] else 0
            last = int(raw[1]) if len(raw) > 1 and raw[1] else total - 1
        except ValueError:
            first, last = 0, total - 1
        first = max(0, min(first, total - 1))
        last = max(first, min(last, total - 1))
        chunk = data[first : last + 1]
        return Response(
            content=chunk,
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            media_type=asset.mime_type,
            headers={
                **base_headers,
                "Content-Range": f"bytes {first}-{last}/{total}",
                "Content-Length": str(len(chunk)),
            },
        )

    return Response(content=data, media_type=asset.mime_type, headers=base_headers)


@router.delete("/{media_id}")
async def delete(
    media_id: int, user: User = Depends(current_user), db: AsyncSession = Depends(get_db)
):
    asset = await db.get(MediaAsset, media_id)
    if not asset or asset.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Midia nao encontrada")
    storage.delete(asset.storage_key)
    await db.delete(asset)
    await db.commit()
    return {"ok": True}


async def attach_media(
    db: AsyncSession, candidate_id: int, media_ids: list[int], user_id: int
) -> None:
    """Anexa midias a um conteudo. Rejeita midia de terceiro (source_reference)."""
    if not media_ids:
        return
    assets = (
        await db.execute(
            select(MediaAsset).where(
                MediaAsset.id.in_(media_ids), MediaAsset.user_id == user_id
            )
        )
    ).scalars().all()

    blocked = [a.filename for a in assets if not a.publishable]
    if blocked:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Midia de terceiro nao pode ser publicada: {', '.join(blocked)}. "
            "Marque como propria ou licenciada se voce tem os direitos.",
        )

    by_id = {a.id: a for a in assets}
    for position, media_id in enumerate(media_ids):
        if media_id in by_id:
            db.add(
                CandidateMedia(
                    content_candidate_id=candidate_id,
                    media_asset_id=media_id,
                    position=position,
                )
            )
