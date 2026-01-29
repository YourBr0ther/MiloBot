from __future__ import annotations

import json
import logging
from datetime import date, datetime, time
from pathlib import Path

import aiohttp
import discord
from discord.ext import commands, tasks

from bot.services.nanogpt import NanoGPTService
from bot.services.outfit import recommend_outfit
from bot.services.weather import DailyWeather, WeatherService
from bot.utils.embeds import build_briefing_embed

log = logging.getLogger("milo.briefing")

# 6:00 AM Eastern - discord.ext.tasks handles DST automatically with tzinfo
import zoneinfo

EASTERN = zoneinfo.ZoneInfo("America/New_York")
LUNCH_DATA_PATH = Path("data/lunch_menu.json")
BRIEFING_TIME = time(hour=6, minute=0, tzinfo=EASTERN)


class MorningBriefing(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        settings = bot.settings  # type: ignore[attr-defined]
        self.channel_id = settings.briefing_channel_id
        self.weather_svc = WeatherService(settings.owm_api_key, settings.owm_zip_code)
        self.quote_svc = NanoGPTService(settings.nanogpt_api_key)
        self._last_briefing_date: date | None = None  # Idempotency guard
        self.daily_briefing.start()

    async def cog_unload(self) -> None:
        self.daily_briefing.cancel()

    def _get_today_meals(self) -> tuple[str | None, str | None]:
        """Look up today's breakfast and lunch from the menu data file."""
        if not LUNCH_DATA_PATH.exists():
            return None, None
        try:
            data = json.loads(LUNCH_DATA_PATH.read_text())
            today_str = datetime.now(EASTERN).strftime("%Y-%m-%d")
            entry = data.get(today_str)
            if entry and isinstance(entry, dict):
                return entry.get("breakfast"), entry.get("lunch")
            return None, None
        except (json.JSONDecodeError, OSError):
            log.exception("Failed to read lunch menu data")
            return None, None

    async def _build_briefing(self) -> discord.Embed:
        weather: DailyWeather | None = None
        outfit: str | None = None
        quote: str | None = None

        async with aiohttp.ClientSession() as session:
            # Weather + outfit
            try:
                weather = await self.weather_svc.get_today(session)
                outfit = recommend_outfit(weather)
            except Exception:
                log.exception("Failed to fetch weather")

            # Quote (has its own fallback)
            quote = await self.quote_svc.get_quote(session)

        breakfast, lunch = self._get_today_meals()

        return build_briefing_embed(weather=weather, outfit=outfit, quote=quote, breakfast=breakfast, lunch=lunch)

    @tasks.loop(time=BRIEFING_TIME)
    async def daily_briefing(self) -> None:
        today = datetime.now(EASTERN).date()
        if self._last_briefing_date == today:
            log.warning("Briefing already sent today, skipping duplicate")
            return

        channel = self.bot.get_channel(self.channel_id)
        if channel is None:
            log.error("Briefing channel %s not found", self.channel_id)
            return

        log.info("Sending daily morning briefing")
        embed = await self._build_briefing()
        await channel.send(embed=embed)
        self._last_briefing_date = today

    @daily_briefing.before_loop
    async def before_daily_briefing(self) -> None:
        await self.bot.wait_until_ready()

    @commands.command(name="briefing")
    async def manual_briefing(self, ctx: commands.Context) -> None:
        """Manually trigger the morning briefing."""
        async with ctx.typing():
            embed = await self._build_briefing()
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MorningBriefing(bot))
