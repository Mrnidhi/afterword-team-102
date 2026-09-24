"""Actual local ingest/resolution checks for sender identity and email dates."""
import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient
from backend.contacts import canonical_provider, canonicalize_email, mine_contacts
from backend.main import create_app

ROOT=Path(__file__).resolve().parents[1]


class ContactIngestTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        data=Path(self.temporary.name)
        self.directory=json.loads((ROOT/'data/providers_directory.json').read_text())
        (data/'providers_directory.json').write_text(json.dumps(self.directory))
        (data/'demo_archive.json').write_text(json.dumps({'person':{'full_name':'Arun Rao'},'findings':[{'id':'insurance','provider_id':'cedar-life','type':'insurance','source_ids':[]}],'documents':[]}))
        self.app=create_app(db_path=':memory:',data_dir=data)
        self.service=self.app.state.service
        self.client=TestClient(self.app,base_url='http://127.0.0.1',headers={'X-Afterword-Client':'web'})

    def tearDown(self):
        self.temporary.cleanup()

    def ingest(self,identifier,text,provider=None,date=''):
        response=self.client.post('/documents/ingest',json={'id':identifier,'type':'email','text':text,'provider_id':provider,'date':date})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def resolve(self):
        response=self.client.post('/providers/resolve',json={'finding_id':'insurance'})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_from_domain_resolves_without_provider_or_display_name(self):
        result=self.ingest('plain-domain','From: claims@cedar-life.example\nSubject: Your request\n\nPlease contact this department.')
        self.assertEqual(result['document']['provider_id'],'cedar-life')
        self.assertEqual(result['document']['provider_assignment'],'inferred')
        selected=self.resolve()['selected']
        self.assertEqual(selected['channels'][0]['value'],'claims@cedar-life.example')
        self.assertEqual(selected['source_kind'],'records')
        evidence=selected['evidence'][0]
        self.assertEqual(result['document']['text'][evidence['start']:evidence['end']],evidence['quote'])

    def test_reply_to_and_return_path_are_supported_with_exact_domain(self):
        for i,header in enumerate(('Reply-To','Return-Path')):
            result=self.ingest('header-'+str(i),f'From: noreply@unknown.example\n{header}: <support@CEDAR-LIFE.EXAMPLE>\n\nYour request is received.')
            self.assertEqual(result['document']['provider_id'],'cedar-life')
            self.assertEqual(result['contacts'][0]['channels'][0]['value'],'support@CEDAR-LIFE.EXAMPLE')

    def test_substring_and_unconfigured_subdomain_never_establish_identity(self):
        for i,domain in enumerate(('cedar-life.example.evil.test','fake-cedar-life.example','sub.cedar-life.example')):
            result=self.ingest('spoof-'+str(i),f'From: claims@{domain}\n\nA generic message.')
            self.assertEqual(result['contacts'],[])
            self.assertIsNone(result['document'].get('provider_id'))
        self.assertIsNone(self.resolve()['selected'])

    def test_display_name_address_does_not_establish_sender_identity(self):
        result=self.ingest('display-spoof','From: "claims@cedar-life.example" <sender@unknown.example>\n\nA generic message.')
        self.assertEqual(result['contacts'],[])
        self.assertIsNone(result['document'].get('provider_id'))

    def test_conflicting_explicit_provider_is_not_reassigned_or_mined(self):
        result=self.ingest('conflict','From: claims@cedar-life.example\n\nValley Storage contact: support@valley-storage.example','valley-storage')
        self.assertEqual(result['document']['provider_id'],'valley-storage')
        self.assertEqual(result['contacts'],[])
        self.assertIsNone(self.resolve()['selected'])

    def test_conflicting_known_headers_do_not_guess_an_institution(self):
        result=self.ingest('ambiguous','From: claims@cedar-life.example\nReply-To: support@valley-storage.example\n\nCedar Life follow-up.')
        self.assertIsNone(result['document'].get('provider_id'))
        self.assertEqual(result['contacts'],[])

    def test_valid_date_header_is_persisted_and_breaks_role_address_ties(self):
        old=self.ingest('old','From: claims-old@cedar-life.example\nDate: Tue, 22 Sep 2026 12:30:00 -0700\n\nPlease contact us.')
        new=self.ingest('new','From: claims-new@cedar-life.example\nDate: Wed, 23 Sep 2026 01:15:00 +0530\n\nPlease contact us.')
        self.assertEqual(new['document']['date'],'2026-09-23')
        self.assertEqual(new['document']['date_source'],'email_header')
        self.assertEqual(new['contacts'][0]['document_date'],'2026-09-23')
        self.assertEqual(old['contacts'][0]['document_date'],'2026-09-22')
        self.assertEqual(self.resolve()['selected']['channels'][0]['value'],'claims-new@cedar-life.example')

    def test_explicit_document_date_wins_over_header(self):
        result=self.ingest('metadata-date','From: claims@cedar-life.example\nDate: Wed, 23 Sep 2026 12:30:00 -0700\n\nPlease contact us.',date='2025-02-03')
        self.assertEqual(result['document']['date'],'2025-02-03')
        self.assertEqual(result['document']['date_source'],'provided_metadata')
        self.assertEqual(result['contacts'][0]['document_date'],'2025-02-03')

    def test_missing_malformed_and_duplicate_date_headers_remain_unknown(self):
        for i,header in enumerate(('', 'Date: not a date\n', 'Date: 32 Sep 2026 09:00:00 +0000\n', 'Date: Wed, 23 Sep 2026 12:30:00 -0700\nDate: Tue, 22 Sep 2026 12:30:00 -0700\n')):
            result=self.ingest('unknown-date-'+str(i),'From: claims@cedar-life.example\n'+header+'\nPlease contact us.')
            self.assertEqual(result['document']['date'],'')
            self.assertEqual(result['document']['date_source'],'unknown')
            self.assertEqual(result['contacts'][0]['document_date'],'')

    def test_role_address_preference_still_precedes_recency(self):
        self.ingest('role-old','From: claims@cedar-life.example\nDate: Mon, 01 Sep 2025 09:00:00 +0000\n\nPlease contact us.')
        self.ingest('person-new','From: individual@cedar-life.example\nDate: Wed, 23 Sep 2026 09:00:00 +0000\n\nPlease contact us.')
        self.assertEqual(self.resolve()['selected']['channels'][0]['value'],'claims@cedar-life.example')

    def test_date_and_domain_survive_mime_decoding_with_correct_evidence(self):
        source='From: claims@cedar-life.example\r\nDate: Wed, 23 Sep 2026 09:00:00 +0000\r\nMIME-Version: 1.0\r\nContent-Type: text/plain; charset=UTF-8\r\nContent-Transfer-Encoding: quoted-printable\r\n\r\nContact support=40cedar-life.example'
        result=self.ingest('encoded',source)
        document=result['document']
        self.assertEqual(document['date'],'2026-09-23')
        self.assertEqual(document['provider_id'],'cedar-life')
        self.assertEqual(document['raw_text'],source)
        self.assertEqual(document['source_representation'],'decoded_email_text')
        for candidate in result['contacts']:
            for evidence in candidate['evidence']:
                self.assertEqual(document['text'][evidence['start']:evidence['end']],evidence['quote'])


if __name__=='__main__':
    unittest.main()
