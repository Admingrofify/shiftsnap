"""ShiftSnap photo OCR: read timestamp overlays from "time snap" photos.

Uses the free OCR.space API (no signup needed for the built-in demo key;
set OCR_SPACE_KEY for your own free key to raise the rate limit).
Falls back gracefully: returns "" when the service is unreachable.
"""
from __future__ import annotations

import datetime
import os
import re

import requests

OCR_URL = "https://api.ocr.space/parse/image"


def extract_text(image_bytes: bytes, filename: str = "photo.jpg") -> str:
    """Run OCR on raw image bytes. Returns the extracted text ("" on failure)."""
    api_key = os.getenv("OCR_SPACE_KEY", "helloworld")
    try:
        resp = requests.post(
            OCR_URL,
            files={"file": (filename, image_bytes, "image/jpeg")},
            data={"apikey": api_key, "OCREngine": "2", "scale": "true"},
            timeout=60,
        )
        data = resp.json()
    except Exception:
        return ""
    results = data.get("ParsedResults") or []
    if not results:
        return ""
    return (results[0].get("ParsedText") or "").strip()


# "Sep 14, 2026 at 6:09:04 AM" | "Sep 14, 2026 6:09 AM" | "2026-09-14 06:09" ...
_TS_RES = [
    re.compile(
        r"([A-Za-z]{3,9})\s+(\d{1,2}),\s+(\d{4})\s+(?:at\s+)?"
        r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AP])\.?\s?M\.?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?",
    ),
    re.compile(
        r"(\d{1,2})/(\d{1,2})/(\d{2,4})\s+(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AP])\.?\s?M\.?",
        re.IGNORECASE,
    ),
    # Time without a date, e.g. "Clock In:08:00AM" — OCR often glues the
    # words together and misreads the date. Assume today; this regex runs
    # LAST so dated matches claim their text first.
    re.compile(
        r"(?<!\d)(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AP])\.?\s?M\.?",
        re.IGNORECASE,
    ),
]



def parse_photo_timestamp(text: str) -> dict | None:
    """Find a timestamp inside OCR text.

    Returns {"date": "YYYY-MM-DD", "time": "HH:MM", "raw": <matched text>}
    or None when nothing parseable is found.
    """
    for rx in _TS_RES:
        m = rx.search(text)
        if not m:
            continue
        g = m.groups()
        try:
            if rx is _TS_RES[0]:
                month_name, day, year, hh, mm, _ss, ap = g
                month = datetime.datetime.strptime(month_name[:3].title(), "%b").month
                h = int(hh)
                if ap.upper() == "P" and h != 12:
                    h += 12
                if ap.upper() == "A" and h == 12:
                    h = 0
                date = datetime.date(int(year), month, int(day))
                return {"date": date.isoformat(), "time": f"{h:02d}:{int(mm):02d}",
                        "raw": m.group(0).strip()}
            elif rx is _TS_RES[1]:
                year, month, day, hh, mm, _ss = g
                date = datetime.date(int(year), int(month), int(day))
                return {"date": date.isoformat(), "time": f"{int(hh):02d}:{int(mm):02d}",
                        "raw": m.group(0).strip()}
            elif rx is _TS_RES[2]:
                month, day, year, hh, mm, _ss, ap = g
                year = int(year) if len(year) == 4 else 2000 + int(year)
                h = int(hh)
                if ap.upper() == "P" and h != 12:
                    h += 12
                if ap.upper() == "A" and h == 12:
                    h = 0
                date = datetime.date(year, int(month), int(day))
                return {"date": date.isoformat(), "time": f"{h:02d}:{int(mm):02d}",
                        "raw": m.group(0).strip()}
            else:
                # Time-only match (no date found in the text): assume today.
                hh, mm, _ss, ap = g
                h = int(hh)
                if ap.upper() == "P" and h != 12:
                    h += 12
                if ap.upper() == "A" and h == 12:
                    h = 0
                date = datetime.date.today()
                return {"date": date.isoformat(), "time": f"{h:02d}:{int(mm):02d}",
                        "raw": m.group(0).strip()}
        except ValueError:
            continue
    return None


def find_all_timestamps(text: str) -> list[dict]:
    """Find every timestamp in OCR text (for weekly timesheet photo import).

    Dated patterns run first and claim their spans, so the time-only
    fallback never double-counts a timestamp that already has a date.
    """
    found: list[dict] = []
    seen: set[str] = set()
    used: list[tuple[int, int]] = []
    for rx in _TS_RES:
        for m in rx.finditer(text):
            s, e = m.span()
            if any(s < ue and e > us for us, ue in used):
                continue
            parsed = parse_photo_timestamp(m.group(0))
            if parsed and parsed["raw"] not in seen:
                seen.add(parsed["raw"])
                found.append(parsed)
                used.append((s, e))
    return found
