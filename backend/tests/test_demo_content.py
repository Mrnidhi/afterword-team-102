import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from demo_content import demo_texts  # noqa: E402


class DemoContentTest(unittest.TestCase):
    def setUp(self):
        self.texts = demo_texts()
        # Keyed by (kind, id): a content id like 'insurance' is reused across
        # kinds (a finding, a letter body, a task doc), so kind alone doesn't
        # disambiguate it.
        self.by_kind_id = {(kind, content_id): text for kind, content_id, text in self.texts}

    def test_covers_findings_letters_subjects_and_instructions(self):
        self.assertEqual(len(self.texts), 13)  # 3 findings + 3 letter bodies + 3 subjects + 4 instructions
        kinds = [kind for kind, _, _ in self.texts]
        self.assertEqual(kinds.count('summary'), 3)
        self.assertEqual(kinds.count('letter'), 3)
        self.assertEqual(kinds.count('instruction'), 7)  # 3 subjects + 4 distinct task instructions

    def test_letter_subjects_are_extracted_as_instruction_kind(self):
        text = self.by_kind_id[('instruction', 'subject-insurance')]
        self.assertEqual(text, 'Request for information about an existing policy')

    def test_letter_subject_is_separate_from_its_own_body(self):
        # The whole point of extracting these separately: the subject must
        # never be silently folded into the body text sent for translation.
        body = self.by_kind_id[('letter', 'insurance')]
        subject = self.by_kind_id[('instruction', 'subject-insurance')]
        self.assertNotIn(subject, body)

    def test_no_text_is_accidentally_empty(self):
        for kind, content_id, text in self.texts:
            self.assertTrue(text.strip(), f'{kind}/{content_id} extracted as empty text')


if __name__ == '__main__':
    unittest.main()
