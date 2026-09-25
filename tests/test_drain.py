import json
import math
from datetime import date, timedelta
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from backend.buckets import BucketClassifier
from backend.drain import CANCELLED, DIVISORS, _exclusion, compute_drain
from backend.main import create_app

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = json.loads((ROOT / 'data/demo_archive.json').read_text())
DIRECTORY = {p['provider_id']: p for p in json.loads((ROOT / 'data/providers_directory.json').read_text())['providers']}
HEADERS = {'X-Afterword-Client': 'web', 'Content-Type': 'application/json'}
MONTHLY = DIVISORS['monthly']
EXTRA_PROVIDERS = {
    'oak-home': {'provider_id': 'oak-home', 'display_name': 'Oakridge Home Insurance', 'aliases': []},
    'harbor-auto': {'provider_id': 'harbor-auto', 'display_name': 'Harbor Auto Loan', 'aliases': []},
}


def classifier():
    return BucketClassifier.from_file(ROOT / 'data/charge_buckets.json', model=None)


def drain(documents=None, findings=None, directory=None, **kwargs):
    return compute_drain(ARCHIVE['documents'] if documents is None else documents, ARCHIVE['findings'] if findings is None else findings,
                         directory or DIRECTORY, classifier(), **kwargs)


def doc(id, text, date, provider_id=None):
    return {'id': id, 'text': text, 'date': date, 'provider_id': provider_id}


def by_label(result):
    return {l['label']: l for l in result['confirmed'] + result['possible']}


def headline_from_lines(result):
    return math.fsum(l['daily_rate'] for l in result['buckets']['stoppable'] if l['tier'] == 'confirmed' and not l['stopped'])


# ---- the real demo archive ----------------------------------------------------

def test_archive_produces_exactly_its_three_recurring_charges():
    lines = by_label(drain())
    assert set(lines) == {'Valley Storage', 'Harbor Gym', 'Streamly'}
    storage, gym, streamly = lines['Valley Storage'], lines['Harbor Gym'], lines['Streamly']
    assert (storage['amount'], storage['frequency'], storage['frequency_basis'], storage['tier']) == (129.0, 'monthly', 'stated', 'confirmed')
    assert storage['finding_id'] == 'storage' and storage['bucket'] == 'stoppable'
    for line, amount in ((gym, 39.99), (streamly, 15.49)):
        # One statement period and no stated frequency: a single mention, so it is only "possible".
        assert (line['amount'], line['tier'], line['frequency_basis'], line['finding_id']) == (amount, 'possible', 'assumed_statement_period', 'subscriptions')
        assert line['bucket'] == 'stoppable'


def test_every_evidence_quote_is_verbatim_from_its_document():
    texts = {d['id']: d['text'] for d in ARCHIVE['documents']}
    result = drain()
    lines = result['confirmed'] + result['possible']
    assert all(line['evidence'] for line in lines)
    for line in lines:
        for evidence in line['evidence']:
            assert texts[evidence['doc_id']][evidence['start']:evidence['end']] == evidence['quote']
    assert by_label(result)['Streamly']['evidence'][0]['quote'] == 'Sep 7 · Streamly · $15.49'


def test_one_time_bills_and_coverage_amounts_are_not_charges():
    result = drain()
    amounts = {l['amount'] for l in result['confirmed'] + result['possible']} | {e['amount'] for e in result['excluded']}
    assert not amounts & {1240.0, 400.0, 250000.0}


def test_archive_headline_values():
    result = drain(as_of=date(2026, 9, 24))
    assert result['daily'] == pytest.approx(129 / MONTHLY)
    assert round(result['daily'], 2) == 4.24
    assert result['annual'] == pytest.approx(129 * 12)
    assert round(result['possible_daily'], 2) == 1.82
    assert result['stopped_so_far'] == 0
    assert result['since_death'] is None and result['date_of_death'] is None


@pytest.mark.parametrize('done', [[], ['storage'], ['subscriptions'], ['storage', 'subscriptions']])
def test_bucket_totals_always_sum_to_the_headline(done):
    result = drain(done=done)
    assert result['daily'] == headline_from_lines(result)
    assert result['annual'] == result['daily'] * 365.25
    everything = result['confirmed'] + result['possible']
    assert sorted(l['id'] for l in everything) == sorted(l['id'] for b in result['buckets'].values() for l in b)


def test_completing_a_task_moves_its_rate_into_stopped_so_far():
    result = drain(done=['storage'])
    assert result['daily'] == 0
    assert result['stopped_so_far'] == pytest.approx(129 / MONTHLY)
    assert by_label(result)['Valley Storage']['stopped'] is True
    # Possible charges never inflate the "already stopped" figure.
    result = drain(done=['subscriptions'])
    assert result['possible_daily'] == 0 and result['stopped_so_far'] == 0
    assert result['daily'] == pytest.approx(129 / MONTHLY)


def test_archive_documents_contain_no_cancellation_phrases():
    assert not [d['id'] for d in ARCHIVE['documents'] if CANCELLED.search(d['text'])]


# ---- safety: charges that must continue ----------------------------------------

def test_home_insurance_and_car_loan_never_count_toward_the_headline_even_when_done():
    directory = {**DIRECTORY, **EXTRA_PROVIDERS}
    documents = ARCHIVE['documents'] + [
        doc('home', 'Your policy renews.\nMonthly premium: $95.00', '2026-09-01', 'oak-home'),
        doc('auto', 'Loan statement\nMonthly payment: $412.50', '2026-09-05', 'harbor-auto'),
    ]
    findings = ARCHIVE['findings'] + [{'id': 'home', 'provider_id': 'oak-home', 'source_ids': ['home']},
                                      {'id': 'auto', 'provider_id': 'harbor-auto', 'source_ids': ['auto']}]
    result = drain(documents, findings, directory, done=['home', 'auto'])
    lines = by_label(result)
    assert lines['Oakridge Home Insurance']['bucket'] == 'keep_for_now'
    assert lines['Harbor Auto Loan']['bucket'] == 'decide_later'
    assert not lines['Oakridge Home Insurance']['stopped'] and not lines['Harbor Auto Loan']['stopped']
    assert all(l['bucket'] == 'stoppable' for l in result['buckets']['stoppable'])
    assert result['daily'] == pytest.approx(129 / MONTHLY)
    assert result['stopped_so_far'] == 0


# ---- confirmation, dedupe and exclusions ----------------------------------------

def test_two_statement_periods_confirm_a_pattern():
    documents = [doc('aug', 'Recurring transactions\nAug 5 · Harbor Gym · $39.99', '2026-08-15'),
                 doc('sep', 'Recurring transactions\nSep 5 · Harbor Gym · $39.99', '2026-09-15')]
    line = by_label(drain(documents))['Harbor Gym']
    assert (line['tier'], line['frequency'], line['frequency_basis'], line['periods']) == ('confirmed', 'monthly', 'observed', 2)
    assert [e['doc_id'] for e in line['evidence']] == ['aug', 'sep']


def test_the_same_charge_in_an_email_and_a_statement_is_counted_once():
    documents = ARCHIVE['documents'] + [doc('statement-2', 'Recurring transactions\nSep 2 · Valley Storage · $129.00', '2026-09-30')]
    result = drain(documents)
    storage = [l for l in result['confirmed'] + result['possible'] if l['provider_id'] == 'valley-storage']
    assert len(storage) == 1 and len(storage[0]['evidence']) == 2
    assert result['daily'] == pytest.approx(129 / MONTHLY)


def test_a_later_cancellation_document_closes_the_charge():
    later = doc('gym-cancel', 'Harbor Gym\nYour membership has been cancelled.', '2026-09-20', 'harbor-gym')
    result = drain(ARCHIVE['documents'] + [later])
    assert 'Harbor Gym' not in by_label(result)
    excluded = {e['label']: e for e in result['excluded']}['Harbor Gym']
    assert excluded['reason'] == 'cancelled_later'
    assert excluded['evidence'][-1]['quote'] == 'has been cancelled'
    earlier = doc('gym-cancel', 'Harbor Gym\nYour membership has been cancelled.', '2026-08-01', 'harbor-gym')
    assert 'Harbor Gym' in by_label(drain(ARCHIVE['documents'] + [earlier]))


def test_a_charge_last_seen_long_before_the_death_is_excluded():
    last_seen = date(2026, 9, 2)
    ended = drain(date_of_death=(last_seen + timedelta(days=31)).isoformat(), as_of=date(2026, 10, 10))
    assert {e['label']: e['reason'] for e in ended['excluded']}['Valley Storage'] == 'ended_before_death'
    assert ended['daily'] == 0
    running = drain(date_of_death='2026-09-18', as_of=date(2026, 9, 24))
    assert 'Valley Storage' in by_label(running)


def test_a_single_unlabelled_transaction_is_not_shown():
    result = drain([doc('card', 'Card activity\nSep 9 · Streamly · $15.49', '2026-09-15')])
    assert result['confirmed'] == result['possible'] == []
    assert result['excluded'][0]['reason'] == 'one_time_or_unknown'


def test_charges_below_the_confidence_floor_are_excluded():
    charge = {'frequency': 'monthly', 'confidence': 0.49, 'label': 'Streamly', 'provider_id': 'streamly', 'last_seen': None, 'evidence': []}
    assert _exclusion(charge, [], DIRECTORY, None) == ('low_confidence', None)
    assert _exclusion({**charge, 'confidence': 0.5}, [], DIRECTORY, None) == (None, None)


def test_since_death_is_the_current_rate_times_days():
    result = drain(date_of_death='2026-09-03', as_of=date(2026, 9, 24))
    assert result['days_since_death'] == 21
    assert result['since_death'] == pytest.approx(21 * 129 / MONTHLY)


# ---- API ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / 'test.sqlite3', allowed_hosts={'testserver'}, bucket_model=None), headers=HEADERS) as c:
        yield c


def test_get_drain_returns_the_documented_shape(client):
    response = client.get('/drain')
    assert response.status_code == 200, response.text
    body = response.json()
    assert {'daily', 'annual', 'since_death', 'stopped_so_far', 'as_of', 'date_of_death', 'confirmed', 'possible', 'buckets'} <= set(body)
    assert set(body['buckets']) == {'stoppable', 'keep_for_now', 'decide_later'}
    line = body['confirmed'][0]
    assert {'finding_id', 'label', 'amount', 'frequency', 'daily_rate', 'bucket', 'confidence', 'evidence'} <= set(line)
    assert body['date_of_death'] is None and body['since_death'] is None


def test_done_ids_update_stopped_so_far_and_are_validated(client):
    body = client.get('/drain', params={'done': 'storage'}).json()
    assert body['daily'] == 0 and body['stopped_so_far'] == pytest.approx(129 / MONTHLY)
    assert client.get('/drain', params={'done': 'storage,unknown'}).status_code == 422
    assert client.get('/drain', params={'as_of': '24/09/2026'}).status_code == 422


def test_date_of_death_persists_across_restarts_and_can_be_cleared(tmp_path):
    path = tmp_path / 'estate.sqlite3'
    with TestClient(create_app(path, allowed_hosts={'testserver'}, bucket_model=None), headers=HEADERS) as c:
        saved = c.post('/estate/date-of-death', json={'date': '2026-09-03'})
        assert saved.status_code == 200 and saved.json()['date_of_death'] == '2026-09-03'
        events = [e for e in c.get('/privacy/outreach').json()['events'] if e['kind'] == 'date_of_death_updated']
        assert events and '2026-09-03' not in json.dumps(events)
    with TestClient(create_app(path, allowed_hosts={'testserver'}, bucket_model=None), headers=HEADERS) as c:
        body = c.get('/drain', params={'as_of': '2026-09-24'}).json()
        assert (body['date_of_death'], body['date_of_death_source'], body['days_since_death']) == ('2026-09-03', 'family', 21)
        assert body['since_death'] == pytest.approx(21 * body['daily'])
        assert c.post('/estate/date-of-death', json={'date': None}).status_code == 200
        assert c.get('/drain').json()['date_of_death'] is None


@pytest.mark.parametrize('value', ['2026-9-3', '2026-02-30', '03/09/2026', '1850-01-01', (date.today() + timedelta(days=1)).isoformat()])
def test_invalid_dates_of_death_are_rejected(client, value):
    assert client.post('/estate/date-of-death', json={'date': value}).status_code == 422


def test_date_of_death_requires_the_same_origin_client(client):
    response = client.post('/estate/date-of-death', json={'date': '2026-09-03'}, headers={'X-Afterword-Client': ''})
    assert response.status_code == 403
