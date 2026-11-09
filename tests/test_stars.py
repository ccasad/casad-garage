from datetime import date

from sqlalchemy import select

from app.models import CarStar, ServiceRecord, UserPrefs
from tests.conftest import make_car, make_user, sign_in


def names(page: str, *candidates: str) -> list[str]:
    return sorted(candidates, key=page.index)


def test_starred_cars_come_first_in_the_selector_and_all_cars(client, db, member):
    a = make_car(db, member, nickname="Alpha")
    make_car(db, member, nickname="Bravo")
    c = make_car(db, member, nickname="Charlie")
    sign_in(client, db, member)

    assert names(client.get("/cars").text, "Alpha", "Bravo", "Charlie") == [
        "Alpha",
        "Bravo",
        "Charlie",
    ]
    client.post(f"/cars/{c.id}/star")
    page = client.get("/cars").text
    assert names(page, "Alpha", "Bravo", "Charlie") == ["Charlie", "Alpha", "Bravo"]
    assert names(client.get("/more").text, "Alpha", "Bravo", "Charlie")[0] == "Charlie"
    client.post(f"/cars/{c.id}/star")  # toggles off
    assert names(client.get("/cars").text, "Alpha", "Bravo", "Charlie")[0] == "Alpha"
    assert a and db.scalars(select(CarStar)).all() == []


def test_stars_and_sort_are_personal(client, db, member, admin):
    car = make_car(db, member, nickname="Alpha")
    make_car(db, member, nickname="Zulu", year=2024)
    sign_in(client, db, member)
    client.post(f"/cars/{car.id}/star")
    client.post("/settings/car-sort", data={"sort": "year"})

    sign_in(client, db, admin)
    page = client.get("/cars").text
    assert names(page, "Alpha", "Zulu") == ["Alpha", "Zulu"]  # not starred, name order
    assert db.get(UserPrefs, admin.id) is None or db.get(UserPrefs, admin.id).car_sort == "name"


def test_sort_options(client, db, member):
    old = make_car(db, member, nickname="Old", year=2001)
    new = make_car(db, member, nickname="New", year=2024)
    never = make_car(db, member, nickname="Never", year=2010)
    db.add(ServiceRecord(car_id=old.id, on=date(2026, 5, 1)))
    db.add(ServiceRecord(car_id=new.id, on=date(2026, 1, 1)))
    db.commit()
    sign_in(client, db, member)

    client.post("/settings/car-sort", data={"sort": "year"})
    assert names(client.get("/cars").text, "Old", "New", "Never") == ["New", "Never", "Old"]
    client.post("/settings/car-sort", data={"sort": "serviced"})
    assert names(client.get("/cars").text, "Old", "New", "Never") == ["Old", "New", "Never"]
    client.post("/settings/car-sort", data={"sort": "name"})
    assert names(client.get("/cars").text, "Old", "New", "Never") == ["Never", "New", "Old"]
    assert never


def test_the_sort_is_remembered_and_validated(client, db, member):
    make_car(db, member)
    sign_in(client, db, member)

    assert client.post("/settings/car-sort", data={"sort": "random"}).status_code == 422
    client.post("/settings/car-sort", data={"sort": "year"})
    assert db.get(UserPrefs, member.id).car_sort == "year"
    assert '<option value="year" selected>' in client.get("/cars").text


def test_cannot_star_a_car_you_cannot_see(client, db, member):
    owner = make_user(db, email="o@example.com")
    car = make_car(db, owner, visibility="private")
    sign_in(client, db, member)

    assert client.post(f"/cars/{car.id}/star").status_code == 404
    assert db.scalars(select(CarStar)).all() == []


def test_star_and_sort_reject_other_sites(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)
    evil = {"Origin": "https://evil.example"}

    assert client.post(f"/cars/{car.id}/star", headers=evil).status_code == 403
    assert client.post("/settings/car-sort", data={"sort": "year"}, headers=evil).status_code == 403


def test_deleting_a_car_or_user_removes_stars(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)
    client.post(f"/cars/{car.id}/star")

    client.post(f"/cars/{car.id}/delete")

    assert db.scalars(select(CarStar)).all() == []
