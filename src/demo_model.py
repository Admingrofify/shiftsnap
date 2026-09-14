"""DemoModel: a deterministic, offline model provider for ShiftSnap.

It implements the Strands Model interface with simple rule-based intent
parsing so the full agent loop (model -> tool call -> tool result -> model)
runs end-to-end with zero API keys or network access.

Set MODEL_PROVIDER=bedrock (or openai/anthropic) to use a real model instead.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any, AsyncGenerator

from strands.models.model import Model


def _blocks_text(msg: dict) -> str:
    return " ".join(b.get("text", "") for b in msg.get("content", []) if "text" in b)


def _current_pay_period() -> tuple[str, str]:
    """This pay period as ISO dates (1st–15th / 16th–month end), NY time."""
    import calendar
    from .nytime import ny_today
    d = ny_today()
    if d.day <= 15:
        return d.replace(day=1).isoformat(), d.replace(day=15).isoformat()
    last = calendar.monthrange(d.year, d.month)[1]
    return d.replace(day=16).isoformat(), d.replace(day=last).isoformat()


class DemoModel(Model):
    """Rule-based stand-in model for offline demos."""

    def __init__(self):
        self._config: dict = {"model_id": "shiftsnap-demo-1"}

    def update_config(self, **model_config: Any) -> None:
        self._config.update(model_config)

    def get_config(self) -> Any:
        return self._config

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError("DemoModel does not support structured output")

    # ---- intent parsing -------------------------------------------------
    TIME_RE = re.compile(
        r"(\d{1,2}:\d{2}\s*(?:[AaPp]\.?[Mm]\.?)?|\d{1,2}\s*[AaPp]\.?[Mm]\.?)")
    DATE_RE = re.compile(
        r"(\d{4}-\d{2}-\d{2}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)"
        r"[a-z]*\s+\d{1,2}(?:\s*,?\s*\d{4})?)", re.IGNORECASE)
    BREAK_RE = re.compile(
        r"break\s+(\d{1,2}(?::\d{2})?\s*(?:[AaPp]\.?[Mm]\.?)?)\s*[-–]\s*"
        r"(\d{1,2}(?::\d{2})?\s*(?:[AaPp]\.?[Mm]\.?)?)", re.IGNORECASE)

    def _parse_log(self, text: str) -> dict | None:
        times = [t.strip() for t in self.TIME_RE.findall(text)]
        dates = [d.strip() for d in self.DATE_RE.findall(text)]
        if len(times) < 2 or not dates:
            return None
        args: dict = {"date": dates[0], "time_in": times[0], "time_out": times[1]}
        bm = self.BREAK_RE.search(text)
        if bm:
            args["break_start"] = bm.group(1).strip()
            args["break_end"] = bm.group(2).strip()
        return args

    def _parse_range(self, text: str) -> tuple[str, str] | None:
        dates = [d.strip() for d in self.DATE_RE.findall(text)]
        if len(dates) >= 2:
            return dates[0], dates[1]
        return None

    def _decide(self, messages: list[dict]) -> tuple[str, list[dict]]:
        """Return (reply_text, tool_calls)."""
        # Collect tool uses and results to detect a pending-results turn.
        use_names: dict[str, str] = {}
        pending: list[tuple[str, str]] = []
        last_user_text = ""
        last_text_idx, last_result_idx = -1, -1
        for i, msg in enumerate(messages):
            has_result = False
            for block in msg.get("content", []):
                if "toolUse" in block:
                    tu = block["toolUse"]
                    use_names[tu["toolUseId"]] = tu["name"]
                elif "toolResult" in block:
                    has_result = True
                    tr = block["toolResult"]
                    txt = " ".join(b.get("text", "") for b in tr.get("content", []) if isinstance(b, dict))
                    pending.append((use_names.get(tr["toolUseId"], "?"), txt))
            if msg.get("role") == "user":
                if _blocks_text(msg).strip():
                    last_text_idx = i
                    last_user_text = _blocks_text(msg)
                if has_result:
                    last_result_idx = i

        # If the latest turn ended with tool results, summarize just that turn.
        if pending and last_result_idx > last_text_idx:
            # only results belonging to the most recent assistant tool-call turn
            last_turn_ids: set[str] = set()
            for msg in messages:
                ids = [b["toolUse"]["toolUseId"] for b in msg.get("content", [])
                       if "toolUse" in b]
                if msg.get("role") == "assistant" and ids:
                    last_turn_ids = set(ids)
            ordered: list[tuple[str, str]] = []
            seen: set[str] = set()
            for msg in messages:
                for block in msg.get("content", []):
                    if "toolResult" in block:
                        tid = block["toolResult"]["toolUseId"]
                        if tid in last_turn_ids and tid not in seen:
                            seen.add(tid)
                            ordered.append((use_names.get(tid, "?"),
                                            " ".join(b.get("text", "") for b in
                                                     block["toolResult"].get("content", [])
                                                     if isinstance(b, dict))))
            parts = []
            for name, result in ordered:
                if name == "log_shift":
                    parts.append(result)
                elif name == "pay_period_summary":
                    parts.append(result)
                elif name == "generate_timesheet":
                    parts.append("Your Excel timesheet is ready to download. " + result)
                elif name == "list_shifts":
                    parts.append("Here are your logged shifts:\n" + result)
                else:
                    parts.append(result)
            return " ".join(parts), []

        text = last_user_text
        low = text.lower()

        clock_hit = (re.search(r"\bclock(\s+me)?\s*-?\s*in\b", low)
                     or re.search(r"\bclock(\s+me)?\s*-?\s*out\b", low)
                     or "clocked in" in low or "clocked out" in low)
        if ("punch" in low or "photo" in low or "snap" in low
                or "import" in low or clock_hit):
            from .ocr import parse_photo_timestamp
            if "import" in low and "photo" in low:
                return ("Scanning the timesheet photo for timestamps.",
                        [{"name": "import_timesheet_photo",
                          "input": {"ocr_text": text}}])
            parsed = parse_photo_timestamp(text)
            if parsed:
                return ("Reading the timestamp from your photo.",
                        [{"name": "punch_clock", "input": {"timestamp": text}}])
            if clock_hit:
                # Clock In/Out button tap; GPS may ride along as lat=/lng=/acc=
                lat = re.search(r"lat=([-\d.]+)", low)
                lng = re.search(r"lng=([-\d.]+)", low)
                acc = re.search(r"acc(?:uracy)?=([\d.]+)", low)
                inp: dict = {}
                if lat:
                    inp["lat"] = lat.group(1)
                if lng:
                    inp["lng"] = lng.group(1)
                if acc:
                    inp["accuracy"] = acc.group(1)
                return ("Clocking you in now.",
                        [{"name": "clock_now", "input": inp}])
            return ("I couldn't read a timestamp from that photo — make sure the "
                    "time overlay is visible and try again."), []

        if "summary" in low or "summarize" in low or "total" in low:
            rng = self._parse_range(text)
            if rng:
                return "Crunching the numbers for that pay period.", [
                    {"name": "pay_period_summary",
                     "input": {"start_date": rng[0], "end_date": rng[1]}}]
            return "Which date range should I summarize? e.g. 'Sep 1 to Sep 15'.", []

        # Natural "how many hours did I work …?" phrasing. "Current pay
        # period" resolves to the 1st–15th / 16th–end range in NY time.
        if re.search(r"\bhow many hours\b", low) or ("hours" in low and "work" in low):
            rng = self._parse_range(text)
            if not rng and "pay period" in low:
                rng = _current_pay_period()
            if rng:
                return "Crunching the numbers for that period.", [
                    {"name": "pay_period_summary",
                     "input": {"start_date": rng[0], "end_date": rng[1]}}]
            return "Which date range should I check? e.g. 'Sep 1 to Sep 15'.", []

        if "timesheet" in low or "excel" in low or "generate" in low:
            rng = self._parse_range(text)
            if rng:
                return "Generating your timesheet now.", [
                    {"name": "generate_timesheet",
                     "input": {"start_date": rng[0], "end_date": rng[1]}}]
            return "Which date range should the timesheet cover?", []

        if "list" in low or "show" in low and "shift" in low:
            rng = self._parse_range(text)
            args = {"start_date": rng[0], "end_date": rng[1]} if rng else {}
            return "Pulling up your shifts.", [{"name": "list_shifts", "input": args}]

        args = self._parse_log(text)
        if args:
            brk = f" with break {args['break_start']}-{args['break_end']}" if "break_start" in args else ""
            return (f"On it — logging {args['date']}, {args['time_in']} to {args['time_out']}{brk}.",
                    [{"name": "log_shift", "input": args}])

        return ("I can log shifts ('Sep 3, 9 AM to 5:30 PM'), summarize a pay period, "
                "or generate your Excel timesheet. What do you need?"), []

    # ---- stream protocol ------------------------------------------------
    async def stream(self, messages, tool_specs=None, system_prompt=None, *,
                     tool_choice=None, **kwargs) -> AsyncGenerator[dict, None]:
        reply, calls = self._decide(list(messages))

        yield {"messageStart": {"role": "assistant"}}
        yield {"contentBlockStart": {"start": {}}}
        # stream the reply in small chunks for a lively demo
        for i in range(0, len(reply), 24):
            yield {"contentBlockDelta": {"delta": {"text": reply[i:i + 24]}}}
        yield {"contentBlockStop": {}}

        for call in calls:
            tool_use_id = f"tooluse_{uuid.uuid4().hex[:24]}"
            yield {"contentBlockStart": {"start": {"toolUse": {
                "name": call["name"], "toolUseId": tool_use_id}}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(call["input"])}}}}
            yield {"contentBlockStop": {}}

        yield {"messageStop": {"stopReason": "tool_use" if calls else "end_turn"}}
