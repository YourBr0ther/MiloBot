from __future__ import annotations

import logging
import random
import re

import aiohttp
import discord
from discord.ext import commands

from bot.services.nanogpt import NanoGPTService

log = logging.getLogger("milo.coloring_book")

# SFW filter: block obvious NSFW keywords
BLOCKED_PATTERNS = re.compile(
    r"\b(nsfw|nude|naked|sex|porn|gore|violent|blood|kill|drug|weapon|gun)\b",
    re.IGNORECASE,
)


class ColoringView(discord.ui.View):
    """Persistent view with Retry and Print buttons."""

    def __init__(self, cog: ColoringBook, subject: str, author_id: int) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.subject = subject
        self.author_id = author_id

    @discord.ui.button(label="Retry", style=discord.ButtonStyle.primary, emoji="\U0001f504")
    async def retry(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the requester can retry.", ephemeral=True)
            return

        await interaction.response.defer()
        seed = random.randint(0, 2**32 - 1)
        try:
            async with aiohttp.ClientSession() as session:
                url = await self.cog.nanogpt.generate_coloring_page(session, self.subject, seed=seed)
        except Exception:
            log.exception("Retry image generation failed")
            await interaction.followup.send("Sorry, image generation failed. Try again!", ephemeral=True)
            return

        embed = discord.Embed(
            title="Coloring Page",
            description=f"**{self.subject}**",
            color=discord.Color.purple(),
        )
        embed.set_image(url=url)
        embed.set_footer(text=f"Seed: {seed}")

        new_view = ColoringView(self.cog, self.subject, self.author_id)
        await interaction.followup.send(embed=embed, view=new_view)

    @discord.ui.button(label="Print", style=discord.ButtonStyle.secondary, emoji="\U0001f5a8\ufe0f")
    async def print_page(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_message(
            "Print support coming soon! This button will send the image to your printer.",
            ephemeral=True,
        )


class ColoringBook(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        settings = bot.settings  # type: ignore[attr-defined]
        self.channel_id = settings.fun_channel_id
        self.nanogpt = NanoGPTService(settings.nanogpt_api_key)

    @commands.command(name="imagine")
    async def imagine(self, ctx: commands.Context, *, subject: str) -> None:
        """Generate a coloring book page. Usage: !imagine A cat in a forest"""
        if ctx.channel.id != self.channel_id:
            await ctx.send("This command can only be used in the fun channel.")
            return

        # SFW check
        if BLOCKED_PATTERNS.search(subject):
            await ctx.send("Let's keep it family-friendly! Please try a different subject.")
            return

        seed = random.randint(0, 2**32 - 1)

        async with ctx.typing():
            try:
                async with aiohttp.ClientSession() as session:
                    url = await self.nanogpt.generate_coloring_page(session, subject, seed=seed)
            except Exception:
                log.exception("Image generation failed")
                await ctx.send("Sorry, I couldn't generate that image. Please try again!")
                return

        embed = discord.Embed(
            title="Coloring Page",
            description=f"**{subject}**",
            color=discord.Color.purple(),
        )
        embed.set_image(url=url)
        embed.set_footer(text=f"Seed: {seed}")

        view = ColoringView(self, subject, ctx.author.id)
        await ctx.send(embed=embed, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ColoringBook(bot))
