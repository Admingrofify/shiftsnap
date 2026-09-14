"""ShiftSnap agent tools (Strands @tool functions).

Tools share one store instance, created by make_tools(). The backend is
chosen by get_store(): Supabase Postgres when SUPABASE_URL/SUPABASE_KEY are
set, otherwise the local JSON ShiftStore (demo mode).
"""
from __future__ import annotations

import datetime
import os

from strands import tool

from .backend import get_store
from .ocr import find_all_timestamps, parse_photo_timestamp
from .store import ShiftStore, fmt_duration, net_minutes
from .timesheet import generate_timesheet as _generate_timesheet
from .nytime import ny_now


def make_tools(store=None, worker_id: str | None = None):
    store = store or get_store(worker_id)
    is_sb = type(store).__name__ == "SupabaseShiftStore"

    _SB_ONLY = {"employee_id", "lat", "lng", "accuracy", "source"}

    def _call(fn, *args, **kwargs):
        # Supabase store methods take employee_id/lat/lng/source;
        # the JSON demo store doesn't — strip those for it.
        if is_sb:
            if worker_id:
                kwargs.setdefault("employee_id", worker_id)
        else:
            for k in _SB_ONLY:
                kwargs.pop(k, None)
        return fn(*args, **kwargs)

    @tool
    def log_shift(date: str, time_in: str, time_out: str,
                  break_start: str = "", break_end: str = "",
                  comment: str = "") -> str:
        """Log one work shift.

        Args:
            date: Work date, e.g. '2026-09-01', 'Sep 1', 'today'.
            time_in: Clock-in time, e.g. '6:58 AM' or '18:58'.
            time_out: Clock-out time, e.g. '10:26 PM' or '22:26'.
            break_start: Unpaid break start, e.g. '2:58 AM' (optional).
            break_end: Unpaid break end, e.g. '10:26 AM' (optional).
            comment: Optional note for the timesheet row.
        Returns:
            Confirmation with the computed net hours for the shift.
        """
        try:
            rec = _call(store.log_shift, date, time_in, time_out,
                        break_start or None, break_end or None, comment)
        except ValueError as exc:
            return f"Could not log shift: {exc}"
        brk = f" (break {rec['break_start']}-{rec['break_end']})" if rec.get("break_start") else ""
        return (f"Logged {rec['date']}: {rec['time_in']} -> {rec['time_out']}{brk}. "
                f"Net hours: {rec['net']}.")

    @tool
    def list_shifts(start_date: str = "", end_date: str = "") -> str:
        """List logged shifts, optionally within a date range.

        Args:
            start_date: Range start, e.g. '2026-09-01' (optional).
            end_date: Range end, e.g. '2026-09-15' (optional).
        Returns:
            Human-readable list of shifts with net hours per day.
        """
        try:
            data = _call(store.list_shifts, start_date or None, end_date or None)
        except ValueError as exc:
            return f"Could not list shifts: {exc}"
        if not data:
            return "No shifts logged in that range."
        lines = []
        for date, shifts in data.items():
            for s in shifts:
                brk = f", break {s['break_start']}-{s['break_end']}" if s.get("break_start") else ""
                lines.append(f"{date}: {s['time_in']}->{s['time_out']}{brk} = {fmt_duration(net_minutes(s))}")
        return "\n".join(lines)

    @tool
    def pay_period_summary(start_date: str, end_date: str) -> str:
        """Summarize a pay period: days worked, total/approved/extra hours.

        Args:
            start_date: Period start, e.g. '2026-09-01'.
            end_date: Period end, e.g. '2026-09-15'.
        Returns:
            Summary with total hours, approved hours (8h/day cap) and extra hours.
        """
        try:
            s = _call(store.summary, start_date, end_date)
        except ValueError as exc:
            return f"Could not summarize: {exc}"
        missing = _call(store.missing_days, start_date, end_date)
        out = (f"Pay period {s['start']} to {s['end']}: {s['days_worked']} day(s) worked, "
               f"total {s['total_hours']} ({s['total_decimal']}h), "
               f"approved {s['approved_hours']}, extra {s['extra_hours']}.")
        if s.get("open_shifts"):
            out += f" {s['open_shifts']} shift(s) still clocked in (no clock-out yet)."
        if missing:
            out += f" Missing (weekday) entries: {', '.join(missing[:5])}."
        return out

    @tool
    def generate_timesheet(start_date: str, end_date: str) -> str:
        """Generate the filled Excel timesheet for a pay period.

        Args:
            start_date: Period start, e.g. '2026-09-01'.
            end_date: Period end, e.g. '2026-09-15'.
        Returns:
            Path to the generated .xlsx file.
        """
        try:
            path = _generate_timesheet(start_date, end_date, store)
        except ValueError as exc:
            return f"Could not generate timesheet: {exc}"
        s = _call(store.summary, start_date, end_date)
        return (f"Timesheet saved to {path}. "
                f"Covers {s['days_worked']} day(s), {s['total_hours']} total "
                f"({s['approved_hours']} approved, {s['extra_hours']} extra).")

    @tool
    def punch_clock(timestamp: str, lat: str = "", lng: str = "",
                    accuracy: str = "", source: str = "chat") -> str:
        """Clock in or out from a timestamp (photo OCR text or button tap).

        Args:
            timestamp: Raw text containing a timestamp, e.g.
                'Sep 14, 2026 at 6:09:04 AM' (as read from a photo).
            lat: GPS latitude of the punch (optional).
            lng: GPS longitude of the punch (optional).
            accuracy: GPS accuracy in meters (optional).
            source: 'button', 'photo', or 'chat'.
        Returns:
            Confirmation of clock-in, or clock-out with the completed
            shift's net hours.
        """
        parsed = parse_photo_timestamp(timestamp)
        if not parsed:
            return (f"Could not find a readable timestamp in: {timestamp!r}. "
                    "Try a clearer photo of the timestamp overlay.")
        try:
            rec = _call(store.punch, parsed["date"], parsed["time"],
                        comment=f"{source} snap {parsed['raw']}".strip(),
                        lat=float(lat) if lat else None,
                        lng=float(lng) if lng else None,
                        accuracy=float(accuracy) if accuracy else None,
                        source=source)
        except (ValueError, TypeError) as exc:
            return f"Could not log punch: {exc}"
        if rec["action"] == "in":
            return (f"Clocked in {rec['date']} at {rec['time_in']} "
                    f"(from {source}: {parsed['raw']}).")
        return (f"Clocked out {rec['date']} at {rec['time_out']} "
                f"(from {source}: {parsed['raw']}). Shift {rec['time_in']} -> "
                f"{rec['time_out']}, net {rec['net']}.")

    @tool
    def clock_now(lat: str = "", lng: str = "",
                  accuracy: str = "") -> str:
        """Clock in/out right now using the current time (Clock In/Out buttons).

        Args:
            lat: GPS latitude captured by the browser (optional).
            lng: GPS longitude captured by the browser (optional).
            accuracy: GPS accuracy in meters (optional).
        Returns:
            Confirmation of clock-in or clock-out with net hours.
        """
        now = ny_now()
        h12 = now.hour % 12 or 12
        stamp = now.strftime("%b %d, %Y at ") + f"{h12}:{now:%M} {now:%p}"
        return punch_clock(timestamp=stamp, lat=lat, lng=lng,
                           accuracy=accuracy, source="button")

    @tool
    def import_timesheet_photo(ocr_text: str) -> str:
        """Extract every timestamp from a weekly timesheet photo's OCR text.

        Args:
            ocr_text: Raw OCR text read from the photo.
        Returns:
            Numbered list of timestamps found, for the worker to review
            before they are logged as punches.
        """
        found = find_all_timestamps(ocr_text)
        if not found:
            return ("No readable timestamps found in that photo. Make sure the "
                    "time overlays are clear and try again.")
        lines = [f"{i + 1}. {p['date']} {p['time']}  (read: {p['raw']})"
                 for i, p in enumerate(found)]
        return ("Found these timestamps — confirm which to log as punches:\n"
                + "\n".join(lines))

    return [log_shift, list_shifts, pay_period_summary, generate_timesheet,
            punch_clock, clock_now, import_timesheet_photo]
