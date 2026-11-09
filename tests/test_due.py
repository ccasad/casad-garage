import uuid
from datetime import date, timedelta

from sqlalchemy import func, select

from app import due
from app.models import DueItem, MileageReading, ServiceRecord, utcnow
from tests.conftest import make_car, make_user, sign_in
from tests.test_service import create as log_service
from tests.test_service import payload

TODAY = date.today()


def add_due(db, car, type="registration", days=None, miles=None, **kw):
    item = DueItem(
        car_id=car.id,
        type=type,
        due_date=TODAY + timedelta(days=days) if days is not None else None,
        due_miles=miles,
        **kw,
    )
    db.add(item)
    db.commit()
    return item


def set_miles(db, car, miles):
    db.add(MileageReading(car_id=car.id, on=TODAY, miles=miles))
    db.commit()


def test_the_due_soon_rule():
    def item(**kw):
        return DueItem(type="other", **kw)

    assert due.status(item(due_date=TODAY - timedelta(days=1)), None) == "overdue"
    assert due.status(item(due_date=TODAY), None) == "soon"
    assert due.status(item(due_date=TODAY + timedelta(days=30)), None) == "soon"
    assert due.status(item(due_date=TODAY + timedelta(days=31)), None) is None
    assert due.status(item(due_miles=60500), 60000) == "soon"
    assert due.status(item(due_miles=60501), 60000) is None
    assert due.status(item(due_miles=60000), 60000) == "overdue"
    assert due.status(item(due_miles=60500), None) is None
    assert due.status(item(due_date=TODAY - timedelta(days=5), done_at=utcnow()), None) is None


def test_adding_a_due_item(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)

    response = client.post(
        f"/cars/{car.id}/due",
        data={"type": "registration", "due_date": "2027-03-01", "due_miles": "", "notes": "renew"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    item = db.scalar(select(DueItem))
    assert (item.car_id, item.type, item.due_date, item.due_miles, item.notes) == (
        car.id,
        "registration",
        date(2027, 3, 1),
        None,
        "renew",
    )


def test_a_due_item_needs_a_date_or_mileage(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)

    response = client.post(f"/cars/{car.id}/due", data={"type": "other"})
    bad_type = client.post(f"/cars/{car.id}/due", data={"type": "nope", "due_miles": "5"})

    assert response.status_code == 422 and "a due date, a due mileage" in response.text
    assert bad_type.status_code == 422
    assert db.scalar(select(func.count()).select_from(DueItem)) == 0


def test_the_tab_lists_soonest_first_and_highlights(client, db, member):
    car = make_car(db, member)
    add_due(db, car, "registration", days=90)
    add_due(db, car, "state_inspection", days=-3)
    add_due(db, car, "oil_change", days=10)
    add_due(db, car, "other", miles=61000)
    set_miles(db, car, 60000)
    sign_in(client, db, member)
    client.post(f"/cars/{car.id}/select")

    page = client.get("/due").text

    order = [page.index(x) for x in ("State inspection", "Oil change", "Registration")]
    assert order == sorted(order)
    assert page.index("Registration") < page.index("61,000 mi")
    assert "Overdue" in page and "Due soon" in page
    assert page.count("Due soon") >= 1 and "1,000 mi to go" in page


def test_mark_done_edit_and_reopen(client, db, member):
    car = make_car(db, member)
    item = add_due(db, car, "registration", days=5)
    sign_in(client, db, member)
    client.post(f"/cars/{car.id}/select")

    client.post(f"/due/{item.id}/done")
    db.refresh(item)
    assert item.done_at is not None
    assert "Done (1)" in client.get("/due").text

    client.post(f"/due/{item.id}/reopen")
    db.refresh(item)
    assert item.done_at is None

    client.post(
        f"/due/{item.id}/edit",
        data={"type": "other", "due_date": "", "due_miles": "70000", "notes": ""},
    )
    db.refresh(item)
    assert (item.type, item.due_date, item.due_miles) == ("other", None, 70000)

    client.post(f"/due/{item.id}/delete")
    assert db.scalar(select(func.count()).select_from(DueItem)) == 0


def test_the_selector_dot_and_all_cars_show_due_soon(client, db, member):
    soon = make_car(db, member, nickname="Soonish")
    calm = make_car(db, member, nickname="Calm")
    add_due(db, soon, "registration", days=7)
    add_due(db, calm, "registration", days=200)
    sign_in(client, db, member)

    more = client.get("/more").text
    assert more.count("Due soon</span>") == 1
    cards = client.get("/cars").text
    assert "Registration:" in cards and cards.count("Registration:") == 1


def test_overview_shows_due_soon_banner(client, db, member):
    car = make_car(db, member)
    add_due(db, car, "registration", days=-2)
    sign_in(client, db, member)
    client.post(f"/cars/{car.id}/select")

    assert "Registration overdue" in client.get("/").text


def test_inspection_service_closes_the_open_item_and_offers_the_next(client, db, member):
    car = make_car(db, member)
    other_car = make_car(db, member)
    open_item = add_due(db, car, "state_inspection", days=-10)
    untouched = add_due(db, car, "registration", days=-10)
    elsewhere = add_due(db, other_car, "state_inspection", days=-10)
    sign_in(client, db, member)

    log_service(
        client,
        car,
        item_description=["State inspection"],
        item_type=["state_inspection"],
        item_part=[""],
        item_cost=[""],
        item_id=[""],
    )

    db.expire_all()
    assert open_item.done_at is not None
    assert untouched.done_at is None and elsewhere.done_at is None
    record = db.scalar(select(ServiceRecord))
    page = client.get(f"/service/{record.id}?saved=1").text
    assert "Set the next state inspection?" in page
    assert 'value="2027-02-10"' in page
    assert "Set the next" not in client.get(f"/service/{record.id}").text


def test_setting_the_next_due_item(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)
    log_service(
        client,
        car,
        item_description=["Oil change"],
        item_type=["oil_change"],
        item_part=[""],
        item_cost=[""],
        item_id=[""],
        miles="50000",
    )
    record = db.scalar(select(ServiceRecord))
    page = client.get(f"/service/{record.id}?saved=1").text
    assert 'value="55000"' in page

    response = client.post(
        f"/service/{record.id}/next-due",
        data={"type": "oil_change", "due_date": "2026-08-10", "due_miles": "55000"},
        follow_redirects=False,
    )

    assert response.headers["location"] == "/due"
    item = db.scalar(select(DueItem))
    assert (item.type, item.due_date, item.due_miles, item.done_at) == (
        "oil_change",
        date(2026, 8, 10),
        55000,
        None,
    )
    # Not offered for a type the record doesn't have, nor without a date or mileage
    assert (
        client.post(
            f"/service/{record.id}/next-due", data={"type": "registration", "due_miles": "1"}
        ).status_code
        == 422
    )
    assert (
        client.post(f"/service/{record.id}/next-due", data={"type": "oil_change"}).status_code
        == 422
    )


def test_other_service_types_make_no_offer(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)
    log_service(client, car)  # cabin filter and oil change; oil change is offered
    record = db.scalar(select(ServiceRecord))

    page = client.get(f"/service/{record.id}?saved=1").text

    assert "next oil change" in page and "next cabin" not in page


def test_private_car_due_items_404_for_others(client, db, member):
    owner = make_user(db, email="o@example.com")
    car = make_car(db, owner, visibility="private")
    item = add_due(db, car, "registration", days=3)
    sign_in(client, db, member)

    assert (
        client.post(f"/cars/{car.id}/due", data={"type": "other", "due_miles": "5"}).status_code
        == 404
    )
    for method, path in (
        ("get", "edit"),
        ("post", "edit"),
        ("post", "done"),
        ("post", "reopen"),
        ("post", "delete"),
    ):
        assert getattr(client, method)(f"/due/{item.id}/{path}").status_code == 404
    assert client.get(f"/due/{uuid.uuid4()}/edit").status_code == 404
    assert "Registration" not in client.get("/cars").text


def test_due_changes_reject_other_sites(client, db, member):
    car = make_car(db, member)
    item = add_due(db, car, "registration", days=3)
    sign_in(client, db, member)
    evil = {"Origin": "https://evil.example"}

    assert client.post(f"/cars/{car.id}/due", data={}, headers=evil).status_code == 403
    for action in ("edit", "done", "reopen", "delete"):
        assert client.post(f"/due/{item.id}/{action}", data={}, headers=evil).status_code == 403
    assert (
        payload()
        and client.post(f"/service/{uuid.uuid4()}/next-due", headers=evil).status_code == 403
    )


def test_deleting_a_car_deletes_its_due_items(client, db, member):
    car = make_car(db, member)
    add_due(db, car, "registration", days=3)
    sign_in(client, db, member)

    client.post(f"/cars/{car.id}/delete")

    assert db.scalar(select(func.count()).select_from(DueItem)) == 0


def test_overview_puts_photo_star_and_edit_in_one_row(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)
    client.post(f"/cars/{car.id}/select")

    html = client.get("/").text
    start = html.index("data-photo-row")
    row = html[start : html.index('id="photo-status"', start)]
    assert "data-photo-upload" in row
    assert f"/cars/{car.id}/star" in row
    assert f"/cars/{car.id}/edit" in row
    heading = html[html.index("<h2", html.index('id="photo-status"')) :].split(">", 1)[0]
    assert "truncate" not in heading
