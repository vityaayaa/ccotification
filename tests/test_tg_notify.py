"""Unit tests for tg-notify hook."""
import json
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
import tempfile
import pytest

# Allow importing the hook module from hooks/
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))
import importlib
tg = importlib.import_module("tg-notify")


def test_load_state_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "STATE_FILE", tmp_path / "state.json")
    state = tg.load_state()
    assert state["mute_until"] is None
    assert state["tg_offset"] == 0
    assert state["daily_count"] == 0
    assert state["last_session_reset_at"] is None


def test_save_and_load_state(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(tg, "STATE_DIR", tmp_path)
    state = {"mute_until": "2026-01-01T12:00:00", "tg_offset": 42,
             "last_session_reset_at": None, "last_weekly_reset_at": None,
             "daily_date": "2026-01-01", "daily_count": 5,
             "daily_total_duration_s": 300}
    tg.save_state(state)
    loaded = tg.load_state()
    assert loaded["tg_offset"] == 42
    assert loaded["daily_count"] == 5


def test_load_config(tmp_path, monkeypatch):
    cfg = {"bot_token": "test123", "chat_id": 12345}
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps(cfg))
    monkeypatch.setattr(tg, "CONFIG_FILE", config_file)
    result = tg.load_config()
    assert result["bot_token"] == "test123"
    assert result["chat_id"] == 12345


def make_transcript(messages: list, path):
    """Write a list of dicts as JSONL to path."""
    path.write_text("\n".join(json.dumps(m) for m in messages))


def test_parse_transcript_duration(tmp_path):
    transcript = tmp_path / "conv.jsonl"
    make_transcript([
        {"type": "user", "timestamp": "2026-05-07T10:00:00.000Z",
         "message": {"role": "user", "content": [{"type": "text", "text": "Hello"}]}},
        {"type": "assistant", "timestamp": "2026-05-07T10:01:30.000Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "Hi there!"}]}},
    ], transcript)
    result = tg.parse_transcript(str(transcript), session_id="test")
    assert abs(result["duration_s"] - 90.0) < 1.0


def test_parse_transcript_text_and_tools(tmp_path):
    transcript = tmp_path / "conv.jsonl"
    make_transcript([
        {"type": "user", "timestamp": "2026-05-07T10:00:00.000Z",
         "message": {"role": "user", "content": [{"type": "text", "text": "Do it"}]}},
        {"type": "assistant", "timestamp": "2026-05-07T10:00:05.000Z",
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "id": "1", "name": "Bash", "input": {}},
             {"type": "tool_use", "id": "2", "name": "Read", "input": {}},
             {"type": "text", "text": "Done. I ran two commands."},
         ]}},
    ], transcript)
    result = tg.parse_transcript(str(transcript), session_id="test")
    assert result["tool_count"] == 2
    assert "Done" in result["text"]
    assert result["has_errors"] is False


def test_parse_transcript_tool_error(tmp_path):
    transcript = tmp_path / "conv.jsonl"
    make_transcript([
        {"type": "user", "timestamp": "2026-05-07T10:00:00.000Z",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "1", "is_error": True, "content": "err"}
         ]}},
        {"type": "assistant", "timestamp": "2026-05-07T10:00:05.000Z",
         "message": {"role": "assistant", "content": [
             {"type": "text", "text": "Something failed."}
         ]}},
    ], transcript)
    result = tg.parse_transcript(str(transcript), session_id="test")
    assert result["has_errors"] is True


def test_extract_preview_single_sentence():
    text = "I implemented the button component. It has hover effects."
    result = tg.extract_preview(text)
    assert result == "I implemented the button component."


def test_extract_preview_short_first_sentence():
    # First sentence < 40 chars → include second
    text = "Done! I also refactored the modal component to use slots."
    result = tg.extract_preview(text)
    assert "Done!" in result
    assert "refactored" in result


def test_extract_preview_strips_code_blocks():
    text = "```python\nrm -rf /\n```\nHere is the explanation of the fix."
    result = tg.extract_preview(text)
    assert "rm -rf" not in result
    assert "explanation" in result


def test_extract_preview_truncates_long():
    text = "This is a very long sentence that goes on and on and keeps going until it exceeds the maximum character limit that we have set for preview text in our notification system."
    result = tg.extract_preview(text, max_chars=50)
    assert len(result) <= 55  # allow a few chars for ellipsis
    assert not result.endswith(" ")
    assert "…" in result


def test_extract_preview_empty():
    assert tg.extract_preview("") == ""
    assert tg.extract_preview("   ") == ""


def test_count_questions_none():
    assert tg.count_questions_in_text("I fixed the bug.") == 0


def test_count_questions_one():
    assert tg.count_questions_in_text("Which approach do you prefer?") == 1


def test_count_questions_two():
    assert tg.count_questions_in_text("Do you want X?\nOr maybe Y?") == 2


def test_count_questions_ignores_code():
    text = "```python\nresult = x if x else y\n```\nDoes this look right?"
    assert tg.count_questions_in_text(text) == 1


def test_get_title_instant():
    assert tg.get_title(5.0, "Done.", False) == "⚡ Мгновенный ответ"


def test_get_title_fast():
    assert tg.get_title(20.0, "Done.", False) == "✅ Быстрый ответ"


def test_get_title_thought():
    assert tg.get_title(60.0, "Done.", False) == "🧠 Хорошо подумал"


def test_get_title_serious():
    assert tg.get_title(200.0, "Done.", False) == "🔧 Серьёзная работа"


def test_get_title_monumental():
    assert tg.get_title(400.0, "Done.", False) == "🏆 Монументальная работа"


def test_get_title_question_one():
    assert tg.get_title(60.0, "Which approach?", False) == "🤔 Клод хочет уточнить"


def test_get_title_question_many():
    assert tg.get_title(60.0, "Option A?\nOr B?", False) == "❓ Нужна твоя помощь"


def test_get_title_error_prefix():
    title = tg.get_title(20.0, "Done.", True)
    assert title.startswith("⚠️")
    assert "✅" in title


def test_get_project_path_deep():
    result = tg.get_project_path("/home/victor/projects/myapp")
    assert result == "victor / projects / myapp"


def test_get_project_path_short():
    result = tg.get_project_path("/myapp")
    assert result == "myapp"


def test_get_project_path_two_levels():
    result = tg.get_project_path("/projects/myapp")
    assert result == "projects / myapp"


def test_get_git_context_not_a_repo(tmp_path):
    result = tg.get_git_context(str(tmp_path))
    assert result is None


def test_read_usage_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "USAGE_FILE", tmp_path / "missing.json")
    assert tg.read_usage() is None


def test_read_usage_valid(tmp_path, monkeypatch):
    data = {"sessionUsage": 42, "sessionResetAt": "2026-05-07T15:00:00+00:00",
            "weeklyUsage": 10, "weeklyResetAt": "2026-05-08T16:00:00+00:00"}
    f = tmp_path / "usage.json"
    f.write_text(json.dumps(data))
    monkeypatch.setattr(tg, "USAGE_FILE", f)
    result = tg.read_usage()
    assert result["sessionUsage"] == 42


def test_format_time_until_hours():
    future = (datetime.now(timezone.utc) + timedelta(hours=3, minutes=12)).isoformat()
    result = tg.format_time_until(future)
    assert "3ч" in result
    assert "м" in result


def test_format_time_until_minutes_only():
    future = (datetime.now(timezone.utc) + timedelta(minutes=45)).isoformat()
    result = tg.format_time_until(future)
    assert "ч" not in result
    assert "м" in result


def test_format_time_until_past():
    result = tg.format_time_until("2020-01-01T00:00:00+00:00")
    assert result == "скоро"
