"""
Pipeline orchestrator.

Runs the full processing pipeline for one comic and updates the CacheRecord
progress at each stage so the frontend can poll for live status.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend.agents.character_agent import attribute_speakers
from backend.agents.sound_director_agent import generate_sfx_prompts
from backend.agents.voice_tone_agent import run_voice_tone_agent
from backend.cache import store
from backend.config import settings
from backend.models import (
    CacheRecord,
    Comic,
    Page,
    ProcessingStage,
    Speaker,
    StoryBible,
)
from backend.pipeline.bubble_ocr import detect_bubbles
from backend.pipeline.normalizer import normalise_comic_panels
from backend.pipeline.panel_detection import detect_panels
from backend.pipeline.pdf_to_images import render_pdf
from backend.pipeline.sfx_generation import generate_sfx_for_comic
from backend.pipeline.tts_generation import generate_tts_for_comic

logger = logging.getLogger(__name__)


async def run_pipeline(
    pdf_path: str,
    comic_id: str,
    record: CacheRecord,
    normalization_enabled: bool = False,
    title: str = "",
    page_range: Optional[tuple[int, int]] = None,
) -> Comic:
    """
    Execute all pipeline stages in order, updating cache record progress.

    Stages and their progress checkpoints:
      pdf_to_images        10 %
      panel_detection      25 %
      bubble_ocr           40 %
      speaker_attribution  55 %
      voice_assignment     65 %
      tts_generation       80 %
      sfx_generation       90 %
      normalization        95 %   (skipped if not enabled)
      done                100 %

    Track B (story analysis) runs concurrently with Track A starting after
    PDF rendering.  Its results are used opportunistically — if it finishes
    before speaker attribution / SFX generation the pipeline uses its output;
    otherwise cold per-panel inference is used instead.

    Parameters
    ----------
    page_range:
        Optional ``(first_page, last_page)`` inclusive 1-based tuple.  When
        provided only that sub-range of pages is rendered and processed.
    """
    from backend.pipeline.track_b import run_track_b  # deferred to avoid circular imports

    def advance(stage: ProcessingStage, pct: int) -> None:
        store.update_stage(record, stage, pct)

    # Persist page_range on the record
    record.page_range = page_range
    store.save_record(record)

    track_b_task: Optional[asyncio.Task] = None
    story_bible: Optional[StoryBible] = None

    try:
        # ── Stage 1: PDF → images ──────────────────────────────────────────
        advance(ProcessingStage.pdf_to_images, 0)
        page_paths = render_pdf(pdf_path, comic_id, page_range=page_range)
        advance(ProcessingStage.pdf_to_images, 10)

        # ── Launch Track B concurrently (non-blocking) ─────────────────────
        try:
            track_b_task = asyncio.create_task(
                run_track_b(page_paths, comic_id)
            )
        except Exception as exc:
            logger.warning("Track B failed to start: %s; continuing with cold inference", exc)
            track_b_task = None

        # Build initial Comic shell
        comic = Comic(
            comic_id=comic_id,
            title=title,
            pdf_hash=record.pdf_hash,
            normalization_enabled=normalization_enabled,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        pages: list[Page] = []
        # page_range may start from a page > 1 — use actual filenames to derive numbers
        for page_path in page_paths:
            stem = Path(page_path).stem            # e.g. "page_0003"
            page_num = int(stem.split("_")[-1])    # e.g. 3
            page_id = f"{comic_id}_pg{page_num:04d}"
            pages.append(
                Page(page_id=page_id, page_number=page_num, image_path=page_path)
            )
        comic.pages = pages

        # ── Stage 2: Panel detection ──────────────────────────────────────
        advance(ProcessingStage.panel_detection, 10)
        for page in comic.pages:
            page.panels = await detect_panels(page.image_path, page.page_id, comic_id)
        advance(ProcessingStage.panel_detection, 25)

        # ── Stage 3: Bubble OCR ───────────────────────────────────────────
        advance(ProcessingStage.bubble_ocr, 25)
        for page in comic.pages:
            for panel in page.panels:
                panel.bubbles = await detect_bubbles(panel)
        advance(ProcessingStage.bubble_ocr, 40)

        # ── Attempt to get Track B story bible before attribution ─────────
        if track_b_task is not None and track_b_task.done():
            try:
                story_bible = track_b_task.result()
            except Exception as exc:
                logger.warning(
                    "Track B failed: %s; continuing with cold inference", exc
                )
                story_bible = None

        # ── Stage 4: Speaker attribution ──────────────────────────────────
        advance(ProcessingStage.speaker_attribution, 40)
        known_speakers: list[Speaker] = []
        for page in comic.pages:
            for panel in page.panels:
                panel.bubbles, new_speakers = await attribute_speakers(
                    panel,
                    panel.bubbles,
                    known_speakers,
                    character_profiles=(
                        story_bible.characters if story_bible else None
                    ),
                )
                # Merge new speakers into the known set
                existing_ids = {s.speaker_id for s in known_speakers}
                for ns in new_speakers:
                    if ns.speaker_id not in existing_ids:
                        known_speakers.append(ns)
        comic.speakers = known_speakers
        advance(ProcessingStage.speaker_attribution, 55)

        # ── Stage 5: Voice assignment + emotion tagging ───────────────────
        advance(ProcessingStage.voice_assignment, 55)
        comic = await run_voice_tone_agent(comic)
        advance(ProcessingStage.voice_assignment, 65)

        # ── Stage 6: TTS generation ───────────────────────────────────────
        advance(ProcessingStage.tts_generation, 65)
        comic = await generate_tts_for_comic(comic)
        advance(ProcessingStage.tts_generation, 80)

        # ── Stage 7: SFX generation ───────────────────────────────────────
        advance(ProcessingStage.sfx_generation, 80)

        # Use Track B per_panel_sfx if available and non-empty
        if track_b_task is not None and track_b_task.done() and story_bible is None:
            try:
                story_bible = track_b_task.result()
            except Exception as exc:
                logger.warning(
                    "Track B failed: %s; continuing with cold inference", exc
                )

        if story_bible is not None and story_bible.per_panel_sfx:
            sfx_prompts = story_bible.per_panel_sfx
        else:
            sfx_prompts = await generate_sfx_prompts(comic)

        comic = await generate_sfx_for_comic(comic, sfx_prompts)
        advance(ProcessingStage.sfx_generation, 90)

        # ── Stage 8: Panel normalisation (optional) ───────────────────────
        if normalization_enabled:
            advance(ProcessingStage.normalization, 90)
            comic = await normalise_comic_panels(comic)
        advance(ProcessingStage.normalization, 95)

        # ── Await Track B and update record ───────────────────────────────
        if track_b_task is not None:
            if not track_b_task.done():
                track_b_task.cancel()
                try:
                    await track_b_task
                except (asyncio.CancelledError, Exception):
                    pass
            else:
                try:
                    if story_bible is None:
                        story_bible = track_b_task.result()
                except Exception:
                    pass

        if story_bible is not None:
            bible_path = Path(settings.storage_root) / comic_id / "story_bible.json"
            if bible_path.exists():
                record.story_bible_path = str(bible_path)

        # ── Persist manifest and mark done ────────────────────────────────
        store.save_manifest(comic)
        store.save_record(record)
        advance(ProcessingStage.done, 100)

        return comic

    except Exception as exc:
        # Cancel Track B if still running before propagating
        if track_b_task is not None and not track_b_task.done():
            track_b_task.cancel()
            try:
                await track_b_task
            except (asyncio.CancelledError, Exception):
                pass
        store.update_stage(record, ProcessingStage.failed, record.progress_pct, str(exc))
        raise
