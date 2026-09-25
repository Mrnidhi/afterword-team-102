#!/usr/bin/env python3
"""Capture a live rehearsal's local evidence; never create, search, authorize or send."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.readiness import loopback_url
from backend.router import request_json

CHECKS = ('hardware_identity', 'local_model', 'scan_ocr', 'vision_contacts', 'lookup_approval', 'gmail_oauth', 'gmail_draft', 'attachments', 'human_send', 'gmail_reply', 'disconnect')


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def report_path(value):
    path = Path(value).expanduser().absolute()
    resolved = path.resolve()
    if path.is_symlink() or resolved == ROOT or ROOT in resolved.parents:
        raise ValueError('Keep live rehearsal reports outside the public repository.')
    return path


def read_report(path):
    if path.stat().st_size > 10_000_000:
        raise ValueError('Rehearsal report exceeds the size limit.')
    report = json.loads(path.read_text())
    if report.get('schema_version') != 1 or report.get('evidence_level') != 'live_rehearsal_capture':
        raise ValueError('This is not a supported live rehearsal report.')
    return report


def write_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.rehearsal-', dir=str(path.parent))
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump(report, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def capture(base_url, transport=request_json):
    if not loopback_url(base_url):
        raise ValueError('The rehearsal only reads a loopback HTTP Afterword service.')
    base = base_url.rstrip('/')
    return {'readiness': transport('GET', base + '/integrations/readiness'), 'audit': transport('GET', base + '/integrations/rehearsal-evidence')}


def artifact(path):
    source = Path(path).expanduser()
    if not source.is_file() or source.is_symlink():
        raise ValueError('Use a regular local evidence file.')
    sha = hashlib.sha256()
    size = 0
    with source.open('rb') as handle:
        for block in iter(lambda: handle.read(1_048_576), b''):
            sha.update(block)
            size += len(block)
            if size > 100_000_000:
                raise ValueError('Evidence file exceeds 100 MB.')
    # File contents are hashed, never copied into the report or uploaded.
    return {'sha256': sha.hexdigest(), 'bytes': size, 'contents_copied': False}


def summarize(report, final):
    earlier = {row['event_id'] for row in report['initial']['audit']['records']}
    rows = [row for row in final['audit']['records'] if row['event_id'] not in earlier]
    durations = [row['finding_to_review_seconds'] for row in rows if row.get('kind') == 'draft_reviewed' and row.get('can_handoff') and row.get('finding_to_review_seconds') is not None]
    lookups = [row for row in rows if row.get('kind') == 'escalation' and row.get('status') == 'started']
    generated = [row for row in rows if row.get('kind') == 'draft_created']
    draft_created = [row for row in rows if row.get('kind') == 'gmail_draft_created']
    manual = [row['elapsed_seconds'] for row in report.get('manual_baselines', [])]
    latest_observations = {row['check']: row for row in report.get('observations', [])}
    gates = {
        'guarded_local_model_observed': any(row.get('generation_mode') == 'local_model_guarded' for row in generated),
        'scan_ocr_completed': any(row['kind'] == 'scan_ocr_completed' for row in rows),
        'scan_ocr_reviewed': any(row['kind'] == 'scan_ocr_reviewed' for row in rows),
        'vision_contacts_observed': any(row['kind'] == 'scan_contacts_ingested' and row.get('verbatim_gate') and row.get('contact_count', 0) > 0 for row in rows),
        'lookup_attempt_observed': bool(lookups),
        'every_lookup_minimized': all(row.get('payload_minimization_verified') is True for row in lookups) if lookups else None,
        'gmail_oauth_observed': any(row['kind'] == 'gmail_connected' for row in rows),
        'gmail_draft_observed': bool(draft_created),
        'attachment_draft_observed': any(row.get('attachment_count', 0) > 0 for row in draft_created),
        'human_marked_sent': any(row['kind'] == 'manually_marked_sent' for row in rows),
        'incoming_reply_correlated': any(row['kind'] == 'gmail_reply_checked' and row.get('sent_verified') and row.get('replied') for row in rows),
        'disconnect_observed': any(row['kind'] == 'gmail_disconnected' for row in rows),
        'timed_workflow_observed': bool(durations),
        'manual_baseline_recorded': bool(manual),
    }
    return {'observed_local_events': rows, 'gates': gates, 'finding_to_review_seconds': durations, 'finding_to_review_median_seconds': statistics.median(durations) if durations else None, 'manual_baseline_seconds': manual, 'manual_baseline_median_seconds': statistics.median(manual) if manual else None, 'missing_or_failed_human_checks': [name for name in CHECKS if latest_observations.get(name, {}).get('outcome') != 'observed_pass'], 'hardware_identity': 'operator claim requiring independent review', 'acceptance_complete': False, 'acceptance_note': 'This capture does not certify external service authenticity, device identity or accuracy. Review the hashed artifacts and actual provider/runtime observations before signing off.'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    begin = sub.add_parser('begin', help='Record initial safe readiness and audit snapshot from the local service.')
    begin.add_argument('--report', required=True)
    begin.add_argument('--api-url', default='http://127.0.0.1:4173')
    begin.add_argument('--environment', choices=['hp-zgx-nano', 'other-local-device'], required=True)
    begin.add_argument('--operator', required=True, help='Pseudonymous participant ID; do not enter a name or email.')
    begin.add_argument('--revision', required=True, help='Git revision being rehearsed.')
    record = sub.add_parser('record', help='Record an actual human observation and local artifact hash.')
    record.add_argument('--report', required=True)
    record.add_argument('--check', choices=CHECKS, required=True)
    record.add_argument('--outcome', choices=['observed_pass', 'observed_fail', 'blocked'], required=True)
    record.add_argument('--evidence', help='Local screenshot/log path; only its hash and size are saved.')
    baseline = sub.add_parser('manual-baseline', help='Record a measured human comparison; no invented default duration.')
    baseline.add_argument('--report', required=True)
    baseline.add_argument('--seconds', type=float, required=True)
    baseline.add_argument('--evidence', required=True)
    finish = sub.add_parser('finish', help='Read final local audit and report only new events and measured durations.')
    finish.add_argument('--report', required=True)
    args = parser.parse_args(argv)
    target = report_path(args.report)
    if args.command == 'begin':
        if target.exists():
            raise ValueError('Choose a new report path; existing rehearsal evidence is not overwritten.')
        import re
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,60}', args.operator) or not re.fullmatch(r'[A-Za-z0-9._/-]{1,100}', args.revision):
            raise ValueError('Use a simple participant ID and source revision; no names or credentials.')
        report = {'schema_version': 1, 'evidence_level': 'live_rehearsal_capture', 'started_at': timestamp(), 'operator_id': args.operator, 'source_revision': args.revision, 'environment_claim': args.environment, 'machine_architecture': platform.machine(), 'hardware_verified': False, 'api_url': args.api_url, 'initial': capture(args.api_url), 'observations': [], 'manual_baselines': [], 'external_actions_performed_by_script': 0, 'complete': False}
    else:
        report = read_report(target)
        if report.get('complete'):
            raise ValueError('This capture was finalized; start a new run for additional evidence.')
        if args.command == 'record':
            if args.outcome == 'observed_pass' and not args.evidence:
                raise ValueError('A passing observation requires a local evidence artifact.')
            report['observations'].append({'check': args.check, 'outcome': args.outcome, 'recorded_at': timestamp(), 'source': 'operator_observation', 'artifact': artifact(args.evidence) if args.evidence else None})
        elif args.command == 'manual-baseline':
            import math
            if not math.isfinite(args.seconds) or not 0 < args.seconds <= 86400:
                raise ValueError('Enter an actual positive measured duration no greater than one day.')
            report['manual_baselines'].append({'elapsed_seconds': args.seconds, 'recorded_at': timestamp(), 'source': 'operator_measured_stopwatch', 'artifact': artifact(args.evidence)})
        else:
            final = capture(report['api_url'])
            report.update(finished_at=timestamp(), final=final, summary=summarize(report, final), complete=True)
    write_report(target, report)
    print(json.dumps({'report_written': True, 'command': args.command, 'capture_finalized': report['complete'], 'acceptance_complete': False, 'external_actions_performed': 0}))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        sys.exit(1)
