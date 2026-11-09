from sqlalchemy import select

from app.models import Car
from tests.conftest import make_car, make_user, sign_in

JPEG = b"\xff\xd8\xff\xe0" + b"fake jpeg body"


def upload(client, car, data=JPEG, name="photo.jpg", **kw):
    return client.post(f"/cars/{car.id}/photo", files={"photo": (name, data, "image/jpeg")}, **kw)


def test_upload_stores_the_photo_and_shows_it(client, db, member, files):
    car = make_car(db, member, color="Blue")
    sign_in(client, db, member)
    client.post(f"/cars/{car.id}/select")

    assert upload(client, car).status_code == 204

    db.refresh(car)
    assert files.files[car.photo_ref] == JPEG
    assert car.photo_ref.startswith("photos/")
    page = client.get("/").text
    assert f"/cars/{car.id}/photo?v=" in page and "Replace photo" in page
    response = client.get(f"/cars/{car.id}/photo")
    assert response.content == JPEG and response.headers["content-type"] == "image/jpeg"
    assert "private" in response.headers["cache-control"]


def test_no_photo_shows_a_placeholder(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)
    client.post(f"/cars/{car.id}/select")

    assert "No photo yet" in client.get("/").text
    assert client.get(f"/cars/{car.id}/photo").status_code == 404
    assert "No photo yet" in client.get("/cars").text


def test_replacing_removes_the_old_file(client, db, member, files):
    car = make_car(db, member)
    sign_in(client, db, member)
    upload(client, car)
    db.refresh(car)
    first = car.photo_ref

    upload(client, car, data=JPEG + b"2")

    db.refresh(car)
    assert car.photo_ref != first and first not in files.files and len(files.files) == 1


def test_only_small_jpegs_are_accepted(client, db, member, files):
    car = make_car(db, member)
    sign_in(client, db, member)

    assert upload(client, car, data=b"GIF89a....").status_code == 415
    assert upload(client, car, data=JPEG + b"x" * (3 * 1024 * 1024)).status_code == 413
    assert files.files == {}


def test_other_cars_photos_are_private(client, db, member):
    owner = make_user(db, email="o@example.com")
    car = make_car(db, owner, visibility="private")
    sign_in(client, db, member)

    assert upload(client, car).status_code == 404
    assert client.get(f"/cars/{car.id}/photo").status_code == 404


def test_photo_upload_rejects_other_sites(client, db, member):
    car = make_car(db, member)
    sign_in(client, db, member)

    assert upload(client, car, headers={"Origin": "https://evil.example"}).status_code == 403


def test_deleting_a_car_deletes_its_photo(client, db, member, files):
    car = make_car(db, member)
    sign_in(client, db, member)
    upload(client, car)

    client.post(f"/cars/{car.id}/delete")

    assert files.files == {}
    assert db.scalars(select(Car)).all() == []
