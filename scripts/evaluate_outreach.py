"""Evaluate contact resolution against a separate answer key; no external calls.

Run from the repository: python scripts/evaluate_outreach.py
This is a fixture benchmark. It is not Nano timing, live lookup or email delivery.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.service import OutreachService


def evaluate():
    answer_key = json.loads((ROOT / 'data/outreach_answer_key.json').read_text())
    mailbox = os.environ.get('AFTERWORD_EVALUATION_MAILBOX', '').strip().lower()
    with tempfile.TemporaryDirectory(prefix='afterword-resolution-') as temporary:
        service = OutreachService(Path(temporary) / 'evaluation.sqlite3', ROOT / 'data', selector=lambda *_: None)
        if mailbox:
            service.set_mailbox(mailbox, True)
        correct = proposed = resolved = deliverable = 0
        tiers = dict.fromkeys(('records', 'directory', 'lookup', 'none'), 0)
        rows = []
        for finding_id, expected in answer_key['findings'].items():
            expected_emails = list(expected['emails'])
            expected_tier = expected['tier']
            if mailbox and expected.get('demo_aliases'):
                local, domain = mailbox.split('@')
                expected_emails += [local.split('+')[0]+'+'+alias+'@'+domain if domain in {'gmail.com','googlemail.com'} else mailbox for alias in expected['demo_aliases']]
                expected_emails = list(dict.fromkeys(expected_emails))
                if expected_tier == 'none':
                    expected_tier = 'directory'
            result = service.resolve(finding_id)
            candidates = result['candidates']
            selected_tier = result['selected']['source_kind'] if result['selected'] else 'none'
            tiers[selected_tier] += 1
            addresses = [channel['value'] for candidate in candidates for channel in candidate['channels'] if channel['kind'] == 'email']
            correct += sum(address in expected_emails for address in addresses)
            proposed += len(addresses)
            resolved += bool(addresses)
            deliverable += any(candidate.get('deliverable') for candidate in candidates)
            row_ok = selected_tier == expected_tier and set(addresses) == set(expected_emails)
            rows.append({'finding_id': finding_id, 'selected_tier': selected_tier, 'proposed_count': len(addresses), 'matches_answer_key': row_ok})
        # Fixed synthetic family fields, no model/network request or email handoff.
        fields = {'writer_name':'Priya Rao','writer_phone':'+1 408 555 0100','relationship':'daughter; authority not yet confirmed','date_of_death':'2026-08-01'}
        disclosure_rows = []
        for template_id in ('policy_information','account_status','cancel_service','balance_confirmation','request_records'):
            draft = service.draft({'finding_id':'insurance','template_id':template_id,'fields':fields,'recipient':mailbox or 'claims@cedar-life.example'})
            review = service.review(draft['id'])
            disclosure_rows.append({'template_id':template_id,'personal_field_categories':len(review['disclosed_fields']),'body_words':len(draft['body'].split()),'body_characters':len(draft['body'])})
        blocked_cases = []
        for label, text in [('Social Security number','SSN: 111-22-3333'),('Full account or policy number','Account number: 123456789012'),('Date of birth','Date of birth: January 1, 1960')]:
            service.edit(draft['id'], {'body':draft['body']+'\n'+text})
            review = service.review(draft['id'])
            blocked_cases.append({'category':label,'blocked':label in review['blocked_fields'] and not review['can_handoff']})
        events = service.repo.list('events')
        service.repo.connection.close()
    result = {
        'scope': 'Deterministic fictional fixtures; approved inbox configured in temporary evaluation workspace' if mailbox else 'Deterministic fictional fixtures; no configured demo inbox',
        'evaluated_at': datetime.now(timezone.utc).isoformat(),
        'execution_mode': 'CPU fixture evaluation with model transport disabled; not a hardware benchmark',
        'answer_key_version': answer_key['version'],
        'findings_evaluated': len(rows),
        'resolution_by_tier': tiers,
        'contact_resolution_rate': resolved / len(rows),
        'deliverable_contact_rate': deliverable / len(rows),
        'proposed_email_count': proposed,
        'correct_proposed_email_count': correct,
        'contact_precision': correct / proposed if proposed else None,
        'actual_external_lookup_count': len([event for event in events if event.get('kind') == 'escalation' and event.get('task_type') == 'provider_lookup' and event.get('status') == 'started']),
        'disclosure_samples': disclosure_rows,
        'average_personal_field_categories_in_template_reviews': sum(row['personal_field_categories'] for row in disclosure_rows)/len(disclosure_rows),
        'blocked_disclosure_cases': blocked_cases,
        'nano_end_to_end_seconds': None,
        'manual_baseline_seconds': None,
        'email_delivery_verified': False,
        'cases': rows,
    }
    print(json.dumps(result, indent=2))
    if not all(row['matches_answer_key'] for row in rows):
        raise SystemExit('Contact resolution differs from the independent fixture answer key.')
    if not all(row['blocked'] for row in blocked_cases):
        raise SystemExit('A prohibited disclosure passed review.')
    return result


if __name__ == '__main__':
    evaluate()
