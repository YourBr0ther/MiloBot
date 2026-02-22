from __future__ import annotations

import zoneinfo
from datetime import datetime, timezone

import discord

from bot.services.weather import DailyWeather

OWM_ICON_URL = "https://openweathermap.org/img/wn/{code}@2x.png"


def build_briefing_embed(
    *,
    weather: DailyWeather | None = None,
    outfit: str | None = None,
    quote: str | None = None,
    breakfast: str | None = None,
    lunch: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(
        title="Good Morning! Here's Your Daily Briefing",
        color=discord.Color.gold(),
        timestamp=datetime.now(timezone.utc),
    )

    if weather:
        embed.set_thumbnail(url=OWM_ICON_URL.format(code=weather.icon))

        weather_text = (
            f"**{weather.description.title()}** in {weather.city}\n"
            f"High: **{weather.high_f}°F** · Low: **{weather.low_f}°F**\n"
            f"Precipitation chance: **{weather.precip_chance:.0f}%**"
        )
        embed.add_field(name="Weather", value=weather_text, inline=False)

        if weather.hourly:
            hourly_lines = [
                f"`{h.time:>5}` {h.temp_f}°F — {h.description}"
                for h in weather.hourly[:6]
            ]
            embed.add_field(
                name="Hourly Forecast",
                value="\n".join(hourly_lines),
                inline=False,
            )
    else:
        embed.add_field(
            name="Weather",
            value="Could not fetch weather data today.",
            inline=False,
        )

    if outfit:
        embed.add_field(name="Outfit Recommendation", value=outfit, inline=False)

    if breakfast or lunch:
        meal_lines = []
        if breakfast:
            meal_lines.append(f"**Breakfast:** {breakfast}")
        if lunch:
            meal_lines.append(f"**Lunch:** {lunch}")
        embed.add_field(name="School Menu", value="\n".join(meal_lines), inline=False)

    if quote:
        embed.add_field(name="Quote of the Day", value=f"*{quote}*", inline=False)

    embed.set_footer(text="Have a great day!")
    return embed


def build_birthday_embed(name: str, days_until: int) -> discord.Embed:
    """Build an embed for birthday reminders."""
    if days_until == 0:
        title = f"Happy Birthday, {name}!"
        description = f"Today is {name}'s birthday!"
    else:
        date_text = _get_upcoming_date_text(days_until)
        title = "Birthday Reminder"
        description = f"Heads up! {name}'s birthday is in {days_until} days ({date_text})"

    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.magenta(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="Birthday Reminder")
    return embed


def build_anniversary_embed(name: str, days_until: int) -> discord.Embed:
    """Build an embed for anniversary reminders."""
    if days_until == 0:
        title = "Happy Anniversary!"
        description = f"Today is the {name} anniversary!"
    else:
        date_text = _get_upcoming_date_text(days_until)
        title = "Anniversary Reminder"
        description = f"Heads up! The {name} anniversary is in {days_until} days ({date_text})"

    embed = discord.Embed(
        title=title,
        description=description,
        color=discord.Color.red(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text="Anniversary Reminder")
    return embed


def _get_upcoming_date_text(days_until: int) -> str:
    """Get a formatted date string for an upcoming date."""
    from datetime import timedelta

    eastern = zoneinfo.ZoneInfo("America/New_York")
    target_date = datetime.now(eastern).date() + timedelta(days=days_until)
    return target_date.strftime("%B %-d")
