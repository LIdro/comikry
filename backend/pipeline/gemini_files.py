"""
Gemini Files API helper.

When USE_GEMINI_FILES_API=true, images are uploaded once via genai.upload_file()
and referenced by URI in all subsequent Gemini calls for the same pipeline run.
When the flag is false, this module's functions silently return None and callers
fall back to base64 encoding.

Upload entries older than 47 hours are treated as stale (Gemini Files API keeps
files for 48 hours) and a fresh upload is performed automatically.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.config import settings

# Maps absolute_image_path → (file_uri, upload_time_utc)
_uri_cache: dict[str, tuple[str, datetime]] = {}

_STALE_THRESHOLD = timedelta(hours=47)


async def upload_image(image_path: str) -> Optional[str]:
    """
    Upload an image to the Gemini Files API and return its file URI.

    Returns
    -------
    str | None
        The Gemini file URI (e.g. ``"files/abc123"``) if the upload succeeded,
        or ``None`` if the feature flag is off or the API key is missing.

    Notes
    -----
    - Returns ``None`` immediately when ``settings.use_gemini_files_api`` is
      ``False`` or ``settings.google_ai_api_key`` is empty.
    - Subsequent calls for the same path return the cached URI without
      re-uploading, unless the entry is older than 47 hours.
    - The blocking ``genai.upload_file()`` call is offloaded to a thread
      executor so the async event loop is not blocked.
    """
    if not settings.use_gemini_files_api or not settings.google_ai_api_key:
        return None

    now = datetime.now(timezone.utc)

    # Check cache
    if image_path in _uri_cache:
        uri, upload_time = _uri_cache[image_path]
        if now - upload_time < _STALE_THRESHOLD:
            return uri
        # Stale — remove and re-upload
        del _uri_cache[image_path]

    # Perform the upload in a thread executor (blocking I/O)
    def _do_upload() -> str:
        import google.generativeai as genai  # type: ignore

        genai.configure(api_key=settings.google_ai_api_key)
        uploaded = genai.upload_file(image_path)
        return uploaded.uri

    loop = asyncio.get_event_loop()
    uri = await loop.run_in_executor(None, _do_upload)

    _uri_cache[image_path] = (uri, now)
    return uri


def clear_cache() -> None:
    """Clear the in-memory URI cache (used in tests and between pipeline runs)."""
    _uri_cache.clear()
