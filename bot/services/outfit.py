from __future__ import annotations

from bot.services.weather import DailyWeather


def recommend_outfit(weather: DailyWeather) -> str:
    parts: list[str] = []
    high = weather.high_f
    precip = weather.precip_chance

    # Base layer
    if high >= 85:
        parts.append("Light, breathable clothes (shorts + t-shirt)")
    elif high >= 70:
        parts.append("Comfortable clothes (jeans or shorts + light shirt)")
    elif high >= 55:
        parts.append("Long pants + long-sleeve shirt or light sweater")
    elif high >= 40:
        parts.append("Warm layers: sweater or fleece + jacket")
    else:
        parts.append("Bundle up! Heavy coat, warm layers, hat, and gloves")

    # Rain gear
    if precip >= 60:
        parts.append("Bring an umbrella and rain jacket - rain is likely!")
    elif precip >= 30:
        parts.append("Consider packing an umbrella just in case")

    # Footwear
    if precip >= 50:
        parts.append("Waterproof shoes or boots recommended")
    elif high >= 75:
        parts.append("Sneakers or sandals work great")
    else:
        parts.append("Closed-toe shoes are a good call")

    return "\n".join(f"• {p}" for p in parts)
