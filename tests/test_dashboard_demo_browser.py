"""Independent browser acceptance for the dashboard's public sample report.

The test uses an isolated Vite port and intercepts API traffic, so it never
creates accounts, ingestion keys, or telemetry in a developer's database.
"""

import os
from pathlib import Path
import re
import socket
import subprocess
import time
import unittest
from urllib.error import URLError
from urllib.request import urlopen
import json
from decimal import Decimal
import math


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "apps" / "dashboard"
WEBSITE = ROOT / "apps" / "website"
VITE = ROOT / "node_modules" / "vite" / "bin" / "vite.js"
CHROME = Path(os.environ.get("TRACEWORTH_TEST_CHROME", r"C:\Program Files\Google\Chrome\Application\chrome.exe"))
SAMPLE = json.loads((DASHBOARD / "src" / "demo-report.json").read_text(encoding="utf-8"))


def sample_cohort(application_id):
    return next(cohort for cohort in SAMPLE["report"]["cohorts"]
                if cohort["application_id"] == application_id)


def ranked_ids(workflows, metric, currency="USD", basis="estimated"):
    rows = []
    for workflow in workflows:
        if metric == "cost":
            prices = [Decimal(cost["amount"]) for cost in workflow["costs"]
                      if cost["currency"] == currency and cost["cost_basis"] == basis]
            if not prices:
                continue
            value = sum(prices, Decimal(0))
        else:
            value = workflow["duration_ms"] if metric == "duration" else workflow["usage_events"]
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                continue
        rows.append((workflow["workflow_id"], value))
    return [workflow_id for workflow_id, _ in sorted(rows, key=lambda row: (-row[1], row[0]))]


class DashboardDemoBrowserAcceptance(unittest.TestCase):
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
                raise RuntimeError("Isolated Vite server exited during startup")
            try:
                with urlopen(url, timeout=1):
                    return
            except (OSError, URLError):
                time.sleep(0.2)
        raise RuntimeError("Isolated Vite server did not become ready")

    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest("Playwright is not installed")
        if not VITE.exists() or not CHROME.exists():
            raise unittest.SkipTest("Vite dependencies or Chrome are unavailable")

        port = cls.free_port()
        cls.base_url = f"http://127.0.0.1:{port}"
        # Reserve a port without listening so Vite's real proxy gets ECONNREFUSED.
        cls.unavailable_api_socket = socket.socket()
        cls.unavailable_api_socket.bind(("127.0.0.1", 0))
        unavailable_api_port = cls.unavailable_api_socket.getsockname()[1]
        dashboard_environment = os.environ.copy()
        dashboard_environment["TRACEWORTH_DEV_API_TARGET"] = f"http://127.0.0.1:{unavailable_api_port}"
        cls.server = subprocess.Popen(
            ["node", str(VITE), "--host", "127.0.0.1", "--port", str(port), "--strictPort"],
            cwd=DASHBOARD,
            env=dashboard_environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            cls.await_server(cls.server, cls.base_url)
            cls.website_url = f"http://127.0.0.1:{cls.free_port()}"
            environment = os.environ.copy()
            environment["VITE_DASHBOARD_URL"] = cls.base_url
            cls.website_server = subprocess.Popen(
                ["node", str(VITE), "--host", "127.0.0.1", "--port", cls.website_url.rsplit(":", 1)[1], "--strictPort"],
                cwd=WEBSITE,
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            cls.await_server(cls.website_server, cls.website_url)
            cls.playwright = sync_playwright().start()
            cls.browser = cls.playwright.chromium.launch(executable_path=str(CHROME), headless=True)
        except Exception:
            if hasattr(cls, "website_server"):
                cls.website_server.terminate()
                cls.website_server.wait(timeout=5)
            cls.server.terminate()
            cls.server.wait(timeout=5)
            cls.unavailable_api_socket.close()
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
        if hasattr(cls, "unavailable_api_socket"):
            cls.unavailable_api_socket.close()
        if hasattr(cls, "website_server"):
            cls.website_server.terminate()
            cls.website_server.wait(timeout=5)

    def setUp(self):
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.requests = []
        self.api_available = False

        def api_unavailable(route):
            self.requests.append((route.request.method, route.request.url))
            if self.api_available:
                if route.request.url.endswith("/api/config"):
                    route.fulfill(status=200, content_type="application/json", body=json.dumps({
                        "mode": "local", "registration_enabled": True,
                        "demo_enabled": False, "metrics_window_days": 30, "metrics_max_events": 1000,
                    }))
                    return
                if route.request.url.endswith("/api/auth/me"):
                    route.fulfill(status=401, content_type="application/json", body='{"detail":"Sign in required"}')
                    return
                if route.request.url.endswith("/api/auth/login"):
                    route.fulfill(status=200, content_type="application/json", body=json.dumps({
                        "user": {"email": "browser@example.test"},
                        "account": {"id": "example-account", "name": "Browser QA"},
                        "csrf_token": "test-csrf",
                    }))
                    return
                if route.request.url.endswith("/api/applications"):
                    route.fulfill(status=200, content_type="application/json", body='{"applications":[]}')
                    return
                if route.request.url.endswith("/api/metrics"):
                    route.fulfill(status=200, content_type="application/json", body=json.dumps({
                        "report": {"cohorts": [], "input": {"valid_events": 0}, "assumptions": []},
                        "loaded_at": "2026-09-27T00:00:00Z",
                    }))
                    return
            route.fulfill(status=503, content_type="application/json", body='{"detail":"API unavailable"}')

        self.page.route("**/api/**", api_unavailable)

    def tearDown(self):
        self.context.close()

    def test_public_demo_has_sample_metrics_without_api_calls(self):
        self.page.goto(self.base_url + "/#demo")
        self.page.get_by_text(re.compile("synthetic", re.I)).first.wait_for()
        assistant = sample_cohort("assistant-service")
        content = self.page.locator("main").inner_text().lower()
        self.assertIn("unknown cost", content)
        self.assertIn("workflow", content)
        self.assertIn("not verified improvement recommendations", content)
        self.assertIn(f"{assistant['costs'][0]['amount']} usd", content)
        self.assertIn("partial", content)
        self.assertEqual(self.page.locator(".panel:has(h2:text-is('Sample workflows')) table tbody tr").count(),
                         assistant["summary"]["workflows"])
        self.page.get_by_role("button", name=re.compile("Inspect answer_question", re.I)).first.click()
        dialog = self.page.get_by_role("dialog")
        self.assertIn("synthetic", dialog.inner_text().lower())
        self.assertIn("recorded usage", dialog.inner_text().lower())
        dialog.get_by_role("button", name="Close").click()
        self.page.get_by_label("Sample application").select_option("document-indexer")
        indexer = sample_cohort("document-indexer")
        self.assertEqual(self.page.locator(".panel:has(h2:text-is('Sample workflows')) table tbody tr").count(),
                         indexer["summary"]["workflows"])
        self.assertIn("index_document", self.page.get_by_role("region", name="Sample workflows table, scroll horizontally for more columns").inner_text())
        self.assertIn(f"{indexer['costs'][0]['amount']} usd", self.page.locator("main").inner_text().lower())
        self.assertEqual(self.requests, [], "Public demo should be local and read-only")

    def test_demo_can_be_opened_when_api_is_unavailable_and_exited(self):
        self.page.goto(self.base_url + "/")
        demo_entry = self.page.locator("a, button").filter(has_text=re.compile("demo", re.I)).first
        demo_entry.click()
        self.page.get_by_text(re.compile("synthetic", re.I)).first.wait_for()
        self.assertEqual(self.page.evaluate("location.hash"), "#demo")
        self.assertFalse(any(method != "GET" for method, _ in self.requests))
        exit_demo = self.page.locator("a, button").filter(has_text=re.compile("exit|sign in", re.I)).first
        exit_demo.click()
        self.assertNotEqual(self.page.evaluate("location.hash"), "#demo")
        self.page.get_by_text(re.compile("API unavailable|Retry connection", re.I)).first.wait_for()

    def test_demo_builder_needs_no_api_and_workspace_exit_explains_offline_api(self):
        self.page.goto(self.base_url + "/#demo")
        self.page.get_by_role("button", name=re.compile("Build a sample view", re.I)).click()
        self.page.get_by_role("heading", name="Shape the sample into your view").wait_for()
        self.assertEqual(self.requests, [], "Entering the demo builder must not call the account API")
        failed_requests = []
        self.page.route(
            "**/api/config",
            lambda route: (failed_requests.append((route.request.method, route.request.url)), route.abort("failed")),
            times=1,
        )
        self.page.get_by_role("button", name=re.compile("sign in.*save|save.*sign in", re.I)).click()
        self.assertEqual(self.page.evaluate("location.hash"), "#login")
        alert = self.page.get_by_role("alert")
        self.assertIn("The local Python API is unavailable on port 18766.", alert.inner_text())
        self.assertNotIn("Failed to fetch", alert.inner_text())
        self.page.get_by_text(re.compile(r"traceworth\.backend.*18766", re.I)).first.wait_for()
        self.page.get_by_role("button", name=re.compile("Retry connection", re.I)).wait_for()
        self.assertEqual(failed_requests, [("GET", self.base_url + "/api/config")])
        self.assertEqual(self.requests, [])
        self.page.get_by_role("button", name=re.compile("Explore synthetic demo", re.I)).click()
        self.page.get_by_role("heading", name="Explore a sample assessment").wait_for()
        self.assertEqual(self.page.evaluate("location.hash"), "#demo")
        self.assertFalse(any(method != "GET" for method, _ in self.requests))

    def test_demo_builder_sign_in_to_save_uses_existing_login_when_api_is_online(self):
        self.api_available = True
        self.page.goto(self.base_url + "/#demo")
        self.page.get_by_role("button", name=re.compile("Build a sample view", re.I)).click()
        self.assertEqual(self.requests, [])
        self.page.get_by_role("button", name=re.compile("sign in.*save|save.*sign in", re.I)).click()
        self.assertEqual(self.page.evaluate("location.hash"), "#login")
        self.page.get_by_label("Email").wait_for()
        self.page.get_by_label("Password").wait_for()
        self.assertFalse(any(method != "GET" for method, _ in self.requests))
        self.page.get_by_label("Email").fill("browser@example.test")
        self.page.get_by_label("Password").fill("example-password")
        self.page.get_by_role("button", name=re.compile("Sign in", re.I)).last.click()
        self.page.get_by_role("heading", name="Application overview").wait_for()
        self.assertEqual(sum(method == "POST" and url.endswith("/api/auth/login") for method, url in self.requests), 1)

    def test_real_vite_proxy_502_gives_local_api_recovery_not_raw_error(self):
        self.page.unroute("**/api/**")
        api_responses = []
        self.page.on(
            "response",
            lambda response: api_responses.append((response.status, response.url))
            if "/api/" in response.url else None,
        )
        self.page.goto(self.base_url + "/#demo")
        self.page.get_by_role("button", name=re.compile("Build a sample view", re.I)).click()
        self.assertEqual(api_responses, [], "The demo builder must work before contacting an API")
        self.page.get_by_role("button", name=re.compile("sign in.*save|save.*sign in", re.I)).click()
        alert = self.page.get_by_role("alert")
        self.assertIn("The local Python API is unavailable on port 18766.", alert.inner_text())
        self.assertNotIn("Failed to fetch", alert.inner_text())
        self.assertNotIn("Unable to reach the API", alert.inner_text())
        self.page.get_by_text(re.compile(r"traceworth\.backend.*18766", re.I)).first.wait_for()
        self.assertEqual(api_responses, [(502, self.base_url + "/api/config")])
        self.page.get_by_role("button", name="Explore synthetic demo").click()
        self.page.get_by_role("heading", name="Explore a sample assessment").wait_for()

    def test_demo_exit_returns_to_existing_sign_in(self):
        self.api_available = True
        self.page.goto(self.base_url + "/")
        self.page.get_by_label("Email").wait_for()
        self.page.get_by_label("Password").wait_for()
        self.page.locator("a, button").filter(has_text=re.compile("demo", re.I)).first.click()
        self.page.get_by_text(re.compile("synthetic", re.I)).first.wait_for()
        self.page.locator("a, button").filter(has_text=re.compile("exit|sign in", re.I)).first.click()
        self.page.get_by_label("Email").wait_for()
        self.page.get_by_label("Password").wait_for()
        self.assertFalse(any(method != "GET" for method, _ in self.requests))
        self.page.get_by_label("Email").fill("browser@example.test")
        self.page.get_by_label("Password").fill("example-password")
        self.page.get_by_role("button", name=re.compile("Sign in", re.I)).last.click()
        self.page.get_by_role("heading", name="Application overview").wait_for()
        self.assertEqual(sum(method == "POST" and url.endswith("/api/auth/login") for method, url in self.requests), 1)

    def test_demo_plot_switches_measures_and_opens_matching_run(self):
        self.page.goto(self.base_url + "/#demo")
        assistant = sample_cohort("assistant-service")
        summary_data = assistant["summary"]
        plot = self.page.get_by_role("region", name="What does this cohort show?")
        summary = plot.get_by_label("Selected cohort evidence")
        self.assertIn(f"{summary_data['workflows']}\nrecorded workflows", summary.inner_text())
        self.assertIn(f"{summary_data['outcome_workflows']} / {summary_data['workflows']}\nwith an explicit outcome", summary.inner_text())
        self.assertIn(f"{summary_data['known_cost_events']} / {summary_data['usage_events']}\nusage events with a price", summary.inner_text())
        self.assertIn(f"{summary_data['unknown_cost_events']} usage events with unknown cost", summary.inner_text())
        self.assertEqual(plot.locator(".overview-aggregate-grid .overview-chart-card").count(), 5)
        coverage = plot.locator(".overview-chart-card").filter(has_text="Usage price coverage")
        self.assertIn(f"{summary_data['known_cost_events']} of {summary_data['usage_events']} recorded usage events include a price", coverage.inner_text())
        self.assertEqual(coverage.get_by_role("img").get_attribute("aria-label"),
                         f"{summary_data['known_cost_events']} priced usage events; {summary_data['unknown_cost_events']} usage events with unknown cost")
        self.assertIn(f"{assistant['costs'][0]['amount']} USD", plot.locator(".overview-chart-card").filter(has_text="Recorded cost by currency and basis").inner_text())
        durations = sorted(row["duration_ms"] for row in assistant["workflows"] if row["duration_ms"] is not None)
        expected_median = (durations[8] + durations[9]) / 2
        duration_card = plot.locator(".overview-chart-card").filter(has_text="Recorded root duration")
        self.assertIn(f"median of {len(durations)} recorded root durations", duration_card.inner_text())
        self.assertEqual(expected_median, 1045)
        self.assertIn("≈1050 ms", duration_card.inner_text())
        self.assertEqual(plot.get_by_role("group", name="Workflows over time · Trend").get_by_role("button").count(), 18)
        observations = plot.get_by_label("What the evidence says").inner_text()
        self.assertIn(f"{summary_data['outcome_workflows']} of {summary_data['workflows']} workflows have an explicit outcome", observations)
        self.assertIn(f"{summary_data['known_cost_events']} of {summary_data['usage_events']} recorded usage events have a price", observations)
        outcome = plot.get_by_role("group", name="Workflow chart view")
        self.assertEqual(outcome.get_by_role("button", name="Outcomes").get_attribute("aria-pressed"), "true")
        self.assertIn(f"Accepted: {summary_data['accepted_workflows']}",
                      plot.get_by_role("img", name=re.compile("Accepted:")).get_attribute("aria-label"))
        outcome.get_by_role("button", name="Status").click()
        self.assertEqual(outcome.get_by_role("button", name="Status").get_attribute("aria-pressed"), "true")
        status_chart = plot.get_by_role("group", name="Workflow status · Vertical bars")
        self.assertIn(f"completed: {summary_data['completed_workflows']}",
                      status_chart.get_by_role("button", name=re.compile("completed:")).get_attribute("aria-label"))
        self.assertIn(f"failed: {summary_data['failed_workflows']}",
                      status_chart.get_by_role("button", name=re.compile("failed:")).get_attribute("aria-label"))
        for title, metric in (("Highest comparable recorded cost", "cost"),
                              ("Longest recorded duration", "duration"),
                              ("Most usage events", "usage")):
            ranking = plot.get_by_role("article", name=title)
            expected = ranked_ids(assistant["workflows"], metric)
            self.assertEqual(ranking.locator("ol button").count(), min(10, len(expected)))
            self.assertEqual(ranking.locator("ol button").evaluate_all(
                "rows => rows.map(row => row.dataset.workflowId)"), expected[:10])
            self.assertIn(f"Top {min(10, len(expected))} of {len(expected)} eligible", ranking.inner_text())
        cost_ranking = plot.get_by_role("article", name="Highest comparable recorded cost")
        cost_ranking.locator("ol button").first.click()
        dialog = self.page.get_by_role("dialog")
        self.assertIn(ranked_ids(assistant["workflows"], "cost")[0], dialog.inner_text())
        self.assertIn("Fictional context:", dialog.inner_text())
        dialog.get_by_role("button", name="Close").click()

        self.page.get_by_label("Sample application").select_option("document-indexer")
        indexer = sample_cohort("document-indexer")
        indexer_summary = indexer["summary"]
        plot = self.page.get_by_role("region", name="What does this cohort show?")
        self.assertEqual(plot.get_by_role("article", name="Highest comparable recorded cost").locator("ol button")
                         .evaluate_all("rows => rows.map(row => row.dataset.workflowId)"),
                         ranked_ids(indexer["workflows"], "cost")[:10])
        summary = plot.get_by_label("Selected cohort evidence").inner_text()
        self.assertIn(f"{indexer_summary['outcome_workflows']} / {indexer_summary['workflows']}\nwith an explicit outcome", summary)
        self.assertIn(f"{indexer_summary['known_cost_events']} / {indexer_summary['usage_events']}\nusage events with a price", summary)
        plot.get_by_role("button", name=re.compile("Build a view")).click()
        self.page.get_by_role("heading", name="Shape the sample into your view").wait_for()
        self.assertEqual(self.requests, [], "Visual exploration of the sample should remain local and read-only")

    def test_demo_plot_controls_work_on_a_phone_and_with_keyboard(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.goto(self.base_url + "/#demo")
        plot = self.page.get_by_role("region", name="What does this cohort show?")
        status = plot.get_by_role("group", name="Workflow chart view").get_by_role("button", name="Status")
        status.focus()
        self.page.keyboard.press("Enter")
        self.assertEqual(status.get_attribute("aria-pressed"), "true")
        self.assertGreaterEqual(plot.get_by_role("group", name="Workflow status · Vertical bars").get_by_role("button").count(), 2)
        run = plot.get_by_role("article", name="Most usage events").locator("ol button").first
        run.focus()
        self.page.keyboard.press("Enter")
        self.page.get_by_role("dialog", name="Workflow details").wait_for()
        self.page.get_by_role("dialog").get_by_role("button", name="Close").click()
        self.assertEqual(plot.get_by_role("article", name="Longest recorded duration").locator("ol button").count(), 10)
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"),
                             self.page.evaluate("document.documentElement.clientWidth") + 1)
        self.assertEqual(self.requests, [])

    def test_context_filters_recompute_charts_cost_findings_details_and_builder_preview(self):
        self.page.goto(self.base_url + "/#demo")
        filters = self.page.get_by_role("group", name="Explore the fictional sample")
        self.assertIn("not TraceWorth account roles", filters.inner_text())

        def assert_slice(application, organization="*", group="*", user="*"):
            selected = SAMPLE["slices"]["|".join((application, organization, group, user))]
            overview = self.page.get_by_role("region", name="What does this cohort show?")
            summary = overview.get_by_label("Selected cohort evidence").inner_text()
            counts = selected["summary"]
            self.assertIn(f"{counts['workflows']}\nrecorded workflows", summary)
            self.assertIn(f"{counts['outcome_workflows']} / {counts['workflows']}\nwith an explicit outcome", summary)
            self.assertIn(f"{counts['known_cost_events']} / {counts['usage_events']}\nusage events with a price", summary)
            self.assertIn(f"{counts['unknown_cost_events']} usage event", summary)
            self.assertEqual(
                set(self.page.get_by_role("region", name="Sample workflows table, scroll horizontally for more columns")
                    .locator("tbody .workflow-id").all_inner_texts()), set(selected["workflow_ids"]))
            self.assertEqual(
                [label.strip() for label in self.page.locator(".finding-card h3").all_inner_texts()],
                [finding["code"].replace("_", " ") for finding in selected["findings"]])
            if selected["costs"]:
                self.assertIn(f"{selected['costs'][0]['amount']} USD",
                              self.page.locator(".panel:has(h2:text-is('Recorded sample costs'))").inner_text())
            workflows = [workflow for workflow in sample_cohort(application)["workflows"]
                         if workflow["workflow_id"] in selected["workflow_ids"]]
            for title, metric in (("Highest comparable recorded cost", "cost"),
                                  ("Longest recorded duration", "duration"),
                                  ("Most usage events", "usage")):
                self.assertEqual(overview.get_by_role("article", name=title).locator("ol button")
                                 .evaluate_all("rows => rows.map(row => row.dataset.workflowId)"),
                                 ranked_ids(workflows, metric)[:10])
            self.assertIn(f"{counts['known_cost_events']} of {counts['usage_events']} recorded usage events include a price",
                          overview.inner_text())
            return selected

        initial = assert_slice("assistant-service")
        filters.get_by_label("Fictional organization").select_option("alder-works")
        organization_slice = assert_slice("assistant-service", "alder-works")
        self.assertNotEqual(initial["costs"], organization_slice["costs"])
        self.assertIn("Alder Works", self.page.locator(".source-panel").inner_text())
        self.assertEqual(organization_slice["costs"][0]["cost_per_accepted_result"],
                         "0.05166666666666666666666666667")
        cost_panel = self.page.locator(".panel:has(h2:text-is('Recorded sample costs'))").inner_text()
        self.assertIn("≈0.0517 USD", cost_panel)
        self.assertNotIn(organization_slice["costs"][0]["cost_per_accepted_result"], cost_panel)
        self.assertEqual(filters.get_by_label("Client group").locator("option").count(), 3)
        filters.get_by_label("Client group").select_option("field-ops")
        group_slice = assert_slice("assistant-service", "alder-works", "field-ops")
        self.assertNotEqual(organization_slice["summary"]["workflows"], group_slice["summary"]["workflows"])
        filters.get_by_label("Sample user").select_option("maya")
        user_slice = assert_slice("assistant-service", "alder-works", "field-ops", "maya")
        self.assertEqual(user_slice["summary"]["workflows"], 2)
        self.assertNotIn("failed steps", self.page.locator(".findings-section").inner_text().lower())
        self.assertNotIn("retries", self.page.locator(".findings-section").inner_text().lower())
        overview = self.page.get_by_role("region", name="What does this cohort show?")
        self.assertEqual(overview.get_by_role("group", name="Workflows over time · Vertical bars")
                         .get_by_role("button").count(), 2)
        self.assertIn("Gaps have no recorded root start", overview.inner_text())
        self.assertEqual(overview.get_by_role("group", name="Workflows over time · Trend").count(), 0)
        self.assertIn("median of 2 recorded root durations", overview.inner_text())
        row = self.page.get_by_role("region", name="Sample workflows table, scroll horizontally for more columns")
        row.get_by_role("button", name=re.compile("Inspect answer_question")).first.click()
        dialog = self.page.get_by_role("dialog", name="Workflow details")
        self.assertIn("Alder Works / Field operations / Maya", dialog.inner_text())
        self.assertTrue(any(identifier in dialog.inner_text() for identifier in user_slice["workflow_ids"]))
        dialog.get_by_role("button", name="Close").click()

        overview.get_by_role("button", name=re.compile("Build a view")).click()
        self.page.get_by_role("heading", name="Shape the sample into your view").wait_for()
        self.assertEqual(self.page.get_by_label("Fictional organization").input_value(), "alder-works")
        self.assertEqual(self.page.get_by_label("Client group").input_value(), "field-ops")
        self.assertEqual(self.page.get_by_label("Sample user").input_value(), "maya")
        preview = self.page.get_by_label("Dashboard preview")
        volume = preview.locator(".builder-widget").filter(has_text="Workflow volume")
        self.assertEqual(volume.locator(".builder-stat strong").inner_text(), "2")
        self.assertIn("Alder Works / Field operations / Maya", self.page.locator(".builder-preview-head").inner_text())
        self.page.get_by_label("Sample application").select_option("document-indexer")
        indexer = SAMPLE["slices"]["document-indexer|alder-works|field-ops|maya"]
        self.assertEqual(volume.locator(".builder-stat strong").inner_text(),
                         str(indexer["summary"]["workflows"]))
        self.assertEqual(self.requests, [], "Context filtering and builder preview must stay API-free")

    def test_empty_context_explains_no_match_and_recovers_in_overview_and_builder(self):
        self.page.goto(self.base_url + "/#demo")
        self.page.get_by_label("Sample application").select_option("signal-classifier")
        self.page.get_by_label("Fictional organization").select_option("pine-district")
        self.page.get_by_label("Client group").select_option("research")
        self.page.get_by_label("Sample user").select_option("iris")
        self.page.get_by_role("heading", name="No generated workflows match").wait_for()
        self.assertEqual(self.page.get_by_role("region", name="What does this cohort show?").count(), 0)
        self.assertIn("no sample events", self.page.locator(".empty-panel").inner_text().lower())
        self.page.get_by_role("navigation", name="Demo navigation").get_by_role("button", name="Build a view").click()
        self.assertIn("No generated workflows match this combination. Clear context filters",
                      self.page.locator(".demo-filter-empty").inner_text())
        self.assertEqual(self.page.get_by_label("Dashboard preview").count(), 0)
        self.page.get_by_role("navigation", name="Demo navigation").get_by_role("button", name="Overview").click()
        self.page.get_by_role("button", name="Clear context filters").click()
        self.page.get_by_role("region", name="What does this cohort show?").wait_for()
        self.assertEqual(self.page.get_by_label("Fictional organization").input_value(), "")
        self.assertEqual(self.page.get_by_label("Client group").input_value(), "")
        self.assertEqual(self.page.get_by_label("Sample user").input_value(), "")
        self.assertIn("18\nrecorded workflows",
                      self.page.get_by_label("Selected cohort evidence").inner_text())
        self.assertEqual(self.requests, [])

    def test_all_unpriced_context_preserves_unknown_cost_and_builder_preview(self):
        self.page.goto(self.base_url + "/#demo")
        self.page.get_by_label("Sample application").select_option("signal-classifier")
        self.page.get_by_label("Fictional organization").select_option("pine-district")
        self.page.get_by_label("Client group").select_option("care")
        self.page.get_by_label("Sample user").select_option("eden")
        selected = SAMPLE["slices"]["signal-classifier|pine-district|care|eden"]
        summary = self.page.get_by_label("Selected cohort evidence").inner_text()
        self.assertIn(f"{selected['summary']['workflows']}\nrecorded workflows", summary)
        self.assertIn(f"0 / {selected['summary']['usage_events']}\nusage events with a price", summary)
        self.assertIn(f"{selected['summary']['unknown_cost_events']} usage events with unknown cost", summary)
        cost_panel = self.page.locator(".panel:has(h2:text-is('Recorded sample costs'))")
        self.assertIn("Usage was recorded without price evidence, so cost remains unknown.",
                      self.page.get_by_role("region", name="Sample assessment highlights").inner_text())
        self.assertIn("There is no price evidence for usage in these generated runs.",
                      cost_panel.inner_text())
        self.assertIn("No priced usage recorded. Cost is unknown, not zero.", cost_panel.inner_text())
        overview = self.page.get_by_role("region", name="What does this cohort show?")
        self.assertIn("0 of 8 recorded usage events include a price", overview.inner_text())
        self.assertIn("No priced usage recorded. Cost is unknown, not zero.", overview.inner_text())
        cost_ranking = overview.get_by_role("article", name="Highest comparable recorded cost")
        self.assertEqual(cost_ranking.locator("ol button").count(), 0)
        self.assertIn("No runs have a comparable recorded value", cost_ranking.inner_text())
        self.assertEqual(overview.get_by_role("article", name="Most usage events").locator("ol button").count(), 4)
        table = self.page.get_by_role("region", name="Sample workflows table, scroll horizontally for more columns")
        self.assertEqual(table.locator("tbody tr").count(), selected["summary"]["workflows"])
        self.assertNotIn("0 USD", table.inner_text())
        table.get_by_role("button", name=re.compile("Inspect classify_signal")).first.click()
        dialog = self.page.get_by_role("dialog", name="Workflow details")
        self.assertIn("No priced usage", dialog.inner_text())
        self.assertIn("Pine District / Care / Eden", dialog.inner_text())
        dialog.get_by_role("button", name="Close").click()
        overview.get_by_role("button", name=re.compile("Build a view")).click()
        preview = self.page.get_by_label("Dashboard preview")
        volume = preview.locator(".builder-widget").filter(has_text="Workflow volume")
        self.assertEqual(volume.locator(".builder-stat strong").inner_text(),
                         str(selected["summary"]["workflows"]))
        editor = self.page.get_by_role("region", name="Dashboard layout editor")
        editor.locator('.builder-gallery button:has(strong:text-is("Recorded cost"))').click()
        self.assertIn("No priced usage recorded. Total cost is unknown.", preview.inner_text())
        self.assertEqual(self.requests, [])

    def test_website_demo_link_opens_the_public_sample(self):
        self.page.goto(self.website_url)
        self.page.get_by_role("link", name=re.compile("Explore the interactive demo", re.I)).click()
        self.page.get_by_text(re.compile("synthetic", re.I)).first.wait_for()
        self.assertTrue(self.page.url.startswith(self.base_url + "/#demo"))
        self.assertEqual(self.requests, [])

    def test_website_preview_switches_applications_and_selected_workflow(self):
        self.page.goto(self.website_url)
        self.assertIn("small preview is a separate synthetic snapshot; the full demo has more apps and fictional contexts",
                      self.page.locator("main").inner_text().lower())
        preview = self.page.locator(".preview-window")
        switch = preview.get_by_role("group", name="Sample application")
        assistant = switch.get_by_role("button", name="Assistant service")
        indexer = switch.get_by_role("button", name="Document indexer")
        self.assertEqual(assistant.get_attribute("aria-pressed"), "true")
        self.assertIn("$0.049", preview.locator(".preview-summary").inner_text())
        self.assertIn("Unknown-cost events\n3", preview.locator(".preview-summary").inner_text())
        self.assertEqual(preview.locator(".preview-bar-row").count(), 3)
        preview.get_by_role("button", name=re.compile("Answer request 02")).click()
        self.assertIn("Answer request 02 · Not accepted", preview.locator(".preview-detail").inner_text())
        self.assertEqual(preview.get_by_role("button", name=re.compile("Answer request 02")).get_attribute("aria-pressed"), "true")
        preview.get_by_role("button", name=re.compile("Answer request 03")).click()
        self.assertIn("cost unknown", preview.get_by_role("button", name=re.compile("Answer request 03")).get_attribute("aria-label"))
        self.assertIn("No outcome recorded", preview.locator(".preview-detail").inner_text())

        indexer.click()
        self.assertEqual(indexer.get_attribute("aria-pressed"), "true")
        self.assertIn("$0.011", preview.locator(".preview-summary").inner_text())
        self.assertIn("Unknown-cost events\n3", preview.locator(".preview-summary").inner_text())
        self.assertEqual(preview.locator(".preview-bar-row").count(), 2)
        self.assertIn("Index document 01 · Accepted", preview.locator(".preview-detail").inner_text())
        preview.get_by_role("button", name=re.compile("Index document 02")).click()
        self.assertIn("Two usage events have no recorded price", preview.locator(".preview-detail").inner_text())
        self.assertIn("Partial total", preview.inner_text())
        self.assertIn("No connected account data", preview.inner_text())
        self.assertEqual(self.requests, [], "Interactive marketing preview must not request account data")

    def test_website_mobile_menu_opens_and_closes(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.goto(self.website_url)
        toggle = self.page.get_by_role("button", name="Open menu")
        toggle.click()
        self.assertEqual(self.page.get_by_role("button", name="Close menu").get_attribute("aria-expanded"), "true")
        self.page.get_by_role("navigation", name="Main navigation").get_by_role("link", name="How it works").click()
        self.assertTrue(self.page.url.endswith("#how-it-works"))
        self.assertEqual(self.page.get_by_role("button", name="Open menu").get_attribute("aria-expanded"), "false")
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"),
                             self.page.evaluate("document.documentElement.clientWidth") + 1)
        self.assertEqual(self.requests, [])

    def test_public_demo_and_website_fit_a_phone_viewport(self):
        for width in (320, 390):
            self.page.set_viewport_size({"width": width, "height": 844})
            for address, expected_heading in (
                (self.base_url + "/#demo", "Explore a sample assessment"),
                (self.website_url, "See the recorded work behind"),
            ):
                with self.subTest(address=address, width=width):
                    self.page.goto(address)
                    self.page.get_by_role("heading", name=re.compile(expected_heading, re.I)).wait_for()
                    dimensions = self.page.evaluate("""() => ({
                        viewport: document.documentElement.clientWidth,
                        content: document.documentElement.scrollWidth,
                    })""")
                    self.assertLessEqual(dimensions["content"], dimensions["viewport"] + 1,
                                         "The page should fit the viewport; wide tables may scroll inside their own container")
        self.assertEqual(self.requests, [], "Public sample pages should not call the account API")

    def test_website_has_motion_without_reduced_motion_preference(self):
        self.page.emulate_media(reduced_motion="no-preference")
        self.page.goto(self.website_url)
        hero = self.page.locator(".landing-hero-copy")
        hero.wait_for()
        self.assertGreater(float(hero.evaluate("element => getComputedStyle(element).animationDuration").split(",")[0].removesuffix("s")), 0)
        self.assertEqual(self.requests, [])

    def test_reduced_motion_preference_disables_decorative_motion(self):
        self.page.emulate_media(reduced_motion="reduce")
        for address in (self.base_url + "/#demo", self.website_url):
            with self.subTest(address=address):
                self.page.goto(address)
                self.page.locator("main").wait_for()
                motion = self.page.evaluate("""() => [...document.querySelectorAll('main, main *')]
                    .map(element => ({
                        animation: getComputedStyle(element).animationDuration,
                        transition: getComputedStyle(element).transitionDuration,
                    }))
                    .filter(item => item.animation.split(',').some(duration => parseFloat(duration) > 0)
                        || item.transition.split(',').some(duration => parseFloat(duration) > 0))""")
                self.assertEqual(motion, [], "Reduced motion should disable decorative animation and transition")


if __name__ == "__main__":
    unittest.main()
