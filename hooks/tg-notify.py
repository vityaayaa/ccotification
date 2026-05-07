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
