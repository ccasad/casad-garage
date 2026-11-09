import json
from datetime import date

from sqlalchemy import select

from app.models import AuditEvent, Car, DueItem, MileageReading, ServiceRecord
from tests.conftest import make_car, make_user, sign_in
from tests.test_service import create as log_service


def setup_private(db, owner):
    car = make_car(db, owner, visibility="private", nickname="Secret Car", vin="1A4AA11AA1A111111")
    db.add(MileageReading(car_id=car.id, on=date(2026, 1, 1), miles=12345))
    db.add(DueItem(car_id=car.id, type="registration", due_date=date(2030, 1, 1)))
    db.commit()
    return car


def test_adding_a_car_as_only_me(client, db, member):
    sign_in(client, db, member)

    client.post("/cars", data={"year": "2020", "make": "A", "model": "B", "visibility": "private"})

    assert db.scalar(select(Car)).visibility == "private"
    assert [e.detail["visibility"] for e in db.scalars(select(AuditEvent))] == ["private"]


def test_others_never_see_a_private_car(client, db, member):
    owner = make_user(db, email="o@example.com")
    car = setup_private(db, owner)
    sign_in(client, db, member)

    for path in ("/", "/cars", "/more", "/service", "/due", "/todo", "/mileage"):
        assert "Secret Car" not in client.get(path).text
    assert client.get(f"/cars/{car.id}/edit").status_code == 404
    assert client.post(f"/cars/{car.id}/select").status_code == 404
    assert (
        client.post(
            f"/cars/{car.id}/edit", data={"year": "1", "make": "a", "model": "b"}
        ).status_code
        == 404
    )
    assert client.post(f"/cars/{car.id}/delete").status_code == 404
    db.refresh(car)
    assert car.nickname == "Secret Car"


def test_not_even_the_admin_sees_it(client, db, admin):
    owner = make_user(db, email="o@example.com")
    car = setup_private(db, owner)
    sign_in(client, db, admin)

    assert "Secret Car" not in client.get("/cars").text
    assert client.post(f"/cars/{car.id}/delete").status_code == 404


def test_the_owner_sees_it(client, db, member):
    car = setup_private(db, member)
    sign_in(client, db, member)

    assert "Secret Car" in client.get("/cars").text
    assert "Only me" in client.get("/more").text
    client.post(f"/cars/{car.id}/select")
    assert "Only me" in client.get("/").text


def test_downloads_leave_out_other_peoples_private_cars(client, db, member):
    owner = make_user(db, email="o@example.com")
    setup_private(db, owner)
    make_car(db, owner, nickname="Family Van")
    sign_in(client, db, member)

    text = client.get("/account/export").text

    assert "Secret Car" not in text and "1A4AA11AA1A111111" not in text and "12345" not in text
    assert "Family Van" in text


def test_owner_download_includes_it(client, db, member):
    setup_private(db, member)
    sign_in(client, db, member)

    data = json.loads(client.get("/account/export").text)

    car = data["cars"][0]
    assert (car["nickname"], car["vin"], car["added_by_me"]) == (
        "Secret Car",
        "1A4AA11AA1A111111",
        True,
    )
    assert car["mileage_readings"] == [{"date": "2026-01-01", "miles": 12345}]
    assert car["due_items"][0]["type"] == "registration"


def test_only_the_adder_can_change_visibility(client, db, member):
    owner = make_user(db, email="o@example.com")
    car = make_car(db, owner)
    sign_in(client, db, member)
    data = {"year": "2019", "make": "Acme", "model": "Roadster", "visibility": "private"}

    assert "Who can see this car" not in client.get(f"/cars/{car.id}/edit").text
    client.post(f"/cars/{car.id}/edit", data=data)
    db.refresh(car)
    assert car.visibility == "shared"

    sign_in(client, db, owner)
    assert "Who can see this car" in client.get(f"/cars/{car.id}/edit").text
    client.post(f"/cars/{car.id}/edit", data=data)
    db.refresh(car)
    assert car.visibility == "private"
    event = db.scalar(select(AuditEvent).where(AuditEvent.event == "car_visibility_changed"))
    assert event.user_id == owner.id and event.detail["to"] == "private"


def test_making_a_car_private_hides_it_and_resets_others_selection(client, db, member):
    owner = make_user(db, email="o@example.com")
    car = make_car(db, owner, nickname="Was Shared")
    sign_in(client, db, member)
    client.post(f"/cars/{car.id}/select")
    assert "Was Shared" in client.get("/").text

    car.visibility = "private"
    db.commit()

    page = client.get("/").text
    assert "Was Shared" not in page and "No cars yet" in page


def test_attached_records_are_hidden_with_the_car(client, db, member):
    owner = make_user(db, email="o@example.com")
    car = make_car(db, owner, visibility="private")
    sign_in(client, db, owner)
    log_service(client, car)
    record = db.scalar(select(ServiceRecord))
    client.cookies.clear()
    sign_in(client, db, member)

    assert client.get(f"/service/{record.id}").status_code == 404
    assert "Test Garage" not in client.get("/account/export").text
