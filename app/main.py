"""FastAPI entrypoint. Vercel detects the `app` object in app/main.py."""

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.routes import account, admin, auth, pages
from app.sessions import LoginRequired
from app.web import STATIC_DIR

app = FastAPI(title=get_settings().app_name, docs_url=None, redoc_url=None, openapi_url=None)


@app.exception_handler(LoginRequired)
async def login_required(request: Request, exc: LoginRequired) -> Response:
    # HTMX requests can't follow a redirect into a full page, so tell htmx to navigate.
    if request.headers.get("hx-request"):
        return Response(status_code=204, headers={"HX-Redirect": "/login"})
    return RedirectResponse("/login", status_code=303)


app.include_router(pages.router)
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
