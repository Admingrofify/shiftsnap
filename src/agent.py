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

from .demo_model import DemoModel
from .store import ShiftStore
from .tools import make_tools

SYSTEM_PROMPT = """You are ShiftSnap, a helpful timesheet agent for hourly workers.

Your job: turn messy, real-world shift reports into clean, accurate timesheets.

TOOLS (use them; don't do math yourself):
- log_shift: record one shift. Always pass date, time_in, time_out; include
  break_start/break_end when the worker mentions an unpaid break.
- list_shifts: show logged shifts, optionally for a date range.
- pay_period_summary: totals for a pay period (total, approved 8h/day, extra hours).
- generate_timesheet: build the Excel timesheet for a pay period.

BEHAVIOR:
- Parse natural language generously: "Sep 1, 6:58am-10:26pm, break 2:58-10:26am",
  "yesterday 9 to 5", "today 18:00-02:00".
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
                provider: str | None = None) -> Agent:
    provider = (provider or os.getenv("MODEL_PROVIDER", "demo")).lower()
    store = ShiftStore(store_path) if store_path else ShiftStore()
    tools = make_tools(store)

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
