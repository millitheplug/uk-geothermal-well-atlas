"""Self-service sign-up: a new account gets its own organisation and a session."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.main import app
from app.models.user import Tenant, User

URL = "/api/v1/auth/register"


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


def _body(email: str = "x@example.org", **over):
    body = {
        "full_name": "Ada Lovelace",
        "email": email,
        "organisation": "Analytical Heat Ltd",
        "password": "a-long-enough-passphrase",
        "password_confirm": "a-long-enough-passphrase",
    }
    body.update(over)
    return body


def test_register_creates_owner_in_new_organisation_and_signs_in(client: TestClient):
    response = client.post(URL, json=_body("Ada@Example.org"))
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["user"]["email"] == "ada@example.org"
    assert data["user"]["role"] == "owner"

    # The token works straight away.
    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == "ada@example.org"

    # Password is stored hashed, and the user sits in a brand-new tenant.
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == "ada@example.org"))
        assert user.hashed_password.startswith("pbkdf2_sha256$")
        assert "a-long-enough-passphrase" not in user.hashed_password
        tenant = db.get(Tenant, user.tenant_id)
        assert tenant.name == "Analytical Heat Ltd"


def test_can_log_in_after_registering(client: TestClient):
    client.post(URL, json=_body("login-after@example.org"))
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "login-after@example.org", "password": "a-long-enough-passphrase"},
    )
    assert response.status_code == 200


def test_two_registrations_never_share_an_organisation(client: TestClient):
    a = client.post(URL, json=_body("a-user@example.org")).json()["user"]
    b = client.post(URL, json=_body("b-user@example.org")).json()["user"]
    assert a["tenant_id"] != b["tenant_id"]


def test_duplicate_email_is_refused_case_insensitively(client: TestClient):
    assert client.post(URL, json=_body("dupe@example.org")).status_code == 201
    again = client.post(URL, json=_body("DUPE@example.org"))
    assert again.status_code == 409
    assert "already exists" in again.json()["detail"]


def test_password_mismatch_is_refused(client: TestClient):
    response = client.post(URL, json=_body("mismatch@example.org", password_confirm="different-pass-123"))
    assert response.status_code == 422
    assert "do not match" in response.json()["detail"]


@pytest.mark.parametrize(
    "over",
    [{"password": "short", "password_confirm": "short"}, {"email": "not-an-email"}, {"organisation": " "}, {"full_name": ""}],
)
def test_invalid_input_is_refused(client: TestClient, over):
    response = client.post(URL, json=_body(**{"email": "invalid@example.org", **over}))
    assert response.status_code == 422


def test_registration_can_be_switched_off(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "allow_registration", False)
    assert client.post(URL, json=_body("closed@example.org")).status_code == 403


def test_password_policy_applies_to_registration(client: TestClient):
    # Long enough for the request schema, too short for the platform policy.
    short = "elevenchars"
    response = client.post(URL, json=_body("policy@example.org", password=short, password_confirm=short))
    assert response.status_code == 422
    assert "at least 12" in response.json()["detail"]


def test_new_account_cannot_see_another_organisations_projects(client: TestClient):
    a = client.post(URL, json=_body("owner-a@example.org")).json()
    b = client.post(URL, json=_body("owner-b@example.org")).json()
    head_a = {"Authorization": f"Bearer {a['access_token']}"}
    head_b = {"Authorization": f"Bearer {b['access_token']}"}

    made = client.post("/api/v1/projects", json={"name": "A's private shortlist"}, headers=head_a)
    assert made.status_code == 201, made.text
    project_id = made.json()["id"]

    assert [p["name"] for p in client.get("/api/v1/projects", headers=head_a).json()] == [
        "A's private shortlist"
    ]
    assert client.get("/api/v1/projects", headers=head_b).json() == []
    assert client.get(f"/api/v1/projects/{project_id}", headers=head_b).status_code == 404
