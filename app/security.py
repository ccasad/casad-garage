import hashlib
import secrets


def new_token() -> str:
    """A 256-bit random token for session cookies."""
    return secrets.token_urlsafe(32)


def new_link_token() -> str:
    """A 256-bit random token for links people send each other.

    Hex only: messaging apps mangle `_` and `-` (markdown italics, link detection
    that drops trailing punctuation), which silently breaks a token.
    """
    return secrets.token_hex(32)


def hash_token(token: str) -> bytes:
    """Only token hashes are stored, so a database leak can't be replayed as a login."""
    return hashlib.sha256(token.encode()).digest()
