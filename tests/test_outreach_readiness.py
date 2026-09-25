import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.readiness import readiness, probe_models

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('outreach_rehearsal',ROOT/'scripts/outreach_rehearsal.py')
rehearsal=importlib.util.module_from_spec(spec)
spec.loader.exec_module(rehearsal)


class ReadinessTests(unittest.TestCase):
    def test_metadata_only_does_not_open_tokens_or_print_config_values(self):
        with tempfile.TemporaryDirectory() as folder:
            token=Path(folder)/'private.json'
            token.write_text('SECRET_TOKEN_CONTENTS')
            token.chmod(0o600)
            env={'AFTERWORD_GMAIL_CLIENT_ID':'SECRET_CLIENT_ID','AFTERWORD_GMAIL_CLIENT_SECRET':'SECRET_CLIENT_SECRET','AFTERWORD_GMAIL_REDIRECT_URI':'http://127.0.0.1:4173/integrations/gmail/callback','AFTERWORD_GMAIL_TOKEN_FILE':str(token),'AFTERWORD_LOOKUP_TOKEN':'SECRET_SEARCH_TOKEN','AFTERWORD_LOOKUP_ENDPOINT':'https://public.example.com/search','AFTERWORD_LLM_MODEL':'PRIVATE_MODEL_NAME'}
            with patch.object(Path,'read_text',side_effect=AssertionError('Readiness must never open credentials')), patch('socket.getaddrinfo',side_effect=AssertionError('No network for readiness')):
                report=readiness(env)
            self.assertTrue(report['gmail']['configured'])
            self.assertTrue(report['gmail']['token_metadata']['owner_only'])
            self.assertFalse(report['token_contents_read'])
            self.assertEqual(report['network_requests'],0)
            encoded=json.dumps(report)
            for secret in ('SECRET_TOKEN_CONTENTS','SECRET_CLIENT_ID','SECRET_CLIENT_SECRET','SECRET_SEARCH_TOKEN','PRIVATE_MODEL_NAME',str(token)):
                self.assertNotIn(secret,encoded)

    def test_empty_configuration_does_not_claim_connected_or_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            report=readiness({'AFTERWORD_GMAIL_TOKEN_FILE':str(Path(folder)/'missing')})
        self.assertFalse(report['gmail']['configured'])
        self.assertFalse(report['gmail']['permissions_verified'])
        self.assertFalse(report['local_model']['inference_verified'])
        self.assertFalse(report['live_acceptance_complete'])
        self.assertIn('google_oauth',{item['id'] for item in report['next_actions']})

    def test_explicit_probe_is_only_get_models_and_redacts_model_ids(self):
        requests=[]
        def fake(request,timeout):
            requests.append(request)
            return io.BytesIO(b'{"data":[{"id":"private-model"}]}')
        report=probe_models('http://127.0.0.1:8000/v1','private-model',fake)
        self.assertEqual(requests[0].get_method(),'GET')
        self.assertEqual(requests[0].full_url,'http://127.0.0.1:8000/v1/models')
        self.assertIsNone(requests[0].data)
        self.assertTrue(report['selected_model_present'])
        self.assertNotIn('private-model',json.dumps(report))
        self.assertFalse(report['inference_verified'])
        with self.assertRaises(ValueError):
            probe_models('https://remote.example.com/v1',opener=fake)

    def test_bad_or_offline_probe_is_honest(self):
        report=probe_models('http://127.0.0.1:8000/v1',opener=lambda *a,**kw:io.BytesIO(b'not json'))
        self.assertFalse(report['reachable'])
        self.assertFalse(report['inference_verified'])


class RehearsalTests(unittest.TestCase):
    def test_summary_uses_new_measured_events_and_no_assumed_baseline(self):
        initial={'audit':{'records':[{'event_id':'old'}]}}
        report={'initial':initial,'observations':[],'manual_baselines':[]}
        final={'audit':{'records':[{'event_id':'old','kind':'draft_reviewed','can_handoff':True,'finding_to_review_seconds':999},{'event_id':'new','kind':'draft_reviewed','can_handoff':True,'finding_to_review_seconds':12.5}]}}
        summary=rehearsal.summarize(report,final)
        self.assertEqual(summary['finding_to_review_seconds'],[12.5])
        self.assertIsNone(summary['manual_baseline_median_seconds'])
        self.assertIsNone(summary['gates']['every_lookup_minimized'])
        self.assertFalse(summary['gates']['gmail_draft_observed'])
        self.assertFalse(summary['acceptance_complete'])

    def test_report_outside_repo_and_pass_needs_evidence(self):
        with self.assertRaises(ValueError):
            rehearsal.report_path(ROOT/'report.json')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'report.json'
            fake={'readiness':{'network_requests':0},'audit':{'records':[]}}
            with patch.object(rehearsal,'capture',return_value=fake),contextlib.redirect_stdout(io.StringIO()):
                rehearsal.main(['begin','--report',str(path),'--operator','participant-1','--revision','test-fixture','--environment','other-local-device'])
                with self.assertRaises(ValueError):
                    rehearsal.main(['record','--report',str(path),'--check','gmail_draft','--outcome','observed_pass'])
                artifact=Path(folder)/'observation.txt';artifact.write_text('Fictional test evidence; no live claim.')
                rehearsal.main(['record','--report',str(path),'--check','gmail_draft','--outcome','observed_pass','--evidence',str(artifact)])
                rehearsal.main(['finish','--report',str(path)])
            report=json.loads(path.read_text())
            self.assertTrue(report['complete'])
            self.assertFalse(report['summary']['acceptance_complete'])
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            self.assertNotIn('Fictional test evidence',path.read_text())
            self.assertFalse(report['summary']['gates']['gmail_draft_observed'],'An operator observation cannot manufacture a provider audit event')

    def test_capture_rejects_external_destinations(self):
        with self.assertRaises(ValueError):
            rehearsal.capture('https://external.example.com',transport=lambda *a:None)


if __name__=='__main__':
    unittest.main()
