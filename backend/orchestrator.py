"""
Pipeline orchestrator.

Runs the full processing pipeline for one comic and updates the CacheRecord
progress at each stage so the frontend can poll for live status.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from backend.agents.character_agent import attribute_speakers
from backend.agents.sound_director_agent import generate_sfx_prompts
from backend.agents.voice_tone_agent import run_voice_tone_agent
from backend.cache import store
from backend.models import (
    CacheRecord,
    Comic,
    Page,
    ProcessingStage,
    Speaker,
)
from backend.pipeline.bubble_ocr import detect_bubbles
from backend.pipeline.normalizer import normalise_comic_panels
from backend.pipeline.panel_detection import detect_panels
from backend.pipeline.pdf_to_images import render_pdf
from backend.pipeline.sfx_generation import generate_sfx_for_comic
from backend.pipeline.tts_generation import generate_tts_for_comic


async def run_pipeline(
    pdf_path: str,
    comic_id: str,
    record: CacheRecord,
    normalization_enabled: bool = False,
    title: str = "",
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
    """

    def advance(stage: ProcessingStage, pct: int) -> None:
        store.update_stage(record, stage, pct)

    try:
        # ── Stage 1: PDF → images ──────────────────────────────────────────
        advance(ProcessingStage.pdf_to_images, 0)
        page_paths = render_pdf(pdf_path, comic_id)
        advance(ProcessingStage.pdf_to_images, 10)

        # Build initial Comic shell
        comic = Comic(
            comic_id=comic_id,
            title=title,
            pdf_hash=record.pdf_hash,
            normalization_enabled=normalization_enabled,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        pages: list[Page] = []
        for page_num, page_path in enumerate(page_paths, start=1):
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

        # ── Stage 4: Speaker attribution ──────────────────────────────────
        advance(ProcessingStage.speaker_attribution, 40)
        known_speakers: list[Speaker] = []
        for page in comic.pages:
            for panel in page.panels:
                panel.bubbles, new_speakers = await attribute_speakers(
                    panel, panel.bubbles, known_speakers
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
        sfx_prompts = await generate_sfx_prompts(comic)
        comic = await generate_sfx_for_comic(comic, sfx_prompts)
        advance(ProcessingStage.sfx_generation, 90)

        # ── Stage 8: Panel normalisation (optional) ───────────────────────
        if normalization_enabled:
            advance(ProcessingStage.normalization, 90)
            comic = await normalise_comic_panels(comic)
        advance(ProcessingStage.normalization, 95)

        # ── Persist manifest and mark done ────────────────────────────────
        store.save_manifest(comic)
        advance(ProcessingStage.done, 100)

        return comic

    except Exception as exc:
        store.update_stage(record, ProcessingStage.failed, record.progress_pct, str(exc))
        raise
