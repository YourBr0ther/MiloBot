from __future__ import annotations

import logging
import random

import aiohttp

log = logging.getLogger("milo.nanogpt")

NANOGPT_URL = "https://nano-gpt.com/api/v1/chat/completions"

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
