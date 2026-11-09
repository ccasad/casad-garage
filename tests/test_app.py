import json
from pathlib import Path

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
    for icon in manifest["icons"]:
        assert icon["purpose"] == "any maskable"
        assert client.get(icon["src"]).status_code == 200


def test_icons_are_the_car_on_the_slug_colour():
    from io import BytesIO

    from PIL import Image

    icons = Path("app/static/icons")
    # hue 176, saturation 55%, lightness 42% -> #30a69e
    for name, size in [
        ("icon-192.png", 192),
        ("icon-512.png", 512),
        ("icon-maskable-512.png", 512),
        ("apple-touch-icon.png", 180),
    ]:
        image = Image.open(BytesIO((icons / name).read_bytes())).convert("RGB")
        assert image.size == (size, size)
        assert image.getpixel((0, 0)) == (0x30, 0xA6, 0x9E)  # full-bleed background
        assert image.getpixel((size // 2, int(size * 0.55))) == (255, 255, 255)  # white car body
        # nothing but background outside the central 80%
        margin = int(size * 0.1) - 1
        assert image.crop((0, 0, size, margin)).getcolors(10) == [
            (size * margin, (0x30, 0xA6, 0x9E))
        ]
    assert "#30a69e" in (icons / "icon.svg").read_text()


def test_offline_page_is_static(client):
    assert client.get("/static/offline.html").status_code == 200
