"""Encryption at rest, keyed by TOKEN_ENCRYPTION_KEY: third-party tokens and sensitive
content, so a database leak alone exposes nothing.

The key lives only in the environment (Vercel, .env), never in the database."""

import hashlib
import hmac
from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    key = get_settings().token_encryption_key
    if not key:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is not set")
    return Fernet(key)


def encrypt(value: str) -> bytes:
    return _fernet().encrypt(value.encode())


def decrypt(token: bytes) -> str:
    return _fernet().decrypt(token).decode()


def blind_index(value: str) -> bytes:
    """A keyed hash for looking a value up (e.g. a VIN) without storing it in the clear.

    HMAC-SHA256 under a key derived from TOKEN_ENCRYPTION_KEY, so the digests mean
    nothing without the key."""
    key = hashlib.sha256(b"blind-index:" + (get_settings().token_encryption_key or "").encode())
    return hmac.new(key.digest(), value.encode(), hashlib.sha256).digest()
