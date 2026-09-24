"""Run: python -m backend.main. Serves the frontend and local API on one origin."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from .models import DraftRequest, EditRequest, ResolveRequest, ConsentRequest, SentRequest, RepliedRequest, MailboxRequest, IngestRequest
from .service import OutreachService

ROOT=Path(__file__).resolve().parent.parent


def create_app(db_path=None,data_dir=None,selector=None,allowed_hosts=None):
    app=FastAPI(title='Afterword local provider outreach',version='1',docs_url='/api-docs')
    service=OutreachService(db_path or os.environ.get('AFTERWORD_DB',str(Path.home()/'.local/share/afterword/outreach.sqlite3')),data_dir or ROOT/'data',selector)
    app.state.service=service
    allowed_hosts=set(allowed_hosts or {'127.0.0.1','localhost','::1'})

    @app.middleware('http')
    async def local_origin(request:Request,call_next):
        # An Origin is a scheme/host/port tuple, not merely a matching host.
        try:
            if len(request.headers.getlist('host'))!=1 or len(request.headers.getlist('origin'))>1:
                raise ValueError('Ambiguous request authority')
            host=request.url.hostname
            if host not in allowed_hosts:
                raise ValueError('Untrusted host')
            origin=request.headers.get('origin')
            if origin:
                parts=urlsplit(origin)
                origin_port=parts.port or (443 if parts.scheme=='https' else 80)
                request_port=request.url.port or (443 if request.url.scheme=='https' else 80)
                if parts.scheme!=request.url.scheme or parts.hostname!=host or origin_port!=request_port or parts.username or parts.password or parts.path or parts.query or parts.fragment:
                    raise ValueError('Cross-origin request')
        except ValueError:
            return JSONResponse({'detail':'Same-origin local access is required.'},status_code=403)
        callback=request.method=='GET' and request.url.path=='/integrations/gmail/callback'
        if request.headers.get('sec-fetch-site') in {'cross-site','same-site'} and not callback:
            return JSONResponse({'detail':'Cross-origin access is not allowed.'},status_code=403)
        if request.method not in {'GET','HEAD','OPTIONS'}:
            if request.headers.get('content-type','').split(';',1)[0].strip().lower()!='application/json':
                return JSONResponse({'detail':'Use application/json requests.'},status_code=415)
            if not origin and request.headers.get('x-afterword-client')!='web':
                return JSONResponse({'detail':'Same-origin client header is required.'},status_code=403)
        response=await call_next(request)
        if not request.url.path.startswith('/assets/'):
            response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['X-Frame-Options']='DENY'
        if 'Content-Security-Policy' not in response.headers:
            response.headers['Content-Security-Policy']="frame-ancestors 'none'"
        return response

    @app.get('/health')
    def health():
        setting=service.repo.get('settings','demo_mailbox')
        return {'service':'afterword-local','version':'1','capabilities':{'outreach':True,'send_email':False,'local_llm':{'endpoint_configured':bool(os.environ.get('AFTERWORD_LLM_URL')),'default_loopback_endpoint':'http://127.0.0.1:8000/v1','verified':False},'contact_ingest':True,'gmail_compose':True},'demo_mailbox':setting['email'] if setting else None}

    @app.get('/providers')
    def providers():
        return {'providers':list(service.directory.values()),'findings':service.repo.list('findings'),'aliases':service.aliases()}

    @app.post('/providers/resolve')
    def resolve(request:ResolveRequest):
        result=service.resolve(request.finding_id,request.provider_id)
        service.log('contact_resolution_requested',finding_id=request.finding_id,selected_tier=result['selected']['source_kind'] if result['selected'] else 'none')
        return result

    @app.get('/documents')
    def documents():
        return {'documents':service.repo.list('documents')}

    @app.post('/documents/ingest')
    def ingest(request:IngestRequest):
        return service.ingest(request.model_dump())

    @app.get('/outreach')
    def outreach():
        return {'outreach':service.repo.list('outreach')}

    @app.post('/outreach/session')
    def start_session(request:ResolveRequest):
        return service.start_session(request.finding_id)

    @app.post('/outreach/draft')
    def draft(request:DraftRequest):
        return service.draft(request.model_dump())

    @app.patch('/outreach/{outreach_id}')
    def edit(outreach_id:str,request:EditRequest):
        return service.edit(outreach_id,request.model_dump(exclude_unset=True))

    @app.post('/outreach/{outreach_id}/review')
    def review(outreach_id:str):
        return service.review(outreach_id)

    @app.post('/outreach/{outreach_id}/consent')
    def consent(outreach_id:str,request:ConsentRequest):
        return service.consent(outreach_id,request.model_dump())

    @app.post('/outreach/{outreach_id}/sent')
    def sent(outreach_id:str,request:SentRequest):
        return service.mark_sent(outreach_id,request.model_dump())

    @app.post('/outreach/{outreach_id}/replied')
    def replied(outreach_id:str,request:RepliedRequest):
        return service.mark_replied(outreach_id,request.model_dump())

    @app.get('/privacy/outreach')
    def privacy():
        return {'outreach':service.repo.list('outreach'),'consents':service.repo.list('consents'),'events':service.repo.list('events'),'metrics':service.metrics()}

    @app.get('/metrics/outreach')
    def metrics():
        return service.metrics()

    @app.post('/settings/demo-mailbox')
    def mailbox(request:MailboxRequest):
        return service.set_mailbox(request.email,request.confirmed_control)

    try:
        from .integrations import mount_integrations
    except ImportError as exc:
        # Only optional missing integration module; implementation errors surface.
        if exc.name!='backend.integrations':
            raise
    else:
        mount_integrations(app,service)
        from .scans import mount_scans
        mount_scans(app,service,app.state.vision_integration)
    app.mount('/',StaticFiles(directory=ROOT/'dist',html=True),name='frontend')
    return app


if __name__=='__main__':
    import uvicorn
    uvicorn.run(create_app(),host='127.0.0.1',port=int(os.environ.get('AFTERWORD_PORT','4173')))
