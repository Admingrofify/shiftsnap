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
    TIME_RE = re.compile(r"(\d{1,2}:\d{2}\s*(?:[AaPp]\.?[Mm]\.?)?)")
    DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2}|[A-Za-z]{3,9}\s+\d{1,2}(?:\s*,?\s*\d{4})?)")

    def _parse_log(self, text: str) -> dict | None:
        times = [t.strip() for t in self.TIME_RE.findall(text)]
        dates = [d.strip() for d in self.DATE_RE.findall(text)]
        if len(times) < 2 or not dates:
            return None
        args: dict = {"date": dates[0], "time_in": times[0], "time_out": times[1]}
        if "break" in text.lower() and len(times) >= 4:
            args["break_start"] = times[2]
            args["break_end"] = times[3]
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

        if "summary" in low or "summarize" in low or "total" in low:
            rng = self._parse_range(text)
            if rng:
                return "Crunching the numbers for that pay period.", [
                    {"name": "pay_period_summary",
                     "input": {"start_date": rng[0], "end_date": rng[1]}}]
            return "Which date range should I summarize? e.g. 'Sep 1 to Sep 15'.", []

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
