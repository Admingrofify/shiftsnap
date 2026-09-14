"""ShiftSnap v2 — multi-worker timesheets.

Free login via Supabase Auth (email magic link). GPS-stamped Clock In/Out,
weekly photo import, per-worker pay rates, Excel exports with pay, and an
admin team view — all scoped by Row Level Security.
"""
import calendar
import os
from datetime import date, datetime

import streamlit as st
from streamlit_geolocation import streamlit_geolocation

from src.agent import build_agent
from src.backend import get_store, supabase_configured
from src.ocr import extract_text, find_all_timestamps, parse_photo_timestamp
from src.sb_auth import (authed_client, consume_callback, current_user,
                         send_magic_link, sign_out)
from src.store import fmt_duration, net_minutes
from src.timesheet import generate_team_timesheet, generate_timesheet

SB = supabase_configured()

st.set_page_config(page_title="ShiftSnap", page_icon="⏱️", layout="centered")

# ------------------------------------------------------------------ styling
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"] { font-family: 'Inter', system-ui, sans-serif; }
.stApp { background: #f4f6fb; }
.block-container { padding-top: 1.2rem; max-width: 720px; }

.hero {
  background: linear-gradient(120deg, #0b1f3a 0%, #123a63 55%, #0e7c6b 130%);
  border-radius: 22px; padding: 30px 26px; color: #fff;
  box-shadow: 0 12px 32px rgba(11,31,58,.25); margin-bottom: 18px;
}
.hero h1 { font-size: 30px; font-weight: 800; margin: 0 0 4px; letter-spacing: -.5px; }
.hero p { margin: 0; opacity: .85; font-size: 14px; }
.hero .status-pill {
  display: inline-block; margin-top: 12px; padding: 6px 14px; border-radius: 999px;
  font-size: 13px; font-weight: 600; background: rgba(255,255,255,.16);
  backdrop-filter: blur(4px);
}
.hero .status-pill.on { background: #22c55e; color: #06281c; }
.hero .status-pill.off { background: rgba(255,255,255,.16); }

.card {
  background: #fff; border-radius: 18px; padding: 20px;
  box-shadow: 0 4px 18px rgba(15,30,60,.07); margin-bottom: 14px;
  border: 1px solid #e8edf5;
}
.card h3 { margin: 0 0 10px; font-size: 16px; font-weight: 700; color: #0b1f3a; }

.stat-row { display: flex; gap: 10px; }
.stat {
  flex: 1; background: #fff; border-radius: 16px; padding: 14px 12px;
  border: 1px solid #e8edf5; text-align: center;
  box-shadow: 0 4px 14px rgba(15,30,60,.05);
}
.stat .v { font-size: 22px; font-weight: 800; color: #0b1f3a; }
.stat .l { font-size: 11px; color: #6b7a90; font-weight: 600; text-transform: uppercase; letter-spacing: .5px; }
.stat .v.green { color: #0e7c6b; }

div.stButton > button[kind="primary"] {
  background: linear-gradient(120deg, #0e7c6b, #12a48f);
  border: none; border-radius: 14px; font-weight: 700; font-size: 16px;
  padding: 14px; box-shadow: 0 8px 20px rgba(14,124,107,.35);
}
div.stButton > button:not([kind="primary"]) {
  border-radius: 14px; font-weight: 600; border: 1.5px solid #dbe3f0;
}
div.stButton > button { width: 100%; }

section[data-testid="stSidebar"] { background: #0b1f3a; }
section[data-testid="stSidebar"] .stRadio label,
section[data-testid="stSidebar"] .stMarkdown,
section[data-testid="stSidebar"] p { color: #dbe6f5 !important; }
section[data-testid="stSidebar"] .stRadio div[role="radiogroup"] label {
  background: rgba(255,255,255,.06); border-radius: 12px; padding: 10px 14px;
  margin-bottom: 6px; font-weight: 600;
}
.avatar {
  width: 44px; height: 44px; border-radius: 50%;
  background: linear-gradient(135deg, #0e7c6b, #34d399);
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-weight: 800; font-size: 18px;
}
.profile-head { display: flex; gap: 12px; align-items: center; margin-bottom: 14px; }
.small { font-size: 12px; color: #6b7a90; }
table { font-size: 13px; }
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------ helpers
def pay_period(d: date):
    if d.day <= 15:
        return date(d.year, d.month, 1), date(d.year, d.month, 15)
    last = calendar.monthrange(d.year, d.month)[1]
    return date(d.year, d.month, 16), date(d.year, d.month, last)


def period_options():
    today = date.today()
    cur = pay_period(today)
    prev_end = cur[0].toordinal() - 1
    prev_end_d = date.fromordinal(prev_end)
    prev = pay_period(prev_end_d)
    first = date(today.year, today.month, 1)
    last = calendar.monthrange(today.year, today.month)[1]
    return {
        f"Current pay period ({cur[0].strftime('%b %-d')}–{cur[1].strftime('%b %-d')})": cur,
        f"Previous pay period ({prev[0].strftime('%b %-d')}–{prev[1].strftime('%b %-d')})": prev,
        f"This month ({first.strftime('%b %-d')}–{date(today.year, today.month, last).strftime('%b %-d')})":
            (first, date(today.year, today.month, last)),
        "Custom…": None,
    }


def gps_kwargs():
    loc = streamlit_geolocation()
    if loc and loc.get("latitude") and loc.get("longitude"):
        return {"lat": loc["latitude"], "lng": loc["longitude"],
                "accuracy": loc.get("accuracy")}
    return {}


def store_punch(kind: str, **kw):
    now = datetime.now().strftime("%H:%M")
    today = date.today().isoformat()
    kw.setdefault("source", "button")
    if kind == "in":
        store.add_punch(today, now, None, **kw)
    else:
        open_shifts = [s for s in store.list_shifts(today, today)
                       if not s.get("time_out")]
        if open_shifts:
            s = open_shifts[-1]
            store.update_punch(today, s["time_in"], time_out=now, **kw)
        else:
            store.add_punch(today, None, now, **kw)


# ------------------------------------------------------------------ auth
def login_screen():
    st.markdown('<div class="hero"><h1>⏱️ ShiftSnap</h1>'
                "<p>Snap a timestamp. Log the shift. Get paid.</p></div>",
                unsafe_allow_html=True)
    st.markdown('<div class="card"><h3>🔑 Login — free, no password</h3>',
                unsafe_allow_html=True)
    st.caption("Enter your work email and we'll send you a one-tap login link.")
    email = st.text_input("Work email", placeholder="you@company.com")
    if st.button("Send me a login link", type="primary",
                 disabled=not email.strip()):
        try:
            send_magic_link(email)
            st.success(f"Login link sent to {email.strip()} — check your inbox. "
                       "It expires in an hour.")
        except Exception as exc:
            st.error(f"Couldn't send the link: {exc}")
    st.markdown("</div>", unsafe_allow_html=True)
    st.caption("Your email only identifies your timesheet. Free tier — "
               "nothing is sold or shared.")


if SB:
    if st.query_params.get("token_hash") and not current_user():
        try:
            consume_callback()
            st.rerun()
        except Exception as exc:
            st.error(f"That login link didn't work ({exc}). Request a new one.")
    if not current_user():
        login_screen()
        st.stop()

    user = current_user()
    client = authed_client()
    if not client:
        sign_out()
        st.rerun()
    from src.sb_store import SupabaseShiftStore
    store = SupabaseShiftStore(employee_id=user["id"], client=client)

    if "worker" not in st.session_state:
        st.markdown('<div class="hero"><h1>⏱️ ShiftSnap</h1>'
                    "<p>One last step.</p></div>", unsafe_allow_html=True)
        st.markdown('<div class="card"><h3>👋 What should we call you?</h3>',
                    unsafe_allow_html=True)
        dname = st.text_input("Display name", placeholder="e.g. Jordan Lee",
                              value=user["email"].split("@")[0])
        if st.button("Start →", type="primary", disabled=not dname.strip()):
            st.session_state.worker = store.ensure_worker(dname.strip(),
                                                           user["email"])
            st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
        st.stop()
    worker = st.session_state.worker
    is_admin = store.is_admin()
    hourly_rate = worker.get("hourly_rate")
else:
    store = get_store()
    worker = {"id": None, "name": "Jordan Lee (demo)", "email": ""}
    user = {"email": "demo"}
    is_admin = False
    hourly_rate = None

worker_name = worker["name"]

# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.markdown(f"""
    <div class="profile-head">
      <div class="avatar">{worker_name[:1].upper()}</div>
      <div><div style="font-weight:700;color:#fff;">{worker_name}</div>
      <div class="small" style="color:#8fa3c2;">{user.get('email', '')}</div></div>
    </div>""", unsafe_allow_html=True)
    pages = ["⏱ Clock", "📅 Timesheet", "📸 Import Photo", "💬 Ask", "👤 Profile"]
    if is_admin:
        pages.append("🛠 Team")
    page = st.radio("Navigate", pages, label_visibility="collapsed")
    st.markdown("---")
    if SB and st.button("🚪 Logout"):
        sign_out()
        st.rerun()

# ------------------------------------------------------------------ CLOCK
if page == "⏱ Clock":
    open_shift = store.open_shift()
    if open_shift:
        pill = (f'<span class="status-pill on">🟢 Clocked in since '
                f'{open_shift["time_in"]}</span>')
    else:
        pill = '<span class="status-pill off">⚪ Not clocked in</span>'
    st.markdown(f'<div class="hero"><h1>⏱️ ShiftSnap</h1>'
                f"<p>{worker_name} · {date.today().strftime('%A, %b %-d')}</p>"
                f"{pill}</div>", unsafe_allow_html=True)

    st.markdown('<div class="card"><h3>📍 Clock in / out</h3>',
                unsafe_allow_html=True)
    st.caption("Your location is captured automatically with each punch.")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🟢 Clock In", type="primary",
                     disabled=bool(open_shift)):
            store_punch("in", **gps_kwargs())
            st.rerun()
    with c2:
        if st.button("🔴 Clock Out", disabled=not bool(open_shift)):
            store_punch("out", **gps_kwargs())
            st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    # today at a glance
    today = date.today().isoformat()
    todays = store.list_shifts(today, today)
    mins = sum(net_minutes(s) for s in todays if s.get("time_out"))
    pay = round(mins / 60 * (hourly_rate or 0), 2) if hourly_rate else None
    st.markdown('<div class="stat-row">', unsafe_allow_html=True)
    st.markdown(f'<div class="stat"><div class="v">{fmt_duration(mins)}</div>'
                '<div class="l">Today</div></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="stat"><div class="v">{len(todays)}</div>'
                '<div class="l">Punches</div></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="stat"><div class="v green">'
                f'{"$" + f"{pay:,.2f}" if pay is not None else "—"}</div>'
                '<div class="l">Est. pay</div></div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
    if not hourly_rate and SB:
        st.caption("💡 Set your hourly pay in 👤 Profile to see earnings.")

# ------------------------------------------------------------------ TIMESHEET
elif page == "📅 Timesheet":
    st.markdown(f'<div class="hero"><h1>📅 Timesheet</h1>'
                f"<p>{worker_name}</p></div>", unsafe_allow_html=True)
    opts = period_options()
    choice = st.selectbox("Period", list(opts.keys()))
    rng = opts[choice]
    if rng is None:
        c1, c2 = st.columns(2)
        with c1:
            s = st.date_input("Start", value=pay_period(date.today())[0])
        with c2:
            e = st.date_input("End", value=date.today())
        rng = (s, e)
    start, end = rng[0].isoformat(), rng[1].isoformat()

    summ = store.summary(start, end)
    pay = round(summ["total_decimal"] * (hourly_rate or 0), 2)
    st.markdown('<div class="stat-row">', unsafe_allow_html=True)
    st.markdown(f'<div class="stat"><div class="v">{summ["total_hours"]}</div>'
                '<div class="l">Hours</div></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="stat"><div class="v">{summ["days_worked"]}</div>'
                '<div class="l">Days</div></div>', unsafe_allow_html=True)
    st.markdown(f'<div class="stat"><div class="v green">${pay:,.2f}</div>'
                '<div class="l">Est. pay</div></div>', unsafe_allow_html=True)
    st.markdown('</div><div style="height:12px"></div>', unsafe_allow_html=True)

    rows = []
    for d, shifts in sorted(store.list_shifts(start, end).items()):
        for s in shifts:
            mins = net_minutes(s) if s.get("time_out") else 0
            rows.append({
                "Date": d, "In": s.get("time_in") or "—",
                "Out": s.get("time_out") or "—",
                "Break": (f"{s['break_start']}–{s['break_end']}"
                          if s.get("break_start") else "—"),
                "Hours": fmt_duration(mins),
                "Pay": f"${mins / 60 * (hourly_rate or 0):,.2f}"
                       if hourly_rate else "—",
                "Note": s.get("comment", ""),
            })
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("No shifts in this period yet.")

    st.markdown('<div class="card"><h3>📥 Export Excel</h3>',
                unsafe_allow_html=True)
    st.caption("Generates your timesheet workbook with hours and pay.")
    if st.button("Generate Excel", type="primary"):
        if SB:
            path = generate_timesheet(start, end, store, worker_name,
                                      hourly_rate)
        else:
            path = generate_timesheet(start, end, store)
        with open(path, "rb") as f:
            st.download_button("⬇️ Download timesheet",
                               data=f.read(),
                               file_name=os.path.basename(path),
                               mime="application/vnd.openxmlformats-"
                                    "officedocument.spreadsheetml.sheet")
    st.markdown("</div>", unsafe_allow_html=True)

# ------------------------------------------------------------------ IMPORT
elif page == "📸 Import Photo":
    st.markdown('<div class="hero"><h1>📸 Import Photo</h1>'
                "<p>Weekly timestamp photos → your timesheet.</p></div>",
                unsafe_allow_html=True)
    st.markdown('<div class="card"><h3>Upload a timestamp photo</h3>',
                unsafe_allow_html=True)
    up = st.file_uploader("Timestamp photo", type=["png", "jpg", "jpeg", "webp"])
    if up:
        st.image(up, use_container_width=True)
        if st.button("🔎 Read timestamps", type="primary"):
            with st.spinner("Reading photo…"):
                data = up.getvalue()
                text = extract_text(data)
                stamps = find_all_timestamps(text)
            st.session_state.photo_stamps = stamps
            st.session_state.photo_bytes = data
        stamps = st.session_state.get("photo_stamps", [])
        if stamps:
            st.success(f"Found {len(stamps)} timestamp(s). Review before saving:")
            for i, p in enumerate(stamps):
                c1, c2, c3 = st.columns([2, 2, 1])
                with c1:
                    d = st.date_input("Date", value=p["date"].date()
                                      if hasattr(p["date"], "date") else p["date"],
                                      key=f"pd{i}")
                with c2:
                    t = st.time_input("Time",
                                      value=datetime.strptime(p["time"], "%H:%M").time()
                                      if len(p["time"]) == 5
                                      else datetime.strptime(p["time"], "%H:%M:%S").time(),
                                      key=f"pt{i}")
                with c3:
                    st.write("")
                    keep = st.checkbox("Keep", value=True, key=f"pk{i}")
                p["_date"], p["_time"], p["_keep"] = d, t, keep
            if st.button("💾 Save to timesheet", type="primary"):
                saved = 0
                for p in stamps:
                    if p.get("_keep", True):
                        store.add_punch(p["_date"].isoformat(),
                                        p["_time"].strftime("%H:%M"), None,
                                        source="photo")
                        saved += 1
                st.success(f"Saved {saved} punch(es). Review pairs in Timesheet.")
                st.session_state.pop("photo_stamps", None)
    st.markdown("</div>", unsafe_allow_html=True)

# ------------------------------------------------------------------ ASK
elif page == "💬 Ask":
    st.markdown('<div class="hero"><h1>💬 Ask ShiftSnap</h1>'
                "<p>Type naturally — “I worked 9 to 5”, “show my week”.</p></div>",
                unsafe_allow_html=True)

    def _agent():
        return build_agent(worker_id=worker["id"] if SB else None)

    if "chat" not in st.session_state:
        st.session_state.chat = []
    for m in st.session_state.chat:
        with st.chat_message(m["role"]):
            st.markdown(m["text"])
    if prompt := st.chat_input("Log a shift, ask about your hours…"):
        st.session_state.chat.append({"role": "user", "text": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("…"):
                try:
                    reply = _agent().chat(prompt)
                except Exception as exc:
                    reply = f"Something went wrong: {exc}"
            st.markdown(reply)
        st.session_state.chat.append({"role": "assistant", "text": reply})

# ------------------------------------------------------------------ PROFILE
elif page == "👤 Profile":
    st.markdown('<div class="hero"><h1>👤 Profile</h1>'
                f"<p>{worker_name}</p></div>", unsafe_allow_html=True)
    st.markdown('<div class="card"><h3>Your details</h3>', unsafe_allow_html=True)
    st.text_input("Email", value=user.get("email", ""), disabled=True)
    new_name = st.text_input("Display name", value=worker_name)
    new_rate = st.number_input("Hourly pay ($/hr)", min_value=0.0, step=0.5,
                               value=float(hourly_rate or 0.0),
                               help="Your pay rate — used for pay estimates and Excel exports.")
    if st.button("💾 Save profile", type="primary"):
        if SB:
            st.session_state.worker = store.update_worker_profile(
                new_name, new_rate or None)
            st.success("Profile saved.")
            st.rerun()
        else:
            st.info("Demo mode — profile saving needs Supabase.")
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown('<div class="card"><h3>🔒 Privacy</h3>', unsafe_allow_html=True)
    st.caption("Only your punches, name and pay rate are stored — visible to "
               "you and your admin. Nothing is sold or shared.")
    st.markdown("</div>", unsafe_allow_html=True)

# ------------------------------------------------------------------ TEAM (admin)
elif page == "🛠 Team":
    if not is_admin:
        st.error("Admins only.")
        st.stop()
    st.markdown('<div class="hero"><h1>🛠 Team</h1>'
                "<p>Everyone's hours & pay.</p></div>", unsafe_allow_html=True)
    opts = period_options()
    choice = st.selectbox("Period", list(opts.keys()), key="team_period")
    rng = opts[choice]
    if rng is None:
        c1, c2 = st.columns(2)
        with c1:
            s = st.date_input("Start", value=pay_period(date.today())[0],
                              key="ts")
        with c2:
            e = st.date_input("End", value=date.today(), key="te")
        rng = (s, e)
    start, end = rng[0].isoformat(), rng[1].isoformat()

    team = store.team_summary(start, end)
    if team:
        rows = []
        for t in team:
            rate = t.get("hourly_rate") or 0
            pay = round(t["total_decimal"] * rate, 2)
            rows.append({"Worker": t["worker"], "Days": t["days_worked"],
                         "Hours": t["total_hours"], "Rate": f"${rate}/h",
                         "Est. pay": f"${pay:,.2f}",
                         "Extra": t["extra_hours"]})
        st.dataframe(rows, use_container_width=True, hide_index=True)
        if st.button("📥 Generate team Excel", type="primary"):
            path = generate_team_timesheet(start, end, store)
            with open(path, "rb") as f:
                st.download_button("⬇️ Download team timesheet",
                                   data=f.read(),
                                   file_name=os.path.basename(path),
                                   mime="application/vnd.openxmlformats-"
                                        "officedocument.spreadsheetml.sheet")
    else:
        st.info("No shifts in this period.")
