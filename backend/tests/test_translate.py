import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from translate import check, protect, restore  # noqa: E402

LETTER = (
    'To Cedar Life — policy services,\n\n'
    'I am writing for [FAMILY MEMBER] about policy POL-48213 held by Arun Rao. '
    'Your letter dated June 12, 2019 records coverage of $250,000. '
    'A payment of $400 was made on 2026-09-14 from account 0042-771.\n\n'
    'Please reply by September 30, 2026 to [EMAIL ADDRESS].'
)

# The real medical template from dist/pages.js.
MEDICAL = (
    'I am helping organize the affairs of Arun Rao. I found an invoice dated September 10, 2026 '
    'showing $1,240 and a receipt dated September 14, 2026 for $400.'
)


def values(tokens, kind):
    return [t.value for t in tokens if t.kind == kind]


class ProtectTest(unittest.TestCase):
    def test_letter_covers_all_five_kinds(self):
        masked, tokens = protect(LETTER)
        self.assertEqual(values(tokens, 'placeholder'), ['[FAMILY MEMBER]', '[EMAIL ADDRESS]'])
        self.assertEqual(values(tokens, 'provider'), ['Cedar Life — policy services'])
        self.assertEqual(values(tokens, 'date'), ['June 12, 2019', '2026-09-14', 'September 30, 2026'])
        self.assertEqual(values(tokens, 'amount'), ['$250,000', '$400'])
        self.assertEqual(values(tokens, 'account'), ['POL-48213', '0042-771'])
        for t in tokens:
            self.assertNotIn(t.value, masked)

    def test_round_trip_is_exact(self):
        for text in (LETTER, MEDICAL, 'No protected tokens here.', ''):
            masked, tokens = protect(text)
            self.assertEqual(restore(masked, tokens), text)
            self.assertEqual(check(masked, tokens), [])

    def test_demo_template(self):
        _, tokens = protect(MEDICAL)
        self.assertEqual([t.value for t in tokens],
                         ['Arun Rao', 'September 10, 2026', '$1,240', 'September 14, 2026', '$400'])

    def test_longest_match_wins_on_overlap(self):
        # The year inside the date and the short provider name inside the full one stay whole.
        _, tokens = protect('Cedar Clinic — billing team wrote on September 10, 2026.')
        self.assertEqual([t.value for t in tokens], ['Cedar Clinic — billing team', 'September 10, 2026'])

    def test_repeated_values_get_distinct_sentinels(self):
        masked, tokens = protect('$400 then $400')
        self.assertEqual(masked, '⟦T1⟧ then ⟦T2⟧')
        self.assertEqual(len({t.sentinel for t in tokens}), 2)

    def test_ordinary_numbers_are_translated(self):
        _, tokens = protect('Call within 30 days about 2 boxes.')
        self.assertEqual(tokens, [])

    def test_translation_can_reorder_sentinels(self):
        masked, tokens = protect('Paid $400 on September 14.')
        translated = 'El ⟦T2⟧ se pagó ⟦T1⟧.'
        self.assertEqual(check(translated, tokens), [])
        self.assertEqual(restore(translated, tokens), 'El September 14 se pagó $400.')


class CheckTest(unittest.TestCase):
    def setUp(self):
        self.masked, self.tokens = protect(MEDICAL)

    def test_dropped_sentinel(self):
        problems = check(self.masked.replace('⟦T3⟧', '1.240 dólares'), self.tokens)
        self.assertEqual(problems, ['missing ⟦T3⟧ (amount: $1,240)'])

    def test_duplicated_sentinel(self):
        self.assertEqual(check(self.masked + ' ⟦T5⟧', self.tokens), ['duplicated ⟦T5⟧'])

    def test_invented_sentinel(self):
        self.assertEqual(check(self.masked + ' ⟦T9⟧', self.tokens), ['unexpected ⟦T9⟧'])


if __name__ == '__main__':
    unittest.main()
