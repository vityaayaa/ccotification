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


def test_escape_html():
    assert tg.escape_html("<b>hello & world</b>") == "&lt;b&gt;hello &amp; world&lt;/b&gt;"


def test_build_message_contains_title():
    msg = tg.build_message(
        title="✅ Быстрый ответ",
        project_path="projects / myapp",
        git={"branch": "main", "short_hash": "abc1234", "message": "Fix bug"},
        duration_s=15.0,
        preview="Here is what I did.",
        tool_count=3,
        usage=None,
    )
    assert "✅ Быстрый ответ" in msg
    assert "projects / myapp" in msg
    assert "main" in msg
    assert "abc1234" in msg
    assert "Here is what I did." in msg
    assert "3 инструментов" in msg
    assert "<b>" in msg
    assert "<code>" in msg


def test_build_message_with_usage():
    future = (datetime.now(timezone.utc) + timedelta(hours=3, minutes=0)).isoformat()
    msg = tg.build_message(
        title="🧠 Хорошо подумал",
        project_path="projects / myapp",
        git=None,
        duration_s=60.0,
        preview="",
        tool_count=0,
        usage={"sessionUsage": 7, "sessionResetAt": future,
               "weeklyUsage": 30, "weeklyResetAt": future,
               "extraUsageEnabled": False},
    )
    assert "7%" in msg
    assert "30%" in msg


def test_build_message_no_git():
    msg = tg.build_message("⚡ Мгновенный ответ", "home / victor", None,
                            5.0, "", 0, None)
    assert "🌿" not in msg


def test_build_keyboard_structure():
    kb = tg.build_keyboard()
    assert "inline_keyboard" in kb
    row = kb["inline_keyboard"][0]
    assert len(row) == 4
    assert row[0]["callback_data"] == "mute_1800"
    assert row[3]["callback_data"] == "mute_eod"


from unittest.mock import patch, MagicMock
import urllib.error


def make_mock_response(data: dict):
    mock = MagicMock()
    mock.read.return_value = json.dumps(data).encode()
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    return mock


def test_send_message_calls_api():
    response_data = {"ok": True, "result": {"message_id": 1}}
    with patch("urllib.request.urlopen", return_value=make_mock_response(response_data)) as mock_open:
        tg.send_message("TOKEN", 12345, "Hello", None)
    assert mock_open.called
    req = mock_open.call_args[0][0]
    body = json.loads(req.data)
    assert body["chat_id"] == 12345
    assert body["text"] == "Hello"
    assert body["parse_mode"] == "HTML"


def test_send_message_with_keyboard():
    response_data = {"ok": True, "result": {"message_id": 2}}
    with patch("urllib.request.urlopen", return_value=make_mock_response(response_data)):
        kb = tg.build_keyboard()
        tg.send_message("TOKEN", 12345, "Hi", kb)


def test_poll_callbacks_empty():
    response_data = {"ok": True, "result": []}
    with patch("urllib.request.urlopen", return_value=make_mock_response(response_data)):
        callbacks, new_offset = tg.poll_callbacks("TOKEN", 0)
    assert callbacks == []
    assert new_offset == 0


def test_poll_callbacks_with_mute():
    cb_query = {"id": "cq1", "from": {}, "message": {}, "chat_instance": "", "data": "mute_3600"}
    response_data = {"ok": True, "result": [{"update_id": 100, "callback_query": cb_query}]}
    with patch("urllib.request.urlopen", return_value=make_mock_response(response_data)):
        callbacks, new_offset = tg.poll_callbacks("TOKEN", 0)
    assert len(callbacks) == 1
    assert callbacks[0]["data"] == "mute_3600"
    assert new_offset == 101


def test_tg_request_network_error():
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
        result = tg.tg_request("TOKEN", "sendMessage", {"chat_id": 1})
    assert result == {}


def test_is_muted_none():
    assert tg.is_muted({"mute_until": None}) is False


def test_is_muted_future():
    future = (datetime.now() + timedelta(hours=1)).isoformat()
    assert tg.is_muted({"mute_until": future}) is True


def test_is_muted_past():
    past = (datetime.now() - timedelta(hours=1)).isoformat()
    assert tg.is_muted({"mute_until": past}) is False


def test_process_callbacks_sets_mute():
    cb = {"id": "cq1", "data": "mute_3600"}
    state = {"mute_until": None, "tg_offset": 0}
    response = {"ok": True, "result": [{"update_id": 5, "callback_query": cb}]}
    with patch("urllib.request.urlopen", return_value=make_mock_response(response)):
        updated = tg.process_callbacks("TOKEN", state)
    assert updated["mute_until"] is not None
    assert updated["tg_offset"] == 6
    until = datetime.fromisoformat(updated["mute_until"])
    assert until > datetime.now()


def test_process_callbacks_mute_eod():
    cb = {"id": "cq2", "data": "mute_eod"}
    state = {"mute_until": None, "tg_offset": 0}
    response = {"ok": True, "result": [{"update_id": 10, "callback_query": cb}]}
    with patch("urllib.request.urlopen", return_value=make_mock_response(response)):
        updated = tg.process_callbacks("TOKEN", state)
    until = datetime.fromisoformat(updated["mute_until"])
    tomorrow = datetime.now() + timedelta(days=1)
    assert until.day == tomorrow.day or until.date() >= datetime.now().date()


def test_update_daily_stats_same_day():
    today = datetime.now().strftime("%Y-%m-%d")
    state = {"daily_date": today, "daily_count": 5, "daily_total_duration_s": 200.0}
    updated = tg.update_daily_stats(state, 60.0)
    assert updated["daily_count"] == 6
    assert updated["daily_total_duration_s"] == 260.0

def test_update_daily_stats_new_day():
    state = {"daily_date": "2026-01-01", "daily_count": 10, "daily_total_duration_s": 500.0}
    updated = tg.update_daily_stats(state, 30.0)
    # Should reset (today != 2026-01-01)
    assert updated["daily_count"] == 1
    assert updated["daily_total_duration_s"] == 30.0

def test_update_cron_entry_writes_entry():
    reset_at = "2026-05-07T15:42:00+00:00"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        tg.update_cron_entry(reset_at, "session")
    write_call = mock_run.call_args_list[-1]
    new_crontab = write_call[1]["input"]
    assert "tg-hook-session-reset" in new_crontab
    assert "--notify-reset session" in new_crontab

def test_update_cron_entry_replaces_old():
    existing = (
        "# tg-hook-session-reset (managed by ccotification)\n"
        "30 10 7 5 * python3 ~/.claude/hooks/tg-notify.py --notify-reset session\n"
    )
    reset_at = "2026-05-07T15:42:00+00:00"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=existing)
        tg.update_cron_entry(reset_at, "session")
    write_call = mock_run.call_args_list[-1]
    new_crontab = write_call[1]["input"]
    assert "30 10 7 5" not in new_crontab
    assert "42" in new_crontab

def test_check_reset_no_change():
    """If sessionResetAt unchanged, no notification sent."""
    usage = {"sessionUsage": 5, "sessionResetAt": "2026-05-07T15:00:00+00:00",
             "weeklyUsage": 10, "weeklyResetAt": "2026-05-08T16:00:00+00:00"}
    state = {"last_session_reset_at": "2026-05-07T15:00:00+00:00",
             "last_weekly_reset_at": "2026-05-08T16:00:00+00:00"}
    sent_texts = []
    with patch.object(tg, "send_message", side_effect=lambda *a, **k: sent_texts.append(a[2])):
        with patch.object(tg, "update_cron_entry"):
            tg.check_reset_notifications("TOKEN", 12345, usage, state)
    assert len(sent_texts) == 0

def test_check_reset_session_changed():
    """If sessionResetAt changed and previous was not None → send notification."""
    usage = {"sessionUsage": 2, "sessionResetAt": "2026-05-07T20:00:00+00:00",
             "weeklyUsage": 10, "weeklyResetAt": "2026-05-08T16:00:00+00:00"}
    state = {"last_session_reset_at": "2026-05-07T15:00:00+00:00",
             "last_weekly_reset_at": "2026-05-08T16:00:00+00:00"}
    sent_texts = []
    with patch.object(tg, "send_message", side_effect=lambda *a, **k: sent_texts.append(a[2])):
        with patch.object(tg, "update_cron_entry"):
            tg.check_reset_notifications("TOKEN", 12345, usage, state)
    assert len(sent_texts) == 1
    assert "Окно сброшено" in sent_texts[0]
    assert state["last_session_reset_at"] == "2026-05-07T20:00:00+00:00"

def test_check_reset_first_run_no_notification():
    """If previous reset_at is None (first run), store but do not notify."""
    usage = {"sessionUsage": 5, "sessionResetAt": "2026-05-07T15:00:00+00:00",
             "weeklyUsage": 10, "weeklyResetAt": "2026-05-08T16:00:00+00:00"}
    state = {"last_session_reset_at": None, "last_weekly_reset_at": None}
    sent_texts = []
    with patch.object(tg, "send_message", side_effect=lambda *a, **k: sent_texts.append(a[2])):
        with patch.object(tg, "update_cron_entry"):
            tg.check_reset_notifications("TOKEN", 12345, usage, state)
    assert len(sent_texts) == 0
    assert state["last_session_reset_at"] == "2026-05-07T15:00:00+00:00"


def test_main_sends_notification(tmp_path, monkeypatch):
    config = {"bot_token": "TESTTOKEN", "chat_id": 99999}
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(config))
    monkeypatch.setattr(tg, "CONFIG_FILE", cfg_file)
    monkeypatch.setattr(tg, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(tg, "STATE_DIR", tmp_path)
    monkeypatch.setattr(tg, "USAGE_FILE", tmp_path / "missing.json")

    transcript = tmp_path / "conv.jsonl"
    make_transcript([
        {"type": "user", "timestamp": "2026-05-07T10:00:00.000Z",
         "message": {"role": "user", "content": [{"type": "text", "text": "Build X"}]}},
        {"type": "assistant", "timestamp": "2026-05-07T10:02:00.000Z",
         "message": {"role": "assistant", "content": [
             {"type": "text", "text": "I built X successfully. Here are the details."}
         ]}},
    ], transcript)

    hook_input = json.dumps({"session_id": "test-session",
                              "transcript_path": str(transcript)})

    sent = []

    empty_updates = {"ok": True, "result": []}
    with patch("urllib.request.urlopen", return_value=make_mock_response(empty_updates)):
        with patch.object(tg, "send_message", side_effect=lambda *a, **k: sent.append(a[2]) or {}):
            with patch.object(tg, "get_cwd_from_session", return_value="/home/victor"):
                with patch.object(tg, "update_cron_entry"):
                    import io
                    monkeypatch.setattr("sys.stdin", io.StringIO(hook_input))
                    tg.main()

    assert len(sent) >= 1
    assert any("victor" in m for m in sent)

def test_main_silent_when_muted(tmp_path, monkeypatch):
    config = {"bot_token": "TESTTOKEN", "chat_id": 99999}
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(config))
    future = (datetime.now() + timedelta(hours=2)).isoformat()
    state = {"mute_until": future, "tg_offset": 0, "last_session_reset_at": None,
             "last_weekly_reset_at": None, "daily_date": None,
             "daily_count": 0, "daily_total_duration_s": 0}
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps(state))
    monkeypatch.setattr(tg, "CONFIG_FILE", cfg_file)
    monkeypatch.setattr(tg, "STATE_FILE", state_file)
    monkeypatch.setattr(tg, "STATE_DIR", tmp_path)

    transcript = tmp_path / "conv.jsonl"
    make_transcript([
        {"type": "user", "timestamp": "2026-05-07T10:00:00.000Z",
         "message": {"role": "user", "content": []}},
        {"type": "assistant", "timestamp": "2026-05-07T10:00:05.000Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "Done."}]}},
    ], transcript)

    sent = []
    empty_updates = {"ok": True, "result": []}
    with patch("urllib.request.urlopen", return_value=make_mock_response(empty_updates)):
        with patch.object(tg, "send_message", side_effect=lambda *a, **k: sent.append(a)):
            import io
            monkeypatch.setattr("sys.stdin", io.StringIO(
                json.dumps({"session_id": "s", "transcript_path": str(transcript)})))
            tg.main()

    assert len(sent) == 0
