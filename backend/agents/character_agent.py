"""
Character recognition agent — Stage 4 (speaker attribution).

Sends a panel image + all bubble texts to Gemini and asks it to cluster each
bubble to a character visible in the panel (or mark it as narrator).

Expected response:
[
  {"bubble_id": "pg001_p001_b001", "speaker_id": "char_0", "label": "Tintin"},
  {"bubble_id": "pg001_p001_b002", "speaker_id": "char_1", "label": "Haddock"},
  {"bubble_id": "pg001_p001_b003", "speaker_id": "narrator", "label": "Narrator"},
  ...
]

The agent also returns a list of new characters it discovered so the comic-level
speaker registry can be updated consistently.
"""

from __future__ import annotations

import base64
import json

from backend.config import settings
from backend.models import Bubble, Panel, Speaker
from backend.pipeline.openrouter_client import chat_completion

_SYSTEM_PROMPT = """\
You are a comic character recognition agent. Given a panel image and a list of
speech/thought/narration bubbles with their texts, assign each bubble to the
character who is speaking or thinking it.

Rules:
- Use visual proximity (a tail pointing toward a character) and context to
  attribute each bubble.
- Assign a stable speaker_id: reuse IDs you have already seen (provided in the
  known_speakers list) when the same character appears again.
- Use "narrator" as the speaker_id for narration boxes with no visual speaker.
- Infer a human-readable label (best-guess character name or a descriptor like
  "tall man in hat") for any new character.

Respond ONLY with a JSON object:
{
  "attributions": [
    {"bubble_id": "...", "speaker_id": "char_N", "label": "..."}
  ],
  "new_speakers": [
    {"speaker_id": "char_N", "label": "...", "gender": "...", "age_group": "..."}
  ]
}
No markdown, no explanation.
"""


def _encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


async def attribute_speakers(
    panel: Panel,
    bubbles: list[Bubble],
    known_speakers: list[Speaker],
) -> tuple[list[Bubble], list[Speaker]]:
    """
    Attribute speakers to all bubbles in a panel.

    Returns:
        - Updated bubbles list (speaker_id set on each)
        - List of newly discovered Speaker objects
    """
    known_list = [
        {"speaker_id": s.speaker_id, "label": s.inferred_label}
        for s in known_speakers
    ]
    bubble_list = [
        {"bubble_id": b.bubble_id, "text": b.text, "type": b.bubble_type.value}
        for b in bubbles
    ]

    b64 = _encode_image(panel.image_path)

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                },
                {
                    "type": "text",
                    "text": json.dumps(
                        {"known_speakers": known_list, "bubbles": bubble_list}
                    ),
                },
            ],
        },
    ]

    result = await chat_completion(settings.vision_model, messages)
    raw = result["choices"][0]["message"]["content"].strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    data = json.loads(raw)

    # Apply attributions
    attr_map = {a["bubble_id"]: a for a in data.get("attributions", [])}
    for bubble in bubbles:
        attr = attr_map.get(bubble.bubble_id)
        if attr:
            bubble.speaker_id = attr["speaker_id"]

    # Collect new speakers
    new_speakers: list[Speaker] = []
    for ns in data.get("new_speakers", []):
        new_speakers.append(
            Speaker(
                speaker_id=ns["speaker_id"],
                inferred_label=ns.get("label", ""),
                gender=ns.get("gender", ""),
                age_group=ns.get("age_group", ""),
            )
        )

    return bubbles, new_speakers
