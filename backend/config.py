"""
Application settings loaded from environment variables or a .env file.

Copy .env.example to .env and fill in your keys before running.

Hot-reload
----------
Call ``reload_settings()`` (or POST /api/reload-config) to re-read the .env
file without restarting the server.  Useful when you add SFX_API_URL to .env
after the server is already running.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8",
        # Re-read the file on every instantiation so reload_settings() works
        env_file_override=False,
    )

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

    # ── SFX API proxy (optional) ──────────────────────────────────────────────
    # If set, SFX generation will POST to this URL instead of running AudioGen
    # locally. Use the optional Colab SFX server cell to get this URL.
    # Example: SFX_API_URL=https://xxxx-colab-tunnel.ngrok.io
    sfx_api_url: str = ""

    # ── Gemini Files API (optional, opt-in) ───────────────────────────────────
    # When use_gemini_files_api=True, page images are uploaded once to the
    # Gemini Files API and referenced by URI for all vision calls (faster, no
    # base64 overhead). The base64 path is used when this is False.
    google_ai_api_key: str = ""
    use_gemini_files_api: bool = False

    # ── Panel normalisation ───────────────────────────────────────────────────
    panel_target_width: int = 1280
    panel_target_height: int = 720

    # ── PDF rendering ─────────────────────────────────────────────────────────
    pdf_render_dpi: int = 150
    # Batched parallel rendering settings (Task 4-7)
    pdf_render_batch_size: int = 3
    pdf_render_max_workers: int = 8

    # ── Storage ───────────────────────────────────────────────────────────────
    storage_root: str = "storage"

    # ── Track B (Hierarchical Story Analysis) ────────────────────────────────
    track_b_pages_per_agent: int = 10
    track_b_overlap_pages: int = 2

    # ── Server ────────────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000


# ── Global singleton + hot-reload helper ─────────────────────────────────────
settings = Settings()


def reload_settings() -> Settings:
    """
    Re-read .env from disk and update the global ``settings`` singleton *in place*.

    Because every backend module does ``from backend.config import settings`` they
    all hold a reference to the same object.  Mutating the object's ``__dict__``
    means every module immediately sees the new values — no restart required.

    Call this (or POST /api/reload-config) after editing .env while the server
    is running, e.g. to activate a newly added SFX_API_URL.
    """
    fresh = Settings()
    settings.__dict__.update(fresh.__dict__)
    return settings


settings = Settings()
