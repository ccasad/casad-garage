import uuid
from datetime import date

from sqlalchemy import func, select

from app.models import MileageReading, ServiceItem, ServiceRecord
from tests.conftest import make_car, make_user, sign_in


def payload(**overrides):
    data = {
        "on": "2026-02-10",
        "miles": "52,100",
        "shop": "Test Garage",
        "ro_number": "1001",
        "total": "",
        "notes": "all good",
        "item_id": ["", ""],
        "item_description": ["Cabin filter", "Oil change"],
        "item_type": ["cabin_air_filter", "oil_change"],
        "item_part": ["Acme CF-1", ""],
        "item_cost": ["30.00", "$59.99"],
    }
    data.update(overrides)
    return data


def create(client, car, **overrides):
    return client.post(f"/cars/{car.id}/service", data=payload(**overrides), follow_redirects=False)


def test_logging_a_service(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)

    response = create(client, car)

    record = db.scalar(select(ServiceRecord))
    assert response.headers["location"] == f"/service/{record.id}?saved=1"
    assert (record.on, record.miles, record.shop, record.ro_number) == (
        date(2026, 2, 10),
        52100,
        "Test Garage",
        "1001",
    )
    assert record.total_cents == 8999  # no total typed: the items add up
    assert [(i.description, i.type, i.part, i.cost_cents) for i in record.items] == [
        ("Cabin filter", "cabin_air_filter", "Acme CF-1", 3000),
        ("Oil change", "oil_change", None, 5999),
    ]
    page = client.get(f"/service/{record.id}").text
    assert "Cabin filter" in page and "$89.99" in page and "Acme CF-1" in page


def test_a_typed_total_wins(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)

    create(client, car, total="100")

    assert db.scalar(select(ServiceRecord)).total_cents == 10000


def test_saving_adds_the_odometer_reading(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)

    create(client, car)

    reading = db.scalar(select(MileageReading))
    assert (reading.car_id, reading.on, reading.miles) == (car.id, date(2026, 2, 10), 52100)
    assert reading.service_record_id is not None


def test_no_mileage_adds_no_reading_and_editing_updates_it(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)
    create(client, car, miles="")
    record = db.scalar(select(ServiceRecord))
    assert db.scalar(select(func.count()).select_from(MileageReading)) == 0

    client.post(
        f"/service/{record.id}/edit",
        data=payload(miles="60000", item_id=[str(i.id) for i in record.items]),
    )
    assert db.scalar(select(MileageReading)).miles == 60000
    client.post(
        f"/service/{record.id}/edit",
        data=payload(miles="61000", item_id=[str(i.id) for i in record.items]),
    )
    assert db.scalar(select(func.count()).select_from(MileageReading)) == 1
    assert db.scalar(select(MileageReading)).miles == 61000
    client.post(
        f"/service/{record.id}/edit",
        data=payload(miles="", item_id=[str(i.id) for i in record.items]),
    )
    assert db.scalar(select(func.count()).select_from(MileageReading)) == 0


def test_validation(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)

    no_items = create(
        client,
        car,
        item_description=[""],
        item_type=["other"],
        item_part=[""],
        item_cost=[""],
        item_id=[""],
    )
    assert no_items.status_code == 422 and "Add at least one item" in no_items.text
    bad = create(
        client, car, on="", miles="x", total="abc", item_description=["", "ok"], item_cost=["x", ""]
    )
    assert bad.status_code == 422
    for text in ("Enter a date", "whole number", "like 89.99", "needs a description"):
        assert text in bad.text
    assert db.scalar(select(func.count()).select_from(ServiceRecord)) == 0


def test_editing_keeps_and_removes_items(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)
    create(client, car)
    record = db.scalar(select(ServiceRecord))
    first = record.items[0]

    client.post(
        f"/service/{record.id}/edit",
        data=payload(
            item_id=[str(first.id)],
            item_description=["Cabin filter (new)"],
            item_type=["cabin_air_filter"],
            item_part=[""],
            item_cost=["31"],
            total="",
        ),
    )

    db.expire_all()
    assert [i.description for i in db.scalars(select(ServiceItem))] == ["Cabin filter (new)"]
    assert db.scalar(select(ServiceItem)).id == first.id
    assert db.scalar(select(ServiceRecord)).total_cents == 3100


def test_the_list_is_newest_first_with_filter_and_search(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)
    client.post(f"/cars/{car.id}/select")
    create(
        client,
        car,
        on="2026-01-01",
        shop="Alpha Shop",
        item_description=["Tires rotated"],
        item_type=["tires"],
        item_part=[""],
        item_cost=[""],
        item_id=[""],
    )
    create(
        client,
        car,
        on="2026-03-01",
        shop="Beta Shop",
        item_description=["New wipers"],
        item_type=["other"],
        item_part=["Brand W"],
        item_cost=[""],
        item_id=[""],
    )

    page = client.get("/service").text
    assert page.index("Beta Shop") < page.index("Alpha Shop")

    only_tires = client.get("/service?type=tires").text
    assert "Alpha Shop" in only_tires and "Beta Shop" not in only_tires
    found = client.get("/service?q=brand w").text
    assert "Beta Shop" in found and "Alpha Shop" not in found
    assert "No records match" in client.get("/service?q=zzz").text


def test_overview_shows_last_done_per_type(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)
    client.post(f"/cars/{car.id}/select")
    create(client, car, on="2025-06-01", miles="40000")
    create(client, car, on="2026-02-10", miles="52100")

    page = client.get("/").text

    assert "Cabin air filter" in page and "Feb 2026, 52,100 mi" in page
    assert "Jun 2025" not in page


def test_deleting_a_record_removes_its_reading(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)
    create(client, car)
    record = db.scalar(select(ServiceRecord))

    client.post(f"/service/{record.id}/delete")

    for model in (ServiceRecord, ServiceItem, MileageReading):
        assert db.scalar(select(func.count()).select_from(model)) == 0


def test_other_users_private_car_records_404(client, db, member):
    owner = make_user(db, email="o@example.com")
    car = make_car(db, owner, visibility="private")
    sign_in(client, db, owner)
    create(client, car)
    record = db.scalar(select(ServiceRecord))
    client.cookies.clear()
    sign_in(client, db, member)

    assert create(client, car).status_code == 404
    for path in (f"/service/{record.id}", f"/service/{record.id}/edit"):
        assert client.get(path).status_code == 404
    assert client.post(f"/service/{record.id}/edit", data=payload()).status_code == 404
    assert client.post(f"/service/{record.id}/delete").status_code == 404
    assert client.get(f"/service/{uuid.uuid4()}").status_code == 404
    assert db.scalar(select(func.count()).select_from(ServiceRecord)) == 1


def test_shared_records_can_be_edited_by_anyone(client, db, member):
    owner = make_user(db, email="o@example.com")
    car = make_car(db, owner)
    sign_in(client, db, member)
    create(client, car)
    record = db.scalar(select(ServiceRecord))

    assert client.get(f"/service/{record.id}/edit").status_code == 200


def test_service_changes_reject_other_sites(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)
    create(client, car)
    record = db.scalar(select(ServiceRecord))
    evil = {"Origin": "https://evil.example"}

    assert client.post(f"/cars/{car.id}/service", data=payload(), headers=evil).status_code == 403
    assert (
        client.post(f"/service/{record.id}/edit", data=payload(), headers=evil).status_code == 403
    )
    assert client.post(f"/service/{record.id}/delete", headers=evil).status_code == 403


def test_notes_are_encrypted_at_rest(client, db, member, engine):
    car = make_car(db, member)
    sign_in(client, db, member)
    create(client, car, notes="very private words")

    with engine.connect() as conn:
        raw = conn.exec_driver_sql("select notes from service_records").scalar()
    assert b"very private" not in raw


def test_deleting_a_car_deletes_its_service(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)
    create(client, car)

    client.post(f"/cars/{car.id}/delete")

    assert db.scalar(select(func.count()).select_from(ServiceRecord)) == 0
    assert db.scalar(select(func.count()).select_from(ServiceItem)) == 0
