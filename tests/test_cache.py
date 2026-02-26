"""Tests for the cache layer."""

from __future__ import annotations

from pathlib import Path

from backend.cache import store
from backend.models import ProcessingStage


def test_hash_pdf_stable():
    data = b"fake pdf content"
    assert store.hash_pdf(data) == store.hash_pdf(data)


def test_hash_pdf_differs():
    assert store.hash_pdf(b"aaa") != store.hash_pdf(b"bbb")


def test_create_and_lookup_record(tmp_storage):
    record = store.create_record("abc123", title="My Comic")
    store.save_record(record)

    found_id = store.lookup_by_hash("abc123")
    assert found_id == record.comic_id


def test_record_not_found_returns_none(tmp_storage):
    assert store.lookup_by_hash("nonexistent") is None
    assert store.load_record("nonexistent") is None


def test_save_and_load_record(tmp_storage):
    record = store.create_record("hash1")
    store.save_record(record)

    loaded = store.load_record(record.comic_id)
    assert loaded is not None
    assert loaded.comic_id == record.comic_id
    assert loaded.pdf_hash == "hash1"


def test_update_stage(tmp_storage):
    record = store.create_record("hash2")
    store.save_record(record)

    store.update_stage(record, ProcessingStage.panel_detection, 25)
    loaded = store.load_record(record.comic_id)
    assert loaded.processing_stage == ProcessingStage.panel_detection
    assert loaded.progress_pct == 25


def test_token_lookup(tmp_storage):
    record = store.create_record("hash3")
    store.save_record(record)

    found = store.load_record_by_token(record.playback_token)
    assert found is not None
    assert found.comic_id == record.comic_id


def test_save_and_load_manifest(tmp_storage):
    from backend.models import Comic

    record = store.create_record("hash4")
    store.save_record(record)

    comic = Comic(comic_id=record.comic_id, pdf_hash="hash4")
    store.save_manifest(comic)

    loaded = store.load_manifest(record.comic_id)
    assert loaded is not None
    assert loaded.pdf_hash == "hash4"
