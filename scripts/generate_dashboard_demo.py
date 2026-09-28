"""Build the API-free dashboard fixture from deterministic, valid SDK event envelopes.

Run from the repository root: python scripts/generate_dashboard_demo.py
Use --check to verify the checked-in fixture without writing it.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from traceworth.assessment import assess_events  # noqa: E402

OUTPUT = ROOT / "apps" / "dashboard" / "src" / "demo-report.json"
APPLICATIONS = [
    {"id": "assistant-service", "name": "Assistant service", "slug": "assistant-service", "workflow": "answer_question"},
    {"id": "document-indexer", "name": "Document indexer", "slug": "document-indexer", "workflow": "index_document"},
    {"id": "signal-classifier", "name": "Signal classifier", "slug": "signal-classifier", "workflow": "classify_signal"},
]
ORGANIZATIONS = [
    {"id": "alder-works", "name": "Alder Works"},
    {"id": "meridian-studio", "name": "Meridian Studio"},
    {"id": "pine-district", "name": "Pine District"},
]
CLIENT_GROUPS = [
    {"id": "field-ops", "name": "Field operations", "organization_id": "alder-works"},
    {"id": "support", "name": "Support", "organization_id": "alder-works"},
    {"id": "accounts", "name": "Accounts", "organization_id": "meridian-studio"},
    {"id": "archive", "name": "Archive", "organization_id": "meridian-studio"},
    {"id": "care", "name": "Care", "organization_id": "pine-district"},
    {"id": "research", "name": "Research", "organization_id": "pine-district"},
]
USERS = [
    {"id": "maya", "name": "Maya", "client_group_id": "field-ops"},
    {"id": "leo", "name": "Leo", "client_group_id": "field-ops"},
    {"id": "ava", "name": "Ava", "client_group_id": "support"},
    {"id": "niko", "name": "Niko", "client_group_id": "accounts"},
    {"id": "ria", "name": "Ria", "client_group_id": "accounts"},
    {"id": "theo", "name": "Theo", "client_group_id": "archive"},
    {"id": "eden", "name": "Eden", "client_group_id": "care"},
    {"id": "jules", "name": "Jules", "client_group_id": "care"},
    {"id": "iris", "name": "Iris", "client_group_id": "research"},
]
START = datetime(2026, 2, 1, 12, tzinfo=timezone.utc)


def identity(value: str) -> str:
    return str(uuid5(NAMESPACE_URL, "traceworth-public-demo-v2:" + value))


def timestamp(start: datetime, milliseconds: int) -> str:
    return (start + timedelta(milliseconds=milliseconds)).isoformat()


def make_events() -> tuple[list[dict], dict[str, dict]]:
    events: list[dict] = []
    contexts: dict[str, dict] = {}
    serial = 0

    def emit(app: dict, run: int, workflow_id: str, step_id: str | None,
             event_type: str, at: datetime, offset: int, **fields) -> None:
        nonlocal serial
        serial += 1
        events.append({
            "schema_version": 1, "event_id": identity(f"event-{serial}"),
            "event_type": event_type, "occurred_at": timestamp(at, offset),
            "application_id": app["id"], "environment": "synthetic-demo",
            "configuration_id": "sample-v2", "workflow_id": workflow_id,
            "step_id": step_id, **fields,
        })

    def step(app: dict, run: int, workflow_id: str, step_id: str, name: str,
             kind: str, parent: str | None, attempt: int, at: datetime,
             started: int, duration: int, status: str = "completed") -> None:
        common = {"name": name, "kind": kind, "parent_step_id": parent,
                  "attempt_number": attempt}
        emit(app, run, workflow_id, step_id, "step.started", at, started, **common)
        emit(app, run, workflow_id, step_id, "step.finished", at, started + duration,
             **common, status=status,
             error_category="SyntheticRetry" if status == "failed" else None,
             duration_ms=float(duration))

    def usage(app: dict, run: int, workflow_id: str, step_id: str, at: datetime,
              offset: int, service: str, units: dict, amount: str | None) -> None:
        emit(app, run, workflow_id, step_id, "usage.recorded", at, offset,
             provider="synthetic-provider", model_or_service=service,
             usage_units=units, amount=amount,
             currency="USD" if amount is not None else None,
             cost_basis="estimated" if amount is not None else None,
             price_version="sample-v2" if amount is not None else None)

    for app_index, app in enumerate(APPLICATIONS):
        for run in range(18):
            workflow_id = identity(f"{app['id']}-workflow-{run}")
            root = identity(f"{app['id']}-root-{run}")
            prep = identity(f"{app['id']}-prep-{run}")
            retrieve = identity(f"{app['id']}-retrieve-{run}")
            query = identity(f"{app['id']}-query-{run}")
            generate = identity(f"{app['id']}-generate-{run}")
            validate = identity(f"{app['id']}-validate-{run}")
            at = START + timedelta(days=run, hours=app_index)
            organization = ORGANIZATIONS[(run + app_index) % 3]
            groups = [item for item in CLIENT_GROUPS if item["organization_id"] == organization["id"]]
            group = groups[(run // 3 + app_index) % len(groups)]
            # Keep one valid context path empty so the public demo can show its
            # honest no-match state without suggesting a real customer has no runs.
            if app["id"] == "signal-classifier" and group["id"] == "research":
                group = next(item for item in groups if item["id"] == "care")
            people = [item for item in USERS if item["client_group_id"] == group["id"]]
            person = people[(run // 6 + app_index) % len(people)]
            all_unpriced = app["id"] == "signal-classifier" and person["id"] == "eden"
            contexts[workflow_id] = {"organization_id": organization["id"],
                                     "client_group_id": group["id"], "user_id": person["id"]}

            failed_step = (run + app_index * 2) % 7 == 3
            root_failed = (run + app_index * 3) % 11 == 5
            duration = 760 + ((run * 71 + app_index * 47) % 850)
            step(app, run, workflow_id, root, app["workflow"], "workflow", None,
                 1, at, 0, duration, "failed" if root_failed else "completed")
            step(app, run, workflow_id, prep, "prepare_input", "operation", root,
                 1, at, 12, 35 + run % 17)
            step(app, run, workflow_id, retrieve, "retrieve_context", "operation", root,
                 1, at, 68, 108 + run % 45)
            step(app, run, workflow_id, query, "source_query", "operation", retrieve,
                 1, at, 82, 53 + run % 22)
            usage(app, run, workflow_id, query, at, 103, "sample-search",
                  {"queries": 1}, None if all_unpriced or (run + app_index) % 3 != 0 else "0.002")
            step(app, run, workflow_id, generate, "generate_result", "operation", root,
                 1, at, 240, 145 + run % 70, "failed" if failed_step else "completed")
            usage(app, run, workflow_id, generate, at, 280, "sample-model-a" if run % 2 else "sample-model-b",
                  {"input_tokens": 300 + run * 23, "output_tokens": 70 + run * 7},
                  None if all_unpriced else f"0.{12 + (run % 9) * 3:03d}")
            if failed_step:
                retry = identity(f"{app['id']}-retry-{run}")
                step(app, run, workflow_id, retry, "generate_result", "operation", root,
                     2, at, 420, 120 + run % 31)
                usage(app, run, workflow_id, retry, at, 445, "sample-model-a",
                      {"input_tokens": 260 + run * 11, "output_tokens": 90 + run * 5},
                      None if all_unpriced else "0.017")
            step(app, run, workflow_id, validate, "validate_result", "operation", root,
                 1, at, 590, 46 + run % 23)
            if (run + app_index) % 4 == 0:
                usage(app, run, workflow_id, validate, at, 607, "sample-validator",
                      {"checks": 1}, None)
            if (run + app_index) % 6 != 0:
                emit(app, run, workflow_id, None, "outcome.recorded", at, duration + 18,
                     outcome_type="accepted", value=not root_failed and (run + app_index) % 5 != 1,
                     evaluator_version="synthetic-review-v2")
    return events, contexts


def key(app: str, organization: str | None, group: str | None, user: str | None) -> str:
    return "|".join((app, organization or "*", group or "*", user or "*"))


def build_fixture() -> dict:
    events, contexts = make_events()
    report = assess_events(events)
    if report["input"]["invalid_lines"] or report["input"]["duplicate_events"]:
        raise RuntimeError("Generated event envelopes did not pass assessment validation")
    slices = {}
    for app in APPLICATIONS:
        app_id = app["id"]
        app_events = [event for event in events if event["application_id"] == app_id]
        app_workflows = {event["workflow_id"] for event in app_events}
        combinations = set()
        for workflow_id in app_workflows:
            context = contexts[workflow_id]
            for organization in (None, context["organization_id"]):
                for group in (None, context["client_group_id"]):
                    for user in (None, context["user_id"]):
                        combinations.add((organization, group, user))
        for organization, group, user in sorted(combinations, key=lambda parts: tuple(item or "" for item in parts)):
            selected = {workflow_id for workflow_id in app_workflows
                        if (organization is None or contexts[workflow_id]["organization_id"] == organization)
                        and (group is None or contexts[workflow_id]["client_group_id"] == group)
                        and (user is None or contexts[workflow_id]["user_id"] == user)}
            scoped = assess_events(event for event in app_events if event["workflow_id"] in selected)
            cohort = scoped["cohorts"][0]
            slices[key(app_id, organization, group, user)] = {
                "workflow_ids": sorted(selected), "summary": cohort["summary"],
                "costs": cohort["costs"], "findings": cohort["findings"],
            }
    return {
        "schema_version": 2,
        "generation": "Deterministic synthetic events assessed by traceworth.assessment.assess_events; contexts are fictional presentation labels, not account roles.",
        "applications": [{item: app[item] for item in ("id", "name", "slug")} for app in APPLICATIONS],
        "organizations": ORGANIZATIONS, "client_groups": CLIENT_GROUPS, "users": USERS,
        "workflow_contexts": contexts, "report": report, "slices": slices,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify that demo-report.json matches this generator")
    args = parser.parse_args()
    rendered = json.dumps(build_fixture(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            print(f"Fixture is stale: {OUTPUT}", file=sys.stderr)
            return 1
        print(f"Fixture verified: {OUTPUT}")
        return 0
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
