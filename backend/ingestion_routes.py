"""JSON upload routes, mounted before the static frontend."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .extraction_repository import SourceConflict

from .ingestion import DocumentIngestor, IngestionError, MAX_BASE64_CHARS, decode_upload


class UploadRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1, max_length=MAX_BASE64_CHARS)
    reference_date: Optional[date] = None
    document_ids: Optional[list[str]] = Field(default=None, min_length=1, max_length=100)


def create_ingestion_router(service, ingestor=None):
    router = APIRouter()
    parser = ingestor if ingestor is not None else DocumentIngestor()

    def parse(request):
        try:
            raw = decode_upload(request.filename, request.content_base64)
            parsed = parser.parse(request.filename, raw)
        except IngestionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if request.document_ids is not None:
            selected = set(request.document_ids)
            known = {item['id'] for item in parsed['documents']} | {item['id'] for item in parsed['errors']}
            if not selected.issubset(known):
                raise HTTPException(status_code=422, detail='A selected item is not part of this file. Re-import the original file.')
            parsed['documents'] = [item for item in parsed['documents'] if item['id'] in selected]
            parsed['errors'] = [item for item in parsed['errors'] if item['id'] in selected]
            parsed['document_count'] = len(parsed['documents'])
            parsed['error_count'] = len(parsed['errors'])
        return parsed

    @router.post('/ingest/preview')
    def preview(request: UploadRequest):
        return parse(request)

    @router.post('/ingest/extract')
    def extract(request: UploadRequest, retry: bool = Query(default=False)):
        parsed = parse(request)
        items = [{key: document[key] for key in ('id', 'source', 'text')} for document in parsed['documents']]
        if request.reference_date is not None:
            for item in items:
                item['reference_date'] = request.reference_date.isoformat()
        # The service serializes calls through the same lock as /extract and
        # /extract/batch, persists every exact input and returns contract failures.
        try:
            results = service.extract_batch(items, retry=retry) if items else []
        except SourceConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValidationError:
            raise HTTPException(status_code=422, detail='The parsed batch exceeds the extraction limits. Split it into smaller files.') from None
        parsed['results'] = results
        parsed['extraction_error_count'] = sum(result.get('status') == 'failed' for result in results)
        failures = parsed['error_count'] + parsed['extraction_error_count']
        successes = len(results) - parsed['extraction_error_count']
        parsed['status'] = 'complete' if not failures else ('partial' if successes else 'failed')
        return parsed

    return router


def mount_ingestion(app, service, ingestor=None):
    parser = ingestor if ingestor is not None else DocumentIngestor()
    app.state.document_ingestor = parser
    app.include_router(create_ingestion_router(service, parser))
    return parser
