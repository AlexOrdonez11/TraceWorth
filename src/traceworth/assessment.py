"""Deterministic assessments of observed telemetry; no inference of unseen usage."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import json
from pathlib import Path
from typing import Iterable

from .validation import validate_event


def _order(event):
    return (datetime.fromisoformat(event['occurred_at'].upper().replace('Z', '+00:00')), event['event_id'])


def _sum(values):
    numbers = [Decimal(str(value)) for value in values]
    if not numbers:
        return Decimal(0)
    # Preserve exact sums, including widely separated fractional exponents.
    precision = max(n.adjusted() for n in numbers) - min(n.as_tuple().exponent for n in numbers) + len(str(len(numbers))) + 3
    with localcontext() as context:
        context.prec = max(28, precision)
        return sum(numbers, Decimal(0))


def _ordered_steps(steps):
    """Preorder traversal with chronological siblings; retain disconnected graphs."""
    by_id = {step['step_id']: step for step in steps}
    children = defaultdict(list)
    def order(step):
        return (step['started_at'] or step['observed_at'], step['step_id'])
    for step in steps:
        children[step['parent_step_id']].append(step)
        step['cycle'] = False
    for step in steps:
        path, positions = [], {}
        current = step
        while current is not None:
            identity = current['step_id']
            if identity in positions:
                for member in path[positions[identity]:]:
                    member['cycle'] = True
                break
            positions[identity] = len(path)
            path.append(current)
            current = by_id.get(current['parent_step_id'])
    roots = sorted((step for step in steps if step['parent_step_id'] not in by_id), key=order)
    result, seen = [], set()
    # Remaining components may contain cycles: start them deterministically too.
    for seed in roots + sorted(steps, key=order):
        pending = [(seed, 0)]
        while pending:
            step, depth = pending.pop()
            if step['step_id'] in seen:
                continue
            seen.add(step['step_id'])
            step['depth'] = depth
            result.append(step)
            pending.extend((child, depth + 1) for child in sorted(children[step['step_id']], key=order, reverse=True))
    return result


def _costs(events, accepted_count=None, *, incomplete_telemetry=False):
    groups = defaultdict(list)
    usage = [e for e in events if e['event_type'] == 'usage.recorded']
    partial = incomplete_telemetry or any(e.get('amount') is None for e in usage)
    for event in usage:
        if event.get('amount') is not None:
            groups[(event['currency'], event['cost_basis'])].append(event['amount'])
    result = []
    for (currency, basis), amounts in sorted(groups.items()):
        total = _sum(amounts)
        with localcontext() as context:
            context.prec = max(28, len(total.as_tuple().digits) + 16)
            per_result = str(total / accepted_count) if accepted_count else None
        result.append({'currency': currency, 'cost_basis': basis, 'amount': str(total),
                       'cost_per_accepted_result': per_result, 'partial': partial})
    return result


def _workflow(workflow_id, events, *, input_errors=False):
    step_events = defaultdict(list)
    for event in events:
        if event['event_type'].startswith('step.'):
            step_events[event['step_id']].append(event)
    steps = []
    for step_id, records in sorted(step_events.items()):
        starts = sorted((e for e in records if e['event_type'] == 'step.started'), key=_order)
        finishes = sorted((e for e in records if e['event_type'] == 'step.finished'), key=_order)
        representative = finishes[-1] if finishes else starts[0]
        step = {key: representative[key] for key in ('name', 'kind', 'parent_step_id', 'attempt_number')}
        step.update(step_id=step_id, status=representative.get('status', 'incomplete'),
                    started_at=_order(starts[0])[0].astimezone(timezone.utc).isoformat() if starts else None,
                    observed_at=min(_order(record)[0] for record in records).astimezone(timezone.utc).isoformat(),
                    duration_ms=representative.get('duration_ms'), incomplete=not starts or not finishes,
                    orphan=representative['parent_step_id'] is not None and representative['parent_step_id'] not in step_events,
                    conflicting_lifecycle=len(starts) > 1 or len(finishes) > 1 or (bool(starts and finishes) and any(starts[0][key] != finishes[-1][key] for key in ('name', 'kind', 'parent_step_id', 'attempt_number'))))
        steps.append(step)
    steps = _ordered_steps(steps)
    roots = [s for s in steps if s['parent_step_id'] is None]
    root = roots[0] if len(roots) == 1 else None
    outcomes = sorted((e for e in events if e['event_type'] == 'outcome.recorded' and e['outcome_type'] == 'accepted' and isinstance(e['value'], bool)), key=_order)
    usage = [e for e in events if e['event_type'] == 'usage.recorded']
    orphan_usage = [e['event_id'] for e in usage if e['step_id'] not in step_events]
    incomplete_telemetry = input_errors or root is None or bool(orphan_usage) or any(
        s['incomplete'] or s['orphan'] or s['conflicting_lifecycle'] or s['cycle'] for s in steps)
    for step in steps:
        step_usage = [e for e in usage if e['step_id'] == step['step_id']]
        step['usage_events'] = len(step_usage)
        step['unknown_cost_events'] = sum(e.get('amount') is None for e in step_usage)
        # Directly attributable usage only: never roll child costs into parents.
        step['costs'] = _costs(step_usage, incomplete_telemetry=incomplete_telemetry)
    units = defaultdict(list)
    for event in usage:
        for unit, value in event['usage_units'].items():
            units[(event['provider'], event['model_or_service'], unit)].append(value)
    return {'workflow_id': workflow_id, 'status': root['status'] if root else 'unknown',
            'duration_ms': root['duration_ms'] if root else None,
            'missing_root': not roots, 'ambiguous_root': len(roots) > 1,
            'accepted': outcomes[-1]['value'] if outcomes else None,
            'acceptance_event_id': outcomes[-1]['event_id'] if outcomes else None,
            'incomplete_telemetry': incomplete_telemetry,
            'steps': steps, 'costs': _costs(events, incomplete_telemetry=incomplete_telemetry), 'usage_events': len(usage),
            'unknown_cost_events': sum(e.get('amount') is None for e in usage),
            'orphan_usage_event_ids': orphan_usage,
            'usage': [{'provider': provider, 'model_or_service': service, 'unit': unit, 'value': str(_sum(values))}
                      for (provider, service, unit), values in sorted(units.items())]}


def _report(events, diagnostics):
    groups = defaultdict(list)
    for event in events:
        groups[(event['application_id'], event['environment'], event['configuration_id'])].append(event)
    cohorts = []
    for (app, env, config), records in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1], item[0][2] or '')):
        by_workflow = defaultdict(list)
        for event in records:
            by_workflow[event['workflow_id']].append(event)
        workflows = [_workflow(key, value, input_errors=bool(diagnostics['errors'])) for key, value in sorted(by_workflow.items())]
        steps = [s for w in workflows for s in w['steps']]
        accepted = sum(w['accepted'] is True for w in workflows)
        usage_count = sum(w['usage_events'] for w in workflows)
        unknown = sum(w['unknown_cost_events'] for w in workflows)
        summary = {'workflows': len(workflows), 'steps': len(steps),
                   'completed_workflows': sum(w['status'] == 'completed' for w in workflows),
                   'failed_workflows': sum(w['status'] == 'failed' for w in workflows),
                   'cancelled_workflows': sum(w['status'] == 'cancelled' for w in workflows),
                   'failed_steps': sum(s['status'] == 'failed' for s in steps),
                   'cancelled_steps': sum(s['status'] == 'cancelled' for s in steps),
                   'retry_steps': sum(s['attempt_number'] > 1 for s in steps),
                   'accepted_workflows': accepted, 'outcome_workflows': sum(w['accepted'] is not None for w in workflows),
                   'incomplete_steps': sum(s['incomplete'] for s in steps),
                   'orphan_steps': sum(s['orphan'] for s in steps),
                   'usage_events': usage_count, 'known_cost_events': usage_count - unknown,
                   'unknown_cost_events': unknown}
        findings = []
        def finding(code, message, evidence):
            if evidence:
                findings.append({'code': code, 'message': message, 'evidence': sorted(evidence)})
        finding('failed_steps', 'Recorded steps failed. Investigate these steps before proposing a change.', [s['step_id'] for s in steps if s['status'] == 'failed'])
        finding('retries', 'Explicit retry attempts were recorded; compare retry causes and their recorded usage.', [s['step_id'] for s in steps if s['attempt_number'] > 1])
        finding('incomplete_steps', 'Start or finish events are missing; recorded execution coverage is incomplete.', [s['step_id'] for s in steps if s['incomplete']])
        finding('orphan_steps', 'A referenced parent step was not observed.', [s['step_id'] for s in steps if s['orphan']])
        finding('cyclic_steps', 'Parent relationships contain a cycle; affected steps are retained for inspection.', [s['step_id'] for s in steps if s['cycle']])
        finding('conflicting_lifecycle', 'A step has repeated or inconsistent lifecycle records; review instrumentation.', [s['step_id'] for s in steps if s['conflicting_lifecycle']])
        finding('missing_cost', 'Observed usage has unknown cost; totals are partial.', [e['event_id'] for e in records if e['event_type'] == 'usage.recorded' and e.get('amount') is None])
        finding('missing_outcome', 'No boolean accepted outcome was recorded for these workflows.', [w['workflow_id'] for w in workflows if w['accepted'] is None])
        finding('missing_root', 'A unique root step was not observed; workflow latency is unavailable.', [w['workflow_id'] for w in workflows if w['missing_root'] or w['ambiguous_root']])
        finding('orphan_usage', 'Usage refers to steps that were not observed.', [eid for w in workflows for eid in w['orphan_usage_event_ids']])
        step_cost_groups = defaultdict(list)
        for workflow in workflows:
            for step in workflow['steps']:
                for cost in step['costs']:
                    step_cost_groups[(cost['currency'], cost['cost_basis'])].append((Decimal(cost['amount']), workflow['workflow_id'], step['step_id']))
        for (currency, basis), candidates in sorted(step_cost_groups.items()):
            highest = max(amount for amount, _, _ in candidates)
            evidence = sorted(step_id for amount, _, step_id in candidates if amount == highest)
            findings.append({'code': 'highest_recorded_step_cost', 'currency': currency,
                             'cost_basis': basis, 'amount': str(highest), 'evidence': evidence,
                             'workflow_ids': sorted({wid for amount, wid, _ in candidates if amount == highest}),
                             'message': f'Highest directly recorded step cost in this cohort: {highest} {currency} ({basis}). This ranks observed costs only; it does not establish an optimization opportunity.'})
        timestamps = [_order(event)[0].astimezone(timezone.utc) for event in records]
        observed_range = {'start': min(timestamps).isoformat(), 'end': max(timestamps).isoformat()}
        cohorts.append({'application_id': app, 'environment': env, 'configuration_id': config,
                        'observed_time_range': observed_range, 'acceptance_cutoff_at': observed_range['end'],
                        'summary': summary, 'costs': _costs(records, accepted, incomplete_telemetry=any(w['incomplete_telemetry'] for w in workflows)), 'workflows': workflows, 'findings': findings})
    return {'schema_version': 1, 'input': diagnostics, 'cohorts': cohorts,
            'assumptions': ['Only observed events are assessed; missing application executions cannot be detected.',
                            'Acceptance is the latest boolean accepted outcome by timestamp, then event_id, within this file.',
                            'Costs are recorded amounts, separated by currency and basis; no provider prices are inferred.',
                            'Total application coverage is unknown even when partial is false; partial marks detected missing costs or incomplete telemetry. Input errors conservatively mark every cohort partial.',
                            'Cost per accepted result includes recorded costs of failed and unaccepted workflows in the cohort.',
                            'Child durations overlap and are never summed into workflow duration.']}


def _ingest(items):
    diagnostics = {'valid_events': 0, 'invalid_lines': 0, 'duplicate_events': 0, 'errors': []}
    seen, events = {}, []
    for line, value, error in items:
        try:
            if error:
                raise ValueError(error)
            validate_event(value)
        except (ValueError, TypeError) as exc:
            diagnostics['invalid_lines'] += 1
            diagnostics['errors'].append({'line': line, 'message': str(exc)})
            continue
        event_id = value['event_id']
        if event_id in seen:
            diagnostics['duplicate_events'] += 1
            if seen[event_id] != value:
                diagnostics['errors'].append({'line': line, 'message': 'Conflicting duplicate event_id; first valid record retained.'})
            continue
        seen[event_id] = value
        events.append(value)
        diagnostics['valid_events'] += 1
    return _report(events, diagnostics)


def assess_events(events: Iterable[dict]) -> dict:
    """Validate and assess event dictionaries, retaining first valid event per ID."""
    return _ingest((line, event, None) for line, event in enumerate(events, 1))


def assess_file(path: str | Path) -> dict:
    """Read JSONL; isolate malformed records and report their one-based line numbers."""
    def records():
        with Path(path).open('rb') as source:
            for line, raw in enumerate(source, 1):
                try:
                    event = json.loads(raw.decode('utf-8'))
                except (ValueError, UnicodeError, RecursionError) as exc:
                    yield line, None, str(exc)
                else:
                    yield line, event, None
    return _ingest(records())


def _duration(milliseconds):
    if milliseconds is None:
        return 'duration unavailable'
    if 0 < milliseconds < 1:
        return '<1 ms'
    if milliseconds < 1000:
        return f'{milliseconds:.0f} ms'
    return f'{milliseconds / 1000:.2f} s'


def format_text(report: dict, detail: bool = False) -> str:
    """Render an actionable summary, with optional workflow trees and evidence."""
    info = report['input']
    lines = ['TraceWorth local assessment (observed telemetry only)',
             f"Events: {info['valid_events']} valid, {info['duplicate_events']} duplicates, {info['invalid_lines']} invalid"]
    if not report['cohorts']:
        lines.append('\nNo usable telemetry to assess.')
        if info['invalid_lines']:
            lines.append('Check the input errors below and export valid version 1 JSONL events.')
        else:
            lines.append('The file is empty. Record a workflow with the Python SDK or generate a synthetic demo.')
        lines.extend(['Try: python -m traceworth demo --output new-demo.jsonl',
                      'Then: python -m traceworth assess new-demo.jsonl'])
    for error in info['errors'][:10 if not detail else None]:
        lines.append(f"Input line {error['line']}: {error['message']}")
    if not detail and len(info['errors']) > 10:
        lines.append('Additional input errors omitted; use --detail or --format json to inspect all errors.')
    for cohort in report['cohorts']:
        lines.append(f"\n{cohort['application_id']} / {cohort['environment']} / {cohort['configuration_id'] or 'unversioned'}")
        summary = cohort['summary']
        lines.append(f"{summary['workflows']} workflows; {summary['accepted_workflows']} accepted; {summary['failed_steps']} failed steps; {summary['retry_steps']} retries")
        lines.append('Findings:')
        if not cohort['findings']:
            lines.append('  No findings in the observed telemetry.')
        for finding in cohort['findings']:
            lines.append(f"  - {finding['message']} ({len(finding['evidence'])} evidence records)")
            if detail:
                lines.append(f"    Evidence: {', '.join(finding['evidence'])}")
        lines.append(f"Workflow statuses: {summary['completed_workflows']} completed, {summary['failed_workflows']} failed, {summary['cancelled_workflows']} cancelled")
        lines.append(f"Acceptance recorded for {summary['outcome_workflows']}/{summary['workflows']} workflows; other outcomes are unknown.")
        lines.append(f"Priced observed usage: {summary['known_cost_events']}/{summary['usage_events']} records")
        if not cohort['costs']:
            lines.append('Recorded cost: unavailable (no priced usage records).')
        for cost in cohort['costs']:
            per_result = cost['cost_per_accepted_result']
            per_result = per_result + ' ' + cost['currency'] if per_result is not None else 'unavailable (no accepted workflows)'
            coverage = 'partial: detected missing cost or telemetry' if cost['partial'] else 'no detected cost gaps; total capture remains unknown'
            lines.append(f"Recorded cost: {cost['amount']} {cost['currency']} ({cost['cost_basis']}); {coverage}")
            lines.append(f"  Cost per accepted result: {per_result}")
        groups = defaultdict(lambda: defaultdict(list))
        for workflow in cohort['workflows']:
            for usage in workflow['usage']:
                groups[(usage['provider'], usage['model_or_service'])][usage['unit']].append(usage['value'])
        if groups:
            lines.append('Observed usage quantities (each unit reported separately):')
            for (provider, service), units in sorted(groups.items()):
                quantities = ', '.join(f'{unit}: {_sum(values)}' for unit, values in sorted(units.items()))
                lines.append(f'  {provider} / {service}: {quantities}')
        else:
            lines.append('Usage quantities: none recorded. Add explicit usage recording to the instrumented operations.')
        lines.append(f"Observed: {cohort['observed_time_range']['start']} to {cohort['observed_time_range']['end']}")
        if detail:
            lines.append(f"Acceptance cutoff: {cohort['acceptance_cutoff_at']} (all supplied records)")
            for workflow in cohort['workflows']:
                outcome = 'accepted' if workflow['accepted'] is True else 'not accepted' if workflow['accepted'] is False else 'acceptance unknown'
                lines.append(f"  Workflow {workflow['workflow_id']}: {workflow['status']}, {_duration(workflow['duration_ms'])}, {outcome}")
                for step in workflow['steps']:
                    indent = '    ' + '  ' * min(step['depth'], 30)
                    annotations = '; missing parent' if step['orphan'] else '; cyclic parent' if step['cycle'] else ''
                    lines.append(f"{indent}{step['name']}: {step['status']}, attempt {step['attempt_number']}, {_duration(step['duration_ms'])}{annotations}")
                    lines.append(f"{indent}  Step {step['step_id']}; parent {step['parent_step_id'] or 'root'}")
                    for cost in step['costs']:
                        lines.append(f"{indent}  Direct cost: {cost['amount']} {cost['currency']} ({cost['cost_basis']})")
    if detail:
        lines.extend('\nAssumption: ' + item for item in report['assumptions'])
    else:
        lines.extend(['\nCoverage: only recorded events are assessed; total application capture is unknown.',
                      'Use --detail for workflow trees and evidence IDs, or --format json for the full report.'])
    return '\n'.join(lines) + '\n'
