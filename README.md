# ccotification

> Claude Code → Telegram notifications

A [Claude Code](https://claude.ai/code) `Stop`-hook that sends a Telegram message every time Claude finishes a response.

**No daemon. No background service. Just a Python script.**

---

## Features

- **Smart titles** based on generation time — ⚡ instant to 🏆 monumental
- **Question detection** — knows when Claude is waiting for your reply
- **Project context** — shows folder path, git branch, last commit
- **Response preview** — first sentence(s) of the reply, no word-cutting
- **Tool summary** — how many tools Claude used, ⚠️ if errors occurred
- **Usage limits** — current window %, next reset time (reads from ccstatusline cache)
- **Reset notifications** — alerts when your 5-hour window or weekly limit resets, via cron (works even when computer is off)
- **Mute buttons** — inline Telegram keyboard: 30 min / 1 hour / 3 hours / until tomorrow
- **Daily summary** — cron at 23:00: how many responses, total time worked

---

## Requirements

- Python 3.8+
- [Claude Code](https://claude.ai/code) with a subscription (Pro / Max)
- A Telegram bot token ([create one via @BotFather](https://t.me/botfather))
- Your Telegram chat ID ([get it via @userinfobot](https://t.me/userinfobot))
- Optional: [ccstatusline](https://github.com/nehpets24/ccstatusline) for live usage data

---

## Install

```bash
git clone https://github.com/vityaayaa/ccotification.git
cd ccotification
bash install.sh
```

The installer will ask for your bot token and chat ID, copy the hook, patch `~/.claude/settings.json`, set up cron entries, and send a test message.

---

## Message format

```
🧠 Хорошо подумал  ·  14:23:45

┌ 📁 projects / myapp
│ 🌿 main  ·  a1b2c3  Fix button styles
└─────────────────────────────────────

Implemented the animation component with three
states: hover, active, disabled...

🛠 6 инструментов
📊 Окно: 7%  ·  сброс через 3ч 12м

[🔕 30 мин]  [🔕 1 час]  [🔕 3 часа]  [🔕 До завтра]
```

### Title thresholds

| Duration | Title |
|---|---|
| < 10s | ⚡ Мгновенный ответ |
| 10–30s | ✅ Быстрый ответ |
| 30–120s | 🧠 Хорошо подумал |
| 2–5 min | 🔧 Серьёзная работа |
| > 5 min | 🏆 Монументальная работа |
| Ends with `?` | 🤔 Клод хочет уточнить |
| Multiple `?` | ❓ Нужна твоя помощь |

---

## Configuration

Config lives at `~/.local/share/tg-hook/config.json`:

```json
{
  "bot_token": "YOUR_BOT_TOKEN",
  "chat_id": 123456789
}
```

---

## Manual install

```bash
cp hooks/tg-notify.py ~/.claude/hooks/tg-notify.py
chmod +x ~/.claude/hooks/tg-notify.py
```

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/hooks/tg-notify.py",
            "async": true
          }
        ]
      }
    ]
  }
}
```

---

## License

MIT
