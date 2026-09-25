"""Phase 6 metrics: round-trip similarity, protected-token preservation,
cold latency and language coverage over the actual demo archive.

Run against a live backend (needs the prewarm to have finished for the
latency numbers to mean anything — cold latency is measured explicitly via
bypass_cache, independent of whatever's already cached):

  cd backend && /home/hp24/miniforge3/envs/zgx/bin/python metrics.py

Writes backend/metrics.json and prints the table below. Numbers are read
straight from live /translate-equivalent calls (via do_translate, in-process
— no HTTP hop needed since this runs alongside app.py's own code), so they
reflect this exact model/prompt/threshold, not a fixture.
"""
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app as backend  # noqa: E402
from demo_content import LANGS, demo_texts  # noqa: E402
from translate import protect  # noqa: E402


def collect():
    texts = demo_texts()
    rows = []
    for kind, content_id, text in texts:
        token_count = len(protect(text)[1])
        for lang in LANGS:
            r = backend.do_translate(text, lang, kind)  # warm: reads the prewarmed cache
            rows.append({'kind': kind, 'id': content_id, 'lang': lang, 'text_len': len(text),
                         'token_count': token_count, 'round_trip_score': r.round_trip_score,
                         'protected_tokens_ok': r.protected_tokens_ok, 'low_confidence': r.low_confidence,
                         'cached': r.cached})
    return texts, rows


def cold_latency(texts):
    """Bypasses the cache so these numbers are genuine cold Nano latency, not
    the prewarmed instant-hit path — matches what the very first user to open
    a given finding in a given language would actually wait for."""
    rows = []
    for kind, content_id, text in texts:
        for lang in LANGS:
            t0 = time.perf_counter()
            backend.do_translate(text, lang, kind, bypass_cache=True)
            rows.append({'kind': kind, 'lang': lang, 'ms': round((time.perf_counter() - t0) * 1000)})
    return rows


def summarize(rows, latency_rows):
    print('== Round-trip similarity (median / worst, per language) ==')
    similarity = {}
    for lang in LANGS:
        scores = [r['round_trip_score'] for r in rows if r['lang'] == lang]
        similarity[lang] = {'median': round(statistics.median(scores), 4), 'worst': round(min(scores), 4),
                             'n': len(scores)}
        print(f"  {lang}: median {similarity[lang]['median']}  worst {similarity[lang]['worst']}  (n={len(scores)})")

    print('\n== Protected-token preservation ==')
    # Conservative attribution: if a response's protected_tokens_ok is false,
    # every token in that text counts as not preserved — we don't know the
    # exact partial count, and guessing high would overclaim.
    total_tokens = sum(r['token_count'] for r in rows)
    preserved = sum(r['token_count'] for r in rows if r['protected_tokens_ok'])
    print(f'  {preserved} of {total_tokens} amounts, dates, names and policy numbers preserved '
          f'({100 * preserved / total_tokens:.1f}%)')
    failures = [r for r in rows if not r['protected_tokens_ok']]
    if failures:
        print(f'  {len(failures)} translation(s) had a token problem: ' +
              ', '.join(f"{r['kind']}/{r['id']}/{r['lang']}" for r in failures))

    print('\n== Latency (cold, bypassing cache) ==')
    latency = {}
    for kind in sorted({r['kind'] for r in latency_rows}):
        latency[kind] = {}
        row = []
        for lang in LANGS:
            ms = [r['ms'] for r in latency_rows if r['kind'] == kind and r['lang'] == lang]
            med = round(statistics.median(ms))
            latency[kind][lang] = med
            row.append(f'{lang} {med/1000:5.1f}s')
        print(f'  {kind:11}', '  '.join(row))

    print('\n== Coverage ==')
    by_content = {}
    for r in rows:
        by_content.setdefault((r['kind'], r['id']), set()).add(r['lang'])
    full = sum(1 for langs in by_content.values() if langs == set(LANGS))
    coverage = full / len(by_content)
    print(f'  {full} of {len(by_content)} demo items available in all {len(LANGS)} languages ({coverage:.0%})')
    print('  (English is the source text itself — always available — so "all languages" here means es+vi+hi.)')

    print('\n== Low-confidence flags ==')
    flagged = [r for r in rows if r['low_confidence']]
    print(f'  {len(flagged)} of {len(rows)} translations flagged "machine translation — please check"')
    for r in flagged:
        print(f"    {r['kind']}/{r['id']}/{r['lang']}  score {r['round_trip_score']:.3f}")

    print('\n== Human check ==')
    print('  Not run. Optional per the plan: a native speaker rating 10 samples, reported as n,')
    print('  not a formal evaluation. No native reviewer was available in this environment.')

    return {'round_trip_similarity': similarity, 'protected_tokens': {'preserved': preserved, 'total': total_tokens},
            'latency_ms_median': latency, 'coverage': coverage, 'low_confidence_count': len(flagged),
            'low_confidence_items': [f"{r['kind']}/{r['id']}/{r['lang']}" for r in flagged],
            'human_check': None}


def main():
    backend.init_db()  # safe if the live server already did this — CREATE TABLE IF NOT EXISTS
    print('Collecting round-trip / token metrics (reads the prewarmed cache where available)...')
    texts, rows = collect()
    print('Measuring cold latency (bypasses cache — this genuinely re-translates everything)...')
    latency_rows = cold_latency(texts)
    summary = summarize(rows, latency_rows)
    out = Path(__file__).resolve().parent / 'metrics.json'
    out.write_text(json.dumps({'summary': summary, 'rows': rows, 'latency_rows': latency_rows}, indent=2))
    print(f'\nWrote {out}')


if __name__ == '__main__':
    main()
