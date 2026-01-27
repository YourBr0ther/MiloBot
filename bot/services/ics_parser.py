from __future__ import annotations

import logging
from datetime import datetime

from icalendar import Calendar

log = logging.getLogger("milo.ics_parser")


def parse_ics(data: bytes) -> dict | None:
    """Parse .ics bytes and return event details dict, or None on failure."""
    try:
        cal = Calendar.from_ical(data)
    except Exception:
        log.exception("Failed to parse .ics data")
        return None

    for component in cal.walk():
        if component.name != "VEVENT":
            continue

        dtstart = component.get("dtstart")
        dtend = component.get("dtend")

        if dtstart is None:
            continue

        start_dt = dtstart.dt
        end_dt = dtend.dt if dtend else None

        is_date = not isinstance(start_dt, datetime)

        result: dict = {
            "title": str(component.get("summary", "Untitled Event")),
            "start_date": start_dt.strftime("%Y-%m-%d") if is_date else start_dt.strftime("%Y-%m-%d"),
            "start_time": None if is_date else start_dt.strftime("%H:%M"),
            "end_date": end_dt.strftime("%Y-%m-%d") if end_dt else None,
            "end_time": None if (end_dt is None or is_date) else end_dt.strftime("%H:%M"),
            "location": str(component.get("location")) if component.get("location") else None,
            "description": str(component.get("description")) if component.get("description") else None,
        }
        return result

    log.warning("No VEVENT found in .ics data")
    return None
