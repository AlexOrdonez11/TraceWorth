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


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "apps" / "dashboard"
WEBSITE = ROOT / "apps" / "website"
VITE = ROOT / "node_modules" / "vite" / "bin" / "vite.js"
CHROME = Path(os.environ.get("TRACEWORTH_TEST_CHROME", r"C:\Program Files\Google\Chrome\Application\chrome.exe"))


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
        cls.server = subprocess.Popen(
            ["node", str(VITE), "--host", "127.0.0.1", "--port", str(port), "--strictPort"],
            cwd=DASHBOARD,
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
        content = self.page.locator("main").inner_text().lower()
        self.assertIn("unknown cost", content)
        self.assertIn("workflow", content)
        self.assertIn("not verified improvement recommendations", content)
        self.assertIn("0.049 usd", content)
        self.assertIn("partial", content)
        self.assertEqual(self.page.locator("table tbody tr").count(), 3)
        self.page.get_by_role("button", name=re.compile("Inspect answer_question", re.I)).first.click()
        dialog = self.page.get_by_role("dialog")
        self.assertIn("synthetic", dialog.inner_text().lower())
        self.assertIn("recorded usage", dialog.inner_text().lower())
        dialog.get_by_role("button", name="Close").click()
        self.page.get_by_label("Sample application").select_option("document-indexer")
        self.assertEqual(self.page.locator("table tbody tr").count(), 2)
        self.assertIn("0.011 usd", self.page.locator("main").inner_text().lower())
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
        plot = self.page.get_by_role("region", name="What did each run record?")
        cost = plot.get_by_role("button", name="Recorded cost", exact=True)
        usage = plot.get_by_role("button", name="Usage events", exact=True)
        self.assertEqual(cost.get_attribute("aria-pressed"), "true")
        self.assertEqual(usage.get_attribute("aria-pressed"), "false")
        self.assertIn("0.014 USD", plot.get_by_role("button", name=re.compile("Inspect Run 1")).inner_text())
        self.assertIn("0.035 USD", plot.get_by_role("button", name=re.compile("Inspect Run 2")).inner_text())
        self.assertIn("Unpriced", plot.get_by_role("button", name=re.compile("Inspect Run 3")).inner_text())
        self.assertIn("partial", plot.inner_text().lower())
        self.assertIn("2 of 3 workflows", self.page.get_by_role("region", name="What can we actually conclude?").inner_text())
        self.assertIn("3 of 6 usage events priced", self.page.get_by_role("region", name="What can we actually conclude?").inner_text())

        usage.click()
        self.assertEqual(cost.get_attribute("aria-pressed"), "false")
        self.assertEqual(usage.get_attribute("aria-pressed"), "true")
        for index, count in enumerate((2, 3, 1), start=1):
            row = plot.get_by_role("button", name=re.compile(f"Inspect Run {index}"))
            self.assertIn(f"{count} recorded usage event", row.get_attribute("aria-label"))
            self.assertIn(str(count), row.inner_text())
        plot.get_by_role("button", name=re.compile("Inspect Run 2")).click()
        dialog = self.page.get_by_role("dialog")
        self.assertIn("0.035 USD", dialog.inner_text())
        dialog.get_by_role("button", name="Close").click()

        self.page.get_by_label("Sample application").select_option("document-indexer")
        plot = self.page.get_by_role("region", name="What did each run record?")
        self.assertEqual(plot.get_by_role("button", name="Recorded cost", exact=True).get_attribute("aria-pressed"), "true")
        self.assertEqual(plot.locator(".demo-plot-row").count(), 2)
        self.assertIn("0.011 USD", plot.get_by_role("button", name=re.compile("Inspect Run 1")).inner_text())
        self.assertIn("Unpriced", plot.get_by_role("button", name=re.compile("Inspect Run 2")).inner_text())
        coverage = self.page.get_by_role("region", name="What can we actually conclude?").inner_text()
        self.assertIn("1 of 2 workflows", coverage)
        self.assertIn("1 of 4 usage events priced", coverage)
        self.assertEqual(self.requests, [], "Visual exploration of the sample should remain local and read-only")

    def test_demo_plot_controls_work_on_a_phone_and_with_keyboard(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.goto(self.base_url + "/#demo")
        plot = self.page.get_by_role("region", name="What did each run record?")
        usage = plot.get_by_role("button", name="Usage events", exact=True)
        usage.focus()
        self.page.keyboard.press("Enter")
        self.assertEqual(usage.get_attribute("aria-pressed"), "true")
        run = plot.get_by_role("button", name=re.compile("Inspect Run 1"))
        run.focus()
        self.page.keyboard.press("Enter")
        self.page.get_by_role("dialog", name="Workflow details").wait_for()
        self.page.get_by_role("dialog").get_by_role("button", name="Close").click()
        self.assertLessEqual(self.page.evaluate("document.documentElement.scrollWidth"),
                             self.page.evaluate("document.documentElement.clientWidth") + 1)
        self.assertEqual(self.requests, [])

    def test_website_demo_link_opens_the_public_sample(self):
        self.page.goto(self.website_url)
        self.page.get_by_role("link", name=re.compile("Explore the interactive demo", re.I)).click()
        self.page.get_by_text(re.compile("synthetic", re.I)).first.wait_for()
        self.assertTrue(self.page.url.startswith(self.base_url + "/#demo"))
        self.assertEqual(self.requests, [])

    def test_website_preview_switches_applications_and_selected_workflow(self):
        self.page.goto(self.website_url)
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
