from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

import discord


class DiscordChannelHandler(logging.Handler):
    """Sends WARNING+ log records to a Discord channel."""

    def __init__(self, bot: discord.Client, channel_id: int) -> None:
        super().__init__(level=logging.WARNING)
        self.bot = bot
        self.channel_id = channel_id

    def emit(self, record: logging.LogRecord) -> None:
        try:
            channel = self.bot.get_channel(self.channel_id)
            if channel is None:
                return
            msg = self.format(record)
            # Truncate to Discord's 2000-char limit
            if len(msg) > 1990:
                msg = msg[:1990] + "..."
            self.bot.loop.create_task(channel.send(f"```\n{msg}\n```"))
        except Exception:
            self.handleError(record)


def setup_logging(bot: discord.Client | None = None, channel_id: int | None = None) -> logging.Logger:
    logger = logging.getLogger("milo")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # Prevent duplicate logs to root logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Only add console/file handlers once (check if already configured)
    if not logger.handlers:
        # Console
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(formatter)
        logger.addHandler(console)

        # File
        os.makedirs("logs", exist_ok=True)
        file_handler = RotatingFileHandler(
            "logs/milo.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    # Discord channel (add if provided and not already present)
    if bot and channel_id:
        has_discord_handler = any(
            isinstance(h, DiscordChannelHandler) for h in logger.handlers
        )
        if not has_discord_handler:
            discord_handler = DiscordChannelHandler(bot, channel_id)
            discord_handler.setFormatter(formatter)
            logger.addHandler(discord_handler)

    return logger
