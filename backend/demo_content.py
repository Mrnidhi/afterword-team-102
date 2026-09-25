"""Extracts the demo archive's translatable text straight from dist/pages.js,
so the prewarm (app.py), the metrics script and the phase 0 spike can never
drift from what the frontend actually sends to /translate.

The letter body is extracted for kind="letter". The subject line is
extracted separately as kind="instruction" (short admin text, translated only
for the family's reading column via dist/i18n.js's translatedInline — never
combined with the body, and never what actually gets sent). Phase 5 had
originally left the subject untranslated because re-splitting one combined
subject+body translation back into two fields proved fragile; this sidesteps
that by never combining them in the first place — see MULTILINGUAL-PLAN.md's
gap-resolution notes.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LANGS = {'es': 'Spanish', 'vi': 'Vietnamese', 'hi': 'Hindi'}


def demo_texts():
    """Returns [(kind, id, text), ...] — 3 findings + 3 letter bodies + 3
    letter subjects + 4 distinct task instructions (7 tasks share just 4
    texts; see openTask in pages.js)."""
    src = (ROOT / 'dist/pages.js').read_text()
    unq = lambda s: s.replace("\\'", "'").replace('\\n', '\n')
    field = lambda block, key: unq(re.search(rf"\b{key}:'((?:[^'\\]|\\.)*)'", block).group(1))
    texts = []

    findings = src[src.index('const findings='):src.index('function evidencePage')]
    for fid in ('insurance', 'medical', 'storage'):
        block = findings[findings.index(fid + ':{'):]
        texts.append(('summary', fid, '\n\n'.join(field(block, k) for k in ('lead', 'known', 'unknown', 'next'))))

    letters = src[src.index('const letterTemplates='):]
    for fid in ('insurance', 'medical', 'storage'):
        block = letters[letters.index(fid + ':{'):]
        texts.append(('letter', fid, field(block, 'body')))
        texts.append(('instruction', f'subject-{fid}', field(block, 'subject')))

    task = src[src.index('function openTask'):src.index('function documentsPage')]
    for i, s in enumerate(re.findall(r"\?'([A-Z][^'<]{40,})'|:'([A-Z][^'<]{40,})'", task)):
        texts.append(('instruction', f'task{i}', next(x for x in s if x)))

    return texts


if __name__ == '__main__':
    for kind, id_, text in demo_texts():
        print(f'{kind:11} {id_:9} {len(text):4} chars  {text[:70]!r}')
