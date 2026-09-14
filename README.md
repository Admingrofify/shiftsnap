# ⏱️ ShiftSnap — your timesheet agent

**Track:** Professional Agents · **Built with:** [Strands Agents SDK](https://strandsagents.com)

Hourly workers lose real money to messy timesheets: timestamp photos, mental math,
unpaid breaks forgotten, under-reported hours. ShiftSnap is an AI agent that runs
quietly in the background of your work life — **snap a photo of your timestamp**
when you clock in and out, or just tell it your shifts in plain English, and it
logs them, totals your pay period, flags missing days, and builds a clean Excel
timesheet ready to submit.

## 📸 Snap a timestamp photo

The fastest way to log: photograph your clock-in / clock-out screen.

```
You:  [uploads timestamp photo]
Agent: 🔍 reading… "Sep 14, 2026 at 6:09:04 AM"
Agent: ✅ Clocked in 2026-09-14 at 06:09. Snap your clock-out photo when the shift ends.
You:  [uploads clock-out photo]
Agent: ✅ Clocked out at 22:26. Shift 06:09 → 22:26, net 16:17.
```

ShiftSnap OCRs the photo, extracts the timestamp overlay, and pairs clock-in/out
punches into shifts — including overnight shifts past midnight.

## Demo

```
You:  I worked Sep 1, in at 6:58 AM, out at 10:26 PM,
      with an unpaid break from 2:58 AM to 10:26 AM.
Agent: Logged 2026-09-01: 06:58 → 22:26 (break 02:58-10:26). Net hours: 8:00.

You:  Also Sep 2, 7:05 AM to 6:40 PM, no break.
Agent: Logged 2026-09-02: 07:05 → 18:40. Net hours: 11:35.

You:  Show me my summary for Sep 1 to Sep 15.
Agent: Pay period 2026-09-01 to 2026-09-15: 2 day(s) worked,
       total 19:35 (19.58h), approved 16:00, extra 3:35.
       Missing (weekday) entries: 2026-09-03, 2026-09-04…

You:  Generate my timesheet for Sep 1 to Sep 15.
Agent: Your Excel timesheet is ready to download. ✅
```

## How it works

```
┌─────────┐   plain English    ┌────────────────────────┐
│  Worker │ ─────────────────▶ │  Strands Agent         │
└─────────┘                    │  (agent.py)            │
                               │                        │
                               │  ┌──────────────────┐  │
                               │  │ Model provider   │  │
                               │  │ demo / bedrock / │  │
                               │  │ openai/anthropic │  │
                               │  └──────────────────┘  │
                               └──────────┬─────────────┘
                                          │ tool calls (agent loop)
              ┌───────────────────────────┼────────────────────────────┐
              ▼                           ▼                            ▼
   ┌───────────────────┐      ┌────────────────────┐      ┌──────────────────────┐
   │ log_shift         │      │ pay_period_summary │      │ generate_timesheet   │
   │ list_shifts       │      │ - totals, approved │      │ - formatted Excel    │
   │ - natural time    │      │   & extra hours    │      │ - per-day rows,      │
   │   parsing, breaks │      │ - missing-day      │      │   totals, est. pay   │
   └─────────┬─────────┘      │   nudges           │      └──────────────────────┘
             ▼                └────────────────────┘
   ┌───────────────────┐
   │ ShiftStore        │
   │ (JSON shift log)  │
   └───────────────────┘
```

The agent follows the Strands agent loop: the model reasons, calls tools,
observes results, and only surfaces back to the worker when there's something
worth saying — a confirmation, a missing day, or the finished timesheet.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. Chat with the agent (offline demo provider, no API keys needed)
python -m src.demo_chat   # or: MODEL_PROVIDER=bedrock python -m src.demo_chat

# 2. Web UI with live Excel download
streamlit run app.py
```

Copy `profile.sample.json` → `profile.json` and fill in your name, hourly rate,
and project details to personalize the generated timesheet.

### Model providers

| `MODEL_PROVIDER` | Notes |
|---|---|
| `demo` (default) | Deterministic offline provider — the full agent loop runs with zero setup. Perfect for trying the demo. |
| `bedrock` | Amazon Bedrock (Strands default). Needs AWS credentials + model access. |
| `openai` | Needs `OPENAI_API_KEY`. |
| `anthropic` | Needs `ANTHROPIC_API_KEY`. |

The agent, tools, and prompts are identical across providers — only the model
plugs in differently, which is the point of the Strands SDK.

## Project layout

```
shiftsnap/
├── app.py               # Streamlit web UI (chat + Excel download)
├── src/
│   ├── agent.py         # Strands Agent wiring, system prompt, provider switch
│   ├── demo_model.py    # Offline Model implementation (demo harness)
│   ├── tools.py         # @tool functions: log/list/summarize/generate
│   ├── store.py         # Shift log, natural time/date parsing, hour math
│   └── timesheet.py     # Formatted Excel timesheet builder (openpyxl)
├── profile.sample.json  # Worker profile template (fictional sample data)
└── requirements.txt
```

## Why it matters

Millions of hourly workers — warehouse staff, data-center technicians, home
aides — track time across long, irregular shifts and submit timesheets every
pay period to get paid. One forgotten break or mis-added hour is lost wages.
ShiftSnap removes the arithmetic and the admin: talk like a human, get paid
like a professional.

*Built for the Agents for Humans Hackathon (AWS + Devpost), Professional Agents track.*
