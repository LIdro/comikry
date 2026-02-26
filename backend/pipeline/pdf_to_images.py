"""
Stage 1 — PDF to images.

Renders every page of a PDF to a PNG file saved under:
  storage/{comic_id}/pages/page_{n:04d}.png

Returns the list of absolute file paths in page order.
"""

from __future__ import annotations

import os
from pathlib import Path

from pdf2image import convert_from_path
from PIL.Image import Image

from backend.config import settings


def render_pdf(pdf_path: str, comic_id: str) -> list[str]:
    """
    Render all pages of *pdf_path* to PNG images.

    Returns a list of absolute file paths, one per page, in order.
    """
    out_dir = Path(settings.storage_root) / comic_id / "pages"
    out_dir.mkdir(parents=True, exist_ok=True)

    pages: list[Image] = convert_from_path(
        pdf_path,
        dpi=settings.pdf_render_dpi,
        fmt="png",
        thread_count=4,
    )

    paths: list[str] = []
    for i, page_img in enumerate(pages, start=1):
        file_path = out_dir / f"page_{i:04d}.png"
        page_img.save(str(file_path), "PNG")
        paths.append(str(file_path))

    return paths
