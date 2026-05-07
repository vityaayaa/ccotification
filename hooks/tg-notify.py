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

    if len(result) < 30 and len(sentences) > 1:
        result = result + " " + sentences[1]

    if len(result) > max_chars:
        truncated = result[:max_chars]
        last_space = truncated.rfind(" ")
        if last_space > max_chars * 0.7:
            truncated = truncated[:last_space]
        result = truncated.rstrip(".,;:") + "…"

    return result


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
