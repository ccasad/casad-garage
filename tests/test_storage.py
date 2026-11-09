import logging

import httpx2
import pytest
from sqlalchemy import select

from app import storage
from app.config import Settings
from app.models import AuditEvent
from tests.conftest import make_car, sign_in

TOKEN = "test-token-123"


@pytest.fixture
def blob(monkeypatch):
    """A BlobBackend whose HTTP layer records every request."""
    requests: list[httpx2.Request] = []
    state = {"handler": lambda request: httpx2.Response(200, json={"url": "https://s.private/x"})}

    def handler(request):
        requests.append(request)
        return state["handler"](request)

    monkeypatch.setattr(
        storage, "http_client", lambda: httpx2.Client(transport=httpx2.MockTransport(handler))
    )
    return storage.BlobBackend(TOKEN), requests, state


def test_put_matches_the_sdk_request(blob):
    backend, requests, _ = blob

    ref = backend.put("photos/a.jpg", b"data", "image/jpeg")

    request = requests[0]
    assert ref == "https://s.private/x"
    assert request.method == "PUT"
    assert str(request.url) == "https://vercel.com/api/blob/?pathname=photos%2Fa.jpg"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.headers["x-api-version"] == storage.BLOB_API_VERSION
    assert request.headers["x-vercel-blob-access"] == "private"
    assert request.headers["x-add-random-suffix"] == "1"
    assert request.headers["x-content-type"] == "image/jpeg"
    assert request.content == b"data"


def test_get_reads_the_blob_url_with_the_token(blob):
    backend, requests, state = blob
    state["handler"] = lambda request: httpx2.Response(200, content=b"bytes")

    assert backend.get("https://s.private/x") == b"bytes"

    assert requests[0].method == "GET"
    assert str(requests[0].url) == "https://s.private/x"
    assert requests[0].headers["authorization"] == f"Bearer {TOKEN}"


def test_delete_matches_the_sdk_request(blob):
    backend, requests, _ = blob

    backend.delete("https://s.private/x")

    request = requests[0]
    assert request.method == "POST"
    assert str(request.url) == "https://vercel.com/api/blob/delete"
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.headers["x-api-version"] == storage.BLOB_API_VERSION
    assert request.read() == b'{"urls":["https://s.private/x"]}'


def test_api_url_can_be_overridden(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx2.Response(200, json={"url": "u"})

    monkeypatch.setattr(
        storage, "http_client", lambda: httpx2.Client(transport=httpx2.MockTransport(handler))
    )
    storage.BlobBackend(TOKEN, "http://localhost:9/blob/").put("a", b"x", "text/plain")

    assert str(requests[0].url) == "http://localhost:9/blob/?pathname=a"


def test_failure_logs_operation_status_and_code_only(blob, caplog):
    backend, _, state = blob
    state["handler"] = lambda r: httpx2.Response(
        403, json={"error": {"code": "forbidden", "message": "secret personal detail"}}
    )

    with (
        caplog.at_level(logging.WARNING, logger="app.storage"),
        pytest.raises(storage.StorageError) as caught,
    ):
        backend.put("invoices/private-path.pdf", b"FILE-CONTENTS", "application/pdf")

    assert (caught.value.operation, caught.value.status, caught.value.code) == (
        "put",
        403,
        "forbidden",
    )
    log = caplog.text
    assert "put" in log and "403" in log and "forbidden" in log
    for secret in (TOKEN, "private-path", "FILE-CONTENTS", "secret personal detail"):
        assert secret not in log


def test_failure_without_a_json_body(blob):
    backend, _, state = blob
    state["handler"] = lambda r: httpx2.Response(502, content=b"<html>")

    with pytest.raises(storage.StorageError) as caught:
        backend.get("https://s.private/x")

    assert (caught.value.operation, caught.value.status, caught.value.code) == ("get", 502, None)


def test_photo_error_reason_reaches_the_browser(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)

    response = client.post(
        f"/cars/{car.id}/photo", files={"photo": ("p.jpg", b"not a jpeg", "image/jpeg")}
    )

    assert response.status_code == 415
    assert response.json()["detail"] == "The photo must be a JPEG."
    script = client.get("/static/js/uploads.js").text
    assert "body.detail" in script


def test_photo_storage_failure_gives_its_reason(client, db, member, files, monkeypatch):
    car = make_car(db, member)
    sign_in(client, db, member)

    def broken(*args):
        raise storage.StorageError("The file could not be saved.", "put", 403, "forbidden")

    monkeypatch.setattr(files, "put", broken)
    response = client.post(
        f"/cars/{car.id}/photo", files={"photo": ("p.jpg", b"\xff\xd8\xffxx", "image/jpeg")}
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "The file could not be saved."


def test_invoice_storage_failure_shows_a_reason(client, db, member, files, monkeypatch):
    from tests.test_invoices import upload

    car = make_car(db, member)
    sign_in(client, db, member)
    client.post(f"/cars/{car.id}/select")
    monkeypatch.setattr(
        files,
        "put",
        lambda *a: (_ for _ in ()).throw(storage.StorageError("x", "put", 500, "unknown")),
    )

    response = upload(client, b"%PDF-1.4 hello")

    assert "notice=storage" in response.headers["location"]
    page = client.get(response.headers["location"])
    assert "The file could not be saved." in page.text


def test_check_reports_success_and_cleans_up(files):
    _name, ok, message = storage.check()

    assert (ok, message) == (True, "File storage works")
    assert files.files == {}


def test_check_reports_the_failing_step(files, monkeypatch):
    def broken(pathname, data, content_type):
        raise storage.StorageError("x", "put", 403, "forbidden")

    monkeypatch.setattr(files, "put", broken)

    _, ok, message = storage.check()

    assert not ok
    assert message == "Saving the test file failed (status 403, error code forbidden)"


def test_check_detects_different_contents(files, monkeypatch):
    monkeypatch.setattr(files, "get", lambda ref: b"other")

    _, ok, message = storage.check()

    assert not ok and "contents differ" in message


def test_admin_runs_the_check_and_it_is_audited(client, db, admin):
    sign_in(client, db, admin)

    page = client.get("/admin/storage")
    assert "Check file storage" in client.get("/more").text
    result = client.post("/admin/storage/check")

    assert page.status_code == 200
    assert "File storage works" in result.text
    event = db.scalars(select(AuditEvent).where(AuditEvent.event == "storage_checked")).one()
    assert event.user_id == admin.id and event.detail["ok"] is True


def test_check_is_admin_only(client, db, member):
    sign_in(client, db, member)

    assert client.get("/admin/storage").status_code == 403
    assert client.post("/admin/storage/check").status_code == 403
    assert "/admin/storage" not in client.get("/more").text


# --- OIDC (FR-7, FR-18, FR-29, NFR-14) ---

REAL_BACKEND = storage.backend
STORE = "store_abc123"
OIDC = "oidc-token-xyz"


@pytest.fixture
def env(monkeypatch):
    """Real backend selection with explicit settings; returns a function to set them."""
    monkeypatch.setattr(storage, "backend", REAL_BACKEND)

    def set_env(**values):
        settings = Settings(_env_file=None, local_storage_dir="/tmp/x-local", **values)
        monkeypatch.setattr(storage, "get_settings", lambda: settings)

    return set_env


def test_oidc_when_store_id_and_token(env):
    env(blob_store_id=STORE, vercel_oidc_token=OIDC, vercel="1")
    chosen = storage.backend()
    assert isinstance(chosen, storage.BlobBackend)
    assert chosen.label == "Vercel Blob via OIDC"
    assert chosen.auth["authorization"] == f"Bearer {OIDC}"
    assert chosen.auth["x-vercel-blob-store-id"] == STORE


def test_oidc_wins_over_the_read_write_token(env):
    env(blob_store_id=STORE, vercel_oidc_token=OIDC, blob_read_write_token=TOKEN, vercel="1")
    assert storage.backend().label == "Vercel Blob via OIDC"


def test_read_write_token_when_no_oidc(env):
    env(blob_store_id=STORE, blob_read_write_token=TOKEN, vercel="1")
    chosen = storage.backend()
    assert chosen.label == "Vercel Blob via read-write token"
    assert chosen.auth == {"authorization": f"Bearer {TOKEN}"}


def test_store_id_without_a_token_is_not_oidc(env):
    env(blob_store_id=STORE)
    assert isinstance(storage.backend(), storage.LocalBackend)


def test_local_folder_when_nothing_is_set_off_vercel(env):
    env()
    assert storage.backend().label == "Local folder"


@pytest.mark.parametrize(
    "values",
    [{}, {"blob_store_id": STORE}, {"vercel_oidc_token": OIDC}],
)
def test_local_folder_is_never_used_on_vercel(env, values):
    env(vercel="1", **values)
    chosen = storage.backend()
    assert isinstance(chosen, storage.UnconnectedBackend)
    with pytest.raises(storage.StorageError, match="no BLOB_STORE_ID / OIDC token"):
        chosen.put("a.jpg", b"x", "image/jpeg")
    with pytest.raises(storage.StorageError, match="isn't connected"):
        chosen.get("a")


def test_oidc_token_comes_from_the_current_request(env):
    env(blob_store_id=STORE, vercel="1")
    seen = []

    async def app(scope, receive, send):
        seen.append(storage.oidc_token())

    import asyncio

    middleware = storage.OidcMiddleware(app)
    scope = {"type": "http", "headers": [(b"x-vercel-oidc-token", b"req-token-1")]}
    asyncio.run(middleware(scope, None, None))
    asyncio.run(middleware({"type": "http", "headers": []}, None, None))
    assert seen == ["req-token-1", None]
    assert storage.oidc_token() is None


def test_request_token_beats_the_environment_token(env):
    env(blob_store_id=STORE, vercel_oidc_token="env-token", vercel="1")
    token = storage.request_oidc_token.set("req-token")
    try:
        assert storage.backend().auth["authorization"] == "Bearer req-token"
    finally:
        storage.request_oidc_token.reset(token)
    assert storage.backend().auth["authorization"] == "Bearer env-token"


def test_header_reaches_storage_through_the_app(client, db, admin, env, monkeypatch):
    env(blob_store_id=STORE, vercel="1")
    sign_in(client, db, admin)
    monkeypatch.setattr(storage, "backend", REAL_BACKEND)
    page = client.get("/admin/storage", headers={"x-vercel-oidc-token": OIDC})
    assert "OIDC token: <span" in page.text and "found</span>" in page.text
    assert OIDC not in page.text and STORE not in page.text
    assert "Vercel Blob via OIDC" in page.text
    page = client.get("/admin/storage")
    assert "Vercel Blob (not connected)" in page.text


def test_oidc_put_get_delete_send_the_expected_auth(env, monkeypatch):
    env(blob_store_id=STORE, vercel_oidc_token=OIDC, vercel="1")
    requests = []

    def handler(request):
        requests.append(request)
        return (
            httpx2.Response(200, json={"url": "https://s.private/x"}, content=None)
            if (request.method == "PUT")
            else httpx2.Response(200, content=b"bytes")
        )

    monkeypatch.setattr(
        storage, "http_client", lambda: httpx2.Client(transport=httpx2.MockTransport(handler))
    )
    backend = storage.backend()
    backend.put("photos/a.jpg", b"d", "image/jpeg")
    backend.get("https://s.private/x")
    backend.delete("https://s.private/x")
    assert len(requests) == 3
    for request in requests:
        assert request.headers["authorization"] == f"Bearer {OIDC}"
        assert request.headers["x-vercel-blob-store-id"] == STORE


def test_oidc_failure_log_has_no_token_or_store(env, monkeypatch, caplog):
    env(blob_store_id=STORE, vercel_oidc_token=OIDC, vercel="1")
    monkeypatch.setattr(
        storage,
        "http_client",
        lambda: httpx2.Client(
            transport=httpx2.MockTransport(
                lambda r: httpx2.Response(403, json={"error": {"code": "forbidden"}})
            )
        ),
    )
    with caplog.at_level(logging.WARNING), pytest.raises(storage.StorageError):
        storage.backend().put("photos/a.jpg", b"d", "image/jpeg")
    assert "status=403 code=forbidden" in caplog.text
    assert OIDC not in caplog.text and STORE not in caplog.text
