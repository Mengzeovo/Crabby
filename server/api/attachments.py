"""Attachment serving endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from attachment_store import AttachmentStore

router = APIRouter(prefix="/attachments", tags=["attachments"])

_store: AttachmentStore | None = None


def set_store(store: AttachmentStore) -> None:
    global _store
    _store = store


def _get_store() -> AttachmentStore:
    assert _store is not None
    return _store


@router.get("/{attachment_id}")
async def get_attachment(attachment_id: str) -> FileResponse:
    store = _get_store()
    path = store.get_path(attachment_id)
    metadata = store.get_metadata(attachment_id)
    if path is None or metadata is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    return FileResponse(
        path=path,
        media_type=str(metadata.get("media_type", "application/octet-stream")),
        filename=str(metadata.get("filename", path.name)),
    )
