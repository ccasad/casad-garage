"""File storage for car photos and invoice PDFs (NFR-14).

Files are private: they live in Vercel Blob (private access) under random paths, the
database keeps only the reference, and downloads go through the app's access check.
Without BLOB_READ_WRITE_TOKEN, files go to a local folder so development works."""

import secrets
from pathlib import Path
from typing import Protocol

import httpx2

from app.config import get_settings

BLOB_API = "https://vercel.com/api/blob"
BLOB_API_VERSION = "13"


class StorageError(Exception):
    """File storage failed. The message is safe to show and log."""


class Backend(Protocol):
    def put(self, pathname: str, data: bytes, content_type: str) -> str: ...
    def get(self, ref: str) -> bytes: ...
    def delete(self, ref: str) -> None: ...


def http_client() -> httpx2.Client:
    return httpx2.Client(timeout=httpx2.Timeout(25.0))


class BlobBackend:
    def __init__(self, token: str) -> None:
        self.headers = {"authorization": f"Bearer {token}", "x-api-version": BLOB_API_VERSION}

    def put(self, pathname: str, data: bytes, content_type: str) -> str:
        headers = {
            **self.headers,
            "x-vercel-blob-access": "private",
            "x-add-random-suffix": "1",
            "x-content-type": content_type,
        }
        try:
            with http_client() as client:
                response = client.put(
                    BLOB_API, params={"pathname": pathname}, content=data, headers=headers
                )
                response.raise_for_status()
                return response.json()["url"]
        except (httpx2.HTTPError, KeyError, ValueError) as exc:
            raise StorageError("The file could not be saved.") from exc

    def get(self, ref: str) -> bytes:
        try:
            with http_client() as client:
                response = client.get(ref, headers=self.headers)
                response.raise_for_status()
                return response.content
        except httpx2.HTTPError as exc:
            raise StorageError("The file could not be read.") from exc

    def delete(self, ref: str) -> None:
        try:
            with http_client() as client:
                response = client.post(
                    f"{BLOB_API}/delete", json={"urls": [ref]}, headers=self.headers
                )
                response.raise_for_status()
        except httpx2.HTTPError as exc:
            raise StorageError("The file could not be deleted.") from exc


class LocalBackend:
    """Development stand-in: files in a folder, referenced by their relative path."""

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
            raise StorageError("File storage isn't set up (BLOB_READ_WRITE_TOKEN).") from exc
        return ref

    def get(self, ref: str) -> bytes:
        try:
            return self.path(ref).read_bytes()
        except OSError as exc:
            raise StorageError("The file could not be read.") from exc

    def delete(self, ref: str) -> None:
        self.path(ref).unlink(missing_ok=True)


def backend() -> Backend:
    settings = get_settings()
    if settings.blob_read_write_token:
        return BlobBackend(settings.blob_read_write_token)
    return LocalBackend(settings.local_storage_dir)


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
