from pathlib import Path
import pytest
from backend.buckets import BucketClassifier
from backend.drain import DIVISORS, daily_rate

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / 'data/charge_buckets.json'


def rules_only():
    return BucketClassifier.from_file(RULES, model=None)


def test_divisors_match_the_spec_table():
    assert DIVISORS['daily'] == 1
    assert DIVISORS['weekly'] == 7
    assert DIVISORS['biweekly'] == 14
    assert round(DIVISORS['monthly'], 2) == 30.44
    assert round(DIVISORS['quarterly'], 2) == 91.31
    assert DIVISORS['yearly'] == 365.25


def test_daily_rate_is_unrounded_and_excludes_one_time_and_unknown():
    assert daily_rate(129, 'monthly') == 129 / (365.25 / 12)
    assert round(daily_rate(129, 'monthly'), 2) == 4.24
    assert daily_rate(70, 'weekly') == 10
    assert daily_rate(1240, 'one_time') is None
    assert daily_rate(15.49, 'unknown') is None
    assert daily_rate(None, 'monthly') is None


@pytest.mark.parametrize('provider_id,label', [('valley-storage', 'Valley Storage'), ('harbor-gym', 'Harbor Gym'), ('streamly', 'Streamly')])
def test_every_recurring_charge_in_the_archive_is_sorted_by_rules(provider_id, label):
    result = rules_only().classify(label, provider_id)
    assert result['bucket'] == 'stoppable'
    assert result['source'] in {'institution', 'rules'}


@pytest.mark.parametrize('label', [
    'Home insurance', 'Homeowners policy', "Oakridge Homeowner's Insurance", 'Maple Property Insurance',
    'Auto insurance', 'Car Insurance Co', 'City Electric', 'County Water & Sewer', 'Natural Gas Utility',
    'Lakeview HOA', 'Brightline Alarm Monitoring',
])
def test_keep_for_now_charges_never_land_in_stoppable(label):
    result = rules_only().classify(label)
    assert result['bucket'] == 'keep_for_now'
    assert result['note']


@pytest.mark.parametrize('label', [
    'Car loan', 'Harbor Auto Loan', 'First Street Mortgage', 'Vehicle lease', 'Sunset Timeshare',
    'Cedar Life Insurance', 'Northstar credit card', 'Student loan servicing',
])
def test_decisions_never_land_in_stoppable(label):
    result = rules_only().classify(label)
    assert result['bucket'] == 'decide_later'
    assert result['note']


def test_safety_rules_outrank_stoppable_keywords_in_the_same_label():
    assert rules_only().classify('Harbor Gym home insurance bundle')['bucket'] == 'keep_for_now'
    assert rules_only().classify('Storage unit loan')['bucket'] == 'decide_later'


def test_keywords_match_whole_words_only():
    # "Waterside" must not trigger the water utility rule; it falls through to the gym rule.
    assert rules_only().classify('Waterside Gym')['bucket'] == 'stoppable'


def test_unmatched_institution_without_model_goes_to_decide_later():
    result = rules_only().classify('Zephyr Monthly Box')
    assert result == {'bucket': 'decide_later', 'source': 'default', 'matched': None, 'note': result['note']}


def test_model_fallback_is_only_used_for_unmatched_institutions():
    calls = []

    def model(label, context):
        calls.append(label)
        return {'bucket': 'stoppable'}
    classifier = BucketClassifier.from_file(RULES, model=model)
    assert classifier.classify('Home insurance')['bucket'] == 'keep_for_now'
    assert classifier.classify('Car loan')['bucket'] == 'decide_later'
    assert calls == []
    result = classifier.classify('Zephyr Monthly Box')
    assert result['bucket'] == 'stoppable' and result['source'] == 'local_model'
    classifier.classify('Zephyr Monthly Box')
    assert calls == ['Zephyr Monthly Box']


@pytest.mark.parametrize('answer', [None, 'stoppable', {'bucket': 'cancel'}, {'bucket': 'stoppable', 'reason': 'x'}, ['stoppable']])
def test_invalid_model_answers_fall_back_to_decide_later(answer):
    result = BucketClassifier.from_file(RULES, model=lambda label, context: answer).classify('Zephyr Monthly Box')
    assert result['bucket'] == 'decide_later' and result['source'] == 'default'


def test_unavailable_model_falls_back_to_decide_later():
    def down(label, context):
        raise ConnectionError('model offline')
    assert BucketClassifier.from_file(RULES, model=down).classify('Zephyr Monthly Box')['bucket'] == 'decide_later'


def test_default_model_refuses_non_loopback_endpoints(monkeypatch):
    from backend.buckets import local_bucket_model
    monkeypatch.setenv('AFTERWORD_LLM_URL', 'http://example.com/v1')
    with pytest.raises(ValueError):
        local_bucket_model('Zephyr', {})
