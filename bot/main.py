from __future__ import annotations

import asyncio
import logging
import pathlib

import discord
from discord.ext import commands

from bot.config import Settings
from bot.logger import setup_logging

log = logging.getLogger("milo")

COGS_DIR = pathlib.Path(__file__).parent / "cogs"


def create_bot(settings: Settings) -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(command_prefix="!", intents=intents)
    bot.settings = settings  # type: ignore[attr-defined]

    @bot.event
    async def on_ready() -> None:
        setup_logging(bot, settings.log_channel_id)
        if bot.user is None:
            log.error("Bot user is None in on_ready event")
            return
        log.info("Milo is online! Logged in as %s (ID: %s)", bot.user, bot.user.id)

    async def _setup_hook() -> None:
        await load_cogs(bot)

    bot.setup_hook = _setup_hook

    return bot


async def load_cogs(bot: commands.Bot) -> None:
    for path in sorted(COGS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        module = f"bot.cogs.{path.stem}"
        try:
            await bot.load_extension(module)
            log.info("Loaded cog: %s", module)
        except Exception:
            log.exception("Failed to load cog: %s", module)


def main() -> None:
    settings = Settings.from_env()
    setup_logging()  # console + file before bot is ready
    bot = create_bot(settings)
    bot.run(settings.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
