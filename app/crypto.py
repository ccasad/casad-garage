"""Encryption at rest, keyed by TOKEN_ENCRYPTION_KEY: third-party tokens and sensitive
content, so a database leak alone exposes nothing.

The key lives only in the environment (Vercel, .env), never in the database."""

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
