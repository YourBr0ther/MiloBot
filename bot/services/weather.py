from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import aiohttp

log = logging.getLogger("milo.weather")

GEO_URL = "https://api.openweathermap.org/geo/1.0/zip"
FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"


@dataclass
class HourlyForecast:
    time: str  # e.g. "9 AM"
    temp_f: float
    description: str
    icon: str


@dataclass
class DailyWeather:
    city: str
    high_f: float
    low_f: float
    description: str
    icon: str
    precip_chance: float  # 0-100
    hourly: list[HourlyForecast]


class WeatherService:
    def __init__(self, api_key: str, zip_code: str) -> None:
        self._api_key = api_key
        self._zip_code = zip_code
        self._lat: float | None = None
        self._lon: float | None = None

    async def _geocode(self, session: aiohttp.ClientSession) -> tuple[float, float]:
        if self._lat is not None and self._lon is not None:
            return self._lat, self._lon

        params = {"zip": f"{self._zip_code},US", "appid": self._api_key}
        async with session.get(GEO_URL, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()
            self._lat = data["lat"]
            self._lon = data["lon"]
            log.debug("Geocoded %s -> (%s, %s)", self._zip_code, self._lat, self._lon)
            return self._lat, self._lon

    async def get_today(self, session: aiohttp.ClientSession) -> DailyWeather:
        lat, lon = await self._geocode(session)
        params = {
            "lat": lat,
            "lon": lon,
            "appid": self._api_key,
            "units": "imperial",
        }
        async with session.get(FORECAST_URL, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()

        city = data["city"]["name"]
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        temps: list[float] = []
        precip_chances: list[float] = []
        descriptions: list[str] = []
        icons: list[str] = []
        hourly: list[HourlyForecast] = []

        for entry in data["list"]:
            dt_txt: str = entry["dt_txt"]
            if not dt_txt.startswith(today_str):
                continue

            temp = entry["main"]["temp"]
            temps.append(temp)
            pop = entry.get("pop", 0) * 100
            precip_chances.append(pop)
            desc = entry["weather"][0]["description"]
            icon = entry["weather"][0]["icon"]
            descriptions.append(desc)
            icons.append(icon)

            dt = datetime.fromisoformat(dt_txt)
            hourly.append(HourlyForecast(
                time=dt.strftime("%-I %p"),
                temp_f=round(temp, 1),
                description=desc,
                icon=icon,
            ))

        if not temps:
            raise ValueError("No forecast data available for today")

        return DailyWeather(
            city=city,
            high_f=round(max(temps), 1),
            low_f=round(min(temps), 1),
            description=descriptions[0],
            icon=icons[0],
            precip_chance=round(max(precip_chances)),
            hourly=hourly,
        )
