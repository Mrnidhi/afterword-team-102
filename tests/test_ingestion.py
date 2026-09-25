"""Document intake verifies real parsers, with explicit OCR/model test doubles."""
import base64
from email.message import EmailMessage
import hashlib
import io
from pathlib import Path
import socket

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from backend.ingestion import (
    DependencyUnavailable, DocumentIngestor, IngestionError, MAX_UPLOAD_BYTES,
    RapidOCRCPU, decode_upload, group_lines,
)
from backend.ingestion_routes import mount_ingestion


def email_bytes(body='Monthly charge: $12.99\nAccount: 1234', **headers):
    msg = EmailMessage()
    msg['Subject'] = headers.get('subject', 'Fictional service notice')
    msg['From'] = headers.get('sender', 'Support <service@fictional.example>')
    msg['Date'] = 'Thu, 24 Sep 2026 09:00:00 -0700'
    msg.set_content(body)
    return msg.as_bytes()


def picture():
    stream = io.BytesIO()
    Image.new('RGB', (100, 60), 'white').save(stream, 'PNG')
    return stream.getvalue()


class FakeOCR:
    def __init__(self, text='Fictional Company\nBalance: $12.99'):
        self.calls = []
        self.text = text

    def extract(self, image):
        self.calls.append(image.size)
        return self.text


class FakeService:
    def __init__(self):
        self.calls = []
        self.store = {}

    def extract_batch(self, items, retry=False):
        results = []
        for item in items:
            self.calls.append((dict(item), retry))
            result = {'contract': 'afterword.finding/v1', 'id': item['id'],
                      'source': item['source'], 'status': 'failed' if 'FAIL MODEL' in item['text'] else 'accepted',
                      'route': 'extract', 'finding': {}, 'evidence': []}
            self.store[item['id']] = {'text': item['text'], 'result': result}
            results.append(result)
        return results


@pytest.fixture
def client():
    app = FastAPI()
    app.state.extraction = FakeService()
    mount_ingestion(app, app.state.extraction, DocumentIngestor(ocr=FakeOCR()))
    with TestClient(app) as result:
        yield result


def upload(client, filename, raw, path='/ingest/extract', **extra):
    return client.post(path, json={'filename': filename, 'content_base64': base64.b64encode(raw).decode(), **extra})


def test_eml_canonical_headers_decodes_unicode_and_retains_body_lines():
    raw = email_bytes('Hello María\nAmount: €25.00\n', subject='Fictional María account')
    parsed = DocumentIngestor().parse('message.eml', raw)
    assert not parsed['errors']
    item = parsed['documents'][0]
    assert item['source'] == 'email'
    assert item['text'] == 'Subject: Fictional María account\nFrom: Support <service@fictional.example>\nDate: Thu, 24 Sep 2026 09:00:00 -0700\n\nHello María\nAmount: €25.00\n'
    assert item['id'] == DocumentIngestor().parse('renamed.eml', raw)['documents'][0]['id']


def test_multipart_alternative_prefers_plain_and_does_not_ingest_attachment():
    msg = EmailMessage()
    msg['Subject'] = 'Fictional alternative'
    msg.set_content('Plain source\nBalance: $25')
    msg.add_alternative('<p>HTML duplicate</p>', subtype='html')
    msg.add_attachment(b'ATTACHMENT SECRET', maintype='text', subtype='plain', filename='attachment.txt')
    item = DocumentIngestor().parse('message.eml', msg.as_bytes())['documents'][0]
    assert 'Plain source\nBalance: $25' in item['text']
    assert 'HTML duplicate' not in item['text']
    assert 'ATTACHMENT SECRET' not in item['text']


def test_html_body_becomes_readable_lines_without_scripts_or_network(monkeypatch):
    monkeypatch.setattr(socket, 'create_connection', lambda *_args, **_kwargs: pytest.fail('Network call'))
    msg = EmailMessage()
    msg['Subject'] = 'Fictional HTML'
    msg.set_content('<head><style>secret</style></head><p>Hello &amp; welcome.</p><p>Amount: <b>$10</b><br>Due: tomorrow</p><script>alert(1)</script><img src="https://tracking.invalid/pixel">', subtype='html')
    item = DocumentIngestor().parse('message.eml', msg.as_bytes())['documents'][0]
    assert item['text'].endswith('Hello & welcome.\nAmount: $10\nDue: tomorrow')
    assert 'secret' not in item['text'] and 'alert' not in item['text'] and 'tracking' not in item['text']


def test_mbox_is_one_item_per_message_and_bad_item_does_not_drop_good():
    raw = b'From fictional@example Thu Sep 24 09:00:00 2026\n' + email_bytes('First item') + b'\nFrom fictional@example Thu Sep 24 10:00:00 2026\nSubject: Empty\n\n' + b'\nFrom fictional@example Thu Sep 24 11:00:00 2026\n' + email_bytes('Third item')
    parsed = DocumentIngestor().parse('archive.mbox', raw)
    assert len(parsed['documents']) == 2
    assert [item['position'] for item in parsed['documents']] == [1, 3]
    assert parsed['errors'][0]['position'] == 2
    assert parsed['documents'][0]['id'] != parsed['documents'][1]['id']
    assert parsed['documents'][0]['text'].endswith('First item\n')


def test_csv_preserves_multiline_body_per_row_and_reports_invalid_rows():
    raw = b'date,sender,body\n2026-09-20,Fictional Shop,"Your order\nAmount: $25"\n2026-09-21,Fictional Shop,\n2026-09-22,Friend,Hello\n'
    parsed = DocumentIngestor().parse('sms.csv', raw)
    assert len(parsed['documents']) == 2
    assert parsed['documents'][0]['text'] == 'Date: 2026-09-20\nFrom: Fictional Shop\n\nYour order\nAmount: $25'
    assert parsed['documents'][1]['position'] == 3
    assert parsed['errors'][0]['position'] == 2
    assert all(item['source'] == 'sms' for item in parsed['documents'])


@pytest.mark.parametrize('raw', [b'body,sender\nHi,You', b'date,sender,body,body\n1,2,3,4', b'date,sender,body\n'])
def test_csv_invalid_schema_or_empty_export_is_rejected(raw):
    with pytest.raises(IngestionError):
        DocumentIngestor().parse('sms.csv', raw)


def test_xml_sms_dates_are_utc_and_mms_is_visible_as_error():
    raw = b'<smses><sms date="0" address="Fictional Friend" body="Hello&#10;Again"/><mms date="0"/></smses>'
    parsed = DocumentIngestor().parse('sms.xml', raw)
    assert parsed['documents'][0]['text'] == 'Date: 1970-01-01T00:00:00+00:00\nFrom: Fictional Friend\n\nHello\nAgain'
    assert parsed['errors'][0]['position'] == 2


@pytest.mark.parametrize('raw', [b'<!DOCTYPE x [<!ENTITY a "boom">]><smses/>', b'<wrong/>', b'<smses>', b'<smses/>'])
def test_xml_malformed_or_entity_expansion_rejected(raw):
    with pytest.raises(IngestionError):
        DocumentIngestor().parse('sms.xml', raw)


def test_plain_text_exact_whitespace_and_utf16_retained():
    text = '  Fictional letter\r\n\r\nAmount: $25  \r\n'
    parsed = DocumentIngestor().parse('letter.txt', text.encode('utf-16'))
    assert parsed['documents'][0]['text'] == text
    assert parsed['documents'][0]['source'] == 'letter'


def test_group_lines_reuses_team_ordering():
    result = [([[60, 10], [80, 10], [80, 20], [60, 20]], '$25', 0.99),
              ([[0, 30], [70, 30], [70, 40], [0, 40]], 'Second line', 0.99),
              ([[0, 9], [50, 9], [50, 19], [0, 19]], 'Amount:', 0.99)]
    assert group_lines(result) == ['Amount: $25', 'Second line']
    assert group_lines([]) == []


def test_image_ocr_passes_pixels_and_preserves_grouped_text():
    ocr = FakeOCR('Fictional Shop\nAccount: 1234\nAmount: $12')
    parsed = DocumentIngestor(ocr=ocr).parse('scan.png', picture())
    assert ocr.calls == [(100, 60)]
    assert parsed['documents'][0]['text'] == ocr.text
    assert parsed['documents'][0]['source_representation'] == 'rapidocr_cpu'
    assert parsed['documents'][0]['warnings']


def test_pdf_each_page_text_or_ocr_failure_keeps_neighbors():
    class Pages:
        count = 3
        def text(self, index):
            return ['Page one\n$10', '', 'Page three\n$30'][index]
        def image(self, index):
            raise DependencyUnavailable('Install local PDF rasterizer')
    parsed = DocumentIngestor(pdf_factory=lambda _: Pages()).parse('letter.pdf', b'fake PDF bytes')
    assert [item['position'] for item in parsed['documents']] == [1, 3]
    assert parsed['documents'][0]['text'] == 'Page one\n$10'
    assert parsed['errors'] == [{'id': 'upload-' + hashlib.sha256(b'fake PDF bytes').hexdigest()[:32] + '-0002', 'position': 2, 'message': 'Install local PDF rasterizer', 'retryable': True}]


def test_scanned_pdf_uses_cpu_ocr_per_page():
    class Pages:
        count = 2
        def text(self, index): return '' if index == 1 else 'Printed text\n$42'
        def image(self, index): return Image.new('RGB', (200, 300), 'white')
    ocr = FakeOCR()
    parsed = DocumentIngestor(ocr=ocr, pdf_factory=lambda _: Pages()).parse('letter.pdf', b'fake PDF')
    assert len(parsed['documents']) == 2
    assert ocr.calls == [(200, 300)]
    assert parsed['documents'][1]['text'] == ocr.text
    assert parsed['documents'][0]['source_representation'] == 'pdf_text'
    assert parsed['documents'][1]['source_representation'] == 'rapidocr_cpu'


def test_local_missing_ocr_is_a_retryable_item_error():
    class MissingOCR:
        def extract(self, image): raise DependencyUnavailable('Missing local OCR models')
    parsed = DocumentIngestor(ocr=MissingOCR()).parse('scan.png', picture())
    assert not parsed['documents']
    assert parsed['errors'][0]['retryable'] is True
    assert 'Missing local' in parsed['errors'][0]['message']


@pytest.mark.parametrize('filename,encoded', [('a.exe', 'YQ=='), ('../a.txt', 'YQ=='), ('a\\b.txt', 'YQ=='), ('a\n.txt', 'YQ=='), ('a.txt', '???'), ('a.txt', '')])
def test_bad_upload_rejected(filename, encoded):
    with pytest.raises(IngestionError): decode_upload(filename, encoded)


def test_upload_byte_limit():
    with pytest.raises(IngestionError):
        decode_upload('a.txt', base64.b64encode(b'x' * (MAX_UPLOAD_BYTES + 1)).decode())


def test_document_count_limit_does_not_silently_truncate():
    raw = b'date,sender,body\n' + b'2026-09-24,Friend,Hi\n' * 101
    with pytest.raises(IngestionError, match='100 messages'):
        DocumentIngestor().parse('sms.csv', raw)


def test_preview_never_calls_model_and_extract_retains_exact_input(client):
    raw = email_bytes('A first line\nA second line')
    preview = upload(client, 'source.eml', raw, '/ingest/preview')
    assert preview.status_code == 200
    document = preview.json()['documents'][0]
    assert not client.app.state.extraction.calls
    response = upload(client, 'source.eml', raw, reference_date='2026-09-01')
    assert response.status_code == 200
    assert response.json()['status'] == 'complete'
    stored = client.app.state.extraction.store[document['id']]
    assert stored['text'] == document['text']
    args, retry = client.app.state.extraction.calls[0]
    assert args == {'id': document['id'], 'source': 'email', 'text': document['text'], 'reference_date': '2026-09-01'}
    assert retry is False


def test_upload_errors_and_model_failures_are_partial_and_selected_retry_is_explicit(client):
    raw = b'date,sender,body\n1,A,Good\n2,B,\n3,C,FAIL MODEL\n'
    response = upload(client, 'sms.csv', raw)
    assert response.status_code == 200
    data = response.json()
    assert data['status'] == 'partial'
    assert len(data['results']) == 2 and data['error_count'] == 1
    assert data['extraction_error_count'] == 1
    assert len(client.app.state.extraction.calls) == 2
    failed = data['results'][1]['id']
    retried = upload(client, 'sms.csv', raw, '/ingest/extract?retry=true', document_ids=[failed])
    assert retried.json()['status'] == 'failed'
    assert len(retried.json()['results']) == 1
    assert client.app.state.extraction.calls[-1][1] is True
    assert len(client.app.state.extraction.calls) == 3


def test_selected_unknown_id_and_invalid_reference_date_are_rejected(client):
    assert upload(client, 'a.txt', b'Hi', document_ids=['unknown']).status_code == 422
    assert upload(client, 'a.txt', b'Hi', reference_date='not-a-date').status_code == 422
    assert not client.app.state.extraction.calls


def test_all_parser_failures_are_not_reported_as_success(client):
    result = upload(client, 'sms.csv', b'date,sender,body\n1,A,\n').json()
    assert result['status'] == 'failed'
    assert result['results'] == []
    assert not client.app.state.extraction.calls


def _text_pdf():
    """Small fictional two-page PDF, built with pypdf itself."""
    pypdf = pytest.importorskip('pypdf')
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = pypdf.PdfWriter()
    for text in ('Fictional letter one', 'Fictional letter two'):
        page = writer.add_blank_page(width=300, height=200)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        stream = DecodedStreamObject()
        stream.set_data(f'BT /F1 12 Tf 20 100 Td ({text}) Tj ET'.encode())
        page[NameObject('/Contents')] = writer._add_object(stream)
    result = io.BytesIO()
    writer.write(result)
    return result.getvalue()


def test_real_pypdf_text_pages_need_no_ocr(monkeypatch):
    monkeypatch.setattr(socket, 'create_connection', lambda *_args, **_kwargs: pytest.fail('Network call'))
    ocr = FakeOCR()
    parsed = DocumentIngestor(ocr=ocr).parse('fictional.pdf', _text_pdf())
    assert [d['text'] for d in parsed['documents']] == ['Fictional letter one', 'Fictional letter two']
    assert not ocr.calls and not parsed['errors']


def test_real_pypdfium_rasterizes_only_blank_page():
    pytest.importorskip('pypdfium2')
    pypdf = pytest.importorskip('pypdf')
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=200)
    data = io.BytesIO(); writer.write(data)
    ocr = FakeOCR()
    parsed = DocumentIngestor(ocr=ocr).parse('fictional.pdf', data.getvalue())
    assert ocr.calls == [(200, 400)]
    assert parsed['documents'][0]['source_representation'] == 'rapidocr_cpu'


def test_password_pdf_is_explicitly_rejected():
    pypdf = pytest.importorskip('pypdf')
    writer = pypdf.PdfWriter(); writer.add_blank_page(width=100, height=100); writer.encrypt('fictional')
    data = io.BytesIO(); writer.write(data)
    with pytest.raises(IngestionError, match='Unlock'):
        DocumentIngestor().parse('fictional.pdf', data.getvalue())


def test_real_rapidocr_uses_cpu_packaged_assets_and_no_network(monkeypatch):
    pytest.importorskip('rapidocr_onnxruntime')
    monkeypatch.setattr(socket, 'create_connection', lambda *_args, **_kwargs: pytest.fail('Network call'))
    monkeypatch.setattr(socket.socket, 'connect', lambda *_args, **_kwargs: pytest.fail('Network call'))
    fixture = Path(__file__).parent / 'fixtures/cedar-life-scan.png'
    ocr = RapidOCRCPU()
    parsed = DocumentIngestor(ocr=ocr).parse(fixture.name, fixture.read_bytes())
    assert not parsed['errors'], parsed['errors']
    assert len(parsed['documents']) == 1
    text = parsed['documents'][0]['text']
    assert '4471' in text
    engine = ocr._engine
    for session in (engine.text_det.infer.session, engine.text_cls.infer.session, engine.text_rec.session.session):
        assert session.get_providers() == ['CPUExecutionProvider']


def test_malformed_csv_quote_and_oversized_field_are_explicit_errors():
    for raw in (b'date,sender,body\n1,A,"unterminated', b'date,sender,body\n1,A,' + b'x' * 2_000_001):
        with pytest.raises(IngestionError, match='CSV is malformed'):
            DocumentIngestor().parse('sms.csv', raw)


def test_email_invalid_encoding_is_visible_for_review():
    raw = b'Subject: Fictional\nContent-Type: text/plain; charset=not-a-real-encoding\n\nAmount: $12\n'
    item = DocumentIngestor().parse('source.eml', raw)['documents'][0]
    assert item['text'].endswith('Amount: $12\n')
    assert 'character encoding' in item['warnings'][0]


def test_actual_extraction_repository_keeps_uploaded_source_and_idempotent_retry(tmp_path):
    from backend.extraction_routes import mount_extraction
    calls = []
    def model(text, source, doc_id, reference_date=None):
        calls.append(doc_id)
        return {'contract': 'afterword.finding/v1', 'id': doc_id, 'source': source,
                'status': 'accepted', 'route': 'extract', 'finding': {'ev': [5]},
                'evidence': [{'line': 5, 'text': text.splitlines()[4]}],
                'checks': {'grounded': {}}, 'meta': {'model': 'explicit-test-double', 'latency_ms': 1, 'output_tokens': 1}}
    app = FastAPI()
    service = mount_extraction(app, db_path=tmp_path / 'findings.sqlite3', extractor=model)
    mount_ingestion(app, service, DocumentIngestor(ocr=FakeOCR()))
    with TestClient(app) as client:
        raw = email_bytes('  Fictional amount $25  \nSecond line\n')
        first = upload(client, 'source.eml', raw, reference_date='2026-09-01')
        assert first.status_code == 200, first.text
        document = first.json()['documents'][0]
        stored = client.get('/findings/' + document['id']).json()
        assert stored['text'] == document['text']
        assert stored['evidence'][0]['text'] == '  Fictional amount $25  '
        again = upload(client, 'renamed.eml', raw, reference_date='2026-09-01')
        assert again.status_code == 200
        assert len(calls) == 1
        conflict = upload(client, 'source.eml', raw, reference_date='2026-09-02')
        assert conflict.status_code == 409
        assert len(calls) == 1
        retried = upload(client, 'source.eml', raw, '/ingest/extract?retry=true', reference_date='2026-09-01')
        assert retried.status_code == 200
        assert len(calls) == 2
        assert client.get('/findings').json()['total'] == 1


def test_pdfium_rendering_is_serialized_across_concurrent_documents(monkeypatch):
    """Real scanned-page renders must not overlap anywhere in PDFium's lifetime."""
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import time
    from backend.ingestion import PDFPages

    pdfium = pytest.importorskip('pypdfium2')
    pypdf = pytest.importorskip('pypdf')
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=100, height=200)
    data = io.BytesIO(); writer.write(data)
    documents = [PDFPages(data.getvalue()), PDFPages(data.getvalue())]
    original_document = pdfium.PdfDocument
    counter_lock = threading.Lock()
    counters = {'active': 0, 'maximum': 0, 'completed': 0}

    class CheckedDocument:
        def __init__(self, raw):
            with counter_lock:
                counters['active'] += 1
                counters['maximum'] = max(counters['maximum'], counters['active'])
            # Allow the competing worker to enter if construction is unguarded.
            time.sleep(0.01)
            self.document = original_document(raw)

        def __enter__(self):
            return self.document.__enter__()

        def __exit__(self, *args):
            try:
                return self.document.__exit__(*args)
            finally:
                with counter_lock:
                    counters['active'] -= 1
                    counters['completed'] += 1

    monkeypatch.setattr(pdfium, 'PdfDocument', CheckedDocument)
    start = threading.Barrier(4)

    def render(index):
        start.wait(timeout=5)
        with documents[index % 2].image(0) as image:
            return image.size, image.getpixel((0, 0))

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(render, range(4)))
    assert results == [((200, 400), (255, 255, 255))] * 4
    assert counters == {'active': 0, 'maximum': 1, 'completed': 4}


def test_pdfium_render_error_releases_process_lock():
    from backend.ingestion import PDFPages
    pytest.importorskip('pypdfium2')
    pypdf = pytest.importorskip('pypdf')

    def pages(width, height):
        writer = pypdf.PdfWriter(); writer.add_blank_page(width=width, height=height)
        data = io.BytesIO(); writer.write(data)
        return PDFPages(data.getvalue())

    with pytest.raises(IngestionError, match='too large'):
        pages(3000, 3000).image(0)
    # A failed oversized page must not prevent the next scanned document.
    with pages(100, 200).image(0) as image:
        assert image.size == (200, 400)
