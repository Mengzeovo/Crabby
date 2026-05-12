"""File-backed storage for persisted chat attachments."""

from __future__ import annotations

import base64
import json
import mimetypes
import uuid
from pathlib import Path
from typing import Any


_MEDIA_TYPE_TO_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


class AttachmentStore:
    """Persist image attachments outside session JSON blobs."""

    def __init__(self, storage_dir: str | Path) -> None:
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def save_image(
        self,
        *,
        data: str,
        media_type: str,
        filename: str,
        width: int | None = None,
        height: int | None = None,
        source_path: str | None = None,
    ) -> dict[str, Any]:
        if not media_type.startswith("image/"):
            raise ValueError(f"Unsupported media type: {media_type}")

        try:
            raw = base64.b64decode(data, validate=True)
        except Exception as exc:  # pragma: no cover - defensive
            raise ValueError("Invalid base64 image payload") from exc

        attachment_id = uuid.uuid4().hex
        ext = _MEDIA_TYPE_TO_EXT.get(media_type)
        if not ext:
            guessed = mimetypes.guess_extension(media_type)
            ext = guessed or ".bin"

        path = self._storage_dir / f"{attachment_id}{ext}"
        path.write_bytes(raw)

        metadata = {
            "attachment_id": attachment_id,
            "filename": filename or path.name,
            "media_type": media_type,
            "width": width,
            "height": height,
            "size_bytes": len(raw),
            "source_path": source_path,
            "path": str(path),
        }
        self._metadata_path(attachment_id).write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return metadata

    def get_metadata(self, attachment_id: str) -> dict[str, Any] | None:
        path = self._metadata_path(attachment_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def get_path(self, attachment_id: str) -> Path | None:
        metadata = self.get_metadata(attachment_id)
        if not metadata:
            return None
        path = Path(str(metadata.get("path", "")))
        if not path.exists():
            return None
        return path

    def build_image_block(self, attachment: dict[str, Any]) -> dict[str, Any] | None:
        attachment_id = str(attachment.get("attachment_id", ""))
        if not attachment_id:
            return None

        path = self.get_path(attachment_id)
        metadata = self.get_metadata(attachment_id)
        if path is None or metadata is None:
            return None

        data = base64.b64encode(path.read_bytes()).decode("ascii")
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": metadata["media_type"],
                "data": data,
            },
        }

    def _metadata_path(self, attachment_id: str) -> Path:
        return self._storage_dir / f"{attachment_id}.json"
