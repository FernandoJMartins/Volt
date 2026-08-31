"""Midia dos posts coletados: download + limpeza de metadados.

Fotos e videos do tweet sao baixados e armazenados SEM metadados (EXIF, GPS,
XMP, IPTC, comentarios). Fotos: remocao lossless em Python puro (so os
segmentos de metadados saem; os pixels nao sao re-encodados). Videos: remux
com ffmpeg (`-map_metadata -1 -c copy`), tambem sem re-encode.

Por decisao do operador do painel, a midia do tweet e publicavel
(origin="source_reference"): baixada sem metadados e usada no mesmo fluxo de
publicacao da midia propria.
"""

import asyncio
import logging
import secrets
import struct
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import MediaAsset
from app.services.storage import StorageError, classify, storage

log = logging.getLogger("worker")

FFMPEG = "ffmpeg"  # instalado no Dockerfile (build do Playwright nao demuxa mp4/jpeg)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# X aceita no maximo 4 midias por post.
MAX_ASSETS_PER_POST = 4

_EXT_BY_MIME = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
}


# ---------------------------------------------------------------- imagens
def strip_image_metadata(data: bytes, mime: str) -> bytes:
    """Remove EXIF/XMP/IPTC/comentarios sem re-encodar. Fallback: devolve como esta."""
    if mime == "image/jpeg":
        return _strip_jpeg(data)
    if mime == "image/png":
        return _strip_png(data)
    if mime == "image/webp":
        return _strip_webp(data)
    if mime == "image/gif":
        return _strip_gif(data)
    return data


def _strip_jpeg(data: bytes) -> bytes:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return data
    out = bytearray(data[:2])
    i, n = 2, len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            return data  # corrompido: nao mexe
        marker = data[i + 1]
        if marker == 0xD9:  # EOI
            out += data[i : i + 2]
            return bytes(out)
        if marker == 0xDA:  # SOS: daqui pra frente e' scan data comprimida
            out += data[i:]
            return bytes(out)
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:  # TEM / RST (sem tamanho)
            out += data[i : i + 2]
            i += 2
            continue
        length = struct.unpack(">H", data[i + 2 : i + 4])[0]
        if length < 2 or i + 2 + length > n:
            return data
        segment = data[i : i + 2 + length]
        drop = False
        if marker == 0xE1:  # APP1 (EXIF / XMP)
            payload = segment[4:]
            drop = payload.startswith(b"Exif\x00\x00") or payload.startswith(
                b"http://ns.adobe.com/xap"
            )
        elif marker in (0xED, 0xFE):  # APP13 (IPTC/Photoshop) / COM (comentario)
            drop = True
        if not drop:
            out += segment
        i += 2 + length
    return bytes(out)


def _strip_png(data: bytes) -> bytes:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return data
    meta = {b"tEXt", b"zTXt", b"iTXt", b"eXIf"}
    out = bytearray(data[:8])
    i, n = 8, len(data)
    while i + 8 <= n:
        length = struct.unpack(">I", data[i : i + 4])[0]
        ctype = data[i + 4 : i + 8]
        end = i + 12 + length
        if end > n:
            return data
        if ctype not in meta:
            out += data[i:end]
        i = end
    return bytes(out)


def _strip_webp(data: bytes) -> bytes:
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return data
    out = bytearray(data[:12])
    i, n = 12, len(data)
    while i + 8 <= n:
        fourcc = data[i : i + 4]
        size = struct.unpack("<I", data[i + 4 : i + 8])[0]
        end = i + 8 + size + (size & 1)  # chunk RIFF com padding para par
        if end > n:
            return data
        if fourcc not in (b"EXIF", b"XMP "):
            out += data[i:end]
        i = end
    return bytes(out)


def _strip_gif(data: bytes) -> bytes:
    if len(data) < 13 or data[:6] not in (b"GIF87a", b"GIF89a"):
        return data
    out = bytearray(data[:13])
    i, n = 13, len(data)
    packed = data[10]
    if packed & 0x80:  # global color table
        gct = 3 * (2 ** ((packed & 0x07) + 1))
        if i + gct > n:
            return data
        out += data[i : i + gct]
        i += gct
    while i < n:
        b = data[i]
        if b == 0x3B:  # trailer
            out += data[i : i + 1]
            return bytes(out)
        if b == 0x21:  # extension
            label = data[i + 1]
            if label == 0xFE:  # comentario: descarta
                i = _skip_sub_blocks(data, i + 2, n)
            elif label == 0xFF:  # application extension (XMP etc.): descarta
                j = i + 2
                if j < n and data[j] == 0x0B:
                    j = _skip_sub_blocks(data, j + 1 + 11, n)
                else:
                    j = _skip_sub_blocks(data, j, n)
                i = j
            else:  # graphics control etc.: copia
                j = _skip_sub_blocks(data, i + 2, n)
                out += data[i:j]
                i = j
            continue
        if b == 0x2C:  # image descriptor: copia
            j = i + 10
            if j > n:
                return data
            packed2 = data[i + 9]
            if packed2 & 0x80:
                j += 3 * (2 ** ((packed2 & 0x07) + 1))
            j += 1  # LZW minimum code size
            j = _skip_sub_blocks(data, j, n)
            if j > n:
                return data
            out += data[i:j]
            i = j
            continue
        return data  # byte desconhecido: nao mexe
    return bytes(out)


def _skip_sub_blocks(data: bytes, i: int, n: int) -> int:
    while i < n:
        size = data[i]
        if size == 0:
            return i + 1
        i += 1 + size
    return n


# ----------------------------------------------------------------- videos
async def _download_hls(url: str, cookies: str) -> bytes:
    """Baixa o video via playlist HLS direto no ffmpeg (remux, sem re-encode)."""
    tmpdir = Path(settings.STORAGE_DIR) / "tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    dst = tmpdir / f"hls_{secrets.token_hex(8)}.mp4"
    try:
        proc = await asyncio.create_subprocess_exec(
            FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
            "-user_agent", USER_AGENT,
            "-headers", f"Cookie: {cookies}\r\nReferer: https://x.com/\r\n",
            "-i", url,
            "-map_metadata", "-1", "-c", "copy", "-movflags", "+faststart",
            str(dst),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout=900)
        except asyncio.TimeoutError:
            proc.kill()
            raise StorageError("Timeout baixando video HLS")
        if proc.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
            detail = err[-200:].decode(errors="ignore") if err else ""
            raise StorageError(f"Falha ao baixar video HLS: {detail}")
        return dst.read_bytes()
    finally:
        dst.unlink(missing_ok=True)


async def _strip_video(data: bytes) -> bytes:
    tmpdir = Path(settings.STORAGE_DIR) / "tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    src = tmpdir / f"in_{secrets.token_hex(8)}.mp4"
    dst = tmpdir / f"out_{secrets.token_hex(8)}.mp4"
    try:
        src.write_bytes(data)
        proc = await asyncio.create_subprocess_exec(
            FFMPEG, "-y", "-i", str(src), "-map_metadata", "-1", "-c", "copy", str(dst),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await proc.communicate()
        if proc.returncode != 0 or not dst.exists() or dst.stat().st_size == 0:
            detail = err[-200:].decode(errors="ignore") if err else ""
            raise StorageError(f"Falha ao limpar metadados do video: {detail}")
        return dst.read_bytes()
    finally:
        src.unlink(missing_ok=True)
        dst.unlink(missing_ok=True)


# ------------------------------------------------------------- importacao
async def _download(url: str) -> bytes:
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=httpx.Timeout(120.0, connect=15.0)
    ) as client:
        resp = await client.get(url, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        return resp.content


async def import_asset(db: AsyncSession, user_id: int, entity: dict) -> MediaAsset | None:
    """Baixa uma midia do tweet, limpa metadados e cria o MediaAsset.

    `entity`: {"type": "photo"|"video"|"animated_gif", "url": str, "mime": str}.
    Falha de uma midia nao derruba a coleta — retorna None.
    """
    url, mime = entity["url"], entity["mime"]
    try:
        if mime == "application/vnd.apple.mpegurl":
            data = await _download_hls(url, entity.get("cookies", ""))
            mime = "video/mp4"
        elif mime.startswith("video/"):
            data = await _download(url)
            data = await _strip_video(data)
            mime = "video/mp4"  # o remux sempre produz mp4
        else:
            data = await _download(url)
            data = strip_image_metadata(data, mime)
        kind = classify(mime, len(data))
        ext = _EXT_BY_MIME.get(mime, ".bin")
        key = storage.save(user_id, f"tweet{ext}", data)
        asset = MediaAsset(
            user_id=user_id,
            filename=f"tweet_{entity.get('type', 'media')}{ext}",
            storage_key=key,
            mime_type=mime,
            size_bytes=len(data),
            kind=kind,
            origin="source_reference",
            usage_rights="Midia coletada de post publico do X, sem metadados.",
        )
        db.add(asset)
        await db.flush()
        return asset
    except (httpx.HTTPError, StorageError) as exc:
        log.warning("Midia do tweet nao importada (%s): %s", entity.get("type"), exc)
        return None


async def import_post_media(
    db: AsyncSession, user_id: int, entities: list[dict]
) -> list[int]:
    """Importa as midias de um post (max. 4) e devolve os ids dos assets criados."""
    ids: list[int] = []
    for entity in entities[:MAX_ASSETS_PER_POST]:
        asset = await import_asset(db, user_id, entity)
        if asset is not None:
            ids.append(asset.id)
    return ids
