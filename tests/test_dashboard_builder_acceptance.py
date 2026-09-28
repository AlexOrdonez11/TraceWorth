"""Independent API acceptance for saved, account-scoped dashboard layouts.

Every test uses a generated SQLite database; no local account or telemetry file
is read or changed. PostgreSQL parity is exercised by the opt-in suite below.
"""

from contextlib import closing
from pathlib import Path
import json
import os
import sqlite3
import tempfile
import unittest
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from fastapi.testclient import TestClient

from traceworth.backend import create_app
from traceworth.backend.storage import Database, INDEXES, SCHEMA
from traceworth.backend.management import provision_runtime_role

try:
    import psycopg
    from psycopg import sql
except ImportError:
    psycopg = None
    sql = None

POSTGRES_DSN = os.environ.get("TRACEWORTH_TEST_POSTGRES_DSN")


ORIGIN = "http://localhost:5173"
PASSWORD = "temporary-dashboard-password-123!"
WIDGETS = [
    {"type": "metric_workflows", "width": "half"},
    {"type": "cost_breakdown", "width": "full"},
]
ALL_TYPES = (
    "metric_workflows", "metric_acceptance", "metric_unknown_cost",
    "cost_breakdown", "usage_coverage", "workflow_comparison",
    "findings", "workflow_list",
)


class DashboardBuilderAcceptance(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / "dashboards.sqlite3"
        self.app = create_app(database_path=self.database, allowed_origins=[ORIGIN])
        self.alice = TestClient(self.app)
        self.bob = TestClient(self.app)
        self.addCleanup(self.alice.close)
        self.addCleanup(self.bob.close)
        self.alice_auth = self.register(self.alice, "alice@example.test")
        self.bob_auth = self.register(self.bob, "bob@example.test")
        self.alice_headers = {"X-CSRF-Token": self.alice_auth["csrf_token"], "Origin": ORIGIN}
        self.bob_headers = {"X-CSRF-Token": self.bob_auth["csrf_token"], "Origin": ORIGIN}
        self.alice_app = self.application(self.alice, self.alice_headers, "alice-app")
        self.alice_other_app = self.application(self.alice, self.alice_headers, "alice-other")
        self.bob_app = self.application(self.bob, self.bob_headers, "bob-app")

    def register(self, client, email):
        response = client.post(
            "/api/auth/register",
            json={"email": email, "password": PASSWORD, "account_name": email},
            headers={"Origin": ORIGIN},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def application(self, client, headers, slug):
        response = client.post(
            "/api/applications", json={"name": slug, "slug": slug}, headers=headers,
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["application"]

    def create_dashboard(self, *, client=None, headers=None, application_id=None, name="Operations"):
        client = client or self.alice
        headers = headers or self.alice_headers
        application_id = application_id or self.alice_app["id"]
        response = client.post(
            "/api/dashboards",
            json={"name": name, "application_id": application_id, "widgets": WIDGETS},
            headers=headers,
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["dashboard"]

    def test_crud_reopen_reorder_and_reload_persistence(self):
        created = self.create_dashboard(name="  Operations  ")
        dashboard_id = created["id"]
        self.assertEqual(created["name"], "Operations")
        self.assertEqual(created["widgets"], WIDGETS)
        self.assertEqual(created["application_id"], self.alice_app["id"])
        self.assertTrue(created["created_at"])
        self.assertTrue(created["updated_at"])
        self.assertEqual(self.alice.get(f"/api/dashboards/{dashboard_id}").json()["dashboard"], created)
        self.assertEqual(self.alice.get("/api/dashboards").json()["dashboards"], [created])

        reordered = list(reversed(WIDGETS))
        response = self.alice.put(
            f"/api/dashboards/{dashboard_id}",
            json={"name": "Cost review", "widgets": reordered}, headers=self.alice_headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        updated = response.json()["dashboard"]
        self.assertEqual(updated["name"], "Cost review")
        self.assertEqual(updated["widgets"], reordered)
        self.assertEqual(updated["created_at"], created["created_at"])
        self.assertEqual(updated["application_id"], created["application_id"])

        # Reopening a fresh app process must retain the saved layout.
        reopened = create_app(database_path=self.database, allowed_origins=[ORIGIN])
        with closing(TestClient(reopened)) as fresh:
            login = fresh.post(
                "/api/auth/login", json={"email": "alice@example.test", "password": PASSWORD},
                headers={"Origin": ORIGIN},
            )
            self.assertEqual(login.status_code, 200, login.text)
            self.assertEqual(fresh.get(f"/api/dashboards/{dashboard_id}").json()["dashboard"], updated)

        deleted = self.alice.delete(f"/api/dashboards/{dashboard_id}", headers=self.alice_headers)
        self.assertEqual(deleted.status_code, 204, deleted.text)
        self.assertEqual(self.alice.get(f"/api/dashboards/{dashboard_id}").status_code, 404)
        self.assertEqual(self.alice.get("/api/dashboards").json()["dashboards"], [])

    def test_application_filter_and_two_account_isolation(self):
        first = self.create_dashboard(name="First")
        second = self.create_dashboard(application_id=self.alice_other_app["id"], name="Second")
        self.assertEqual(
            [d["id"] for d in self.alice.get("/api/dashboards", params={"application_id": self.alice_app["id"]}).json()["dashboards"]],
            [first["id"]],
        )
        self.assertEqual(
            {d["id"] for d in self.alice.get("/api/dashboards").json()["dashboards"]},
            {first["id"], second["id"]},
        )
        self.assertEqual(self.bob.get("/api/dashboards").json()["dashboards"], [])
        self.assertEqual(self.bob.get(f"/api/dashboards/{first['id']}").status_code, 404)
        self.assertEqual(self.alice.get("/api/dashboards", params={"application_id": self.bob_app["id"]}).status_code, 404)
        self.assertEqual(self.bob.get("/api/dashboards", params={"application_id": self.alice_app["id"]}).status_code, 404)

        foreign_create = self.alice.post(
            "/api/dashboards",
            json={"name": "Foreign", "application_id": self.bob_app["id"], "widgets": WIDGETS},
            headers=self.alice_headers,
        )
        self.assertEqual(foreign_create.status_code, 404, foreign_create.text)
        for method, payload in (
            ("PUT", {"name": "Hijacked", "widgets": WIDGETS}), ("DELETE", None),
        ):
            with self.subTest(method=method):
                response = self.bob.request(
                    method, f"/api/dashboards/{first['id']}", json=payload, headers=self.bob_headers,
                )
                self.assertEqual(response.status_code, 404, response.text)
        self.assertEqual(self.alice.get(f"/api/dashboards/{first['id']}").json()["dashboard"], first)

    def test_anonymous_and_sdk_bearer_cannot_read_or_write_dashboards(self):
        created = self.create_dashboard()
        key = self.alice.post(
            f"/api/applications/{self.alice_app['id']}/keys",
            json={"name": "SDK"}, headers=self.alice_headers,
        ).json()["token"]
        with closing(TestClient(self.app)) as outsider:
            for headers in ({}, {"Authorization": "Bearer " + key}):
                for method, path, payload in (
                    ("GET", "/api/dashboards", None),
                    ("GET", f"/api/dashboards/{created['id']}", None),
                    ("POST", "/api/dashboards", {"name": "No", "application_id": self.alice_app["id"], "widgets": WIDGETS}),
                    ("PUT", f"/api/dashboards/{created['id']}", {"name": "No", "widgets": WIDGETS}),
                    ("DELETE", f"/api/dashboards/{created['id']}", None),
                ):
                    with self.subTest(method=method, path=path, bearer=bool(headers)):
                        response = outsider.request(method, path, json=payload, headers=headers)
                        self.assertEqual(response.status_code, 401, response.text)
        self.assertEqual(self.alice.get(f"/api/dashboards/{created['id']}").json()["dashboard"], created)

    def test_csrf_and_exact_origin_protect_each_mutation(self):
        created = self.create_dashboard()
        operations = (
            ("POST", "/api/dashboards", {"name": "Blocked", "application_id": self.alice_app["id"], "widgets": WIDGETS}),
            ("PUT", f"/api/dashboards/{created['id']}", {"name": "Blocked", "widgets": WIDGETS}),
            ("DELETE", f"/api/dashboards/{created['id']}", None),
        )
        bad_headers = (
            {"Origin": ORIGIN},
            {"Origin": ORIGIN, "X-CSRF-Token": "wrong"},
            {"Origin": "https://attacker.example", "X-CSRF-Token": self.alice_auth["csrf_token"]},
            {"Origin": ORIGIN + ".attacker.example", "X-CSRF-Token": self.alice_auth["csrf_token"]},
            {"Origin": "null", "X-CSRF-Token": self.alice_auth["csrf_token"]},
        )
        for method, path, payload in operations:
            for headers in bad_headers:
                with self.subTest(method=method, headers=headers):
                    response = self.alice.request(method, path, json=payload, headers=headers)
                    self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self.alice.get("/api/dashboards").json()["dashboards"], [created])

    def test_strict_widget_and_name_validation_is_atomic(self):
        valid = {"name": "Valid", "application_id": self.alice_app["id"], "widgets": WIDGETS}
        invalid = (
            dict(valid, name=" "),
            dict(valid, name="x" * 81),
            dict(valid, name=0),
            dict(valid, name="Unsafe\x00name"),
            dict(valid, widgets=[]),
            dict(valid, widgets=WIDGETS + WIDGETS),
            dict(valid, widgets=[{"type": "arbitrary_query", "width": "full"}]),
            dict(valid, widgets=[{"type": "metric_workflows", "width": "oversized"}]),
            dict(valid, widgets=[{"type": "metric_workflows", "width": "half", "html": "<script>x</script>"}]),
            dict(valid, widgets=[{"type": "metric_workflows"}]),
            dict(valid, widgets=[{"type": t, "width": "half"} for t in ALL_TYPES] + [{"type": "metric_workflows", "width": "full"}]),
            dict(valid, unexpected=True),
        )
        for payload in invalid:
            with self.subTest(payload=payload):
                response = self.alice.post("/api/dashboards", json=payload, headers=self.alice_headers)
                self.assertEqual(response.status_code, 422, response.text)
        escaped_surrogate = self.alice.post(
            "/api/dashboards",
            content=json.dumps(dict(valid, name="Unsafe\ud800name"), ensure_ascii=True),
            headers=dict(self.alice_headers, **{"Content-Type": "application/json"}),
        )
        self.assertEqual(escaped_surrogate.status_code, 422, escaped_surrogate.text)
        self.assertEqual(self.alice.get("/api/dashboards").json()["dashboards"], [])

        created = self.create_dashboard()
        before = self.alice.get(f"/api/dashboards/{created['id']}").json()["dashboard"]
        for payload in (
            {"name": "Bad", "widgets": WIDGETS, "application_id": self.alice_other_app["id"]},
            {"name": "Bad", "widgets": [{"type": "unknown", "width": "full"}]},
            {"name": "Bad", "widgets": []},
            {"name": "Bad", "widgets": WIDGETS, "account_id": self.bob_auth["account"]["id"]},
        ):
            with self.subTest(payload=payload):
                response = self.alice.put(f"/api/dashboards/{created['id']}", json=payload, headers=self.alice_headers)
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.alice.get(f"/api/dashboards/{created['id']}").json()["dashboard"], before)

    def test_per_account_limit_does_not_block_another_account(self):
        for index in range(25):
            self.create_dashboard(name=f"Dashboard {index}")
        limit = self.alice.post(
            "/api/dashboards",
            json={"name": "Dashboard 26", "application_id": self.alice_app["id"], "widgets": WIDGETS},
            headers=self.alice_headers,
        )
        self.assertEqual(limit.status_code, 409, limit.text)
        self.assertEqual(len(self.alice.get("/api/dashboards").json()["dashboards"]), 25)
        self.create_dashboard(client=self.bob, headers=self.bob_headers, application_id=self.bob_app["id"])
        self.assertEqual(len(self.bob.get("/api/dashboards").json()["dashboards"]), 1)


class DashboardMigrationAcceptance(unittest.TestCase):
    def test_v2_database_migrates_without_erasing_existing_telemetry(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "before-builder.sqlite3"
            with closing(sqlite3.connect(path)) as db:
                db.executescript(SCHEMA + INDEXES)
                db.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
                db.executemany("INSERT INTO schema_migrations VALUES(?,?)", [(1, "2026-09-01"), (2, "2026-09-02")])
                db.execute("INSERT INTO accounts VALUES(?,?,?)", ("prior-account", "Prior account", "2026-09-01"))
                db.execute("INSERT INTO applications VALUES(?,?,?,?,?)", ("prior-app", "prior-account", "Prior app", "prior-app", "2026-09-01"))
                db.execute("INSERT INTO events VALUES(?,?,?,?,?)", ("prior-account", "prior-app", "prior-event", "{}", "2026-09-01"))
                db.commit()

            database = Database(path, auto_migrate=False)
            self.assertFalse(database.ready())
            database.migrate()
            database.migrate()
            self.assertTrue(database.ready())
            with database.connect() as db:
                versions = {row["version"] for row in db.execute("SELECT version FROM schema_migrations")}
                events = db.execute("SELECT account_id,application_id,event_id FROM events").fetchall()
                accounts = db.execute("SELECT id FROM accounts").fetchall()
                dashboard_columns = {row["name"] for row in db.execute("PRAGMA table_info(dashboards)")}
            self.assertEqual(versions, {1, 2, 3})
            self.assertEqual(tuple(events[0]), ("prior-account", "prior-app", "prior-event"))
            self.assertEqual(accounts[0]["id"], "prior-account")
            self.assertTrue({"id", "account_id", "application_id", "widgets"} <= dashboard_columns)


@unittest.skipUnless(POSTGRES_DSN and psycopg, "Set TRACEWORTH_TEST_POSTGRES_DSN for disposable PostgreSQL gate")
class PostgreSQLDashboardAcceptance(unittest.TestCase):
    def test_migrated_runtime_role_can_save_and_reopen_scoped_dashboard(self):
        database_name = "tw_builder_" + uuid4().hex
        runtime_role = "tw_builder_role_" + uuid4().hex
        runtime_password = "temporary-builder-" + uuid4().hex
        with psycopg.connect(POSTGRES_DSN, autocommit=True) as admin:
            admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        parsed = urlsplit(POSTGRES_DSN)
        owner_dsn = urlunsplit(parsed._replace(path="/" + database_name))
        try:
            database = Database(owner_dsn, auto_migrate=False)
            try:
                database.migrate()
                provision_runtime_role(database, runtime_role, runtime_password)
            finally:
                database.close()
            runtime_dsn = urlunsplit(parsed._replace(
                path="/" + database_name,
                netloc=f"{runtime_role}:{runtime_password}@{parsed.hostname}:{parsed.port}",
            ))
            app = create_app(database_url=runtime_dsn, allowed_origins=["https://dashboard.example.test"], cloud_mode=True)
            try:
                # Cloud registration is disabled; create a pilot owner explicitly.
                from traceworth.backend.management import bootstrap_owner
                owner = Database(owner_dsn, auto_migrate=False)
                try:
                    bootstrap_owner(owner, "pilot@example.test", "Pilot", PASSWORD)
                    with owner.connect() as db:
                        account_id = db.execute("SELECT id FROM accounts WHERE name=?", ("Pilot",)).fetchone()["id"]
                        application_id = str(uuid4())
                        db.execute(
                            "INSERT INTO applications VALUES(?,?,?,?,?)",
                            (application_id, account_id, "Pilot app", "pilot-app", "2026-09-27T00:00:00+00:00"),
                        )
                finally:
                    owner.close()
                with closing(TestClient(app, base_url="https://dashboard.example.test")) as client:
                    login = client.post(
                        "/api/auth/login", json={"email": "pilot@example.test", "password": PASSWORD},
                        headers={"Origin": "https://dashboard.example.test"},
                    )
                    self.assertEqual(login.status_code, 200, login.text)
                    csrf = login.json()["csrf_token"]
                    saved = client.post(
                        "/api/dashboards",
                        json={"name": "Runtime dashboard", "application_id": application_id, "widgets": WIDGETS},
                        headers={"Origin": "https://dashboard.example.test", "X-CSRF-Token": csrf},
                    )
                    self.assertEqual(saved.status_code, 201, saved.text)
                    dashboard_id = saved.json()["dashboard"]["id"]
                    self.assertEqual(client.get(f"/api/dashboards/{dashboard_id}").json()["dashboard"]["widgets"], WIDGETS)
                    removed = client.delete(
                        f"/api/dashboards/{dashboard_id}",
                        headers={"Origin": "https://dashboard.example.test", "X-CSRF-Token": csrf},
                    )
                    self.assertEqual(removed.status_code, 204, removed.text)
            finally:
                app.state.database.close()
        finally:
            with psycopg.connect(POSTGRES_DSN, autocommit=True) as admin:
                admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name)))
                admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(runtime_role)))


if __name__ == "__main__":
    unittest.main()
