import json
from typing import Any

from django.test import Client


def _post(path: str, body: dict[str, Any], token: str | None = None) -> Any:
    if token:
        return Client().post(
            f"/api/v1/auth{path}",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )
    return Client().post(
        f"/api/v1/auth{path}", data=json.dumps(body), content_type="application/json"
    )


def test_signup_creates_account_and_returns_a_token(db):
    r = _post("/signup", {"email": "a@example.com", "password": "longenough", "display_name": "A"})
    assert r.status_code == 201
    body = r.json()
    assert body["token"] and body["user"]["email"] == "a@example.com"
    from core.models import User

    u = User.objects.get(email="a@example.com")
    assert u.password and u.password != "longenough"  # stored hashed


def test_signup_rejects_duplicate_email_and_short_password(db):
    _post("/signup", {"email": "a@example.com", "password": "longenough", "display_name": "A"})
    dup = _post(
        "/signup", {"email": "a@example.com", "password": "longenough", "display_name": "B"}
    )
    assert dup.status_code == 409
    weak = _post("/signup", {"email": "b@example.com", "password": "short", "display_name": "B"})
    assert weak.status_code == 422
    blank_name = _post(
        "/signup",
        {"email": "blankname@example.com", "password": "longenough", "display_name": "   "},
    )
    assert blank_name.status_code == 422


def test_login_succeeds_and_is_generic_on_failure(db):
    _post("/signup", {"email": "a@example.com", "password": "longenough", "display_name": "A"})
    r = _post("/login", {"email": "a@example.com", "password": "longenough"})
    assert r.status_code == 200
    b = r.json()
    assert b["token"] and b["user"]["email"] == "a@example.com"
    assert _post("/login", {"email": "a@example.com", "password": "wrongpass"}).status_code == 401
    no_user = _post("/login", {"email": "nobody@example.com", "password": "longenough"})
    assert no_user.status_code == 401


def test_make_password_none_is_unusable(db):
    from django.contrib.auth.hashers import check_password, make_password

    dummy = make_password(None)
    assert not check_password("anything", dummy)
    assert not check_password("", dummy)


def test_me_and_logout(db):
    signup = _post(
        "/signup", {"email": "a@example.com", "password": "longenough", "display_name": "A"}
    )
    token = signup.json()["token"]
    me = Client().get("/api/v1/auth/me", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert me.status_code == 200 and me.json()["email"] == "a@example.com"
    assert Client().get("/api/v1/auth/me").status_code == 401  # no token
    assert _post("/logout", {}, token=token).status_code == 204
    me_after = Client().get("/api/v1/auth/me", HTTP_AUTHORIZATION=f"Bearer {token}")
    assert me_after.status_code == 401  # session gone
