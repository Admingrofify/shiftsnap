"""ShiftSnap backend selection: Supabase Postgres vs local JSON demo store."""
from __future__ import annotations

import os


def supabase_configured() -> bool:
    return bool(os.getenv("SUPABASE_URL") and
                (os.getenv("SUPABASE_ANON_KEY") or os.getenv("SUPABASE_KEY")
                 or os.getenv("SUPABASE_SERVICE_KEY")))


def get_store(worker_id: str | None = None):
    """Return the active shift store.

    SupabaseShiftStore when SUPABASE_URL/SUPABASE_KEY are set (multi-worker),
    otherwise the local JSON ShiftStore (single-worker demo mode).
    """
    if supabase_configured():
        from .sb_store import SupabaseShiftStore
        return SupabaseShiftStore(employee_id=worker_id)
    from .store import ShiftStore
    return ShiftStore()
