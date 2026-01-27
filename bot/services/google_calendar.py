from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

import aiohttp
import google.auth.transport.requests
from google.oauth2 import service_account

log = logging.getLogger("milo.google_calendar")

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
CALENDAR_API = "https://www.googleapis.com/calendar/v3"


class GoogleCalendarService:
    def __init__(self, service_account_path: str, calendar_id: str) -> None:
        self._calendar_id = calendar_id
        self._creds = service_account.Credentials.from_service_account_file(
            service_account_path, scopes=SCOPES
        )

    async def _get_headers(self) -> dict[str, str]:
        """Refresh credentials and return authorization headers."""
        if not self._creds.valid:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, self._creds.refresh, google.auth.transport.requests.Request()
            )
        return {
            "Authorization": f"Bearer {self._creds.token}",
            "Content-Type": "application/json",
        }

    async def create_event(
        self,
        session: aiohttp.ClientSession,
        *,
        title: str,
        start_date: str,
        start_time: str | None = None,
        end_date: str | None = None,
        end_time: str | None = None,
        location: str | None = None,
        description: str | None = None,
    ) -> dict:
        """Create a Google Calendar event. Returns the created event resource."""
        headers = await self._get_headers()
        url = f"{CALENDAR_API}/calendars/{self._calendar_id}/events"

        body: dict = {"summary": title}

        if location:
            body["location"] = location
        if description:
            body["description"] = description

        tz = "America/New_York"

        if start_time:
            start_dt = f"{start_date}T{start_time}:00"
            body["start"] = {"dateTime": start_dt, "timeZone": tz}

            if end_date and end_time:
                end_dt = f"{end_date}T{end_time}:00"
            elif end_time:
                end_dt = f"{start_date}T{end_time}:00"
            else:
                # Default 1-hour duration
                dt = datetime.strptime(start_dt, "%Y-%m-%dT%H:%M:%S")
                end_dt = (dt + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
            body["end"] = {"dateTime": end_dt, "timeZone": tz}
        else:
            # All-day event
            body["start"] = {"date": start_date}
            end = end_date or start_date
            body["end"] = {"date": end}

        async with session.post(url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if not resp.ok:
                text = await resp.text()
                log.error("Calendar create failed (%s): %s", resp.status, text)
                resp.raise_for_status()
            data = await resp.json()
            log.info("Created calendar event: %s", data.get("htmlLink"))
            return data
