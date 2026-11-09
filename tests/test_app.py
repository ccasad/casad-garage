import json

import pytest

from app.web import NAV_ITEMS
from tests.conftest import sign_in


@pytest.mark.parametrize("item", NAV_ITEMS, ids=lambda item: item["key"])
def test_pages_render_with_navigation(client, db, member, item):
    sign_in(client, db, member)

    response = client.get(item["href"])

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert 'aria-current="page"' in response.text
    assert 'rel="manifest"' in response.text


def test_signed_out_pages_have_no_navigation(client):
    response = client.get("/login")

    assert response.status_code == 200
    assert 'aria-label="Main"' not in response.text


def test_healthz_needs_no_database(client):
    # The client fixture's database is never touched here; Vercel uptime checks
    # must not wake Neon.
    assert client.get("/healthz").json() == {"status": "ok"}


def test_service_worker_is_served_from_root(client):
    response = client.get("/sw.js")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.headers["cache-control"] == "no-cache"


def test_service_worker_only_caches_offline_page(client):
    source = client.get("/sw.js").text

    assert "cache.add(" in source
    assert "cache.put(" not in source
    assert "addAll(" not in source


def test_manifest_icons_exist(client):
    response = client.get("/manifest.webmanifest")
    manifest = json.loads(response.text)

    assert response.headers["content-type"].startswith("application/manifest+json")
    assert manifest["display"] == "standalone"
    assert any(icon["purpose"] == "maskable" for icon in manifest["icons"])
    for icon in manifest["icons"]:
        assert client.get(icon["src"]).status_code == 200


def test_offline_page_is_static(client):
    assert client.get("/static/offline.html").status_code == 200
