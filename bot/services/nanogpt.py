from __future__ import annotations

import json
import logging
import random
from datetime import datetime

import aiohttp
from zoneinfo import ZoneInfo

log = logging.getLogger("milo.nanogpt")

NANOGPT_URL = "https://nano-gpt.com/api/v1/chat/completions"
NANOGPT_IMAGE_URL = "https://nano-gpt.com/v1/images/generations"
NANOGPT_BALANCE_URL = "https://nano-gpt.com/api/check-balance"

EVENT_EXTRACTION_PROMPT = """\
Current date/time: {now}

Extract event details. Return ONLY valid JSON:
{{
  "title": "event name",
  "start_date": "YYYY-MM-DD",
  "start_time": "HH:MM (24h) or null",
  "end_date": "YYYY-MM-DD or null",
  "end_time": "HH:MM (24h) or null",
  "location": "string or null",
  "description": "string or null"
}}

Rules:
- Resolve relative dates ("Saturday", "next Friday") to actual dates
- If year missing, assume current or next occurrence
- If no end time, set null
- Return ONLY JSON"""

COLORING_BOOK_PREFIX = (
    "Black and white line drawing, coloring book page. "
    "Clean clear lines with no shading or gradients. "
    "Entirely white background with no additional elements or textures. "
    "Simple illustration in the style of a blank coloring book with open space "
    "between the lines, without shading, leaving room for hand coloring. "
    "Subject: "
)
COLORING_BOOK_SUFFIX = ""

FALLBACK_QUOTES = [
    "Every morning is a fresh start. Make it count!",
    "The secret to getting ahead is getting started. - Mark Twain",
    "Today is a good day to have a good day.",
    "Be yourself; everyone else is already taken. - Oscar Wilde",
    "You're never fully dressed without a smile.",
    "Life is short. Smile while you still have teeth.",
    "The early bird gets the worm, but the second mouse gets the cheese.",
    "Coffee first. Schemes later.",
]

PROMPT = (
    "Generate a single short quote (1-2 sentences) that is either funny, "
    "inspiring, or a mix of both. Perfect for starting someone's morning. "
    "Do not include attribution or quotation marks. Just the quote text."
)


class NanoGPTService:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def check_balance(self, session: aiohttp.ClientSession) -> dict:
        """Return account balance info from NanoGPT."""
        headers = {"x-api-key": self._api_key}
        async with session.post(
            NANOGPT_BALANCE_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def generate_coloring_page(
        self, session: aiohttp.ClientSession, subject: str, seed: int | None = None
    ) -> str:
        """Generate a coloring book image. Returns the image URL."""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict = {
            "model": "nano-banana",
            "prompt": COLORING_BOOK_PREFIX + subject + COLORING_BOOK_SUFFIX,
            "n": 1,
            "size": "1024x1024",
            "response_format": "url",
        }
        if seed is not None:
            payload["seed"] = seed

        async with session.post(NANOGPT_IMAGE_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            if not resp.ok:
                body = await resp.text()
                log.error("Image generation failed (%s): %s", resp.status, body)
                resp.raise_for_status()
            data = await resp.json()
            return data["data"][0]["url"]

    async def ask(self, session: aiohttp.ClientSession, question: str, search_context: str | None = None) -> str:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        system_content = (
            "You are Milo, a friendly and helpful family assistant bot. "
            "Keep answers concise and family-friendly. "
            "If you don't know something, say so honestly."
        )
        if search_context:
            system_content += (
                "\n\nUse the following web search results to inform your answer. "
                "Cite sources when relevant.\n\n"
                f"{search_context}"
            )
        payload = {
            "model": "chatgpt-4o-latest",
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": question},
            ],
        }
        async with session.post(NANOGPT_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data["choices"][0]["message"]["content"].strip()

    def _event_prompt(self) -> str:
        now = datetime.now(ZoneInfo("America/New_York")).strftime("%A, %B %d, %Y %I:%M %p %Z")
        return EVENT_EXTRACTION_PROMPT.format(now=now)

    def _parse_event_json(self, text: str) -> dict | None:
        """Extract JSON from a response that may include markdown fences."""
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            log.error("Failed to parse event JSON: %s", text)
            return None

    async def extract_event_from_text(self, session: aiohttp.ClientSession, text: str) -> dict | None:
        """Use AI to extract event details from plain text."""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "chatgpt-4o-latest",
            "messages": [
                {"role": "system", "content": self._event_prompt()},
                {"role": "user", "content": text},
            ],
        }
        async with session.post(NANOGPT_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            resp.raise_for_status()
            data = await resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            return self._parse_event_json(content)

    async def extract_event_from_image(self, session: aiohttp.ClientSession, image_url: str) -> dict | None:
        """Use AI vision to extract event details from an image URL."""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "chatgpt-4o-latest",
            "messages": [
                {"role": "system", "content": self._event_prompt()},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_url}},
                        {"type": "text", "text": "Extract event details from this image."},
                    ],
                },
            ],
        }
        async with session.post(NANOGPT_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            resp.raise_for_status()
            data = await resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            return self._parse_event_json(content)

    async def extract_lunch_menu(
        self, session: aiohttp.ClientSession, page_data_uris: list[str], month_hint: str
    ) -> dict[str, str]:
        """Extract a lunch menu from one or more page images. Returns {YYYY-MM-DD: description}."""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        system_prompt = (
            "You are extracting a school meal menu from a calendar-style image.\n"
            f"Month/year hint (use the date printed on the menu if visible): {month_hint}\n\n"
            "Return ONLY valid JSON mapping each school day to an object with breakfast and lunch:\n"
            '{"YYYY-MM-DD": {"breakfast": "...", "lunch": "..."}, ...}\n\n'
            "Rules:\n"
            "- The FIRST item listed each day is the featured breakfast item\n"
            "- Everything after that is lunch: entree choices, then sides/fruit\n"
            "- Format breakfast as just the item name (e.g. \"Apple Cinnamon Toast\")\n"
            "- Format lunch as: \"Entrees: <choices separated by ' or '>. Sides: <sides separated by ', '>\"\n"
            "- Strip out all parenthetical numbers like (44) or (EM14) — those are allergen codes\n"
            "- Skip the PBJ Sandwich line (it is a daily standing option, not a featured item)\n"
            "- Skip days that are blank or have no menu (weekends, holidays, no-school days)\n"
            "- Use the full date format YYYY-MM-DD\n"
            "- Return ONLY the JSON object, no other text"
        )
        content_parts: list[dict] = []
        for uri in page_data_uris:
            content_parts.append({"type": "image_url", "image_url": {"url": uri}})
        content_parts.append({"type": "text", "text": "Extract the lunch menu from these images."})

        payload = {
            "model": "chatgpt-4o-latest",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content_parts},
            ],
        }
        async with session.post(
            NANOGPT_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=60)
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            result = self._parse_event_json(content)
            if result is None:
                return {}
            return {k: v for k, v in result.items() if isinstance(v, dict)}

    async def enrich_location(self, session: aiohttp.ClientSession, location: str, search_context: str) -> dict | None:
        """Given a location string and web search results, return structured place info."""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "chatgpt-4o-latest",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are given a location reference from a calendar event and web search results about it. "
                        "Return ONLY valid JSON with the enriched location info:\n"
                        '{"name": "business/place name", "address": "full street address, city, state zip", '
                        '"maps_query": "name + address for Google Maps search"}\n'
                        "If the search results don't help identify the place, return null."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Location from event: {location}\n\nSearch results:\n{search_context}",
                },
            ],
        }
        async with session.post(NANOGPT_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()
            data = await resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            return self._parse_event_json(content)

    async def get_quote(self, session: aiohttp.ClientSession) -> str:
        try:
            headers = {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": "chatgpt-4o-latest",
                "messages": [{"role": "user", "content": PROMPT}],
            }
            async with session.post(NANOGPT_URL, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                resp.raise_for_status()
                data = await resp.json()
                quote = data["choices"][0]["message"]["content"].strip().strip('"')
                log.debug("NanoGPT quote: %s", quote)
                return quote
        except Exception:
            log.exception("NanoGPT request failed, using fallback quote")
            return random.choice(FALLBACK_QUOTES)
