"""Supabase Auth (email + password) helpers for the Streamlit app.

Why password instead of magic link: Supabase's built-in email service is
rate-limited to a trickle and meant for testing only, so magic links break
under real usage. Email+password with "Confirm email" DISABLED in the
dashboard (Authentication > Settings) sends zero emails — no limits, no
SMTP setup, free forever.

Flow:
  1. Worker enters work email + password, taps "Login / Sign up".
  2. First tap creates the account (min 6 chars), later taps sign in.
  3. The session JWT is stored in st.session_state AND in a browser
     cookie ("shiftsnap_session"), so a page reload keeps the worker
     logged in. authed_client() returns a supabase client carrying it,
     so every query is scoped by Row Level Security to that worker.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

APP_URL = os.getenv("APP_URL", "https://shiftssnap.com")

COOKIE_NAME = "shiftsnap_session"
COOKIE_DAYS = 30


def _env(key: str, *alts: str) -> str:
    for k in (key, *alts):
        v = os.getenv(k, "")
        if v:
            return v
    return ""


def supabase_url() -> str:
    return _env("SUPABASE_URL")


def anon_key() -> str:
    # Accept SUPABASE_ANON_KEY; fall back to SUPABASE_KEY for older setups.
    return _env("SUPABASE_ANON_KEY", "SUPABASE_KEY")


def get_anon_client():
    from supabase import create_client
    url, key = supabase_url(), anon_key()
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_ANON_KEY are required.")
    return create_client(url, key)


def _cookie_manager(key: str = "ss_init"):
    # CookieManager reads the browser's cookies into self.cookies only when
    # its iframe first mounts, and the iframe reports that value exactly
    # once. A stable key therefore gives a trustworthy one-shot read after
    # a page reload (fresh mount), but the value then goes stale for the
    # rest of the session — never treat it as live. Fresh keys are used
    # below whenever a write must actually reach the browser.
    from extra_streamlit_components import CookieManager
    return CookieManager(key=key)


def _cookie_nonce() -> int:
    """Monotonic counter so each cookie write mounts a fresh iframe."""
    import streamlit as st
    n = int(st.session_state.get("_ss_ck_nonce", 0)) + 1
    st.session_state["_ss_ck_nonce"] = n
    return n


def _save_session(res) -> dict:
    import streamlit as st
    if not res.session or not res.user:
        raise RuntimeError(
            "No session returned. The Supabase project likely still has "
            "'Confirm email' enabled — turn it off under "
            "Authentication > Settings.")
    sess = {
        "access_token": res.session.access_token,
        "refresh_token": res.session.refresh_token,
        "user_id": res.user.id,
        "email": res.user.email,
    }
    st.session_state.sb_session = sess
    # Fresh login: allow the cookie to be (re)written and make sure a
    # previous in-session logout doesn't block this session.
    st.session_state["_ss_logged_out"] = False
    st.session_state["_ss_cookie_ok"] = False
    # NOTE: the cookie itself is written by persist_session_cookie() during
    # a normal render. Writing it here would race with the st.rerun() that
    # follows login, and the browser might never execute it.
    return {"id": res.user.id, "email": res.user.email}


def _parse_session_cookie(raw):
    """Parse the session cookie.

    universal-cookie JSON-parses cookie values on read, so the session
    cookie comes back as a dict; accept a raw JSON string too.
    Returns the session dict, or None when there is no usable session.
    """
    if isinstance(raw, dict):
        sess = raw
    elif isinstance(raw, str) and raw:
        try:
            sess = json.loads(raw)
        except Exception:
            return None
    else:
        return None
    if isinstance(sess, dict) and sess.get("refresh_token"):
        return sess
    return None


def persist_session_cookie() -> None:
    """Write the login cookie once per login.

    Called on every script run, but the write itself happens exactly once:
    a fresh component key mounts a fresh iframe whose mount effect writes
    document.cookie, then _ss_cookie_ok gates every later run. (Re-rendering
    the same key would reuse the mounted iframe and never re-fire the
    write, which is why logout/login cycles need fresh keys.)
    """
    import streamlit as st
    sess = st.session_state.get("sb_session")
    if not sess:
        return
    if st.session_state.get("_ss_cookie_ok"):
        return  # already written for this login
    try:
        cm = _cookie_manager(key=f"ss_init_w_{_cookie_nonce()}")
        payload = json.dumps({
            "access_token": sess.get("access_token"),
            "refresh_token": sess.get("refresh_token"),
            "user_id": sess.get("user_id"),
            "email": sess.get("email"),
        })
        cm.set(
            COOKIE_NAME, payload,
            expires_at=datetime.now() + timedelta(days=COOKIE_DAYS),
            path="/", same_site="strict",
            key=f"ss_set_{_cookie_nonce()}")
        st.session_state["_ss_cookie_ok"] = True
    except Exception:
        pass


def restore_session() -> None:
    """Restore a persisted login from the cookie after a page reload.

    The "ss_init" iframe reads document.cookie when it mounts (which is
    exactly what a full page reload does) and reports once; the rerun it
    triggers then picks the session up. Within a session the value is
    never re-read, so a logout can never resurrect a stale session here —
    sign_out() additionally sets _ss_logged_out as a hard guard.
    """
    import streamlit as st
    if st.session_state.get("sb_session"):
        return
    if st.session_state.get("_ss_logged_out"):
        return  # signed out in this session: stay signed out
    try:
        raw = _cookie_manager().get(COOKIE_NAME)
    except Exception:
        return
    sess = _parse_session_cookie(raw)
    if sess:
        st.session_state.sb_session = sess


def sign_up_or_in(email: str, password: str) -> dict:
    """Login; creates the account on first use. Returns the user dict."""
    email = email.strip()
    if len(password) < 6:
        raise ValueError("Password needs at least 6 characters.")
    client = get_anon_client()
    try:
        res = client.auth.sign_in_with_password(
            {"email": email, "password": password})
        return _save_session(res)
    except Exception as signin_err:
        # Probably a new worker — create the account, then we're logged in.
        try:
            res = client.auth.sign_up({"email": email, "password": password})
            return _save_session(res)
        except Exception:
            # Sign-up failed too (e.g. weak password); surface sign-in error
            # if it looks like wrong credentials, else the signup error.
            msg = str(signin_err)
            if "invalid" in msg.lower() and "credential" in msg.lower():
                raise ValueError("Wrong password for this email.") from None
            raise


def authed_client():
    """Supabase client scoped to the logged-in worker (RLS enforced).

    Returns None when nobody is logged in. Retries once: a transient
    network blip must not sign the worker out (app.py signs out + reruns
    when this returns None, so a flaky first attempt would wedge the app
    into a sign-out/restore loop).
    """
    import streamlit as st
    sess = st.session_state.get("sb_session")
    if not sess:
        return None
    client = get_anon_client()
    try:
        client.auth.set_session(sess["access_token"], sess["refresh_token"])
        return client
    except Exception:
        pass
    try:
        import time
        time.sleep(1)
        client.auth.set_session(sess["access_token"], sess["refresh_token"])
        return client
    except Exception:
        return None


def current_user() -> dict | None:
    import streamlit as st
    s = st.session_state.get("sb_session")
    return {"id": s["user_id"], "email": s["email"]} if s else None


def sign_out() -> None:
    import streamlit as st
    try:
        client = authed_client()
        if client:
            client.auth.sign_out()
    finally:
        # Delete with a FRESH component key: a reused "delete" iframe never
        # re-fires its effect, so a second logout in one session would
        # silently skip the browser-side delete.
        try:
            _cookie_manager().delete(
                COOKIE_NAME, key=f"ss_del_{_cookie_nonce()}")
        except Exception:
            pass
        # Hard in-session guard: the cookie iframe's saved value goes stale
        # after a delete (it only reports on mount), so without this flag
        # restore_session() would resurrect the session on the next rerun
        # and logout would appear to do nothing.
        st.session_state["_ss_logged_out"] = True
        st.session_state["_ss_cookie_ok"] = False
        for k in ("sb_session", "worker", "chat"):
            st.session_state.pop(k, None)
