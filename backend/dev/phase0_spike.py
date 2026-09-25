"""Phase 0 spike: can the local models carry this feature?

Measures, over the real demo text in dist/pages.js:
  1. translation latency per language and kind (LLM on :8000)
  2. whether round-trip cosine separates good from bad translations (:8003)
  3. how often each sentinel format survives translation and back-translation

  python3 backend/dev/phase0_spike.py  ->  backend/dev/phase0_results.json
"""
import json
import re
import statistics
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from demo_content import demo_texts  # noqa: E402
from translate import SENTINEL_RE, check, protect, restore  # noqa: E402

LLM = 'http://127.0.0.1:8000/v1'
EMBED = 'http://127.0.0.1:8003/v1'
LANGS = {'es': 'Spanish', 'vi': 'Vietnamese', 'hi': 'Hindi'}
FORMATS = {'unicode': ('⟦T{n}⟧', re.compile(r'⟦T(\d+)⟧')), 'ascii': ('[[T{n}]]', re.compile(r'\[\[T(\d+)\]\]'))}

PROMPT = (
    'You translate short texts for a family dealing with the practical affairs of someone who has died.\n'
    'Translate the user text from English into {language}. Output only the translation.\n'
    'Rules:\n'
    '- Keep every token that looks like {example} exactly as written, once each. Never translate or remove them.\n'
    '- Use plain, respectful, everyday words a twelve-year-old would understand.\n'
    '- Prefer common {language} words over English finance jargon where one exists.\n'
    '- Do not add, remove or explain any facts. Keep the paragraph breaks.'
)
BACK = (
    'Translate the user text from {language} into English. Output only the translation.\n'
    'Keep every token that looks like {example} exactly as written, once each.'
)


def post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {'content-type': 'application/json'})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)


def chat(system, text):
    t0 = time.perf_counter()
    d = post(f'{LLM}/chat/completions', {'messages': [{'role': 'system', 'content': system},
                                                      {'role': 'user', 'content': text}],
                                         'temperature': 0, 'max_tokens': 2048})
    return d['choices'][0]['message']['content'], time.perf_counter() - t0


def cosine(a, b):
    v = [d['embedding'] for d in post(f'{EMBED}/embeddings', {'input': [a, b]})['data']]
    return sum(x * y for x, y in zip(*v))  # vectors are normalized


def to_format(masked, fmt):
    return SENTINEL_RE.sub(lambda m: FORMATS[fmt][0].format(n=m.group(1)), masked)


def from_format(text, fmt):
    return FORMATS[fmt][1].sub(lambda m: f'⟦T{m.group(1)}⟧', text)


def embedding_calibration():
    """Does cosine separate paraphrases from real meaning changes?"""
    base = 'Please confirm whether the payment of $400 was applied to this invoice and send an updated balance.'
    pairs = {
        'paraphrase': [base, 'Could you tell me if the $400 payment went toward this invoice, and send the current balance?'],
        'paraphrase_2': ['Ask the insurer for its current policy and beneficiary information.',
                         'Request the current policy details and beneficiary information from the insurance company.'],
        'meaning_flip': [base, 'Please confirm that the payment of $400 was not applied to this invoice and cancel the balance.'],
        'fact_dropped': [base, 'Please send an updated balance.'],
        'unrelated': [base, 'Arrange a visit to the storage unit before deciding whether to cancel.'],
    }
    return {k: round(cosine(*v), 4) for k, v in pairs.items()}


def main():
    texts = demo_texts()
    print(f'{len(texts)} demo texts; calibrating embeddings...', flush=True)
    results = {'calibration': embedding_calibration(), 'runs': []}
    with urllib.request.urlopen(f'{LLM}/models') as r:
        results['model'] = json.load(r)['data'][0]['id']
    with urllib.request.urlopen(f'{EMBED}/models') as r:
        results['embedding_model'] = json.load(r)['data'][0]['id']
    print('calibration', results['calibration'], flush=True)

    for kind, tid, text in texts:
        masked, tokens = protect(text)
        for code, language in LANGS.items():
            for fmt, (example, _) in FORMATS.items():
                ex = example.format(n=1)
                fwd, s1 = chat(PROMPT.format(language=language, example=ex), to_format(masked, fmt))
                fwd_std = from_format(fwd, fmt)
                back, s2 = chat(BACK.format(language=language, example=ex), to_format(fwd_std, fmt))
                back_std = from_format(back, fmt)
                run = {'kind': kind, 'id': tid, 'lang': code, 'format': fmt, 'tokens': len(tokens),
                       'forward_problems': check(fwd_std, tokens), 'back_problems': check(back_std, tokens),
                       'forward_s': round(s1, 2), 'back_s': round(s2, 2),
                       'score': round(cosine(text, restore(back_std, tokens)), 4),
                       'translation': restore(fwd_std, tokens), 'back_translation': restore(back_std, tokens)}
                results['runs'].append(run)
                print(f"{kind:11} {tid:9} {code} {fmt:7} fwd {s1:5.1f}s score {run['score']:.3f} "
                      f"lost {len(run['forward_problems'])}/{len(run['back_problems'])}", flush=True)
                (ROOT / 'backend/dev/phase0_results.json').write_text(json.dumps(results, ensure_ascii=False, indent=1))
    summarize(results)


def summarize(results):
    runs = results['runs']
    print('\n== sentinel survival (texts with every token intact, forward / after back-translation)')
    for fmt in FORMATS:
        for code in LANGS:
            rs = [r for r in runs if r['format'] == fmt and r['lang'] == code]
            tok = sum(r['tokens'] for r in rs)
            lost = sum(len(r['forward_problems']) for r in rs)
            print(f"  {fmt:7} {code}: fwd {sum(not r['forward_problems'] for r in rs)}/{len(rs)} texts, "
                  f"back {sum(not r['back_problems'] for r in rs)}/{len(rs)}; tokens lost fwd {lost}/{tok}")
    print('\n== round-trip cosine (unicode format)')
    for code in LANGS:
        sc = [r['score'] for r in runs if r['format'] == 'unicode' and r['lang'] == code]
        print(f'  {code}: median {statistics.median(sc):.3f}  worst {min(sc):.3f}')
    print('\n== median forward seconds (unicode format)')
    for kind in ('summary', 'letter', 'instruction'):
        row = [f"{code} {statistics.median([r['forward_s'] for r in runs if r['kind'] == kind and r['lang'] == code and r['format'] == 'unicode']):5.1f}s"
               for code in LANGS]
        print(f'  {kind:11}', '  '.join(row))


if __name__ == '__main__':
    main()
