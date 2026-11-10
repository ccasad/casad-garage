import json
from datetime import date

import pytest
from sqlalchemy import func, select

from app import invoice
from app.models import (
    Car,
    Document,
    DueItem,
    MileageReading,
    RecommendedItem,
    ServiceItem,
    ServiceRecord,
)
from tests.conftest import make_car, make_user, sign_in
from tests.invoice_fixture import FAKE_VIN, PAGE_1, PAGE_2, invoice_text, make_pdf


def upload(client, data=None, name="invoice.pdf", **form):
    data = make_pdf() if data is None else data
    return client.post(
        "/invoices",
        files={"invoice": (name, data, "application/pdf")},
        data=form,
        follow_redirects=False,
    )


def count(db, model):
    db.expire_all()
    return db.scalar(select(func.count()).select_from(model))


# --- the parser (FR-19) -------------------------------------------------------------


@pytest.mark.parametrize(
    "text", [invoice_text(), invoice.extract_text(make_pdf())], ids=["same-line", "pdf"]
)
def test_parser_reads_the_supported_layout(text):
    parsed = invoice.parse_invoice(text)

    assert (parsed.ro_number, parsed.on, parsed.shop) == (
        "12345",
        "2026-02-10",
        "Example Auto Care",
    )
    assert (parsed.vin, parsed.year, parsed.make, parsed.model, parsed.trim) == (
        FAKE_VIN,
        "2019",
        "Acme",
        "Roadster",
        "Sport",
    )
    assert parsed.odometer == 52100 and parsed.grand_total_cents == 5000
    jobs = [(j.title, j.status, j.price_cents, j.type) for j in parsed.jobs]
    assert jobs == [
        ("State Inspection", "approved", 2000, "state_inspection"),
        ("Emissions Test", "approved", 3000, "emissions_inspection"),
        ("Rear Brakes", "declined", 32000, "brakes"),  # the final amount of "Subtotal + tax"
        ("Cabin Air Filter", "declined", 4550, "cabin_air_filter"),
        ("Cooling System Flush", "declined", 12800, "fluids"),
    ]
    assert len(parsed.approved) == 2 and len(parsed.declined) == 3
    assert parsed.jobs[4].note == (
        "Coolant is dirty and due for a flush, which keeps the engine running cool."
    )
    first, third = parsed.jobs[0], parsed.jobs[2]
    assert (first.shop_note, first.note) == ("Passed", "Sticker issued for the windshield.")
    assert (third.shop_note, third.note) == ("Pads at 3mm", "Replace pads and resurface rotors.")


def test_customer_and_payment_details_are_not_kept():
    parsed = invoice.parse_invoice(invoice.extract_text(make_pdf()))

    kept = json.dumps(parsed.to_json())
    for private in (
        "Pat Example",
        "pat@example.com",
        "Nowhere Lane",
        "Visa",
        "0000",
        "ZX81QQ",
        "Page 1 of 2",
    ):
        assert private not in kept


def test_unrecognised_text_is_not_an_invoice():
    assert invoice.parse_invoice("Just some letter\nwith no invoice in it") is None
    assert invoice.parse_invoice("Invoice for RO #9\nno jobs here") is None


def test_text_extraction_edge_cases():
    assert invoice.extract_text(make_pdf(pages=([],))).strip() == ""
    with pytest.raises(invoice.InvoiceError):
        invoice.extract_text(b"%PDF-1.4 not really")


# --- upload, match and review (FR-18, FR-20, FR-21) --------------------------------


def test_upload_matches_the_car_by_vin_and_opens_the_review(client, db, member, files):
    car = make_car(db, member, vin=FAKE_VIN, nickname="Matched")
    other = make_car(db, member, nickname="Other")
    sign_in(client, db, member)
    client.post(f"/cars/{other.id}/select")

    response = upload(client)

    doc = db.scalar(select(Document))
    assert response.headers["location"] == f"/invoices/{doc.id}/review"
    assert doc.car_id == car.id and doc.status == "review" and doc.uploaded_by_id == member.id
    assert files.files[doc.storage_ref].startswith(b"%PDF-")
    page = client.get(response.headers["location"]).text
    for text in (
        "Matched",
        "State Inspection",
        "Emissions Test",
        "Rear Brakes",
        "Cabin Air Filter",
        "12345",
        "Example Auto Care",
    ):
        assert text in page
    assert "Pat Example" not in page
    # Nothing is saved until the review is confirmed
    assert count(db, ServiceRecord) == 0 and count(db, RecommendedItem) == 0


def test_upload_matches_a_pre_1981_vin(client, db, member, files):
    car = make_car(db, member, vin="6T07T000000", nickname="Classic")
    make_car(db, member, nickname="Other")
    sign_in(client, db, member)
    pages = [[(line.replace(FAKE_VIN, "6T07T000000"), right) for line, right in PAGE_1], PAGE_2]

    upload(client, make_pdf(pages))

    doc = db.scalar(select(Document))
    assert doc.car_id == car.id and doc.status == "review"
    assert (
        invoice.parse_invoice(invoice_text().replace(FAKE_VIN, "6T07T000000")).vin == "6T07T000000"
    )


def test_saving_the_review_creates_everything(client, db, member):
    car = make_car(db, member, vin=FAKE_VIN)
    sign_in(client, db, member)
    doc_url = upload(client).headers["location"]
    doc = db.scalar(select(Document))

    response = client.post(
        doc_url.replace("review", "save"),
        data={
            "on": "2026-02-10",
            "miles": "52100",
            "shop": "Example Auto Care",
            "ro_number": "12345",
            "total": "50.00",
            "notes": "",
            "item_id": ["", ""],
            "item_description": ["State Inspection", "Emissions Test"],
            "item_type": ["state_inspection", "emissions_inspection"],
            "item_part": ["", ""],
            "item_cost": ["20.00", "30.00"],
            "rec_description": ["Rear Brakes", "Cabin Air Filter"],
            "rec_note": ["Pads at 3mm", ""],
            "rec_price": ["320.00", "45.50"],
        },
        follow_redirects=False,
    )

    record = db.scalar(select(ServiceRecord))
    assert response.headers["location"] == f"/service/{record.id}?saved=1"
    assert (record.car_id, record.shop, record.ro_number, record.total_cents, record.miles) == (
        car.id,
        "Example Auto Care",
        "12345",
        5000,
        52100,
    )
    assert record.document_id == doc.id
    assert count(db, ServiceItem) == 2
    reading = db.scalar(select(MileageReading))
    assert (reading.miles, reading.on) == (52100, date(2026, 2, 10))
    recs = {r.description: r for r in db.scalars(select(RecommendedItem))}
    assert set(recs) == {"Rear Brakes", "Cabin Air Filter"}
    brakes = recs["Rear Brakes"]
    assert (brakes.shop_note, brakes.price_cents, brakes.status) == ("Pads at 3mm", 32000, "open")
    assert (brakes.recommended_on, brakes.recommended_miles, brakes.car_id, brakes.document_id) == (
        date(2026, 2, 10),
        52100,
        car.id,
        doc.id,
    )
    db.refresh(doc)
    assert doc.parsed is None and doc.status == "attached"
    assert "Set the next state inspection?" in client.get(response.headers["location"]).text
    # the review is single-use
    assert client.get(doc_url).status_code == 404


def test_the_review_can_edit_remove_and_add_lines(client, db, member):
    make_car(db, member, vin=FAKE_VIN)
    sign_in(client, db, member)
    doc_url = upload(client).headers["location"]

    client.post(
        doc_url.replace("review", "save"),
        data={
            "on": "2026-02-11",
            "miles": "52,200",
            "shop": "Other Shop",
            "ro_number": "",
            "item_description": ["Only job"],
            "item_type": ["other"],
            "item_part": ["Part X"],
            "item_cost": ["5"],
            "rec_description": ["Added by hand"],
            "rec_note": [""],
            "rec_price": [""],
        },
    )

    record = db.scalar(select(ServiceRecord))
    assert (record.on, record.shop, record.total_cents) == (date(2026, 2, 11), "Other Shop", 500)
    assert [i.description for i in db.scalars(select(ServiceItem))] == ["Only job"]
    assert [r.description for r in db.scalars(select(RecommendedItem))] == ["Added by hand"]


def test_review_validation_keeps_what_was_typed(client, db, member):
    make_car(db, member, vin=FAKE_VIN)
    sign_in(client, db, member)
    doc_url = upload(client).headers["location"]

    response = client.post(
        doc_url.replace("review", "save"),
        data={
            "on": "",
            "item_description": ["Kept text"],
            "item_type": ["other"],
            "rec_description": [""],
            "rec_note": ["orphan note"],
            "rec_price": ["x"],
        },
    )

    assert response.status_code == 422
    assert "Enter a date" in response.text and "Kept text" in response.text
    assert "orphan note" in response.text
    assert count(db, ServiceRecord) == 0


def test_only_declined_jobs_still_import(client, db, member):
    make_car(db, member, vin=FAKE_VIN)
    sign_in(client, db, member)
    doc_url = upload(client).headers["location"]

    response = client.post(
        doc_url.replace("review", "save"),
        data={
            "on": "2026-02-10",
            "miles": "52100",
            "rec_description": ["Rear Brakes"],
            "rec_note": [""],
            "rec_price": ["320"],
        },
        follow_redirects=False,
    )

    assert response.headers["location"] == "/todo"
    assert count(db, ServiceRecord) == 0 and count(db, RecommendedItem) == 1
    assert count(db, MileageReading) == 1


def test_saving_closes_open_due_items(client, db, member):
    car = make_car(db, member, vin=FAKE_VIN)
    item = DueItem(car_id=car.id, type="state_inspection", due_date=date(2026, 1, 1))
    db.add(item)
    db.commit()
    sign_in(client, db, member)
    doc_url = upload(client).headers["location"]

    client.post(
        doc_url.replace("review", "save"),
        data={
            "on": "2026-02-10",
            "item_description": ["State Inspection"],
            "item_type": ["state_inspection"],
        },
    )

    db.refresh(item)
    assert item.done_at is not None


# --- no matching car (FR-20) ------------------------------------------------------


def test_no_matching_car_asks_which_car(client, db, member):
    mine = make_car(db, member, nickname="Some Car", vin="2B4BB22BB2B222222")
    sign_in(client, db, member)

    doc_url = upload(client).headers["location"]
    doc = db.scalar(select(Document))
    assert doc.car_id is None
    page = client.get(doc_url).text
    assert "Which car is it for?" in page and "Some Car" in page
    assert f"/cars/new?invoice={doc.id}" in page

    client.post(f"{doc_url.replace('review', 'car')}", data={"car_id": str(mine.id)})
    db.refresh(doc)
    assert doc.car_id == mine.id
    assert "Which car is it for?" not in client.get(doc_url).text


def test_a_private_car_of_someone_else_is_not_a_match(client, db, member):
    owner = make_user(db, email="o@example.com")
    make_car(db, owner, visibility="private", vin=FAKE_VIN, nickname="Hidden")
    sign_in(client, db, member)

    page = client.get(upload(client).headers["location"]).text

    assert "Which car is it for?" in page and "Hidden" not in page


def test_adding_a_new_car_from_the_invoice(client, db, member):
    sign_in(client, db, member)
    doc_url = upload(client).headers["location"]
    doc = db.scalar(select(Document))

    form = client.get(f"/cars/new?invoice={doc.id}").text
    for prefilled in (
        'value="2019"',
        'value="Acme"',
        'value="Roadster"',
        'value="Sport"',
        FAKE_VIN,
    ):
        assert prefilled in form

    response = client.post(
        "/cars",
        data={
            "year": "2019",
            "make": "Acme",
            "model": "Roadster",
            "trim": "Sport",
            "vin": FAKE_VIN,
            "invoice": str(doc.id),
        },
        follow_redirects=False,
    )

    car = db.scalar(select(Car))
    assert response.headers["location"] == doc_url
    db.refresh(doc)
    assert doc.car_id == car.id
    assert "State Inspection" in client.get(doc_url).text


def test_someone_elses_unmatched_upload_is_not_usable(client, db, member):
    owner = make_user(db, email="o@example.com")
    sign_in(client, db, owner)
    doc_url = upload(client).headers["location"]
    doc = db.scalar(select(Document))
    client.cookies.clear()
    sign_in(client, db, member)
    mine = make_car(db, member)

    assert client.get(doc_url).status_code == 404
    assert (
        client.post(doc_url.replace("review", "car"), data={"car_id": str(mine.id)}).status_code
        == 404
    )
    assert client.get(f"/cars/new?invoice={doc.id}").text.count('value="Acme"') == 0
    assert client.get(f"/documents/{doc.id}/file").status_code == 404


# --- unreadable files (FR-22) -----------------------------------------------------


@pytest.mark.parametrize(
    ("pdf", "notice"),
    [
        (make_pdf(pages=([],)), "no readable text"),
        (
            make_pdf(pages=([("Some other shop's layout", None), ("Total: $5", None)],)),
            "isn&#39;t recognised",
        ),
        (b"%PDF-1.4\ngarbage", "couldn&#39;t be read"),
    ],
    ids=["no-text", "other-layout", "corrupt"],
)
def test_unreadable_pdfs_stay_attached_and_open_an_empty_record(
    client, db, member, files, pdf, notice
):
    car = make_car(db, member, nickname="Mine")
    sign_in(client, db, member)
    client.post(f"/cars/{car.id}/select")

    response = upload(client, data=pdf, car_id=str(car.id))

    doc = db.scalar(select(Document))
    assert doc.car_id == car.id and doc.status == "attached" and doc.storage_ref in files.files
    assert response.headers["location"].startswith(f"/service/new?document={doc.id}")
    page = client.get(response.headers["location"]).text
    assert notice in page and f'name="document_id" value="{doc.id}"' in page
    # saving the hand-typed record links the file
    client.post(
        f"/cars/{car.id}/service",
        data={
            "on": "2026-01-01",
            "document_id": str(doc.id),
            "item_description": ["Oil"],
            "item_type": ["oil_change"],
        },
    )
    assert db.scalar(select(ServiceRecord)).document_id == doc.id
    assert "invoice.pdf" in client.get("/documents").text


def test_a_file_that_is_not_a_pdf_is_refused(client, db, member, files):
    make_car(db, member)
    sign_in(client, db, member)

    response = upload(client, data=b"GIF89a not a pdf")

    assert response.headers["location"] == "/service?notice=type"
    assert "isn&#39;t a PDF" in client.get(response.headers["location"]).text
    assert count(db, Document) == 0 and files.files == {}


def test_a_pdf_over_10_mb_is_refused(client, db, member):
    make_car(db, member)
    sign_in(client, db, member)

    response = upload(client, data=b"%PDF-" + b"0" * (10 * 1024 * 1024))

    assert response.headers["location"] == "/service?notice=size"
    assert count(db, Document) == 0


def test_unreadable_pdf_without_a_car_asks_to_pick_one(client, db, member):
    sign_in(client, db, member)

    response = upload(client, data=make_pdf(pages=([],)))

    assert response.headers["location"] == "/service?notice=no-car"
    assert count(db, Document) == 0


# --- duplicates (FR-23) -----------------------------------------------------------


def test_duplicate_invoices_warn_before_saving(client, db, member):
    car = make_car(db, member, vin=FAKE_VIN)
    db.add(
        ServiceRecord(
            car_id=car.id, on=date(2026, 1, 1), shop="example auto care", ro_number="12345"
        )
    )
    db.commit()
    sign_in(client, db, member)
    doc_url = upload(client).headers["location"]
    assert "This looks like a duplicate" in client.get(doc_url).text
    data = {
        "on": "2026-02-10",
        "shop": "Example Auto Care",
        "ro_number": "12345",
        "item_description": ["State Inspection"],
        "item_type": ["state_inspection"],
    }

    warned = client.post(doc_url.replace("review", "save"), data=data)
    assert "This looks like a duplicate" in warned.text and count(db, ServiceRecord) == 1

    client.post(doc_url.replace("review", "save"), data={**data, "confirm_duplicate": "yes"})
    assert count(db, ServiceRecord) == 2


def test_other_shops_or_numbers_are_not_duplicates(client, db, member):
    car = make_car(db, member, vin=FAKE_VIN)
    db.add(
        ServiceRecord(car_id=car.id, on=date(2026, 1, 1), shop="Different Shop", ro_number="12345")
    )
    db.add(
        ServiceRecord(car_id=car.id, on=date(2026, 1, 1), shop="Example Auto Care", ro_number="999")
    )
    db.commit()
    sign_in(client, db, member)

    assert "duplicate" not in client.get(upload(client).headers["location"]).text


# --- documents and access (FR-18, NFR-14) ------------------------------------------


def test_documents_list_and_open(client, db, member):
    car = make_car(db, member, vin=FAKE_VIN)
    sign_in(client, db, member)
    upload(client, name="shop invoice.pdf")
    doc = db.scalar(select(Document))
    client.post(f"/cars/{car.id}/select")

    page = client.get("/documents").text
    assert (
        "shop invoice.pdf" in page
        and "not imported yet" in page
        and f"/documents/{doc.id}/file" in page
    )
    response = client.get(f"/documents/{doc.id}/file")
    assert (
        response.content.startswith(b"%PDF-")
        and response.headers["content-type"] == "application/pdf"
    )
    assert response.headers["cache-control"] == "private, no-store"
    assert "inline" in response.headers["content-disposition"]


def test_documents_need_sign_in_and_hide_private_cars(client, db, member):
    owner = make_user(db, email="o@example.com")
    car = make_car(db, owner, visibility="private", vin=FAKE_VIN)
    sign_in(client, db, owner)
    upload(client)
    doc = db.scalar(select(Document))
    assert doc.car_id == car.id
    client.cookies.clear()

    assert client.get(f"/documents/{doc.id}/file", follow_redirects=False).status_code == 303
    sign_in(client, db, member)
    assert client.get(f"/documents/{doc.id}/file").status_code == 404
    assert client.get(f"/invoices/{doc.id}/review").status_code == 404
    assert client.post(f"/invoices/{doc.id}/save", data={}).status_code == 404


def test_shared_documents_are_visible_to_the_household(client, db, member):
    owner = make_user(db, email="o@example.com")
    car = make_car(db, owner, vin=FAKE_VIN)
    sign_in(client, db, owner)
    upload(client)
    doc = db.scalar(select(Document))
    client.cookies.clear()
    sign_in(client, db, member)
    client.post(f"/cars/{car.id}/select")

    assert client.get(f"/documents/{doc.id}/file").status_code == 200


def test_invoice_changes_reject_other_sites(client, db, member):
    make_car(db, member, vin=FAKE_VIN)
    sign_in(client, db, member)
    doc_url = upload(client).headers["location"]
    evil = {"Origin": "https://evil.example"}

    assert (
        client.post("/invoices", files={"invoice": ("a.pdf", make_pdf())}, headers=evil).status_code
        == 403
    )
    assert client.post(doc_url.replace("review", "save"), data={}, headers=evil).status_code == 403
    assert client.post(doc_url.replace("review", "car"), data={}, headers=evil).status_code == 403
    assert count(db, ServiceRecord) == 0


def test_the_filename_is_encrypted_and_the_pdf_not_in_the_database(client, db, member, engine):
    make_car(db, member, vin=FAKE_VIN)
    sign_in(client, db, member)
    upload(client, name="../../pat-example-invoice.pdf")

    with engine.connect() as conn:
        raw = conn.exec_driver_sql("select filename, parsed, storage_ref from documents").one()
    assert b"pat-example" not in raw[0] and b"State Inspection" not in raw[1]
    assert raw[2].startswith("invoices/") and raw[2].endswith(".pdf")
    assert db.scalar(select(Document)).filename == "pat-example-invoice.pdf"  # path stripped


def test_deleting_a_car_removes_its_documents_and_files(client, db, member, files):
    car = make_car(db, member, vin=FAKE_VIN)
    sign_in(client, db, member)
    upload(client)
    assert len(files.files) == 1

    client.post(f"/cars/{car.id}/delete")

    assert files.files == {} and count(db, Document) == 0


def test_deleting_an_account_removes_its_files(client, db, member, files):
    car = make_car(db, member, vin=FAKE_VIN)
    other = make_user(db, email="o@example.com")
    sign_in(client, db, member)
    upload(client)
    client.post(
        f"/cars/{car.id}/photo", files={"photo": ("p.jpg", b"\xff\xd8\xff\xe0 jpeg", "image/jpeg")}
    )
    assert len(files.files) == 2

    client.post("/account/delete", data={"confirm": "DELETE"})

    assert files.files == {}
    assert count(db, Document) == 0 and other


# --- script uploads and the service worker (FR-18, NFR-20) ----------------------------


def test_script_upload_gets_json_with_the_next_url(client, db, member, files):
    make_car(db, member)
    sign_in(client, db, member)

    response = client.post(
        "/invoices",
        files={"invoice": ("invoice.pdf", make_pdf(), "application/pdf")},
        headers={"accept": "application/json"},
        follow_redirects=False,
    )

    doc = db.scalar(select(Document))
    assert response.status_code == 200
    assert response.json() == {"next": f"/invoices/{doc.id}/review"}


def test_plain_form_upload_still_redirects(client, db, member, files):
    make_car(db, member)
    sign_in(client, db, member)

    response = upload(client)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/invoices/")


def test_script_upload_failures_give_the_reason_as_json(client, db, member):
    make_car(db, member)
    sign_in(client, db, member)
    headers = {"accept": "application/json"}

    not_pdf = client.post(
        "/invoices", files={"invoice": ("a.pdf", b"GIF89a", "application/pdf")}, headers=headers
    )
    too_big = client.post(
        "/invoices",
        files={"invoice": ("a.pdf", b"%PDF-" + b"0" * (10 * 1024 * 1024), "application/pdf")},
        headers=headers,
    )

    assert not_pdf.status_code == 415 and "isn't a PDF" in not_pdf.json()["detail"]
    assert too_big.status_code == 413 and "larger than 10 MB" in too_big.json()["detail"]


def test_missing_file_on_a_form_post_shows_a_friendly_page(client, db, member):
    sign_in(client, db, member)

    page = client.post("/invoices", data={"car_id": ""}, headers={"accept": "text/html"})
    api = client.post("/invoices", data={"car_id": ""}, headers={"accept": "application/json"})

    assert page.status_code == 422
    assert "Something was missing from the form" in page.text
    assert not page.text.lstrip().startswith("{")
    assert api.status_code == 422 and api.json()["detail"][0]["type"] == "missing"


def test_service_worker_only_handles_get_navigations():
    from app.web import STATIC_DIR

    text = (STATIC_DIR / "sw.js").read_text()
    assert 'event.request.method !== "GET"' in text
    assert '"offline-v2"' in text
