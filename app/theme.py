"""Light/dark appearance. Saved on the account so it follows you across sign-ins and
devices, and mirrored in a cookie so pages before sign-in use it too."""

from fastapi import Request, Response

from app.config import get_settings
from app.models import User

THEMES = ("dark", "light", "system")
DEFAULT_THEME = "dark"
THEME_COOKIE = "theme"


def theme_for(request: Request, user: User | None) -> str:
    if user is not None and user.theme in THEMES:
        return user.theme
    cookie = request.cookies.get(THEME_COOKIE)
    return cookie if cookie in THEMES else DEFAULT_THEME


def remember_theme(response: Response, theme: str) -> None:
    # Not HttpOnly: the static offline page reads it. It holds no personal data.
    response.set_cookie(
        THEME_COOKIE,
        theme,
        max_age=365 * 24 * 3600,
        secure=get_settings().secure_cookies,
        samesite="lax",
        path="/",
    )
