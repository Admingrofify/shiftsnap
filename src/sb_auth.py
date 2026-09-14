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


def _cookie_manager():
    import streamlit as st
    cm = st.session_state.get("cookie_manager")
    if cm is None:
        from extra_streamlit_components import CookieManager
        cm = CookieManager()
        st.session_state.cookie_manager = cm
    return cm


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
    # NOTE: the cookie itself is written by persist_session_cookie() during
    # a normal render. Writing it here would race with the st.rerun() that
    # follows login, and the browser might never execute it.
    return {"id": res.user.id, "email": res.user.email}


def persist_session_cookie() -> None:
    """(Re)write the login cookie while a session is active.

    Called on every script run; the write happens during a completed
    render so the browser reliably executes it. Once per session is
    enough — the cookie then lives in the browser for COOKIE_DAYS.
    """
    import streamlit as st
    sess = st.session_state.get("sb_session")
    if not sess or st.session_state.get("cookie_persisted"):
        return
    try:
        _cookie_manager().set(
            COOKIE_NAME, json.dumps(sess),
            expires_at=datetime.now() + timedelta(days=COOKIE_DAYS))
        st.session_state.cookie_persisted = True
    except Exception:
        pass


def restore_session() -> None:
    """Restore a persisted login from the cookie after a page reload.

    Note: extra-streamlit-components has no ready() API. On a cold load
    get_all() returns {} until the frontend reports back, which triggers
    an automatic rerun — then the cookie is picked up.
    """
    import streamlit as st
    if st.session_state.get("sb_session"):
        return
    try:
        raw = _cookie_manager().get_all().get(COOKIE_NAME)
    except Exception:
        return
    if not raw:
        return
    try:
        sess = json.loads(raw)
    except Exception:
        return
    if isinstance(sess, dict) and sess.get("refresh_token"):
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

    Returns None when nobody is logged in.
    """
    import streamlit as st
    sess = st.session_state.get("sb_session")
    if not sess:
        return None
    client = get_anon_client()
    try:
        client.auth.set_session(sess["access_token"], sess["refresh_token"])
    except Exception:
        return None
    return client


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
        try:
            _cookie_manager().delete(COOKIE_NAME)
        except Exception:
            try:  # older CookieManager without delete(): expire it instead
                _cookie_manager().set(
                    COOKIE_NAME, "",
                    expires_at=datetime.now() - timedelta(days=1))
            except Exception:
                pass
        for k in ("sb_session", "worker", "chat"):
            st.session_state.pop(k, None)
