import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as app_module  # noqa: E402
from demo_content import demo_texts  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from translate import protect  # noqa: E402


class FakeResponse:
    def __init__(self, data):
        self._data = data
        self.status_code = 200

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class FakeClient:
    """Stands in for app._client. chat_fn(system, text) -> str;
    embed_fn(texts) -> list[list[float]]. Both are swappable per test."""

    def __init__(self, chat_fn=None, embed_fn=None, model_id='fake-model-1', up=True):
        self.chat_fn = chat_fn or (lambda system, text: text)  # identity by default
        self.embed_fn = embed_fn or (lambda texts: [[1.0, 0.0] for _ in texts])
        self.model_id = model_id
        self.up = up
        self.chat_calls = []

    def get(self, url, timeout=None):
        if not self.up:
            raise app_module.httpx.ConnectError('down')
        assert url.endswith('/models')
        return FakeResponse({'data': [{'id': self.model_id}]})

    def post(self, url, json=None):
        if url.endswith('/chat/completions'):
            system, text = json['messages'][0]['content'], json['messages'][1]['content']
            self.chat_calls.append(text)
            return FakeResponse({'choices': [{'message': {'content': self.chat_fn(system, text)}}]})
        if url.endswith('/embeddings'):
            vecs = self.embed_fn(json['input'])
            return FakeResponse({'data': [{'embedding': v} for v in vecs]})
        raise ValueError(url)


def identical_embed(texts):
    # Same vector for everything -> cosine 1.0, i.e. a "perfect" round trip.
    return [[1.0, 0.0] for _ in texts]


def orthogonal_embed(texts):
    # First text vs the rest are unrelated -> cosine ~0, a "bad" round trip.
    return [[1.0, 0.0]] + [[0.0, 1.0] for _ in texts[1:]]


class AppTest(unittest.TestCase):
    def setUp(self):
        app_module.DB_PATH = Path(__file__).resolve().parent / f'_test_{self.id().split(".")[-1]}.db'
        app_module.DB_PATH.unlink(missing_ok=True)
        app_module.init_db()
        app_module._model_id_cache['id'] = None
        app_module._prewarm.update(done=0, total=0, started=False)
        self.client = TestClient(app_module.app)

    def tearDown(self):
        app_module.DB_PATH.unlink(missing_ok=True)

    def use(self, fake_client):
        app_module._client = fake_client

    # -- languages / health --------------------------------------------------

    def test_languages_lists_all_three_with_correct_fonts(self):
        body = self.client.get('/languages').json()
        by_code = {row['code']: row for row in body}
        self.assertEqual(set(by_code), {'es', 'vi', 'hi'})
        self.assertIsNone(by_code['es']['font'])
        self.assertIsNone(by_code['vi']['font'])
        self.assertEqual(by_code['hi']['font']['family'], 'Noto Sans Devanagari')
        self.assertEqual(by_code['hi']['native_name'], 'हिन्दी')

    def test_health_reports_reachable_servers(self):
        self.use(FakeClient(up=True))
        body = self.client.get('/health').json()
        self.assertEqual({k: v for k, v in body.items() if k != 'prewarm'},
                          {'status': 'ok', 'llm': True, 'embeddings': True})

    def test_health_reports_unreachable_server(self):
        self.use(FakeClient(up=False))
        body = self.client.get('/health').json()
        self.assertEqual({k: v for k, v in body.items() if k != 'prewarm'},
                          {'status': 'ok', 'llm': False, 'embeddings': False})

    def test_health_reports_prewarm_state(self):
        # A bare TestClient() (no `with`) never fires the startup event, so
        # this only exercises the "not started" branch — real prewarm
        # progress is checked against the live server in the plan's phase 6
        # verification, not here.
        self.use(FakeClient())
        self.assertEqual(self.client.get('/health').json()['prewarm'], 'not started')

    # -- validation -----------------------------------------------------------

    def test_rejects_unknown_language(self):
        self.use(FakeClient(embed_fn=identical_embed))
        r = self.client.post('/translate', json={'text': 'Hello', 'target_lang': 'fr', 'kind': 'summary'})
        self.assertEqual(r.status_code, 422)

    def test_rejects_unknown_kind(self):
        self.use(FakeClient(embed_fn=identical_embed))
        r = self.client.post('/translate', json={'text': 'Hello', 'target_lang': 'es', 'kind': 'novel'})
        self.assertEqual(r.status_code, 422)

    def test_rejects_text_over_the_length_cap(self):
        r = self.client.post('/translate', json={'text': 'x' * (app_module.MAX_CHARS + 1),
                                                   'target_lang': 'es', 'kind': 'summary'})
        self.assertEqual(r.status_code, 422)

    # -- cache -----------------------------------------------------------------

    def test_second_call_is_served_from_cache_without_calling_the_model_again(self):
        fake = FakeClient(chat_fn=lambda s, t: t, embed_fn=identical_embed)
        self.use(fake)
        body = {'text': 'Please confirm the current balance.', 'target_lang': 'es', 'kind': 'summary'}
        first = self.client.post('/translate', json=body).json()
        calls_after_first = len(fake.chat_calls)
        second = self.client.post('/translate', json=body).json()
        self.assertFalse(first['cached'])
        self.assertTrue(second['cached'])
        self.assertEqual(first['text'], second['text'])
        self.assertEqual(len(fake.chat_calls), calls_after_first)  # no extra LLM call on the cache hit

    def test_different_language_is_a_separate_cache_entry(self):
        self.use(FakeClient(chat_fn=lambda s, t: t, embed_fn=identical_embed))
        body = {'text': 'Please confirm the current balance.', 'kind': 'summary'}
        es = self.client.post('/translate', json={**body, 'target_lang': 'es'}).json()
        vi = self.client.post('/translate', json={**body, 'target_lang': 'vi'}).json()
        self.assertFalse(es['cached'])
        self.assertFalse(vi['cached'])  # not served from the Spanish entry

    # -- protected tokens --------------------------------------------------------

    def test_intact_tokens_are_restored_and_marked_ok(self):
        # The "translation" just relabels the language in brackets; sentinels pass through untouched.
        self.use(FakeClient(chat_fn=lambda s, t: f'[ES] {t}', embed_fn=identical_embed))
        r = self.client.post('/translate', json={'text': 'Pay $400 by September 30, 2026.',
                                                   'target_lang': 'es', 'kind': 'letter'}).json()
        self.assertTrue(r['protected_tokens_ok'])
        self.assertIn('$400', r['text'])
        self.assertIn('September 30, 2026', r['text'])

    def test_dropped_token_is_recovered_on_retry(self):
        calls = {'n': 0}

        def flaky(system, text):
            calls['n'] += 1
            return text.replace('⟦T1⟧', '') if calls['n'] == 1 else text  # drop it, then don't

        self.use(FakeClient(chat_fn=flaky, embed_fn=identical_embed))
        r = self.client.post('/translate', json={'text': 'Paid $400 in total.',
                                                   'target_lang': 'hi', 'kind': 'summary'}).json()
        self.assertTrue(r['protected_tokens_ok'])
        self.assertIn('$400', r['text'])
        # 2 forward attempts (the retry) + 1 back-translation call = 3 total.
        self.assertEqual(calls['n'], 3)

    def test_token_still_missing_after_retry_is_flagged_not_silently_dropped(self):
        self.use(FakeClient(chat_fn=lambda s, t: t.replace('⟦T1⟧', ''), embed_fn=identical_embed))
        r = self.client.post('/translate', json={'text': 'Paid $400 in total.',
                                                   'target_lang': 'hi', 'kind': 'summary'}).json()
        self.assertFalse(r['protected_tokens_ok'])
        self.assertNotIn('$400', r['text'])  # honest: never fabricated back in

    # -- round-trip confidence ------------------------------------------------------

    def test_low_confidence_flag_below_threshold(self):
        self.use(FakeClient(chat_fn=lambda s, t: t, embed_fn=orthogonal_embed))
        r = self.client.post('/translate', json={'text': 'Please confirm the balance.',
                                                   'target_lang': 'vi', 'kind': 'summary'}).json()
        self.assertLess(r['round_trip_score'], app_module.THRESHOLD)
        self.assertTrue(r['low_confidence'])

    def test_high_confidence_not_flagged(self):
        self.use(FakeClient(chat_fn=lambda s, t: t, embed_fn=identical_embed))
        r = self.client.post('/translate', json={'text': 'Please confirm the balance.',
                                                   'target_lang': 'vi', 'kind': 'summary'}).json()
        self.assertFalse(r['low_confidence'])

    # -- negation guard (phase 0's known blind spot: a flipped negation can
    # -- still score above the round-trip threshold) ---------------------------

    def test_negation_flip_is_flagged_even_with_a_high_similarity_score(self):
        # The "translation" round-trips almost perfectly by cosine (identical
        # vectors) but a negation was silently added on the way back — this is
        # exactly the failure mode phase 0's calibration found round-trip
        # cosine alone cannot catch.
        def flip_back_translation(system, text):
            return text.replace('was applied', 'was not applied') if 'into English' in system else text

        self.use(FakeClient(chat_fn=flip_back_translation, embed_fn=identical_embed))
        r = self.client.post('/translate', json={'text': 'The payment was applied to the invoice.',
                                                   'target_lang': 'es', 'kind': 'summary'}).json()
        self.assertGreaterEqual(r['round_trip_score'], app_module.THRESHOLD)  # cosine alone would pass this
        self.assertTrue(r['low_confidence'])  # the negation guard catches it anyway

    def test_negation_on_both_sides_is_not_a_flip(self):
        # Both source and round-trip mention a negation in the same place —
        # not a flip, shouldn't trip the guard.
        self.use(FakeClient(chat_fn=lambda s, t: t, embed_fn=identical_embed))
        r = self.client.post('/translate', json={'text': 'The payment was not applied to the invoice.',
                                                   'target_lang': 'es', 'kind': 'summary'}).json()
        self.assertFalse(r['low_confidence'])

    def test_negation_flip_flag_survives_a_cache_hit(self):
        def flip_back_translation(system, text):
            return text.replace('was applied', 'was not applied') if 'into English' in system else text

        self.use(FakeClient(chat_fn=flip_back_translation, embed_fn=identical_embed))
        body = {'text': 'The payment was applied to the invoice.', 'target_lang': 'es', 'kind': 'summary'}
        first = self.client.post('/translate', json=body).json()
        second = self.client.post('/translate', json=body).json()
        self.assertTrue(second['cached'])
        self.assertTrue(second['low_confidence'])  # not lost when served from the DB instead of computed fresh

    # -- Hindi glossary hint (phase 0/6's "policy"/"provider" weaknesses) -------

    def test_hindi_prompt_includes_the_glossary_hint(self):
        seen = {}

        def spy(system, text):
            seen.setdefault('systems', []).append(system)
            return text

        self.use(FakeClient(chat_fn=spy, embed_fn=identical_embed))
        self.client.post('/translate', json={'text': 'Ask about the policy.', 'target_lang': 'hi', 'kind': 'instruction'})
        forward_system = seen['systems'][0]
        self.assertIn('पॉलिसी', forward_system)
        self.assertIn('प्रदाता', forward_system)

    def test_spanish_prompt_has_no_hindi_specific_hint(self):
        seen = {}

        def spy(system, text):
            seen.setdefault('systems', []).append(system)
            return text

        self.use(FakeClient(chat_fn=spy, embed_fn=identical_embed))
        self.client.post('/translate', json={'text': 'Ask about the policy.', 'target_lang': 'es', 'kind': 'instruction'})
        self.assertNotIn('पॉलिसी', seen['systems'][0])

    # -- protection --------------------------------------------------------------

    def test_translator_never_receives_the_raw_amount(self):
        seen = {}

        def spy(system, text):
            seen['text'] = text
            return text

        self.use(FakeClient(chat_fn=spy, embed_fn=identical_embed))
        self.client.post('/translate', json={'text': 'A payment of $250,000 was recorded.',
                                               'target_lang': 'es', 'kind': 'letter'})
        self.assertNotIn('$250,000', seen['text'])
        self.assertIn('⟦T1⟧', seen['text'])

    # -- bypass_cache (used by metrics.py's cold-latency measurement) ------------

    def test_bypass_cache_forces_a_real_call_even_when_cached(self):
        fake = FakeClient(chat_fn=lambda s, t: t, embed_fn=identical_embed)
        self.use(fake)
        app_module.do_translate('Please confirm the balance.', 'es', 'summary')
        calls_after_first = len(fake.chat_calls)
        app_module.do_translate('Please confirm the balance.', 'es', 'summary', bypass_cache=True)
        self.assertGreater(len(fake.chat_calls), calls_after_first)

    def test_bypass_cache_result_still_gets_cached_for_next_time(self):
        fake = FakeClient(chat_fn=lambda s, t: t, embed_fn=identical_embed)
        self.use(fake)
        app_module.do_translate('Please confirm the balance.', 'es', 'summary', bypass_cache=True)
        calls_after_bypass = len(fake.chat_calls)
        r = app_module.do_translate('Please confirm the balance.', 'es', 'summary')
        self.assertTrue(r.cached)
        self.assertEqual(len(fake.chat_calls), calls_after_bypass)  # no extra call on the normal cached path

    # -- prewarm ---------------------------------------------------------------

    def test_prewarm_translates_every_demo_text_into_every_language(self):
        fake = FakeClient(chat_fn=lambda s, t: t, embed_fn=identical_embed)
        self.use(fake)
        expected = len(demo_texts()) * len(app_module.LANGUAGES)
        app_module.run_prewarm()
        self.assertEqual(app_module._prewarm['total'], expected)
        self.assertEqual(app_module._prewarm['done'], expected)
        with app_module.db_conn() as db:
            count = db.execute('SELECT COUNT(*) c FROM translations').fetchone()['c']
        self.assertEqual(count, expected)

    def test_prewarm_keeps_going_after_one_item_fails(self):
        calls = {'n': 0}

        def flaky(system, text):
            calls['n'] += 1
            if calls['n'] == 1:
                raise RuntimeError('simulated model server hiccup')
            return text

        self.use(FakeClient(chat_fn=flaky, embed_fn=identical_embed))
        expected = len(demo_texts()) * len(app_module.LANGUAGES)
        app_module.run_prewarm()
        self.assertEqual(app_module._prewarm['done'], expected)  # every item still attempted
        with app_module.db_conn() as db:
            count = db.execute('SELECT COUNT(*) c FROM translations').fetchone()['c']
        self.assertEqual(count, expected - 1)  # the one that raised never got a cache row


    # -- schema migration (an afterword.db from before the negation guard) -----

    def test_init_db_migrates_a_table_missing_the_negation_flip_column(self):
        # Simulates the real backend/afterword.db from before this fix: a
        # translations table with the original columns only.
        with sqlite3.connect(app_module.DB_PATH) as db:
            db.execute('DROP TABLE translations')
            db.execute('''CREATE TABLE translations (
                lang TEXT NOT NULL, kind TEXT NOT NULL, source_hash TEXT NOT NULL,
                prompt_version TEXT NOT NULL, model_id TEXT NOT NULL, text TEXT NOT NULL,
                round_trip_score REAL NOT NULL, protected_tokens_ok INTEGER NOT NULL,
                ms INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (lang, kind, source_hash, prompt_version, model_id))''')
        app_module.init_db()  # must not raise, and must add the missing column
        with app_module.db_conn() as db:
            cols = {row['name'] for row in db.execute('PRAGMA table_info(translations)')}
        self.assertIn('negation_flip', cols)

    # -- static frontend mount ---------------------------------------------------

    def test_dist_is_served_from_the_same_origin(self):
        r = self.client.get('/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('Afterword', r.text)

    # -- CORS ---------------------------------------------------------------------

    def test_cors_defaults_to_explicit_local_development_origins(self):
        self.assertEqual(app_module.CORS_ORIGINS,
                         ['http://127.0.0.1:8080', 'http://localhost:8080'])


class AuthRoutesTest(unittest.TestCase):
    def setUp(self):
        self.path = Path(__file__).resolve().parent / f'_auth_{self.id().split(".")[-1]}.db'
        for suffix in ('', '-wal', '-shm'):
            Path(str(self.path) + suffix).unlink(missing_ok=True)
        app_module.auth.AUTH_DB_PATH = self.path
        app_module.auth.init_db()
        self.client = TestClient(app_module.app)

    def tearDown(self):
        for suffix in ('', '-wal', '-shm'):
            Path(str(self.path) + suffix).unlink(missing_ok=True)

    def test_signup_authenticates_and_persists_workspace_on_hp(self):
        signed_up = self.client.post('/api/auth/signup', json={
            'username': 'family.demo', 'display_name': 'Family Demo',
            'password': 'a secure local password'})
        self.assertEqual(signed_up.status_code, 200)
        csrf = signed_up.json()['csrf_token']
        self.assertEqual(self.client.get('/api/auth/session').json()['user']['username'], 'family.demo')
        saved = self.client.put('/api/workspace', headers={'X-CSRF-Token': csrf},
                                json={'state': {'completed': ['insurance']}})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self.client.get('/api/workspace').json()['state']['completed'], ['insurance'])

    def test_workspace_route_requires_a_session(self):
        response = self.client.get('/app/', follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['location'], '/login?next=/app/')


class ProtectSmokeTest(unittest.TestCase):
    """Confirms app.py's own imports of translate.py still line up."""

    def test_protect_is_importable_from_app_module(self):
        masked, tokens = protect('$5 on June 1, 2026')
        self.assertTrue(tokens)
        self.assertNotIn('$5', masked)


if __name__ == '__main__':
    unittest.main()
