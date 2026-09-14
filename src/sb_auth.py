"""Supabase Auth (email magic link) helpers for the Streamlit app.

Flow:
  1. Worker enters their work email -> send_magic_link() emails them a link.
  2. They click it -> Supabase redirects to APP_URL with
     ?token_hash=...&type=magiclink.
  3. consume_callback() verifies it and stores the session (JWT) in
     st.session_state.
  4. authed_client() returns a supabase client carrying that JWT, so every
     query is scoped by Row Level Security to that worker.

Free tier: Auth + 50k monthly active users included.
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


def send_magic_link(email: str) -> None:
    client = get_anon_client()
    client.auth.sign_in_with_otp(
        {"email": email.strip(),
         "options": {"email_redirect_to": APP_URL}})


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


def consume_callback() -> dict | None:
    """Verify a ?token_hash= magic-link callback. Returns the user dict."""
    import streamlit as st
    qp = st.query_params
    token_hash = qp.get("token_hash")
    if not token_hash:
        return None
    client = get_anon_client()
    res = client.auth.verify_otp(
        {"token_hash": token_hash, "type": qp.get("type", "magiclink")})
    if not res.session or not res.user:
        raise RuntimeError("Login link did not return a session.")
    st.session_state.sb_session = {
        "access_token": res.session.access_token,
        "refresh_token": res.session.refresh_token,
        "user_id": res.user.id,
        "email": res.user.email,
    }
    st.query_params.clear()
    return {"id": res.user.id, "email": res.user.email}


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
