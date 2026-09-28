"""Real-browser creator acceptance against an isolated Vite/FastAPI/SQLite stack."""

import json
from decimal import Decimal
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4

from test_mvp_acceptance import outcome, span, usage


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "apps" / "dashboard"
VITE = ROOT / "node_modules" / "vite" / "bin" / "vite.js"
CHROME = Path(os.environ.get("TRACEWORTH_TEST_CHROME", r"C:\Program Files\Google\Chrome\Application\chrome.exe"))
PASSWORD = "temporary-browser-password-123!"
DEMO_ASSISTANT = next(cohort for cohort in json.loads(
    (DASHBOARD / "src" / "demo-report.json").read_text(encoding="utf-8"))["report"]["cohorts"]
    if cohort["application_id"] == "assistant-service")


class DashboardBuilderBrowserAcceptance(unittest.TestCase):
    @staticmethod
    def free_port():
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    @staticmethod
    def await_server(server, url):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError(f"Isolated service exited during startup: {url}")
            try:
                with urlopen(url, timeout=1):
                    return
            except (OSError, URLError):
                time.sleep(0.2)
        raise RuntimeError(f"Isolated service did not become ready: {url}")

    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest("Playwright is not installed")
        if not VITE.exists() or not CHROME.exists():
            raise unittest.SkipTest("Vite dependencies or Chrome are unavailable")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.api_port = cls.free_port()
        cls.web_port = cls.free_port()
        cls.base_url = f"http://127.0.0.1:{cls.web_port}"
        cls.api_url = f"http://127.0.0.1:{cls.api_port}"
        cls.backend = subprocess.Popen(
            [sys.executable, "-m", "traceworth.backend", "--port", str(cls.api_port),
             "--database", str(Path(cls.temporary.name) / "browser.sqlite3"),
             "--allowed-origin", cls.base_url],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            cls.await_server(cls.backend, cls.api_url + "/api/health/ready")
            environment = os.environ.copy()
            environment["TRACEWORTH_DEV_API_TARGET"] = cls.api_url
            cls.server = subprocess.Popen(
                ["node", str(VITE), "--host", "127.0.0.1", "--port", str(cls.web_port), "--strictPort"],
                cwd=DASHBOARD, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            cls.await_server(cls.server, cls.base_url)
            cls.playwright = sync_playwright().start()
            cls.browser = cls.playwright.chromium.launch(executable_path=str(CHROME), headless=True)
        except Exception:
            if hasattr(cls, "server"):
                cls.server.terminate()
                cls.server.wait(timeout=5)
            cls.backend.terminate()
            cls.backend.wait(timeout=5)
            cls.temporary.cleanup()
            raise

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "browser"):
            cls.browser.close()
        if hasattr(cls, "playwright"):
            cls.playwright.stop()
        if hasattr(cls, "server"):
            cls.server.terminate()
            cls.server.wait(timeout=5)
        if hasattr(cls, "backend"):
            cls.backend.terminate()
            cls.backend.wait(timeout=5)
        if hasattr(cls, "temporary"):
            cls.temporary.cleanup()

    def setUp(self):
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.addCleanup(self.context.close)
        account_suffix = uuid4().hex
        registered = self.context.request.post(
            self.base_url + "/api/auth/register",
            data={"email": f"builder-{account_suffix}@example.test", "password": PASSWORD,
                  "account_name": "Browser builder"},
            headers={"Origin": self.base_url},
        )
        self.assertEqual(registered.status, 201, registered.text())
        self.csrf = registered.json()["csrf_token"]
        application = self.context.request.post(
            self.base_url + "/api/applications",
            data={"name": "Assistant service", "slug": "assistant-service"},
            headers={"Origin": self.base_url, "X-CSRF-Token": self.csrf},
        )
        self.assertEqual(application.status, 201, application.text())
        self.application_id = application.json()["application"]["id"]

    def open_creator(self):
        self.page.goto(self.base_url)
        self.page.get_by_role("heading", name="Application overview").wait_for()
        self.page.get_by_role("navigation").get_by_role("button", name="Dashboards").click()
        self.page.get_by_label("Application", exact=True).select_option(self.application_id)
        self.page.get_by_role("heading", name="Your dashboards").wait_for()

    def test_create_edit_reorder_reopen_and_delete_persisted_layout(self):
        self.open_creator()
        self.page.get_by_text("No dashboards yet").wait_for()
        self.page.get_by_role("button", name="New dashboard").click()
        self.page.get_by_label("Dashboard name").fill("Quality and cost")
        editor = self.page.get_by_role("region", name="Dashboard layout editor")
        editor.get_by_role("button", name="Move Workflow volume down").click()
        editor.get_by_role("button", name="Remove Chart · Recorded cost by run").click()
        editor.locator('.builder-gallery button:has(strong:text-is("Recorded cost"))').click()
        editor.get_by_label("Recorded cost width").select_option("full")
        self.page.get_by_role("button", name="Create dashboard", exact=True).click()
        self.page.get_by_text("Dashboard saved for this application.").wait_for()
        self.assertIn("Quality and cost", self.page.get_by_role("main").inner_text())

        saved = self.context.request.get(self.base_url + f"/api/dashboards?application_id={self.application_id}")
        self.assertEqual(saved.status, 200, saved.text())
        records = saved.json()["dashboards"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["name"], "Quality and cost")
        self.assertEqual([item["type"] for item in records[0]["widgets"]],
                         ["metric_acceptance", "metric_workflows", "chart", "chart", "cost_breakdown"])

        self.page.reload()
        self.page.get_by_role("navigation").get_by_role("button", name="Dashboards").click()
        self.page.get_by_label("Application", exact=True).select_option(self.application_id)
        self.page.get_by_role("button", name="Quality and cost").click()
        self.page.get_by_role("heading", name="Quality and cost").wait_for()
        self.page.get_by_role("button", name="Edit layout").click()
        self.page.get_by_label("Dashboard name").fill("Operations review")
        self.page.get_by_role("button", name="Save changes").click()
        self.page.get_by_role("heading", name="Operations review").wait_for()
        self.assertEqual(self.context.request.get(self.base_url + f"/api/dashboards/{records[0]['id']}").json()["dashboard"]["name"], "Operations review")
        self.page.get_by_role("button", name="Delete", exact=True).click()
        self.page.get_by_role("button", name="Confirm delete").click()
        self.page.get_by_text("Dashboard deleted.").wait_for()
        self.assertEqual(self.context.request.get(self.base_url + f"/api/dashboards/{records[0]['id']}").status, 404)

    def test_mobile_keyboard_layout_and_empty_report_are_understandable(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.open_creator()
        self.page.get_by_role("button", name="New dashboard").focus()
        self.page.keyboard.press("Enter")
        editor = self.page.get_by_role("region", name="Dashboard layout editor")
        editor.get_by_role("button", name="Move Workflow volume down").focus()
        self.page.keyboard.press("Enter")
        self.assertIn("No workflows in this report window", self.page.get_by_label("Dashboard preview").inner_text())
        self.assertLessEqual(
            self.page.evaluate("document.documentElement.scrollWidth"),
            self.page.evaluate("document.documentElement.clientWidth") + 1,
        )

    def test_cohort_picker_changes_widgets_without_combining_application_cohorts(self):
        key = self.context.request.post(
            self.base_url + f"/api/applications/{self.application_id}/keys",
            data={"name": "Cohort browser fixture"},
            headers={"Origin": self.base_url, "X-CSRF-Token": self.csrf},
        )
        self.assertEqual(key.status, 201, key.text())
        token = key.json()["token"]
        events = []
        for environment, configuration, count in (
            ("production", "stable", 1), ("stage", "candidate", 2),
        ):
            for index in range(count):
                records = span(workflow=f"{environment}-{index}-{uuid4().hex}")
                for record in records:
                    record.update(application_id="assistant-service", environment=environment,
                                  configuration_id=configuration)
                events.extend(records)
        ingested = self.context.request.post(
            self.base_url + "/api/events", data={"events": events},
            headers={"Authorization": "Bearer " + token},
        )
        self.assertEqual(ingested.status, 200, ingested.text())
        self.assertEqual(ingested.json()["accepted"], 6)

        self.open_creator()
        picker = self.page.get_by_label("Environment / configuration")
        picker.select_option(label="production · stable")
        self.page.get_by_role("button", name="New dashboard").click()
        volume = self.page.get_by_label("Dashboard preview").locator(".builder-widget").filter(has_text="Workflow volume")
        self.assertEqual(volume.locator(".builder-stat strong").inner_text(), "1")
        scope = self.page.locator(".builder-scope")
        self.assertIn("production · stable", scope.inner_text())
        self.assertIn("only the selected environment and configuration", scope.inner_text())
        self.assertIn("not all activity for this application", self.page.locator(".builder-cohort-picker").inner_text())

        picker.select_option(label="stage · candidate")
        self.assertEqual(volume.locator(".builder-stat strong").inner_text(), "2")
        self.assertIn("stage · candidate", scope.inner_text())
        self.assertNotIn("production · stable", scope.inner_text())
        self.page.get_by_label("Dashboard name").fill("Cohort review")
        self.page.get_by_role("button", name="Create dashboard", exact=True).click()
        self.page.get_by_text("Dashboard saved for this application.").wait_for()
        saved_volume = self.page.get_by_label("Dashboard widgets").locator(".builder-widget").filter(has_text="Workflow volume")
        self.assertEqual(saved_volume.locator(".builder-stat strong").inner_text(), "2")
        picker.select_option(label="production · stable")
        self.assertEqual(saved_volume.locator(".builder-stat strong").inner_text(), "1")
        self.assertIn("production · stable", scope.inner_text())

    def test_overview_charts_follow_application_and_cohort_with_exact_evidence(self):
        second = self.context.request.post(
            self.base_url + "/api/applications",
            data={"name": "Document indexer", "slug": "document-indexer"},
            headers={"Origin": self.base_url, "X-CSRF-Token": self.csrf},
        )
        self.assertEqual(second.status, 201, second.text())
        second_id = second.json()["application"]["id"]

        def ingest(application_id, slug, rows):
            key = self.context.request.post(
                self.base_url + f"/api/applications/{application_id}/keys",
                data={"name": "Overview browser fixture"},
                headers={"Origin": self.base_url, "X-CSRF-Token": self.csrf},
            )
            self.assertEqual(key.status, 201, key.text())
            events = []
            for environment, configuration, amount, accepted, status in rows:
                workflow = f"{slug}-{environment}-{uuid4().hex}"
                root = span(workflow=workflow, status=status)
                records = root + [usage(root[0]["step_id"], amount, workflow=workflow)]
                if accepted is not None:
                    records.append(outcome(accepted, workflow=workflow))
                for record in records:
                    record.update(application_id=slug, environment=environment,
                                  configuration_id=configuration)
                events.extend(records)
            sent = self.context.request.post(
                self.base_url + "/api/events", data={"events": events},
                headers={"Authorization": "Bearer " + key.json()["token"]},
            )
            self.assertEqual(sent.status, 200, sent.text())
            self.assertEqual(sent.json()["accepted"], len(events))

        ingest(self.application_id, "assistant-service", [
            ("production", "stable", "0.02", True, "completed"),
            ("stage", "candidate", "0.03", False, "failed"),
            ("stage", "candidate", None, None, "completed"),
        ])
        ingest(second_id, "document-indexer", [
            ("production", "stable", "0.07", True, "completed"),
        ])

        self.page.goto(self.base_url)
        self.page.get_by_role("heading", name="Application overview").wait_for()
        self.page.get_by_label("Application", exact=True).select_option(self.application_id)
        cohort_picker = self.page.get_by_label("Environment / configuration")
        cohort_picker.select_option(label="assistant-service · production · stable")
        overview = self.page.get_by_role("region", name="What does this cohort show?")
        summary = overview.get_by_label("Selected cohort evidence")
        self.assertIn("1\nrecorded workflows", summary.inner_text())
        self.assertIn("1 / 1\nwith an explicit outcome", summary.inner_text())
        self.assertIn("1 / 1\nusage events with a price", summary.inner_text())
        self.assertIn("0 usage events with unknown cost", summary.inner_text())
        self.assertIn("0.02 USD", overview.locator(".overview-chart-card").filter(
            has_text="Recorded cost by currency and basis").inner_text())
        self.assertEqual(overview.get_by_role("article", name="Highest comparable recorded cost").locator("ol button").count(), 1)
        self.assertNotIn("0.03 USD", overview.inner_text())
        self.assertIn("Recorded telemetry", self.page.locator(".source-panel").inner_text())
        self.assertIn("Received-time report", overview.inner_text())

        cohort_picker.select_option(label="assistant-service · stage · candidate")
        overview = self.page.get_by_role("region", name="What does this cohort show?")
        summary = overview.get_by_label("Selected cohort evidence")
        self.assertIn("2\nrecorded workflows", summary.inner_text())
        self.assertIn("1 / 2\nwith an explicit outcome", summary.inner_text())
        self.assertIn("1 / 2\nusage events with a price", summary.inner_text())
        self.assertIn("1 usage event with unknown cost", summary.inner_text())
        cost_rank = overview.get_by_role("article", name="Highest comparable recorded cost")
        self.assertEqual(cost_rank.locator("ol button").count(), 1)
        self.assertIn("0.03 USD", cost_rank.inner_text())
        self.assertIn("1 of 2 selected runs excluded", cost_rank.inner_text())
        self.assertEqual(overview.get_by_role("article", name="Longest recorded duration").locator("ol button").count(), 2)
        self.assertEqual(overview.get_by_role("article", name="Most usage events").locator("ol button").count(), 2)
        self.assertIn("1 of 2 recorded usage events include a price", overview.inner_text())
        self.assertNotIn("0.02 USD", overview.inner_text())
        self.assertIn("partial", overview.inner_text().lower())
        outcomes = overview.get_by_role("group", name="Workflow chart view")
        outcomes.get_by_role("button", name="Status").click()
        self.assertEqual(outcomes.get_by_role("button", name="Status").get_attribute("aria-pressed"), "true")
        status_chart = overview.get_by_role("group", name="Workflow status · Vertical bars")
        self.assertEqual(status_chart.get_by_role("button").count(), 2)
        overview.get_by_text("View chart data").first.click()
        self.assertEqual(overview.get_by_role("region", name="Workflow status data table").get_by_role("row").count(), 3)
        cost_rank.locator("ol button").first.click()
        dialog = self.page.get_by_role("dialog", name="Workflow details")
        self.assertIn("0.03 USD", dialog.inner_text())
        dialog.get_by_role("button", name="Close").click()
        overview.get_by_role("button", name="Build a dashboard", exact=False).click()
        self.page.get_by_role("heading", name="Your dashboards").wait_for()
        self.page.get_by_role("navigation").get_by_role("button", name="Overview").click()

        self.page.get_by_label("Application", exact=True).select_option(second_id)
        self.page.get_by_label("Environment / configuration").select_option(
            label="document-indexer · production · stable")
        overview = self.page.get_by_role("region", name="What does this cohort show?")
        self.assertIn("0.07 USD", overview.get_by_role("article", name="Highest comparable recorded cost").inner_text())
        self.assertNotIn("0.03 USD", overview.inner_text())
        self.assertNotIn("assistant-service", self.page.locator(".source-panel").inner_text())
        self.page.set_viewport_size({"width": 390, "height": 844})
        status = overview.get_by_role("group", name="Workflow chart view").get_by_role("button", name="Status")
        status.focus()
        self.page.keyboard.press("Enter")
        self.assertEqual(status.get_attribute("aria-pressed"), "true")
        run = overview.get_by_role("article", name="Highest comparable recorded cost").locator("ol button").first
        run.focus()
        self.page.keyboard.press("Enter")
        self.page.get_by_role("dialog", name="Workflow details").get_by_role("button", name="Close").click()
        self.assertIn("Swipe table sideways for recorded cost and Inspect",
                      self.page.locator(".workflow-table-hint").inner_text())
        table_region = self.page.get_by_role(
            "region", name="Workflows table, scroll horizontally for recorded cost and details")
        self.assertEqual(table_region.get_attribute("tabindex"), "0")
        table_region.focus()
        self.assertTrue(table_region.evaluate("element => element === document.activeElement"))
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"),
                             self.page.evaluate("document.documentElement.clientWidth") + 1)

    def test_cost_ranking_uses_exact_decimals_all_rows_and_comparable_group(self):
        key = self.context.request.post(
            self.base_url + f"/api/applications/{self.application_id}/keys",
            data={"name": "Precise ranking fixture"},
            headers={"Origin": self.base_url, "X-CSRF-Token": self.csrf},
        )
        self.assertEqual(key.status, 201, key.text())
        amounts = [
            ("rank-a-low", "0.3000000000000000000000000001", "USD"),
            ("rank-b-high", "0.3000000000000000000000000002", "USD"),
            ("rank-z-high", "0.3000000000000000000000000002", "USD"),
            *[(f"rank-{index:02d}", f"0.0{index}", "USD") for index in range(1, 10)],
            ("rank-tiny", "0." + "0" * 4999 + "1", "USD"),
            ("rank-other-currency", "10", "ZAR"),
            ("rank-unknown", None, "USD"),
        ]
        events = []
        for index, (workflow, amount, currency) in enumerate(amounts):
            root = span(workflow=workflow, duration=100 + index)
            records = root + [usage(root[0]["step_id"], amount, workflow=workflow, currency=currency)]
            for record in records:
                record.update(application_id="assistant-service", environment="ranking",
                              configuration_id="precise")
            events.extend(records)
        sent = self.context.request.post(
            self.base_url + "/api/events", data={"events": events},
            headers={"Authorization": "Bearer " + key.json()["token"]},
        )
        self.assertEqual(sent.status, 200, sent.text())
        self.assertEqual(sent.json()["accepted"], len(events))
        report = self.context.request.get(
            self.base_url + f"/api/metrics?application_id={self.application_id}")
        self.assertEqual(report.status, 200, report.text())
        cohort = next(row for row in report.json()["report"]["cohorts"]
                      if row["environment"] == "ranking")
        self.assertEqual(len(cohort["workflows"]), len(amounts))
        self.assertIn(("ZAR", "estimated"),
                      [(row["currency"], row["cost_basis"]) for row in cohort["costs"]])
        expected = sorted(
            ((row["workflow_id"], sum((Decimal(cost["amount"]) for cost in row["costs"]
                                      if cost["currency"] == "USD" and cost["cost_basis"] == "estimated"), Decimal(0)))
             for row in cohort["workflows"] if any(cost["currency"] == "USD" for cost in row["costs"])),
            key=lambda row: (-row[1], row[0]),
        )
        self.assertEqual(len(expected), 13)
        self.assertEqual([identifier for identifier, _ in expected[:3]],
                         ["rank-b-high", "rank-z-high", "rank-a-low"])

        self.page.goto(self.base_url)
        self.page.get_by_label("Application", exact=True).select_option(self.application_id)
        self.page.get_by_label("Environment / configuration").select_option(
            label="assistant-service · ranking · precise")
        overview = self.page.get_by_role("region", name="What does this cohort show?")
        cost_rank = overview.get_by_role("article", name="Highest comparable recorded cost")
        self.assertIn("Top 10 of 13 eligible", cost_rank.inner_text())
        self.assertEqual(cost_rank.locator("ol button").evaluate_all(
            "rows => rows.map(row => row.dataset.workflowId)"),
            [identifier for identifier, _ in expected[:10]])
        self.assertIn("2 of 15 selected runs excluded", cost_rank.inner_text())
        self.assertIn("Only USD · estimated priced amounts", cost_rank.inner_text())
        self.assertEqual(overview.get_by_role("article", name="Longest recorded duration").locator("ol button").count(), 10)
        self.assertEqual(overview.get_by_role("article", name="Most usage events").locator("ol button").count(), 10)
        self.assertIn("0.3000000000000000000000000002 USD", cost_rank.inner_text())
        group_select = overview.get_by_label("Comparable cost group")
        self.assertIn('["ZAR","estimated"]', group_select.locator("option").evaluate_all(
            "options => options.map(option => option.value)"))
        group_select.select_option('["ZAR","estimated"]')
        cost_rank = overview.get_by_role("article", name="Highest comparable recorded cost")
        self.assertEqual(cost_rank.locator("ol button").evaluate_all(
            "rows => rows.map(row => row.dataset.workflowId)"), ["rank-other-currency"])
        self.assertIn("14 of 15 selected runs excluded", cost_rank.inner_text())

    def test_failed_save_preserves_layout_and_allows_retry(self):
        self.open_creator()
        self.page.get_by_role("button", name="New dashboard").click()
        name = self.page.get_by_label("Dashboard name")
        name.fill("Retry this layout")
        editor = self.page.get_by_role("region", name="Dashboard layout editor")
        editor.get_by_role("button", name="Remove Chart · Recorded cost by run").click()
        self.page.route("**/api/dashboards", lambda route: route.abort("failed"), times=1)
        self.page.get_by_role("button", name="Create dashboard", exact=True).click()
        alert = self.page.get_by_role("alert")
        self.assertIn("Could not reach the API", alert.inner_text())
        self.assertIn("Your name and layout are still here", alert.inner_text())
        self.assertEqual(name.input_value(), "Retry this layout")
        self.assertEqual(editor.locator(".builder-widget-row").count(), 4)
        self.page.get_by_role("button", name="Create dashboard", exact=True).click()
        self.page.get_by_text("Dashboard saved for this application.").wait_for()
        saved = self.context.request.get(self.base_url + f"/api/dashboards?application_id={self.application_id}")
        self.assertEqual(saved.status, 200, saved.text())
        self.assertEqual(saved.json()["dashboards"][0]["name"], "Retry this layout")
        self.assertEqual(len(saved.json()["dashboards"][0]["widgets"]), 4)

    def test_public_demo_composer_is_local_and_resets_on_reload(self):
        requests = []
        self.page.route("**/api/**", lambda route: (requests.append((route.request.method, route.request.url)), route.abort()))
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.goto(self.base_url + "/#demo")
        self.page.get_by_role("navigation", name="Demo navigation").get_by_role("button", name="Build a view").click()
        self.page.get_by_role("heading", name="Shape the sample into your view").wait_for()
        self.assertIn("Synthetic demo — no live telemetry", self.page.get_by_role("main").inner_text())
        editor = self.page.get_by_role("region", name="Dashboard layout editor")
        editor.get_by_role("button", name="Remove Workflow volume").focus()
        self.page.keyboard.press("Enter")
        self.assertEqual(self.page.get_by_label("Dashboard preview").locator(".builder-widget").count(), 4)
        editor.locator('.builder-gallery button:has(strong:text-is("Recorded cost"))').click()
        self.assertEqual(self.page.get_by_label("Dashboard preview").locator(".builder-widget").count(), 5)
        self.assertIn("recorded", self.page.get_by_label("Dashboard preview").inner_text().lower())
        self.page.get_by_label("Sample application").select_option("document-indexer")
        self.assertIn("Document indexer", self.page.get_by_role("main").inner_text())
        self.page.get_by_role("button", name="Reset layout").click()
        self.assertEqual(self.page.get_by_label("Dashboard preview").locator(".builder-widget").count(), 5)
        self.assertLessEqual(
            self.page.evaluate("document.documentElement.scrollWidth"),
            self.page.evaluate("document.documentElement.clientWidth") + 1,
        )
        self.page.reload()
        self.page.get_by_role("navigation", name="Demo navigation").get_by_role("button", name="Build a view").click()
        self.assertEqual(self.page.get_by_label("Dashboard preview").locator(".builder-widget").count(), 5)
        self.assertEqual(requests, [], "Public demo customization must not use the account API")

    def test_demo_chart_controls_render_distinct_plots_on_phone_without_api_calls(self):
        requests = []
        self.page.route("**/api/**", lambda route: (requests.append(route.request.url), route.abort()))
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.goto(self.base_url + "/#demo")
        self.page.get_by_role("button", name="Build a sample view").click()
        editor = self.page.get_by_role("region", name="Dashboard layout editor")
        preview = self.page.get_by_label("Dashboard preview")
        self.assertEqual(preview.locator(".chart-card").count(), 3)
        outcome_card = preview.locator(".chart-card").nth(0)
        outcome_card.get_by_text("View chart data").click()
        outcome_table = outcome_card.locator(".chart-data-table table").inner_text()
        for label in ("Accepted", "Not accepted", "Not recorded"):
            self.assertIn(label, outcome_table)
        cost_card = preview.locator(".chart-card").nth(2)
        cost_card.get_by_text("View chart data").click()
        cost_table = cost_card.locator(".chart-data-table table").inner_text()
        for workflow in DEMO_ASSISTANT["workflows"][:2]:
            self.assertIn(f"{workflow['costs'][0]['amount']} USD · estimated", cost_table)
        self.assertIn("unknown cost", cost_table)
        self.assertIn("unknown and other costs are excluded", cost_card.inner_text())
        editor.get_by_label("Chart 3 dataset").select_option("workflow_status")
        preview.get_by_role("group", name="Workflow status · Pie").wait_for()
        editor.get_by_label("Chart 3 visualization").select_option("horizontal_bar")
        status_chart = preview.get_by_role("group", name="Workflow status · Horizontal bars")
        point = status_chart.get_by_role("button", name=re.compile(
            f"completed: {DEMO_ASSISTANT['summary']['completed_workflows']}"))
        point.focus()
        self.page.keyboard.press("Enter")
        self.assertEqual(point.get_attribute("aria-pressed"), "true")
        status_chart.locator("xpath=../..").get_by_text("View chart data").click()
        self.assertIn("completed", preview.locator(".chart-data-table table").first.inner_text())
        editor.get_by_label("Chart 3 dataset").select_option("usage_by_run")
        usage_chart = preview.locator(".chart-card").nth(0)
        usage_chart.get_by_text("View chart data").click()
        usage_table = usage_chart.locator(".chart-data-table table").inner_text()
        self.assertIn("Run 1", usage_table)
        self.assertIn("Run 2", usage_table)
        self.assertIn("Run 3", usage_table)
        self.assertIn("This is not a token total", usage_chart.inner_text())

        editor.locator('.builder-gallery button:has(strong:text-is("Add chart"))').click()
        editor.get_by_label("Chart 6 dataset").select_option("duration_by_run")
        editor.get_by_label("Chart 6 visualization").select_option("trend")
        editor.get_by_label("Chart 6 width").select_option("full")
        trend = preview.get_by_role("group", name="Duration by run · Trend")
        self.assertEqual(preview.locator(".chart-card").count(), 4)
        run = trend.get_by_role("button").first
        run.focus()
        self.page.keyboard.press("Enter")
        self.assertEqual(run.get_attribute("aria-pressed"), "true")
        self.assertIn("caller-supplied", preview.inner_text())
        duration_card = preview.locator(".chart-card").last
        duration_card.get_by_text("View chart data").click()
        duration_table = duration_card.locator(".chart-data-table table").inner_text()
        for workflow in DEMO_ASSISTANT["workflows"][:2]:
            self.assertIn(f"{workflow['duration_ms']:.1f} ms", duration_table)
        editor.get_by_label("Chart 6 dataset").select_option("workflows_over_time")
        daily_card = preview.locator(".chart-card").last
        daily_card.get_by_text("View chart data").click()
        daily_table = daily_card.locator(".chart-data-table table").inner_text()
        self.assertIn("2026-02-01 UTC", daily_table)
        self.assertEqual(daily_card.locator(".chart-data-table tbody tr").count(), 18)
        self.assertIn("Missing days are not zero-activity days", daily_card.inner_text())
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"),
                             self.page.evaluate("document.documentElement.clientWidth") + 1)
        self.assertEqual(requests, [])

    def test_signed_in_chart_choices_and_ids_survive_save_and_reload(self):
        self.open_creator()
        self.page.get_by_role("button", name="New dashboard").click()
        editor = self.page.get_by_role("region", name="Dashboard layout editor")
        editor.get_by_label("Chart 3 dataset").select_option("usage_by_run")
        self.assertEqual(editor.get_by_label("Chart 3 visualization").input_value(), "horizontal_bar",
                         "Changing away from a pie-only dataset must select a compatible visual")
        editor.get_by_label("Chart 3 visualization").select_option("trend")
        editor.get_by_label("Chart 3 width").select_option("full")
        editor.locator('.builder-gallery button:has(strong:text-is("Add chart"))').click()
        editor.get_by_label("Chart 6 dataset").select_option("workflows_over_time")
        editor.get_by_label("Chart 6 visualization").select_option("trend")
        self.page.get_by_label("Dashboard name").fill("Configured charts")
        self.page.get_by_role("button", name="Create dashboard", exact=True).click()
        self.page.get_by_text("Dashboard saved for this application.").wait_for()
        response = self.context.request.get(self.base_url + f"/api/dashboards?application_id={self.application_id}")
        self.assertEqual(response.status, 200, response.text())
        saved = response.json()["dashboards"][0]
        charts = [widget for widget in saved["widgets"] if widget["type"] == "chart"]
        self.assertEqual(len(charts), 4)
        self.assertEqual(len({item["id"] for item in charts}), 4)
        self.assertEqual((charts[0]["dataset"], charts[0]["visualization"], charts[0]["width"]),
                         ("usage_by_run", "trend", "full"))
        self.assertEqual((charts[-1]["dataset"], charts[-1]["visualization"]),
                         ("workflows_over_time", "trend"))
        self.page.reload()
        self.page.get_by_role("navigation").get_by_role("button", name="Dashboards").click()
        self.page.get_by_label("Application", exact=True).select_option(self.application_id)
        self.page.get_by_role("button", name="Configured charts").click()
        self.page.get_by_role("button", name="Edit layout").click()
        editor = self.page.get_by_role("region", name="Dashboard layout editor")
        self.assertEqual(editor.get_by_label("Chart 3 dataset").input_value(), "usage_by_run")
        self.assertEqual(editor.get_by_label("Chart 3 visualization").input_value(), "trend")
        self.assertEqual(editor.get_by_label("Chart 6 dataset").input_value(), "workflows_over_time")


if __name__ == "__main__":
    unittest.main()
