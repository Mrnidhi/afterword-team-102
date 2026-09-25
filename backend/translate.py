"""Protected-token handling for on-device translation.

Amounts, dates, account numbers, names and [PLACEHOLDERS] must reach the
provider exactly as written. Before text goes to the LLM, each one is swapped
for a numbered sentinel; after translation the sentinels are checked and
swapped back. This is enforced in code, not requested in the prompt.
"""
import re
from dataclasses import dataclass

# Phase 0 may switch this to an ASCII form if the model mangles ⟦ ⟧.
SENTINEL = '⟦T{n}⟧'
SENTINEL_RE = re.compile(r'⟦T(\d+)⟧')

# Exact-match names from the demo archive. No NER: a missed name is only
# translated, but a false match could freeze ordinary words.
PROVIDER_NAMES = [
    'Cedar Life — policy services', 'Cedar Clinic — billing team', 'Valley Storage — customer team',
    'Cedar Life', 'Cedar Clinic', 'Valley Storage', 'Harbor Gym', 'Streamly',
]
PERSON_NAMES = ['Arun Rao', 'Priya Rao', 'Maya Rao']

MONTH = (r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?'
         r'|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)')

def _names(names):
    return re.compile('|'.join(re.escape(n) for n in sorted(names, key=len, reverse=True)))

# Listed in priority order: on an equal-length overlap the earlier kind wins.
PATTERNS = [
    ('placeholder', re.compile(r'\[[A-Z][A-Z0-9 _-]*\]')),
    ('provider', _names(PROVIDER_NAMES)),
    ('person', _names(PERSON_NAMES)),
    ('date', re.compile(
        rf'\b{MONTH}\.? \d{{1,2}}(?:st|nd|rd|th)?(?:, \d{{4}})?\b'   # September 10, 2026 / Sep 3
        rf'|\b\d{{1,2}} {MONTH}(?: \d{{4}})?\b'                       # 10 September 2026
        r'|\b\d{4}-\d{2}-\d{2}\b'                                     # 2026-09-10
        r'|\b\d{1,2}/\d{1,2}/\d{2,4}\b'                               # 09/10/2026
        r'|\b(?:19|20)\d{2}\b')),                                     # 2019
    ('amount', re.compile(
        r'[$€£₹]\s?\d[\d,]*(?:\.\d+)?'
        r'|\b(?:USD|EUR|GBP|INR|Rs\.?)\s?\d[\d,]*(?:\.\d+)?')),
    ('account', re.compile(r'(?<![\w-])[A-Za-z]{0,6}[-#]?\d[\dA-Za-z-]*(?![\w-])')),
]
KIND_ORDER = {kind: i for i, (kind, _) in enumerate(PATTERNS)}


@dataclass(frozen=True)
class Token:
    sentinel: str
    kind: str
    value: str


def _is_account(value):
    # Short numbers ("12 months") are ordinary text; identifiers carry 4+ digits.
    return sum(c.isdigit() for c in value) >= 4


def protect(text):
    """Return (masked_text, tokens). Each occurrence gets its own sentinel."""
    matches = []
    for kind, pattern in PATTERNS:
        for m in pattern.finditer(text):
            if kind == 'account' and not _is_account(m.group()):
                continue
            matches.append((m.start(), m.end(), kind))
    # Longest match first, then kind priority; drop anything overlapping a kept match.
    matches.sort(key=lambda m: (m[0] - m[1], KIND_ORDER[m[2]], m[0]))
    kept = []
    for start, end, kind in matches:
        if all(end <= s or start >= e for s, e, _ in kept):
            kept.append((start, end, kind))
    kept.sort()

    out, tokens, pos = [], [], 0
    for n, (start, end, kind) in enumerate(kept, 1):
        sentinel = SENTINEL.format(n=n)
        out += [text[pos:start], sentinel]
        tokens.append(Token(sentinel, kind, text[start:end]))
        pos = end
    out.append(text[pos:])
    return ''.join(out), tokens


def check(translated, tokens):
    """Return a list of problems; empty means every token survived exactly once."""
    found = [SENTINEL.format(n=n) for n in SENTINEL_RE.findall(translated)]
    expected = {t.sentinel for t in tokens}
    problems = [f'missing {t.sentinel} ({t.kind}: {t.value})' for t in tokens if t.sentinel not in found]
    problems += [f'duplicated {s}' for s in sorted(expected) if found.count(s) > 1]
    problems += [f'unexpected {s}' for s in sorted(set(found) - expected)]
    return problems


def restore(translated, tokens):
    """Substitute original values back. Callers must run check() first.

    A sentinel-looking match that isn't one of ours -- the model inventing an
    extra ⟦Tn⟧ that was never in the input, a known failure mode phase 0
    flagged -- has no real value to restore. It used to be echoed back
    verbatim, which meant a fabricated sentinel could leak into the text a
    family actually reads as raw, meaningless bracket syntax; check() already
    flags this case as a problem, so restore()'s job is to keep it out of
    what anyone reads, not just report it. Found via metrics.py surfacing a
    live '... discarded. ⟦T1⟧' case in a Hindi task instruction with nothing
    to protect in the first place -- see MULTILINGUAL-PLAN.md's gap-
    resolution notes.
    """
    values = {t.sentinel: t.value for t in tokens}
    restored = SENTINEL_RE.sub(lambda m: values.get(m.group(), ''), translated)
    return re.sub(r'[ \t]{2,}', ' ', restored).strip()
