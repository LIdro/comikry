"""
Track B — Hierarchical Story Analysis pipeline.

Runs concurrently with Track A to pre-build a story bible from all pages so
attribution and emotion steps have cross-page character context.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from backend.agents.page_range_agent import analyse_page_range
from backend.agents.story_director_agent import synthesise_story_bible
from backend.config import settings
from backend.models import StoryBible


async def run_track_b(
    page_image_paths: list[str],
    comic_id: str,
    pages_per_agent: Optional[int] = None,
    overlap: Optional[int] = None,
) -> StoryBible:
    """
    Run the full Track B pipeline: parallel page-range analysis → story bible.

    The page list is split into overlapping slices.  All ``analyse_page_range``
    calls are launched concurrently with ``asyncio.gather``.

    Parameters
    ----------
    page_image_paths:
        Ordered list of absolute paths to rendered page images (output of
        ``render_pdf``).
    comic_id:
        Stable comic identifier forwarded to sub-agents and the story bible.
    pages_per_agent:
        Number of pages per agent slice.  Defaults to
        ``settings.track_b_pages_per_agent``.
    overlap:
        Number of pages shared between consecutive slices.  Defaults to
        ``settings.track_b_overlap_pages``.

    Returns
    -------
    StoryBible
        The unified story bible returned by the Story Director agent.

    Example (25 pages, pages_per_agent=10, overlap=2)
    --------------------------------------------------
    Slice 1: pages 1–10
    Slice 2: pages 9–18  (overlap: pages 9–10 shared)
    Slice 3: pages 17–25 (overlap: pages 17–18 shared)
    """
    if pages_per_agent is None:
        pages_per_agent = settings.track_b_pages_per_agent
    if overlap is None:
        overlap = settings.track_b_overlap_pages

    total = len(page_image_paths)

    # Build overlapping slices of *indices* into page_image_paths (0-based)
    slices: list[tuple[int, int]] = []   # (start_idx, end_idx) inclusive
    start = 0
    while start < total:
        end = min(start + pages_per_agent - 1, total - 1)
        slices.append((start, end))
        if end == total - 1:
            break
        # Next slice starts (pages_per_agent - overlap) pages forward
        start = start + pages_per_agent - overlap

    # Launch all page-range agents in parallel
    # Pass empty known_characters=[] to each — the Story Director reconciles.
    tasks = [
        analyse_page_range(
            page_image_paths=page_image_paths[s:e + 1],
            page_range=(s + 1, e + 1),   # 1-based page numbers
            comic_id=comic_id,
            known_characters=[],
        )
        for s, e in slices
    ]

    fragments = list(await asyncio.gather(*tasks))

    return await synthesise_story_bible(fragments, comic_id)
