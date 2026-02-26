"""Shared pytest fixtures."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Point storage at a temp dir so tests never touch real storage
@pytest.fixture(autouse=True)
def tmp_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))
    # Re-import settings so the env var takes effect
    import importlib
    import backend.config as cfg
    importlib.reload(cfg)
    import backend.cache.store as cs
    importlib.reload(cs)
    yield tmp_path / "storage"
