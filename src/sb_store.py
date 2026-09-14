"""ShiftSnap Supabase backend: multi-worker shift store on Postgres.

Same method interface as src.store.ShiftStore, plus worker scoping:
every method takes an optional employee_id (a workers.id uuid string).

Connects with the service_role key, which must stay server-side
(Streamlit secrets / env vars — never shipped to the browser).
"""
from __future__ import annotations

import datetime
import os

from .store import (ShiftStore, fmt_duration, net_minutes, normalize_date,
                    normalize_time, to_minutes)


def _hhmm(value) -> str | None:
    """Normalize a Postgres `time` value ('HH:MM:SS') to 'HH:MM'."""
    if value is None:
        return None
    s = str(value)
    return s[:5] if len(s) >= 5 else s


class SupabaseShiftStore(ShiftStore):
    """ShiftStore API backed by Supabase Postgres instead of local JSON."""

    def __init__(self, employee_id: str | None = None):
        # Don't call ShiftStore.__init__ (no local file needed).
        self.employee_id = employee_id
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_KEY", "") or os.getenv("SUPABASE_SERVICE_KEY", "")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY env vars are required.")
        from supabase import create_client
        self.client = create_client(url, key)

    # ---- workers ------------------------------------------------------
    def list_workers(self) -> list[dict]:
        res = (self.client.table("workers").select("id,name")
               .order("name").execute())
        return res.data or []

    def get_or_create_worker(self, name: str) -> dict:
        name = name.strip()
        if not name:
            raise ValueError("Worker name is required.")
        res = (self.client.table("workers").select("id,name")
               .eq("name", name).limit(1).execute())
        if res.data:
            return res.data[0]
        res = (self.client.table("workers").insert({"name": name})
               .select("id,name").execute())
        return res.data[0]

    def is_admin(self, employee_id: str) -> bool:
        res = (self.client.table("admins").select("worker_id")
               .eq("worker_id", employee_id).limit(1).execute())
        return bool(res.data)

    # ---- internal -----------------------------------------------------
    def _emp(self, employee_id: str | None) -> str:
        emp = employee_id or self.employee_id
        if not emp:
            raise ValueError("No worker selected.")
        return emp

    def _row_to_shift(self, row: dict) -> dict:
        return {"time_in": _hhmm(row["time_in"]),
                "time_out": _hhmm(row.get("time_out")),
                "break_start": _hhmm(row.get("break_start")),
                "break_end": _hhmm(row.get("break_end")),
                "comment": row.get("comment") or "",
                "source": row.get("source") or "chat",
                "lat": row.get("lat"), "lng": row.get("lng")}

    def _shifts_for(self, employee_id: str, start: str | None = None,
                    end: str | None = None) -> dict[str, list[dict]]:
        q = (self.client.table("shifts")
             .select("*").eq("employee_id", employee_id).order("date")
             .order("time_in"))
        if start:
            q = q.gte("date", normalize_date(start))
        if end:
            q = q.lte("date", normalize_date(end))
        data: dict[str, list[dict]] = {}
        for row in q.execute().data or []:
            data.setdefault(row["date"], []).append(self._row_to_shift(row))
        return data

    # ---- ShiftStore-compatible API ------------------------------------
    def log_shift(self, date: str, time_in: str, time_out: str,
                  break_start: str | None = None, break_end: str | None = None,
                  comment: str = "", employee_id: str | None = None,
                  source: str = "chat", lat=None, lng=None,
                  accuracy=None) -> dict:
        emp = self._emp(employee_id)
        date = normalize_date(date)
        time_in = normalize_time(time_in)
        time_out = normalize_time(time_out)
        if to_minutes(time_out) <= to_minutes(time_in):
            # allow overnight: keep on start date, net_minutes adds 24h
            pass
        if break_start:
            break_start = normalize_time(break_start)
        if break_end:
            break_end = normalize_time(break_end)
        # replace an identical open/closed shift for the day
        existing = (self.client.table("shifts").select("id")
                    .eq("employee_id", emp).eq("date", date)
                    .eq("time_in", time_in).eq("time_out", time_out)
                    .limit(1).execute()).data or []
        payload = {"employee_id": emp, "date": date, "time_in": time_in,
                   "time_out": time_out, "break_start": break_start,
                   "break_end": break_end, "comment": comment, "source": source,
                   "lat": lat, "lng": lng, "accuracy_m": accuracy}
        if existing:
            self.client.table("shifts").update(payload).eq(
                "id", existing[0]["id"]).execute()
        else:
            self.client.table("shifts").insert(payload).execute()
        shift = {"time_in": time_in, "time_out": time_out,
                 "break_start": break_start, "break_end": break_end,
                 "comment": comment}
        shift = dict(shift)
        shift["net"] = fmt_duration(net_minutes(shift))
        return {"date": date, **shift}

    def punch(self, date: str, time: str, comment: str = "",
              employee_id: str | None = None, source: str = "chat",
              lat=None, lng=None, accuracy=None) -> dict:
        emp = self._emp(employee_id)
        date = normalize_date(date)
        time = normalize_time(time)
        day = datetime.date.fromisoformat(date)

        open_row = None
        for cand in (date, (day - datetime.timedelta(days=1)).isoformat()):
            rows = (self.client.table("shifts").select("*")
                    .eq("employee_id", emp).eq("date", cand)
                    .is_("time_out", "null").order("time_in").limit(1)
                    .execute()).data or []
            if rows:
                open_row = rows[0]
                break

        if open_row:
            self.client.table("shifts").update({"time_out": time}).eq(
                "id", open_row["id"]).execute()
            s = self._row_to_shift({**open_row, "time_out": time})
            return {"action": "out", "date": open_row["date"],
                    "time_in": s["time_in"], "time_out": time,
                    "net": fmt_duration(net_minutes(s))}

        self.client.table("shifts").insert(
            {"employee_id": emp, "date": date, "time_in": time,
             "comment": comment, "source": source,
             "lat": lat, "lng": lng, "accuracy_m": accuracy}).execute()
        return {"action": "in", "date": date, "time_in": time,
                "time_out": None, "net": "0:00"}

    def list_shifts(self, start: str | None = None, end: str | None = None,
                    employee_id: str | None = None) -> dict[str, list[dict]]:
        return self._shifts_for(self._emp(employee_id), start, end)

    def open_shifts(self, employee_id: str | None = None) -> list[dict]:
        emp = self._emp(employee_id)
        rows = (self.client.table("shifts").select("*").eq("employee_id", emp)
                .is_("time_out", "null").order("date").order("time_in")
                .execute()).data or []
        return [{"date": r["date"], **self._row_to_shift(r)} for r in rows]

    def clear_date(self, date: str, employee_id: str | None = None) -> None:
        (self.client.table("shifts").delete().eq("employee_id", self._emp(employee_id))
         .eq("date", normalize_date(date)).execute())

    def missing_days(self, start: str, end: str,
                     employee_id: str | None = None) -> list[str]:
        emp = self._emp(employee_id)
        start_d = datetime.date.fromisoformat(normalize_date(start))
        end_d = datetime.date.fromisoformat(normalize_date(end))
        have = set(self._shifts_for(emp, start, end))
        missing = []
        day = start_d
        while day <= end_d:
            if day.weekday() < 5 and day.isoformat() not in have:
                missing.append(day.isoformat())
            day += datetime.timedelta(days=1)
        return missing

    def summary(self, start: str, end: str,
                employee_id: str | None = None) -> dict:
        emp = self._emp(employee_id)
        start_n = normalize_date(start)
        end_n = normalize_date(end)
        data = self._shifts_for(emp, start_n, end_n)
        total_min = 0
        open_count = 0
        for shifts in data.values():
            for s in shifts:
                if s.get("time_out"):
                    total_min += net_minutes(s)
                else:
                    open_count += 1
        days = len(data)
        approved_min = min(total_min, days * 8 * 60)
        return {
            "start": start_n, "end": end_n,
            "days_worked": days,
            "open_shifts": open_count,
            "total_hours": fmt_duration(total_min),
            "total_decimal": round(total_min / 60, 2),
            "approved_hours": fmt_duration(approved_min),
            "extra_hours": fmt_duration(total_min - approved_min),
        }

    def team_summary(self, start: str, end: str) -> list[dict]:
        """Per-worker summaries for the admin view."""
        out = []
        for w in self.list_workers():
            s = self.summary(start, end, employee_id=w["id"])
            if s["days_worked"]:
                out.append({"worker": w["name"], **s})
        return sorted(out, key=lambda r: r["worker"])
