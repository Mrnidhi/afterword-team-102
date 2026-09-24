"""Daily drain: recurring charges still billing the estate, derived only from source evidence."""

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
    'daily': 'daily', 'weekly': 'weekly', 'biweekly': 'biweekly', 'fortnightly': 'biweekly',
    'monthly': 'monthly', 'quarterly': 'quarterly', 'annual': 'yearly', 'annually': 'yearly', 'yearly': 'yearly',
}


def daily_rate(amount, frequency):
    """Unrounded daily rate, or None for one-time and unknown frequencies. Round only for display."""
    divisor = DIVISORS.get(frequency)
    if divisor is None or amount is None:
        return None
    return amount / divisor
