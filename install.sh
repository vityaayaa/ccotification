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
