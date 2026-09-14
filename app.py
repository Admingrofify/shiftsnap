"""ShiftSnap web UI (Streamlit): chat with your timesheet agent.

Run:  streamlit run app.py
"""
from pathlib import Path

import streamlit as st

from src.agent import build_agent
from src.store import ShiftStore

st.set_page_config(page_title="ShiftSnap — Timesheet Agent", page_icon="⏱️",
                   layout="centered")

DATA = Path.home() / ".shiftsnap" / "shifts.json"

st.title("⏱️ ShiftSnap")
st.caption("Your timesheet agent — log shifts in plain English, get a clean Excel timesheet.")

if "agent" not in st.session_state:
    st.session_state.agent = build_agent()
    st.session_state.messages = [
        {"role": "assistant",
         "content": ("Hi! Tell me your shifts like \"Sep 3, 9 AM to 5:30 PM\" and I'll "
                     "log them, total your pay period, and build your Excel timesheet.")},
    ]
    st.session_state.xlsx = None

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("e.g. Sep 3, 9 AM to 5:30 PM, break 12-12:30 PM"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        with st.spinner("Working..."):
            result = st.session_state.agent(prompt)
            text = result.message["content"][0]["text"]
            # surface tool activity
            calls = [b["toolUse"]["name"] for m in result.message.get("content", [])
                     for b in [m] if isinstance(m, dict) and "toolUse" in b]
        st.markdown(text)
    st.session_state.messages.append({"role": "assistant", "content": text})
    st.rerun()

st.divider()
st.subheader("Your shifts")
store = ShiftStore()
data = store.list_shifts()
if data:
    rows = []
    for date, shifts in data.items():
        for s in shifts:
            brk = f"{s['break_start']}-{s['break_end']}" if s.get("break_start") else "—"
            rows.append({"Date": date, "In": s["time_in"], "Out": s["time_out"],
                         "Break": brk, "Comment": s.get("comment", "")})
    st.dataframe(rows, use_container_width=True, hide_index=True)
else:
    st.info("No shifts logged yet — say hello above.")

with st.sidebar:
    st.header("Pay period")
    c1, c2 = st.columns(2)
    start = c1.text_input("Start", "2026-09-01")
    end = c2.text_input("End", "2026-09-15")
    if st.button("📊 Summarize"):
        with st.spinner("..."):
            r = st.session_state.agent(f"Show me my summary for {start} to {end}.")
        st.success(r.message["content"][0]["text"])
    if st.button("📥 Generate Excel timesheet"):
        with st.spinner("Building..."):
            r = st.session_state.agent(f"Generate my timesheet for {start} to {end}.")
        st.success(r.message["content"][0]["text"])
        xlsx = sorted(Path("timesheets").glob("*.xlsx"), key=lambda p: p.stat().st_mtime)
        if xlsx:
            st.download_button("Download timesheet", xlsx[-1].read_bytes(),
                               file_name=xlsx[-1].name)
    st.caption("Provider: " + __import__("os").getenv("MODEL_PROVIDER", "demo"))
