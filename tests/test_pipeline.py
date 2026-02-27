"""Tests for pipeline utility functions (no OpenRouter calls)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.voice_tone_agent import assign_voices
from backend.models import Speaker


def test_narrator_gets_sage_voice():
    speakers = [Speaker(speaker_id="narrator", gender="unknown", age_group="adult")]
    result = assign_voices(speakers)
    assert result[0].voice_id == "sage"


def test_male_adult_gets_echo():
    speakers = [Speaker(speaker_id="char_0", gender="male", age_group="adult")]
    result = assign_voices(speakers)
    assert result[0].voice_id == "echo"


def test_female_child_gets_coral():
    speakers = [Speaker(speaker_id="char_1", gender="female", age_group="child")]
    result = assign_voices(speakers)
    assert result[0].voice_id == "coral"


def test_unknown_gender_gets_alloy():
    speakers = [Speaker(speaker_id="char_2", gender="unknown", age_group="adult")]
    result = assign_voices(speakers)
    assert result[0].voice_id == "alloy"


def test_assign_voices_multiple():
    speakers = [
        Speaker(speaker_id="char_0", gender="male", age_group="elder"),
        Speaker(speaker_id="char_1", gender="female", age_group="teen"),
        Speaker(speaker_id="narrator"),
    ]
    result = assign_voices(speakers)
    voice_ids = [s.voice_id for s in result]
    assert voice_ids == ["onyx", "coral", "sage"]


# ── Task 2-8: Gemini Files API tests ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_upload_image_returns_none_when_flag_off(monkeypatch, tmp_path):
    """upload_image() returns None when use_gemini_files_api=False."""
    import backend.pipeline.gemini_files as gf

    monkeypatch.setattr(gf.settings, "use_gemini_files_api", False)
    monkeypatch.setattr(gf.settings, "google_ai_api_key", "dummy-key")
    gf.clear_cache()

    # Create a dummy image file so the path is real
    img = tmp_path / "page_0001.png"
    img.write_bytes(b"\x89PNG\r\n")

    result = await gf.upload_image(str(img))
    assert result is None


@pytest.mark.asyncio
async def test_upload_image_returns_none_when_key_missing(monkeypatch, tmp_path):
    """upload_image() returns None when google_ai_api_key is empty."""
    import backend.pipeline.gemini_files as gf

    monkeypatch.setattr(gf.settings, "use_gemini_files_api", True)
    monkeypatch.setattr(gf.settings, "google_ai_api_key", "")
    gf.clear_cache()

    img = tmp_path / "page_0001.png"
    img.write_bytes(b"\x89PNG\r\n")

    result = await gf.upload_image(str(img))
    assert result is None


@pytest.mark.asyncio
async def test_upload_image_caches_uri(monkeypatch, tmp_path):
    """upload_image() returns cached URI without calling genai.upload_file again."""
    import backend.pipeline.gemini_files as gf

    monkeypatch.setattr(gf.settings, "use_gemini_files_api", True)
    monkeypatch.setattr(gf.settings, "google_ai_api_key", "dummy-key")
    gf.clear_cache()

    img = tmp_path / "page_0001.png"
    img.write_bytes(b"\x89PNG\r\n")

    mock_file = MagicMock()
    mock_file.uri = "files/abc123"

    with patch("google.generativeai.upload_file", return_value=mock_file) as mock_upload, \
         patch("google.generativeai.configure"):
        uri1 = await gf.upload_image(str(img))
        uri2 = await gf.upload_image(str(img))  # second call — should use cache

    assert uri1 == "files/abc123"
    assert uri2 == "files/abc123"
    # genai.upload_file must only have been called once (cache hit on second call)
    assert mock_upload.call_count == 1


@pytest.mark.asyncio
async def test_upload_image_stale_cache_triggers_fresh_upload(monkeypatch, tmp_path):
    """upload_image() re-uploads when the cache entry is older than 47 hours."""
    import backend.pipeline.gemini_files as gf

    monkeypatch.setattr(gf.settings, "use_gemini_files_api", True)
    monkeypatch.setattr(gf.settings, "google_ai_api_key", "dummy-key")
    gf.clear_cache()

    img = tmp_path / "page_0001.png"
    img.write_bytes(b"\x89PNG\r\n")

    # Manually insert a stale cache entry (49 hours ago)
    stale_time = datetime.now(timezone.utc) - timedelta(hours=49)
    gf._uri_cache[str(img)] = ("files/old_uri", stale_time)

    mock_file = MagicMock()
    mock_file.uri = "files/new_uri"

    with patch("google.generativeai.upload_file", return_value=mock_file) as mock_upload, \
         patch("google.generativeai.configure"):
        uri = await gf.upload_image(str(img))

    assert uri == "files/new_uri"
    assert mock_upload.call_count == 1


# ── Task 4-7: Batched PDF rendering tests ────────────────────────────────────

def test_render_pdf_calls_once_per_batch(monkeypatch, tmp_path):
    """render_pdf() calls _render_batch once per batch, not once for the whole doc."""
    import backend.pipeline.pdf_to_images as pdf_mod

    monkeypatch.setattr(pdf_mod.settings, "pdf_render_dpi", 72)
    monkeypatch.setattr(pdf_mod.settings, "pdf_render_batch_size", 3)
    monkeypatch.setattr(pdf_mod.settings, "pdf_render_max_workers", 2)
    monkeypatch.setattr(pdf_mod.settings, "storage_root", str(tmp_path))

    # Fake pdfinfo: 7 pages → expect ceil(7/3) = 3 batches
    with patch("backend.pipeline.pdf_to_images.pdfinfo_from_path", return_value={"Pages": 7}), \
         patch("backend.pipeline.pdf_to_images.ProcessPoolExecutor") as mock_executor_cls:

        # Build a fake context manager for ProcessPoolExecutor
        fake_executor = MagicMock()
        mock_executor_cls.return_value.__enter__ = MagicMock(return_value=fake_executor)
        mock_executor_cls.return_value.__exit__ = MagicMock(return_value=False)

        # Each submit call returns a future-like that returns page paths
        call_idx = [0]
        batches_called: list[tuple[int, int]] = []

        def fake_submit(fn, pdf_path, out_dir, first_page, last_page, dpi):
            batches_called.append((first_page, last_page))
            # Create fake PNG files so sorting works
            out = Path(out_dir)
            out.mkdir(parents=True, exist_ok=True)
            paths = []
            for n in range(first_page, last_page + 1):
                p = out / f"page_{n:04d}.png"
                p.touch()
                paths.append(str(p))
            future = MagicMock()
            future.result.return_value = paths
            return future

        fake_executor.submit.side_effect = fake_submit

        result = pdf_mod.render_pdf("fake.pdf", "test_comic")

    # 7 pages, batch_size=3 → batches (1,3), (4,6), (7,7)
    assert len(batches_called) == 3
    assert batches_called[0] == (1, 3)
    assert batches_called[1] == (4, 6)
    assert batches_called[2] == (7, 7)


def test_render_pdf_result_sorted_by_page(monkeypatch, tmp_path):
    """render_pdf() sorts paths by page number even if batches finish out of order."""
    import backend.pipeline.pdf_to_images as pdf_mod

    monkeypatch.setattr(pdf_mod.settings, "pdf_render_dpi", 72)
    monkeypatch.setattr(pdf_mod.settings, "pdf_render_batch_size", 2)
    monkeypatch.setattr(pdf_mod.settings, "pdf_render_max_workers", 4)
    monkeypatch.setattr(pdf_mod.settings, "storage_root", str(tmp_path))

    pages_dir = tmp_path / "sort_comic" / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    for n in range(1, 5):
        (pages_dir / f"page_{n:04d}.png").touch()

    with patch("backend.pipeline.pdf_to_images.pdfinfo_from_path", return_value={"Pages": 4}), \
         patch("backend.pipeline.pdf_to_images.ProcessPoolExecutor") as mock_executor_cls:

        fake_executor = MagicMock()
        mock_executor_cls.return_value.__enter__ = MagicMock(return_value=fake_executor)
        mock_executor_cls.return_value.__exit__ = MagicMock(return_value=False)

        def fake_submit(fn, pdf_path, out_dir, first_page, last_page, dpi):
            out = Path(out_dir)
            out.mkdir(parents=True, exist_ok=True)
            paths = []
            for n in range(first_page, last_page + 1):
                p = out / f"page_{n:04d}.png"
                p.touch()
                paths.append(str(p))
            future = MagicMock()
            # Return in reverse order to test sorting
            future.result.return_value = list(reversed(paths))
            return future

        fake_executor.submit.side_effect = fake_submit

        result = pdf_mod.render_pdf("fake.pdf", "sort_comic")

    # Must be in ascending page order
    page_nums = [int(Path(p).stem.split("_")[-1]) for p in result]
    assert page_nums == sorted(page_nums)


def test_render_pdf_with_page_range(monkeypatch, tmp_path):
    """render_pdf() passes page_range to the batch worker correctly."""
    import backend.pipeline.pdf_to_images as pdf_mod

    monkeypatch.setattr(pdf_mod.settings, "pdf_render_dpi", 72)
    monkeypatch.setattr(pdf_mod.settings, "pdf_render_batch_size", 10)
    monkeypatch.setattr(pdf_mod.settings, "pdf_render_max_workers", 4)
    monkeypatch.setattr(pdf_mod.settings, "storage_root", str(tmp_path))

    batches_called: list[tuple[int, int]] = []

    with patch("backend.pipeline.pdf_to_images.pdfinfo_from_path", return_value={"Pages": 20}), \
         patch("backend.pipeline.pdf_to_images.ProcessPoolExecutor") as mock_executor_cls:

        fake_executor = MagicMock()
        mock_executor_cls.return_value.__enter__ = MagicMock(return_value=fake_executor)
        mock_executor_cls.return_value.__exit__ = MagicMock(return_value=False)

        def fake_submit(fn, pdf_path, out_dir, first_page, last_page, dpi):
            batches_called.append((first_page, last_page))
            out = Path(out_dir)
            out.mkdir(parents=True, exist_ok=True)
            paths = []
            for n in range(first_page, last_page + 1):
                p = out / f"page_{n:04d}.png"
                p.touch()
                paths.append(str(p))
            future = MagicMock()
            future.result.return_value = paths
            return future

        fake_executor.submit.side_effect = fake_submit

        result = pdf_mod.render_pdf("fake.pdf", "range_comic", page_range=(5, 8))

    # Only pages 5–8 should be rendered (one batch since batch_size=10)
    assert batches_called == [(5, 8)]
    assert len(result) == 4


# ── Task 4-6: Track B tests ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_track_b_correct_number_of_agent_calls(monkeypatch):
    """run_track_b() calls analyse_page_range the right number of times."""
    from backend.models import StoryBible, StoryFragment
    import backend.pipeline.track_b as tb

    # 25 pages, pages_per_agent=10, overlap=2
    # Slices: (0,9), (8,17), (16,24) → 3 calls
    page_paths = [f"/fake/page_{i:04d}.png" for i in range(1, 26)]

    fragment = StoryFragment(page_range=(1, 10))
    bible = StoryBible(comic_id="test_comic")

    with patch.object(tb, "analyse_page_range", new_callable=AsyncMock, return_value=fragment) as mock_analyse, \
         patch.object(tb, "synthesise_story_bible", new_callable=AsyncMock, return_value=bible):
        result = await tb.run_track_b(page_paths, "test_comic", pages_per_agent=10, overlap=2)

    assert mock_analyse.call_count == 3
    assert result is bible


@pytest.mark.asyncio
async def test_run_track_b_single_page_list():
    """run_track_b() handles a list shorter than pages_per_agent."""
    from backend.models import StoryBible, StoryFragment
    import backend.pipeline.track_b as tb

    page_paths = [f"/fake/page_{i:04d}.png" for i in range(1, 4)]  # 3 pages

    fragment = StoryFragment(page_range=(1, 3))
    bible = StoryBible(comic_id="tiny")

    with patch.object(tb, "analyse_page_range", new_callable=AsyncMock, return_value=fragment) as mock_analyse, \
         patch.object(tb, "synthesise_story_bible", new_callable=AsyncMock, return_value=bible):
        result = await tb.run_track_b(page_paths, "tiny", pages_per_agent=10, overlap=2)

    # Only one slice since total pages < pages_per_agent
    assert mock_analyse.call_count == 1


@pytest.mark.asyncio
async def test_orchestrator_continues_when_track_b_raises(monkeypatch, tmp_path):
    """Orchestrator sets story_bible=None and continues without error when Track B raises."""
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path / "storage"))

    import importlib
    import backend.config as cfg
    importlib.reload(cfg)
    import backend.cache.store as cs
    importlib.reload(cs)
    import backend.orchestrator as orch_mod
    importlib.reload(orch_mod)

    from backend.cache.store import create_record, save_record
    from backend.models import Comic, ProcessingStage

    # Create a minimal fake PDF
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    record = create_record(b"%PDF-1.4".hex())
    save_record(record)

    fake_pages = [str(tmp_path / f"page_{i:04d}.png") for i in range(1, 3)]
    for p in fake_pages:
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        Path(p).touch()

    fake_comic = Comic(comic_id=record.comic_id, pdf_hash=record.pdf_hash)

    async def raise_always(*a, **kw):
        raise RuntimeError("Track B boom")

    with patch.object(orch_mod, "render_pdf", return_value=fake_pages), \
         patch.object(orch_mod, "detect_panels", new_callable=AsyncMock, return_value=[]), \
         patch.object(orch_mod, "detect_bubbles", new_callable=AsyncMock, return_value=[]), \
         patch.object(orch_mod, "attribute_speakers", new_callable=AsyncMock, return_value=([], [])), \
         patch.object(orch_mod, "run_voice_tone_agent", new_callable=AsyncMock, return_value=fake_comic), \
         patch.object(orch_mod, "generate_tts_for_comic", new_callable=AsyncMock, return_value=fake_comic), \
         patch.object(orch_mod, "generate_sfx_prompts", new_callable=AsyncMock, return_value={}), \
         patch.object(orch_mod, "generate_sfx_for_comic", new_callable=AsyncMock, return_value=fake_comic), \
         patch.object(orch_mod, "normalise_comic_panels", new_callable=AsyncMock, return_value=fake_comic), \
         patch("backend.pipeline.track_b.run_track_b", side_effect=raise_always), \
         patch.object(orch_mod, "store") as mock_store:

        mock_store.update_stage = MagicMock()
        mock_store.save_record = MagicMock()
        mock_store.save_manifest = MagicMock()

        # Pipeline must complete without raising
        result = await orch_mod.run_pipeline(
            str(pdf_path), record.comic_id, record
        )

    assert result is not None


@pytest.mark.asyncio
async def test_story_bible_written_to_correct_path(monkeypatch, tmp_path):
    """story_bible.json is written to storage/{comic_id}/story_bible.json."""
    import json as _json
    from backend.models import StoryBible
    import backend.agents.story_director_agent as sda

    comic_id = "story_test_comic"
    monkeypatch.setattr(sda.settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(sda.settings, "vision_model", "fake/model")

    bible = StoryBible(
        comic_id=comic_id,
        genre="action",
        tone_summary="tense",
        narrator_voice_style="calm",
    )

    with patch.object(sda, "chat_completion", new_callable=AsyncMock) as mock_chat:
        # Return valid story bible JSON
        mock_chat.return_value = {
            "choices": [
                {
                    "message": {
                        "content": _json.dumps({
                            "comic_id": comic_id,
                            "characters": [],
                            "per_panel_sfx": {},
                            "genre": "action",
                            "tone_summary": "tense",
                            "narrator_voice_style": "calm",
                        })
                    }
                }
            ]
        }
        from backend.models import StoryFragment
        fragments = [StoryFragment(page_range=(1, 5))]
        result = await sda.synthesise_story_bible(fragments, comic_id)

    expected_path = tmp_path / comic_id / "story_bible.json"
    assert expected_path.exists(), "story_bible.json should be written to storage/{comic_id}/"
    data = _json.loads(expected_path.read_text())
    assert data["comic_id"] == comic_id
    assert result.comic_id == comic_id
