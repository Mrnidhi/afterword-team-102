"""Local PNG/JPEG → OCR preview → explicit review → vision evidence pipeline."""
import base64
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import warnings
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from .contacts import blocked_email, email_matches_provider
from .router import IntegrationError

MAX_BYTES=6_000_000
MAX_PIXELS=20_000_000
MAX_TEXT=200_000


def checksum(raw):
    return hashlib.sha256(raw).hexdigest()


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class ScanRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    filename: str=Field(min_length=1,max_length=180)
    image_base64: str=Field(min_length=1,max_length=8_000_000)
    provider_id: str=Field(min_length=1,max_length=100)
    date: str=Field(default='',max_length=10)
    title: str=Field(default='',max_length=200)


class ScanCorrection(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    ocr_text: str=Field(min_length=1,max_length=MAX_TEXT)
    previous_ocr_sha256: str=Field(pattern=r'^[a-f0-9]{64}$')
    actor: str=Field(min_length=1,max_length=150)


class ScanConfirmation(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    ocr_sha256: str=Field(pattern=r'^[a-f0-9]{64}$')
    image_sha256: str=Field(pattern=r'^[a-f0-9]{64}$')
    confirmed: bool
    actor: str=Field(min_length=1,max_length=150)


class TesseractOCR:
    """Only an operator-configured executable and fixed argument list are used."""
    def __init__(self,executable=None,timeout=30,runner=None):
        configured=executable or os.environ.get('AFTERWORD_TESSERACT_BIN') or shutil.which('tesseract')
        self.executable=str(Path(configured).expanduser().resolve()) if configured else None
        self.timeout=min(max(int(timeout),1),60)
        self.runner=runner or subprocess.run

    def status(self):
        available=bool(self.executable and Path(self.executable).is_file() and os.access(self.executable,os.X_OK))
        return {'available':available,'engine':'tesseract','reason':None if available else 'Install local Tesseract with English language data, or set AFTERWORD_TESSERACT_BIN to its executable.'}

    def extract(self,image_path,working_directory):
        if not self.status()['available']:
            raise IntegrationError(self.status()['reason'])
        # Images are validated and stored at generated paths, never a user path.
        output=Path(working_directory)/'ocr-result'
        args=[self.executable,str(image_path),str(output),'-l','eng','--psm','6']
        try:
            result=self.runner(args,cwd=str(working_directory),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=self.timeout,check=False,env={**os.environ,'OMP_THREAD_LIMIT':'2'})
        except subprocess.TimeoutExpired as exc:
            raise IntegrationError('Local OCR exceeded its time limit. Try a smaller, clearer scan.') from exc
        except OSError as exc:
            raise IntegrationError('The local OCR engine could not start.') from exc
        result_file=output.with_suffix('.txt')
        if result.returncode!=0 or not result_file.is_file() or result_file.is_symlink():
            raise IntegrationError('Local OCR failed. Check that Tesseract English language data is installed.')
        result_file.chmod(0o600)
        if result_file.stat().st_size>MAX_TEXT*4:
            raise IntegrationError('The extracted text exceeds the supported limit.')
        try:
            text=result_file.read_text(encoding='utf-8').strip()
        except UnicodeError as exc:
            raise IntegrationError('The local OCR engine returned invalid text.') from exc
        if not text or len(text)>MAX_TEXT:
            raise IntegrationError('No readable text was found, or the text exceeds the supported limit. Try a clearer crop.')
        return {'text':text,'engine':'tesseract','processing':'local_ocr'}


def checked_image(raw):
    if not raw or len(raw)>MAX_BYTES:
        raise IntegrationError('Use a nonempty PNG or JPEG scan up to 6 MB.')
    if importlib.util.find_spec('PIL') is None:
        raise IntegrationError('Local image validation is unavailable. Install the declared Pillow dependency.')
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as original:
                image_format=original.format
                if image_format not in {'PNG','JPEG'} or getattr(original,'n_frames',1)!=1:
                    raise IntegrationError('Use a single, nonanimated PNG or JPEG scan. PDF conversion is not included.')
                width,height=original.size
                if width<1 or height<1 or width*height>MAX_PIXELS or max(width,height)>12000:
                    raise IntegrationError('The scan exceeds the 20 megapixel or 12,000 pixel dimension limit.')
                original.verify()
            with Image.open(io.BytesIO(raw)) as original:
                original.load()
                image=ImageOps.exif_transpose(original)
                if 'A' in image.getbands():
                    rgba=image.convert('RGBA')
                    clean=Image.new('RGB',rgba.size,'white');clean.paste(rgba,mask=rgba.getchannel('A'))
                else:
                    clean=image.convert('RGB')
                output=io.BytesIO();clean.save(output,format='PNG')
                processed=output.getvalue()
                if len(processed)>MAX_BYTES:
                    output=io.BytesIO();clean.save(output,format='JPEG',quality=90,subsampling=0)
                    processed=output.getvalue();processing_type='image/jpeg'
                else:
                    processing_type='image/png'
                if len(processed)>MAX_BYTES:
                    raise IntegrationError('The validated processing image is larger than 6 MB. Crop the scan and try again.')
                return {'raw':raw,'processed':processed,'mime':'image/png' if image_format=='PNG' else 'image/jpeg','processing_mime':processing_type,'width':width,'height':height}
    except IntegrationError:
        raise
    except (UnidentifiedImageError,OSError,ValueError,SyntaxError,Image.DecompressionBombError,Image.DecompressionBombWarning) as exc:
        raise IntegrationError('The scan is invalid or cannot be safely decoded.') from exc


class ScanPipeline:
    def __init__(self,service,vision,ocr=None,storage_root=None):
        self.service,self.vision=service,vision
        self.ocr=ocr or TesseractOCR()
        self.root=Path(storage_root or os.environ.get('AFTERWORD_SCAN_DIR','~/.local/share/afterword/scans')).expanduser().resolve()
        repo=Path(__file__).resolve().parents[1]
        if self.root==repo or repo in self.root.parents:
            raise IntegrationError('Scan storage must be outside the repository.')

    def status(self):
        return {'ocr':self.ocr.status(),'image_validation':{'available':importlib.util.find_spec('PIL') is not None},'vision':{'configured':bool(getattr(self.vision,'endpoint','') and getattr(self.vision,'model',''))},'accepted_types':['image/png','image/jpeg'],'max_bytes':MAX_BYTES,'max_pixels':MAX_PIXELS,'automatic_email_attachment':False}

    def get(self,ident):
        if not re.fullmatch('[a-f0-9]{32}',ident):
            raise IntegrationError('Scan not found.')
        record=self.service.repo.get('settings','scan:'+ident)
        if not record:
            raise IntegrationError('Scan not found.')
        return record

    def read(self,record,processing=False):
        name='processing-image' if processing else 'original-image'
        path=self.root/record['id']/name
        expected=record['processing_sha256'] if processing else record['image_sha256']
        if not path.is_file() or path.is_symlink() or path.parent.is_symlink() or path.stat().st_size>MAX_BYTES:
            raise IntegrationError('The stored scan is unavailable. Reimport and review the source.')
        raw=path.read_bytes()
        if checksum(raw)!=expected:
            raise IntegrationError('The stored scan changed. Reimport and review the source.')
        return raw

    def stage(self,data):
        if data['provider_id'] not in self.service.directory:
            raise IntegrationError('Select a known provider before importing the scan.')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _().-]{0,170}\.(?:png|jpe?g)',data['filename'],re.I):
            raise IntegrationError('Use a PNG or JPEG filename without directory paths.')
        if data.get('date'):
            try:
                datetime.strptime(data['date'],'%Y-%m-%d')
            except ValueError as exc:
                raise IntegrationError('Use YYYY-MM-DD for the source document date.') from exc
        if not self.ocr.status()['available']:
            raise IntegrationError(self.ocr.status()['reason'])
        try:
            raw=base64.b64decode(data['image_base64'],validate=True)
        except ValueError as exc:
            raise IntegrationError('The image is not valid base64.') from exc
        image=checked_image(raw)
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.root.chmod(0o700)
        ident=secrets.token_hex(16)
        destination=self.root/ident
        with tempfile.TemporaryDirectory(prefix='.pending-',dir=str(self.root)) as temporary:
            temporary=Path(temporary);temporary.chmod(0o700)
            for name,content in [('original-image',raw),('processing-image',image['processed'])]:
                path=temporary/name
                fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'wb') as stream:
                    stream.write(content)
            result=self.ocr.extract(temporary/'processing-image',temporary)
            text=result.get('text','')
            if not isinstance(text,str) or not text.strip() or len(text)>MAX_TEXT or result.get('processing')!='local_ocr':
                raise IntegrationError('The local OCR adapter did not return usable text.')
            record={'id':ident,'status':'awaiting_review','provider_id':data['provider_id'],'date':data.get('date',''),'title':data.get('title','') or data['filename'],'filename':data['filename'],'ocr_text':text,'ocr_sha256':checksum(text.encode()),'raw_ocr_text':text,'raw_ocr_sha256':checksum(text.encode()),'correction_history':[],'image_sha256':checksum(raw),'processing_sha256':checksum(image['processed']),'mime':image['mime'],'processing_mime':image['processing_mime'],'width':image['width'],'height':image['height'],'created_at':timestamp(),'engine':result['engine'],'preview_url':'/scans/'+ident+'/image','warnings':['Check every extracted contact against the original scan. OCR can misread characters.','This scan stays local and is not attached to any email.']}
            # Copy only immutable source and processing image, never OCR scratch files.
            destination.mkdir(mode=0o700)
            try:
                for name in ('original-image','processing-image'):
                    shutil.copyfile(temporary/name,destination/name)
                    (destination/name).chmod(0o600)
                self.service.repo.put('settings','scan:'+ident,record)
            except Exception:
                shutil.rmtree(destination)
                raise
        self.service.log('scan_ocr_completed',scan_id=ident,provider_id=data['provider_id'],image_sha256=record['image_sha256'],processing_sha256=record['processing_sha256'],ocr_sha256=record['ocr_sha256'],engine=result['engine'])
        return record

    def correct(self,ident,data):
        with self.service.repo.lock:
            record=self.get(ident)
            if record['status']!='awaiting_review':
                raise IntegrationError('An ingested OCR source is immutable. Import a new scan version to change it.')
            if data['previous_ocr_sha256']!=record['ocr_sha256']:
                raise IntegrationError('The OCR text changed. Reload it before saving your correction.')
            if not data['actor'].strip() or not data['ocr_text'].strip():
                raise IntegrationError('Enter your name and nonempty corrected text.')
            self.read(record)
            updated_hash=checksum(data['ocr_text'].encode())
            if updated_hash==record['ocr_sha256']:
                return record
            if len(record.get('correction_history',[]))>=20:
                raise IntegrationError('This scan reached its correction limit. Import a new version.')
            version={'scan_id':ident,'ocr_text':data['ocr_text'],'ocr_sha256':updated_hash,'previous_ocr_sha256':record['ocr_sha256'],'actor':data['actor'].strip(),'created_at':timestamp()}
            self.service.repo.put('settings','scan-revision:'+ident+':'+updated_hash,version)
            record['correction_history'].append({k:v for k,v in version.items() if k not in {'ocr_text','scan_id'}})
            record.update(ocr_text=data['ocr_text'],ocr_sha256=updated_hash)
            self.service.repo.put('settings','scan:'+ident,record)
            self.service.log('scan_ocr_corrected',scan_id=ident,actor=version['actor'],previous_ocr_sha256=version['previous_ocr_sha256'],ocr_sha256=updated_hash)
            return record

    def confirm(self,ident,data):
        with self.service.repo.lock:
            record=self.get(ident)
            if not data.get('confirmed') or not data.get('actor','').strip():
                raise IntegrationError('Confirm that you checked this OCR text against the original scan.')
            if data['ocr_sha256']!=record['ocr_sha256'] or data['image_sha256']!=record['image_sha256'] or checksum(record['ocr_text'].encode())!=record['ocr_sha256']:
                raise IntegrationError('The scan or OCR preview changed. Review it again.')
            self.read(record)
            processing=self.read(record,processing=True)
            if record['status']=='extracted':
                return record['result']
            if not self.status()['vision']['configured']:
                raise IntegrationError('The local vision model is not configured. The OCR preview is saved; no contacts were ingested.')
            self.service.log('scan_ocr_reviewed',scan_id=ident,actor=data['actor'].strip(),ocr_sha256=record['ocr_sha256'],image_sha256=record['image_sha256'])
            doc_id='scan-'+ident
            result=self.vision.extract(doc_id,base64.b64encode(processing).decode(),record['ocr_text'])
            provider=self.service.directory[record['provider_id']]
            contacts=[]
            for contact in result.get('contacts',[]):
                evidence=contact.get('evidence',{});start,end=evidence.get('start'),evidence.get('end')
                value=contact.get('value','')
                if not isinstance(start,int) or not isinstance(end,int) or start<0 or end<=start or end>len(record['ocr_text']) or record['ocr_text'][start:end]!=value or evidence.get('quote')!=value or evidence.get('doc_id')!=doc_id:
                    continue
                if contact.get('kind')=='email' and (blocked_email(value) or not email_matches_provider(value,provider,self.service.aliases().get(provider['provider_id']))):
                    continue
                contacts.append(contact)
            hints=[]
            for hint in result.get('account_hints',[]):
                if not isinstance(hint,dict):
                    continue
                value=hint.get('value');start,end=hint.get('start'),hint.get('end')
                if isinstance(value,str) and isinstance(start,int) and isinstance(end,int) and 0<=start<end<=len(record['ocr_text']) and hint.get('doc_id')==doc_id and record['ocr_text'][start:end]==hint.get('quote')==value:
                    hints.append(hint)
            sensitive=[]
            for hint in hints:
                for token in re.findall(r'\b[A-Z0-9][A-Z0-9-]{4,}\b',hint['value'],re.I):
                    if re.search(r'\d',token):
                        sensitive.append(token)
            document={'id':doc_id,'provider_id':record['provider_id'],'type':'ocr','date':record['date'],'title':record['title'],'filename':record['filename'],'text':record['ocr_text'],'source_representation':'human_corrected_ocr_text' if record['correction_history'] else 'reviewed_ocr_text','raw_ocr_text':record['raw_ocr_text'],'raw_ocr_sha256':record['raw_ocr_sha256'],'correction_history':record['correction_history'],'account_hints':hints,'sensitive_identifiers':list(dict.fromkeys(sensitive)),'scan_id':ident,'image_sha256':record['image_sha256'],'processing_sha256':record['processing_sha256'],'ocr_sha256':record['ocr_sha256'],'ocr_reviewed_by':data['actor'].strip(),'ocr_reviewed_at':timestamp(),'preview_url':record['preview_url']}
            self.service.repo.put('documents',doc_id,document)
            for index,contact in enumerate(contacts):
                candidate={'candidate_id':'scan:'+ident+':'+str(index),'provider_id':provider['provider_id'],'display_name':provider['display_name'],'aliases':provider.get('aliases',[]),'channels':[{k:v for k,v in contact.items() if k!='evidence'}],'source_kind':'records','evidence':[contact['evidence']],'confidence':0.8,'verified_by_user':False,'document_date':record['date'],'account_hints':hints}
                self.service.repo.put('providers',candidate['candidate_id'],candidate)
            output={'status':'extracted','document':document,'contacts':contacts,'account_hints':hints,'processing':'local_ocr_and_vision','verbatim_gate':True}
            record.update(status='extracted',result=output,confirmed_by=data['actor'].strip(),confirmed_at=timestamp())
            self.service.repo.put('settings','scan:'+ident,record)
            self.service.log('scan_contacts_ingested',scan_id=ident,doc_id=doc_id,contact_count=len(contacts),verbatim_gate=True)
            return output


def mount_scans(app,service,vision,ocr=None,storage_root=None):
    pipeline=ScanPipeline(service,vision,ocr,storage_root)
    app.state.scan_integration=pipeline

    @app.get('/scans/status')
    def status():
        return pipeline.status()

    @app.post('/scans')
    def stage(request:ScanRequest):
        try:
            return pipeline.stage(request.model_dump())
        except IntegrationError as exc:
            raise HTTPException(409,str(exc)) from exc

    @app.get('/scans/{ident}')
    def preview(ident:str):
        try:
            return pipeline.get(ident)
        except IntegrationError as exc:
            raise HTTPException(404,str(exc)) from exc

    @app.patch('/scans/{ident}')
    def correction(ident:str,request:ScanCorrection):
        try:
            return pipeline.correct(ident,request.model_dump())
        except IntegrationError as exc:
            raise HTTPException(409,str(exc)) from exc

    @app.get('/scans/{ident}/image')
    def image(ident:str):
        try:
            record=pipeline.get(ident)
            return Response(pipeline.read(record),media_type=record['mime'],headers={'Content-Disposition':'inline; filename="'+record['filename']+'"','Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
        except IntegrationError as exc:
            raise HTTPException(409,str(exc)) from exc

    @app.post('/scans/{ident}/confirm')
    def confirm(ident:str,request:ScanConfirmation):
        try:
            return pipeline.confirm(ident,request.model_dump())
        except IntegrationError as exc:
            raise HTTPException(409,str(exc)) from exc

    return pipeline
