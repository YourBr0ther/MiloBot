from __future__ import annotations

import logging

import aiohttp
import discord
from discord.ext import commands, tasks

from bot.services.nanogpt import NanoGPTService
from bot.services.spectrum import SpectrumService

log = logging.getLogger("milo.patch_notes")

SPECTRUM_CHANNEL_ID = "190048"  # PTU Patch Notes forum on Spectrum

SUMMARY_PROMPT = """\
You are summarizing Star Citizen patch notes for a Discord gaming community.

Rules:
- Focus on: new features, new ships, new contracts, new gameplay, and VR updates.
- IGNORE bug fixes entirely — do not mention them.
- Keep it concise (bullet points).
- If there are VR-related changes, put them in their own "VR Updates" section.
- Use Discord markdown formatting (bold, bullet points).
- Do NOT include the patch version in your summary (it will be in the embed title).
- If there is essentially nothing noteworthy beyond bug fixes, just say "This patch is primarily bug fixes and stability improvements."

Patch notes to summarize:
{content}"""


class PatchNotes(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        settings = bot.settings  # type: ignore[attr-defined]
        self.channel_id = settings.patch_notes_channel_id
        self.spectrum = SpectrumService()
        self.nanogpt = NanoGPTService(settings.nanogpt_api_key)
        self.seen_thread_ids: set[str] = set()
        self._first_run = True
        self.check_patch_notes.start()

    def cog_unload(self) -> None:
        self.check_patch_notes.cancel()

    @tasks.loop(minutes=10)
    async def check_patch_notes(self) -> None:
        try:
            async with aiohttp.ClientSession() as session:
                threads = await self.spectrum.get_threads(session, SPECTRUM_CHANNEL_ID)

            if not threads:
                return

            # On first run, seed the seen set so we don't spam old posts.
            if self._first_run:
                self.seen_thread_ids = {t["id"] for t in threads}
                self._first_run = False
                log.info("Patch notes: seeded %d existing thread IDs", len(self.seen_thread_ids))
                return

            new_threads = [t for t in threads if t["id"] not in self.seen_thread_ids]
            if not new_threads:
                return

            channel = self.bot.get_channel(self.channel_id)
            if not channel:
                log.error("Patch notes channel %s not found", self.channel_id)
                return

            for thread in new_threads:
                self.seen_thread_ids.add(thread["id"])
                await self._post_summary(channel, thread)

        except Exception:
            log.exception("Error checking patch notes")

    async def _post_summary(self, channel: discord.abc.Messageable, thread: dict) -> None:
        thread_id = thread["id"]
        slug = thread["slug"]
        subject = thread["subject"]
        link = SpectrumService.thread_url(SPECTRUM_CHANNEL_ID, slug)

        try:
            async with aiohttp.ClientSession() as session:
                content = await self.spectrum.get_thread_content(session, thread_id, slug)
                if not content:
                    log.warning("Empty content for thread %s", thread_id)
                    return

                # Truncate to avoid token limits (keep first ~6000 chars)
                summary = await self.nanogpt.ask(
                    session,
                    SUMMARY_PROMPT.format(content=content[:6000]),
                )
        except Exception:
            log.exception("Failed to summarize patch notes for thread %s", thread_id)
            return

        embed = discord.Embed(
            title=subject,
            url=link,
            description=summary[:4096],
            color=discord.Color.dark_gold(),
        )
        embed.set_footer(text="Star Citizen Patch Notes")

        await channel.send(embed=embed)

    @commands.command(name="testpatch")
    @commands.is_owner()
    async def test_patch(self, ctx: commands.Context) -> None:
        """Post a summary of the latest patch notes for testing."""
        async with ctx.typing():
            async with aiohttp.ClientSession() as session:
                threads = await self.spectrum.get_threads(session, SPECTRUM_CHANNEL_ID)
            if not threads:
                await ctx.reply("No threads found.")
                return
            await self._post_summary(ctx.channel, threads[0])

    @check_patch_notes.before_loop
    async def before_check(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PatchNotes(bot))
