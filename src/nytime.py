"""America/New_York time helpers.

The app is hosted on Render (UTC) but the workers operate in the US
Eastern timezone. Every user-visible "now" / "today" — punch timestamps,
pay-period boundaries, OCR date defaults, agent "current time" — must use
these helpers instead of naive datetime.now() / date.today().
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


def ny_now() -> datetime:
    """Current time in America/New_York (timezone-aware)."""
    return datetime.now(NY)


def ny_today() -> date:
    """Current date in America/New_York."""
    return ny_now().date()
