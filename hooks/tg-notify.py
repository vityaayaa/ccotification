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


def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_message(title: str, project_path: str, git: dict | None,
                  duration_s: float, preview: str, tool_count: int,
                  usage: dict | None) -> str:
    now = datetime.now().strftime("%H:%M:%S")
    m, s = divmod(int(duration_s), 60)
    dur_str = f"{m}м {s}с" if m > 0 else f"{s}с"

    lines = [f"<b>{escape_html(title)}</b>  ·  {now}", ""]

    # Project context block (code block for visual separation)
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


def update_daily_stats(state: dict, duration_s: float) -> dict:
    today = datetime.now().strftime("%Y-%m-%d")
    if state.get("daily_date") != today:
        state["daily_date"] = today
        state["daily_count"] = 0
        state["daily_total_duration_s"] = 0.0
    state["daily_count"] = state.get("daily_count", 0) + 1
    state["daily_total_duration_s"] = state.get("daily_total_duration_s", 0.0) + duration_s
    return state

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
