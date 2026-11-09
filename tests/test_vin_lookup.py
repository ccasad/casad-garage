import httpx2
import pytest

from app import nhtsa
from tests.conftest import sign_in

FAKE_VIN = "1A4AA11AA1A111111"
ROW = {
    "ModelYear": "2019",
    "Make": "ACME",
    "Model": "Roadster",
    "Trim": "Sport",
    "DisplacementL": "2.998832712",
    "EngineCylinders": "6",
    "FuelTypePrimary": "Gasoline",
}


@pytest.fixture
def vpic(monkeypatch):
    """Replace the NHTSA client with a canned response and record the requests."""
    state = {
        "requests": [],
        "handler": lambda request: httpx2.Response(200, json={"Results": [ROW]}),
    }

    def handler(request):
        state["requests"].append(request)
        return state["handler"](request)

    monkeypatch.setattr(
        nhtsa, "http_client", lambda: httpx2.Client(transport=httpx2.MockTransport(handler))
    )
    return state


def lookup(client, **data):
    return client.post("/cars/vin-lookup", data={"vin": FAKE_VIN, **data})


def test_decoding_fills_the_fields(client, db, member, vpic):
    sign_in(client, db, member)

    page = lookup(client, color="Blue", plate="ABC").text

    assert 'value="2019"' in page and 'value="Acme"' in page and 'value="Roadster"' in page
    assert 'value="Sport"' in page and 'value="2.9L 6-cyl"' not in page and "3.0L 6-cyl" in page
    assert 'value="Blue"' in page and "Filled in from the VIN" in page
    assert vpic["requests"][0].url.path.endswith(f"/DecodeVinValues/{FAKE_VIN}")


def test_decoded_fields_replace_typed_ones_but_others_stay(client, db, member, vpic):
    vpic["handler"] = lambda r: httpx2.Response(200, json={"Results": [{**ROW, "Trim": ""}]})
    sign_in(client, db, member)

    page = lookup(client, trim="Typed trim", nickname="Mine").text

    assert 'value="Typed trim"' in page and 'value="Mine"' in page


def test_lookup_failure_says_so(client, db, member, vpic):
    vpic["handler"] = lambda r: httpx2.Response(503)
    sign_in(client, db, member)

    page = lookup(client, make="Typed").text

    assert "isn&#39;t available right now" in page and 'value="Typed"' in page
    assert FAKE_VIN in page  # the typed VIN stays in the field


def test_empty_result_says_nothing_found(client, db, member, vpic):
    vpic["handler"] = lambda r: httpx2.Response(200, json={"Results": [{"Make": "", "Model": ""}]})
    sign_in(client, db, member)

    assert "No vehicle was found" in lookup(client).text


def test_bad_vin_is_not_sent_to_nhtsa(client, db, member, vpic):
    sign_in(client, db, member)

    page = client.post("/cars/vin-lookup", data={"vin": "ab$"}).text

    assert "Enter the 17-character VIN" in page and vpic["requests"] == []


def test_lookup_needs_sign_in_and_same_origin(client, db, member, vpic):
    assert client.post(
        "/cars/vin-lookup", data={"vin": FAKE_VIN}, follow_redirects=False
    ).status_code in (204, 303)
    sign_in(client, db, member)
    evil = client.post(
        "/cars/vin-lookup", data={"vin": FAKE_VIN}, headers={"Origin": "https://evil.example"}
    )
    assert evil.status_code == 403 and vpic["requests"] == []


def test_the_form_has_a_look_up_button(client, db, member):
    sign_in(client, db, member)

    assert 'hx-post="/cars/vin-lookup"' in client.get("/cars/new").text


def test_short_vin_is_not_looked_up_and_shows_the_hint(client, db, member, vpic):
    sign_in(client, db, member)

    page = client.post("/cars/vin-lookup", data={"vin": "6T07T000000", "year": "1966"}).text

    assert "Pre-1981 VIN: enter the year, make and model yourself." in page
    assert "6T07T000000" in page and vpic["requests"] == []
    assert "disabled" in page


def test_vin_with_i_o_or_q_is_still_not_looked_up(client, db, member, vpic):
    sign_in(client, db, member)

    page = client.post("/cars/vin-lookup", data={"vin": "1A4AA11AA1A11111O"}).text

    assert "Enter the 17-character VIN" in page and vpic["requests"] == []
