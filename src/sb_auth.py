"""Supabase Auth (email + password) helpers for the Streamlit app.

Why password instead of magic link: Supabase's built-in email service is
rate-limited to a trickle and meant for testing only, so magic links break
under real usage. Email+password with "Confirm email" DISABLED in the
dashboard (Authentication > Settings) sends zero emails — no limits, no
SMTP setup, free forever.

Flow:
  1. Worker enters work email + password, taps "Login / Sign up".
  2. First tap creates the account (min 6 chars), later taps sign in.
  3. The session JWT is stored in st.session_state; authed_client()
     returns a supabase client carrying it, so every query is scoped by
     Row Level Security to that worker.
"""
from __future__ import annotations

import os

APP_URL = os.getenv("APP_URL", "https://shiftssnap.com")


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


def _save_session(res) -> dict:
    import streamlit as st
    if not res.session or not res.user:
        raise RuntimeError(
            "No session returned. The Supabase project likely still has "
            "'Confirm email' enabled — turn it off under "
            "Authentication > Settings.")
    st.session_state.sb_session = {
        "access_token": res.session.access_token,
        "refresh_token": res.session.refresh_token,
        "user_id": res.user.id,
        "email": res.user.email,
    }
    return {"id": res.user.id, "email": res.user.email}


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
        for k in ("sb_session", "worker", "chat"):
            st.session_state.pop(k, None)
