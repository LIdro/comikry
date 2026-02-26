"""
Voice and tone director agent — Stage 6 (voice assignment + emotion tagging).

Two responsibilities:
1. Assign a TTS voice_id to each Speaker based on inferred gender, age, and
   personality. The mapping uses the GPT Audio voice roster.
2. Tag each Bubble with an emotion_tag (e.g. "angry", "happy", "sad",
   "excited", "neutral") by reading the bubble text and context.

Voice roster (openai/gpt-audio-mini via OpenRouter):
  alloy    – neutral adult
  echo     – male adult
  fable    – warm female
  onyx     – deep male adult
  nova     – energetic female
  shimmer  – soft female
  ash      – calm adult male
  sage     – authoritative adult
  coral    – young female
  verse    – young male narrator
"""

from __future__ import annotations

import json

from backend.config import settings
from backend.models import Bubble, Comic, Speaker
from backend.pipeline.openrouter_client import chat_completion

# ── Static voice assignment heuristic ────────────────────────────────────────
# Used first so we don't need an LLM call for every speaker.

_VOICE_MAP: dict[tuple[str, str], str] = {
    ("male", "child"): "verse",
    ("male", "teen"): "verse",
    ("male", "adult"): "echo",
    ("male", "elder"): "onyx",
    ("female", "child"): "coral",
    ("female", "teen"): "coral",
    ("female", "adult"): "nova",
    ("female", "elder"): "shimmer",
    ("unknown", "adult"): "alloy",
}

_NARRATOR_VOICE = "sage"


def assign_voices(speakers: list[Speaker]) -> list[Speaker]:
    """
    Assign a TTS voice_id to each speaker using the static heuristic.
    Speakers whose speaker_id is 'narrator' always get the narrator voice.
    """
    for speaker in speakers:
        if speaker.speaker_id == "narrator":
            speaker.voice_id = _NARRATOR_VOICE
            continue
        key = (speaker.gender or "unknown", speaker.age_group or "adult")
        speaker.voice_id = _VOICE_MAP.get(key, "alloy")
    return speakers


# ── Emotion tagging via Gemini ────────────────────────────────────────────────

_EMOTION_SYSTEM_PROMPT = """\
You are a comic voice director. Given a list of speech bubbles (with text and
speaker labels), infer the emotion for each bubble.

Choose one emotion per bubble from:
  neutral, happy, sad, angry, excited, scared, surprised, disgusted, sarcastic,
  whispering, shouting

Respond ONLY with a JSON array:
[
  {"bubble_id": "...", "emotion": "..."},
  ...
]
No markdown, no explanation.
"""


async def tag_emotions(bubbles: list[Bubble], speakers: list[Speaker]) -> list[Bubble]:
    """
    Tag each bubble with an emotion using Gemini.
    """
    speaker_map = {s.speaker_id: s.inferred_label for s in speakers}
    bubble_list = [
        {
            "bubble_id": b.bubble_id,
            "text": b.text,
            "speaker": speaker_map.get(b.speaker_id or "", "unknown"),
        }
        for b in bubbles
        if b.text.strip()
    ]

    if not bubble_list:
        return bubbles

    messages = [
        {"role": "system", "content": _EMOTION_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(bubble_list)},
    ]

    result = await chat_completion(settings.vision_model, messages)
    raw = result["choices"][0]["message"]["content"].strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    emotion_data: list[dict] = json.loads(raw)
    emotion_map = {e["bubble_id"]: e["emotion"] for e in emotion_data}

    for bubble in bubbles:
        if bubble.bubble_id in emotion_map:
            bubble.emotion_tag = emotion_map[bubble.bubble_id]

    return bubbles


async def run_voice_tone_agent(comic: Comic) -> Comic:
    """
    Full voice/tone pass over the comic:
    1. Assign TTS voices to all speakers.
    2. Tag emotions on all bubbles.
    """
    comic.speakers = assign_voices(comic.speakers)

    for page in comic.pages:
        for panel in page.panels:
            panel.bubbles = await tag_emotions(panel.bubbles, comic.speakers)

    return comic
