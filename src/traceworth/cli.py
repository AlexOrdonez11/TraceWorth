"""Local demo and assessment commands."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .assessment import assess_file, format_text
from .sdk import JsonlExporter, TraceWorth


def create_demo(path: str | Path) -> None:
    """Create synthetic telemetry exclusively through the public SDK API."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create avoids accidentally replacing captured real application data.
    with target.open('x', encoding='utf-8'):
        pass
    for app, workflow_name in [('ClientSignalEQ', 'conversation_analysis'),
                               ('MyHandyAI', 'repair_request'),
                               ('AnalyticsAI', 'answer_question')]:
        with TraceWorth(app, JsonlExporter(target), environment='synthetic-demo', configuration_id='synthetic-v1') as client:
            for index in range(3):
                with client.span(workflow_name, workflow=True) as workflow_id:
                    if index == 1:
                        try:
                            with client.span('synthetic_provider_call', attempt_number=1):
                                client.record_usage('synthetic', 'fixture-model', {'input_tokens': 100}, amount='0.01', currency='USD', cost_basis='estimated', price_version='synthetic-v1')
                                raise RuntimeError('Synthetic failure')
                        except RuntimeError:
                            pass
                    with client.span('synthetic_provider_call', attempt_number=2 if index == 1 else 1):
                        if index == 2:
                            client.record_usage('synthetic', 'fixture-model', {'input_tokens': 90, 'output_tokens': 30})
                        else:
                            client.record_usage('synthetic', 'fixture-model', {'input_tokens': 100, 'output_tokens': 50}, amount='0.02', currency='USD', cost_basis='estimated', price_version='synthetic-v1')
                if index < 2:
                    client.record_outcome('accepted', index == 0, workflow_id=workflow_id, evaluator_version='synthetic-human-v1')
            if not client.close():
                raise RuntimeError('Synthetic demo export did not finish')
            if client.diagnostics['dropped_events'] or client.diagnostics['export_errors']:
                raise RuntimeError('Synthetic demo export lost events')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='traceworth', description='Inspect Python workflow costs, retries, outcomes, and recorded usage locally.',
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog='Quick start:\n  python -m traceworth demo --output new-demo.jsonl\n  python -m traceworth assess new-demo.jsonl\n  python -m traceworth serve --events new-demo.jsonl')
    commands = parser.add_subparsers(dest='command', required=True)
    demo = commands.add_parser('demo', help='Generate synthetic examples for three applications', description='Create synthetic workflows for all three applications, including retries, outcomes, and unknown costs. Choose a new file; existing data is preserved.', epilog='Example: python -m traceworth demo --output new-demo.jsonl')
    demo.add_argument('--output', type=Path, required=True, help='New JSONL path (must not already exist)')
    assess = commands.add_parser('assess', help='Summarize recorded JSONL events', description='Summarize costs, usage, failures, and outcomes from a local JSONL export. Malformed rows are reported while valid rows continue to be assessed. A successful exit does not guarantee that all rows were valid; inspect the input diagnostics. Use --detail for workflow trees and evidence IDs.', epilog='Example: python -m traceworth assess new-demo.jsonl --detail --output report.txt')
    assess.add_argument('path', type=Path, help='JSONL event file to assess')
    assess.add_argument('--format', choices=['text', 'json'], default='text', help='Readable summary (text, default) or complete machine-readable report (json)')
    assess.add_argument('--detail', action='store_true', help='Include workflow trees and evidence IDs in text output; JSON always includes full detail')
    assess.add_argument('--output', type=Path, help='Save the report to this path instead of printing it, replacing any existing report at that path')
    serve = commands.add_parser('serve', help='Open a local web dashboard', description='Serve the local TraceWorth dashboard on localhost. Stop it with Ctrl+C.', epilog='Example: python -m traceworth serve --events new-demo.jsonl --port 8765')
    serve.add_argument('--events', type=Path, help='Optional JSONL export to load into the dashboard')
    serve.add_argument('--port', type=int, default=8765, help='Local port (default: 8765)')
    args = parser.parse_args(argv)
    try:
        if args.command == 'demo':
            create_demo(args.output)
            print(f'Synthetic telemetry written to {args.output}')
        elif args.command == 'serve':
            if not 1 <= args.port <= 65535:
                raise ValueError('Port must be between 1 and 65535')
            from .web import serve as serve_dashboard
            serve_dashboard(events=args.events, port=args.port)
        else:
            if args.output and args.output.resolve() == args.path.resolve():
                raise ValueError('Report output must differ from the input events file')
            report = assess_file(args.path)
            rendered = json.dumps(report, indent=2, allow_nan=False) + '\n' if args.format == 'json' else format_text(report, detail=args.detail)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(rendered, encoding='utf-8')
                print(f'Report saved to {args.output.resolve()}', file=sys.stderr)
            else:
                sys.stdout.write(rendered)
    except FileExistsError as exc:
        print(f'traceworth: That path already exists: {exc.filename}. Existing data was preserved. Choose a new --output path, for example --output new-demo.jsonl.', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('\nTraceWorth stopped.', file=sys.stderr)
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'traceworth: {exc}', file=sys.stderr)
        return 2
    return 0
