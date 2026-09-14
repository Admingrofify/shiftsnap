"""ShiftSnap v2 — Snap. Log. Get paid. Now multi-worker on Supabase.

Worker flow: pick your name -> Clock In/Out buttons (GPS) or snap a
timestamp photo -> agent logs it -> pay-period dashboard -> Excel export.

Admin flow: sidebar PIN -> team table, per-worker drill-down, team Excel.

Without SUPABASE_URL/SUPABASE_KEY env vars the app runs in single-worker
demo mode on a local JSON store.
"""
from __future__ import annotations

import datetime
import os

import streamlit as st

from src.agent import build_agent
from src.backend import get_store, supabase_configured
from src.ocr import extract_text, find_all_timestamps, parse_photo_timestamp
from src.sb_auth import (authed_client, consume_callback, current_user,
                         send_magic_link, sign_out)
from src.store import fmt_duration, net_minutes
from src.timesheet import generate_team_timesheet, generate_timesheet

st.set_page_config(page_title="ShiftSnap", page_icon="⏱️", layout="centered")

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp { background: #FAF7F2; }
.hero {
  background: linear-gradient(135deg, #0F766E 0%, #134E4A 60%, #1E293B 100%);
  border-radius: 20px; padding: 28px 24px; color: white; margin-bottom: 18px;
  box-shadow: 0 10px 30px rgba(15,118,110,.25);
}
.hero h1 { font-size: 1.7rem; font-weight: 800; margin: 0 0 6px 0; }
.hero p { opacity: .85; margin: 0; font-size: .95rem; }
.card { background: white; border-radius: 16px; padding: 18px;
        box-shadow: 0 2px 12px rgba(0,0,0,.06); margin-bottom: 14px; }
.card h3 { margin: 0 0 10px 0; font-size: 1.02rem; }
.stat { background: white; border-radius: 14px; padding: 14px 10px; text-align: center;
        box-shadow: 0 2px 12px rgba(0,0,0,.06); }
.stat .v { font-size: 1.35rem; font-weight: 800; color: #0F766E; }
.stat .l { font-size: .72rem; color: #64748B; text-transform: uppercase; letter-spacing: .04em; }
.punch { border-left: 4px solid #0F766E; background: white; border-radius: 12px;
         padding: 12px 14px; margin-bottom: 10px; box-shadow: 0 2px 10px rgba(0,0,0,.05); }
.punch.open { border-left-color: #F59E0B; }
.badge { display: inline-block; font-size: .72rem; font-weight: 700; border-radius: 999px;
         padding: 2px 10px; }
.badge.done { background: #D1FAE5; color: #065F46; }
.badge.open { background: #FEF3C7; color: #92400E; }
.badge.src { background: #E0F2F1; color: #0F766E; }
.stButton>button { border-radius: 12px; font-weight: 700; }
div[data-testid="stChatInput"] { border-radius: 14px; }
.worker-chip { background: #0F766E; color: white; border-radius: 999px;
               padding: 4px 14px; font-weight: 700; font-size: .85rem; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

SB = supabase_configured()


def get_gps() -> dict | None:
    """Browser GPS via streamlit-geolocation; None when unavailable/denied."""
    try:
        from streamlit_geolocation import streamlit_geolocation
        loc = streamlit_geolocation()
    except Exception:
        return None
    if not loc:
        return None
    lat, lng = loc.get("latitude") or 0, loc.get("longitude") or 0
    if not lat and not lng:
        return None
    return {"lat": lat, "lng": lng, "acc": loc.get("accuracy") or 0}


# ---------------------------------------------------------------- auth gate
# Free login: email magic link via Supabase Auth (no password, no cost).
# The worker's JWT scopes every query through Row Level Security.
def auth_gate():
    # Returning from the email link? ?token_hash=...&type=magiclink
    if st.query_params.get("token_hash") and not current_user():
        try:
            consume_callback()
            st.rerun()
        except Exception as exc:
            st.error(f"That login link didn't work ({exc}). Request a new one below.")
    if current_user():
        return
    st.markdown('<div class="hero"><h1>⏱️ ShiftSnap</h1>'
                "<p>Snap a timestamp. Log the shift. Get paid.</p></div>",
                unsafe_allow_html=True)
    st.markdown('<div class="card"><h3>🔑 Login — free, no password</h3>',
                unsafe_allow_html=True)
    st.caption("Enter your work email and we'll send you a one-tap login link.")
    email = st.text_input("Work email", placeholder="you@company.com")
    if st.button("📧 Send me a login link", type="primary",
                 use_container_width=True, disabled=not email.strip()):
        try:
            send_magic_link(email)
            st.success(f"Login link sent to {email.strip()} — check your inbox "
                       "(and spam). It expires in an hour.")
        except Exception as exc:
            st.error(f"Couldn't send the link: {exc}")
    st.markdown("</div>", unsafe_allow_html=True)
    st.caption("Your email only identifies your timesheet — nothing else. "
               "Supabase free tier; no personal data is sold or shared.")


if SB:
    auth_gate()  # stops here until logged in
    user = current_user()
    client = authed_client()
    if not client:
        sign_out()
        st.rerun()
    store = get_store()  # placeholder, replaced below with authed client
    from src.sb_store import SupabaseShiftStore
    store = SupabaseShiftStore(employee_id=user["id"], client=client)
    if "worker" not in st.session_state:
        # First login: pick a display name for the timesheet.
        st.markdown('<div class="hero"><h1>⏱️ ShiftSnap</h1>'
                    "<p>One last step.</p></div>", unsafe_allow_html=True)
        st.markdown('<div class="card"><h3>👋 What should we call you?</h3>',
                    unsafe_allow_html=True)
        dname = st.text_input("Display name",
                              placeholder="e.g. Jordan Lee",
                              value=user["email"].split("@")[0])
        if st.button("Start →", type="primary", use_container_width=True,
                     disabled=not dname.strip()):
            st.session_state.worker = store.ensure_worker(dname.strip(),
                                                           user["email"])
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
        st.stop()
    worker = st.session_state.worker
    worker_label = worker["name"]
    is_admin = store.is_admin()
else:
    store = get_store()  # JSON demo mode
    worker = None
    worker_label = "Jordan Lee (demo)"
    is_admin = False


def _agent():
    key = f"agent_{worker_label}"
    if key not in st.session_state:
        wid = worker["id"] if SB and worker else None
        st.session_state[key] = build_agent(worker_id=wid)
    return st.session_state[key]


def ask_agent(text: str) -> str:
    try:
        return str(_agent()(text)).strip()
    except Exception as exc:
        return f"Something went wrong: {exc}"


def store_punch(p, source="photo"):
    kw = {"comment": f"{source} {p['raw']}", "source": source}
    if SB and worker:
        kw["employee_id"] = worker["id"]
    store.punch(p["date"], p["time"], **kw)


# ------------------------------------------------------------------ pay period
today = datetime.date.today()
if today.day <= 15:
    d_start, d_end = today.replace(day=1), today.replace(day=15)
else:
    d_start, d_end = today.replace(day=16), today

with st.sidebar:
    st.markdown("### 📅 Pay period")
    p_start = st.date_input("Start", d_start)
    p_end = st.date_input("End", d_end)
    if SB:
        st.markdown("---")
        st.markdown(f"👤 **{worker_label}**")
        st.caption(user["email"])
        if st.button("🚪 Logout", use_container_width=True):
            sign_out()
            st.rerun()
        st.session_state.is_admin = is_admin

S, E = p_start.isoformat(), p_end.isoformat()

# ------------------------------------------------------------------ admin view
if SB and st.session_state.get("is_admin"):
    st.markdown('<div class="hero"><h1>🛡️ Team overview</h1>'
                "<p>Everyone's hours for the pay period.</p></div>",
                unsafe_allow_html=True)
    team = store.team_summary(S, E)
    if team:
        st.dataframe(
            [{"Worker": t["worker"], "Days": t["days_worked"],
              "Total": t["total_hours"], "Approved": t["approved_hours"],
              "Extra": t["extra_hours"],
              "⚠️ open": t["open_shifts"]} for t in team],
            use_container_width=True, hide_index=True)
        if st.button("📥 Download team Excel", type="primary"):
            path = generate_team_timesheet(S, E, store)
            with open(path, "rb") as f:
                st.download_button(
                    "Save Team_Timesheet.xlsx", f,
                    file_name=path.split("/")[-1],
                    mime="application/vnd.openxmlformats-officedocument."
                         "spreadsheetml.sheet")
    else:
        st.info("No shifts logged in this period yet.")
    st.stop()

# ------------------------------------------------------------------ worker UI
summary = store.summary(S, E)
open_now = store.open_shifts()

st.markdown(
    f'<div class="hero"><h1>⏱️ ShiftSnap</h1>'
    f"<p><span class='worker-chip'>{worker_label}</span></p>"
    f"<p style='margin-top:8px'>Snap a timestamp. Log the shift. Get paid.</p></div>",
    unsafe_allow_html=True)

# Clock in / out buttons -------------------------------------------------------
st.markdown('<div class="card"><h3>📍 Clock in / out</h3>', unsafe_allow_html=True)
gps = get_gps()
gps_note = ("🛰️ GPS attached" if gps else
            "📵 no GPS — allow location for site verification")
c1, c2 = st.columns(2)
with c1:
    if st.button("🟢 Clock In", use_container_width=True, type="primary"):
        tail = (f" lat={gps['lat']} lng={gps['lng']} acc={gps['acc']}"
                if gps else "")
        st.session_state.flash = ask_agent(f"Clock me in{tail}")
        st.rerun()
with c2:
    if st.button("🔴 Clock Out", use_container_width=True):
        tail = (f" lat={gps['lat']} lng={gps['lng']} acc={gps['acc']}"
                if gps else "")
        st.session_state.flash = ask_agent(f"Clock me out{tail}")
        st.rerun()
st.caption(gps_note)
if st.session_state.get("flash"):
    st.success(st.session_state.pop("flash"))
st.markdown("</div>", unsafe_allow_html=True)

if open_now:
    o = open_now[0]
    st.warning(f"⏳ You're clocked in since {o['date']} {o['time_in']} — "
               "don't forget to clock out!")

# Stat tiles -------------------------------------------------------------------
a, b, c, d = st.columns(4)
for col, v, l in ((a, summary["total_hours"], "Total"),
                  (b, summary["approved_hours"], "Approved"),
                  (c, summary["extra_hours"], "Extra"),
                  (d, str(summary["days_worked"]), "Days")):
    col.markdown(f'<div class="stat"><div class="v">{v}</div>'
                 f'<div class="l">{l}</div></div>', unsafe_allow_html=True)
st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

# Photo snap -------------------------------------------------------------------
st.markdown('<div class="card"><h3>📸 Snap a timestamp photo</h3>',
            unsafe_allow_html=True)
photo = st.file_uploader("Upload a clock-in/out timestamp photo",
                         type=["jpg", "jpeg", "png", "webp"], key="snap")
if photo and not st.session_state.get(f"snapped_{photo.name}"):
    with st.spinner("Reading timestamp…"):
        parsed = parse_photo_timestamp(extract_text(photo.getvalue()))
    if parsed:
        st.session_state.pending_punch = parsed
    else:
        st.error("Couldn't read a timestamp — try a clearer shot of the time overlay.")
    st.session_state[f"snapped_{photo.name}"] = True

pp = st.session_state.get("pending_punch")
if pp:
    action = "CLOCK OUT" if open_now else "CLOCK IN"
    st.info(f"🕒 Found **{pp['date']} {pp['time']}** → this will **{action}**.")
    cc1, cc2 = st.columns(2)
    with cc1:
        if st.button(f"✅ Confirm {action}", type="primary",
                     use_container_width=True):
            store_punch(pp)
            st.session_state.pop("pending_punch")
            st.success(f"{action.title()} confirmed: {pp['date']} {pp['time']}.")
            st.rerun()
    with cc2:
        if st.button("🔁 Retake", use_container_width=True):
            st.session_state.pop("pending_punch")
            st.rerun()
st.markdown("</div>", unsafe_allow_html=True)

# Weekly import ----------------------------------------------------------------
st.markdown('<div class="card"><h3>🧾 Import weekly timesheet photo</h3>',
            unsafe_allow_html=True)
imp = st.file_uploader("Upload a photo of a weekly timesheet",
                       type=["jpg", "jpeg", "png", "webp"], key="import")
if imp and not st.session_state.get(f"imported_{imp.name}"):
    with st.spinner("Scanning for timestamps…"):
        st.session_state.import_found = find_all_timestamps(
            extract_text(imp.getvalue()))
    st.session_state[f"imported_{imp.name}"] = True

found = st.session_state.get("import_found")
if found:
    st.write(f"Found **{len(found)}** timestamps — uncheck any to skip:")
    picks = [st.checkbox(f"{p['date']}  {p['time']}", value=True, key=f"imp_{i}")
             for i, p in enumerate(found)]
    chosen = [p for p, on in zip(found, picks) if on]
    if st.button(f"✅ Log {len(chosen)} punches", type="primary",
                 disabled=not chosen):
        n = 0
        for p in chosen:
            try:
                store_punch(p)
                n += 1
            except Exception:
                pass
        st.session_state.pop("import_found")
        st.success(f"Logged {n} punch(es).")
        st.rerun()
elif imp:
    st.warning("No readable timestamps in that photo.")
st.markdown("</div>", unsafe_allow_html=True)

# Chat -------------------------------------------------------------------------
st.markdown('<div class="card"><h3>💬 Tell the agent</h3>', unsafe_allow_html=True)
st.caption('e.g. "Sep 3, 9 AM to 5:30 PM, break 12–12:30 PM" · '
           '"summarize Sep 1–15" · "make my timesheet"')
if "chat" not in st.session_state:
    st.session_state.chat = []
for m in st.session_state.chat[-12:]:
    with st.chat_message(m["role"]):
        st.write(m["text"])
if prompt := st.chat_input("Log a shift, ask for a summary…"):
    st.session_state.chat.append({"role": "user", "text": prompt})
    with st.chat_message("user"):
        st.write(prompt)
    with st.chat_message("assistant"):
        with st.spinner("…"):
            reply = ask_agent(prompt)
        st.write(reply)
    st.session_state.chat.append({"role": "assistant", "text": reply})
    if "timesheet" in prompt.lower() or "excel" in prompt.lower():
        try:
            path = generate_timesheet(S, E, store)
            with open(path, "rb") as f:
                st.download_button(
                    "📥 Download Excel timesheet", f,
                    file_name=path.split("/")[-1],
                    mime="application/vnd.openxmlformats-officedocument."
                         "spreadsheetml.sheet")
        except Exception as exc:
            st.error(f"Excel failed: {exc}")
st.markdown("</div>", unsafe_allow_html=True)

# Timeline ---------------------------------------------------------------------
st.markdown('<div class="card"><h3>🗓️ Shifts</h3>', unsafe_allow_html=True)
data = store.list_shifts(S, E)
if not data:
    st.caption("Nothing logged in this period yet — clock in to start.")
for date in sorted(data, reverse=True):
    for s in data[date]:
        done = bool(s.get("time_out"))
        badge = ('<span class="badge done">done</span>' if done
                 else '<span class="badge open">clocked in</span>')
        src = s.get("source") or "chat"
        src_badge = f'<span class="badge src">{src}</span>'
        brk = (f" · break {s['break_start']}–{s['break_end']}"
               if s.get("break_start") else "")
        gps_b = " 📍" if s.get("lat") else ""
        when = (f"{s['time_in']} → {s['time_out']}"
                if done else f"{s['time_in']} → …")
        st.markdown(
            f'<div class="punch{" open" if not done else ""}">'
            f"<b>{date}</b> · {when}{brk} · "
            f"<b>{fmt_duration(net_minutes(s))}</b>{gps_b} {badge} {src_badge}"
            f"</div>", unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

# Export -----------------------------------------------------------------------
st.markdown('<div class="card"><h3>📥 Timesheet</h3>', unsafe_allow_html=True)
if st.button("Generate my Excel timesheet", type="primary",
             use_container_width=True):
    try:
        path = generate_timesheet(S, E, store)
        with open(path, "rb") as f:
            st.download_button(
                "📥 Download Excel timesheet", f,
                file_name=path.split("/")[-1],
                mime="application/vnd.openxmlformats-officedocument."
                     "spreadsheetml.sheet")
        st.success(f"{summary['days_worked']} day(s) · {summary['total_hours']} "
                   f"total · {summary['approved_hours']} approved · "
                   f"{summary['extra_hours']} extra")
    except Exception as exc:
        st.error(f"Excel failed: {exc}")
st.markdown("</div>", unsafe_allow_html=True)
