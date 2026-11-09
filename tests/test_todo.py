import uuid
from datetime import date

from sqlalchemy import func, select

from app.models import MileageReading, RecommendedItem, ServiceRecord
from tests.conftest import make_car, make_user, sign_in


def add(db, car, description="Rear brakes", price=32000, status="open", **kw):
    item = RecommendedItem(
        car_id=car.id, description=description, price_cents=price, status=status, **kw
    )
    db.add(item)
    db.commit()
    return item


def selected(client, db, user, car):
    sign_in(client, db, user)
    client.post(f"/cars/{car.id}/select")


def test_adding_work_by_hand_defaults_to_current_mileage(client, db, member):
    car = make_car(db, member)
    db.add(MileageReading(car_id=car.id, on=date(2026, 1, 1), miles=70500))
    db.commit()
    sign_in(client, db, member)

    response = client.post(
        f"/cars/{car.id}/todo",
        data={
            "description": "Wiper blades",
            "note": "both sides",
            "price": "$24.50",
            "on": "2026-03-01",
        },
        follow_redirects=False,
    )

    assert response.headers["location"] == "/todo"
    item = db.scalar(select(RecommendedItem))
    assert (item.description, item.shop_note, item.price_cents, item.recommended_on) == (
        "Wiper blades",
        "both sides",
        2450,
        date(2026, 3, 1),
    )
    assert (item.recommended_miles, item.status) == (70500, "open")


def test_validation(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)

    response = client.post(
        f"/cars/{car.id}/todo", data={"description": " ", "price": "lots", "on": "x"}
    )

    assert response.status_code == 422
    for text in ("Describe the work", "like 89.99", "Enter a valid date"):
        assert text in response.text
    assert db.scalar(select(func.count()).select_from(RecommendedItem)) == 0


def test_the_tab_lists_open_items_with_the_total(client, db, member):
    car = make_car(db, member)
    add(db, car, "Rear brakes", 32000, shop_note="Pads at 3mm")
    add(db, car, "Cabin air filter", 4550)
    add(db, car, "Look at the noise", None)
    add(db, car, "Old thing", 99900, status="dismissed")
    selected(client, db, member, car)

    page = client.get("/todo").text

    assert "$365.50" in page and "1 item without a quoted price" in page
    assert "Pads at 3mm" in page and "Rear brakes" in page
    assert "History (1)" in page and "Old thing" in page
    assert "$999.00" not in page


def test_mark_done_with_a_linked_record(client, db, member):
    car = make_car(db, member)
    item = add(db, car)
    record = ServiceRecord(car_id=car.id, on=date(2026, 4, 1), shop="Fix It")
    db.add(record)
    db.commit()
    selected(client, db, member, car)
    assert "Fix It" in client.get("/todo").text  # offered in the link choice

    client.post(f"/todo/{item.id}/done", data={"record_id": str(record.id)})

    db.refresh(item)
    assert (item.status, item.done_record_id) == ("done", record.id)
    assert item.closed_at is not None
    page = client.get("/todo").text
    assert "History (1)" in page and f"/service/{record.id}" in page and "$320.00" not in page


def test_mark_done_without_a_link_and_dismiss_and_reopen(client, db, member):
    car = make_car(db, member)
    first, second = add(db, car, "One"), add(db, car, "Two")
    selected(client, db, member, car)

    client.post(f"/todo/{first.id}/done")
    client.post(f"/todo/{second.id}/dismiss")
    db.refresh(first)
    db.refresh(second)
    assert (first.status, first.done_record_id, second.status) == ("done", None, "dismissed")
    assert "Nothing recommended" in client.get("/todo").text

    client.post(f"/todo/{second.id}/reopen")
    db.refresh(second)
    assert (second.status, second.closed_at) == ("open", None)


def test_a_record_from_another_car_cannot_be_linked(client, db, member):
    car, other = make_car(db, member), make_car(db, member)
    item = add(db, car)
    foreign = ServiceRecord(car_id=other.id, on=date(2026, 4, 1))
    db.add(foreign)
    db.commit()
    sign_in(client, db, member)

    assert (
        client.post(f"/todo/{item.id}/done", data={"record_id": str(foreign.id)}).status_code == 422
    )
    assert client.post(f"/todo/{item.id}/done", data={"record_id": "nope"}).status_code == 422
    db.refresh(item)
    assert item.status == "open"


def test_editing(client, db, member):
    car = make_car(db, member)
    item = add(db, car)
    sign_in(client, db, member)

    assert "Rear brakes" in client.get(f"/todo/{item.id}/edit").text
    client.post(
        f"/todo/{item.id}/edit",
        data={"description": "Front brakes", "price": "100", "note": "", "on": "", "miles": ""},
    )

    db.refresh(item)
    assert (item.description, item.price_cents, item.shop_note, item.recommended_miles) == (
        "Front brakes",
        10000,
        None,
        None,
    )
    assert client.post(f"/todo/{item.id}/edit", data={"description": ""}).status_code == 422


def test_other_peoples_private_work_404s(client, db, member):
    owner = make_user(db, email="o@example.com")
    car = make_car(db, owner, visibility="private")
    item = add(db, car, "Secret job")
    sign_in(client, db, member)

    assert client.post(f"/cars/{car.id}/todo", data={"description": "x"}).status_code == 404
    for method, path in (
        ("get", "edit"),
        ("post", "edit"),
        ("post", "done"),
        ("post", "dismiss"),
        ("post", "reopen"),
    ):
        assert getattr(client, method)(f"/todo/{item.id}/{path}").status_code == 404
    assert client.get(f"/todo/{uuid.uuid4()}/edit").status_code == 404
    assert "Secret job" not in client.get("/todo").text
    assert "Secret job" not in client.get("/account/export").text


def test_todo_changes_reject_other_sites(client, db, member):
    car = make_car(db, member)
    item = add(db, car)
    sign_in(client, db, member)
    evil = {"Origin": "https://evil.example"}

    assert client.post(f"/cars/{car.id}/todo", data={}, headers=evil).status_code == 403
    for action in ("edit", "done", "dismiss", "reopen"):
        assert client.post(f"/todo/{item.id}/{action}", data={}, headers=evil).status_code == 403
    db.refresh(item)
    assert item.status == "open"


def test_deleting_a_car_deletes_its_work_list(client, db, member):
    car = make_car(db, member)
    add(db, car)
    sign_in(client, db, member)

    client.post(f"/cars/{car.id}/delete")

    assert db.scalar(select(func.count()).select_from(RecommendedItem)) == 0


def test_export_includes_recommended_work(client, db, member):
    car = make_car(db, member)
    add(db, car, "Rear brakes", 32000)
    sign_in(client, db, member)

    work = client.get("/account/export").json()["cars"][0]["recommended_work"]

    assert work[0]["description"] == "Rear brakes" and work[0]["quoted_price"] == "320.00"
