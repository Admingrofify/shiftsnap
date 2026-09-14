# ShiftSnap — Devpost submission copy (draft, ready to paste)

## Project name
ShiftSnap

## Tagline / elevator pitch
Your timesheet agent: log shifts in plain words, get employer-ready timesheets.

## Inspiration
Hourly workers — warehouse staff, site technicians, healthcare aides — work long, irregular shifts and then face the most dreaded admin of the pay period: the timesheet. Timestamps live in photos, texts, and memory; breaks get forgotten; a missed day means lost pay. Payroll disputes over hours are one of the most common wage complaints in hourly work. ShiftSnap exists so logging a shift is as easy as texting a friend.

## What it does
ShiftSnap is a conversational agent that turns natural-language shift notes into accurate, employer-ready timesheets:
- **Log shifts in plain words** — "worked yesterday 7am to 6:30pm, break 1 to 1:45" becomes a precise, break-aware time entry. No forms, no apps to learn.
- **Break-aware math** — unpaid breaks are subtracted automatically; net hours, decimal hours, approved hours, and overtime-style "extra hours" are computed for you.
- **Missing-day nudges** — the agent flags weekdays in the pay period with no entry, so no shift (and no pay) slips through.
- **One-click Excel timesheets** — generates a clean, formatted workbook for any pay period, ready to send to a manager or payroll.

## How we built it
ShiftSnap is built on the **Strands Agents SDK**. A single Strands `Agent` drives a tool-calling loop over four typed tools:
- `log_shift` — parse and store a shift from natural language
- `list_shifts` — review logged entries
- `pay_period_summary` — totals, approved vs. extra hours, missing days
- `generate_timesheet` — build the formatted Excel workbook (openpyxl)

The agent runs against a pluggable model provider (Bedrock, OpenAI, Anthropic, or a deterministic offline demo model), with a Streamlit chat UI on top and a local JSON shift store — so worker data stays private on the worker's own machine. Demo data is fully synthetic.

## Challenges we ran into
The hardest part was time itself: parsing "yesterday 7am to 6:30pm" reliably, handling overnight shifts, and making break subtraction unambiguous when workers describe breaks casually. We solved it with a dedicated natural date/time parser plus explicit confirmation of parsed entries before they're stored.

## Accomplishments that we're proud of
- A full working agent loop — natural language in, verified Excel out — in a single focused project.
- Break-aware calculations and missing-day detection that match how real hourly payroll works (e.g., 8 approved hours/day, extras tracked separately).
- A demo that runs entirely offline, so anyone can try it without API keys.

## What we learned
Small, well-scoped tools beat one giant prompt. Giving the agent four narrow tools with clear schemas made its behavior predictable and its output trustworthy — exactly what you want when the output determines someone's paycheck.

## What's next for ShiftSnap
- Photo timestamp ingestion (snap a photo of a time clock, get a logged shift)
- Multi-worker crews and manager approval flows
- One-tap export to common payroll formats (CSV, PDF)
- Optional cloud sync via AWS AgentCore for teams

## Built with
Strands Agents SDK, Python, Streamlit, openpyxl

## Links
- GitHub repo: https://github.com/Admingrofify/shiftsnap
- Demo video: (YouTube unlisted link — to be added)
