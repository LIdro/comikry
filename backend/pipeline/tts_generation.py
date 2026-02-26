"""
Stage 5 — TTS generation.

Calls openai/gpt-audio-mini via OpenRouter to synthesise one audio file per
bubble. Audio is saved to storage/{comic_id}/audio/voice/{bubble_id}.mp3.

The voice_id on each bubble's speaker, plus the emotion_tag, are passed as
instructions to the TTS model.
"""

from __future__ import annotations

import base64
from pathlib import Path

import httpx

from backend.config import settings
from backend.models import Bubble, Comic
from backend.pipeline.openrouter_client import openrouter_client

_TTS_ENDPOINT = "/audio/speech"


async def generate_tts_for_bubble(
    bubble: Bubble,
    voice_id: str,
    comic_id: str,
) -> str:
    """
    Generate TTS audio for a single bubble.

    Returns the relative path (from project root) of the saved audio file.
    """
    if not bubble.text.strip():
        return ""

    instruction = f"Speak with a {bubble.emotion_tag or 'neutral'} tone."

    payload = {
        "model": settings.tts_model,
        "input": bubble.text,
        "voice": voice_id,
        "instructions": instruction,
        "response_format": "mp3",
    }

    response = await openrouter_client.post(_TTS_ENDPOINT, json=payload)
    response.raise_for_status()

    out_dir = Path(settings.storage_root) / comic_id / "audio" / "voice"
    out_dir.mkdir(parents=True, exist_ok=True)
    audio_path = out_dir / f"{bubble.bubble_id}.mp3"
    audio_path.write_bytes(response.content)

    return str(audio_path)


async def generate_tts_for_comic(comic: Comic) -> Comic:
    """
    Run TTS for every bubble in the comic.

    Mutates bubble.tts_audio_path in place and returns the updated comic.
    """
    # Build speaker_id → voice_id lookup
    voice_map = {s.speaker_id: s.voice_id for s in comic.speakers}

    for page in comic.pages:
        for panel in page.panels:
            for bubble in panel.bubbles:
                if bubble.bubble_type.value in ("sfx",):
                    continue  # SFX text is not spoken
                voice_id = voice_map.get(bubble.speaker_id or "", "alloy")
                path = await generate_tts_for_bubble(bubble, voice_id, comic.comic_id)
                bubble.tts_audio_path = path

    return comic
