"""Storage de midia. Abstrato para trocar por S3 depois sem mexer nas rotas."""

import secrets
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings

# Limites do X (ver docs.x.com). Validados no upload para falhar cedo.
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_GIF_BYTES = 15 * 1024 * 1024
MAX_VIDEO_BYTES = 512 * 1024 * 1024

ALLOWED = {
    "image/jpeg": ("image", MAX_IMAGE_BYTES),
    "image/png": ("image", MAX_IMAGE_BYTES),
    "image/webp": ("image", MAX_IMAGE_BYTES),
    "image/gif": ("gif", MAX_GIF_BYTES),
    "video/mp4": ("video", MAX_VIDEO_BYTES),
    "video/quicktime": ("video", MAX_VIDEO_BYTES),
}


class StorageError(Exception):
    pass


def classify(mime_type: str, size_bytes: int) -> str:
    """Valida tipo e tamanho, devolve o `kind` (image/gif/video)."""
    entry = ALLOWED.get(mime_type)
    if not entry:
        raise StorageError(
            f"Tipo nao suportado: {mime_type}. Aceitos: JPEG, PNG, WebP, GIF, MP4, MOV."
        )
    kind, limit = entry
    if size_bytes > limit:
        raise StorageError(
            f"Arquivo de {size_bytes // 1024 // 1024}MB excede o limite de "
            f"{limit // 1024 // 1024}MB para {kind}."
        )
    if size_bytes == 0:
        raise StorageError("Arquivo vazio.")
    return kind


class Storage(ABC):
    @abstractmethod
    def save(self, user_id: int, filename: str, data: bytes) -> str: ...

    @abstractmethod
    def read(self, key: str) -> bytes: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def local_path(self, key: str) -> str:
        """Caminho absoluto no disco. Usado para anexar midia no navegador."""


class LocalStorage(Storage):
    """Grava em volume Docker. `key` é sempre relativo — nunca aceita path do usuario."""

    def __init__(self, root: str | None = None):
        self.root = Path(root or settings.STORAGE_DIR)

    def _full(self, key: str) -> Path:
        path = (self.root / key).resolve()
        # Impede path traversal via nome de arquivo malicioso.
        if not str(path).startswith(str(self.root.resolve())):
            raise StorageError("Caminho invalido.")
        return path

    def save(self, user_id: int, filename: str, data: bytes) -> str:
        suffix = Path(filename).suffix.lower()[:10]
        stamp = datetime.now(timezone.utc).strftime("%Y%m")
        key = f"{user_id}/{stamp}/{secrets.token_hex(16)}{suffix}"
        path = self._full(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def read(self, key: str) -> bytes:
        path = self._full(key)
        if not path.exists():
            raise StorageError("Arquivo nao encontrado.")
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self._full(key)
        path.unlink(missing_ok=True)

    def local_path(self, key: str) -> str:
        path = self._full(key)
        if not path.exists():
            raise StorageError("Arquivo nao encontrado.")
        return str(path)


storage: Storage = LocalStorage()
