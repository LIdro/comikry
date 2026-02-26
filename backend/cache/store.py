"""
Cache layer.

Responsibilities:
- Hash an uploaded PDF (SHA-256) to get a stable identity.
- Look up whether a comic has already been processed.
- Persist and load the JSON manifest (Comic model) for a comic_id.
- Store and look up CacheRecord entries (processing status + playback token).

Layout on disk:
  storage/
    index.json                       ← maps pdf_hash → comic_id
    {comic_id}/
      cache_record.json              ← CacheRecord for this comic
      manifest.json                  ← Comic (full data model)
      pages/                         ← rendered page PNGs
      panels/                        ← cropped panel PNGs
        normalised/                  ← normalised panel PNGs (optional)
      audio/
        voice/                       ← per-bubble MP3s
        sfx/                         ← per-panel SFX MP3s
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from python_ulid import ULID

from backend.config import settings
from backend.models import CacheRecord, Comic, ProcessingStage

_INDEX_FILE = Path(settings.storage_root) / "index.json"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_index() -> dict[str, str]:
    """Load the pdf_hash → comic_id index from disk."""
    if _INDEX_FILE.exists():
        return json.loads(_INDEX_FILE.read_text())
    return {}


def _save_index(index: dict[str, str]) -> None:
    _INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    _INDEX_FILE.write_text(json.dumps(index, indent=2))


def _comic_dir(comic_id: str) -> Path:
    return Path(settings.storage_root) / comic_id


def _record_path(comic_id: str) -> Path:
    return _comic_dir(comic_id) / "cache_record.json"


def _manifest_path(comic_id: str) -> Path:
    return _comic_dir(comic_id) / "manifest.json"


# ── Public API ────────────────────────────────────────────────────────────────

def hash_pdf(pdf_bytes: bytes) -> str:
    """Return the SHA-256 hex digest of a PDF's raw bytes."""
    return hashlib.sha256(pdf_bytes).hexdigest()


def lookup_by_hash(pdf_hash: str) -> str | None:
    """Return the comic_id for a PDF hash, or None if not cached."""
    return _load_index().get(pdf_hash)


def create_record(pdf_hash: str, title: str = "") -> CacheRecord:
    """
    Create a new CacheRecord and register it in the index.

    Returns the new record (not yet persisted — call save_record() after).
    """
    comic_id = str(ULID())
    token = str(ULID())

    record = CacheRecord(
        comic_id=comic_id,
        pdf_hash=pdf_hash,
        manifest_path=str(_manifest_path(comic_id)),
        playback_token=token,
        processing_stage=ProcessingStage.queued,
        progress_pct=0,
        created_at=_now_iso(),
        updated_at=_now_iso(),
    )

    # Register in index
    index = _load_index()
    index[pdf_hash] = comic_id
    _save_index(index)

    return record


def save_record(record: CacheRecord) -> None:
    """Persist a CacheRecord to disk."""
    record.updated_at = _now_iso()
    path = _record_path(record.comic_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(record.model_dump_json(indent=2))


def load_record(comic_id: str) -> CacheRecord | None:
    """Load a CacheRecord from disk, or None if not found."""
    path = _record_path(comic_id)
    if not path.exists():
        return None
    return CacheRecord.model_validate_json(path.read_text())


def load_record_by_token(token: str) -> CacheRecord | None:
    """Find a CacheRecord by its playback token (linear scan over index)."""
    index = _load_index()
    for comic_id in index.values():
        record = load_record(comic_id)
        if record and record.playback_token == token:
            return record
    return None


def save_manifest(comic: Comic) -> None:
    """Persist the full Comic manifest to disk."""
    path = _manifest_path(comic.comic_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(comic.model_dump_json(indent=2))


def load_manifest(comic_id: str) -> Comic | None:
    """Load the Comic manifest from disk, or None if not found."""
    path = _manifest_path(comic_id)
    if not path.exists():
        return None
    return Comic.model_validate_json(path.read_text())


def update_stage(
    record: CacheRecord,
    stage: ProcessingStage,
    progress_pct: int,
    error: str | None = None,
) -> CacheRecord:
    """
    Update the processing stage and progress on a record and save it.
    """
    record.processing_stage = stage
    record.progress_pct = progress_pct
    record.error_message = error
    save_record(record)
    return record
