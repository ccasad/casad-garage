from tests.conftest import sign_in


def test_every_page_has_the_tab_bar_hook_and_the_keyboard_script(client, db, member):
    sign_in(client, db, member)

    page = client.get("/cars/new").text

    assert "data-tabbar" in page and "js/app.js" in page
    script = client.get("/static/js/app.js").text
    assert "keyboard-open" in script and "focusin" in script and "focusout" in script
    css = client.get("/static/css/app.css").text
    assert "body.keyboard-open [data-tabbar]" in css or "keyboard-open" in css


def test_the_car_form_has_the_vin_hint_hooks(client, db, member):
    sign_in(client, db, member)

    page = client.get("/cars/new").text

    assert "data-vin-input" in page and "data-vin-lookup" in page and "data-vin-hint" in page
    assert "Pre-1981 VIN: enter the year, make and model yourself." in page
