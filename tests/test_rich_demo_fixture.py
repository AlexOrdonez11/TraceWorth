"""Independent consistency checks for the public synthetic demo fixture."""

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path
import runpy
import subprocess
import sys
import unittest

from traceworth.assessment import assess_events


FIXTURE = Path(__file__).resolve().parents[1] / "apps" / "dashboard" / "src" / "demo-report.json"
GENERATOR = FIXTURE.parents[3] / "scripts" / "generate_dashboard_demo.py"


class RichDemoFixtureAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sample = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.generator = runpy.run_path(str(GENERATOR))
        cls.events, cls.contexts = cls.generator["make_events"]()

    def test_generator_is_reproducible_and_assessment_matches_checked_in_fixture(self):
        check = subprocess.run([sys.executable, str(GENERATOR), "--check"],
                               cwd=FIXTURE.parents[3], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertEqual(self.sample, self.generator["build_fixture"]())
        self.assertEqual((self.events, self.contexts), self.generator["make_events"]())
        self.assertEqual(self.sample["report"], assess_events(self.events))
        self.assertEqual(self.sample["report"]["input"]["valid_events"], len(self.events))
        self.assertEqual(self.sample["report"]["input"]["invalid_lines"], 0)

    def test_sample_has_broad_fictional_context_and_multiday_traces(self):
        sample = self.sample
        self.assertGreaterEqual(len(sample["applications"]), 3)
        self.assertGreaterEqual(len(sample["organizations"]), 3)
        self.assertGreaterEqual(len(sample["client_groups"]), 5)
        self.assertGreaterEqual(len(sample["users"]), 8)
        workflows = [workflow for cohort in sample["report"]["cohorts"]
                     for workflow in cohort["workflows"]]
        self.assertGreaterEqual(len(workflows), 40)
        self.assertEqual(set(sample["workflow_contexts"]),
                         {workflow["workflow_id"] for workflow in workflows})
        starts = [datetime.fromisoformat(step["started_at"])
                  for workflow in workflows for step in workflow["steps"]
                  if step["kind"] == "workflow" and step["started_at"]]
        self.assertGreaterEqual((max(starts) - min(starts)).days, 14)
        self.assertGreaterEqual(len({start.date() for start in starts}), 14)
        self.assertGreater(len({workflow["duration_ms"] for workflow in workflows}), 5)
        self.assertTrue(any(workflow["status"] == "failed" for workflow in workflows))
        self.assertTrue(any(workflow["accepted"] is None for workflow in workflows))
        self.assertTrue(any(workflow["unknown_cost_events"] for workflow in workflows))
        self.assertTrue(any(len(workflow["steps"]) >= 5 for workflow in workflows))

    def test_every_slice_uses_exact_context_workflows_and_reassessed_values(self):
        application_for = {
            workflow["workflow_id"]: cohort["application_id"]
            for cohort in self.sample["report"]["cohorts"]
            for workflow in cohort["workflows"]
        }
        organizations = {item["id"] for item in self.sample["organizations"]}
        groups = {item["id"]: item["organization_id"] for item in self.sample["client_groups"]}
        users = {item["id"]: item["client_group_id"] for item in self.sample["users"]}
        self.assertEqual(self.contexts, self.sample["workflow_contexts"])
        for workflow_id, context in self.contexts.items():
            with self.subTest(context_workflow=workflow_id):
                self.assertIn(context["organization_id"], organizations)
                self.assertEqual(groups[context["client_group_id"]], context["organization_id"])
                self.assertEqual(users[context["user_id"]], context["client_group_id"])
        self.assertGreaterEqual(len(self.sample["slices"]), 40)
        for slice_key, slice_report in self.sample["slices"].items():
            app, organization, group, user = slice_key.split("|")
            selected = {
                workflow_id for workflow_id, context in self.contexts.items()
                if application_for[workflow_id] == app
                and (organization == "*" or context["organization_id"] == organization)
                and (group == "*" or context["client_group_id"] == group)
                and (user == "*" or context["user_id"] == user)
            }
            with self.subTest(slice=slice_key):
                self.assertTrue(selected)
                self.assertEqual(slice_report["workflow_ids"], sorted(selected))
                assessed = assess_events(event for event in self.events
                                         if event["workflow_id"] in selected)["cohorts"]
                self.assertEqual(len(assessed), 1)
                self.assertEqual(slice_report["summary"], assessed[0]["summary"])
                self.assertEqual(slice_report["costs"], assessed[0]["costs"])
                self.assertEqual(slice_report["findings"], assessed[0]["findings"])

    def test_empty_and_all_unpriced_contexts_are_real_assessed_cases(self):
        empty = "signal-classifier|pine-district|research|iris"
        self.assertNotIn(empty, self.sample["slices"])
        signal_ids = {workflow["workflow_id"]
                      for cohort in self.sample["report"]["cohorts"]
                      if cohort["application_id"] == "signal-classifier"
                      for workflow in cohort["workflows"]}
        self.assertFalse(any(
            workflow_id in signal_ids
            and context["organization_id"] == "pine-district"
            and context["client_group_id"] == "research"
            and context["user_id"] == "iris"
            for workflow_id, context in self.contexts.items()
        ))
        unpriced = self.sample["slices"]["signal-classifier|pine-district|care|eden"]
        self.assertGreaterEqual(unpriced["summary"]["workflows"], 1)
        self.assertEqual(unpriced["summary"]["known_cost_events"], 0)
        self.assertEqual(unpriced["summary"]["unknown_cost_events"],
                         unpriced["summary"]["usage_events"])
        self.assertEqual(unpriced["costs"], [])
        self.assertIn("missing_cost", {finding["code"] for finding in unpriced["findings"]})

    def test_assessed_totals_match_visible_workflow_records(self):
        applications = {item["id"] for item in self.sample["applications"]}
        cohorts = self.sample["report"]["cohorts"]
        self.assertTrue(cohorts)
        self.assertEqual(applications, {cohort["application_id"] for cohort in cohorts})
        for cohort in cohorts:
            with self.subTest(application=cohort["application_id"]):
                workflows = cohort["workflows"]
                summary = cohort["summary"]
                self.assertEqual(summary["workflows"], len(workflows))
                self.assertEqual(summary["accepted_workflows"],
                                 sum(workflow["accepted"] is True for workflow in workflows))
                self.assertEqual(summary["outcome_workflows"],
                                 sum(workflow["accepted"] is not None for workflow in workflows))
                self.assertEqual(summary["usage_events"],
                                 sum(workflow["usage_events"] for workflow in workflows))
                self.assertEqual(summary["unknown_cost_events"],
                                 sum(workflow["unknown_cost_events"] for workflow in workflows))
                self.assertEqual(summary["known_cost_events"],
                                 summary["usage_events"] - summary["unknown_cost_events"])
                grouped = defaultdict(Decimal)
                for workflow in workflows:
                    for cost in workflow["costs"]:
                        grouped[(cost["currency"], cost["cost_basis"])] += Decimal(cost["amount"])
                self.assertEqual(set(grouped),
                                 {(cost["currency"], cost["cost_basis"]) for cost in cohort["costs"]})
                for cost in cohort["costs"]:
                    self.assertEqual(Decimal(cost["amount"]),
                                     grouped[(cost["currency"], cost["cost_basis"])])


if __name__ == "__main__":
    unittest.main()
