from __future__ import annotations

import logging

import aiohttp

log = logging.getLogger("milo.tavily")

TAVILY_URL = "https://api.tavily.com/search"


class TavilyService:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def search(self, query: str, session: aiohttp.ClientSession) -> str | None:
        """Search the web and return a formatted context string, or None on failure."""
        try:
            payload = {
                "api_key": self._api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": 5,
                "include_answer": True,
            }
            async with session.post(TAVILY_URL, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                resp.raise_for_status()
                data = await resp.json()

            parts: list[str] = []

            # Tavily's built-in AI answer
            if data.get("answer"):
                parts.append(f"Summary: {data['answer']}")

            # Individual source results
            for result in data.get("results", [])[:5]:
                title = result.get("title", "")
                content = result.get("content", "")
                url = result.get("url", "")
                parts.append(f"- {title}: {content} ({url})")

            if not parts:
                return None

            return "\n".join(parts)
        except Exception:
            log.exception("Tavily search failed")
            return None
