"""Evaluate the daily drain against data/drain_answer_key.json; no external calls or model.

Reports rate accuracy, bucket precision, keep-for-now harms (separately, because
recommending that insurance be cancelled is a harm, not a miss), coverage and
evidence completeness. Exits non-zero on any harm or mismatch.
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.buckets import BucketClassifier  # noqa: E402
from backend.drain import DIVISORS, RULES_PATH, compute_drain  # noqa: E402


def evaluate():
    archive = json.loads((ROOT / 'data/demo_archive.json').read_text())
    directory = {p['provider_id']: p for p in json.loads((ROOT / 'data/providers_directory.json').read_text())['providers']}
    key = json.loads((ROOT / 'data/drain_answer_key.json').read_text())
    classifier = BucketClassifier.from_file(RULES_PATH, model=None)
    result = compute_drain(archive['documents'], archive['findings'], directory, classifier)
    texts = {d['id']: d['text'] for d in archive['documents']}
    lines = result['confirmed'] + result['possible']

    rows = []
    for expected in key['archive_charges']:
        found = [l for l in lines if l['provider_id'] == expected['provider_id'] and math.isclose(l['amount'], expected['amount'])]
        line = found[0] if len(found) == 1 else None
        rows.append({'provider_id': expected['provider_id'], 'produced_line': line is not None,
                     'rate_correct': bool(line) and line['frequency'] == expected['frequency'] and line['tier'] == expected['tier'],
                     'bucket_correct': bool(line) and line['bucket'] == expected['bucket']})
    expected_daily = math.fsum(c['amount'] / DIVISORS[c['frequency']] for c in key['archive_charges'] if c['tier'] == 'confirmed' and c['bucket'] == 'stoppable')
    keyed = {(c['provider_id'], c['amount']) for c in key['archive_charges']}
    unexpected = [l['label'] for l in lines if (l['provider_id'], l['amount']) not in keyed]
    verbatim = [l for l in lines if l['evidence'] and all(texts.get(e['doc_id'], '')[e['start']:e['end']] == e['quote'] for e in l['evidence'])]

    cases = [(case, classifier.classify(case['label'], case.get('provider_id'))['bucket']) for case in key['classifier_cases']]
    keep_cases = [(case, got) for case, got in cases if case['bucket'] == 'keep_for_now']
    archive_keep = [c for c in key['archive_charges'] if c['bucket'] == 'keep_for_now']
    report = {
        'answer_key_version': key['version'],
        'rate_accuracy': {'computed_daily': result['daily'], 'expected_daily': expected_daily,
                          'difference': result['daily'] - expected_daily,
                          'lines_correct': sum(r['rate_correct'] for r in rows), 'lines_expected': len(rows)},
        'bucket_precision': {'archive_correct': sum(r['bucket_correct'] for r in rows), 'archive_lines': len(rows),
                             'synthetic_correct': sum(case['bucket'] == got for case, got in cases), 'synthetic_cases': len(cases)},
        'keep_for_now_harms': {
            'archive': sum(1 for c in archive_keep for l in lines if l['provider_id'] == c['provider_id'] and l['bucket'] == 'stoppable'),
            'archive_keep_for_now_charges': len(archive_keep),
            'synthetic': sum(got == 'stoppable' for _, got in keep_cases),
            'synthetic_keep_for_now_cases': len(keep_cases),
        },
        'coverage': {'charges_with_a_line': sum(r['produced_line'] for r in rows), 'planted_charges': len(rows)},
        'unexpected_lines': unexpected,
        'evidence_completeness': {'lines_with_verbatim_quote': len(verbatim), 'lines': len(lines)},
        'rows': rows,
    }
    return report


def failures(report):
    problems = []
    if not math.isclose(report['rate_accuracy']['difference'], 0, abs_tol=1e-9):
        problems.append('headline differs from the answer key')
    if report['rate_accuracy']['lines_correct'] != report['rate_accuracy']['lines_expected']:
        problems.append('a line has the wrong frequency or tier')
    b = report['bucket_precision']
    if b['archive_correct'] != b['archive_lines'] or b['synthetic_correct'] != b['synthetic_cases']:
        problems.append('a charge is in the wrong bucket')
    if report['keep_for_now_harms']['archive'] or report['keep_for_now_harms']['synthetic']:
        problems.append('HARM: a keep-for-now charge was sorted as stoppable')
    if report['coverage']['charges_with_a_line'] != report['coverage']['planted_charges'] or report['unexpected_lines']:
        problems.append('coverage differs from the answer key')
    e = report['evidence_completeness']
    if e['lines_with_verbatim_quote'] != e['lines']:
        problems.append('a line lacks a verbatim quote')
    return problems


if __name__ == '__main__':
    report = evaluate()
    print(json.dumps(report, indent=2))
    problems = failures(report)
    if problems:
        raise SystemExit('Drain evaluation failed: ' + '; '.join(problems))
