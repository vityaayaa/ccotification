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
