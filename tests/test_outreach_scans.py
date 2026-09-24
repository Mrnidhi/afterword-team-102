"""OCR orchestration tests use explicit fakes except the optional real-engine smoke test."""
import base64
import io
import os
from pathlib import Path
import shutil
import stat
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.main import create_app
from backend.scans import TesseractOCR, checked_image, checksum
from backend.router import IntegrationError

HEADERS={'X-Afterword-Client':'web','Content-Type':'application/json'}
OCR_TEXT='Cedar Life\nFor support contact clains@cedar-life.example\nPolicy ending 4471'


def picture(fmt='PNG'):
    stream=io.BytesIO();Image.new('RGB',(100,60),'white').save(stream,format=fmt)
    return stream.getvalue()


class FakeOCR:
    def __init__(self):
        self.calls=[]
    def status(self):
        return {'available':True,'engine':'test-double','reason':None}
    def extract(self,image_path,directory):
        assert Path(image_path).is_file()
        self.calls.append((str(image_path),str(directory)))
        return {'text':OCR_TEXT,'engine':'test-double','processing':'local_ocr'}


class FakeVision:
    endpoint='http://127.0.0.1:8000/v1/chat/completions'
    model='test-double'
    def __init__(self):
        self.calls=[]
    def extract(self,doc_id,image_base64,text):
        self.calls.append((doc_id,image_base64,text))
        values=['claims@cedar-life.example','claims@foreign.example']
        contacts=[]
        for value in values:
            start=text.find(value)
            contacts.append({'kind':'email','value':value,'label':'Contact','preferred':True,'evidence':{'doc_id':doc_id,'quote':value,'start':start,'end':start+len(value)}})
        return {'contacts':contacts,'account_hints':[],'processing':'local_vision'}


@pytest.fixture
def client(tmp_path):
    app=create_app(tmp_path/'outreach.sqlite3',allowed_hosts={'testserver'},selector=lambda *_:None)
    pipeline=app.state.scan_integration
    pipeline.root=tmp_path/'scans'
    pipeline.ocr=FakeOCR()
    pipeline.vision=FakeVision()
    with TestClient(app,headers=HEADERS) as client:
        yield client


def stage(client,**changes):
    data={'filename':'source.png','image_base64':base64.b64encode(picture()).decode(),'provider_id':'cedar-life','date':'2026-09-18'}
    data.update(changes)
    return client.post('/scans',json=data)


def confirm(client,record,**changes):
    payload={'ocr_sha256':record['ocr_sha256'],'image_sha256':record['image_sha256'],'confirmed':True,'actor':'Priya Rao'}
    payload.update(changes)
    return client.post('/scans/'+record['id']+'/confirm',json=payload)


def test_stage_has_exact_source_preview_and_does_not_ingest_or_attach(client):
    record=stage(client).json()
    assert record['status']=='awaiting_review'
    assert record['ocr_text']==OCR_TEXT==record['raw_ocr_text']
    assert record['image_sha256']==checksum(picture())
    assert client.get(record['preview_url']).content==picture()
    assert client.app.state.service.repo.get('documents','scan-'+record['id']) is None
    assert client.get('/outreach').json()=={'outreach':[]}
    assert client.get('/scans/status').json()['automatic_email_attachment'] is False
    path=client.app.state.scan_integration.root/record['id']
    assert stat.S_IMODE(path.stat().st_mode)==0o700
    assert stat.S_IMODE((path/'original-image').stat().st_mode)==0o600
    assert stat.S_IMODE((path/'processing-image').stat().st_mode)==0o600
    assert not list(client.app.state.scan_integration.root.glob('.pending-*'))


def test_correction_keeps_raw_ocr_and_old_hash_cannot_confirm(client):
    original=stage(client).json()
    revised=OCR_TEXT.replace('clains@','claims@')
    response=client.patch('/scans/'+original['id'],json={'ocr_text':revised,'previous_ocr_sha256':original['ocr_sha256'],'actor':'Priya Rao'})
    assert response.status_code==200,response.text
    current=response.json()
    assert current['raw_ocr_text']==original['ocr_text']
    assert current['raw_ocr_sha256']==original['ocr_sha256']
    assert current['ocr_sha256']!=original['ocr_sha256']
    assert current['correction_history'][0]['actor']=='Priya Rao'
    assert confirm(client,original).status_code==409
    assert client.patch('/scans/'+original['id'],json={'ocr_text':revised,'previous_ocr_sha256':original['ocr_sha256'],'actor':'Priya Rao'}).status_code==409
    extracted=confirm(client,current)
    assert extracted.status_code==200,extracted.text
    result=extracted.json()
    assert result['status']=='extracted'
    assert len(result['contacts'])==1
    document=result['document'];evidence=result['contacts'][0]['evidence']
    assert document['source_representation']=='human_corrected_ocr_text'
    assert document['raw_ocr_text']==OCR_TEXT
    assert document['text'][evidence['start']:evidence['end']]=='claims@cedar-life.example'
    assert document['ocr_reviewed_by']=='Priya Rao'
    assert confirm(client,current).json()==result
    assert len(client.app.state.scan_integration.vision.calls)==1
    assert client.patch('/scans/'+original['id'],json={'ocr_text':'Changed','previous_ocr_sha256':current['ocr_sha256'],'actor':'Priya Rao'}).status_code==409


def test_vision_does_not_repair_contacts_without_exact_reviewed_text(client):
    record=stage(client).json()
    result=confirm(client,record).json()
    assert result['status']=='extracted'
    assert result['contacts']==[]
    assert client.app.state.service.repo.get('documents','scan-'+record['id'])['text']==OCR_TEXT


def test_vision_foreign_provider_or_invented_span_cannot_create_recipient(client):
    record=stage(client).json()
    corrected=OCR_TEXT.replace('clains@','claims@')+'\nclaims@foreign.example'
    record=client.patch('/scans/'+record['id'],json={'ocr_text':corrected,'previous_ocr_sha256':record['ocr_sha256'],'actor':'Priya'}).json()
    extracted=confirm(client,record).json()
    assert [c['value'] for c in extracted['contacts']]==['claims@cedar-life.example']


def test_missing_model_keeps_preview_and_never_claims_ingestion(client):
    pipeline=client.app.state.scan_integration
    pipeline.vision.endpoint=''
    record=stage(client).json()
    assert record['status']=='awaiting_review'
    response=confirm(client,record)
    assert response.status_code==409
    assert 'not configured' in response.json()['detail']
    assert client.get('/scans/'+record['id']).json()['status']=='awaiting_review'
    assert client.app.state.service.repo.get('documents','scan-'+record['id']) is None
    assert pipeline.vision.calls==[]


def test_missing_ocr_reports_unavailable_and_no_stage_created(client):
    pipeline=client.app.state.scan_integration
    pipeline.ocr=TesseractOCR('/path/that/does/not/exist')
    assert client.get('/scans/status').json()['ocr']['available'] is False
    response=stage(client)
    assert response.status_code==409
    assert not pipeline.root.exists()


@pytest.mark.parametrize('changes',[
 {'filename':'../../outside.png'},
 {'filename':'photo.svg'},
 {'filename':'scan.png; touch bad'},
 {'image_base64':'not-base64'},
 {'image_base64':base64.b64encode(b'<svg>not a raster</svg>').decode()},
 {'provider_id':'invented-company'},
 {'date':'2026-99-99'},
 {'image_base64':base64.b64encode(b'\x89PNG\r\n\x1a\n').decode()}
])
def test_scan_ingest_rejects_invalid_unbounded_or_arbitrary_inputs(client,changes):
    response=stage(client,**changes)
    assert response.status_code==409
    assert client.app.state.scan_integration.ocr.calls==[]


def test_pixel_and_animation_limits_are_checked_before_ocr():
    big=io.BytesIO();Image.new('1',(5000,4001),1).save(big,format='PNG')
    with pytest.raises(IntegrationError,match='megapixel'):
        checked_image(big.getvalue())
    animated=io.BytesIO();Image.new('RGB',(10,10),'white').save(animated,format='PNG',save_all=True,append_images=[Image.new('RGB',(10,10),'black')],duration=100,loop=0)
    with pytest.raises(IntegrationError,match='nonanimated'):
        checked_image(animated.getvalue())
    with pytest.raises(IntegrationError,match='6 MB'):
        checked_image(b'x'*6_000_001)


def test_jpeg_original_and_processing_copy_are_distinct(client):
    source=picture('JPEG')
    record=stage(client,filename='source.jpeg',image_base64=base64.b64encode(source).decode()).json()
    assert client.get(record['preview_url']).content==source
    assert record['image_sha256']==checksum(source)
    assert record['processing_sha256']!=record['image_sha256']
    assert record['processing_mime']=='image/png'


def test_confirm_requires_actor_consent_matching_image_and_unmodified_storage(client):
    record=stage(client).json()
    assert confirm(client,record,confirmed=False).status_code==409
    assert confirm(client,record,actor=' ').status_code==409
    assert confirm(client,record,image_sha256='0'*64).status_code==409
    assert confirm(client,record,confirmed='true').status_code==422
    path=client.app.state.scan_integration.root/record['id']/'original-image'
    path.write_bytes(b'tampered')
    assert confirm(client,record).status_code==409
    assert client.app.state.scan_integration.vision.calls==[]


def test_tesseract_exec_uses_fixed_argv_and_timeout(tmp_path):
    calls=[]
    binary=tmp_path/'tesseract';binary.write_text('not executed');binary.chmod(0o700)
    image=tmp_path/'processing-image';image.write_bytes(picture())
    def run(args,**kwargs):
        calls.append((args,kwargs))
        Path(args[2]+'.txt').write_text('Actual adapter output')
        return SimpleNamespace(returncode=0)
    engine=TesseractOCR(binary,timeout=30,runner=run)
    assert engine.extract(image,tmp_path)['text']=='Actual adapter output'
    args,kwargs=calls[0]
    assert args==[str(binary),str(image),str(tmp_path/'ocr-result'),'-l','eng','--psm','6']
    assert 'shell' not in kwargs
    assert kwargs['timeout']==30
    assert kwargs['env']['OMP_THREAD_LIMIT']=='2'
    def timed_out(*a,**kw):
        raise subprocess.TimeoutExpired(a[0],kw['timeout'])
    with pytest.raises(IntegrationError,match='time limit'):
        TesseractOCR(binary,runner=timed_out).extract(image,tmp_path)


@pytest.mark.skipif(not shutil.which('tesseract'),reason='Optional real local Tesseract is not installed')
def test_actual_tesseract_reads_fictional_fixture(tmp_path):
    fixture=Path(__file__).parent/'fixtures'/'cedar-life-scan.png'
    if not fixture.is_file():
        pytest.skip('The optional manual rehearsal fixture is unavailable')
    result=TesseractOCR().extract(fixture,tmp_path)
    assert result['processing']=='local_ocr'
    assert result['engine']=='tesseract'
    assert 'Policy ending 4471' in result['text']
    assert '@cedar-life.example' in result['text']
    # OCR may misread claims as clains. No assertion invents a corrected contact.


def test_failed_ocr_cleans_temporary_files_without_persisting_stage(client):
    pipeline=client.app.state.scan_integration
    def fail(*args):
        raise IntegrationError('Local OCR failed.')
    pipeline.ocr.extract=fail
    assert stage(client).status_code==409
    assert list(pipeline.root.iterdir())==[]
    assert not [entry for entry in client.app.state.service.repo.list('settings') if entry.get('status')=='awaiting_review']


@pytest.mark.skipif(not shutil.which('tesseract'),reason='Optional real local Tesseract is not installed')
def test_actual_ocr_api_can_stage_and_preview_with_no_vision_service(client):
    fixture=Path(__file__).parent/'fixtures'/'cedar-life-scan.png'
    if not fixture.is_file():
        pytest.skip('The optional manual rehearsal fixture is unavailable')
    pipeline=client.app.state.scan_integration
    pipeline.ocr=TesseractOCR()
    pipeline.vision.endpoint=''
    raw=fixture.read_bytes()
    response=stage(client,filename=fixture.name,image_base64=base64.b64encode(raw).decode())
    assert response.status_code==200,response.text
    record=response.json()
    assert record['engine']=='tesseract'
    assert 'Policy ending 4471' in record['raw_ocr_text']
    assert record['image_sha256']==checksum(raw)
    assert client.get(record['preview_url']).content==raw
    assert confirm(client,record).status_code==409
    assert client.app.state.service.repo.get('documents','scan-'+record['id']) is None
