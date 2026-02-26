"""Tests for data models."""

from backend.models import (
    BBox, Bubble, BubbleType, CacheRecord, Comic, Page, Panel,
    PlaybackState, ProcessingStage, Speaker,
)


def test_bbox_fields():
    bb = BBox(x=10, y=20, w=100, h=50)
    assert bb.x == 10 and bb.w == 100


def test_bubble_defaults():
    b = Bubble(bubble_id="p1_b1", order_index=1, bbox=BBox(x=0,y=0,w=10,h=10))
    assert b.bubble_type == BubbleType.speech
    assert b.ocr_confidence == 1.0
    assert b.speaker_id is None


def test_speaker_voice_default():
    s = Speaker(speaker_id="char_0")
    assert s.voice_id == ""


def test_comic_round_trip():
    comic = Comic(comic_id="abc", pdf_hash="deadbeef")
    json_str = comic.model_dump_json()
    restored = Comic.model_validate_json(json_str)
    assert restored.comic_id == "abc"
    assert restored.pdf_hash == "deadbeef"


def test_processing_stage_enum():
    assert ProcessingStage.done == "done"
    assert ProcessingStage.failed == "failed"


def test_playback_state_defaults():
    ps = PlaybackState(comic_id="x")
    assert ps.voice_volume == 1.0
    assert ps.sfx_volume == 0.4
    assert ps.playback_speed == 1.0
