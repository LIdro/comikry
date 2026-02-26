"""
API integration tests.

Uses FastAPI's TestClient (sync) so no real HTTP calls or OpenRouter
calls are made — pipeline stages are mocked out.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app, raise_server_exceptions=False)


def _fake_pdf_bytes() -> bytes:
    # Minimal valid-looking bytes (not a real PDF — just for hashing)
    return b"%PDF-1.4 fake content for testing"


@patch("backend.api.routes.asyncio.create_task")
def test_upload_new_comic(mock_task, tmp_storage):
    mock_task.return_value = AsyncMock()

    response = client.post(
        "/comics",
        files={"file": ("test.pdf", _fake_pdf_bytes(), "application/pdf")},
    )
    assert response.status_code == 202
    data = response.json()
    assert "comic_id" in data
    assert data["cached"] is False


@patch("backend.api.routes.asyncio.create_task")
def test_upload_same_pdf_twice_returns_cached(mock_task, tmp_storage):
    mock_task.return_value = AsyncMock()

    pdf = _fake_pdf_bytes()

    # First upload
    r1 = client.post("/comics", files={"file": ("a.pdf", pdf, "application/pdf")})
    comic_id = r1.json()["comic_id"]

    # Manually mark as done
    from backend.cache import store
    from backend.models import Comic, ProcessingStage

    record = store.load_record(comic_id)
    store.update_stage(record, ProcessingStage.done, 100)
    store.save_manifest(Comic(comic_id=comic_id, pdf_hash=record.pdf_hash))

    # Second upload of same PDF
    r2 = client.post("/comics", files={"file": ("a.pdf", pdf, "application/pdf")})
    assert r2.status_code == 202
    assert r2.json()["cached"] is True
    assert r2.json()["comic_id"] == comic_id


def test_status_not_found(tmp_storage):
    r = client.get("/comics/doesnotexist/status")
    assert r.status_code == 404


@patch("backend.api.routes.asyncio.create_task")
def test_status_returns_stage(mock_task, tmp_storage):
    mock_task.return_value = AsyncMock()

    r = client.post("/comics", files={"file": ("b.pdf", _fake_pdf_bytes(), "application/pdf")})
    comic_id = r.json()["comic_id"]

    status = client.get(f"/comics/{comic_id}/status")
    assert status.status_code == 200
    assert "stage" in status.json()
    assert "progress_pct" in status.json()


def test_manifest_before_done_returns_409(tmp_storage):
    from backend.cache import store

    record = store.create_record("hash_pending")
    store.save_record(record)

    r = client.get(f"/comics/{record.comic_id}/manifest")
    assert r.status_code == 409


def test_play_token_not_found(tmp_storage):
    r = client.get("/play/badtoken")
    assert r.status_code == 404
