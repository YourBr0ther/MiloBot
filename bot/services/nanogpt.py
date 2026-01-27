from __future__ import annotations

import logging
import random

import aiohttp

log = logging.getLogger("milo.nanogpt")

NANOGPT_URL = "https://nano-gpt.com/api/v1/chat/completions"
NANOGPT_IMAGE_URL = "https://nano-gpt.com/v1/images/generations"

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
