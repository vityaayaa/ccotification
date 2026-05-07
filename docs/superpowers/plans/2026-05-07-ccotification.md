# ccotification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A single Python 3 Stop-hook script that sends richly formatted Telegram notifications after every Claude Code response, with mute buttons, usage tracking, and reset notifications via cron.

**Architecture:** One file `hooks/tg-notify.py` with pure functions and a `main()` entry point. All state in `~/.local/share/tg-hook/state.json`. Uses only Python stdlib (urllib, subprocess, re, json, datetime) — zero pip dependencies. The `install.sh` script copies the hook and patches `~/.claude/settings.json`.

**Tech Stack:** Python 3.8+, Telegram Bot API (sendMessage, getUpdates, answerCallbackQuery), crontab, git CLI, Claude Code Stop-hook format.

**Spec:** `~/docs/superpowers/specs/2026-05-07-ccotification-design.md`

---

## File Map

| File | Role |
|---|---|
| `hooks/tg-notify.py` | Main hook — all logic lives here |
| `tests/test_tg_notify.py` | Unit tests for every pure function |
| `install.sh` | Interactive installer |
| `README.md` | Already written |
| `LICENSE` | Already written |

---

## Task 1: Test infrastructure and project skeleton

**Files:**
- Create: `hooks/tg-notify.py` (empty module)
- Create: `tests/test_tg_notify.py` (test runner entry)
- Create: `tests/__init__.py`

- [ ] **Step 1: Install pytest (if not present)**

```bash
python3 -m pytest --version 2>/dev/null || pip3 install pytest
```

- [ ] **Step 2: Create empty hook module**

`hooks/tg-notify.py`:
```python
#!/usr/bin/env python3
"""ccotification — Claude Code → Telegram notifications."""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib import request, error

STATE_DIR = Path.home() / ".local/share/tg-hook"
CONFIG_FILE = STATE_DIR / "config.json"
STATE_FILE = STATE_DIR / "state.json"
USAGE_FILE = Path.home() / ".cache/ccstatusline/usage.json"
TG_API = "https://api.telegram.org/bot{token}/{method}"
```

- [ ] **Step 3: Create test file skeleton**

`tests/__init__.py`: (empty file)

`tests/test_tg_notify.py`:
```python
"""Unit tests for tg-notify hook."""
import json
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta

# Allow importing the hook module from hooks/
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))
import importlib
tg = importlib.import_module("tg-notify")
```

- [ ] **Step 4: Run test skeleton to confirm import works**

```bash
cd /home/victor/projects/ccotification
python3 -m pytest tests/ -v
```

Expected: `no tests ran` (0 collected), no import errors.

- [ ] **Step 5: Commit**

```bash
git add hooks/tg-notify.py tests/__init__.py tests/test_tg_notify.py
git commit -m "feat: project skeleton with test infrastructure"
```

---

## Task 2: Config and State management

**Files:**
- Modify: `hooks/tg-notify.py` — add `load_config`, `load_state`, `save_state`
- Modify: `tests/test_tg_notify.py` — add config/state tests

- [ ] **Step 1: Write failing tests**

Add to `tests/test_tg_notify.py`:
```python
import tempfile
import pytest

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
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python3 -m pytest tests/test_tg_notify.py::test_load_state_defaults -v
```

Expected: `AttributeError: module 'tg-notify' has no attribute 'load_state'`

- [ ] **Step 3: Implement functions**

Add to `hooks/tg-notify.py`:
```python
def load_config() -> dict:
    with open(CONFIG_FILE) as f:
        return json.load(f)

def load_state() -> dict:
    defaults = {
        "mute_until": None,
        "tg_offset": 0,
        "last_session_reset_at": None,
        "last_weekly_reset_at": None,
        "daily_date": None,
        "daily_count": 0,
        "daily_total_duration_s": 0,
    }
    if STATE_FILE.exists():
        data = json.loads(STATE_FILE.read_text())
        return {**defaults, **data}
    return defaults

def save_state(state: dict):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python3 -m pytest tests/test_tg_notify.py -k "config or state" -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add hooks/tg-notify.py tests/test_tg_notify.py
git commit -m "feat: config and state management"
```

---

## Task 3: Transcript parsing

**Files:**
- Modify: `hooks/tg-notify.py` — add `parse_transcript`, `get_cwd_from_session`
- Modify: `tests/test_tg_notify.py` — add transcript tests

- [ ] **Step 1: Write failing tests**

Add to `tests/test_tg_notify.py`:
```python
def make_transcript(messages: list, path: Path):
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
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python3 -m pytest tests/test_tg_notify.py -k "transcript" -v
```

Expected: `AttributeError: module 'tg-notify' has no attribute 'parse_transcript'`

- [ ] **Step 3: Implement functions**

Add to `hooks/tg-notify.py`:
```python
def get_cwd_from_session(session_id: str) -> str:
    """Find cwd from the session file matching session_id."""
    sessions_dir = Path.home() / ".claude/sessions"
    if sessions_dir.exists():
        for f in sessions_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                if data.get("sessionId") == session_id:
                    return data.get("cwd", os.getcwd())
            except Exception:
                pass
    return os.getcwd()

def parse_transcript(path: str, session_id: str = "") -> dict:
    """Parse JSONL transcript and return extracted data."""
    messages = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

    last_user = None
    last_assistant = None
    for msg in messages:
        t = msg.get("type")
        if t == "user":
            last_user = msg
        elif t == "assistant":
            last_assistant = msg

    # Duration: last user message → last assistant message
    duration_s = 0.0
    if last_user and last_assistant:
        try:
            t1 = datetime.fromisoformat(last_user["timestamp"].replace("Z", "+00:00"))
            t2 = datetime.fromisoformat(last_assistant["timestamp"].replace("Z", "+00:00"))
            duration_s = max(0.0, (t2 - t1).total_seconds())
        except Exception:
            pass

    # Text + tool_use count from last assistant message
    text = ""
    tool_count = 0
    if last_assistant:
        for block in last_assistant.get("message", {}).get("content", []):
            if block.get("type") == "text":
                text += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_count += 1

    # Tool errors: any tool_result with is_error in any user message
    has_errors = False
    for msg in messages:
        if msg.get("type") == "user":
            content = msg.get("message", {}).get("content", [])
            if isinstance(content, list):
                for block in content:
                    if block.get("type") == "tool_result" and block.get("is_error"):
                        has_errors = True

    cwd = get_cwd_from_session(session_id) if session_id else os.getcwd()

    return {
        "duration_s": duration_s,
        "text": text.strip(),
        "tool_count": tool_count,
        "has_errors": has_errors,
        "cwd": cwd,
    }
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python3 -m pytest tests/test_tg_notify.py -k "transcript" -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add hooks/tg-notify.py tests/test_tg_notify.py
git commit -m "feat: transcript parsing — duration, text, tool count, errors"
```

---

## Task 4: Preview extraction

**Files:**
- Modify: `hooks/tg-notify.py` — add `extract_preview`
- Modify: `tests/test_tg_notify.py` — add preview tests

- [ ] **Step 1: Write failing tests**

Add to `tests/test_tg_notify.py`:
```python
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
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python3 -m pytest tests/test_tg_notify.py -k "preview" -v
```

Expected: `AttributeError: module 'tg-notify' has no attribute 'extract_preview'`

- [ ] **Step 3: Implement**

Add to `hooks/tg-notify.py`:
```python
def extract_preview(text: str, max_chars: int = 150) -> str:
    """Return first 1-2 sentences, max max_chars chars, no word-cutting."""
    if not text or not text.strip():
        return ""
    # Strip code blocks
    cleaned = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"`[^`]+`", "", cleaned).strip()
    if not cleaned:
        return ""

    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    result = sentences[0]

    if len(result) < 40 and len(sentences) > 1:
        result = result + " " + sentences[1]

    if len(result) > max_chars:
        truncated = result[:max_chars]
        last_space = truncated.rfind(" ")
        if last_space > max_chars * 0.7:
            truncated = truncated[:last_space]
        result = truncated.rstrip(".,;:") + "…"

    return result
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python3 -m pytest tests/test_tg_notify.py -k "preview" -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add hooks/tg-notify.py tests/test_tg_notify.py
git commit -m "feat: smart preview extraction with code-block stripping"
```

---

## Task 5: Question detection and title logic

**Files:**
- Modify: `hooks/tg-notify.py` — add `count_questions_in_text`, `get_title`
- Modify: `tests/test_tg_notify.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_tg_notify.py`:
```python
def test_count_questions_none():
    assert tg.count_questions_in_text("I fixed the bug.") == 0

def test_count_questions_one():
    assert tg.count_questions_in_text("Which approach do you prefer?") == 1

def test_count_questions_two():
    assert tg.count_questions_in_text("Do you want X?\nOr maybe Y?") == 2

def test_count_questions_ignores_code():
    # ? in code block must not count
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
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python3 -m pytest tests/test_tg_notify.py -k "question or title" -v
```

Expected: `AttributeError` on missing functions.

- [ ] **Step 3: Implement**

Add to `hooks/tg-notify.py`:
```python
def count_questions_in_text(text: str) -> int:
    """Count ? at sentence endings, ignoring code blocks."""
    cleaned = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"`[^`]+`", "", cleaned)
    return len(re.findall(r"\?\s*(?:\n|$)", cleaned))

def get_title(duration_s: float, text: str, has_errors: bool) -> str:
    q = count_questions_in_text(text)
    if q >= 2:
        base = "❓ Нужна твоя помощь"
    elif q == 1:
        base = "🤔 Клод хочет уточнить"
    elif duration_s < 10:
        base = "⚡ Мгновенный ответ"
    elif duration_s < 30:
        base = "✅ Быстрый ответ"
    elif duration_s < 120:
        base = "🧠 Хорошо подумал"
    elif duration_s < 300:
        base = "🔧 Серьёзная работа"
    else:
        base = "🏆 Монументальная работа"
    return ("⚠️ " + base) if has_errors else base
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python3 -m pytest tests/test_tg_notify.py -k "question or title" -v
```

Expected: `12 passed`

- [ ] **Step 5: Commit**

```bash
git add hooks/tg-notify.py tests/test_tg_notify.py
git commit -m "feat: question detection and title logic"
```

---

## Task 6: Project path and git context

**Files:**
- Modify: `hooks/tg-notify.py` — add `get_project_path`, `get_git_context`
- Modify: `tests/test_tg_notify.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_tg_notify.py`:
```python
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
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python3 -m pytest tests/test_tg_notify.py -k "project_path or git_context" -v
```

Expected: `AttributeError` on missing functions.

- [ ] **Step 3: Implement**

Add to `hooks/tg-notify.py`:
```python
def get_project_path(cwd: str) -> str:
    """Return last 3 path components joined with ' / '."""
    parts = [p for p in Path(cwd).parts if p and p != "/"]
    return " / ".join(parts[-3:]) if parts else cwd

def get_git_context(cwd: str) -> dict | None:
    """Return {branch, short_hash, message} or None if not a git repo."""
    try:
        branch = subprocess.check_output(
            ["git", "-C", cwd, "branch", "--show-current"],
            stderr=subprocess.DEVNULL, text=True
        ).strip()
        log = subprocess.check_output(
            ["git", "-C", cwd, "log", "--oneline", "-1"],
            stderr=subprocess.DEVNULL, text=True
        ).strip()
        if not branch and not log:
            return None
        short_hash = log[:7] if log else ""
        commit_msg = log[8:50] if len(log) > 8 else ""
        return {"branch": branch, "short_hash": short_hash, "message": commit_msg}
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python3 -m pytest tests/test_tg_notify.py -k "project_path or git_context" -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add hooks/tg-notify.py tests/test_tg_notify.py
git commit -m "feat: project path and git context"
```

---

## Task 7: Usage reading and time formatting

**Files:**
- Modify: `hooks/tg-notify.py` — add `read_usage`, `format_time_until`
- Modify: `tests/test_tg_notify.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_tg_notify.py`:
```python
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
    from datetime import timezone
    future = (datetime.now(timezone.utc) + timedelta(hours=3, minutes=12)).isoformat()
    result = tg.format_time_until(future)
    assert "3ч" in result
    assert "12м" in result

def test_format_time_until_minutes_only():
    from datetime import timezone
    future = (datetime.now(timezone.utc) + timedelta(minutes=45)).isoformat()
    result = tg.format_time_until(future)
    assert "ч" not in result
    assert "45м" in result

def test_format_time_until_past():
    result = tg.format_time_until("2020-01-01T00:00:00+00:00")
    assert result == "скоро"
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python3 -m pytest tests/test_tg_notify.py -k "usage or time_until" -v
```

Expected: `AttributeError` on missing functions.

- [ ] **Step 3: Implement**

Add to `hooks/tg-notify.py`:
```python
def read_usage() -> dict | None:
    try:
        return json.loads(USAGE_FILE.read_text())
    except Exception:
        return None

def format_time_until(iso_str: str) -> str:
    """Return human-readable time until the given ISO timestamp."""
    try:
        reset = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = reset - now
        if delta.total_seconds() <= 0:
            return "скоро"
        total_minutes = int(delta.total_seconds() / 60)
        hours, minutes = divmod(total_minutes, 60)
        if hours > 0:
            return f"{hours}ч {minutes}м"
        return f"{minutes}м"
    except Exception:
        return "?"
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python3 -m pytest tests/test_tg_notify.py -k "usage or time_until" -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add hooks/tg-notify.py tests/test_tg_notify.py
git commit -m "feat: usage reading and time-until formatting"
```

---

## Task 8: Message building

**Files:**
- Modify: `hooks/tg-notify.py` — add `escape_html`, `build_message`, `build_keyboard`
- Modify: `tests/test_tg_notify.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_tg_notify.py`:
```python
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
    assert "<b>" in msg  # HTML formatting
    assert "<code>" in msg  # code block for project context

def test_build_message_with_usage():
    from datetime import timezone
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
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python3 -m pytest tests/test_tg_notify.py -k "escape or build_message or build_keyboard" -v
```

Expected: `AttributeError` on missing functions.

- [ ] **Step 3: Implement**

Add to `hooks/tg-notify.py`:
```python
def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def build_message(title: str, project_path: str, git: dict | None,
                  duration_s: float, preview: str, tool_count: int,
                  usage: dict | None) -> str:
    now = datetime.now().strftime("%H:%M:%S")
    m, s = divmod(int(duration_s), 60)
    dur_str = f"{m}м {s}с" if m > 0 else f"{s}с"

    lines = [f"<b>{escape_html(title)}</b>  ·  {now}", ""]

    # Project context block
    ctx = [f"┌ 📁 {escape_html(project_path)}"]
    if git:
        ctx.append(f"│ 🌿 {escape_html(git['branch'])}  ·  "
                   f"{escape_html(git['short_hash'])}  {escape_html(git['message'])}")
    ctx.append("└" + "─" * 37)
    lines.append("<code>" + "\n".join(ctx) + "</code>")
    lines.append("")

    if preview:
        lines.append(escape_html(preview))
        lines.append("")

    tool_line = f"🛠 {tool_count} инструментов  ·  ⏱ {dur_str}" if tool_count > 0 else f"⏱ {dur_str}"
    lines.append(tool_line)

    if usage:
        s_pct = usage.get("sessionUsage", 0)
        s_reset = usage.get("sessionResetAt", "")
        w_pct = usage.get("weeklyUsage", 0)
        w_reset = usage.get("weeklyResetAt", "")
        s_line = f"📊 Окно: {s_pct}%"
        if s_reset:
            s_line += f"  ·  сброс через {format_time_until(s_reset)}"
        lines.append(s_line)
        if w_pct > 0:
            w_line = f"📅 Неделя: {w_pct}%"
            if w_reset:
                w_line += f"  ·  сброс через {format_time_until(w_reset)}"
            lines.append(w_line)

    return "\n".join(lines)

def build_keyboard() -> dict:
    return {"inline_keyboard": [[
        {"text": "🔕 30 мин",     "callback_data": "mute_1800"},
        {"text": "🔕 1 час",      "callback_data": "mute_3600"},
        {"text": "🔕 3 часа",     "callback_data": "mute_10800"},
        {"text": "🔕 До завтра",  "callback_data": "mute_eod"},
    ]]}
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python3 -m pytest tests/test_tg_notify.py -k "escape or build_message or build_keyboard" -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add hooks/tg-notify.py tests/test_tg_notify.py
git commit -m "feat: message building with HTML formatting and inline keyboard"
```

---

## Task 9: Telegram API calls

**Files:**
- Modify: `hooks/tg-notify.py` — add `tg_request`, `send_message`, `poll_callbacks`, `answer_callback`
- Modify: `tests/test_tg_notify.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_tg_notify.py`:
```python
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
        result = tg.send_message("TOKEN", 12345, "Hello", None)
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
    cb_query = {
        "id": "cq1", "from": {}, "message": {}, "chat_instance": "",
        "data": "mute_3600"
    }
    response_data = {"ok": True, "result": [
        {"update_id": 100, "callback_query": cb_query}
    ]}
    with patch("urllib.request.urlopen", return_value=make_mock_response(response_data)):
        callbacks, new_offset = tg.poll_callbacks("TOKEN", 0)
    assert len(callbacks) == 1
    assert callbacks[0]["data"] == "mute_3600"
    assert new_offset == 101

def test_tg_request_network_error():
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
        result = tg.tg_request("TOKEN", "sendMessage", {"chat_id": 1})
    assert result == {}
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python3 -m pytest tests/test_tg_notify.py -k "send_message or poll_callbacks or tg_request" -v
```

Expected: `AttributeError` on missing functions.

- [ ] **Step 3: Implement**

Add to `hooks/tg-notify.py`:
```python
def tg_request(token: str, method: str, data: dict) -> dict:
    url = TG_API.format(token=token, method=method)
    body = json.dumps(data).encode()
    req = request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except error.URLError:
        return {}

def send_message(token: str, chat_id: int, text: str, reply_markup: dict = None) -> dict:
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)
    return tg_request(token, "sendMessage", data)

def poll_callbacks(token: str, offset: int) -> tuple:
    """Returns (list_of_callback_queries, new_offset)."""
    result = tg_request(token, "getUpdates", {
        "offset": offset, "timeout": 0, "limit": 20,
        "allowed_updates": ["callback_query"],
    })
    updates = result.get("result", [])
    callbacks = []
    new_offset = offset
    for update in updates:
        new_offset = max(new_offset, update["update_id"] + 1)
        if "callback_query" in update:
            callbacks.append(update["callback_query"])
    return callbacks, new_offset

def answer_callback(token: str, callback_query_id: str):
    tg_request(token, "answerCallbackQuery", {"callback_query_id": callback_query_id})
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python3 -m pytest tests/test_tg_notify.py -k "send_message or poll_callbacks or tg_request" -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add hooks/tg-notify.py tests/test_tg_notify.py
git commit -m "feat: Telegram API — send, poll, answer callback"
```

---

## Task 10: Mute logic

**Files:**
- Modify: `hooks/tg-notify.py` — add `process_callbacks`, `is_muted`
- Modify: `tests/test_tg_notify.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_tg_notify.py`:
```python
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
    # Should be tomorrow 23:59:59
    tomorrow = datetime.now() + timedelta(days=1)
    assert until.day == tomorrow.day or until.date() >= datetime.now().date()
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python3 -m pytest tests/test_tg_notify.py -k "muted or process_callbacks" -v
```

Expected: `AttributeError` on missing functions.

- [ ] **Step 3: Implement**

Add to `hooks/tg-notify.py`:
```python
def process_callbacks(token: str, state: dict) -> dict:
    """Poll Telegram for mute button presses, update state."""
    callbacks, new_offset = poll_callbacks(token, state.get("tg_offset", 0))
    state["tg_offset"] = new_offset
    for cb in callbacks:
        data = cb.get("data", "")
        answer_callback(token, cb["id"])
        if data == "mute_eod":
            tomorrow = (datetime.now() + timedelta(days=1)).replace(
                hour=23, minute=59, second=59, microsecond=0)
            state["mute_until"] = tomorrow.isoformat()
        elif data.startswith("mute_"):
            seconds = int(data.split("_")[1])
            state["mute_until"] = (datetime.now() + timedelta(seconds=seconds)).isoformat()
    return state

def is_muted(state: dict) -> bool:
    mute_until = state.get("mute_until")
    if not mute_until:
        return False
    try:
        return datetime.now() < datetime.fromisoformat(mute_until)
    except Exception:
        return False
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python3 -m pytest tests/test_tg_notify.py -k "muted or process_callbacks" -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add hooks/tg-notify.py tests/test_tg_notify.py
git commit -m "feat: mute logic with inline keyboard callbacks"
```

---

## Task 11: Daily stats

**Files:**
- Modify: `hooks/tg-notify.py` — add `update_daily_stats`
- Modify: `tests/test_tg_notify.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_tg_notify.py`:
```python
def test_update_daily_stats_new_day():
    state = {"daily_date": "2026-01-01", "daily_count": 10, "daily_total_duration_s": 500}
    # Simulate today being different from stored date
    with patch("tg.datetime") as mock_dt:
        mock_dt.now.return_value = datetime(2026, 1, 2, 12, 0, 0)
        mock_dt.fromisoformat = datetime.fromisoformat
        updated = tg.update_daily_stats(state, 30.0)
    assert updated["daily_date"] == "2026-01-02"
    assert updated["daily_count"] == 1
    assert updated["daily_total_duration_s"] == 30.0

def test_update_daily_stats_same_day():
    today = datetime.now().strftime("%Y-%m-%d")
    state = {"daily_date": today, "daily_count": 5, "daily_total_duration_s": 200}
    updated = tg.update_daily_stats(state, 60.0)
    assert updated["daily_count"] == 6
    assert updated["daily_total_duration_s"] == 260.0
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python3 -m pytest tests/test_tg_notify.py -k "daily_stats" -v
```

Expected: `AttributeError` on missing function.

- [ ] **Step 3: Implement**

Add to `hooks/tg-notify.py`:
```python
def update_daily_stats(state: dict, duration_s: float) -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    if state.get("daily_date") != today:
        state["daily_date"] = today
        state["daily_count"] = 0
        state["daily_total_duration_s"] = 0.0
    state["daily_count"] = state.get("daily_count", 0) + 1
    state["daily_total_duration_s"] = state.get("daily_total_duration_s", 0.0) + duration_s
    return state
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python3 -m pytest tests/test_tg_notify.py -k "daily_stats" -v
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add hooks/tg-notify.py tests/test_tg_notify.py
git commit -m "feat: daily stats tracking"
```

---

## Task 12: Cron management

**Files:**
- Modify: `hooks/tg-notify.py` — add `update_cron_entry`
- Modify: `tests/test_tg_notify.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_tg_notify.py`:
```python
def test_update_cron_entry_writes_entry():
    reset_at = "2026-05-07T15:42:00+00:00"
    # Simulate empty crontab
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        tg.update_cron_entry(reset_at, "session")
    # Second call should be `crontab -` (the write)
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
    # Old line gone, new line present
    assert "30 10 7 5" not in new_crontab
    assert "42 15" in new_crontab  # new reset time (UTC)
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python3 -m pytest tests/test_tg_notify.py -k "cron" -v
```

Expected: `AttributeError` on missing function.

- [ ] **Step 3: Implement**

Add to `hooks/tg-notify.py`:
```python
def update_cron_entry(reset_at: str, reset_type: str):
    """Write/replace managed cron entry for the given reset time."""
    try:
        reset = datetime.fromisoformat(reset_at.replace("Z", "+00:00")).astimezone()
        marker = f"# tg-hook-{reset_type}-reset (managed by ccotification)"
        cron_line = (
            f"{reset.minute} {reset.hour} {reset.day} {reset.month} * "
            f"python3 ~/.claude/hooks/tg-notify.py --notify-reset {reset_type}"
        )
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        existing = result.stdout if result.returncode == 0 else ""
        lines = [l for l in existing.splitlines()
                 if marker not in l and f"--notify-reset {reset_type}" not in l]
        lines.extend([marker, cron_line])
        subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n",
                       text=True, check=True)
    except Exception:
        pass
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python3 -m pytest tests/test_tg_notify.py -k "cron" -v
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add hooks/tg-notify.py tests/test_tg_notify.py
git commit -m "feat: cron management for reset notifications"
```

---

## Task 13: Reset notifications and --notify-reset flag

**Files:**
- Modify: `hooks/tg-notify.py` — add `check_reset_notifications`, `notify_reset`
- Modify: `tests/test_tg_notify.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_tg_notify.py`:
```python
def test_check_reset_no_change():
    """If sessionResetAt unchanged, no notification sent."""
    usage = {"sessionUsage": 5, "sessionResetAt": "2026-05-07T15:00:00+00:00",
             "weeklyUsage": 10, "weeklyResetAt": "2026-05-08T16:00:00+00:00"}
    state = {"last_session_reset_at": "2026-05-07T15:00:00+00:00",
             "last_weekly_reset_at": "2026-05-08T16:00:00+00:00"}
    with patch("urllib.request.urlopen") as mock_open:
        tg.check_reset_notifications("TOKEN", 12345, usage, state)
    assert not mock_open.called  # No message sent

def test_check_reset_session_changed():
    """If sessionResetAt changed and previous was not None → send notification."""
    usage = {"sessionUsage": 2, "sessionResetAt": "2026-05-07T20:00:00+00:00",
             "weeklyUsage": 10, "weeklyResetAt": "2026-05-08T16:00:00+00:00"}
    state = {"last_session_reset_at": "2026-05-07T15:00:00+00:00",
             "last_weekly_reset_at": "2026-05-08T16:00:00+00:00"}
    sent_texts = []
    def fake_send(token, chat_id, text, kb=None):
        sent_texts.append(text)
    with patch.object(tg, "send_message", side_effect=fake_send):
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
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python3 -m pytest tests/test_tg_notify.py -k "reset" -v
```

Expected: `AttributeError` on missing functions.

- [ ] **Step 3: Implement**

Add to `hooks/tg-notify.py`:
```python
def check_reset_notifications(token: str, chat_id: int,
                               usage: dict, state: dict) -> dict:
    if not usage:
        return state

    s_reset = usage.get("sessionResetAt")
    w_reset = usage.get("weeklyResetAt")

    if s_reset and s_reset != state.get("last_session_reset_at"):
        if state.get("last_session_reset_at") is not None:
            send_message(token, chat_id,
                "🔄 <b>Окно сброшено!</b>\n\n"
                f"📊 Окно: {usage.get('sessionUsage', 0)}% → снова полный доступ\n"
                f"⏰ Следующий сброс через {format_time_until(s_reset)}")
        state["last_session_reset_at"] = s_reset
        update_cron_entry(s_reset, "session")

    if w_reset and w_reset != state.get("last_weekly_reset_at"):
        if state.get("last_weekly_reset_at") is not None:
            send_message(token, chat_id,
                "🗓 <b>Недельный лимит сброшен!</b>\n\n"
                f"📅 Неделя: {usage.get('weeklyUsage', 0)}%\n"
                f"⏰ Следующий сброс через {format_time_until(w_reset)}")
        state["last_weekly_reset_at"] = w_reset
        update_cron_entry(w_reset, "weekly")

    return state

def notify_reset(reset_type: str):
    """Called by cron with --notify-reset <type>."""
    config = load_config()
    usage = read_usage()
    if reset_type == "session":
        next_r = format_time_until(usage.get("sessionResetAt", "")) if usage else "?"
        text = ("🔄 <b>Окно сброшено!</b>\n\n"
                "📊 Снова полный доступ\n"
                f"⏰ Следующий сброс через {next_r}")
    else:
        next_r = format_time_until(usage.get("weeklyResetAt", "")) if usage else "?"
        text = ("🗓 <b>Недельный лимит сброшен!</b>\n\n"
                "📅 Недельные лимиты обновлены\n"
                f"⏰ Следующий сброс через {next_r}")
    send_message(config["bot_token"], config["chat_id"], text)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python3 -m pytest tests/test_tg_notify.py -k "reset" -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add hooks/tg-notify.py tests/test_tg_notify.py
git commit -m "feat: reset notifications for session and weekly limits"
```

---

## Task 14: Main function and hook wiring

**Files:**
- Modify: `hooks/tg-notify.py` — add `main()` and `if __name__ == "__main__":`
- Modify: `tests/test_tg_notify.py` — integration test

- [ ] **Step 1: Write failing test**

Add to `tests/test_tg_notify.py`:
```python
def test_main_sends_notification(tmp_path, monkeypatch):
    # Setup config
    config = {"bot_token": "TESTTOKEN", "chat_id": 99999}
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(config))
    monkeypatch.setattr(tg, "CONFIG_FILE", cfg_file)
    monkeypatch.setattr(tg, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(tg, "STATE_DIR", tmp_path)
    monkeypatch.setattr(tg, "USAGE_FILE", tmp_path / "missing.json")

    # Setup transcript
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
    def fake_send(token, chat_id, text, kb=None):
        sent.append(text)
        return {}

    empty_updates = {"ok": True, "result": []}
    with patch("urllib.request.urlopen", return_value=make_mock_response(empty_updates)):
        with patch.object(tg, "send_message", side_effect=fake_send):
            with patch.object(tg, "get_cwd_from_session", return_value="/home/victor"):
                with patch.object(tg, "update_cron_entry"):
                    sys.stdin = __import__("io").StringIO(hook_input)
                    tg.main()

    assert len(sent) == 1
    assert "🔧" in sent[0] or "🧠" in sent[0]  # 120s → Серьёзная работа
    assert "victor" in sent[0]

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
            sys.stdin = __import__("io").StringIO(
                json.dumps({"session_id": "s", "transcript_path": str(transcript)}))
            tg.main()

    assert len(sent) == 0
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python3 -m pytest tests/test_tg_notify.py -k "test_main" -v
```

Expected: `AttributeError: module 'tg-notify' has no attribute 'main'`

- [ ] **Step 3: Implement main()**

Add to `hooks/tg-notify.py`:
```python
def main():
    # Handle --notify-reset flag (called by cron)
    if len(sys.argv) >= 3 and sys.argv[1] == "--notify-reset":
        notify_reset(sys.argv[2])
        return

    try:
        hook_input = json.loads(sys.stdin.read())
    except Exception:
        return

    transcript_path = hook_input.get("transcript_path", "")
    session_id = hook_input.get("session_id", "")
    if not transcript_path or not os.path.exists(transcript_path):
        return

    try:
        config = load_config()
    except Exception:
        return

    token = config["bot_token"]
    chat_id = config["chat_id"]
    state = load_state()

    # Poll for mute callbacks (before checking mute state)
    state = process_callbacks(token, state)

    if is_muted(state):
        save_state(state)
        return

    data = parse_transcript(transcript_path, session_id)
    title = get_title(data["duration_s"], data["text"], data["has_errors"])
    project_path = get_project_path(data["cwd"])
    git = get_git_context(data["cwd"])
    preview = extract_preview(data["text"]) if data["text"] else ""
    usage = read_usage()

    message = build_message(title, project_path, git, data["duration_s"],
                            preview, data["tool_count"], usage)
    send_message(token, chat_id, message, build_keyboard())

    state = update_daily_stats(state, data["duration_s"])
    state = check_reset_notifications(token, chat_id, usage, state)
    save_state(state)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run all tests**

```bash
python3 -m pytest tests/ -v
```

Expected: all tests pass (30+ passed, 0 failed)

- [ ] **Step 5: Commit**

```bash
git add hooks/tg-notify.py tests/test_tg_notify.py
git commit -m "feat: main() entry point and full hook integration"
```

---

## Task 15: install.sh

**Files:**
- Modify: `install.sh`

- [ ] **Step 1: Write install.sh**

`install.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail

HOOK_SRC="$(cd "$(dirname "$0")" && pwd)/hooks/tg-notify.py"
HOOK_DST="$HOME/.claude/hooks/tg-notify.py"
CONFIG_DIR="$HOME/.local/share/tg-hook"
CONFIG_FILE="$CONFIG_DIR/config.json"
SETTINGS="$HOME/.claude/settings.json"

echo "╔══════════════════════════════╗"
echo "║   ccotification installer   ║"
echo "╚══════════════════════════════╝"
echo ""

# Collect credentials
read -rp "Telegram Bot Token: " BOT_TOKEN
read -rp "Your Telegram Chat ID: " CHAT_ID

# Write config
mkdir -p "$CONFIG_DIR"
printf '{\n  "bot_token": "%s",\n  "chat_id": %s\n}\n' \
    "$BOT_TOKEN" "$CHAT_ID" > "$CONFIG_FILE"
echo "✓ Config saved to $CONFIG_FILE"

# Copy hook
mkdir -p "$(dirname "$HOOK_DST")"
cp "$HOOK_SRC" "$HOOK_DST"
chmod +x "$HOOK_DST"
echo "✓ Hook installed at $HOOK_DST"

# Patch settings.json
python3 - <<'PYEOF'
import json, sys, os

settings_path = os.path.expanduser("~/.claude/settings.json")
try:
    with open(settings_path) as f:
        settings = json.load(f)
except FileNotFoundError:
    settings = {}

hook_entry = {
    "hooks": [{"type": "command",
               "command": "python3 ~/.claude/hooks/tg-notify.py",
               "async": True}]
}

hooks = settings.setdefault("hooks", {})
stop_hooks = hooks.setdefault("Stop", [])

# Check if already registered
for h in stop_hooks:
    for inner in h.get("hooks", []):
        if "tg-notify.py" in inner.get("command", ""):
            print("✓ Hook already in settings.json")
            sys.exit(0)

stop_hooks.append(hook_entry)

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
print("✓ settings.json updated")
PYEOF

# Daily summary cron at 23:00
CRON_MARKER="# ccotification-daily-summary"
CRON_LINE="0 23 * * * python3 ~/.claude/hooks/tg-notify.py --daily-summary"
EXISTING=$(crontab -l 2>/dev/null || true)
if ! echo "$EXISTING" | grep -q "daily-summary"; then
    (echo "$EXISTING"; echo "$CRON_MARKER"; echo "$CRON_LINE") | crontab -
    echo "✓ Daily summary cron set (23:00)"
fi

# Send test message
echo ""
echo "Sending test message..."
python3 - <<PYEOF
import json, urllib.request
with open("$CONFIG_FILE") as f:
    cfg = json.load(f)
data = json.dumps({
    "chat_id": cfg["chat_id"],
    "text": "✅ <b>ccotification installed!</b>\n\nYou will now receive notifications after every Claude response.",
    "parse_mode": "HTML"
}).encode()
req = urllib.request.Request(
    f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage",
    data=data, headers={"Content-Type": "application/json"}
)
try:
    resp = urllib.request.urlopen(req, timeout=5)
    print("✓ Test message sent — check your Telegram!")
except Exception as e:
    print(f"✗ Could not send test message: {e}")
    print("  Check your bot token and chat ID.")
PYEOF

echo ""
echo "Done! Restart Claude Code or start a new session to activate."
```

- [ ] **Step 2: Make executable and test dry-run syntax**

```bash
chmod +x install.sh
bash -n install.sh && echo "Syntax OK"
```

Expected: `Syntax OK`

- [ ] **Step 3: Commit**

```bash
git add install.sh
git commit -m "feat: interactive installer with cron and settings.json patching"
```

---

## Task 16: Full test run and push

- [ ] **Step 1: Run the full test suite**

```bash
cd /home/victor/projects/ccotification
python3 -m pytest tests/ -v --tb=short
```

Expected: all tests pass.

- [ ] **Step 2: Manually install and test**

```bash
bash install.sh
```

Enter your real bot token (`8608830412:AAFg46_F0AuFO8eDSA3QcOoRzFcViOafTHk`) and chat ID (`863338180`). Verify test message arrives in Telegram.

- [ ] **Step 3: Trigger the hook manually to verify end-to-end**

Find the most recent transcript:
```bash
ls -t ~/.claude/projects/-home-victor/*.jsonl | head -1
```

Run the hook manually with a real transcript:
```bash
echo '{"session_id":"test","transcript_path":"<PATH_FROM_ABOVE>"}' \
    | python3 ~/.claude/hooks/tg-notify.py
```

Expected: notification arrives in Telegram.

- [ ] **Step 4: Push to GitHub**

```bash
git push origin main
```

Expected: `https://github.com/vityaayaa/ccotification` updated.

---

## Spec Coverage Check

| Spec requirement | Task |
|---|---|
| Dynamic titles by duration | Task 5 |
| Project name (2-3 levels) | Task 6 |
| Time of response | Task 8 |
| Duration | Tasks 3, 8 |
| Question detection | Task 5 |
| Limit tracking (session + weekly) | Tasks 7, 13 |
| Reset notifications via cron | Tasks 12, 13 |
| Mute buttons (inline keyboard) | Tasks 9, 10 |
| Git context (branch + commit) | Task 6 |
| Response preview | Task 4 |
| Tool count + error flag | Tasks 3, 8 |
| install.sh | Task 15 |
| GitHub repo | Done |
