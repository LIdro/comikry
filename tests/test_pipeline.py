"""Tests for pipeline utility functions (no OpenRouter calls)."""

from __future__ import annotations

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
