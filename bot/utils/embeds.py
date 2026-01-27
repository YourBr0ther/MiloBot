from __future__ import annotations

from datetime import datetime, timezone

import discord

from bot.services.weather import DailyWeather

OWM_ICON_URL = "https://openweathermap.org/img/wn/{code}@2x.png"


def build_briefing_embed(
    *,
    weather: DailyWeather | None = None,
    outfit: str | None = None,
    quote: str | None = None,
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

    if quote:
        embed.add_field(name="Quote of the Day", value=f"*{quote}*", inline=False)

    embed.set_footer(text="Have a great day!")
    return embed
