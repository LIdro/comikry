"""
Stage 1 — PDF to images.

Renders every page of a PDF to a PNG file saved under:
  storage/{comic_id}/pages/page_{n:04d}.png

Returns the list of absolute file paths in page order.

Task 4-7: Uses concurrent.futures.ProcessPoolExecutor for parallel batched
rendering so large PDFs are processed faster.  Each worker renders a batch of
pages and saves them immediately; the main process collects and sorts the paths.
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from pdf2image import pdfinfo_from_path

from backend.config import settings


# ── Module-level worker (must be picklable — no lambdas or nested functions) ──

def _render_batch(
    pdf_path: str,
    out_dir: str,
    first_page: int,
    last_page: int,
    dpi: int,
) -> list[str]:
    """
    Worker function: render pages *first_page*…*last_page* of *pdf_path* to PNG.

    Saves each page immediately to *out_dir* and returns the list of saved paths.
    This function runs in a subprocess — it must not import anything that holds
    module-level state that cannot be pickled.
    """
    from pdf2image import convert_from_path  # local import keeps worker lean

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    pages = convert_from_path(
        pdf_path,
        dpi=dpi,
        fmt="png",
        first_page=first_page,
        last_page=last_page,
        thread_count=1,   # one thread per worker — parallelism comes from processes
    )

    saved: list[str] = []
    for page_num, page_img in enumerate(pages, start=first_page):
        file_path = out / f"page_{page_num:04d}.png"
        page_img.save(str(file_path), "PNG")
        saved.append(str(file_path))

    return saved


def render_pdf(
    pdf_path: str,
    comic_id: str,
    page_range: tuple[int, int] | None = None,
) -> list[str]:
    """
    Render pages of *pdf_path* to PNG images.

    Parameters
    ----------
    pdf_path:
        Absolute path to the source PDF.
    comic_id:
        Used to build the output directory path.
    page_range:
        Optional ``(first_page, last_page)`` tuple (both **inclusive**, 1-based).
        When *None* all pages are rendered (existing behaviour).

    Returns
    -------
    list[str]
        Absolute file paths, one per page, sorted by page number.
    """
    out_dir = Path(settings.storage_root) / comic_id / "pages"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Determine the effective page range
    info = pdfinfo_from_path(pdf_path)
    total_pages: int = info["Pages"]

    if page_range is not None:
        first_page, last_page = page_range
        first_page = max(1, first_page)
        last_page = min(total_pages, last_page)
    else:
        first_page, last_page = 1, total_pages

    batch_size: int = settings.pdf_render_batch_size
    max_workers: int = min(os.cpu_count() or 1, settings.pdf_render_max_workers)

    # Build batches: [(first, last), ...]
    batches: list[tuple[int, int]] = []
    page = first_page
    while page <= last_page:
        batches.append((page, min(page + batch_size - 1, last_page)))
        page += batch_size

    all_paths: list[str] = []

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                _render_batch,
                pdf_path,
                str(out_dir),
                batch_first,
                batch_last,
                settings.pdf_render_dpi,
            )
            for batch_first, batch_last in batches
        ]
        for future in futures:
            all_paths.extend(future.result())

    # Sort by page number (batches may finish out of order in edge cases)
    all_paths.sort(key=lambda p: int(Path(p).stem.split("_")[-1]))
    return all_paths
