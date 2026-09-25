"""Mount contract endpoints before the frontend static mount."""
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from .extraction_contract import ExtractInput, BatchInput
from .extraction_repository import SourceConflict
from .extraction_service import ExtractionService


def mount_extraction(app, service=None, db_path=None, extractor=None, engine=None):
    if extractor is not None and engine is not None:
        raise ValueError('Supply either extractor or engine, not both.')
    service = service or ExtractionService(
        db_path or os.environ.get('AFTERWORD_FINDINGS_DB', str(Path.home() / 'Documents/Afterword-Integration/runtime/findings.sqlite3')),
        engine=extractor if extractor is not None else engine)
    app.state.extraction_service = service
    app.state.extraction = service
    router = APIRouter()

    @router.post('/extract')
    def extract(item: ExtractInput, retry: bool = Query(False)):
        try:
            return service.extract(item, retry=retry)
        except SourceConflict as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post('/extract/batch')
    def extract_batch(batch: BatchInput, retry: bool = Query(False)):
        try:
            return service.extract_batch(batch.items, retry=retry)
        except SourceConflict as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get('/findings')
    def findings():
        return service.collection()

    @router.get('/findings/{identifier}')
    def finding(identifier: str):
        result = service.get(identifier)
        if result is None:
            raise HTTPException(404, 'Finding not found.')
        return result

    app.include_router(router)
    return service
