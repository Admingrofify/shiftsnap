"""ShiftSnap agent tools (Strands @tool functions).

All tools share one ShiftStore instance, created by make_tools().
"""
from __future__ import annotations

from pathlib import Path

from strands import tool

from .store import ShiftStore, fmt_duration, net_minutes
from .timesheet import generate_timesheet as _generate_timesheet


def make_tools(store: ShiftStore | None = None):
    store = store or ShiftStore()

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
            rec = store.log_shift(date, time_in, time_out,
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
            data = store.list_shifts(start_date or None, end_date or None)
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
            s = store.summary(start_date, end_date)
        except ValueError as exc:
            return f"Could not summarize: {exc}"
        missing = store.missing_days(start_date, end_date)
        out = (f"Pay period {s['start']} to {s['end']}: {s['days_worked']} day(s) worked, "
               f"total {s['total_hours']} ({s['total_decimal']}h), "
               f"approved {s['approved_hours']}, extra {s['extra_hours']}.")
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
        s = store.summary(start_date, end_date)
        return (f"Timesheet saved to {path}. "
                f"Covers {s['days_worked']} day(s), {s['total_hours']} total "
                f"({s['approved_hours']} approved, {s['extra_hours']} extra).")

    return [log_shift, list_shifts, pay_period_summary, generate_timesheet]
