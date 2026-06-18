import base64
import hashlib
import hmac
import os
import secrets
import time
from typing import Optional

from fastapi import Header, HTTPException


def allowed_users() -> dict[str, str]:
    raw = os.getenv("AUTH_ALLOWED_USERS", "Jake,Jordan")
    names = [x.strip() for x in raw.split(",") if x.strip()]
    return {name.lower(): name for name in names}


def secret_value() -> str:
    return os.getenv("AUTH_PASSCODE", "")


def signing_key() -> bytes:
    return (os.getenv("AUTH_TOKEN_SECRET") or "change-me-in-vercel").encode("utf-8")


def sign(payload: str) -> str:
    return hmac.new(signing_key(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def make_session(username: str, passcode: str) -> dict:
    users = allowed_users()
    key = (username or "").strip().lower()
    expected = secret_value()
    if not expected:
        raise HTTPException(status_code=503, detail="Authentication is not configured")
    if key not in users or not hmac.compare_digest(passcode or "", expected):
        raise HTTPException(status_code=401, detail="Invalid login")
    user = users[key]
    expires_at = int(time.time()) + int(os.getenv("AUTH_TOKEN_TTL_SECONDS", "86400"))
    nonce = secrets.token_urlsafe(12)
    payload = f"{user}|{expires_at}|{nonce}"
    token = base64.urlsafe_b64encode(f"{payload}|{sign(payload)}".encode("utf-8")).decode("utf-8")
    return {"access_token": token, "token_type": "bearer", "user": user, "expires_at": expires_at}


def read_session(token: str) -> str:
    try:
        decoded = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
        user, exp_raw, nonce, signature = decoded.rsplit("|", 3)
        payload = f"{user}|{exp_raw}|{nonce}"
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid session") from exc
    if not hmac.compare_digest(signature, sign(payload)):
        raise HTTPException(status_code=401, detail="Invalid session")
    if int(exp_raw) < int(time.time()):
        raise HTTPException(status_code=401, detail="Session expired")
    users = allowed_users()
    if user.lower() not in users:
        raise HTTPException(status_code=401, detail="User not allowed")
    return users[user.lower()]


def current_user(authorization: Optional[str] = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Login required")
    return read_session(authorization.split(" ", 1)[1].strip())
