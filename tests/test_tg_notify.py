"""Unit tests for tg-notify hook."""
import json
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
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
