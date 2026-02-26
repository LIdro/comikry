"""
Shared async OpenRouter HTTP client.

All pipeline stages and agents import this to make model calls, so there is a
single place to configure auth headers, retries, and timeouts.
"""

from __future__ import annotations

import httpx

from backend.config import settings

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
