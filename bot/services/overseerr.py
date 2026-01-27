from __future__ import annotations

import logging

import aiohttp

log = logging.getLogger("milo.overseerr")


class OverseerrService:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/") + "/api/v1"
        self._headers = {"X-Api-Key": api_key}

    async def search(self, session: aiohttp.ClientSession, query: str) -> list[dict]:
        """Search Overseerr for movies and TV shows."""
        url = f"{self._base_url}/search"
        params = {"query": query, "page": "1"}
        async with session.get(url, headers=self._headers, params=params,
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()
            data = await resp.json()
        return data.get("results", [])

    async def request_media(self, session: aiohttp.ClientSession, media_type: str, tmdb_id: int) -> dict:
        """Submit a media request to Overseerr."""
        url = f"{self._base_url}/request"
        payload = {"mediaType": media_type, "mediaId": tmdb_id}
        async with session.post(url, headers=self._headers, json=payload,
                                timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_request_status(self, session: aiohttp.ClientSession, request_id: int) -> dict:
        """Get the status of a specific request."""
        url = f"{self._base_url}/request/{request_id}"
        async with session.get(url, headers=self._headers,
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_media(self, session: aiohttp.ClientSession, media_id: int) -> dict:
        """Get media info including Plex rating key."""
        url = f"{self._base_url}/media/{media_id}"
        async with session.get(url, headers=self._headers,
                               timeout=aiohttp.ClientTimeout(total=15)) as resp:
            resp.raise_for_status()
            return await resp.json()
