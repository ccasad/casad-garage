from datetime import date

from sqlalchemy import select

from app.models import Car, DueItem, utcnow
from tests.conftest import make_car, make_user, sign_in

CAR = {"year": "2020", "make": "Acme", "model": "Hauler"}


def loan_items(db):
    db.expire_all()
    return list(db.scalars(select(DueItem).where(DueItem.type == "loan_payoff")))


def test_a_loan_adds_a_payoff_due_item(client, db, member):
    sign_in(client, db, member)

    client.post(
        "/cars",
        data={
            **CAR,
            "lender": "Example Credit Union",
            "loan_end": "2028-06-15",
            "loan_monthly": "$412.50",
        },
    )

    car = db.scalar(select(Car))
    assert car.loan == {
        "lender": "Example Credit Union",
        "final_date": "2028-06-15",
        "monthly_cents": 41250,
    }
    (item,) = loan_items(db)
    assert (item.car_id, item.due_date, item.source) == (car.id, date(2028, 6, 15), "loan")
    assert "Example Credit Union" in item.notes
    page = client.get("/").text
    assert "Loan: Example Credit Union" in page and "$412.50 a month" in page


def test_the_monthly_amount_is_optional(client, db, member):
    sign_in(client, db, member)

    client.post("/cars", data={**CAR, "lender": "Bank", "loan_end": "2028-06-15"})

    assert db.scalar(select(Car)).loan["monthly_cents"] is None


def test_a_loan_needs_a_lender_and_final_date(client, db, member):
    sign_in(client, db, member)

    no_date = client.post("/cars", data={**CAR, "lender": "Bank"})
    no_lender = client.post("/cars", data={**CAR, "loan_end": "2028-06-15"})
    bad_amount = client.post(
        "/cars", data={**CAR, "lender": "B", "loan_end": "2028-06-15", "loan_monthly": "x"}
    )

    assert no_date.status_code == 422 and "Enter the final payment date" in no_date.text
    assert no_lender.status_code == 422 and "Enter the lender" in no_lender.text
    assert bad_amount.status_code == 422
    assert db.scalars(select(Car)).all() == []


def test_changing_and_removing_the_loan(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)
    base = {**CAR, "lender": "Bank", "loan_end": "2028-06-15"}
    client.post(f"/cars/{car.id}/edit", data=base)
    (item,) = loan_items(db)
    item.done_at = utcnow()
    db.commit()

    client.post(f"/cars/{car.id}/edit", data={**base, "loan_end": "2029-01-01"})
    (item,) = loan_items(db)
    assert (item.due_date, item.done_at) == (date(2029, 1, 1), None)  # a new date reopens it
    assert "2029-01-01" in client.get(f"/cars/{car.id}/edit").text

    client.post(f"/cars/{car.id}/edit", data=CAR)
    assert loan_items(db) == []
    db.refresh(car)
    assert car.loan is None


def test_the_loan_is_encrypted_at_rest(client, db, member, engine):
    sign_in(client, db, member)
    client.post(
        "/cars", data={**CAR, "lender": "Distinctive Lender Name", "loan_end": "2028-06-15"}
    )

    with engine.connect() as conn:
        raw = conn.exec_driver_sql("select loan from cars").scalar()
    assert b"Distinctive" not in raw


def test_the_payoff_shows_on_the_due_tab_and_can_be_marked_done_only(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)
    client.post(f"/cars/{car.id}/select")
    client.post(f"/cars/{car.id}/edit", data={**CAR, "lender": "Bank", "loan_end": "2028-06-15"})

    page = client.get("/due").text

    assert "Loan payoff" in page and "Jun 15, 2028" in page and "Final payment to Bank" in page
    (item,) = loan_items(db)
    assert f"/due/{item.id}/edit" not in page and f"/due/{item.id}/delete" not in page
    client.post(f"/due/{item.id}/delete")
    assert len(loan_items(db)) == 1


def test_loans_stay_private_with_the_car(client, db, member):
    owner = make_user(db, email="o@example.com")
    car = make_car(
        db,
        owner,
        visibility="private",
        loan={"lender": "Secret Bank", "final_date": "2030-01-01", "monthly_cents": None},
    )
    sign_in(client, db, member)

    assert "Secret Bank" not in client.get("/account/export").text
    assert client.get(f"/cars/{car.id}/edit").status_code == 404


def test_the_owner_download_includes_the_loan(client, db, member):
    make_car(
        db, member, loan={"lender": "My Bank", "final_date": "2030-01-01", "monthly_cents": 5000}
    )
    sign_in(client, db, member)

    assert client.get("/account/export").json()["cars"][0]["loan"]["lender"] == "My Bank"
