"""ShiftSnap agent: a Strands agent that manages hourly-work timesheets.

Provider selection via MODEL_PROVIDER env var:
    demo       - offline rule-based provider (default; zero API keys, for demos)
    bedrock    - Amazon Bedrock (Strands default)
    openai     - OpenAI (needs OPENAI_API_KEY)
    anthropic  - Anthropic (needs ANTHROPIC_API_KEY)
"""
from __future__ import annotations

import os
from pathlib import Path

from strands import Agent

from .backend import get_store, supabase_configured
from .demo_model import DemoModel
from .tools import make_tools

SYSTEM_PROMPT = """You are ShiftSnap, a helpful timesheet agent for hourly workers.

Your job: turn messy, real-world shift reports into clean, accurate timesheets.

TOOLS (use them; don't do math yourself):
- log_shift: record one shift. Always pass date, time_in, time_out; include
  break_start/break_end when the worker mentions an unpaid break.
- punch_clock: clock in/out from a timestamp. Pass the raw OCR text
  (e.g. 'Sep 14, 2026 at 6:09:04 AM') plus optional lat/lng/accuracy and
  source ('button', 'photo', 'chat'). First punch of the day clocks in;
  the next punch clocks out and completes the shift.
- clock_now: clock in/out right now (Clock In/Out buttons). Pass the
  browser-captured lat/lng/accuracy when available.
- import_timesheet_photo: extract every timestamp from a weekly timesheet
  photo's OCR text; returns a numbered list for the worker to review
  before logging as punches.
- list_shifts: show logged shifts, optionally for a date range.
- pay_period_summary: totals for a pay period (total, approved 8h/day, extra hours).
- generate_timesheet: build the Excel timesheet for a pay period.

BEHAVIOR:
- Parse natural language generously: "Sep 1, 6:58am-10:26pm, break 2:58-10:26am",
  "yesterday 9 to 5", "today 18:00-02:00".
- When the worker taps Clock In/Out, call clock_now with the GPS coordinates.
- When the worker sends a photo timestamp ("photo shows ...", "I clocked in at
  ...", "snap: ..."), call punch_clock with the timestamp text and source='photo'.
- For a weekly timesheet photo, call import_timesheet_photo, show the found
  timestamps, and only log the ones the worker confirms (via punch_clock each).
- Times may cross midnight; if time_out looks earlier than time_in and no date
  change is given, ask rather than guess.
- After logging, always confirm the computed net hours back to the worker.
- Unpaid breaks reduce net hours; say so explicitly when you subtract one.
- When asked for a summary or timesheet, proactively mention missing weekday
  entries in the range so nothing gets under-reported.
- Be concise and warm. This runs quietly in the background of someone's work
  life; only surface what needs a decision.
"""


def build_agent(store_path: str | Path | None = None,
                provider: str | None = None,
                worker_id: str | None = None) -> Agent:
    provider = (provider or os.getenv("MODEL_PROVIDER", "demo")).lower()
    if store_path and not supabase_configured():
        from .store import ShiftStore
        store = ShiftStore(store_path)
        tools = make_tools(store)
    else:
        store = get_store(worker_id)
        tools = make_tools(store, worker_id=worker_id)

    if provider == "demo":
        model = DemoModel()
    elif provider == "bedrock":
        from strands.models import BedrockModel
        model = BedrockModel()
    elif provider == "openai":
        from strands.models import OpenAIModel
        model = OpenAIModel()
    elif provider == "anthropic":
        from strands.models import AnthropicModel
        model = AnthropicModel()
    else:
        raise ValueError(f"Unknown MODEL_PROVIDER: {provider}")

    return Agent(model=model, tools=tools, system_prompt=SYSTEM_PROMPT)
