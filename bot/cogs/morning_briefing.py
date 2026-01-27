from __future__ import annotations

import logging
from datetime import time

import aiohttp
import discord
from discord.ext import commands, tasks

from bot.services.nanogpt import NanoGPTService
from bot.services.outfit import recommend_outfit
from bot.services.weather import DailyWeather, WeatherService
from bot.utils.embeds import build_briefing_embed

log = logging.getLogger("milo.briefing")

# 7:00 AM Eastern = 12:00 UTC (EST) or 11:00 UTC (EDT)
# discord.ext.tasks supports timezone-aware times via the `time` kwarg.
# We specify both so the loop fires at 7 AM ET year-round.
import zoneinfo

EASTERN = zoneinfo.ZoneInfo("America/New_York")
BRIEFING_TIME = time(hour=7, minute=0, tzinfo=EASTERN)


class MorningBriefing(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        settings = bot.settings  # type: ignore[attr-defined]
        self.channel_id = settings.briefing_channel_id
        self.weather_svc = WeatherService(settings.owm_api_key, settings.owm_zip_code)
        self.quote_svc = NanoGPTService(settings.nanogpt_api_key)
        self.daily_briefing.start()

    async def cog_unload(self) -> None:
        self.daily_briefing.cancel()

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

        return build_briefing_embed(weather=weather, outfit=outfit, quote=quote)

    @tasks.loop(time=BRIEFING_TIME)
    async def daily_briefing(self) -> None:
        channel = self.bot.get_channel(self.channel_id)
        if channel is None:
            log.error("Briefing channel %s not found", self.channel_id)
            return

        log.info("Sending daily morning briefing")
        embed = await self._build_briefing()
        await channel.send(embed=embed)

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
