def test_only_admin_can_manage_catalogue(client, user_h):
    assert client.post("/tests/", json={"name": "X"}, headers=user_h).status_code == 403
    assert client.post("/centres/", json={"name": "C", "location": "L"}, headers=user_h).status_code == 403
    assert client.post("/centres/", json={"name": "C", "location": "L"}).status_code == 401


def test_admin_builds_catalogue_and_public_can_read(client, admin_h):
    t = client.post("/tests/", json={"name": "Lipid Profile"}, headers=admin_h).json()
    c = client.post("/centres/", json={"name": "EVE Delhi", "location": "Delhi"}, headers=admin_h).json()
    r = client.post(f"/centres/{c['id']}/tests", json={"test_id": t["id"], "price": "600"}, headers=admin_h)
    assert r.status_code == 201 and r.json()["price"] == "600.00"

    r = client.get(f"/centres/{c['id']}")  # no auth needed
    assert r.status_code == 200
    assert r.json()["tests"][0]["name"] == "Lipid Profile"


def test_duplicates_and_bad_input(client, admin_h, catalogue):
    assert client.post("/tests/", json={"name": "CBC"}, headers=admin_h).status_code == 409
    dup = client.post(f"/centres/{catalogue['centre_id']}/tests",
                      json={"test_id": catalogue["test_id"], "price": "1"}, headers=admin_h)
    assert dup.status_code == 409
    for bad in ("0", "-5", "abc", "10.999"):
        r = client.post(f"/centres/{catalogue['centre_id']}/tests",
                        json={"test_id": catalogue["test_id"], "price": bad}, headers=admin_h)
        assert r.status_code == 422, bad
    assert client.get("/centres/9999").status_code == 404
    assert client.get("/centres/abc").status_code == 422
    r = client.post("/centres/9999/tests", json={"test_id": 1, "price": "5"}, headers=admin_h)
    assert r.status_code == 404


def test_list_filters_and_pagination(client, admin_h, catalogue):
    client.post("/centres/", json={"name": "EVE Pune", "location": "Pune"}, headers=admin_h)
    r = client.get("/centres/", params={"limit": 1})
    body = r.json()
    assert body["total"] == 2 and len(body["items"]) == 1 and body["limit"] == 1
    assert client.get("/centres/", params={"location": "noi"}).json()["total"] == 1
    assert client.get("/centres/", params={"test": "cbc"}).json()["total"] == 1
    assert client.get("/centres/", params={"test": "nothing"}).json()["total"] == 0
    assert client.get("/centres/", params={"limit": 0}).status_code == 422
    assert client.get("/centres/", params={"limit": 1000}).status_code == 422


def test_price_change_does_not_touch_existing_bookings(client, admin_h, catalogue, user_h, make_booking):
    booking = make_booking(user_h)
    r = client.patch(f"/centres/{catalogue['centre_id']}/tests/{catalogue['test_id']}",
                     json={"price": "999.00"}, headers=admin_h)
    assert r.status_code == 200 and r.json()["price"] == "999.00"
    assert client.get(f"/bookings/{booking['id']}", headers=user_h).json()["amount"] == "500.00"
