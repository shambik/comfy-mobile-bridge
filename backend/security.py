import hmac
import secrets

from fastapi import HTTPException, Request

COOKIE = "h3_session"


def new_token() -> str:
    return secrets.token_urlsafe(32)


def require_csrf(request: Request):
    cookie = request.cookies.get(COOKIE, "")
    header = request.headers.get("x-csrf-token", "")
    if not cookie or not header or not hmac.compare_digest(cookie, header):
        raise HTTPException(403, "Invalid session token")

