import uuid
from datetime import date

from sqlalchemy import func, select

from app.models import MileageReading
from tests.conftest import make_car, make_user, sign_in


def add(db, car, on, miles):
    reading = MileageReading(car_id=car.id, on=on, miles=miles)
    db.add(reading)
    db.commit()
    return reading


def test_adding_a_reading(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)

    response = client.post(
        f"/cars/{car.id}/mileage",
        data={"on": "2026-03-01", "miles": "52,100"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    reading = db.scalar(select(MileageReading))
    assert (reading.car_id, reading.on, reading.miles) == (car.id, date(2026, 3, 1), 52100)


def test_the_newest_reading_by_date_is_current(client, db, member):
    car = make_car(db, member)
    add(db, car, date(2026, 5, 1), 60000)
    add(db, car, date(2026, 6, 1), 61500)
    add(db, car, date(2026, 4, 1), 70000)  # entered last but older
    sign_in(client, db, member)
    client.post(f"/cars/{car.id}/select")

    assert "61,500 mi" in client.get("/").text
    assert "61,500 mi" in client.get("/cars").text


def test_history_lists_newest_first(client, db, member):
    car = make_car(db, member)
    add(db, car, date(2026, 1, 1), 1111)
    add(db, car, date(2026, 3, 1), 3333)
    add(db, car, date(2026, 2, 1), 2222)
    sign_in(client, db, member)
    client.post(f"/cars/{car.id}/select")

    page = client.get("/mileage").text

    assert page.index("3,333") < page.index("2,222") < page.index("1,111")


def test_bad_input_is_explained(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)

    response = client.post(f"/cars/{car.id}/mileage", data={"on": "", "miles": "lots"})

    assert response.status_code == 422
    assert "Enter a date" in response.text and "whole number" in response.text
    assert db.scalar(select(func.count()).select_from(MileageReading)) == 0


def test_edit_and_delete_a_reading(client, db, member):
    car = make_car(db, member)
    reading = add(db, car, date(2026, 1, 1), 1000)
    sign_in(client, db, member)

    assert "1000" in client.get(f"/mileage/{reading.id}/edit").text
    client.post(f"/mileage/{reading.id}/edit", data={"on": "2026-01-02", "miles": "1200"})
    db.refresh(reading)
    assert (reading.on, reading.miles) == (date(2026, 1, 2), 1200)

    client.post(f"/mileage/{reading.id}/delete")
    assert db.scalar(select(func.count()).select_from(MileageReading)) == 0


def test_other_users_private_readings_404(client, db, member):
    owner = make_user(db, email="o@example.com")
    car = make_car(db, owner, visibility="private")
    reading = add(db, car, date(2026, 1, 1), 1000)
    sign_in(client, db, member)

    assert (
        client.post(f"/cars/{car.id}/mileage", data={"on": "2026-01-01", "miles": "1"}).status_code
        == 404
    )
    assert client.get(f"/mileage/{reading.id}/edit").status_code == 404
    assert (
        client.post(
            f"/mileage/{reading.id}/edit", data={"on": "2026-01-01", "miles": "5"}
        ).status_code
        == 404
    )
    assert client.post(f"/mileage/{reading.id}/delete").status_code == 404
    assert client.post(f"/mileage/{uuid.uuid4()}/delete").status_code == 404
    db.refresh(reading)
    assert reading.miles == 1000


def test_shared_readings_can_be_edited_by_anyone(client, db, member):
    owner = make_user(db, email="o@example.com")
    car = make_car(db, owner)
    reading = add(db, car, date(2026, 1, 1), 1000)
    sign_in(client, db, member)

    client.post(f"/mileage/{reading.id}/edit", data={"on": "2026-01-01", "miles": "2000"})

    db.refresh(reading)
    assert reading.miles == 2000


def test_mileage_changes_reject_other_sites(client, db, member):
    car = make_car(db, member)
    reading = add(db, car, date(2026, 1, 1), 1000)
    sign_in(client, db, member)
    evil = {"Origin": "https://evil.example"}

    assert client.post(f"/cars/{car.id}/mileage", data={}, headers=evil).status_code == 403
    assert client.post(f"/mileage/{reading.id}/edit", data={}, headers=evil).status_code == 403
    assert client.post(f"/mileage/{reading.id}/delete", headers=evil).status_code == 403


def test_deleting_a_car_deletes_its_readings(client, db, member):
    car = make_car(db, member)
    add(db, car, date(2026, 1, 1), 1000)
    sign_in(client, db, member)

    client.post(f"/cars/{car.id}/delete")

    assert db.scalar(select(func.count()).select_from(MileageReading)) == 0
