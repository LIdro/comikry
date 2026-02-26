"""
Comikry data models.

All models are plain Pydantic v2 dataclasses so they can be serialised to/from
the JSON manifest stored on disk and returned by the API unchanged.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ── Enumerations ──────────────────────────────────────────────────────────────

class BubbleType(str, Enum):
    speech = "speech"
    thought = "thought"
    narration = "narration"
    sfx = "sfx"


class ProcessingStage(str, Enum):
    queued = "queued"
    pdf_to_images = "pdf_to_images"
    panel_detection = "panel_detection"
    bubble_ocr = "bubble_ocr"
    speaker_attribution = "speaker_attribution"
    voice_assignment = "voice_assignment"
    tts_generation = "tts_generation"
    sfx_generation = "sfx_generation"
    normalization = "normalization"
    done = "done"
    failed = "failed"


# ── Bounding box ──────────────────────────────────────────────────────────────

class BBox(BaseModel):
    """Pixel coordinates: (x, y) top-left corner, width and height."""
    x: int
    y: int
    w: int
    h: int


# ── Speaker / voice ───────────────────────────────────────────────────────────

class Speaker(BaseModel):
    speaker_id: str                         # stable across panels, e.g. "char_0"
    inferred_label: str = ""                # best-effort name from Gemini, e.g. "Tintin"
    voice_id: str = ""                      # TTS voice ID assigned by voice_assignment stage
    gender: str = ""                        # "male" | "female" | "unknown"
    age_group: str = ""                     # "child" | "teen" | "adult" | "elder"
    personality_tags: list[str] = Field(default_factory=list)


# ── Bubble ────────────────────────────────────────────────────────────────────

class Bubble(BaseModel):
    bubble_id: str                          # "{panel_id}_b{index}"
    order_index: int                        # reading order within the panel
    bubble_type: BubbleType = BubbleType.speech
    bbox: BBox
    text: str = ""
    language: str = "en"                    # BCP-47 language code
    speaker_id: Optional[str] = None       # None for narration / sfx
    emotion_tag: str = ""                   # e.g. "angry", "happy", "neutral"
    tts_audio_path: Optional[str] = None   # relative path inside storage/
    ocr_confidence: float = 1.0            # 0.0–1.0; flagged below threshold


# ── Panel ─────────────────────────────────────────────────────────────────────

class Panel(BaseModel):
    panel_id: str                           # "{page_id}_p{index}"
    order_index: int                        # reading order within the page
    bbox: BBox                              # coordinates on the original page image
    image_path: str = ""                    # relative path to cropped panel image
    normalized_image_path: Optional[str] = None   # set when normalization is enabled
    normalization_fill_model: Optional[str] = None
    sfx_audio_path: Optional[str] = None   # background SFX for the panel
    bubbles: list[Bubble] = Field(default_factory=list)


# ── Page ──────────────────────────────────────────────────────────────────────

class Page(BaseModel):
    page_id: str                            # "{comic_id}_pg{number}"
    page_number: int                        # 1-based
    image_path: str = ""                    # relative path to full rendered page image
    panels: list[Panel] = Field(default_factory=list)


# ── Comic (root manifest) ─────────────────────────────────────────────────────

class Comic(BaseModel):
    comic_id: str                           # ULID
    title: str = ""
    pdf_hash: str                           # SHA-256 of original PDF
    speakers: list[Speaker] = Field(default_factory=list)
    pages: list[Page] = Field(default_factory=list)
    source_language: str = "en"
    available_languages: list[str] = Field(default_factory=lambda: ["en"])
    normalization_enabled: bool = False
    created_at: str = ""                    # ISO-8601 UTC


# ── Cache record ──────────────────────────────────────────────────────────────

class CacheRecord(BaseModel):
    comic_id: str
    pdf_hash: str
    manifest_path: str                      # relative path to comic JSON manifest
    playback_token: str                     # URL-safe token for /play/{token}
    processing_stage: ProcessingStage = ProcessingStage.queued
    progress_pct: int = 0                   # 0–100
    error_message: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""


# ── Playback state (frontend uses this; not persisted) ───────────────────────

class PlaybackState(BaseModel):
    comic_id: str
    current_page: int = 0
    current_panel: int = 0
    current_bubble: int = 0
    voice_volume: float = 1.0              # 0.0–1.0
    sfx_volume: float = 0.4               # 0.0–1.0
    playback_speed: float = 1.0
    language: str = "en"
