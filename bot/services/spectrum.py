from __future__ import annotations

import logging

import aiohttp

log = logging.getLogger("milo.spectrum")

SPECTRUM_API = "https://robertsspaceindustries.com/api/spectrum"
SPECTRUM_BASE = "https://robertsspaceindustries.com/spectrum/community/SC/forum"


class SpectrumService:
    """Client for the (unofficial) RSI Spectrum forum API."""

    async def get_threads(
        self, session: aiohttp.ClientSession, channel_id: str, page: int = 1,
    ) -> list[dict]:
        """Return a list of threads for a forum channel, newest first."""
        url = f"{SPECTRUM_API}/forum/channel/threads"
        payload = {"channel_id": channel_id, "page": page, "sort": "time-created"}
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()
            data = await resp.json()
        if not data.get("success"):
            log.warning("Spectrum thread list failed: %s", data.get("msg"))
            return []
        return data.get("data", {}).get("threads", [])

    async def get_thread_content(
        self, session: aiohttp.ClientSession, thread_id: str, slug: str,
    ) -> str:
        """Fetch a thread's first post and convert Draft.js blocks to plain text."""
        url = f"{SPECTRUM_API}/forum/thread/nested"
        payload = {"thread_id": thread_id, "page": 1, "slug": slug}
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()
            data = await resp.json()
        if not data.get("success"):
            log.warning("Spectrum thread content failed: %s", data.get("msg"))
            return ""
        content_blocks = data.get("data", {}).get("content_blocks", [])
        if not content_blocks:
            return ""
        blocks = content_blocks[0].get("data", {}).get("blocks", [])
        return self._blocks_to_text(blocks)

    @staticmethod
    def thread_url(channel_id: str, slug: str) -> str:
        return f"{SPECTRUM_BASE}/{channel_id}/thread/{slug}"

    @staticmethod
    def _blocks_to_text(blocks: list[dict]) -> str:
        lines: list[str] = []
        for b in blocks:
            text = b.get("text", "")
            btype = b.get("type", "unstyled")
            depth = b.get("depth", 0)
            if btype == "header-one":
                lines.append(f"# {text}")
            elif btype == "header-two":
                lines.append(f"## {text}")
            elif btype == "header-three":
                lines.append(f"### {text}")
            elif btype == "unordered-list-item":
                lines.append(f"{'  ' * depth}- {text}")
            elif btype == "ordered-list-item":
                lines.append(f"{'  ' * depth}1. {text}")
            elif btype == "blockquote":
                lines.append(f"> {text}")
            else:
                lines.append(text)
        return "\n".join(lines)
