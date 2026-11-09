from types import SimpleNamespace

from app.routes import auth
from app.theme import THEME_COOKIE
from tests.conftest import sign_in
from tests.test_auth import add_passkey


def html_theme(page: str) -> str:
    return page.split('data-theme="', 1)[1].split('"', 1)[0]


def test_dark_is_the_default(client, db, member):
    assert html_theme(client.get("/login").text) == "dark"
    sign_in(client, db, member)
    assert member.theme == "dark"
    assert html_theme(client.get("/").text) == "dark"


def test_choosing_light_saves_it_on_the_account(client, db, member):
    sign_in(client, db, member)

    response = client.post("/settings/theme", data={"theme": "light"}, follow_redirects=False)

    assert response.headers["location"] == "/more"
    assert response.cookies[THEME_COOKIE] == "light"
    db.refresh(member)
    assert member.theme == "light"
    page = client.get("/more").text
    assert html_theme(page) == "light"
    assert '<meta name="color-scheme" content="light">' in page
    assert 'value="light" aria-pressed="true"' in page


def test_choice_survives_signing_out(client, db, member):
    sign_in(client, db, member)
    client.post("/settings/theme", data={"theme": "light"})

    client.post("/logout")

    assert html_theme(client.get("/login").text) == "light"


def test_signing_in_applies_the_accounts_theme_to_the_device(client, db, member, monkeypatch):
    member.theme = "system"
    db.commit()
    add_passkey(db, member)
    monkeypatch.setattr(
        auth, "verify_authentication_response", lambda **kwargs: SimpleNamespace(new_sign_count=1)
    )
    start = client.post("/auth/login/options").json()

    response = client.post(
        "/auth/login/verify",
        json={"challenge_id": start["challenge_id"], "credential": {"rawId": "Y3JlZGVudGlhbC0x"}},
    )

    assert response.cookies[THEME_COOKIE] == "system"
    page = client.get("/").text
    assert html_theme(page) == "system"
    assert 'media="(prefers-color-scheme: dark)"' in page


def test_theme_values_are_checked(client, db, member):
    sign_in(client, db, member)

    assert client.post("/settings/theme", data={"theme": "neon"}).status_code == 422
    assert (
        client.post(
            "/settings/theme", data={"theme": "light"}, headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
