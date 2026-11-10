"""FastAPI entrypoint. Vercel detects the `app` object in app/main.py."""

from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routes import account, admin, auth, cars, due, invoices, mileage, pages, service, todo
from app.sessions import CrossOriginBlocked, LoginRequired
from app.storage import OidcMiddleware
from app.web import STATIC_DIR, render

app = FastAPI(title=get_settings().app_name, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(OidcMiddleware)


@app.exception_handler(LoginRequired)
async def login_required(request: Request, exc: LoginRequired) -> Response:
    # HTMX requests can't follow a redirect into a full page, so tell htmx to navigate.
    if request.headers.get("hx-request"):
        return Response(status_code=204, headers={"HX-Redirect": "/login"})
    return RedirectResponse("/login", status_code=303)


def wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "application/json" not in accept and "text/html" in accept


def back_link(request: Request) -> str:
    back = urlsplit(request.headers.get("referer", ""))
    return back.path if back.netloc == request.url.netloc and back.path.startswith("/") else "/"


@app.exception_handler(RequestValidationError)
async def invalid_form(request: Request, exc: RequestValidationError) -> Response:
    # NFR-20: a form post that fails validation gets a friendly page, not raw JSON.
    if not wants_html(request):
        return await request_validation_exception_handler(request, exc)
    return render(
        request,
        "pages/form_error.html",
        title="Something was missing",
        user=None,
        status_code=422,
        back=back_link(request),
        message="Something was missing from the form. Please try again.",
    )


@app.exception_handler(CrossOriginBlocked)
async def blocked_form(request: Request, exc: CrossOriginBlocked) -> Response:
    # NFR-21: a blocked form post gets a friendly page; script requests keep the JSON 403.
    if not wants_html(request):
        return await http_exception_handler(request, exc)
    return render(
        request,
        "pages/form_error.html",
        title="Form not sent",
        user=None,
        status_code=403,
        back=back_link(request),
        message="This form couldn't be sent. Go back and try again.",
    )


app.include_router(pages.router)
app.include_router(cars.router)
app.include_router(mileage.router)
app.include_router(invoices.router)
app.include_router(service.router)
app.include_router(due.router)
app.include_router(todo.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(account.router)


# The service worker and manifest are served from the site root so the worker's
# scope covers every page. Declared before the static mount so they reach the function.
@app.get("/sw.js", include_in_schema=False)
async def service_worker() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/manifest.webmanifest", include_in_schema=False)
async def manifest() -> FileResponse:
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "icons" / "icon.svg", media_type="image/svg+xml")


# Must never touch the database: uptime checks would keep Neon awake.
@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
