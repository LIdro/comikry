"""
Application settings loaded from environment variables or a .env file.

Copy .env.example to .env and fill in your keys before running.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # ── OpenRouter ────────────────────────────────────────────────────────────
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # ── Model IDs (all routed through OpenRouter) ─────────────────────────────
    vision_model: str = "google/gemini-2.5-flash-lite"          # panel detect, OCR, attribution
    tts_model: str = "openai/gpt-audio-mini"                    # voice generation
    image_gen_model_primary: str = "google/gemini-2.5-flash-image"   # normalization fill
    image_gen_model_fallback: str = "bytedance-seed/seedream-4.5"    # normalization fill fallback

    # ── Audiocraft (SFX) ──────────────────────────────────────────────────────
    # "cpu" for the web/local instance; set to "cuda" in Colab (T4 GPU).
    audiocraft_device: str = "cpu"

    # ── Panel normalisation ───────────────────────────────────────────────────
    panel_target_width: int = 1280
    panel_target_height: int = 720

    # ── PDF rendering ─────────────────────────────────────────────────────────
    pdf_render_dpi: int = 150

    # ── Storage ───────────────────────────────────────────────────────────────
    storage_root: str = "storage"

    # ── Server ────────────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000


settings = Settings()
