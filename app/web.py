from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app import cars as car_access
from app import due
from app.config import get_settings
from app.models import User, utcnow
from app.theme import theme_for

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

templates = Jinja2Templates(directory=BASE_DIR / "templates")


def time_ago(moment: datetime) -> str:
    """'just now', '5 minutes ago', '3 hours ago', '2 days ago', then a date."""
    seconds = int((utcnow() - moment).total_seconds())
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            count = seconds // size
            if unit == "day" and count > 30:
                return moment.strftime("%b %-d, %Y")
            return f"{count} {unit}{'' if count == 1 else 's'} ago"
    return "just now"


templates.env.filters["ago"] = time_ago

# Pages may show personal data, so the browser must never store them.
NO_STORE = {"Cache-Control": "no-store"}

# Bottom tabs on phones, sidebar on laptops. Up to five items; keep "More" last.
NAV_ITEMS = [
    {"key": "overview", "label": "Overview", "href": "/", "icon": "car"},
    {"key": "service", "label": "Service", "href": "/service", "icon": "wrench"},
    {"key": "due", "label": "Due", "href": "/due", "icon": "calendar-clock"},
    {"key": "todo", "label": "To do", "href": "/todo", "icon": "clipboard"},
    {"key": "more", "label": "More", "href": "/more", "icon": "dots"},
]


def render(
    request: Request,
    template: str,
    *,
    title: str,
    user: User | None,
    active: str | None = None,
    status_code: int = 200,
    db: Session | None = None,
    **context: Any,
) -> HTMLResponse:
    """Render a page. The navigation and car selector only appear for signed-in users;
    pass `db` for pages that show the selector."""
    selector = None
    if user is not None and db is not None:
        cars = car_access.ordered_cars(db, user)
        chosen = car_access.selected_car(db, user)
        selector = {
            "cars": cars,
            "selected": chosen,
            "due_soon": due.due_soon_car_ids(db, [c.id for c in cars]),
            "stars": car_access.starred_ids(db, user),
        }
    return templates.TemplateResponse(
        request,
        template,
        {
            "app_name": get_settings().app_name,
            "page_title": title,
            "active": active,
            "nav_items": NAV_ITEMS,
            "user": user,
            "theme": theme_for(request, user),
            "now": utcnow(),
            "selector": selector,
            "current_path": request.url.path,
            **context,
        },
        status_code=status_code,
        headers=NO_STORE,
    )
