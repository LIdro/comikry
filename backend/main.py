"""
Comikry — FastAPI application entry point.

Run with:
    uvicorn backend.main:app --reload
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.routes import router
from backend.config import settings

app = FastAPI(
    title="Comikry",
    description="Comic text-to-speech reader API",
    version="0.1.0",
)

# Allow the frontend (served separately in dev) to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

# Serve cached audio and image assets directly
app.mount("/storage", StaticFiles(directory=settings.storage_root, check_dir=False), name="storage")

# Serve the frontend build
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
