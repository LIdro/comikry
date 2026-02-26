"""
Stage 6 — SFX generation via Audiocraft (AudioGen).

Uses facebook/audiogen-small (≈ 300 MB) rather than the medium/large variants
to keep Colab disk usage low.

Device strategy
---------------
* Web / local instance  → CPU (set AUDIOCRAFT_DEVICE=cpu in .env, the default).
  audiogen-small on CPU is slow but produces correct output and requires no GPU.
* Colab prototype       → CUDA (set AUDIOCRAFT_DEVICE=cuda in the Colab config
  cell or .env).  The T4 instance handles audiogen-small with ease.

The model is lazy-loaded on first use and reused across all panels. If
Audiocraft is not installed the module falls back to a silent placeholder so
the rest of the pipeline still runs.

Audio is saved to storage/{comic_id}/audio/sfx/{panel_id}.wav then converted
to MP3 with ffmpeg if available (saves ~60 % disk vs WAV).

Installation (Colab / local):
    pip install -q audiocraft==1.3.0
    # gradio pin only needed if you are running the AudioCraft web UI:
    # pip install -q gradio==4.44.1
    # Python 3.9 or 3.10 recommended; PyTorch >= 2.0 required.
    # FFmpeg must be on PATH for MP3 conversion.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from backend.config import settings
from backend.models import Comic, Panel

# ── Model — loaded once, reused across all panels ────────────────────────────
# AudioGen-small is ~300 MB on disk vs ~1.5 GB for medium.
# Set AUDIOCRAFT_CACHE_DIR env var to redirect model weights away from /root
# (useful in Colab where the home partition is small).
_SFX_DURATION_SEC = 4        # keep short to save VRAM and disk
_MODEL_ID = "facebook/audiogen-small"

_sfx_model = None  # lazy-loaded on first use


def _load_model():
    global _sfx_model
    if _sfx_model is not None:
        return _sfx_model
    try:
        import torch
        from audiocraft.models import AudioGen  # type: ignore

        device = settings.audiocraft_device
        # Validate and fall back gracefully: if "cuda" is requested but no GPU
        # is available (e.g. developer laptop), silently use CPU instead.
        if device == "cuda" and not torch.cuda.is_available():
            device = "cpu"

        _sfx_model = AudioGen.get_pretrained(_MODEL_ID, device=device)
        _sfx_model.set_generation_params(duration=_SFX_DURATION_SEC)
    except ImportError:
        _sfx_model = None  # audiocraft not installed — stub mode
    return _sfx_model


def _wav_to_mp3(wav_path: Path) -> Path:
    """Convert WAV → MP3 with ffmpeg (128 kbps). Returns the MP3 path."""
    mp3_path = wav_path.with_suffix(".mp3")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(wav_path), "-b:a", "128k", str(mp3_path)],
            check=True, capture_output=True,
        )
        wav_path.unlink(missing_ok=True)  # delete WAV after conversion
        return mp3_path
    except (subprocess.CalledProcessError, FileNotFoundError):
        # ffmpeg not available — keep the WAV
        return wav_path


async def _generate_sfx_audio(prompt: str, out_path: Path) -> Path:
    """
    Generate SFX for one prompt. Returns the final saved file path (MP3 or WAV).

    Runs the blocking Audiocraft inference in a thread executor so the async
    event loop is not blocked.
    """
    model = _load_model()

    if model is None:
        # Stub: silent placeholder when Audiocraft is not installed
        out_path.write_bytes(b"\x00")
        return out_path

    def _infer():
        from audiocraft.data.audio import audio_write  # type: ignore
        import torch

        with torch.inference_mode():
            wav = model.generate([prompt])  # shape: (1, 1, samples)

        # audio_write saves as WAV; stem = path without extension
        stem = str(out_path.with_suffix(""))
        audio_write(
            stem,
            wav[0].cpu(),
            model.sample_rate,
            strategy="loudness",
            loudness_compressor=True,
        )
        saved_wav = Path(stem + ".wav")
        return _wav_to_mp3(saved_wav)

    loop = asyncio.get_event_loop()
    final_path = await loop.run_in_executor(None, _infer)
    return final_path


async def generate_sfx_for_panel(
    panel: Panel,
    sfx_prompt: str,
    comic_id: str,
) -> str:
    """
    Generate background SFX audio for a panel and return its file path.
    """
    out_dir = Path(settings.storage_root) / comic_id / "audio" / "sfx"
    out_dir.mkdir(parents=True, exist_ok=True)
    # Use a WAV stem; _generate_sfx_audio will convert to MP3 if ffmpeg is available
    out_path = out_dir / f"{panel.panel_id}.wav"
    final_path = await _generate_sfx_audio(sfx_prompt, out_path)
    panel.sfx_audio_path = str(final_path)
    return str(final_path)


async def generate_sfx_for_comic(comic: Comic, sfx_prompts: dict[str, str]) -> Comic:
    """
    Run SFX generation for every panel.

    *sfx_prompts* maps panel_id → prompt string (produced by the sound director
    agent). Panels without a prompt get a generic ambient fill.
    """
    for page in comic.pages:
        for panel in page.panels:
            prompt = sfx_prompts.get(panel.panel_id, "soft ambient background, comic book")
            await generate_sfx_for_panel(panel, prompt, comic.comic_id)
    return comic
