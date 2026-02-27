"""
FastAPI routes.

POST   /comics                      Upload a PDF; returns comic_id + status
GET    /comics/{comic_id}/status    Processing stage + progress %
GET    /comics/{comic_id}/manifest  Full Comic JSON (once done)
GET    /comics/{comic_id}/play      Shareable /play/{token} URL
POST   /comics/{comic_id}/reprocess Force a fresh pipeline run
GET    /comics/{comic_id}/story-bible  Story bible built by Track B (if available)
GET    /play/{token}                Resolve token → redirect to manifest URL
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse

from backend.cache import store
from backend.config import settings, reload_settings
from backend.models import CacheRecord, Comic, ProcessingStage
from backend.orchestrator import run_pipeline

router = APIRouter()

# ── Background task registry ──────────────────────────────────────────────────
# Maps comic_id → asyncio.Task so we can check if processing is running.
_running: dict[str, asyncio.Task] = {}


async def _process_in_background(
    pdf_path: str,
    comic_id: str,
    record: CacheRecord,
    normalization_enabled: bool,
    title: str,
    page_range: tuple[int, int] | None,
) -> None:
    try:
        await run_pipeline(
            pdf_path, comic_id, record, normalization_enabled, title,
            page_range=page_range,
        )
    finally:
        _running.pop(comic_id, None)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/comics", status_code=202)
async def upload_comic(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    normalization: bool = False,
    force_reprocess: bool = False,
    page_start: int = 1,
    page_end: int | None = None,
):
    """
    Upload a PDF comic. Returns immediately with comic_id and processing status.

    If the same PDF was processed before and force_reprocess is False, the
    existing comic_id is returned and processing is skipped.

    Use ``page_start`` and ``page_end`` (both inclusive, 1-based) to process
    only a sub-range of pages.  When only ``page_start`` is given the full
    document from that page onwards is processed.
    """
    pdf_bytes = await file.read()
    pdf_hash = store.hash_pdf(pdf_bytes)

    existing_id = store.lookup_by_hash(pdf_hash)
    if existing_id and not force_reprocess:
        record = store.load_record(existing_id)
        if record and record.processing_stage == ProcessingStage.done:
            return {
                "comic_id": existing_id,
                "stage": record.processing_stage,
                "progress_pct": record.progress_pct,
                "cached": True,
            }

    # Build page_range when parameters are meaningful
    page_range: tuple[int, int] | None = None
    if page_end is not None:
        page_range = (page_start, page_end)
    elif page_start > 1:
        # page_start provided without page_end — treat as open-ended start
        # (pdf_to_images will cap at the actual last page)
        page_range = (page_start, 999_999)

    # Save PDF to a temp file that persists long enough for background processing
    tmp_dir = Path(tempfile.mkdtemp())
    pdf_path = str(tmp_dir / (file.filename or "comic.pdf"))
    Path(pdf_path).write_bytes(pdf_bytes)

    record = store.create_record(pdf_hash, title=file.filename or "")
    record.page_range = page_range
    store.save_record(record)

    task = asyncio.create_task(
        _process_in_background(
            pdf_path,
            record.comic_id,
            record,
            normalization,
            title=file.filename or "",
            page_range=page_range,
        )
    )
    _running[record.comic_id] = task

    return {
        "comic_id": record.comic_id,
        "stage": record.processing_stage,
        "progress_pct": record.progress_pct,
        "cached": False,
    }

@router.get("/comics/{comic_id}/status")
async def get_status(comic_id: str):
    record = store.load_record(comic_id)
    if not record:
        raise HTTPException(status_code=404, detail="Comic not found")
    return {
        "comic_id": comic_id,
        "stage": record.processing_stage,
        "progress_pct": record.progress_pct,
        "error": record.error_message,
    }


@router.get("/comics/{comic_id}/manifest")
async def get_manifest(comic_id: str):
    record = store.load_record(comic_id)
    if not record:
        raise HTTPException(status_code=404, detail="Comic not found")
    if record.processing_stage != ProcessingStage.done:
        raise HTTPException(
            status_code=409,
            detail=f"Processing not complete. Stage: {record.processing_stage}",
        )
    comic = store.load_manifest(comic_id)
    if not comic:
        raise HTTPException(status_code=404, detail="Manifest not found on disk")
    return comic.model_dump()


@router.get("/comics/{comic_id}/play")
async def get_play_url(comic_id: str, request_base_url: str = "http://localhost:8000"):
    record = store.load_record(comic_id)
    if not record:
        raise HTTPException(status_code=404, detail="Comic not found")
    return {
        "comic_id": comic_id,
        "playback_url": f"{request_base_url}/play/{record.playback_token}",
        "token": record.playback_token,
    }


@router.post("/comics/{comic_id}/reprocess", status_code=202)
async def reprocess_comic(comic_id: str, normalization: bool = False):
    """Force a fresh pipeline run for an already-processed comic."""
    record = store.load_record(comic_id)
    if not record:
        raise HTTPException(status_code=404, detail="Comic not found")
    if comic_id in _running:
        raise HTTPException(status_code=409, detail="Processing already in progress")

    # We need the original PDF — look it up in the temp dir or return an error
    # For MVP: client must re-upload if the PDF is no longer in temp storage.
    raise HTTPException(
        status_code=501,
        detail=(
            "Reprocess from cache not yet implemented. "
            "Re-upload the PDF with force_reprocess=true."
        ),
    )


@router.get("/play/{token}")
async def play_by_token(token: str):
    """Resolve a playback token and redirect to the manifest endpoint."""
    record = store.load_record_by_token(token)
    if not record:
        raise HTTPException(status_code=404, detail="Invalid or expired playback token")
    return RedirectResponse(url=f"/comics/{record.comic_id}/manifest")


@router.get("/comics/{comic_id}/story-bible")
async def get_story_bible(comic_id: str):
    """Return the story bible if Track B completed successfully."""
    story_bible_path = (
        Path(settings.storage_root) / comic_id / "story_bible.json"
    )
    if not story_bible_path.exists():
        raise HTTPException(status_code=404, detail="Story bible not available")
    return json.loads(story_bible_path.read_text())


@router.post("/api/reload-config")
async def reload_config():
    """
    Hot-reload .env without restarting the server.

    Re-reads the .env file from disk and updates every setting in place so that
    all backend modules (which imported ``settings`` at startup) immediately see
    the new values.  Useful when you add or change SFX_API_URL (or any other
    setting) after the server is already running.

    Returns a summary of the settings that changed.
    """
    old_sfx = settings.sfx_api_url
    old_gemini = settings.use_gemini_files_api

    updated = reload_settings()

    changed = {}
    if updated.sfx_api_url != old_sfx:
        changed["sfx_api_url"] = {"before": old_sfx or "(empty)", "after": updated.sfx_api_url or "(empty)"}
    if updated.use_gemini_files_api != old_gemini:
        changed["use_gemini_files_api"] = {"before": old_gemini, "after": updated.use_gemini_files_api}

    return {
        "ok": True,
        "sfx_api_url": updated.sfx_api_url or None,
        "use_gemini_files_api": updated.use_gemini_files_api,
        "changed": changed,
    }
