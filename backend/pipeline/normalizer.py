"""
Stage 7 — Panel image normalisation.

Resizes panel images to the target resolution (settings.panel_target_width ×
settings.panel_target_height). If the panel's aspect ratio differs from the
target, the panel is centred on a canvas and the surrounding blank area is
filled using an AI image generation model (google/gemini-2.5-flash-image with
a fallback to bytedance-seed/seedream-4.5, both via OpenRouter).

Normalised images are saved to:
  storage/{comic_id}/panels/normalised/{panel_id}.png
"""

from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image as PILImage

from backend.config import settings
from backend.models import Comic, Panel
from backend.pipeline.openrouter_client import image_generation


def _build_fill_prompt(panel_image_path: str) -> str:
    return (
        "Comic book panel background continuation. "
        "Match the art style, colour palette, and shading of the source image. "
        "Fill the blank area seamlessly. No new characters or text."
    )


async def _ai_fill(
    panel_img: PILImage.Image,
    canvas: PILImage.Image,
    prompt: str,
) -> PILImage.Image:
    """
    Ask the image generation model to outpaint the blank canvas areas.

    Falls back to the secondary model if the primary fails.
    For MVP, if both fail, the plain canvas (letterboxed) is returned.
    """
    # Encode composite as base64 for the prompt (used as reference image context)
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()

    for model in (settings.image_gen_model_primary, settings.image_gen_model_fallback):
        try:
            result = await image_generation(
                model=model,
                prompt=prompt,
                n=1,
                size=f"{settings.panel_target_width}x{settings.panel_target_height}",
                # Pass the composite as a reference where the API supports it
                image=f"data:image/png;base64,{b64}",
            )
            img_data = result["data"][0]
            if "b64_json" in img_data:
                raw = base64.b64decode(img_data["b64_json"])
            else:
                import httpx
                raw = httpx.get(img_data["url"]).content
            return PILImage.open(io.BytesIO(raw)).convert("RGBA")
        except Exception:
            continue  # try fallback model

    # Both models failed — return plain letterboxed canvas
    return canvas


async def normalise_panel(panel: Panel, comic_id: str) -> str:
    """
    Normalise a single panel image to the target resolution.

    Returns the path of the normalised image.
    """
    tw = settings.panel_target_width
    th = settings.panel_target_height

    src = PILImage.open(panel.image_path).convert("RGBA")
    src.thumbnail((tw, th), PILImage.LANCZOS)

    canvas = PILImage.new("RGBA", (tw, th), (0, 0, 0, 255))
    x_off = (tw - src.width) // 2
    y_off = (th - src.height) // 2
    canvas.paste(src, (x_off, y_off))

    needs_fill = src.width < tw or src.height < th
    if needs_fill:
        prompt = _build_fill_prompt(panel.image_path)
        canvas = await _ai_fill(src, canvas, prompt)

    out_dir = Path(settings.storage_root) / comic_id / "panels" / "normalised"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{panel.panel_id}.png"
    canvas.convert("RGB").save(str(out_path), "PNG")

    return str(out_path)


async def normalise_comic_panels(comic: Comic) -> Comic:
    """
    Normalise all panel images in the comic if normalization is enabled.
    """
    if not comic.normalization_enabled:
        return comic

    for page in comic.pages:
        for panel in page.panels:
            norm_path = await normalise_panel(panel, comic.comic_id)
            panel.normalized_image_path = norm_path
            panel.normalization_fill_model = settings.image_gen_model_primary

    return comic
