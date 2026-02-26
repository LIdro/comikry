<div align="center">

# 🎙️ Comikry

**Turn any comic PDF into a fully narrated, browser-based audio experience.**

Comikry detects panels and speech bubbles, assigns distinct voices to every character, generates ambient sound effects, and plays the whole thing back panel-by-panel — all automatically, no manual tagging required.

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![OpenRouter](https://img.shields.io/badge/Models-OpenRouter-6C47FF)](https://openrouter.ai/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

---

## ✨ Features

- **Automatic panel detection** — Gemini vision finds and orders every panel in reading sequence
- **Bubble OCR** — extracts text from speech, thought, narration, and SFX bubbles
- **Character voice assignment** — gender, age, and personality are inferred; a unique TTS voice is auto-assigned to every character with no user input
- **Emotion-aware TTS** — each line is spoken with the correct emotional tone (happy, angry, whispering, shouting, …)
- **Ambient SFX** — Audiocraft AudioGen generates a background soundscape per panel
- **Panel image normalisation** *(optional)* — pads or outpaints panels to a standard 1280 × 720 canvas using AI image generation
- **Smart caching** — SHA-256 PDF hashing means re-uploading the same comic loads instantly from cache
- **Shareable URLs** — every processed comic gets a unique `/play/{token}` URL you can send to anyone
- **Full-screen panel viewer** — bubble highlights animate in sync with the audio playback
- **Keyboard shortcuts** — `Space` play/pause · `←` / `→` previous/next panel · `[` / `]` speed down/up

---

## 🚀 Quick start

### Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.10 + |
| [poppler](https://poppler.freedesktop.org/) | any recent (for `pdf2image`) |
| [ffmpeg](https://ffmpeg.org/) | any recent (for SFX MP3 conversion) |
| [OpenRouter API key](https://openrouter.ai/) | — |

Install system dependencies (Ubuntu / Debian):

```bash
sudo apt-get install -y poppler-utils ffmpeg
```

### 1 — Clone and configure

```bash
git clone https://github.com/LIdro/comikry.git
cd comikry
cp .env.example .env
# Open .env and set OPENROUTER_API_KEY=sk-or-v1-...
```

### 2 — Start the app

```bash
chmod +x start.sh
./start.sh
```

That's it. The script creates a virtual environment, installs all dependencies, and launches the server.

Open **http://localhost:8000** in your browser, upload a comic PDF, and press play.

#### Start script options

```
./start.sh              # development mode with auto-reload (default)
./start.sh --prod       # production mode, 4 workers, no reload
./start.sh --port 9000  # custom port
./start.sh --host 127.0.0.1 --port 9000
```

### Manual start (without the script)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

---

## 🗂️ Project layout

```
comikry/
├── start.sh                    # one-command launcher
├── requirements.txt
├── .env.example                # copy to .env and fill in keys
│
├── backend/
│   ├── main.py                 # FastAPI app entry point
│   ├── config.py               # settings loaded from .env
│   ├── models.py               # Pydantic v2 data models
│   ├── orchestrator.py         # runs all pipeline stages in order
│   ├── pipeline/
│   │   ├── openrouter_client.py    # shared async HTTP client
│   │   ├── pdf_to_images.py        # PDF → PNG pages (pdf2image)
│   │   ├── panel_detection.py      # Gemini: panel bboxes in reading order
│   │   ├── bubble_ocr.py           # Gemini: bubble text + bbox
│   │   ├── tts_generation.py       # GPT Audio Mini: voice per bubble
│   │   ├── sfx_generation.py       # Audiocraft AudioGen: SFX per panel
│   │   └── normalizer.py           # AI outpaint to standard canvas size
│   ├── agents/
│   │   ├── character_agent.py      # clusters bubbles → speakers
│   │   ├── voice_tone_agent.py     # auto voice + emotion tags
│   │   └── sound_director_agent.py # crafts Audiocraft prompts
│   ├── cache/
│   │   └── store.py                # PDF hashing, manifest CRUD, token lookup
│   └── api/
│       └── routes.py               # REST endpoints
│
├── frontend/
│   ├── index.html              # single-page app shell
│   ├── style.css
│   └── viewer/
│       └── viewer.js           # upload → progress → player (vanilla JS)
│
├── colab/
│   └── prototype.ipynb         # end-to-end pipeline validation notebook
│
├── tests/
│   ├── conftest.py
│   ├── test_models.py
│   ├── test_cache.py
│   ├── test_api.py
│   └── test_pipeline.py
│
└── storage/                    # runtime cache — gitignored
```

---

## 🔌 API reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/comics` | Upload a PDF; returns `comic_id` and initial status |
| `GET` | `/comics/{id}/status` | Current processing stage and progress `0–100` |
| `GET` | `/comics/{id}/manifest` | Full Comic JSON manifest (available when done) |
| `GET` | `/comics/{id}/play` | Returns the shareable `/play/{token}` URL |
| `POST` | `/comics/{id}/reprocess` | Force a fresh pipeline run (bypass cache) |
| `GET` | `/play/{token}` | Resolve a share token → manifest (public, no auth) |

---

## 🤖 Models

All model calls are routed through **[OpenRouter](https://openrouter.ai/)** — a single API key gives access to every model below.

| Purpose | Model |
|---|---|
| Panel detection, OCR, speaker attribution, emotion | `google/gemini-2.5-flash-lite` |
| Text-to-speech (all characters) | `openai/gpt-audio-mini` |
| Panel image normalisation — primary | `google/gemini-2.5-flash-image` |
| Panel image normalisation — fallback | `bytedance-seed/seedream-4.5` |
| Background SFX | [Audiocraft](https://github.com/facebookresearch/audiocraft) `facebook/audiogen-small` (local) |

### Audiocraft device

| Environment | Setting | Notes |
|---|---|---|
| Local / web server | `AUDIOCRAFT_DEVICE=cpu` (default) | No GPU needed; `audiogen-small` is fast enough |
| Google Colab | `AUDIOCRAFT_DEVICE=cuda` | Uses the free T4 GPU; `audiogen-small` fits easily |

---

## ⚙️ Configuration

All settings live in `.env` (copy from `.env.example`):

```bash
# Required
OPENROUTER_API_KEY=sk-or-v1-...

# Audiocraft inference device: "cpu" (default) or "cuda" (Colab / GPU server)
AUDIOCRAFT_DEVICE=cpu
```

Full list of available settings: [`backend/config.py`](backend/config.py)

---

## 🧪 Running tests

```bash
source .venv/bin/activate
pytest tests/ -v
```

---

## 🗒️ Colab prototype

`colab/prototype.ipynb` runs the complete pipeline on a single page so you can validate output quality before deploying. Open it in Google Colab, set your `OPENROUTER_API_KEY` in the config cell, upload a PDF, and run all cells top-to-bottom.

The SFX cell uses the Colab T4 GPU automatically (`AUDIOCRAFT_DEVICE=cuda`).

---

## 🗺️ Roadmap

- [x] PDF → panel → bubble → OCR pipeline
- [x] Automatic character voice assignment
- [x] Emotion-aware TTS
- [x] Audiocraft SFX per panel
- [x] Panel image normalisation (AI outpaint)
- [x] Shareable playback URLs + caching
- [ ] Multilingual automatic detection and translation
- [ ] Advanced panel ordering (Z-order, inset panel trees)
- [ ] Voice consistency across language switches
- [ ] Face recognition for speaker attribution
- [ ] Cloud processing for large books

---

## 📄 License

MIT © 2026 LIdro
