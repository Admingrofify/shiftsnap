"""ShiftSnap CLI demo: scripted conversation showing the agent loop end-to-end.

Usage: python -m src.demo_chat [--store PATH]
"""
import sys

from .agent import build_agent

SCRIPT = [
    "I worked Sep 1, in at 6:58 AM, out at 10:26 PM, with an unpaid break from 2:58 AM to 10:26 AM.",
    "Also Sep 2, 7:05 AM to 6:40 PM, no break.",
    "Show me my summary for Sep 1 to Sep 15.",
    "Generate my timesheet for Sep 1 to Sep 15.",
]


def main() -> None:
    store = sys.argv[sys.argv.index("--store") + 1] if "--store" in sys.argv else None
    agent = build_agent(store_path=store)
    print("=== ShiftSnap demo ===\n")
    for msg in SCRIPT:
        print(f"You:  {msg}")
        result = agent(msg)
        print(f"Agent: {result.message['content'][0]['text']}\n")


if __name__ == "__main__":
    main()
