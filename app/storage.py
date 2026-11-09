"""File storage for car photos and invoice PDFs (NFR-14).

Files are private: they live in Vercel Blob (private access) under random paths, the
database keeps only the reference, and downloads go through the app's access check.
On Vercel the app authenticates with OIDC: BLOB_STORE_ID plus the OIDC token of the current
request. BLOB_READ_WRITE_TOKEN is the fallback. Off Vercel with neither, files go to a local
folder so development works; on Vercel the local folder is never used."""

import contextvars
import logging
import secrets
from pathlib import Path
from typing import Protocol

import httpx2

from app.config import get_settings

BLOB_API = "https://vercel.com/api/blob"
BLOB_API_VERSION = "13"
OIDC_HEADER = "x-vercel-oidc-token"

# The OIDC token of the request being handled; set by OidcMiddleware.
request_oidc_token: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_oidc_token", default=None
)


class OidcMiddleware:
    """Pure ASGI middleware: remembers the request's x-vercel-oidc-token for the storage code
    (Vercel Python functions receive it as a header, not as an environment variable)."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            wanted = OIDC_HEADER.encode()
            token = next(
                (value.decode("latin-1") for name, value in scope["headers"] if name == wanted),
                None,
            )
            reset = request_oidc_token.set(token or None)
            try:
                await self.app(scope, receive, send)
            finally:
                request_oidc_token.reset(reset)
        else:
            await self.app(scope, receive, send)


def oidc_token() -> str | None:
    """The current request's OIDC token, else VERCEL_OIDC_TOKEN (e.g. after `vercel env pull`)."""
    return request_oidc_token.get() or get_settings().vercel_oidc_token or None


log = logging.getLogger(__name__)


class StorageError(Exception):
    """File storage failed. The message is safe to show and log.

    For Blob failures, `operation`, `status` and `code` say which request failed and why."""

    def __init__(
        self,
        message: str,
        operation: str | None = None,
        status: int | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.status = status
        self.code = code


class Backend(Protocol):
    name: str

    def put(self, pathname: str, data: bytes, content_type: str) -> str: ...
    def get(self, ref: str) -> bytes: ...
    def delete(self, ref: str) -> None: ...


def http_client() -> httpx2.Client:
    return httpx2.Client(timeout=httpx2.Timeout(25.0))


def error_code(response: httpx2.Response) -> str | None:
    """Vercel's error code from {"error": {"code": ...}}; never the message or anything else."""
    try:
        code = response.json()["error"]["code"]
    except (ValueError, KeyError, TypeError):
        return None
    return code if isinstance(code, str) and len(code) <= 60 and code.isidentifier() else None


class BlobBackend:
    """Mirrors the @vercel/blob client: PUT {api}/?pathname=..., POST {api}/delete, and a
    GET of the blob URL, each with the bearer token."""

    name = "Vercel Blob"
    method = "read-write token"

    def __init__(self, token: str, api_url: str | None = None, store_id: str | None = None) -> None:
        self.api = (api_url or BLOB_API).rstrip("/")
        self.auth = {"authorization": f"Bearer {token}"}
        if store_id:
            # OIDC: the bearer is the OIDC token, so say which store it is for.
            self.auth["x-vercel-blob-store-id"] = store_id
            self.method = "OIDC"
        self.headers = {**self.auth, "x-api-version": BLOB_API_VERSION}

    @property
    def label(self) -> str:
        return f"{self.name} via {self.method}"

    def fail(
        self, operation: str, message: str, response: httpx2.Response | None, exc: Exception
    ) -> StorageError:
        status = response.status_code if response is not None else None
        code = error_code(response) if response is not None else None
        log.warning(
            "Blob %s failed: status=%s code=%s (%s)", operation, status, code, type(exc).__name__
        )
        return StorageError(message, operation, status, code)

    def put(self, pathname: str, data: bytes, content_type: str) -> str:
        headers = {
            **self.headers,
            "x-vercel-blob-access": "private",
            "x-add-random-suffix": "1",
            "x-content-type": content_type,
        }
        response = None
        try:
            with http_client() as client:
                response = client.put(
                    f"{self.api}/", params={"pathname": pathname}, content=data, headers=headers
                )
                response.raise_for_status()
                return response.json()["url"]
        except (httpx2.HTTPError, KeyError, ValueError) as exc:
            raise self.fail("put", "The file could not be saved.", response, exc) from exc

    def get(self, ref: str) -> bytes:
        response = None
        try:
            with http_client() as client:
                response = client.get(ref, headers=self.auth)
                response.raise_for_status()
                return response.content
        except httpx2.HTTPError as exc:
            raise self.fail("get", "The file could not be read.", response, exc) from exc

    def delete(self, ref: str) -> None:
        response = None
        try:
            with http_client() as client:
                response = client.post(
                    f"{self.api}/delete", json={"urls": [ref]}, headers=self.headers
                )
                response.raise_for_status()
        except httpx2.HTTPError as exc:
            raise self.fail("delete", "The file could not be deleted.", response, exc) from exc


class LocalBackend:
    """Development stand-in: files in a folder, referenced by their relative path."""

    name = "Local folder"
    label = "Local folder"

    def __init__(self, root: str) -> None:
        self.root = Path(root)

    def path(self, ref: str) -> Path:
        path = (self.root / ref).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise StorageError("Bad file reference.")
        return path

    def put(self, pathname: str, data: bytes, content_type: str) -> str:
        ref = pathname
        try:
            path = self.path(ref)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except OSError as exc:
            raise StorageError("The file could not be saved.") from exc
        return ref

    def get(self, ref: str) -> bytes:
        try:
            return self.path(ref).read_bytes()
        except OSError as exc:
            raise StorageError("The file could not be read.") from exc

    def delete(self, ref: str) -> None:
        self.path(ref).unlink(missing_ok=True)


NOT_CONNECTED = "File storage isn't connected: no BLOB_STORE_ID / OIDC token"


class UnconnectedBackend:
    """On Vercel with no usable Blob credentials: fail clearly rather than use the local folder."""

    name = "Vercel Blob"
    label = "Vercel Blob (not connected)"

    def put(self, pathname: str, data: bytes, content_type: str) -> str:
        raise StorageError(NOT_CONNECTED)

    def get(self, ref: str) -> bytes:
        raise StorageError(NOT_CONNECTED)

    def delete(self, ref: str) -> None:
        raise StorageError(NOT_CONNECTED)


def backend() -> Backend:
    """OIDC (store ID + the request's OIDC token), then the read-write token, then the local
    folder, which is only allowed when not running on Vercel."""
    settings = get_settings()
    token = oidc_token()
    if settings.blob_store_id and token:
        return BlobBackend(token, settings.vercel_blob_api_url, settings.blob_store_id)
    if settings.blob_read_write_token:
        return BlobBackend(settings.blob_read_write_token, settings.vercel_blob_api_url)
    if settings.vercel:
        return UnconnectedBackend()
    return LocalBackend(settings.local_storage_dir)


def describe() -> dict:
    """What the Check page shows: the backend and method, and whether the OIDC inputs exist.
    Presence only, never values."""
    settings = get_settings()
    return {
        "label": backend().label,
        "store_id_found": bool(settings.blob_store_id),
        "oidc_token_found": bool(oidc_token()),
    }


def new_pathname(kind: str, extension: str) -> str:
    """An unguessable path, so a leaked reference alone still isn't a public URL."""
    return f"{kind}/{secrets.token_urlsafe(24)}.{extension}"


def save(kind: str, extension: str, data: bytes, content_type: str) -> str:
    return backend().put(new_pathname(kind, extension), data, content_type)


def load(ref: str) -> bytes:
    return backend().get(ref)


def remove(ref: str | None) -> None:
    """Best effort: a file that can't be deleted must not block deleting the record."""
    if not ref:
        return
    try:
        backend().delete(ref)
    except StorageError:
        pass


def check() -> tuple[str, bool, str]:
    """Save, read back, compare and delete a tiny test file. Returns (backend label, ok, message)
    where the message is "File storage works" or the failing step with status and error code."""
    store = backend()
    data = secrets.token_bytes(16)
    ref = None

    def failure(step: str, exc: StorageError) -> tuple[str, bool, str]:
        detail = ", ".join(
            part
            for part in (
                f"status {exc.status}" if exc.status else "",
                f"error code {exc.code}" if exc.code else "",
            )
            if part
        )
        return store.label, False, f"{step} failed" + (f" ({detail})" if detail else f": {exc}")

    try:
        ref = store.put(new_pathname("checks", "txt"), data, "text/plain")
    except StorageError as exc:
        return failure("Saving the test file", exc)
    try:
        if store.get(ref) != data:
            return store.label, False, "Reading back the test file failed (contents differ)"
    except StorageError as exc:
        remove(ref)
        return failure("Reading back the test file", exc)
    try:
        store.delete(ref)
    except StorageError as exc:
        return failure("Deleting the test file", exc)
    return store.label, True, "File storage works"
