from datetime import date

from sqlalchemy import select

from app.models import DueItem, ServiceRecord
from app.service import add_months
from tests.conftest import make_car, make_user, sign_in
from tests.test_service import create, payload


def battery(**overrides):
    return {
        "on": "2026-03-10",
        "miles": "50,000",
        "item_id": [""],
        "item_description": ["Battery"],
        "item_type": ["battery"],
        "item_part": ["Brand B"],
        "item_cost": ["150"],
        "item_warranty_months": ["36"],
        "item_warranty_miles": [""],
        **overrides,
    }


def warranty_items(db):
    db.expire_all()
    return list(db.scalars(select(DueItem).where(DueItem.type == "warranty_ends")))


def test_add_months_clamps_to_the_month_end():
    assert add_months(date(2026, 3, 10), 36) == date(2029, 3, 10)
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_months(date(2026, 11, 30), 3) == date(2027, 2, 28)
    assert add_months(date(2026, 12, 15), 12) == date(2027, 12, 15)


def test_a_warranty_adds_a_warranty_ends_due_item(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)

    create(client, car, **battery())

    (due,) = warranty_items(db)
    assert (due.car_id, due.due_date, due.due_miles, due.source) == (
        car.id,
        date(2029, 3, 10),
        None,
        "warranty",
    )
    assert due.notes == "Warranty on Battery" and due.service_item_id is not None


def test_warranty_in_miles_and_months_together(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)

    create(client, car, **battery(item_warranty_miles=["36,000"]))

    (due,) = warranty_items(db)
    assert (due.due_date, due.due_miles) == (date(2029, 3, 10), 86000)


def test_miles_only_warranty_needs_the_service_mileage(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)

    bad = create(
        client, car, **battery(miles="", item_warranty_months=[""], item_warranty_miles=["10000"])
    )
    assert bad.status_code == 422 and warranty_items(db) == []

    ok = create(client, car, **battery(item_warranty_months=[""], item_warranty_miles=["10000"]))
    assert ok.status_code == 303
    (due,) = warranty_items(db)
    assert (due.due_date, due.due_miles) == (None, 60000)


def test_bad_warranty_values_are_rejected(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)

    response = create(client, car, **battery(item_warranty_months=["three"]))

    assert response.status_code == 422 and "Warranties are whole months" in response.text


def test_editing_updates_and_removing_deletes_the_due_item(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)
    create(client, car, **battery())
    record = db.scalar(select(ServiceRecord))
    item_id = str(record.items[0].id)

    client.post(
        f"/service/{record.id}/edit", data=battery(item_id=[item_id], item_warranty_months=["24"])
    )
    (due,) = warranty_items(db)
    assert due.due_date == date(2028, 3, 10)

    client.post(
        f"/service/{record.id}/edit", data=battery(item_id=[item_id], item_warranty_months=[""])
    )
    assert warranty_items(db) == []


def test_deleting_the_record_or_the_item_removes_it(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)
    create(client, car, **battery())
    record = db.scalar(select(ServiceRecord))

    client.post(f"/service/{record.id}/delete")

    assert warranty_items(db) == []


def test_a_warranty_ending_soon_is_due_soon_and_listed(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)
    client.post(f"/cars/{car.id}/select")
    create(client, car, **battery(on="2026-01-01", item_warranty_months=["1"]))
    due = warranty_items(db)[0]
    due.due_date = date.today()
    db.commit()

    page = client.get("/due").text

    assert "Warranty ends" in page and "Warranty on Battery" in page and "Due soon" in page
    assert f"/due/{due.id}/edit" not in page  # follows the service item, so no editing here
    assert (
        client.post(f"/due/{due.id}/edit", data={"type": "other", "due_miles": "5"}).status_code
        == 422
    )
    assert (
        "Warranty: 1 months" in client.get(f"/service/{db.scalar(select(ServiceRecord)).id}").text
    )


def test_warranty_due_items_of_private_cars_stay_private(client, db, member):
    owner = make_user(db, email="o@example.com")
    car = make_car(db, owner, visibility="private")
    sign_in(client, db, owner)
    create(client, car, **battery())
    client.cookies.clear()
    sign_in(client, db, member)

    (due,) = warranty_items(db)
    assert client.post(f"/due/{due.id}/done").status_code == 404
    assert payload()
