"""Daily drain: recurring charges still billing the estate, derived only from source evidence.

Charges are read from document text by fixed rules, each with a verbatim quote
and its character offsets. Only confirmed, stoppable charges that the family
hasn't stopped count toward the headline; see docs/DRAIN-COUNTER.md.
"""
import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Optional
from fastapi import HTTPException, Query
from .buckets import BucketClassifier, local_bucket_model
from .models import DateOfDeathRequest, DrainResponse

YEAR_DAYS = 365.25
DIVISORS = {
    'daily': 1,
    'weekly': 7,
    'biweekly': 14,
    'monthly': YEAR_DAYS / 12,
    'quarterly': YEAR_DAYS / 4,
    'yearly': YEAR_DAYS,
}
FREQUENCY_WORDS = {
    'daily': 'daily', 'day': 'daily', 'weekly': 'weekly', 'week': 'weekly', 'biweekly': 'biweekly', 'fortnightly': 'biweekly',
    'monthly': 'monthly', 'month': 'monthly', 'mo': 'monthly', 'quarterly': 'quarterly', 'quarter': 'quarterly',
    'annual': 'yearly', 'annually': 'yearly', 'yearly': 'yearly', 'year': 'yearly', 'yr': 'yearly',
}
# Tolerance, in days, when inferring a frequency from the gap between observed charges.
OBSERVED_TOLERANCE = {'weekly': 2, 'biweekly': 3, 'monthly': 5, 'quarterly': 10, 'yearly': 20}
CONFIDENCE = {'stated': 0.9, 'observed_3': 0.95, 'observed_2': 0.85, 'observed_same_period': 0.7, 'assumed_statement_period': 0.6, 'single_unlabelled': 0.4}
MIN_CONFIDENCE = 0.5
# Safety rules ship with the product, independent of which archive is loaded.
RULES_PATH = Path(__file__).resolve().parent.parent / 'data' / 'charge_buckets.json'

AMOUNT = r'\$\s?(?P<amount>\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+(?:\.\d{2})?)'
STATED = [
    re.compile(r'\b(?P<freq>daily|weekly|biweekly|fortnightly|monthly|quarterly|annual|annually|yearly)\s+(?:charge|fee|payment|premium|subscription|bill|rate|rent|dues)\s*[:\-–]?\s*' + AMOUNT, re.I),
    re.compile(AMOUNT + r'\s*(?:per|a|each|/)\s*(?P<freq>day|week|month|mo|quarter|year|yr)\b', re.I),
]
MONTHS = {m: i for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'], 1)}
TRANSACTION = re.compile(r'^(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?[ \t]+(?P<day>\d{1,2})[ \t]*[·|][ \t]*(?P<name>[^·|\n$]+?)[ \t]*[·|][ \t]*' + AMOUNT + r'(?=[ \t]*$)', re.M)
RECURRING_LABEL = re.compile(r'\brecurring\b', re.I)
CANCELLED = re.compile(r'\b(?:has|have)\s+been\s+(?:cancell?ed|closed|terminated|ended)\b|\bwas\s+(?:cancell?ed|closed|terminated)\b'
                       r'|\bcancell?ation\s+(?:is\s+|has\s+been\s+)?confirmed\b|\bconfirm(?:s|ing)?\s+(?:the\s+|your\s+)?cancell?ation\b', re.I)


def daily_rate(amount, frequency):
    """Unrounded daily rate, or None for one-time and unknown frequencies. Round only for display."""
    divisor = DIVISORS.get(frequency)
    if divisor is None or amount is None:
        return None
    return amount / divisor


def parse_date(value):
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def _amount(value):
    return round(float(value.replace(',', '')), 2)


def _provider_for_name(name, directory):
    wanted = name.strip().lower()
    for provider_id, provider in directory.items():
        if wanted in {provider['display_name'].lower(), *(a.lower() for a in provider.get('aliases', []))}:
            return provider_id
    return None


def _transaction_date(doc_date, month, day):
    if not doc_date:
        return None
    year = doc_date.year - (1 if month > doc_date.month else 0)
    try:
        return date(year, month, day)
    except ValueError:
        return None


def extract_occurrences(documents, directory):
    """Every charge mention with a verbatim quote: stated amount+frequency, or a dated transaction line."""
    found = []
    for doc in documents:
        text = doc.get('text') or ''
        doc_date = parse_date(doc.get('date'))
        provider_id = doc.get('provider_id')
        for pattern in STATED:
            for match in pattern.finditer(text):
                found.append({'provider_id': provider_id, 'label': directory.get(provider_id, {}).get('display_name') or doc.get('title') or 'Unnamed charge',
                              'amount': _amount(match.group('amount')), 'frequency': FREQUENCY_WORDS[match.group('freq').lower()],
                              'date': doc_date, 'recurring_label': True,
                              'evidence': {'doc_id': doc['id'], 'quote': match.group(0), 'start': match.start(), 'end': match.end()}})
        labelled = bool(RECURRING_LABEL.search(text))
        for match in TRANSACTION.finditer(text):
            name = match.group('name').strip()
            found.append({'provider_id': _provider_for_name(name, directory), 'label': name, 'amount': _amount(match.group('amount')), 'frequency': None,
                          'date': _transaction_date(doc_date, MONTHS[match.group('mon').lower()[:3]], int(match.group('day'))),
                          'recurring_label': labelled,
                          'evidence': {'doc_id': doc['id'], 'quote': match.group(0), 'start': match.start(), 'end': match.end()}})
    return found


def _observed_frequency(dates):
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    if not gaps:
        return None
    gap = median(gaps)
    for frequency, tolerance in OBSERVED_TOLERANCE.items():
        if abs(gap - DIVISORS[frequency]) <= tolerance:
            return frequency
    return 'daily' if gap <= 1.5 else None


def merge_occurrences(occurrences, directory):
    """One charge per provider (or label) and amount, so an email and a statement line never double count."""
    groups = {}
    for item in occurrences:
        key = (item['provider_id'] or item['label'].lower(), item['amount'])
        groups.setdefault(key, []).append(item)
    charges = []
    for (identity, amount), items in groups.items():
        items.sort(key=lambda i: (i['date'] or date.min, i['evidence']['start']))
        dates = sorted({i['date'] for i in items if i['date']})
        periods = len({(d.year, d.month) for d in dates})
        stated = [i['frequency'] for i in items if i['frequency']]
        observed = _observed_frequency(dates)
        if stated:
            frequency, basis, confidence = stated[0], 'stated', CONFIDENCE['stated']
        elif observed and periods >= 2:
            frequency, basis, confidence = observed, 'observed', CONFIDENCE['observed_3' if periods >= 3 else 'observed_2']
        elif observed:
            frequency, basis, confidence = observed, 'observed', CONFIDENCE['observed_same_period']
        elif any(i['recurring_label'] for i in items):
            frequency, basis, confidence = 'monthly', 'assumed_statement_period', CONFIDENCE['assumed_statement_period']
        else:
            frequency, basis, confidence = 'unknown', None, CONFIDENCE['single_unlabelled']
        provider_id = items[0]['provider_id']
        label = directory.get(provider_id, {}).get('display_name') or items[0]['label']
        slug = re.sub(r'[^a-z0-9]+', '-', str(identity).lower()).strip('-')
        charges.append({'id': f'charge-{slug}-{round(amount * 100)}', 'provider_id': provider_id, 'label': label, 'amount': amount,
                        'frequency': frequency, 'frequency_basis': basis, 'confidence': confidence, 'periods': periods,
                        'tier': 'confirmed' if basis == 'stated' or (basis == 'observed' and periods >= 2) else 'possible',
                        'last_seen': dates[-1] if dates else None, 'evidence': [i['evidence'] for i in items]})
    return charges


def _finding_for(charge, findings):
    doc_ids = {e['doc_id'] for e in charge['evidence']}
    linked = [f for f in findings if charge['provider_id'] and charge['provider_id'] in (f.get('provider_ids') or [f.get('provider_id')])]
    for finding in linked:
        if doc_ids & set(finding.get('source_ids', [])):
            return finding['id']
    return linked[0]['id'] if linked else None


def _cancellation(charge, documents, directory):
    evidence_docs = {e['doc_id'] for e in charge['evidence']}
    names = [charge['label'].lower(), *(a.lower() for a in directory.get(charge['provider_id'], {}).get('aliases', []))]
    for doc in documents:
        if doc['id'] in evidence_docs:
            continue
        text = doc.get('text') or ''
        about = (charge['provider_id'] and doc.get('provider_id') == charge['provider_id']) or any(n in text.lower() for n in names)
        doc_date = parse_date(doc.get('date'))
        if about and (doc_date is None or charge['last_seen'] is None or doc_date >= charge['last_seen']):
            match = CANCELLED.search(text)
            if match:
                return {'doc_id': doc['id'], 'quote': match.group(0), 'start': match.start(), 'end': match.end()}
    return None


def _exclusion(charge, documents, directory, date_of_death):
    if charge['frequency'] not in DIVISORS:
        return 'one_time_or_unknown', None
    if charge['confidence'] < MIN_CONFIDENCE:
        return 'low_confidence', None
    cancelled = _cancellation(charge, documents, directory)
    if cancelled:
        return 'cancelled_later', cancelled
    if date_of_death and charge['last_seen'] and charge['last_seen'] < date_of_death - timedelta(days=DIVISORS[charge['frequency']]):
        return 'ended_before_death', None
    return None, None


def compute_drain(documents, findings, directory, classifier, date_of_death=None, done=(), as_of=None, date_of_death_source=None):
    as_of = as_of or date.today()
    death = parse_date(date_of_death)
    done = set(done)
    lines, excluded = [], []
    for charge in merge_occurrences(extract_occurrences(documents, directory), directory):
        reason, extra = _exclusion(charge, documents, directory, death)
        if reason:
            excluded.append({'id': charge['id'], 'label': charge['label'], 'amount': charge['amount'], 'frequency': charge['frequency'],
                             'reason': reason, 'evidence': charge['evidence'] + ([extra] if extra else [])})
            continue
        provider = directory.get(charge['provider_id'], {})
        sorted_as = classifier.classify(charge['label'], charge['provider_id'], provider.get('aliases', []))
        finding_id = _finding_for(charge, findings)
        lines.append({'id': charge['id'], 'finding_id': finding_id, 'provider_id': charge['provider_id'], 'label': charge['label'],
                      'amount': charge['amount'], 'frequency': charge['frequency'], 'frequency_basis': charge['frequency_basis'],
                      'daily_rate': daily_rate(charge['amount'], charge['frequency']),
                      'bucket': sorted_as['bucket'], 'bucket_source': sorted_as['source'], 'note': sorted_as['note'],
                      'tier': charge['tier'], 'confidence': charge['confidence'], 'periods': charge['periods'],
                      'last_seen': charge['last_seen'].isoformat() if charge['last_seen'] else None,
                      # Only a stoppable charge can be "stopped"; finishing an insurance or loan task never counts as cancelling it.
                      'stopped': sorted_as['bucket'] == 'stoppable' and finding_id in done,
                      'evidence': charge['evidence']})
    lines.sort(key=lambda l: (l['tier'] != 'confirmed', -l['daily_rate'], l['label']))
    stoppable = [l for l in lines if l['bucket'] == 'stoppable']
    daily = math.fsum(l['daily_rate'] for l in stoppable if l['tier'] == 'confirmed' and not l['stopped'])
    days = (as_of - death).days if death and as_of >= death else None
    return {
        'daily': daily,
        'possible_daily': math.fsum(l['daily_rate'] for l in stoppable if l['tier'] == 'possible' and not l['stopped']),
        'annual': daily * YEAR_DAYS,
        'since_death': daily * days if days is not None else None,
        'days_since_death': days,
        'stopped_so_far': math.fsum(l['daily_rate'] for l in stoppable if l['tier'] == 'confirmed' and l['stopped']),
        'as_of': as_of.isoformat(),
        'date_of_death': death.isoformat() if death else None,
        'date_of_death_source': date_of_death_source if death else None,
        'confirmed': [l for l in lines if l['tier'] == 'confirmed'],
        'possible': [l for l in lines if l['tier'] == 'possible'],
        'buckets': {bucket: [l for l in lines if l['bucket'] == bucket] for bucket in ('stoppable', 'keep_for_now', 'decide_later')},
        'excluded': excluded,
        # Per-action rates for the plan captions, still stoppable and not yet stopped.
        'by_finding': {finding: {'daily': math.fsum(l['daily_rate'] for l in stoppable if l['finding_id'] == finding and l['tier'] == 'confirmed' and not l['stopped']),
                                 'possible_daily': math.fsum(l['daily_rate'] for l in stoppable if l['finding_id'] == finding and l['tier'] == 'possible' and not l['stopped'])}
                       for finding in sorted({l['finding_id'] for l in stoppable if l['finding_id']})},
    }


def validate_date_of_death(value, today=None):
    if value is None:
        return None
    parsed = parse_date(value)
    if not parsed or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise HTTPException(422, 'Use YYYY-MM-DD for the date of death.')
    if parsed > (today or date.today()):
        raise HTTPException(422, 'The date of death cannot be in the future.')
    if parsed.year < 1900:
        raise HTTPException(422, 'Check the year of the date of death.')
    return parsed.isoformat()


def mount_drain(app, service, model=local_bucket_model, rules_path=None):
    classifier = BucketClassifier.from_file(rules_path or RULES_PATH, model)
    app.state.drain_classifier = classifier

    def estate_date():
        record = service.repo.get('settings', 'estate')
        if record and record.get('date_of_death'):
            return record['date_of_death'], 'family'
        suggested = service.person.get('date_of_death')
        return (suggested, 'archive') if suggested else (None, None)

    @app.get('/drain', response_model=DrainResponse)
    def drain(done: str = Query(default='', max_length=500), as_of: Optional[str] = Query(default=None, max_length=10)):
        ids = [i for i in done.split(',') if i]
        if len(ids) > 20 or any(not service.repo.get('findings', i) for i in ids):
            raise HTTPException(422, 'done must list known finding ids.')
        when = parse_date(as_of) if as_of else date.today()
        if as_of and not when:
            raise HTTPException(422, 'Use YYYY-MM-DD for as_of.')
        death, source = estate_date()
        return compute_drain(service.repo.list('documents'), service.repo.list('findings'), service.directory, classifier,
                             date_of_death=death, done=ids, as_of=when, date_of_death_source=source)

    @app.post('/estate/date-of-death')
    def set_date_of_death(request: DateOfDeathRequest):
        value = validate_date_of_death(request.date)
        record = {'date_of_death': value, 'source': 'family', 'updated_at': datetime.now().astimezone().isoformat()}
        if value:
            service.repo.put('settings', 'estate', record)
        else:
            service.repo.delete('settings', 'estate')
        # The event records that the date changed, not the date itself.
        service.log('date_of_death_updated', cleared=value is None)
        return record

    return classifier

