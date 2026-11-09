import logging

import httpx2
import pytest
from sqlalchemy import select

from app import storage
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
