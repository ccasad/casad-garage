import uuid

from sqlalchemy import func, select

from app.models import AuditEvent, Car, UserPrefs
from tests.conftest import make_car, make_user, sign_in

FAKE_VIN = "1A4AA11AA1A111111"


def add_car(client, **overrides):
    data = {"year": "2019", "make": "Acme", "model": "Roadster", **overrides}
    return client.post("/cars", data=data, follow_redirects=False)


def test_adding_a_car_selects_it(client, db, member):
    sign_in(client, db, member)

    response = add_car(client, nickname="Blue", vin=FAKE_VIN.lower(), plate="ABC123", notes="hi")

    assert response.status_code == 303
    car = db.scalar(select(Car))
    assert car.added_by_id == member.id
    assert car.vin == FAKE_VIN
    assert car.visibility == "shared"
    assert db.get(UserPrefs, member.id).selected_car_id == car.id
    page = client.get("/").text
    assert "Blue" in page and FAKE_VIN in page


def test_year_make_and_model_are_required(client, db, member):
    sign_in(client, db, member)

    response = client.post("/cars", data={"year": "abc", "make": "", "model": ""})

    assert response.status_code == 422
    assert "Make is required" in response.text and "Enter a 4-digit year" in response.text
    assert db.scalar(select(func.count()).select_from(Car)) == 0


def test_a_bad_vin_is_rejected(client, db, member):
    sign_in(client, db, member)

    assert add_car(client, vin="NOTAVIN").status_code == 422


def test_vin_and_plate_are_encrypted_at_rest(client, db, member, engine):
    sign_in(client, db, member)
    add_car(client, vin=FAKE_VIN, plate="ZZZ999", notes="secret note")

    with engine.connect() as conn:
        raw = conn.exec_driver_sql("select vin, plate, notes, vin_hash from cars").one()
    for value in raw:
        assert FAKE_VIN.encode() not in value and b"ZZZ999" not in value
        assert b"secret note" not in value


def test_editing_any_visible_car(client, db, member):
    other = make_user(db, email="o@example.com")
    car = make_car(db, other)
    sign_in(client, db, member)

    assert "Roadster" in client.get(f"/cars/{car.id}/edit").text
    response = client.post(
        f"/cars/{car.id}/edit",
        data={"year": "2020", "make": "Acme", "model": "Hauler", "color": "Red"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    db.refresh(car)
    assert (car.year, car.model, car.color) == (2020, "Hauler", "Red")


def test_selecting_a_car_is_remembered(client, db, member):
    first = make_car(db, member, nickname="First")
    second = make_car(db, member, nickname="Second")
    sign_in(client, db, member)

    assert "Pick a car above" in client.get("/").text
    client.post(f"/cars/{second.id}/select")
    assert "Second" in client.get("/").text
    client.post(f"/cars/{first.id}/select", data={"next": "/service"})
    db.expire_all()
    assert db.get(UserPrefs, member.id).selected_car_id == first.id


def test_select_redirects_only_to_known_tabs(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)

    ok = client.post(f"/cars/{car.id}/select", data={"next": "/due"}, follow_redirects=False)
    bad = client.post(
        f"/cars/{car.id}/select", data={"next": "https://evil.example"}, follow_redirects=False
    )

    assert ok.headers["location"] == "/due"
    assert bad.headers["location"] == "/"


def test_selector_lists_cars_all_cars_and_add(client, db, member):
    make_car(db, member, nickname="Daily")
    sign_in(client, db, member)

    page = client.get("/more").text

    assert "Daily" in page and "All cars" in page and "Add a car" in page


def test_all_cars_shows_a_card_per_car(client, db, member):
    make_car(db, member, nickname="Daily", trim="Sport", color="Green")
    sign_in(client, db, member)

    page = client.get("/cars").text

    assert "Daily" in page and "Sport" in page and "Green" in page


def test_only_the_adder_or_admin_may_delete(client, db, member, admin):
    owner = make_user(db, email="owner@example.com")
    car = make_car(db, owner)
    sign_in(client, db, member)

    assert client.post(f"/cars/{car.id}/delete").status_code == 403
    assert "Delete this car" not in client.post(f"/cars/{car.id}/select").text
    client.post(f"/cars/{car.id}/select")
    assert "Delete this car" not in client.get("/").text

    sign_in(client, db, admin)
    client.post(f"/cars/{car.id}/select")
    assert "Delete this car" in client.get("/").text
    assert client.post(f"/cars/{car.id}/delete", follow_redirects=False).status_code == 303
    assert db.scalar(select(func.count()).select_from(Car)) == 0
    assert [e.event for e in db.scalars(select(AuditEvent))] == ["car_deleted"]


def test_the_adder_can_delete_and_selection_resets(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)
    client.post(f"/cars/{car.id}/select")

    client.post(f"/cars/{car.id}/delete")

    assert "Pick a car above" in client.get("/").text or "No cars yet" in client.get("/").text


def test_unknown_cars_404(client, db, member):
    sign_in(client, db, member)
    missing = uuid.uuid4()

    for path in (f"/cars/{missing}/edit",):
        assert client.get(path).status_code == 404
    assert client.post(f"/cars/{missing}/select").status_code == 404
    assert client.post(f"/cars/{missing}/delete").status_code == 404


def test_car_changes_reject_other_sites(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)
    evil = {"Origin": "https://evil.example"}

    assert client.post("/cars", data={}, headers=evil).status_code == 403
    assert client.post(f"/cars/{car.id}/edit", data={}, headers=evil).status_code == 403
    assert client.post(f"/cars/{car.id}/select", headers=evil).status_code == 403
    assert client.post(f"/cars/{car.id}/delete", headers=evil).status_code == 403
    assert db.scalar(select(func.count()).select_from(Car)) == 1


def test_deleting_a_user_deletes_their_cars(client, db, member):
    make_car(db, member)
    sign_in(client, db, member)

    client.post("/account/delete", data={"confirm": "DELETE"})

    assert db.scalar(select(func.count()).select_from(Car)) == 0
