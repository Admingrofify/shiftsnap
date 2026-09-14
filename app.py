"""ShiftSnap web UI: snap timestamp photos, chat with your timesheet agent.

Run:  streamlit run app.py
"""
from __future__ import annotations

import calendar
import datetime
from pathlib import Path

import streamlit as st

from src.agent import build_agent
from src.ocr import extract_text, parse_photo_timestamp
from src.store import ShiftStore, fmt_duration, net_minutes

st.set_page_config(page_title="ShiftSnap — Snap. Log. Get paid.",
                   page_icon="⏱️", layout="centered",
                   initial_sidebar_state="collapsed")

DATA = Path.home() / ".shiftsnap" / "shifts.json"
ACCENT = "#0E7C7B"
ACCENT_DARK = "#0A5A59"
AMBER = "#E8A33D"
INK = "#17222B"
MUTED = "#6B7A87"
PAPER = "#F6F4EE"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
* {{ font-family: 'Inter', -apple-system, sans-serif; }}
.stApp {{ background: {PAPER}; }}
header[data-testid="stHeader"], footer, #MainMenu {{ display: none !important; }}
.block-container {{ padding-top: 1.2rem; padding-bottom: 6rem; max-width: 640px; }}

/* hero */
.hero {{
  background: linear-gradient(135deg, #0E2A38 0%, #0E7C7B 100%);
  border-radius: 22px; padding: 26px 22px; color: white;
  box-shadow: 0 12px 32px rgba(14,124,123,.28); margin-bottom: 18px;
}}
.hero h1 {{ color: #fff; font-size: 2rem; font-weight: 800; margin: 0 0 4px; letter-spacing: -.5px; }}
.hero p {{ color: rgba(255,255,255,.82); margin: 0 0 14px; font-size: .95rem; }}
.hero .logo {{
  width: 46px; height: 46px; border-radius: 14px; background: rgba(255,255,255,.14);
  display: flex; align-items: center; justify-content: center; font-size: 26px; margin-bottom: 10px;
}}
.steps {{ display: flex; gap: 8px; }}
.step {{
  flex: 1; background: rgba(255,255,255,.12); border-radius: 12px;
  padding: 8px 6px; text-align: center; font-size: .68rem; color: rgba(255,255,255,.9);
}}
.step b {{ display: block; font-size: 1rem; }}

/* cards */
.card {{
  background: #fff; border-radius: 18px; padding: 18px;
  box-shadow: 0 4px 18px rgba(23,34,43,.07); margin-bottom: 14px;
  border: 1px solid rgba(23,34,43,.05);
}}
.card h3 {{ margin: 0 0 2px; font-size: 1.02rem; font-weight: 700; color: {INK}; }}
.card .sub {{ color: {MUTED}; font-size: .82rem; margin-bottom: 10px; }}

/* stat tiles */
.stats {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
.stat {{
  background: #fff; border-radius: 16px; padding: 14px;
  border: 1px solid rgba(23,34,43,.06); box-shadow: 0 3px 12px rgba(23,34,43,.05);
}}
.stat .v {{ font-size: 1.45rem; font-weight: 800; color: {INK}; letter-spacing: -.5px; }}
.stat .l {{ font-size: .72rem; color: {MUTED}; text-transform: uppercase; letter-spacing: .6px; }}
.stat.hl .v {{ color: {ACCENT}; }}

/* shift rows */
.day {{ margin-bottom: 12px; }}
.day .dhead {{ font-weight: 700; font-size: .85rem; color: {INK}; margin-bottom: 6px; }}
.shift {{
  display: flex; align-items: center; gap: 10px; background: #fff;
  border-radius: 14px; padding: 12px 14px; margin-bottom: 8px;
  border: 1px solid rgba(23,34,43,.06);
}}
.shift .times {{ font-weight: 700; font-size: .95rem; color: {INK}; }}
.shift .net {{ margin-left: auto; font-weight: 800; color: {ACCENT}; font-size: .95rem; }}
.badge {{
  font-size: .68rem; font-weight: 700; padding: 4px 10px; border-radius: 999px;
  text-transform: uppercase; letter-spacing: .5px;
}}
.badge.open {{ background: #FFF3D6; color: #9A6B00; }}
.badge.done {{ background: #DFF5F1; color: {ACCENT_DARK}; }}
.pulse {{ display:inline-block; width:8px; height:8px; border-radius:50%; background:{AMBER};
  margin-right:6px; animation: pl 1.6s infinite; }}
@keyframes pl {{ 0%,100% {{ opacity:1; }} 50% {{ opacity:.25; }} }}

/* photo result */
.snap-ok {{ text-align: center; padding: 6px 0 2px; }}
.snap-ok .ts {{ font-size: 2rem; font-weight: 800; color: {INK}; letter-spacing: -1px; }}
.snap-ok .dt {{ color: {MUTED}; font-size: .9rem; margin-bottom: 8px; }}

/* chat */
[data-testid="stChatMessage"] {{
  background: #fff; border-radius: 16px; border: 1px solid rgba(23,34,43,.06);
  box-shadow: 0 2px 10px rgba(23,34,43,.04); padding: 12px 14px; margin-bottom: 10px;
}}
[data-testid="stChatMessageAvatarUser"] {{ background: {ACCENT}; }}
.stChatInput {{ position: sticky; }}

/* uploader */
[data-testid="stFileUploader"] {{
  border: 2px dashed rgba(14,124,123,.4); border-radius: 16px;
  padding: 14px; background: rgba(14,124,123,.05);
}}
[data-testid="stFileUploader"] button {{
  background: {ACCENT} !important; color: #fff !important; border: none !important;
  border-radius: 12px !important; font-weight: 700 !important; width: 100%;
  padding: 12px !important;
}}
.stButton > button {{
  background: {ACCENT}; color: #fff; border: none; border-radius: 14px;
  font-weight: 700; padding: 12px 18px; width: 100%;
}}
.stButton > button:hover {{ background: {ACCENT_DARK}; color: #fff; }}
.stDownloadButton > button {{
  background: {INK}; color: #fff; border-radius: 14px; font-weight: 700;
  padding: 12px 18px; width: 100%; border: none;
}}
.empty {{ text-align: center; color: {MUTED}; padding: 22px 10px; font-size: .9rem; }}
.section-t {{ font-size: 1.1rem; font-weight: 800; color: {INK}; margin: 20px 0 10px; }}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ---------- state ----------
def default_period():
    today = datetime.date.today()
    if today.day <= 15:
        return today.replace(day=1), today.replace(day=15)
    last = calendar.monthrange(today.year, today.month)[1]
    return today.replace(day=16), today.replace(day=last)


if "agent" not in st.session_state:
    st.session_state.agent = build_agent()
    st.session_state.messages = [{
        "role": "assistant",
        "content": ("👋 I'm ShiftSnap. **Snap a photo** of your timestamp when you "
                    "clock in and out — I'll read the time, log your shifts, and "
                    "build your Excel timesheet. You can also just type, e.g. "
                    "\"Sep 3, 9 AM to 5:30 PM\".")}]

p0, p1 = default_period()
st.session_state.setdefault("p_start", p0)
st.session_state.setdefault("p_end", p1)
st.session_state.setdefault("snap", None)   # {"image": bytes, "parsed": {...}, "raw": str}


def run_agent(prompt: str) -> str:
    with st.spinner("Working…"):
        result = st.session_state.agent(prompt)
    return result.message["content"][0]["text"]


def post_message(role: str, content: str):
    st.session_state.messages.append({"role": "user" if role == "user" else "assistant",
                                      "content": content})


# ---------- hero ----------
st.markdown(f"""
<div class="hero">
  <div class="logo">⏱️</div>
  <h1>ShiftSnap</h1>
  <p>Snap a timestamp photo. Get a perfect timesheet.</p>
  <div class="steps">
    <div class="step"><b>📸</b>Snap clock-in/out</div>
    <div class="step"><b>🤖</b>Agent reads & logs</div>
    <div class="step"><b>📊</b>Excel timesheet</div>
  </div>
</div>
""", unsafe_allow_html=True)

store = ShiftStore(str(DATA))

# ---------- snap card ----------
st.markdown('<div class="card"><h3>📸 Snap a timestamp</h3>'
            '<div class="sub">Upload a photo of your clock-in / clock-out screen — '
            'ShiftSnap reads the time and logs the punch.</div>',
            unsafe_allow_html=True)
upload = st.file_uploader("Snap a timestamp photo", type=["jpg", "jpeg", "png"],
                          label_visibility="collapsed", key="snap_upload")

if upload is not None and st.session_state.snap is None:
    img_bytes = upload.getvalue()
    with st.spinner("🔍 Reading timestamp…"):
        raw_text = extract_text(img_bytes, upload.name)
        parsed = parse_photo_timestamp(raw_text)
    if parsed:
        st.session_state.snap = {"image": img_bytes, "parsed": parsed, "raw": raw_text}
    else:
        st.error("Couldn't read a timestamp from that photo — make sure the time "
                 "overlay is clear and try again.")
        st.caption(f"OCR saw: {raw_text[:200]}" if raw_text else "OCR returned no text.")

snap = st.session_state.snap
if snap:
    p = snap["parsed"]
    dt = datetime.date.fromisoformat(p["date"])
    nice_date = dt.strftime("%a, %b %d, %Y")
    hh, mm = map(int, p["time"].split(":"))
    suffix = "AM" if hh < 12 else "PM"
    h12 = hh % 12 or 12
    open_now = bool(store.open_shifts())
    action = "CLOCK OUT" if open_now else "CLOCK IN"
    badge = "done" if open_now else "open"
    st.markdown(f"""
    <div class="snap-ok">
      <span class="badge {badge}">{action}</span>
      <div class="ts">{h12}:{mm:02d} {suffix}</div>
      <div class="dt">{nice_date}</div>
    </div>""", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    if c1.button("✅ Log this punch", key="snap_yes", use_container_width=True):
        msg = f"📸 Photo timestamp: \"{p['raw']}\" — log this punch."
        post_message("user", msg)
        reply = run_agent(msg)
        post_message("assistant", reply)
        st.session_state.snap = None
        st.rerun()
    if c2.button("🔄 Retake", key="snap_no", use_container_width=True):
        st.session_state.snap = None
        st.rerun()
st.markdown("</div>", unsafe_allow_html=True)

# ---------- stats ----------
s = store.summary(st.session_state.p_start.isoformat(),
                  st.session_state.p_end.isoformat())
st.markdown(f"""
<div class="section-t">This pay period</div>
<div class="stats">
  <div class="stat hl"><div class="v">{s['total_hours']}</div><div class="l">Total hours</div></div>
  <div class="stat"><div class="v">{s['approved_hours']}</div><div class="l">Approved (8h/d)</div></div>
  <div class="stat"><div class="v">{s['extra_hours']}</div><div class="l">Extra hours</div></div>
  <div class="stat"><div class="v">{s['days_worked']}</div><div class="l">Days worked</div></div>
</div>
""", unsafe_allow_html=True)
if s.get("open_shifts"):
    st.warning(f"⏳ {s['open_shifts']} shift(s) clocked in but not clocked out yet.")

# ---------- chat ----------
st.markdown('<div class="section-t">Chat with your agent</div>', unsafe_allow_html=True)
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("Type a shift, e.g. Sep 3, 9 AM to 5:30 PM…"):
    post_message("user", prompt)
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        reply = run_agent(prompt)
        st.markdown(reply)
    post_message("assistant", reply)
    st.rerun()

# ---------- timeline ----------
st.markdown('<div class="section-t">Your shifts</div>', unsafe_allow_html=True)
data = store.list_shifts()
if not data:
    st.markdown('<div class="card"><div class="empty">No shifts yet — snap your first timestamp above 📸</div></div>',
                unsafe_allow_html=True)
else:
    for date, shifts in sorted(data.items(), reverse=True):
        dt = datetime.date.fromisoformat(date)
        rows = []
        for sh in shifts:
            if sh.get("time_out"):
                brk = (f"<div style='font-size:.75rem;color:{MUTED}'>break "
                       f"{sh['break_start']}–{sh['break_end']}</div>"
                       if sh.get("break_start") else "")
                rows.append(
                    f"<div class='shift'><span class='badge done'>done</span>"
                    f"<div><div class='times'>{sh['time_in']} → {sh['time_out']}</div>{brk}</div>"
                    f"<div class='net'>{fmt_duration(net_minutes(sh))}</div></div>")
            else:
                rows.append(
                    f"<div class='shift'><span class='badge open'><span class='pulse'></span>open</span>"
                    f"<div><div class='times'>in {sh['time_in']}</div>"
                    f"<div style='font-size:.75rem;color:{MUTED}'>waiting for clock-out</div></div></div>")
        st.markdown(f"<div class='day'><div class='dhead'>{dt.strftime('%a, %b %d')}</div>"
                    + "".join(rows) + "</div>", unsafe_allow_html=True)

# ---------- pay period + excel ----------
st.markdown('<div class="section-t">Pay period & timesheet</div>', unsafe_allow_html=True)
st.markdown('<div class="card">', unsafe_allow_html=True)
c1, c2 = st.columns(2)
ns = c1.date_input("Start", st.session_state.p_start, key="pp_s")
ne = c2.date_input("End", st.session_state.p_end, key="pp_e")
if ns != st.session_state.p_start or ne != st.session_state.p_end:
    st.session_state.p_start, st.session_state.p_end = ns, ne
    st.rerun()
b1, b2 = st.columns(2)
if b1.button("📊 Summarize", use_container_width=True):
    reply = run_agent(f"Summarize my pay period from {ns} to {ne}.")
    post_message("user", f"Summarize {ns} to {ne}")
    post_message("assistant", reply)
    st.rerun()
if b2.button("📥 Build Excel", use_container_width=True):
    reply = run_agent(f"Generate my timesheet for {ns} to {ne}.")
    post_message("user", f"Generate timesheet {ns} to {ne}")
    post_message("assistant", reply)
    st.rerun()
xlsx = sorted(Path("timesheets").glob("*.xlsx"),
              key=lambda p: p.stat().st_mtime) if Path("timesheets").exists() else []
if xlsx:
    st.download_button("⬇️ Download latest timesheet", xlsx[-1].read_bytes(),
                       file_name=xlsx[-1].name, use_container_width=True)
st.markdown("</div>", unsafe_allow_html=True)
st.caption("ShiftSnap · your timesheet agent ⏱️")
