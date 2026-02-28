"""
Shared async OpenRouter HTTP client.

All pipeline stages and agents import this to make model calls, so there is a
single place to configure auth headers, retries, and timeouts.
"""

from __future__ import annotations

import json
import logging
import re

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

_HEADERS = {
    "Authorization": f"Bearer {settings.openrouter_api_key}",
    "Content-Type": "application/json",
    "HTTP-Referer": "https://comikry.app",
    "X-Title": "Comikry",
}

# Shared async client — instantiate once and reuse across requests.
openrouter_client = httpx.AsyncClient(
    base_url=settings.openrouter_base_url,
    headers=_HEADERS,
    timeout=120.0,
)


async def chat_completion(model: str, messages: list[dict], **kwargs) -> dict:
    """
    Call the OpenRouter chat completions endpoint.

    Returns the full response dict so callers can extract what they need.
    """
    payload = {"model": model, "messages": messages, **kwargs}
    response = await openrouter_client.post("/chat/completions", json=payload)
    response.raise_for_status()
    return response.json()


async def image_generation(model: str, prompt: str, **kwargs) -> dict:
    """
    Call the OpenRouter image generation endpoint.

    Returns the full response dict (data[0].b64_json or data[0].url).
    """
    payload = {"model": model, "prompt": prompt, **kwargs}
    response = await openrouter_client.post("/images/generations", json=payload)
    response.raise_for_status()
    return response.json()


def extract_json(raw: str, context: str = "") -> list | dict:
    """
    Robustly extract a JSON value (array or object) from a model response.

    Handles:
    - Pure JSON responses
    - Markdown code fences (```json ... ```)
    - Leading/trailing prose around the JSON
    - Empty or whitespace-only responses → raises ValueError with context

    Raises
    ------
    ValueError
        When no valid JSON can be extracted, with a message that includes
        the raw text so it appears in logs.
    """
    if not raw or not raw.strip():
        raise ValueError(
            f"Model returned an empty response{' (' + context + ')' if context else ''}."
        )

    text = raw.strip()

    # 1. Strip markdown fences: ```json\n...\n``` or ```\n...\n```
    fence = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    # 2. Try parsing as-is
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 3. Find the first [ or { and try from there
    for start_char, end_char in [("[", "]"), ("{", "}")]:
        start = text.find(start_char)
        end   = text.rfind(end_char)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass

    raise ValueError(
        f"Could not extract JSON from model response"
        f"{' (' + context + ')' if context else ''}.\n"
        f"Raw response (first 500 chars): {raw[:500]!r}"
    )
