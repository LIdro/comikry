"""
Page-range agent — Track B (Hierarchical Story Analysis).

Analyses a sub-range of pages and produces a StoryFragment that the Story
Director agent will later merge into the full StoryBible.
"""

from __future__ import annotations

import base64
import json

from backend.config import settings
from backend.models import CharacterProfile, StoryFragment
from backend.pipeline.openrouter_client import chat_completion

_SYSTEM_PROMPT = """\
You are a comic story analyst. Given a sequence of comic page images and a list
of already-known character profiles, analyse the pages and return a structured
JSON summary.

Your response MUST be a single JSON object with this exact schema:
{
  "page_range": [<first_page_int>, <last_page_int>],
  "characters": [
    {
      "character_id": "char_001",
      "name": "<inferred name or label>",
      "description": "<physical appearance>",
      "personality": "<personality traits>",
      "arc_summary": "<how this character changes across these pages>",
      "voice_tone_rules": "<speaking style cues>",
      "gender": "male|female|unknown",
      "age_group": "child|teen|adult|elder"
    }
  ],
  "events": [
    {"pages": [<int>, ...], "summary": "<event summary>", "tone": "<tone>"}
  ],
  "sfx_palette": [
    {"page": <int>, "panel_order": <int>, "prompt": "<audiocraft prompt ≤12 words>"}
  ],
  "unresolved": ["<open question or ambiguity string>", ...]
}

Rules:
- Reuse character_ids from known_characters when the same character appears.
- Only create a new character_id when a genuinely new character appears.
- sfx_palette should have one entry per panel with a short audiocraft prompt.
- Respond ONLY with the JSON object. No markdown, no explanation.
"""


def _encode_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode()


async def analyse_page_range(
    page_image_paths: list[str],
    page_range: tuple[int, int],
    comic_id: str,
    known_characters: list[CharacterProfile],
) -> StoryFragment:
    """
    Analyse a sub-range of pages and return a StoryFragment.

    Parameters
    ----------
    page_image_paths:
        Absolute paths to the page images for this range (already sliced).
    page_range:
        (first_page, last_page) inclusive 1-based indices for labelling.
    comic_id:
        Used for Gemini Files API uploads (comic identity).
    known_characters:
        Characters already discovered in previous fragments; passed as JSON
        context so Gemini reuses IDs instead of inventing new ones.

    Returns
    -------
    StoryFragment
        Parsed and validated story fragment for this page range.
    """
    from backend.pipeline.gemini_files import upload_image

    known_characters_json = json.dumps(
        [cp.model_dump() for cp in known_characters], indent=2
    )
    user_text = (
        f"Page range: {page_range[0]}–{page_range[1]}\n"
        f"Known characters:\n{known_characters_json}\n\n"
        "Analyse these comic pages and return the structured JSON."
    )

    # Try Gemini Files API path first; fall back to base64
    uris: list[str | None] = [
        await upload_image(p) for p in page_image_paths
    ]
    use_files_api = all(u is not None for u in uris)

    if use_files_api:
        import google.generativeai as genai  # type: ignore

        genai.configure(api_key=settings.google_ai_api_key)
        model = genai.GenerativeModel(settings.vision_model)
        file_refs = [genai.get_file(u) for u in uris]  # type: ignore[arg-type]
        response = model.generate_content([_SYSTEM_PROMPT, *file_refs, user_text])
        raw = response.text.strip()
    else:
        # Base64 fallback
        content_parts: list[dict] = []
        for path in page_image_paths:
            b64 = _encode_image(path)
            content_parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                }
            )
        content_parts.append({"type": "text", "text": user_text})

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": content_parts},
        ]
        result = await chat_completion(settings.vision_model, messages)
        raw = result["choices"][0]["message"]["content"].strip()

    # Strip markdown fences
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    data = json.loads(raw)
    # Normalise page_range from list to tuple if necessary
    if isinstance(data.get("page_range"), list):
        data["page_range"] = tuple(data["page_range"])

    return StoryFragment.model_validate(data)
