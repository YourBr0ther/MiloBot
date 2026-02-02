from __future__ import annotations

import asyncio
import base64
import json
import logging
from calendar import monthrange
from datetime import date, datetime, time
from pathlib import Path

import aiohttp
import discord
import fitz  # PyMuPDF
from discord.ext import commands, tasks

from bot.services.nanogpt import NanoGPTService

log = logging.getLogger("milo.lunch_menu")

import zoneinfo

EASTERN = zoneinfo.ZoneInfo("America/New_York")
DATA_PATH = Path("data/lunch_menu.json")
REMINDER_TIME = time(hour=6, minute=5, tzinfo=EASTERN)


MenuData = dict[str, dict[str, str]]


def _load_menu() -> MenuData:
    if not DATA_PATH.exists():
        return {}
    try:
        with DATA_PATH.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        log.exception("Failed to load lunch menu data")
        return {}


def _save_menu(data: MenuData) -> None:
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DATA_PATH.open("w") as f:
        json.dump(data, f, indent=2, sort_keys=True)


class LunchMenu(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        settings = bot.settings  # type: ignore[attr-defined]
        self.channel_id = settings.log_channel_id
        self.nanogpt = NanoGPTService(settings.nanogpt_api_key)
        self._last_reminder_date: date | None = None
        self.upload_reminder.start()

    def cog_unload(self) -> None:
        self.upload_reminder.cancel()

    def _restricted(self, ctx: commands.Context) -> bool:
        return ctx.channel.id != self.channel_id

    @commands.group(name="lunch", invoke_without_command=True)
    async def lunch(self, ctx: commands.Context, date_str: str | None = None) -> None:
        """Show today's school menu, or a specific date with !lunch MM-DD."""
        log.info("!lunch invoked in channel %s (expected %s)", ctx.channel.id, self.channel_id)
        if self._restricted(ctx):
            log.info("!lunch blocked by channel restriction")
            return

        today = datetime.now(EASTERN).date()
        if date_str:
            try:
                parsed = datetime.strptime(date_str, "%m-%d").date()
                lookup = parsed.replace(year=today.year)
            except ValueError:
                await ctx.send("Invalid date format. Use MM-DD, e.g. `!lunch 02-14`")
                return
        else:
            lookup = today

        menu = _load_menu()
        key = lookup.strftime("%Y-%m-%d")
        entry = menu.get(key)

        if entry:
            embed = discord.Embed(
                title=f"School Menu \u2014 {lookup.strftime('%A, %B %-d')}",
                color=discord.Color.green(),
            )
            if entry.get("breakfast"):
                embed.add_field(name="Breakfast", value=entry["breakfast"], inline=False)
            if entry.get("lunch"):
                embed.add_field(name="Lunch", value=entry["lunch"], inline=False)
        else:
            embed = discord.Embed(
                title=f"School Menu \u2014 {lookup.strftime('%A, %B %-d')}",
                description="No menu found for this date.",
                color=discord.Color.greyple(),
            )

        await ctx.send(embed=embed)

    @lunch.command(name="upload")
    async def lunch_upload(self, ctx: commands.Context) -> None:
        """Upload a lunch menu PDF. Attach the file to your message."""
        if self._restricted(ctx):
            return

        attachment = ctx.message.attachments[0] if ctx.message.attachments else None
        if not attachment or not attachment.filename.lower().endswith(".pdf"):
            await ctx.send("Please attach a PDF file with the lunch menu.")
            return

        async with ctx.typing():
            try:
                extracted = await self._extract_menu_from_pdf(attachment)
            except Exception:
                log.exception("Failed to extract lunch menu from PDF")
                await ctx.send("Sorry, I couldn't extract the menu from that PDF. Please try again.")
                return

        if not extracted:
            await ctx.send("I couldn't find any lunch menu dates in that PDF.")
            return

        # Merge into existing data
        menu = _load_menu()
        menu.update(extracted)
        _save_menu(menu)

        dates = sorted(extracted.keys())
        embed = discord.Embed(
            title="Lunch Menu Updated",
            description=f"Added **{len(extracted)}** days to the lunch menu.",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Date Range",
            value=f"{dates[0]} to {dates[-1]}",
            inline=False,
        )
        # Show a preview of the first few entries
        preview_lines = []
        for d in dates[:5]:
            dt = datetime.strptime(d, "%Y-%m-%d")
            preview_lines.append(f"**{dt.strftime('%b %-d')}**: {extracted[d].get('lunch', '')}")
        if len(dates) > 5:
            preview_lines.append(f"*...and {len(dates) - 5} more days*")
        embed.add_field(name="Preview", value="\n".join(preview_lines), inline=False)

        await ctx.send(embed=embed)

    @lunch.command(name="clear")
    async def lunch_clear(self, ctx: commands.Context) -> None:
        """Clear all stored lunch menu data."""
        if self._restricted(ctx):
            return
        _save_menu({})
        await ctx.send("Lunch menu data has been cleared.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Auto-detect PDF uploads in the lunch channel."""
        if message.author.bot:
            return
        if message.channel.id != self.channel_id:
            return
        if message.content.startswith("!"):
            return

        attachment = message.attachments[0] if message.attachments else None
        if not attachment or not attachment.filename.lower().endswith(".pdf"):
            return

        async with message.channel.typing():
            try:
                extracted = await self._extract_menu_from_pdf(attachment)
            except Exception:
                log.exception("Failed to extract lunch menu from PDF")
                await message.reply("Sorry, I couldn't extract the menu from that PDF.")
                return

        if not extracted:
            await message.reply("I couldn't find any lunch menu dates in that PDF.")
            return

        menu = _load_menu()
        menu.update(extracted)
        _save_menu(menu)

        dates = sorted(extracted.keys())
        embed = discord.Embed(
            title="Lunch Menu Updated",
            description=f"Added **{len(extracted)}** days to the lunch menu.",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Date Range",
            value=f"{dates[0]} to {dates[-1]}",
            inline=False,
        )
        preview_lines = []
        for d in dates[:5]:
            dt = datetime.strptime(d, "%Y-%m-%d")
            preview_lines.append(f"**{dt.strftime('%b %-d')}**: {extracted[d].get('lunch', '')}")
        if len(dates) > 5:
            preview_lines.append(f"*...and {len(dates) - 5} more days*")
        embed.add_field(name="Preview", value="\n".join(preview_lines), inline=False)

        await message.reply(embed=embed)

    async def _extract_menu_from_pdf(self, attachment: discord.Attachment) -> dict[str, str]:
        """Download a PDF, render all pages to images, and extract via AI vision."""
        pdf_bytes = await attachment.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

        page_uris: list[str] = []
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")
            b64 = base64.b64encode(img_bytes).decode()
            page_uris.append(f"data:image/png;base64,{b64}")
        doc.close()

        today = datetime.now(EASTERN).date()
        month_hint = today.strftime("%B %Y")

        last_err: Exception | None = None
        for attempt in range(2):
            try:
                async with aiohttp.ClientSession() as session:
                    return await self.nanogpt.extract_lunch_menu(session, page_uris, month_hint)
            except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
                last_err = exc
                if attempt == 0:
                    log.warning("Lunch menu extraction timed out, retrying after 5s...")
                    await asyncio.sleep(5)
        raise last_err

    # --- Admin reminder: upload next month's menu ---

    @tasks.loop(time=REMINDER_TIME)
    async def upload_reminder(self) -> None:
        today = datetime.now(EASTERN).date()
        if self._last_reminder_date == today:
            return

        # Only check during the last 7 days of the month
        _, days_in_month = monthrange(today.year, today.month)
        if today.day < days_in_month - 6:
            return

        # Check if next month has any entries
        if today.month == 12:
            next_month_prefix = f"{today.year + 1}-01"
        else:
            next_month_prefix = f"{today.year}-{today.month + 1:02d}"

        menu = _load_menu()
        has_next_month = any(k.startswith(next_month_prefix) for k in menu)

        if has_next_month:
            return

        channel = self.bot.get_channel(self.channel_id)
        if channel is None:
            log.error("Log channel %s not found for lunch reminder", self.channel_id)
            return

        embed = discord.Embed(
            title="Lunch Menu Reminder",
            description=(
                f"No lunch menu found for **{next_month_prefix}** yet.\n"
                "Time to upload next month's school lunch PDF!"
            ),
            color=discord.Color.orange(),
        )
        await channel.send(embed=embed)
        self._last_reminder_date = today
        log.info("Sent lunch menu upload reminder for %s", next_month_prefix)

    @upload_reminder.before_loop
    async def before_upload_reminder(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LunchMenu(bot))
