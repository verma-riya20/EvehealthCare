from tests.conftest import PASSWORD


def signup(client, **over):
    body = {"email": "a@example.com", "full_name": "A", "password": PASSWORD, **over}
    return client.post("/auth/signup", json=body)


def test_signup_and_login_flow(client):
    r = signup(client, email="A@Example.com")
    assert r.status_code == 201
    assert r.json()["email"] == "a@example.com"  # normalised
    assert "password" not in r.text and "hashed" not in r.text
    assert r.json()["is_admin"] is False

    r = client.post("/auth/login", json={"email": "a@example.com", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["token_type"] == "bearer"

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == "a@example.com"


def test_duplicate_email_is_409(client):
    assert signup(client).status_code == 201
    r = signup(client, email="A@example.com")
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"


def test_signup_validation(client):
    assert signup(client, email="not-an-email").status_code == 422
    assert signup(client, password="short1").status_code == 422
    assert signup(client, password="onlyletters").status_code == 422
    assert signup(client, full_name="   ").status_code == 422
    assert client.post("/auth/signup", json={}).status_code == 422


def test_login_wrong_password_and_unknown_user_look_identical(client):
    signup(client)
    bad_pw = client.post("/auth/login", json={"email": "a@example.com", "password": "Wrong1234"})
    unknown = client.post("/auth/login", json={"email": "nobody@example.com", "password": "Wrong1234"})
    assert bad_pw.status_code == unknown.status_code == 401
    assert bad_pw.json() == unknown.json()


def test_protected_route_requires_valid_token(client):
    assert client.get("/auth/me").status_code == 401
    r = client.get("/auth/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_token"
