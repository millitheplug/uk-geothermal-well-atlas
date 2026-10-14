"""Integration tests for the API.

These run against a real SQLite database with the schema created and the
development adapters loaded, so they exercise the whole stack: routing,
authentication, tenant scoping, the spatial fallback, the deterministic
pipeline and the agent layer.

The negative tests carry most of the weight here. A test suite that only
confirms the happy path would pass against a service with no authentication, no
tenant isolation and a score the LLM could set.
"""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.security import create_access_token, hash_password  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models.analysis import Analysis  # noqa: E402
from app.models.project import Project, ProjectWell  # noqa: E402
from app.models.user import User  # noqa: E402


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture(scope="module")
def admin_token(tenants) -> str:
    """An owner token for the development tenant.

    Depends on the session-scoped ``tenants`` fixture so both tenants exist
    before any user row references them - otherwise the insert fails the foreign
    key and every downstream test errors for the wrong reason.
    """
    from app.db.session import SessionLocal
    from tests.conftest import DEV_TENANT_ID

    with SessionLocal() as session:
        user = session.query(User).filter(User.tenant_id == DEV_TENANT_ID).first()
        if user is None:
            user = User(
                tenant_id=DEV_TENANT_ID,
                email="api-admin@example.com",
                hashed_password=hash_password("integration-test-password"),
                full_name="API Admin",
                role="owner",
                is_active=True,
            )
            session.add(user)
            session.commit()
        return create_access_token(
            user_id=user.id, tenant_id=user.tenant_id, role=user.role
        )


@pytest.fixture(scope="module")
def other_tenant_token(tenants) -> str:
    from app.db.session import SessionLocal
    from tests.conftest import OTHER_TENANT_ID

    with SessionLocal() as session:
        user = session.query(User).filter(User.tenant_id == OTHER_TENANT_ID).first()
        if user is None:
            user = User(
                tenant_id=OTHER_TENANT_ID,
                email="other@example.com",
                hashed_password=hash_password("other-tenant-password"),
                full_name="Other Org",
                role="owner",
                is_active=True,
            )
            session.add(user)
            session.commit()
        return create_access_token(
            user_id=user.id, tenant_id=user.tenant_id, role=user.role
        )


@pytest.fixture(scope="module")
def unclaimed_tenant_token(tenants) -> str:
    """A third tenant that never references a well.

    Separate from ``other_tenant_token`` because that one is deliberately granted
    a claim on a well by ``TestProjects``. This one stays empty for the whole
    module, so "sees nothing" is a stable assertion regardless of test order.
    """
    import uuid as _uuid

    from app.db.session import SessionLocal
    from app.models.user import Tenant

    tenant_id = _uuid.UUID("00000000-0000-0000-0000-0000000000dd")
    with SessionLocal() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(Tenant(id=tenant_id, slug="unclaimed", name="Unclaimed Org"))
            session.commit()

        user = session.query(User).filter(User.tenant_id == tenant_id).first()
        if user is None:
            user = User(
                tenant_id=tenant_id,
                email="unclaimed@example.com",
                hashed_password=hash_password("unclaimed-tenant-password"),
                full_name="Unclaimed Analyst",
                role="analyst",
                is_active=True,
            )
            session.add(user)
            session.commit()

        return create_access_token(
            user_id=user.id, tenant_id=user.tenant_id, role=user.role
        )


@pytest.fixture(scope="module")
def project_id(admin_token: str, loaded_data: dict) -> str:
    """A project holding every development well, so they are visible.

    Wells are national reference data with no tenant of their own; attaching
    them to a project is how the tenant claims them. Every data test depends on
    this fixture, and on ``loaded_data`` having run first.

    Keyed on this fixture's own slug rather than on "any project the tenant
    owns", and the links are reconciled on every call. ``TestProjects`` exercises
    the project CRUD endpoints against this same tenant, creating projects that
    hold no wells, and the suite runs in a randomised order - so "the first
    project found" is frequently one of those. Attaching the wells only when the
    fixture created the project itself made every well-visibility assertion
    depend on whether ``TestProjects`` had already run. It cost a green run on
    CI and a red one on the next push, which is precisely the coupling this
    suite is configured to catch.
    """
    from app.db.session import SessionLocal
    from app.models.well import Well
    from tests.conftest import DEV_TENANT_ID

    with SessionLocal() as session:
        project = (
            session.query(Project)
            .filter(
                Project.tenant_id == DEV_TENANT_ID,
                Project.slug == "national-screening-test",
            )
            .first()
        )
        if project is None:
            project = Project(
                tenant_id=DEV_TENANT_ID,
                name="National Screening",
                slug="national-screening-test",
                stage="screening",
            )
            session.add(project)
            session.flush()

        linked = {
            row.well_id
            for row in session.query(ProjectWell).filter(
                ProjectWell.project_id == project.id
            )
        }
        for well in session.query(Well).all():
            if well.id not in linked:
                session.add(
                    ProjectWell(
                        project_id=project.id, well_id=well.id, role="candidate"
                    )
                )
        session.commit()
        return str(project.id)


@pytest.fixture(scope="module")
def any_well_id(loaded_data: dict) -> str:
    """A fully characterised development well."""
    from app.db.session import SessionLocal
    from app.models.well import Well

    with SessionLocal() as session:
        well = session.query(Well).filter(Well.well_id == "UK-MOCK-WLN-002").one()
        return str(well.id)


class TestHealth:
    def test_health_reports_configuration(self, client: TestClient):
        response = client.get("/api/v1/admin/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] in ("ok", "degraded")
        assert body["spatial_dialect"] in ("postgis", "haversine")
        assert body["llm"] in ("anthropic", "mock", "disabled")

    def test_health_flags_mock_data_present(self, client: TestClient, loaded_data: dict):
        """Once the development adapters have run, health must say so.

        Read from the wells rather than the dataset registry, so the flag
        reflects rows that actually landed.
        """
        body = client.get("/api/v1/admin/health").json()
        assert body["is_mock_data"] is True

    def test_health_degrades_when_the_database_is_unreachable(self, client: TestClient):
        """A dead database must be reported, not raised.

        The mock-row count used to sit outside the endpoint's guard, so an
        unreachable database raised straight through it and returned a bare 500
        with an empty body. The designed "degraded" readout never appeared, and
        a platform health check wired to this path could not tell a dead
        database from a dead process - it just saw an opaque failure.
        """
        from sqlalchemy.exc import OperationalError

        from app.db.session import engine, get_db

        class _UnreachableSession:
            """Cannot reach the data, but still knows its own dialect."""

            def execute(self, *_args: object, **_kwargs: object):
                raise OperationalError("SELECT 1", {}, Exception("database is down"))

            def scalar(self, *_args: object, **_kwargs: object):
                raise OperationalError("SELECT 1", {}, Exception("database is down"))

            def get_bind(self):
                # No connection needed to read the dialect name.
                return engine

        client.app.dependency_overrides[get_db] = lambda: _UnreachableSession()
        try:
            response = client.get("/api/v1/admin/health")
        finally:
            client.app.dependency_overrides.pop(get_db, None)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "degraded"
        assert body["database"] == "unavailable"
        assert body["is_mock_data"] is False

    def test_root_exposes_docs(self, client: TestClient):
        body = client.get("/").json()
        assert body["docs"] == "/api/docs"
        assert "viability" in body["notice"]

    def test_openapi_is_served(self, client: TestClient):
        response = client.get("/api/openapi.json")
        assert response.status_code == 200
        assert "/api/v1/wells" in response.json()["paths"]


class TestAuthentication:
    def test_wells_require_authentication(self, client: TestClient):
        response = client.get("/api/v1/wells")
        assert response.status_code == 401
        assert "authentication required" in response.json()["detail"]

    def test_analyses_require_authentication(self, client: TestClient):
        assert client.get("/api/v1/analyses").status_code == 401

    def test_bad_token_is_rejected(self, client: TestClient):
        response = client.get(
            "/api/v1/wells", headers={"Authorization": "Bearer not-a-real-token"}
        )
        assert response.status_code == 401

    def test_valid_token_is_accepted(self, client: TestClient, admin_token: str):
        response = client.get(
            "/api/v1/wells", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200

    def test_login_with_wrong_password_is_rejected(self, client: TestClient):
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "api-admin@example.com", "password": "wrong-password-entirely"},
        )
        assert response.status_code == 401
        # Must not reveal whether the account exists.
        assert "invalid email or password" in response.json()["detail"]

    def test_login_with_unknown_email_gives_the_same_message(self, client: TestClient):
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "wrong-password-entirely"},
        )
        assert response.status_code == 401
        assert "invalid email or password" in response.json()["detail"]

    def test_login_with_correct_credentials_issues_a_token(self, client: TestClient):
        response = client.post(
            "/api/v1/auth/login",
            json={
                "email": "api-admin@example.com",
                "password": "integration-test-password",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["user"]["email"] == "api-admin@example.com"

    def test_me_returns_the_caller(self, client: TestClient, admin_token: str):
        response = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert response.status_code == 200
        assert response.json()["role"] == "owner"

    def test_short_passwords_are_rejected_at_registration(self):
        from app.core.security import validate_password_strength

        with pytest.raises(ValueError, match="12 characters"):
            validate_password_strength("short")


class TestTenantIsolation:
    def test_wells_are_invisible_without_a_project(
        self, client: TestClient, unclaimed_tenant_token: str
    ):
        """A tenant that has never referenced a well must see none of them.

        Uses a dedicated tenant rather than the shared one: another test grants
        the shared tenant a claim on a well, and this module's tests run in a
        randomised order, so sharing would make the assertion order-dependent.
        """
        response = client.get(
            "/api/v1/wells",
            headers={"Authorization": f"Bearer {unclaimed_tenant_token}"},
            params={"limit": 50},
        )
        assert response.status_code == 200
        assert response.json()["total"] == 0
        assert response.json()["items"] == []

    def test_unclaimed_tenant_cannot_read_any_well_directly(
        self, client: TestClient, unclaimed_tenant_token: str, any_well_id: str
    ):
        """Direct id access must be blocked, not only the list endpoint."""
        response = client.get(
            f"/api/v1/wells/{any_well_id}",
            headers={"Authorization": f"Bearer {unclaimed_tenant_token}"},
        )
        assert response.status_code == 404
        # The message must not confirm the well exists.
        assert "not visible to this tenant" in response.json()["detail"]

    def test_wells_become_visible_after_claiming(self, client: TestClient, project_id: str):
        response = client.get(
            "/api/v1/wells",
            headers={"Authorization": f"Bearer {BEARER['admin']}"},
            params={"limit": 5},
        )
        assert response.json()["total"] > 0

    def test_other_tenant_cannot_read_this_projects_wells(
        self, client: TestClient, other_tenant_token: str, any_well_id: str
    ):
        """Direct id access must be blocked, not just the list endpoint."""
        response = client.get(
            f"/api/v1/wells/{any_well_id}",
            headers={"Authorization": f"Bearer {other_tenant_token}"},
        )
        assert response.status_code == 404
        # The message must not confirm the well exists.
        assert "not visible to this tenant" in response.json()["detail"]

    def test_projects_are_tenant_scoped(
        self, client: TestClient, other_tenant_token: str, project_id: str
    ):
        response = client.get(
            f"/api/v1/projects/{project_id}",
            headers={"Authorization": f"Bearer {other_tenant_token}"},
        )
        assert response.status_code == 404

    def test_analyses_are_tenant_scoped(
        self, client: TestClient, other_tenant_token: str
    ):
        response = client.get(
            "/api/v1/analyses",
            headers={"Authorization": f"Bearer {other_tenant_token}"},
        )
        assert response.status_code == 200
        assert response.json() == []


class TestClaimableWells:
    """Adoption of wells that belong to no project.

    Without this the tenancy model is a dead end: wells become visible only by
    being attached to one of your own projects, and you cannot find a well to
    attach because you cannot see any.

    These tests build their own well rather than reaching for the shared
    fixtures, because ``project_id`` claims *every* development well for the
    development tenant. Depending on the shared inventory would make every
    assertion here depend on whether ``TestProjects`` has already run, which is
    exactly the kind of order-dependence this suite is configured to catch.
    """

    @pytest.fixture(scope="class")
    def new_unadopted_well(self, loaded_data: dict):
        """Factory for a well that belongs to no project.

        A factory rather than one shared well, because two of the tests here
        deliberately adopt their well into a project - which is the behaviour
        under test - and a shared fixture would leave nothing claimable for the
        test that runs next.

        Each well is removed in teardown. Leaving one behind would break the
        assertions elsewhere that assume the inventory holds only mock wells, and
        a helper that quietly changes global state for every other test is worse
        than a flaky test.
        """
        import uuid as _uuid

        from app.db.session import SessionLocal
        from app.models.well import Well

        created: list[_uuid.UUID] = []
        counter = {"n": 0}

        def _make() -> str:
            counter["n"] += 1
            well_id = _uuid.uuid4()
            with SessionLocal() as session:
                session.add(
                    Well(
                        id=well_id,
                        well_id=f"TEST-UNADOPTED-{counter['n']:03d}",
                        well_name=f"Adoption Test Well {counter['n']}",
                        latitude=53.0,
                        longitude=-2.0,
                        region="East Midlands",
                        source="mock_adoption_test",
                    )
                )
                session.commit()
            created.append(well_id)
            return str(well_id)

        yield _make

        # Teardown: remove the join rows first so the foreign keys do not object.
        with SessionLocal() as session:
            for well_id in created:
                session.query(ProjectWell).filter(
                    ProjectWell.well_id == well_id
                ).delete(synchronize_session=False)
                session.query(Analysis).filter(
                    Analysis.well_id == well_id
                ).delete(synchronize_session=False)
                orphan = session.get(Well, well_id)
                if orphan is not None:
                    session.delete(orphan)
            session.commit()

    def test_claimable_search_offers_an_unadopted_well(
        self, client: TestClient, unclaimed_tenant_token: str, new_unadopted_well
    ):
        well_id = new_unadopted_well()
        response = client.get(
            "/api/v1/wells",
            headers={"Authorization": f"Bearer {unclaimed_tenant_token}"},
            params={"include_claimable": True, "limit": 1000},
        )
        assert response.status_code == 200
        ids = {item["id"] for item in response.json()["items"]}
        assert well_id in ids

    def test_claimable_is_off_by_default(
        self, client: TestClient, unclaimed_tenant_token: str, new_unadopted_well
    ):
        """A plain search shows what you hold, not the national inventory."""
        well_id = new_unadopted_well()
        response = client.get(
            "/api/v1/wells",
            headers={"Authorization": f"Bearer {unclaimed_tenant_token}"},
            params={"limit": 1000},
        )
        ids = {item["id"] for item in response.json()["items"]}
        assert well_id not in ids

    def test_claimable_is_a_superset_of_visible(
        self, client: TestClient, unclaimed_tenant_token: str, new_unadopted_well
    ):
        new_unadopted_well()
        strict = client.get(
            "/api/v1/wells",
            headers={"Authorization": f"Bearer {unclaimed_tenant_token}"},
            params={"limit": 1000},
        ).json()
        wide = client.get(
            "/api/v1/wells",
            headers={"Authorization": f"Bearer {unclaimed_tenant_token}"},
            params={"include_claimable": True, "limit": 1000},
        ).json()
        assert wide["total"] >= strict["total"]
        assert {item["id"] for item in strict["items"]} <= {
            item["id"] for item in wide["items"]
        }

    def test_map_flags_which_wells_are_still_unadopted(
        self, client: TestClient, unclaimed_tenant_token: str, new_unadopted_well
    ):
        well_id = new_unadopted_well()
        response = client.get(
            "/api/v1/wells/map",
            headers={"Authorization": f"Bearer {unclaimed_tenant_token}"},
            params={"include_claimable": True, "limit": 20000},
        )
        assert response.status_code == 200
        flagged = {
            feature["properties"]["id"]: feature["properties"]["claimable"]
            for feature in response.json()["features"]
        }
        assert flagged.get(well_id) is True

    def test_a_well_in_another_tenants_project_is_never_claimable(
        self,
        client: TestClient,
        unclaimed_tenant_token: str,
        new_unadopted_well,
        admin_token: str,
    ):
        """The assertion that matters most.

        Adoption must not become a way to take another organisation's work: a
        well inside any project is neither offered as claimable nor readable.
        """
        well_id = new_unadopted_well()

        project = client.post(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "Foreign adoption probe"},
        )
        assert project.status_code == 201
        client.post(
            f"/api/v1/projects/{project.json()['id']}/wells/{well_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

        response = client.get(
            "/api/v1/wells/map",
            headers={"Authorization": f"Bearer {unclaimed_tenant_token}"},
            params={"include_claimable": True, "limit": 20000},
        )
        ids = {feature["properties"]["id"] for feature in response.json()["features"]}
        assert well_id not in ids

        blocked = client.get(
            f"/api/v1/wells/{well_id}",
            headers={"Authorization": f"Bearer {unclaimed_tenant_token}"},
        )
        assert blocked.status_code == 404

    def test_adoption_makes_the_record_readable(
        self, client: TestClient, unclaimed_tenant_token: str, new_unadopted_well
    ):
        """The whole point: adopt a well, and it opens - as claimable no longer."""
        well_id = new_unadopted_well()

        project = client.post(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {unclaimed_tenant_token}"},
            json={"name": "Adoption test"},
        )
        assert project.status_code == 201

        added = client.post(
            f"/api/v1/projects/{project.json()['id']}/wells/{well_id}",
            headers={"Authorization": f"Bearer {unclaimed_tenant_token}"},
        )
        assert added.status_code == 204

        detail = client.get(
            f"/api/v1/wells/{well_id}",
            headers={"Authorization": f"Bearer {unclaimed_tenant_token}"},
        )
        assert detail.status_code == 200
        assert detail.json()["id"] == well_id

        # Visible in a plain search now, and no longer offered as claimable.
        strict = client.get(
            "/api/v1/wells",
            headers={"Authorization": f"Bearer {unclaimed_tenant_token}"},
            params={"limit": 1000},
        ).json()
        assert well_id in {item["id"] for item in strict["items"]}

        again = client.get(
            "/api/v1/wells/map",
            headers={"Authorization": f"Bearer {unclaimed_tenant_token}"},
            params={"include_claimable": True, "limit": 20000},
        ).json()
        flagged = {
            feature["properties"]["id"]: feature["properties"]["claimable"]
            for feature in again["features"]
        }
        assert flagged[well_id] is False

    def test_adopting_a_well_another_tenant_holds_is_impossible_by_default(
        self, client: TestClient, unclaimed_tenant_token: str, other_tenant_token: str
    ):
        """A well visible to one tenant is invisible to another, claimable or not.

        ``add_well_to_project`` accepts any well id, which is what lets adoption
        work at all. This test pins the reason that is acceptable: it only ever
        transfers a well nobody holds, so the API cannot be used to enumerate or
        hijack another organisation's shortlist.
        """
        held = client.get(
            "/api/v1/wells",
            headers={"Authorization": f"Bearer {other_tenant_token}"},
            params={"limit": 5},
        ).json()["items"]
        if not held:
            # The other tenant holds nothing, so there is nothing to protect.
            return
        target = held[0]["id"]

        blocked = client.get(
            f"/api/v1/wells/{target}",
            headers={"Authorization": f"Bearer {unclaimed_tenant_token}"},
        )
        assert blocked.status_code == 404

    def test_audit_log_requires_owner(self, client: TestClient, user: dict):
        """A non-owner must not be able to read the tenant's access record."""
        response = client.get(
            "/api/v1/auth/audit", headers=user and {"Authorization": f"Bearer {user['token']}"}
        )
        assert response.status_code == 403


class TestWellSearch:
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {BEARER['admin']}"}

    def test_search_returns_wells(self, client: TestClient, project_id: str):
        response = client.get("/api/v1/wells", headers=self._headers(), params={"limit": 10})
        assert response.status_code == 200
        body = response.json()
        assert body["total"] > 0
        assert len(body["items"]) <= 10
        assert body["spatial_dialect"] in ("postgis", "haversine")

    def test_search_by_name(self, client: TestClient, project_id: str):
        response = client.get(
            "/api/v1/wells",
            headers=self._headers(),
            params={"search": "Wealden", "limit": 10},
        )
        assert response.json()["total"] >= 1

    def test_temperature_filter(self, client: TestClient, project_id: str):
        response = client.get(
            "/api/v1/wells",
            headers=self._headers(),
            params={"min_temperature_c": 85, "limit": 50},
        )
        assert response.json()["total"] >= 1
        for item in response.json()["items"]:
            assert item["temperature_c"] >= 85

    def test_depth_filter(self, client: TestClient, project_id: str):
        response = client.get(
            "/api/v1/wells",
            headers=self._headers(),
            params={"min_depth_m": 1500, "max_depth_m": 3000, "limit": 50},
        )
        for item in response.json()["items"]:
            assert 1500 <= item["total_depth_m"] <= 3000

    def test_has_temperature_false_returns_only_unmeasured_wells(
        self, client: TestClient, project_id: str
    ):
        response = client.get(
            "/api/v1/wells",
            headers=self._headers(),
            params={"has_temperature": "false", "limit": 50},
        )
        assert response.json()["total"] >= 1
        for item in response.json()["items"]:
            assert item["temperature_c"] is None
            assert item["temperature_status"] == "UNKNOWN"

    def test_invalid_order_by_is_rejected(self, client: TestClient, project_id: str):
        """Ordering is allow-listed; a bad column must not reach SQL."""
        response = client.get(
            "/api/v1/wells",
            headers=self._headers(),
            params={"order_by": "latitude; DROP TABLE wells"},
        )
        assert response.status_code == 422
        assert "cannot order by" in response.json()["detail"]

    def test_out_of_range_latitude_is_rejected(self, client: TestClient, project_id: str):
        response = client.get(
            "/api/v1/wells",
            headers=self._headers(),
            params={"centre_lat": 10.0, "centre_lon": 0.0, "radius_m": 5000},
        )
        assert response.status_code == 422

    def test_facets_are_derived_from_data(self, client: TestClient, project_id: str):
        response = client.get("/api/v1/wells/facets", headers=self._headers())
        assert response.status_code == 200
        body = response.json()
        assert body["statuses"]
        assert body["temperature_range_c"]["min"] is not None
        assert body["total_wells"] > 0

    def test_excluding_mock_data_returns_nothing_in_development(
        self, client: TestClient, project_id: str
    ):
        """The mock exclusion must actually work, or the watermark is cosmetic."""
        response = client.get(
            "/api/v1/wells",
            headers=self._headers(),
            params={"include_mock": "false", "limit": 50},
        )
        assert response.json()["total"] == 0


class TestWellDetail:
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {BEARER['admin']}"}

    def test_detail_includes_temperatures_and_provenance(
        self, client: TestClient, project_id: str, any_well_id: str
    ):
        response = client.get(f"/api/v1/wells/{any_well_id}", headers=self._headers())
        assert response.status_code == 200
        body = response.json()
        assert body["well_id"] == "UK-MOCK-WLN-002"
        assert body["source"] == "mock_nsta"
        assert body["temperatures"]
        for t in body["temperatures"]:
            assert t["status"] in ("MEASURED", "DERIVED", "ESTIMATE", "ASSUMPTION", "UNKNOWN", "MODELLED")
            assert t["measurement_method"]

    def test_integrity_is_returned_when_assessed(
        self, client: TestClient, project_id: str, any_well_id: str
    ):
        response = client.get(f"/api/v1/wells/{any_well_id}", headers=self._headers())
        assert response.json()["integrity"] is not None
        assert response.json()["integrity"]["status"] == "good_condition"

    def test_unknown_well_returns_404(self, client: TestClient, project_id: str):
        response = client.get(f"/api/v1/wells/{uuid.uuid4()}", headers=self._headers())
        assert response.status_code == 404

    def test_malformed_uuid_returns_422(self, client: TestClient, project_id: str):
        response = client.get("/api/v1/wells/not-a-uuid", headers=self._headers())
        assert response.status_code == 422

    def test_demand_endpoint_returns_matching_buildings(
        self, client: TestClient, project_id: str, any_well_id: str
    ):
        response = client.get(
            f"/api/v1/wells/{any_well_id}/demand", headers=self._headers(),
            params={"radius_m": 2000},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["building_count"] > 0
        assert body["total_annual_demand_kwh"] > 0
        for b in body["buildings"]:
            assert b["distance_m"] <= 2000

    def test_demand_confidence_is_reported(self, client: TestClient, project_id: str, any_well_id: str):
        body = client.get(
            f"/api/v1/wells/{any_well_id}/demand", headers=self._headers()
        ).json()
        assert body["demand_confidence"] in ("high", "medium", "low", "very_low", "unknown")


class TestMap:
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {BEARER['admin']}"}

    def test_map_returns_geojson(self, client: TestClient, project_id: str):
        response = client.get("/api/v1/wells/map", headers=self._headers())
        assert response.status_code == 200
        body = response.json()
        assert body["type"] == "FeatureCollection"
        assert body["features"]
        feature = body["features"][0]
        assert feature["geometry"]["type"] == "Point"
        assert len(feature["geometry"]["coordinates"]) == 2
        assert "score" in feature["properties"]
        assert "confidence" in feature["properties"]

    def test_mock_features_are_flagged_for_the_watermark(
        self, client: TestClient, project_id: str
    ):
        features = client.get("/api/v1/wells/map", headers=self._headers()).json()["features"]
        assert all(f["properties"]["is_mock"] for f in features)

    def test_radius_filter_reduces_the_count(self, client: TestClient, project_id: str):
        everything = client.get("/api/v1/wells/map", headers=self._headers()).json()
        local = client.get(
            "/api/v1/wells/map",
            headers=self._headers(),
            params={"centre_lat": 51.118, "centre_lon": 0.29, "radius_m": 5000},
        ).json()
        assert len(local["features"]) < len(everything["features"])


class TestAnalysis:
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {BEARER['admin']}"}

    def test_run_assessment_returns_full_result(
        self, client: TestClient, project_id: str, any_well_id: str
    ):
        response = client.post(
            "/api/v1/analyses",
            headers=self._headers(),
            json={"well_id": any_well_id, "include_ai_agents": True},
        )
        assert response.status_code == 201
        body = response.json()

        # Every field the specification requires on the result surface.
        for key in (
            "feasibility_score", "confidence_score", "thermal_output_kw",
            "thermal_output_status", "lcoh_p_per_kwh", "capex_gbp",
            "recommendation", "next_action", "risk", "confidence_detail",
            "calculation_trace", "data_gaps", "warnings",
        ):
            assert key in body, key

    def test_thermal_output_is_labelled_not_measured(
        self, client: TestClient, project_id: str, any_well_id: str
    ):
        """No flow test exists in the development data, so output must be ESTIMATE."""
        body = client.post(
            "/api/v1/analyses",
            headers=self._headers(),
            json={"well_id": any_well_id},
        ).json()
        assert body["thermal_output_status"] in ("ESTIMATE", "UNKNOWN")
        assert body["thermal_output_status"] != "MEASURED"

    def test_recommendation_is_one_of_four_levels(
        self, client: TestClient, project_id: str, any_well_id: str
    ):
        body = client.post(
            "/api/v1/analyses", headers=self._headers(), json={"well_id": any_well_id}
        ).json()
        assert body["recommendation"] in (
            "HIGH PRIORITY", "MEDIUM PRIORITY", "LOW PRIORITY", "DO NOT PURSUE",
        )

    def test_recommendation_has_a_rationale(self, client: TestClient, project_id: str, any_well_id: str):
        body = client.post(
            "/api/v1/analyses", headers=self._headers(), json={"well_id": any_well_id}
        ).json()
        assert body["recommendation_rationale"]

    def test_confidence_is_separate_from_feasibility(
        self, client: TestClient, project_id: str, any_well_id: str
    ):
        body = client.post(
            "/api/v1/analyses", headers=self._headers(), json={"well_id": any_well_id}
        ).json()
        assert 0.0 <= body["confidence_score"] <= 1.0
        assert 0.0 <= body["feasibility_score"] <= 100.0

    def test_trace_exposes_the_six_required_fields(
        self, client: TestClient, project_id: str, any_well_id: str
    ):
        body = client.post(
            "/api/v1/analyses", headers=self._headers(), json={"well_id": any_well_id}
        ).json()
        assert body["calculation_trace"]
        for trace in body["calculation_trace"]:
            for key in ("inputs", "input_units", "formula", "result", "status"):
                assert key in trace, key

    def test_progress_returns_all_nine_stages(
        self, client: TestClient, project_id: str, any_well_id: str
    ):
        created = client.post(
            "/api/v1/analyses", headers=self._headers(), json={"well_id": any_well_id}
        ).json()
        response = client.get(
            f"/api/v1/analyses/{created['analysis_id']}/progress",
            headers=self._headers(),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "complete"
        assert body["percent_complete"] == 100
        assert len(body["completed_stages"]) == 9
        assert len(body["stage_messages"]) == 9

    def test_report_is_generated_with_disclaimers(
        self, client: TestClient, project_id: str, any_well_id: str
    ):
        created = client.post(
            "/api/v1/analyses", headers=self._headers(), json={"well_id": any_well_id}
        ).json()
        response = client.get(
            f"/api/v1/analyses/{created['analysis_id']}/report", headers=self._headers()
        )
        assert response.status_code == 200
        assert "not a statement of commercial viability" in response.text

    def test_report_covers_all_required_sections(
        self, client: TestClient, project_id: str, any_well_id: str
    ):
        created = client.post(
            "/api/v1/analyses", headers=self._headers(), json={"well_id": any_well_id}
        ).json()
        report = client.get(
            f"/api/v1/analyses/{created['analysis_id']}/report", headers=self._headers()
        ).text
        for section in ("Executive summary", "Temperature assessment", "Geology",
                        "Well integrity", "Thermal output", "Heat demand",
                        "CAPEX", "OPEX", "LCOH", "NPV", "IRR",
                        "Environmental considerations", "Risks",
                        "Sensitivity analysis",
                        "Regulatory considerations", "Data gaps",
                        "Validation plan", "Final recommendation"):
            assert section in report, section

    def test_sensitivity_section_quotes_no_spread_it_did_not_compute(
        self, client: TestClient, project_id: str, any_well_id: str
    ):
        """A single scenario cannot honestly report a sensitivity range.

        The section must name the assumptions the engine used and say where the
        comparison is actually run, rather than presenting a fabricated spread
        as if it had been calculated here.
        """
        created = client.post(
            "/api/v1/analyses", headers=self._headers(), json={"well_id": any_well_id}
        ).json()
        report = client.get(
            f"/api/v1/analyses/{created['analysis_id']}/report", headers=self._headers()
        ).text
        start = report.index("## Sensitivity analysis")
        end = report.find("## ", start + 5)
        body = report[start:end if end != -1 else None]
        assert "single scenario" in body
        assert "Monte Carlo simulation is not implemented" in body

    def test_report_never_claims_viability(
        self, client: TestClient, project_id: str, any_well_id: str
    ):
        created = client.post(
            "/api/v1/analyses", headers=self._headers(), json={"well_id": any_well_id}
        ).json()
        report = client.get(
            f"/api/v1/analyses/{created['analysis_id']}/report", headers=self._headers()
        ).text.lower()
        assert "commercially viable" not in report
        assert "risk-free" not in report
        assert "guaranteed" not in report

    def test_agent_outputs_are_flagged_as_mock(
        self, client: TestClient, project_id: str, any_well_id: str
    ):
        """The UI must be able to tell the reader which provider wrote the prose."""
        body = client.post(
            "/api/v1/analyses", headers=self._headers(), json={"well_id": any_well_id}
        ).json()
        assert body["agent_outputs"]["is_mock"] is True
        assert body["agent_outputs"]["provider"] == "mock"

    def test_analysis_without_agents_still_returns_numbers(
        self, client: TestClient, project_id: str, any_well_id: str
    ):
        """Deterministic results must be identical with or without the LLM."""
        body = client.post(
            "/api/v1/analyses",
            headers=self._headers(),
            json={"well_id": any_well_id, "include_ai_agents": False},
        ).json()
        assert body["feasibility_score"] > 0
        assert body["thermal_output_kw"] > 0

    def test_analysis_is_persisted_and_retrievable(
        self, client: TestClient, project_id: str, any_well_id: str
    ):
        created = client.post(
            "/api/v1/analyses", headers=self._headers(), json={"well_id": any_well_id}
        ).json()
        fetched = client.get(
            f"/api/v1/analyses/{created['analysis_id']}", headers=self._headers()
        )
        assert fetched.status_code == 200
        assert fetched.json()["analysis_id"] == created["analysis_id"]
        # The UUID is the key every well endpoint takes; `well_id` is only the
        # publisher's id and cannot be used to open or filter by a well.
        assert created["well_uuid"] == any_well_id
        assert fetched.json()["well_uuid"] == any_well_id

    def test_unknown_well_returns_404(self, client: TestClient, project_id: str):
        response = client.post(
            "/api/v1/analyses", headers=self._headers(), json={"well_id": str(uuid.uuid4())}
        )
        assert response.status_code == 404


class TestScenarios:
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {BEARER['admin']}"}

    def test_bear_base_bull_produce_a_range(
        self, client: TestClient, project_id: str, any_well_id: str
    ):
        response = client.post(
            f"/api/v1/analyses/{any_well_id}/scenarios",
            headers=self._headers(),
            json=[
                {"name": "bear", "inputs": {"flow_rate_lps": 8, "capex_gbp": 4_000_000}},
                {"name": "base", "inputs": {"flow_rate_lps": 20}},
                {"name": "bull", "inputs": {"flow_rate_lps": 45, "capex_gbp": 1_500_000}},
            ],
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["scenarios"]) == 3
        assert body["spread_lcoh_p_per_kwh"] is not None
        assert body["spread_lcoh_p_per_kwh"] > 0

    def test_overrides_are_recorded_per_scenario(
        self, client: TestClient, project_id: str, any_well_id: str
    ):
        body = client.post(
            f"/api/v1/analyses/{any_well_id}/scenarios",
            headers=self._headers(),
            json=[
                {"name": "bear", "inputs": {"flow_rate_lps": 8}},
                {"name": "base", "inputs": {}},
            ],
        ).json()
        bear = next(s for s in body["scenarios"] if s["name"] == "bear")
        base = next(s for s in body["scenarios"] if s["name"] == "base")
        assert bear["overrides_applied"]["flow_rate_lps"] is True
        assert base["overrides_applied"]["flow_rate_lps"] is False

    def test_no_weights_means_no_expected_value(
        self, client: TestClient, project_id: str, any_well_id: str
    ):
        """An unweighted average across bear/base/bull has no interpretation."""
        body = client.post(
            f"/api/v1/analyses/{any_well_id}/scenarios",
            headers=self._headers(),
            json=[{"name": "bear", "inputs": {}}, {"name": "bull", "inputs": {}}],
        ).json()
        assert body["expected_lcoh_p_per_kwh"] is None
        assert any("probability weights" in n for n in body["notes"])

    def test_weights_produce_an_expected_value(
        self, client: TestClient, project_id: str, any_well_id: str
    ):
        body = client.post(
            f"/api/v1/analyses/{any_well_id}/scenarios",
            headers=self._headers(),
            json=[
                {"name": "bear", "inputs": {"flow_rate_lps": 8}, "probability_weight": 0.25},
                {"name": "bull", "inputs": {"flow_rate_lps": 45}, "probability_weight": 0.75},
            ],
        ).json()
        assert body["expected_lcoh_p_per_kwh"] is not None

    def test_empty_scenario_list_rejected(
        self, client: TestClient, project_id: str, any_well_id: str
    ):
        response = client.post(
            f"/api/v1/analyses/{any_well_id}/scenarios", headers=self._headers(), json=[]
        )
        assert response.status_code == 422


class TestWhatIf:
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {BEARER['admin']}"}

    def test_overriding_flow_rate_changes_output(
        self, client: TestClient, project_id: str, any_well_id: str
    ):
        """Flow rate enters the output linearly, so doubling it doubles the kW.

        This is the check that the what-if endpoint actually re-runs the
        deterministic engine rather than returning a cached result.
        """
        base = client.post(
            "/api/v1/analyses/what-if",
            headers=self._headers(),
            params={"well_uuid": any_well_id},
            json={},
        )
        assert base.status_code == 200, base.text
        base_body = base.json()

        higher = client.post(
            "/api/v1/analyses/what-if",
            headers=self._headers(),
            params={"well_uuid": any_well_id},
            json={"flow_rate_lps": 50},
        )
        assert higher.status_code == 200, higher.text
        higher_body = higher.json()

        # The default flow is 20 L/s, so 50 should be 2.5x the output.
        assert higher_body["thermal_output_kw"] == pytest.approx(
            base_body["thermal_output_kw"] * 2.5, rel=0.01
        )

    def test_nothing_is_persisted(self, client: TestClient, project_id: str, any_well_id: str):
        before = client.get("/api/v1/analyses", headers=self._headers()).json()
        client.post(
            "/api/v1/analyses/what-if",
            headers=self._headers(),
            params={"well_id": any_well_id},
            json={"flow_rate_lps": 99},
        )
        after = client.get("/api/v1/analyses", headers=self._headers()).json()
        assert len(after) == len(before)

    def test_extra_fields_are_rejected(
        self, client: TestClient, project_id: str, any_well_id: str
    ):
        """Unrecognised inputs must be refused, not silently ignored."""
        response = client.post(
            "/api/v1/analyses/what-if",
            headers=self._headers(),
            params={"well_id": any_well_id},
            json={"arbitrary_field": 1},
        )
        assert response.status_code == 422


class TestDashboard:
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {BEARER['admin']}"}

    def test_national_headlines(self, client: TestClient, project_id: str):
        response = client.get("/api/v1/dashboard/national", headers=self._headers())
        assert response.status_code == 200
        body = response.json()
        assert body["total_wells"] > 0
        assert body["wells_with_temperature"] > 0
        assert body["wells_without_temperature"] > 0
        assert body["average_temperature_c"] is not None
        assert body["total_estimated_thermal_capacity_status"] == "ESTIMATE"

    def test_counts_add_up(self, client: TestClient, project_id: str):
        body = client.get("/api/v1/dashboard/national", headers=self._headers()).json()
        assert (
            body["wells_with_temperature"] + body["wells_without_temperature"]
            == body["total_wells"]
        )

    def test_mock_data_is_disclosed(self, client: TestClient, project_id: str):
        body = client.get("/api/v1/dashboard/national", headers=self._headers()).json()
        assert body["is_mock"] is True
        assert any("synthetic" in c.lower() for c in body["caveats"])

    def test_score_histogram_reports_unassessed_separately(
        self, client: TestClient, project_id: str
    ):
        body = client.get("/api/v1/dashboard/national", headers=self._headers()).json()
        buckets = body["score_histogram"]
        assert any(b["range"] == "not assessed" for b in buckets)

    def test_candidate_table_has_every_specified_column(
        self, client: TestClient, project_id: str
    ):
        response = client.get(
            "/api/v1/dashboard/candidates", headers=self._headers(), params={"limit": 20}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] > 0
        row = body["items"][0]
        for column in (
            "rank", "well_id", "well_name", "latitude", "longitude", "status",
            "total_depth_m", "temperature_c", "temperature_status",
            "temperature_confidence", "annual_demand_kwh",
            "nearest_building_distance_m", "thermal_output_kw", "capex_gbp",
            "lcoh_p_per_kwh", "feasibility_score", "confidence_score",
            "recommendation",
        ):
            assert column in row, column

    def test_candidate_rows_carry_a_uuid_that_opens_the_well(
        self, client: TestClient, project_id: str
    ):
        """`well_id` is the publisher's id; the UUID is the key every endpoint takes.

        NSTA ids look like "LN/10- 4Z": not a UUID, and not usable as a URL
        segment. A page that used `well_id` to open, assess or filter by a well
        therefore failed on real data while working on synthetic ids.
        """
        items = client.get(
            "/api/v1/dashboard/candidates", headers=self._headers(), params={"limit": 5}
        ).json()["items"]
        assert items
        for row in items:
            uuid.UUID(row["well_uuid"])
            assert row["well_uuid"] != row["well_id"]
            well = client.get(f"/api/v1/wells/{row['well_uuid']}", headers=self._headers())
            assert well.status_code == 200
            assert well.json()["well_id"] == row["well_id"]
            listed = client.get(
                "/api/v1/analyses",
                headers=self._headers(),
                params={"well_id": row["well_uuid"], "limit": 1},
            )
            assert listed.status_code == 200
            for analysis in listed.json():
                assert analysis["well_uuid"] == row["well_uuid"]

    def test_publisher_id_is_not_accepted_as_a_well_key(
        self, client: TestClient, project_id: str
    ):
        """Pins the contract the frontend has to respect: UUIDs only."""
        response = client.get(
            "/api/v1/analyses",
            headers=self._headers(),
            params={"well_id": "LN/10- 4Z", "limit": 1},
        )
        assert response.status_code == 422

    def test_ranks_are_sequential(self, client: TestClient, project_id: str):
        items = client.get(
            "/api/v1/dashboard/candidates", headers=self._headers(), params={"limit": 20}
        ).json()["items"]
        assert [i["rank"] for i in items] == list(range(1, len(items) + 1))

    def test_candidates_sorted_by_score_descending(self, client: TestClient, project_id: str):
        items = client.get(
            "/api/v1/dashboard/candidates", headers=self._headers(), params={"limit": 20}
        ).json()["items"]
        scores = [i["feasibility_score"] for i in items if i["feasibility_score"] is not None]
        assert scores == sorted(scores, reverse=True)

    def test_pagination_reports_totals(self, client: TestClient, project_id: str):
        body = client.get(
            "/api/v1/dashboard/candidates",
            headers=self._headers(),
            params={"limit": 3, "offset": 0},
        ).json()
        assert len(body["items"]) == 3
        assert body["total"] > 3
        assert body["ranking_basis"] == "feasibility_score"

    def test_summary_exposes_the_weights(self, client: TestClient, project_id: str):
        body = client.get("/api/v1/dashboard/summary", headers=self._headers()).json()
        assert body["weights_sum"] == pytest.approx(1.0)
        assert body["weights"]["thermal"] == 0.25
        assert len(body["stages"]) == 9
        assert len(body["recommendation_levels"]) == 4


class TestHeatEndpoints:
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {BEARER['admin']}"}

    def test_nearby_buildings(self, client: TestClient, project_id: str):
        response = client.get(
            "/api/v1/heat/buildings",
            headers=self._headers(),
            params={"lat": 51.118, "lon": 0.29, "radius_m": 1500},
        )
        assert response.status_code == 200
        for b in response.json():
            assert b["distance_m"] <= 1500

    def test_clusters_report_nearest_well(self, client: TestClient, project_id: str):
        response = client.get(
            "/api/v1/heat/clusters", headers=self._headers(), params={"cell_deg": 0.02}
        )
        assert response.status_code == 200
        clusters = response.json()
        assert clusters
        for c in clusters:
            if c["nearest_well_distance_m"] is not None:
                assert c["nearest_well_distance_m"] <= 3000

    def test_cluster_nearest_well_uuid_matches_its_publisher_id(
        self, client: TestClient, project_id: str
    ):
        clusters = client.get(
            "/api/v1/heat/clusters", headers=self._headers(), params={"cell_deg": 0.02}
        ).json()
        attributed = [c for c in clusters if c["nearest_well_id"]]
        assert attributed
        for cluster in attributed[:5]:
            well = client.get(
                f"/api/v1/wells/{cluster['nearest_well_uuid']}", headers=self._headers()
            )
            assert well.status_code == 200
            assert well.json()["well_id"] == cluster["nearest_well_id"]
        for cluster in clusters:
            if not cluster["nearest_well_id"]:
                assert cluster["nearest_well_uuid"] is None

    def test_clusters_flag_the_backend(self, client: TestClient, project_id: str):
        clusters = client.get(
            "/api/v1/heat/clusters", headers=self._headers()
        ).json()
        assert all(c["is_clustered_with_postgis"] is False for c in clusters)

    def test_density_grid(self, client: TestClient, project_id: str):
        response = client.get(
            "/api/v1/heat/density", headers=self._headers(), params={"cell_deg": 0.2}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["count"] > 0
        assert body["totals"]["wells"] > 0

    def test_corridors_are_labelled_indicative(self, client: TestClient, project_id: str):
        response = client.get(
            "/api/v1/heat/corridors", headers=self._headers(), params={"limit_wells": 30}
        )
        assert response.status_code == 200
        body = response.json()
        assert "understates" in body["caveat"]
        for corridor in body["corridors"]:
            assert corridor["indicative"] is True
            assert "not a route" in corridor["note"].lower()

    def test_demand_summary_caveats_modelled_figures(self, client: TestClient, project_id: str):
        body = client.get("/api/v1/heat/demand-summary", headers=self._headers()).json()
        assert "not metered" in body["caveat"]
        assert body["totals"]["buildings"] > 0


class TestAdmin:
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {BEARER['admin']}"}

    def test_datasets_carry_provenance(self, client: TestClient):
        body = client.get("/api/v1/admin/datasets", headers=self._headers()).json()
        assert body["counts"]["total"] > 0
        for dataset in body["datasets"]:
            for key in ("source", "version", "quality_score", "is_mock", "licence"):
                assert key in dataset

    def test_mock_datasets_are_disclosed(self, client: TestClient, loaded_data: dict):
        body = client.get("/api/v1/admin/datasets", headers=self._headers()).json()
        assert body["counts"]["mock"] > 0
        assert body["note"]

    def test_adapters_are_listed(self, client: TestClient):
        body = client.get("/api/v1/admin/adapters", headers=self._headers()).json()
        assert body["count"] > 0
        # Synthetic adapters are flagged synthetic by name and flag; the real
        # NSTA adapter is flagged real. No adapter may be ambiguous.
        for a in body["adapters"]:
            assert a["is_mock"] == a["name"].startswith("mock_"), a
        assert any(not a["is_mock"] for a in body["adapters"]), "real NSTA adapter missing"

    def test_ingest_requires_owner(self, client: TestClient, user: dict):
        response = client.post(
            "/api/v1/admin/ingest",
            headers={"Authorization": f"Bearer {user['token']}"},
            params={"adapter": "mock_wells"},
        )
        assert response.status_code == 403

    def test_dry_run_ingest_writes_nothing(self, client: TestClient):
        before = client.get("/api/v1/wells", headers=self._headers()).json()["total"]
        response = client.post(
            "/api/v1/admin/ingest",
            headers=self._headers(),
            params={"adapter": "mock_wells", "dry_run": "true"},
        )
        assert response.status_code == 200
        after = client.get("/api/v1/wells", headers=self._headers()).json()["total"]
        assert before == after

    def test_unknown_adapter_rejected(self, client: TestClient):
        response = client.post(
            "/api/v1/admin/ingest",
            headers=self._headers(),
            params={"adapter": "does-not-exist"},
        )
        assert response.status_code == 404

    def test_prices_include_decomposition(self, client: TestClient, loaded_data: dict):
        body = client.get("/api/v1/admin/prices", headers=self._headers()).json()
        assert body["count"] > 0
        assert any(p["price_basis"] for p in body["prices"])

    def test_heat_price_is_flagged_as_assumption(
        self, client: TestClient, loaded_data: dict
    ):
        body = client.get(
            "/api/v1/admin/prices",
            headers=self._headers(),
            params={"fuel": "heat_district_estimated"},
        ).json()
        assert all(p["status"] == "ASSUMPTION" for p in body["prices"])

    def test_regulatory_lead_times_are_caveated(
        self, client: TestClient, loaded_data: dict
    ):
        body = client.get("/api/v1/admin/regulatory", headers=self._headers()).json()
        assert body["count"] > 0
        assert "engineering estimates" in body["caveat"]

    def test_engineering_parameters_expose_rationales(self, client: TestClient):
        body = client.get("/api/v1/admin/parameters", headers=self._headers()).json()
        assert body["count"] > 10
        for spec in body["parameters"]:
            assert spec["rationale"], spec["key"]

    def test_configuration_filter_on_regulatory(
        self, client: TestClient, loaded_data: dict
    ):
        closed = client.get(
            "/api/v1/admin/regulatory",
            headers=self._headers(),
            params={"configuration": "closed_loop"},
        ).json()
        open_loop = client.get(
            "/api/v1/admin/regulatory",
            headers=self._headers(),
            params={"configuration": "open_loop"},
        ).json()
        # An open loop carries strictly more consent burden than a closed loop.
        assert len(open_loop["requirements"]) > len(closed["requirements"])


class TestProjects:
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {BEARER['admin']}"}

    def test_create_and_list(self, client: TestClient):
        created = client.post(
            "/api/v1/projects",
            headers=self._headers(),
            json={"name": "Test Project", "description": "Created by a test"},
        )
        assert created.status_code == 201
        assert created.json()["slug"].startswith("test-project")

        listed = client.get("/api/v1/projects", headers=self._headers()).json()
        assert any(p["name"] == "Test Project" for p in listed)

    def test_stage_can_be_changed_with_an_audit_entry(self, client: TestClient):
        created = client.post(
            "/api/v1/projects", headers=self._headers(), json={"name": "Stage Test"}
        ).json()
        response = client.patch(
            f"/api/v1/projects/{created['id']}/stage",
            headers=self._headers(),
            params={"stage": "due_diligence"},
        )
        assert response.status_code == 200
        assert response.json()["stage"] == "due_diligence"
        assert response.json()["previous_stage"] == "sourcing"

    def test_invalid_stage_rejected(self, client: TestClient):
        created = client.post(
            "/api/v1/projects", headers=self._headers(), json={"name": "Bad Stage"}
        ).json()
        response = client.patch(
            f"/api/v1/projects/{created['id']}/stage",
            headers=self._headers(),
            params={"stage": "teleported"},
        )
        assert response.status_code == 422

    def test_adding_a_well_makes_it_visible(
        self, client: TestClient, other_tenant_token: str, any_well_id: str
    ):
        """The whole tenant-isolation model depends on this working.

        The claim is withdrawn before returning. These tests run in a
        randomised order alongside ``TestTenantIsolation``, and leaving the
        shared well claimed by the other organisation turned its expected 404
        into a 200. The guard under test was fine; the state leaking out of
        here was not, and a test that quietly narrows what every later test can
        assert is worse than one that fails on its own.
        """
        from app.db.session import SessionLocal

        created = client.post(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {other_tenant_token}"},
            json={"name": "Other Org Project", "well_ids": [any_well_id]},
        )
        assert created.status_code == 201
        created_project_id = created.json()["id"]

        try:
            response = client.get(
                f"/api/v1/wells/{any_well_id}",
                headers={"Authorization": f"Bearer {other_tenant_token}"},
            )
            assert response.status_code == 200
            assert response.json()["well_id"] == "UK-MOCK-WLN-002"
        finally:
            with SessionLocal() as session:
                # ``project_id`` is a UUID column, so the id from the JSON body
                # has to be converted before it can be used in a filter.
                session.query(ProjectWell).filter(
                    ProjectWell.project_id == uuid.UUID(created_project_id)
                ).delete(synchronize_session=False)
                session.commit()


class TestDataProvenance:
    def test_every_well_carries_a_source(self, client: TestClient, project_id: str):
        """Every well must name the adapter that wrote it.

        Checked on the detail endpoint: the summary is deliberately terse and
        carries only the derived ``is_mock`` flag, not the raw source string.
        """
        headers = {"Authorization": f"Bearer {BEARER['admin']}"}
        items = client.get(
            "/api/v1/wells", headers=headers, params={"limit": 100}
        ).json()["items"]
        assert items

        for item in items:
            detail = client.get(f"/api/v1/wells/{item['id']}", headers=headers).json()
            assert detail["source"], detail["well_id"]
            # The source string is what makes "mock_" exclusion possible, so it
            # must be the raw adapter id rather than a display label.
            assert detail["source"].startswith("mock_") or detail["source"] in (
                "nsta", "bgs_wells", "bgs_geothermal",
            )

    def test_no_well_claims_a_temperature_without_a_status(
        self, client: TestClient, project_id: str
    ):
        """Every temperature figure must be accompanied by its provenance label.

        Checked against the detail endpoint, where the rolled-up value and its
        status travel together. The summary endpoint carries the status too, but
        the detail response is what the well page renders.
        """
        headers = {"Authorization": f"Bearer {BEARER['admin']}"}
        wells = client.get("/api/v1/wells", headers=headers, params={"limit": 100}).json()["items"]
        assert wells

        for item in wells:
            detail = client.get(f"/api/v1/wells/{item['id']}", headers=headers).json()
            if detail["temperature_c"] is not None:
                assert detail["temperature_status"] in (
                    "MEASURED", "DERIVED", "ESTIMATE", "MODELLED", "FACT",
                )
                # A temperature never travels without the method that produced it.
                assert any(
                    t["measurement_method"] for t in detail["temperatures"]
                ), detail["well_id"]
            else:
                assert detail["temperature_status"] == "UNKNOWN"
                assert not detail["temperatures"]

    def test_mock_wells_are_flagged_in_summaries(
        self, client: TestClient, project_id: str
    ):
        items = client.get(
            "/api/v1/wells", headers={"Authorization": f"Bearer {BEARER['admin']}"},
            params={"limit": 5},
        ).json()["items"]
        assert all(item["is_mock"] for item in items)


# Populated at session start so data-dependent fixtures can resolve the tokens.
BEARER: dict[str, str] = {}


@pytest.fixture(autouse=True)
def _register_tokens(request: pytest.FixtureRequest):
    """Make the admin token available to the ``self._headers`` helpers.

    Resolved unconditionally rather than only when a test happens to list
    ``admin_token`` among its parameters. The ``_headers`` helpers read this
    module global, and ``TestProjects`` builds its headers the same way while
    declaring no token fixture at all - so it raised ``KeyError: 'admin'``
    whenever it shuffled to the front of a randomised run.
    """
    BEARER["admin"] = request.getfixturevalue("admin_token")
    yield
