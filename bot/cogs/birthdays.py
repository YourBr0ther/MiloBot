from __future__ import annotations

import json
import logging
from datetime import date, datetime, time
from pathlib import Path
from typing import TypedDict

import discord
from discord.ext import commands, tasks

from bot.utils.embeds import build_birthday_embed, build_anniversary_embed

log = logging.getLogger("milo.birthdays")

import zoneinfo

EASTERN = zoneinfo.ZoneInfo("America/New_York")
REMINDER_TIME = time(hour=6, minute=0, tzinfo=EASTERN)

DATA_FILE = Path("data/birthdays.json")


class BirthdayEntry(TypedDict):
    name: str
    date: str  # MM-DD format
    year: int | None


class AnniversaryEntry(TypedDict):
    name: str
    date: str  # MM-DD format
    year: int | None


class BirthdayData(TypedDict):
    birthdays: list[BirthdayEntry]
    anniversaries: list[AnniversaryEntry]


def _load_data() -> BirthdayData:
    if not DATA_FILE.exists():
        return {"birthdays": [], "anniversaries": []}
    try:
        with DATA_FILE.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        log.exception("Failed to load birthday data")
        return {"birthdays": [], "anniversaries": []}


def _save_data(data: BirthdayData) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with DATA_FILE.open("w") as f:
        json.dump(data, f, indent=2)


def _parse_date(date_str: str) -> tuple[int, int]:
    """Parse MM-DD string into (month, day) tuple."""
    parts = date_str.split("-")
    return int(parts[0]), int(parts[1])


def _format_date(month: int, day: int) -> str:
    """Format month/day as a readable string like 'March 15'."""
    d = date(2000, month, day)
    return d.strftime("%B %-d")


def _days_until(month: int, day: int, today: date) -> int:
    """Calculate days until the next occurrence of this date."""
    event_date = date(today.year, month, day)
    if event_date < today:
        event_date = date(today.year + 1, month, day)
    return (event_date - today).days


class BirthdayReminder(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        settings = bot.settings  # type: ignore[attr-defined]
        self.reminder_channel_id = settings.birthday_reminder_channel_id
        self.commands_channel_id = settings.birthday_commands_channel_id
        self._last_check_date: date | None = None
        self.daily_check.start()

    async def cog_unload(self) -> None:
        self.daily_check.cancel()

    async def cog_check(self, ctx: commands.Context) -> bool:
        """Restrict commands to the commands channel only."""
        return ctx.channel.id == self.commands_channel_id

    @tasks.loop(time=REMINDER_TIME)
    async def daily_check(self) -> None:
        today = datetime.now(EASTERN).date()
        if self._last_check_date == today:
            log.warning("Birthday check already ran today, skipping duplicate")
            return

        channel = self.bot.get_channel(self.reminder_channel_id)
        if channel is None:
            log.error("Birthday reminder channel %s not found", self.reminder_channel_id)
            return

        data = _load_data()
        await self._check_birthdays(channel, data["birthdays"], today)
        await self._check_anniversaries(channel, data["anniversaries"], today)
        self._last_check_date = today

    async def _check_birthdays(
        self, channel: discord.TextChannel, birthdays: list[BirthdayEntry], today: date
    ) -> None:
        for entry in birthdays:
            month, day = _parse_date(entry["date"])
            days = _days_until(month, day, today)

            if days == 0:
                log.info("Sending birthday reminder for %s (today)", entry["name"])
                embed = build_birthday_embed(entry["name"], 0)
                await channel.send(embed=embed)
            elif days == 5:
                log.info("Sending birthday reminder for %s (5 days)", entry["name"])
                embed = build_birthday_embed(entry["name"], 5)
                await channel.send(embed=embed)

    async def _check_anniversaries(
        self,
        channel: discord.TextChannel,
        anniversaries: list[AnniversaryEntry],
        today: date,
    ) -> None:
        for entry in anniversaries:
            month, day = _parse_date(entry["date"])
            days = _days_until(month, day, today)

            if days == 0:
                log.info("Sending anniversary reminder for %s (today)", entry["name"])
                embed = build_anniversary_embed(entry["name"], 0)
                await channel.send(embed=embed)
            elif days == 5:
                log.info("Sending anniversary reminder for %s (5 days)", entry["name"])
                embed = build_anniversary_embed(entry["name"], 5)
                await channel.send(embed=embed)

    @daily_check.before_loop
    async def before_daily_check(self) -> None:
        await self.bot.wait_until_ready()

    @commands.group(name="birthday", invoke_without_command=True)
    async def birthday(self, ctx: commands.Context) -> None:
        """Birthday reminder commands. Use !birthday list, add, or remove."""
        await ctx.send_help(ctx.command)

    @birthday.command(name="add")
    async def birthday_add(
        self, ctx: commands.Context, name: str, date_str: str, year: int | None = None
    ) -> None:
        """Add a birthday. Usage: !birthday add <name> <MM-DD> [year]"""
        try:
            month, day = _parse_date(date_str)
            date(2000, month, day)  # Validate date
        except (ValueError, IndexError):
            await ctx.send("Invalid date format. Use MM-DD (e.g., 03-15)")
            return

        data = _load_data()
        for entry in data["birthdays"]:
            if entry["name"].lower() == name.lower():
                await ctx.send(f"Birthday for '{name}' already exists.")
                return

        entry: BirthdayEntry = {"name": name, "date": date_str, "year": year}
        data["birthdays"].append(entry)
        _save_data(data)

        formatted = _format_date(month, day)
        year_str = f" ({year})" if year else ""
        await ctx.send(f"Added birthday: {name} on {formatted}{year_str}")

    @birthday.command(name="remove")
    async def birthday_remove(self, ctx: commands.Context, name: str) -> None:
        """Remove a birthday. Usage: !birthday remove <name>"""
        data = _load_data()
        original_len = len(data["birthdays"])
        data["birthdays"] = [
            b for b in data["birthdays"] if b["name"].lower() != name.lower()
        ]

        if len(data["birthdays"]) == original_len:
            await ctx.send(f"No birthday found for '{name}'")
            return

        _save_data(data)
        await ctx.send(f"Removed birthday for '{name}'")

    @birthday.command(name="list")
    async def birthday_list(self, ctx: commands.Context) -> None:
        """List all birthdays."""
        data = _load_data()
        if not data["birthdays"]:
            await ctx.send("No birthdays saved.")
            return

        lines = []
        today = datetime.now(EASTERN).date()
        for entry in sorted(data["birthdays"], key=lambda x: x["date"]):
            month, day = _parse_date(entry["date"])
            formatted = _format_date(month, day)
            year_str = f" ({entry['year']})" if entry.get("year") else ""
            days = _days_until(month, day, today)
            lines.append(f"- {entry['name']}: {formatted}{year_str} (in {days} days)")

        await ctx.send("**Birthdays:**\n" + "\n".join(lines))

    @commands.group(name="anniversary", invoke_without_command=True)
    async def anniversary(self, ctx: commands.Context) -> None:
        """Anniversary reminder commands. Use !anniversary list, add, or remove."""
        await ctx.send_help(ctx.command)

    @anniversary.command(name="add")
    async def anniversary_add(
        self, ctx: commands.Context, name: str, date_str: str, year: int | None = None
    ) -> None:
        """Add an anniversary. Usage: !anniversary add <name> <MM-DD> [year]"""
        try:
            month, day = _parse_date(date_str)
            date(2000, month, day)  # Validate date
        except (ValueError, IndexError):
            await ctx.send("Invalid date format. Use MM-DD (e.g., 09-10)")
            return

        data = _load_data()
        for entry in data["anniversaries"]:
            if entry["name"].lower() == name.lower():
                await ctx.send(f"Anniversary for '{name}' already exists.")
                return

        entry: AnniversaryEntry = {"name": name, "date": date_str, "year": year}
        data["anniversaries"].append(entry)
        _save_data(data)

        formatted = _format_date(month, day)
        year_str = f" ({year})" if year else ""
        await ctx.send(f"Added anniversary: {name} on {formatted}{year_str}")

    @anniversary.command(name="remove")
    async def anniversary_remove(self, ctx: commands.Context, name: str) -> None:
        """Remove an anniversary. Usage: !anniversary remove <name>"""
        data = _load_data()
        original_len = len(data["anniversaries"])
        data["anniversaries"] = [
            a for a in data["anniversaries"] if a["name"].lower() != name.lower()
        ]

        if len(data["anniversaries"]) == original_len:
            await ctx.send(f"No anniversary found for '{name}'")
            return

        _save_data(data)
        await ctx.send(f"Removed anniversary for '{name}'")

    @anniversary.command(name="list")
    async def anniversary_list(self, ctx: commands.Context) -> None:
        """List all anniversaries."""
        data = _load_data()
        if not data["anniversaries"]:
            await ctx.send("No anniversaries saved.")
            return

        lines = []
        today = datetime.now(EASTERN).date()
        for entry in sorted(data["anniversaries"], key=lambda x: x["date"]):
            month, day = _parse_date(entry["date"])
            formatted = _format_date(month, day)
            year_str = f" ({entry['year']})" if entry.get("year") else ""
            days = _days_until(month, day, today)
            lines.append(f"- {entry['name']}: {formatted}{year_str} (in {days} days)")

        await ctx.send("**Anniversaries:**\n" + "\n".join(lines))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BirthdayReminder(bot))
