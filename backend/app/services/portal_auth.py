"""Small demo account/session layer for resumable supplier applications."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PortalSession


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split(":", 1)
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
        return secrets.compare_digest(actual, bytes.fromhex(digest_hex))
    except (ValueError, TypeError):
        return False


def create_session(db: Session, role: str, account_id=None) -> str:
    token = secrets.token_urlsafe(32)
    db.add(PortalSession(
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        role=role,
        account_id=account_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    ))
    db.commit()
    return token


def current_session(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> PortalSession:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    token = authorization.removeprefix("Bearer ").strip()
    session = db.scalar(select(PortalSession).where(
        PortalSession.token_hash == hashlib.sha256(token.encode()).hexdigest()
    ))
    if session is None:
        raise HTTPException(status_code=401, detail="Your session has expired. Please sign in again.")
    expires_at = session.expires_at.replace(tzinfo=timezone.utc) if session.expires_at.tzinfo is None else session.expires_at
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Your session has expired. Please sign in again.")
    return session


def require_supplier(session: PortalSession = Depends(current_session)) -> PortalSession:
    if session.role != "supplier" or session.account_id is None:
        raise HTTPException(status_code=403, detail="Supplier access is required.")
    return session


def require_reviewer(session: PortalSession = Depends(current_session)) -> PortalSession:
    if session.role != "reviewer":
        raise HTTPException(status_code=403, detail="Reviewer access is required.")
    return session


def require_admin(session: PortalSession = Depends(current_session)) -> PortalSession:
    if session.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access is required.")
    return session
