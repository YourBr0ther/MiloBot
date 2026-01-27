from __future__ import annotations

import logging

import aiohttp
import discord
from discord.ext import commands

from bot.services.nanogpt import NanoGPTService
from bot.services.tavily import TavilyService

log = logging.getLogger("milo.ask_ai")


class AskAI(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        settings = bot.settings  # type: ignore[attr-defined]
        self.channel_id = settings.ask_ai_channel_id
        self.nanogpt = NanoGPTService(settings.nanogpt_api_key)
        self.tavily = TavilyService(settings.tavily_api_key)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.channel.id != self.channel_id:
            return
        # Ignore command invocations
        if message.content.startswith("!"):
            return

        question = message.content.strip()
        if not question:
            return

        async with message.channel.typing():
            try:
                async with aiohttp.ClientSession() as session:
                    search_context = await self.tavily.search(question, session)
                    answer = await self.nanogpt.ask(session, question, search_context)
            except Exception:
                log.exception("Failed to get AI response")
                answer = "Sorry, I couldn't process that right now. Try again in a moment!"

        # Split long responses to stay within Discord's 2000-char limit
        while len(answer) > 2000:
            split_at = answer.rfind("\n", 0, 2000)
            if split_at == -1:
                split_at = 2000
            await message.reply(answer[:split_at])
            answer = answer[split_at:].lstrip()

        await message.reply(answer)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AskAI(bot))
