"""
Stage 2 — Panel detection and ordering.

Sends a rendered page image to Gemini and asks it to return panel bounding
boxes in reading order as structured JSON.

Expected Gemini response (parsed):
[
  {"order": 1, "x": 10, "y": 10, "w": 300, "h": 200},
  ...
]
"""

from __future__ import annotations

import base64
from pathlib import Path

from backend.config import settings
from backend.models import BBox, Panel
from backend.pipeline.openrouter_client import chat_completion, extract_json

_SYSTEM_PROMPT = """\
You are a comic panel analyser. Given an image of a comic page, identify every
panel and return them in reading order (left-to-right, top-to-bottom for Western
comics; right-to-left for manga).

Respond ONLY with a JSON array. Each element must have these integer fields:
  order  – 1-based reading order index
  x      – left edge in pixels
  y      – top edge in pixels
  w      – width in pixels
  h      – height in pixels

No markdown, no explanation — raw JSON only.
"""


def _encode_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode()


async def detect_panels(
    page_image_path: str,
    page_id: str,
    comic_id: str,
) -> list[Panel]:
    """
    Detect panels on a single page image.

    Returns a list of Panel objects (without bubbles filled in yet).
    Cropped panel images are saved to storage/{comic_id}/panels/.

    If ``settings.use_gemini_files_api`` is True, the image is uploaded to the
    Gemini Files API and referenced by URI; otherwise base64 encoding is used.
    """
    from backend.pipeline.gemini_files import upload_image
    from PIL import Image as PILImage

    uri = await upload_image(page_image_path)

    if uri:
        # ── Gemini Files API path (direct google-generativeai SDK) ────────────
        import google.generativeai as genai  # type: ignore

        genai.configure(api_key=settings.google_ai_api_key)
        model = genai.GenerativeModel(settings.vision_model)
        file_ref = genai.get_file(uri)
        response = model.generate_content(
            [_SYSTEM_PROMPT, file_ref, "Detect all panels on this comic page."]
        )
        raw = response.text.strip()
    else:
        # ── Base64 fallback (existing OpenRouter path) ─────────────────────────
        b64 = _encode_image(page_image_path)

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                    {"type": "text", "text": "Detect all panels on this comic page."},
                ],
            },
        ]

        result = await chat_completion(settings.vision_model, messages)
        raw = result["choices"][0]["message"]["content"].strip()

    # Strip accidental markdown fences
    panel_data: list[dict] = extract_json(raw, context=f"panel_detection page={page_id}")

    out_dir = Path(settings.storage_root) / comic_id / "panels"
    out_dir.mkdir(parents=True, exist_ok=True)

    page_img = PILImage.open(page_image_path)
    panels: list[Panel] = []

    for item in sorted(panel_data, key=lambda d: d["order"]):
        idx = item["order"]
        bbox = BBox(x=item["x"], y=item["y"], w=item["w"], h=item["h"])
        panel_id = f"{page_id}_p{idx:03d}"

        # Crop and save panel image
        crop = page_img.crop((bbox.x, bbox.y, bbox.x + bbox.w, bbox.y + bbox.h))
        panel_path = out_dir / f"{panel_id}.png"
        crop.save(str(panel_path), "PNG")

        panels.append(
            Panel(
                panel_id=panel_id,
                order_index=idx,
                bbox=bbox,
                image_path=str(panel_path),
            )
        )

    return panels
