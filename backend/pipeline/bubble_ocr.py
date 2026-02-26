"""
Stage 3 — Bubble detection and OCR.

Sends a panel image to Gemini and asks it to locate all speech/thought/narration
bubbles and extract their text.

Expected Gemini response (parsed):
[
  {
    "order": 1,
    "type": "speech",
    "x": 20, "y": 10, "w": 80, "h": 40,
    "text": "Hello there!",
    "confidence": 0.97
  },
  ...
]
"""

from __future__ import annotations

import base64
import json

from backend.config import settings
from backend.models import BBox, Bubble, BubbleType
from backend.pipeline.openrouter_client import chat_completion

_SYSTEM_PROMPT = """\
You are a comic book OCR specialist. Given a panel image, find every speech
bubble, thought bubble, narration box, and sound-effect text.

For each one, return a JSON object with:
  order      – 1-based reading order within the panel
  type       – one of: "speech", "thought", "narration", "sfx"
  x, y, w, h – bounding box in pixels (integers)
  text       – the verbatim text inside the bubble (preserve punctuation)
  confidence – float 0.0–1.0, your OCR confidence for the text

Respond ONLY with a JSON array. No markdown, no explanation.
"""


def _encode_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode()


async def detect_bubbles(panel: "Panel") -> list[Bubble]:  # type: ignore[name-defined]
    """
    Detect and OCR all bubbles in a single panel image.

    Returns a list of Bubble objects (speaker_id not assigned yet).
    """
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
                {"type": "text", "text": "Find all bubbles and extract their text."},
            ],
        },
    ]

    result = await chat_completion(settings.vision_model, messages)
    raw = result["choices"][0]["message"]["content"].strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    bubble_data: list[dict] = json.loads(raw)
    bubbles: list[Bubble] = []

    for item in sorted(bubble_data, key=lambda d: d["order"]):
        idx = item["order"]
        bubble_id = f"{panel.panel_id}_b{idx:03d}"

        bubble_type = BubbleType(item.get("type", "speech"))

        bubbles.append(
            Bubble(
                bubble_id=bubble_id,
                order_index=idx,
                bubble_type=bubble_type,
                bbox=BBox(
                    x=item["x"], y=item["y"], w=item["w"], h=item["h"]
                ),
                text=item.get("text", ""),
                ocr_confidence=float(item.get("confidence", 1.0)),
            )
        )

    return bubbles
