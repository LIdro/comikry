"""
Story director agent — Track B (Hierarchical Story Analysis).

Receives all StoryFragment objects from the parallel page-range agents and
synthesises them into a unified StoryBible.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from backend.config import settings
from backend.models import StoryBible, StoryFragment
from backend.pipeline.openrouter_client import chat_completion

_SYSTEM_PROMPT = """\
You are a senior story director for a comic audiobook production. You have
received a list of story fragments, each analysing a sub-range of pages.

Your task is to synthesise these fragments into a unified story bible.

Return ONLY a JSON object with this exact schema:
{
  "comic_id": "<comic_id>",
  "characters": [
    {
      "character_id": "char_001",
      "name": "<canonical name>",
      "description": "<merged physical appearance>",
      "personality": "<merged personality traits>",
      "arc_summary": "<full story arc across all pages>",
      "voice_tone_rules": "<speaking style cues>",
      "gender": "male|female|unknown",
      "age_group": "child|teen|adult|elder"
    }
  ],
  "per_panel_sfx": {
    "<panel_id>": "<audiocraft prompt ≤12 words>",
    ...
  },
  "genre": "<inferred genre>",
  "tone_summary": "<overall tone of the story>",
  "narrator_voice_style": "<style cues for the narrator voice>"
}

Rules for per_panel_sfx keys:
  panel_id format = "{comic_id}_pg{page:04d}_p{panel_order:03d}"
  e.g. "mycomic_pg0001_p001"

Rules for characters:
  - Deduplicate: if two fragments give the same character different IDs,
    reconcile them under one canonical ID (prefer earlier-appearing ID).
  - Merge descriptions and arc summaries coherently.

No markdown, no explanation — raw JSON only.
"""


async def synthesise_story_bible(
    fragments: list[StoryFragment],
    comic_id: str,
) -> StoryBible:
    """
    Merge all StoryFragment objects into a unified StoryBible.

    Sends text-only (no images) — the fragments are serialised as JSON.
    Saves ``story_bible.json`` to ``storage/{comic_id}/story_bible.json``.

    Parameters
    ----------
    fragments:
        All StoryFragment objects produced by the parallel page-range agents.
    comic_id:
        Stable comic identifier (used in panel_id keys and the saved filename).

    Returns
    -------
    StoryBible
        The parsed and validated story bible.
    """
    fragments_json = json.dumps(
        [_serialise_fragment(f) for f in fragments], indent=2
    )

    user_text = (
        f"comic_id: {comic_id}\n\n"
        f"Story fragments:\n{fragments_json}\n\n"
        "Synthesise these fragments into a unified story bible."
    )

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_text},
    ]

    result = await chat_completion(settings.vision_model, messages)
    raw = result["choices"][0]["message"]["content"].strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    data = json.loads(raw)
    data["comic_id"] = comic_id
    data["created_at"] = datetime.now(timezone.utc).isoformat()

    story_bible = StoryBible.model_validate(data)

    # Persist to disk
    out_path = Path(settings.storage_root) / comic_id / "story_bible.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(story_bible.model_dump_json(indent=2))

    return story_bible


def _serialise_fragment(fragment: StoryFragment) -> dict:
    """Convert a StoryFragment to a plain dict (tuple → list for JSON)."""
    d = fragment.model_dump()
    if isinstance(d.get("page_range"), tuple):
        d["page_range"] = list(d["page_range"])
    return d
