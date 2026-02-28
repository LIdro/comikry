"""
Sound director agent — SFX prompt generation.

For each panel, this agent composes a short descriptive prompt that Audiocraft
will use to generate background SFX. It reads the panel's bubble texts and
infers the scene atmosphere.

Expected response:
[
  {"panel_id": "...", "prompt": "tense city street, distant sirens, rain"},
  ...
]
"""

from __future__ import annotations

import json

from backend.config import settings
from backend.models import Comic
from backend.pipeline.openrouter_client import chat_completion, extract_json

_SYSTEM_PROMPT = """\
You are a sound director for a comic audiobook. Given a list of panels with
their bubble texts, generate a short Audiocraft sound prompt for each panel.

The prompt should describe the ambient background sounds only (no dialogue, no
music unless it is diegetic). Keep it under 15 words. Be specific about
environment, mood, and any notable sound effects.

Respond ONLY with a JSON array:
[
  {"panel_id": "...", "prompt": "..."},
  ...
]
No markdown, no explanation.
"""


async def generate_sfx_prompts(comic: Comic) -> dict[str, str]:
    """
    Return a dict mapping panel_id → Audiocraft prompt string for every panel
    in the comic.
    """
    panels_summary = []
    for page in comic.pages:
        for panel in page.panels:
            texts = [b.text for b in panel.bubbles if b.text.strip()]
            panels_summary.append(
                {"panel_id": panel.panel_id, "bubble_texts": texts}
            )

    if not panels_summary:
        return {}

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(panels_summary)},
    ]

    result = await chat_completion(settings.vision_model, messages)
    raw = result["choices"][0]["message"]["content"].strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    sfx_data: list[dict] = extract_json(raw, context="sound_director_agent")
    return {item["panel_id"]: item["prompt"] for item in sfx_data}
