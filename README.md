<div align="center">

# Milo Bot

**Your personal Discord command center — daily briefings, AI chat, calendar management, media requests, game news, and more.**

Built with [discord.py](https://discordpy.readthedocs.io/) &bull; Deployed with Docker &bull; Powered by AI

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![discord.py](https://img.shields.io/badge/discord.py-2.4.0-5865F2?style=flat-square&logo=discord&logoColor=white)
![Docker](https://img.shields.io/badge/docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white)

</div>

---

## Features

### Daily Life

| Feature | Description | Trigger |
|:--------|:------------|:--------|
| **Morning Briefing** | Wake up to weather, outfit recommendations, and an inspirational quote — delivered every morning at 6 AM ET | Auto / `!briefing` |
| **Ask AI** | Get answers to anything using NanoGPT with real-time web search context via Tavily | Dedicated channel |
| **Calendar Invite** | Drop text, images, PDFs, or `.ics` files and Milo extracts event details and creates Google Calendar events | Dedicated channel |
| **Shopping List** | A shared, persistent shopping list for the household | `!add` `!remove` `!list` `!clear` |
| **Birthday Reminders** | Never miss a birthday or anniversary — get reminders on the day and 5 days before | Auto / `!birthday` `!anniversary` |

### Entertainment

| Feature | Description | Trigger |
|:--------|:------------|:--------|
| **Media Requests** | Search and request movies or TV shows through Overseerr, with Plex availability polling and notifications | `!request <query>` |
| **Coloring Book** | Generate AI coloring page images on demand | `!imagine <subject>` |

### Game & News Watchers

| Feature | Description | Interval |
|:--------|:------------|:---------|
| **Star Citizen Patch Notes** | Monitors RSI Spectrum for new patch notes and posts AI summaries | Every 10 min |
| **WoW Patch Notes** | Watches Wowhead RSS for World of Warcraft news | Every 10 min |
| **Nintendo Direct** | Scans Reddit for Nintendo Direct announcements with LLM verification | Every 5 min |
| **RSI Service Status** | Tracks Star Citizen service incidents via RSS with color-coded status updates | Every 5 min |
| **RSI YouTube** | Monitors the Roberts Space Industries YouTube channel for new video uploads | Every 10 min |
| **Trump Speech Summaries** | Monitors YouTube feeds (White House, C-SPAN, Fox News), extracts captions, and posts AI summaries with deduplication | Every 30 min |

### Admin

| Feature | Description | Trigger |
|:--------|:------------|:--------|
| **Restart** | Restart the bot remotely | `!restart` (log channel only) |
| **Logging** | Warnings and errors forwarded to a Discord channel in real time | Auto |

---

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/YourBr0ther/MiloBot.git
cd MiloBot

# 2. Configure environment
cp .env.example .env
# Edit .env with your tokens, API keys, and channel IDs

# 3. Add Google service account key
# Place service-account.json in the project root

# 4. Launch
docker-compose up -d --build

# 5. Verify
docker-compose logs -f
```

> Every variable in `.env` is **required** — the bot will refuse to start if any are missing.

---

## Project Structure

```
miloBot/
├── bot/
│   ├── cogs/              # Feature modules (auto-loaded on startup)
│   ├── services/          # External API wrappers
│   ├── utils/             # Shared helpers (embed builders, etc.)
│   ├── config.py          # Settings dataclass, loaded from .env
│   ├── logger.py          # Console, file, and Discord channel logging
│   └── main.py            # Bot entrypoint and cog loader
├── data/                  # Persistent JSON data (volume-mounted)
├── logs/                  # Rotating log files (volume-mounted)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

## Environment Variables

All variables are defined in [`.env.example`](.env.example). Here's a quick reference:

| Group | Variables |
|:------|:---------|
| **Discord** | `DISCORD_TOKEN`, plus channel IDs for each feature (`BRIEFING_CHANNEL_ID`, `LOG_CHANNEL_ID`, `ASK_AI_CHANNEL_ID`, `FUN_CHANNEL_ID`, `EVENT_CHANNEL_ID`, `REQUESTS_CHANNEL_ID`, `PATCH_NOTES_CHANNEL_ID`, `WOW_CHANNEL_ID`, `NINTENDO_CHANNEL_ID`, `SHOPPING_LIST_CHANNEL_ID`, `BIRTHDAY_REMINDER_CHANNEL_ID`, `BIRTHDAY_COMMANDS_CHANNEL_ID`, `TRUMP_SPEECH_CHANNEL_ID`, `SC_YOUTUBE_CHANNEL_ID`) |
| **Google Calendar** | `GOOGLE_CALENDAR_ID`, `GOOGLE_SERVICE_ACCOUNT_PATH` |
| **Weather** | `OWM_API_KEY`, `OWM_ZIP_CODE` |
| **AI / Search** | `NANOGPT_API_KEY`, `TAVILY_API_KEY` |
| **Media** | `OVERSEERR_URL`, `OVERSEERR_API_KEY`, `PLEX_MACHINE_ID`, `PLEX_TOKEN`, `PLEX_URL` |

---

## Running Without Docker

Requires Python 3.12+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m bot.main
```

---

## Rebuilding After Changes

```bash
docker-compose up -d --build
```

Persistent data in `data/` and `logs/` is preserved across rebuilds via Docker volume mounts.

---

## Adding a New Feature

1. Create a new file in `bot/cogs/` (e.g., `my_feature.py`)
2. Define a `commands.Cog` subclass with an `async def setup(bot)` function
3. Add any new settings to `Settings` in `bot/config.py`, its `from_env` classmethod, and `.env.example`
4. Rebuild: `docker-compose up -d --build`

> Cog files prefixed with `_` are skipped by the auto-loader.

---

## Tech Stack

| Component | Technology |
|:----------|:-----------|
| Framework | [discord.py 2.4.0](https://discordpy.readthedocs.io/) |
| Runtime | Python 3.12+ |
| HTTP | aiohttp (async) |
| AI | NanoGPT + Tavily |
| Calendar | Google Calendar API |
| Weather | OpenWeatherMap |
| Media | Overseerr + Plex |
| PDF Parsing | PyMuPDF |
| Captions | yt-dlp |
| Deployment | Docker + Docker Compose |

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/)
- A Discord bot token with the **Message Content** intent enabled
- API keys for the external services listed in `.env.example`
- A Google service account JSON key file (for calendar features)
