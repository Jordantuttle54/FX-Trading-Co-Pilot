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


def passwordless_login_enabled() -> bool:
    """Whether anyone naming an allowed user can log in with no passcode.

    This defaulted to ON, which on a public deployment means the allowlist is
    the only thing between the internet and the account - and the allowlist
    defaults to "Jake,Jordan". Fine while nothing was at stake; not something
    to carry into live money. It now has to be switched on deliberately:
    set TEMP_PASSWORDLESS_LOGIN=true to get the old behaviour back.
    """
    return os.getenv("TEMP_PASSWORDLESS_LOGIN", "false").lower() in ("1", "true", "yes", "on")


PLACEHOLDER_SIGNING_KEY = "change-me-in-vercel"


def signing_key() -> bytes:
    """The key session tokens are signed with.

    The placeholder is public knowledge - it is in this file - so anything
    signed with it can be forged by anyone. It is tolerated only in the
    explicit development mode that also turns off passcodes; a deployment
    posing as production without a real secret is a misconfiguration, and
    failing loudly here beats handing out forgeable sessions.
    """
    configured = os.getenv("AUTH_TOKEN_SECRET", "").strip()
    if configured:
        return configured.encode("utf-8")
    if passwordless_login_enabled():
        return PLACEHOLDER_SIGNING_KEY.encode("utf-8")
    raise HTTPException(
        status_code=503,
        detail="AUTH_TOKEN_SECRET is not set on this deployment, so sessions cannot be signed securely.",
    )


def sign(payload: str) -> str:
    return hmac.new(signing_key(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def make_session(username: str, passcode: str = "") -> dict:
    users = allowed_users()
    key = (username or "").strip().lower()
    if key not in users:
        raise HTTPException(status_code=401, detail="Invalid login")

    if not passwordless_login_enabled():
        expected = secret_value()
        if not expected:
            raise HTTPException(status_code=503, detail="Authentication is not configured")
        if not hmac.compare_digest(passcode or "", expected):
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
