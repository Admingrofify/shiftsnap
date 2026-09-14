"""ShiftSnap shift store: JSON-backed log of work shifts.

A shift is a dict:
    {"time_in": "HH:MM", "time_out": "HH:MM",
     "break_start": "HH:MM|None", "break_end": "HH:MM|None",
     "comment": str}

Stored as {date_str: [shift, ...]} where date_str is "YYYY-MM-DD".
"""
from __future__ import annotations

import datetime
import json
import re
from pathlib import Path

DEFAULT_PATH = Path.home() / ".shiftsnap" / "shifts.json"


def normalize_time(raw: str) -> str:
    """Normalize human time input to 24h 'HH:MM'.

    Accepts: '6:58 AM', '6:58am', '6:58 a.m.', '18:58', '6:58', '9 AM',
    '12' (bare hour -> HH:00), '06:58 PM'...
    """
    s = raw.strip().lower().replace(".", "")
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s?m?\.?$", s)
    if not m:
        m = re.match(r"^(\d{1,2}):(\d{2})$", s)
        if not m:
            m = re.match(r"^(\d{1,2})$", s)
            if not m:
                raise ValueError(f"Could not understand time: {raw!r}")
            h, mi, ap = int(m.group(1)), "00", None
        else:
            h, mi, ap = int(m.group(1)), m.group(2), None
    else:
        h, mi, ap = int(m.group(1)), m.group(2) or "00", m.group(3)
    mi = int(mi)
    if ap == "p" and h != 12:
        h += 12
    if ap == "a" and h == 12:
        h = 0
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        raise ValueError(f"Invalid time: {raw!r}")
    return f"{h:02d}:{mi:02d}"


def normalize_date(raw: str, today: datetime.date | None = None) -> str:
    """Normalize date input to 'YYYY-MM-DD'.

    Accepts 'YYYY-MM-DD', 'MM/DD/YYYY', 'Sep 1', 'Sept 1 2026', 'today', 'yesterday'.
    """
    today = today or datetime.date.today()
    s = raw.strip().lower()
    if s == "today":
        return today.isoformat()
    if s == "yesterday":
        return (today - datetime.timedelta(days=1)).isoformat()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.datetime.strptime(raw.strip(), fmt).date().isoformat()
        except ValueError:
            pass
    m = re.match(r"^([a-z]+)\s+(\d{1,2})(?:\s*,?\s*(\d{4}))?$", s)
    if m:
        month_name, day, year = m.group(1), int(m.group(2)), m.group(3)
        try:
            month = datetime.datetime.strptime(month_name[:3], "%b").month
        except ValueError:
            raise ValueError(f"Could not understand date: {raw!r}")
        year = int(year) if year else today.year
        return datetime.date(year, month, day).isoformat()
    raise ValueError(f"Could not understand date: {raw!r}")


def to_minutes(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def net_minutes(shift: dict) -> int:
    if not shift.get("time_out"):
        return 0  # open shift: clocked in, not yet out
    gross = to_minutes(shift["time_out"]) - to_minutes(shift["time_in"])
    if gross < 0:
        gross += 24 * 60  # overnight shift past midnight
    elif gross == 0:
        return 0  # clocked out in the same minute: no time worked
    if shift.get("break_start") and shift.get("break_end"):
        gross -= to_minutes(shift["break_end"]) - to_minutes(shift["break_start"])
    return gross


def fmt_duration(minutes: int) -> str:
    return f"{minutes // 60}:{minutes % 60:02d}"


class ShiftStore:
    def __init__(self, path: Path | str = DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, list[dict]] = {}
        self.load()

    def load(self):
        if self.path.exists():
            self._data = json.loads(self.path.read_text())
        else:
            self._data = {}

    def save(self):
        self.path.write_text(json.dumps(self._data, indent=2))

    def log_shift(self, date: str, time_in: str, time_out: str,
                  break_start: str | None = None, break_end: str | None = None,
                  comment: str = "") -> dict:
        date = normalize_date(date)
        time_in = normalize_time(time_in)
        time_out = normalize_time(time_out)
        if to_minutes(time_out) <= to_minutes(time_in):
            raise ValueError("time_out must be after time_in")
        if break_start:
            break_start = normalize_time(break_start)
        if break_end:
            break_end = normalize_time(break_end)
        shift = {"time_in": time_in, "time_out": time_out,
                 "break_start": break_start, "break_end": break_end,
                 "comment": comment}
        shifts = self._data.setdefault(date, [])
        for i, s in enumerate(shifts):
            if s["time_in"] == time_in and s["time_out"] == time_out:
                shifts[i] = shift
                break
        else:
            shifts.append(shift)
        shifts.sort(key=lambda s: s["time_in"])
        self.save()
        shift = dict(shift)
        shift["net"] = fmt_duration(net_minutes(shift))
        return {"date": date, **shift}

    def punch(self, date: str, time: str, comment: str = "") -> dict:
        """Clock in or out from a timestamp (e.g. a photo snap).

        If there is an open shift (clocked in, no clock-out yet) on `date`
        — or on the previous day for overnight shifts — this punch closes it.
        Otherwise it opens a new shift with `time` as clock-in.
        Returns {"action": "in"|"out", "date": ..., "time_in": ..., ...}.
        """
        date = normalize_date(date)
        time = normalize_time(time)
        day = datetime.date.fromisoformat(date)

        # find an open shift: same day first, then previous day (overnight)
        open_ref = None
        for cand in (date, (day - datetime.timedelta(days=1)).isoformat()):
            for i, s in enumerate(self._data.get(cand, [])):
                if not s.get("time_out"):
                    open_ref = (cand, i)
                    break
            if open_ref:
                break

        if open_ref:
            cand, i = open_ref
            s = self._data[cand][i]
            s["time_out"] = time
            if comment and comment not in s.get("comment", ""):
                s["comment"] = (s.get("comment", "") + " " + comment).strip()
            self._data[cand].sort(key=lambda x: x["time_in"])
            self.save()
            return {"action": "out", "date": cand,
                    "time_in": s["time_in"], "time_out": time,
                    "net": fmt_duration(net_minutes(s))}

        shift = {"time_in": time, "time_out": None,
                 "break_start": None, "break_end": None, "comment": comment}
        shifts = self._data.setdefault(date, [])
        shifts.append(shift)
        shifts.sort(key=lambda s: s["time_in"])
        self.save()
        return {"action": "in", "date": date, "time_in": time,
                "time_out": None, "net": "0:00"}

    def open_shifts(self) -> list[dict]:
        """All shifts that are clocked in but not yet out."""
        out = []
        for date, shifts in self._data.items():
            for s in shifts:
                if not s.get("time_out"):
                    out.append({"date": date, **s})
        return sorted(out, key=lambda r: (r["date"], r["time_in"]))

    def list_shifts(self, start: str | None = None, end: str | None = None) -> dict[str, list[dict]]:
        data = self._data
        if start:
            start = normalize_date(start)
            data = {d: s for d, s in data.items() if d >= start}
        if end:
            end = normalize_date(end)
            data = {d: s for d, s in data.items() if d <= end}
        return dict(sorted(data.items()))

    def clear_date(self, date: str) -> None:
        self._data.pop(normalize_date(date), None)
        self.save()

    def missing_days(self, start: str, end: str) -> list[str]:
        start_d = datetime.date.fromisoformat(normalize_date(start))
        end_d = datetime.date.fromisoformat(normalize_date(end))
        missing = []
        day = start_d
        while day <= end_d:
            if day.weekday() < 5 and day.isoformat() not in self._data:
                missing.append(day.isoformat())
            day += datetime.timedelta(days=1)
        return missing

    def summary(self, start: str, end: str) -> dict:
        start = normalize_date(start)
        end = normalize_date(end)
        total_min = 0
        days = 0
        open_count = 0
        for date, shifts in self._data.items():
            if start <= date <= end:
                days += 1
                for s in shifts:
                    if s.get("time_out"):
                        total_min += net_minutes(s)
                    else:
                        open_count += 1
        approved_min = min(total_min, days * 8 * 60)
        return {
            "start": start, "end": end,
            "days_worked": days,
            "open_shifts": open_count,
            "total_hours": fmt_duration(total_min),
            "total_decimal": round(total_min / 60, 2),
            "approved_hours": fmt_duration(approved_min),
            "extra_hours": fmt_duration(total_min - approved_min),
        }
