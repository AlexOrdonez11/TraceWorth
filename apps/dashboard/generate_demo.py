"""Regenerate the dashboard's static, synthetic assessment fixture.

Run from the repository root with: python apps/dashboard/generate_demo.py
No API, account, or telemetry database is contacted.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from traceworth import TraceWorth  # noqa: E402
from traceworth.assessment import assess_events  # noqa: E402


def main():
    events = []
    with TraceWorth("assistant-service", events.append, environment="synthetic-demo", configuration_id="sample-v1") as trace:
        with trace.span("answer_question", workflow=True) as workflow_id:
            with trace.span("retrieve_context"):
                trace.record_usage("example-search", "index-v1", {"queries": 1})
            with trace.span("generate_answer"):
                trace.record_usage("example-model-provider", "sample-model-a", {"input_tokens": 420, "output_tokens": 115}, amount="0.014", currency="USD", cost_basis="estimated", price_version="sample-v1")
        trace.record_outcome("accepted", True, workflow_id=workflow_id)

        with trace.span("answer_question", workflow=True) as workflow_id:
            with trace.span("retrieve_context"):
                trace.record_usage("example-search", "index-v1", {"queries": 1})
            with trace.span("generate_answer", attempt_number=1):
                trace.record_usage("example-model-provider", "sample-model-a", {"input_tokens": 510, "output_tokens": 70}, amount="0.016", currency="USD", cost_basis="estimated", price_version="sample-v1")
            with trace.span("generate_answer", attempt_number=2):
                trace.record_usage("example-model-provider", "sample-model-a", {"input_tokens": 560, "output_tokens": 138}, amount="0.019", currency="USD", cost_basis="estimated", price_version="sample-v1")
        trace.record_outcome("accepted", False, workflow_id=workflow_id)

        with trace.span("answer_question", workflow=True):
            try:
                with trace.span("retrieve_context"):
                    raise TimeoutError("Synthetic example failure")
            except TimeoutError:
                pass
            with trace.span("generate_answer"):
                trace.record_usage("example-model-provider", "sample-model-b", {"input_tokens": 240, "output_tokens": 65})

    with TraceWorth("document-indexer", events.append, environment="synthetic-demo", configuration_id="sample-v1") as trace:
        with trace.span("index_document", workflow=True) as workflow_id:
            with trace.span("parse_document"):
                trace.record_usage("example-parser", "parser-v1", {"pages": 6})
            with trace.span("embed_sections"):
                trace.record_usage("example-model-provider", "sample-embedding-model", {"input_tokens": 1100}, amount="0.011", currency="USD", cost_basis="estimated", price_version="sample-v1")
        trace.record_outcome("accepted", True, workflow_id=workflow_id)

        with trace.span("index_document", workflow=True):
            with trace.span("parse_document"):
                trace.record_usage("example-parser", "parser-v1", {"pages": 4})
            with trace.span("embed_sections"):
                trace.record_usage("example-model-provider", "sample-embedding-model", {"input_tokens": 780})

    # Keep checked-in output stable across runs. The SDK creates random IDs and
    # live timings; replace them with fixed illustrative values before assessment.
    ids = {}
    def stable_id(value):
        if value is None:
            return None
        if value not in ids:
            ids[value] = str(UUID(int=len(ids) + 1))
        return ids[value]

    start = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    for index, event in enumerate(events):
        for field in ("event_id", "workflow_id", "step_id", "parent_step_id"):
            if field in event:
                event[field] = stable_id(event[field])
        event["occurred_at"] = (start + timedelta(milliseconds=index * 10)).isoformat()
        if event["event_type"] == "step.finished":
            event["duration_ms"] = float(80 + index * 3)

    report = assess_events(events)
    fixture = {
        "applications": [
            {"id": "assistant-service", "name": "Assistant service", "slug": "assistant-service"},
            {"id": "document-indexer", "name": "Document indexer", "slug": "document-indexer"},
        ],
        "report": report,
    }
    output = Path(__file__).parent / "src" / "demo-report.json"
    output.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output} from {len(events)} synthetic SDK events")


if __name__ == "__main__":
    main()
