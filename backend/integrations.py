"""Optional routes. Missing credentials produce a visible unavailable state."""
import base64
import hashlib
import math
from functools import wraps
import os
from pathlib import Path
import re
import secrets
import time
from typing import List, Literal

from fastapi import HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from .gmail import GmailIntegration, TokenStore, verified_mime
from .router import IntegrationError, ProviderLookup, SearchAdapter
from .vision import VisionContacts
from .readiness import readiness


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class LookupInput(StrictInput):
    finding_id: str = Field(min_length=1, max_length=100)
    country: str = Field(pattern=r"^[A-Z]{2}$")
    approved: bool
    actor: str = Field(min_length=1, max_length=100)
    preview_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class OAuthInput(StrictInput):
    purpose: Literal["drafts", "reply_tracking"] = "drafts"
    approved: bool
    actor: str = Field(min_length=1, max_length=100)


class DraftInput(StrictInput):
    consent_id: str = Field(min_length=1, max_length=100)
    snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    attachment_review_ids: List[str] = Field(default_factory=list, max_length=5)


class AttachmentInput(StrictInput):
    name: str = Field(min_length=1, max_length=110)
    content_base64: str = Field(min_length=1, max_length=13_333_336)


class AttachmentReview(StrictInput):
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reviewed: bool
    actor: str = Field(min_length=1, max_length=100)


class ScanInput(StrictInput):
    image_base64: str = Field(min_length=1, max_length=8_000_000)


def mount_integrations(app, service, gmail=None, lookup=None, vision=None, attachment_root=None):
    gmail = gmail or GmailIntegration(os.environ.get("AFTERWORD_GMAIL_CLIENT_ID", ""), os.environ.get("AFTERWORD_GMAIL_CLIENT_SECRET", ""), os.environ.get("AFTERWORD_GMAIL_REDIRECT_URI", ""), TokenStore(os.environ.get("AFTERWORD_GMAIL_TOKEN_FILE", "~/.local/share/afterword/gmail-tokens.json")))
    endpoint = os.environ.get("AFTERWORD_LOOKUP_ENDPOINT", "")
    adapter = SearchAdapter(endpoint, os.environ.get("AFTERWORD_LOOKUP_TOKEN", "")) if endpoint else None
    def audit(**record):
        record["task_type"] = record.pop("kind", "provider_lookup")
        service.log("escalation", **record)
    lookup = lookup or ProviderLookup(adapter, audit)
    vision = vision or VisionContacts(os.environ.get("AFTERWORD_VISION_ENDPOINT", ""), os.environ.get("AFTERWORD_VISION_MODEL", ""))
    root = Path(attachment_root or os.environ.get("AFTERWORD_ATTACHMENT_DIR", "~/.local/share/afterword/attachments")).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[1]
    if root == repo_root or repo_root in root.parents:
        raise IntegrationError("Attachment storage must be outside the repository.")
    app.state.gmail_integration, app.state.lookup_integration, app.state.vision_integration = gmail, lookup, vision

    def fail(exc):
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    def serialized(function):
        @wraps(function)
        def run(*args, **kwargs):
            # The local prototype intentionally serializes mutation and external
            # draft creation. An edit cannot race an approved disclosure snapshot.
            with service.repo.lock:
                return function(*args, **kwargs)
        return run

    def editable(outreach_id):
        outreach = service.get_outreach(outreach_id)
        if outreach.get("status") != "draft":
            raise HTTPException(409, "Sent outreach is immutable. Create a new draft to follow up.")
        return outreach

    def provider_for(finding_id):
        finding = service.repo.get("findings", finding_id)
        if not finding:
            raise HTTPException(404, "Finding not found")
        provider = service.directory.get(finding.get("provider_id"))
        if not provider:
            raise HTTPException(409, "A curated company name is required before public lookup.")
        return provider

    @app.get("/integrations/status")
    def integration_status():
        try:
            return {"gmail": gmail.status(), "lookup_configured": lookup.search is not None, "vision_configured": bool(vision.endpoint and vision.model), "live_validation": "Requires configured services and user-approved rehearsal; automated tests use fakes."}
        except IntegrationError as exc:
            fail(exc)

    @app.get("/integrations/readiness")
    def integration_readiness():
        # Configuration and filesystem metadata only: this route never opens a
        # token file, probes a model, resolves DNS or contacts Google/search.
        from .router import request_json, public_request_json
        report = readiness()
        report["registered_components"] = {"gmail_configured": gmail.configured, "gmail_uses_network_transport": gmail.transport is request_json, "lookup_configured": lookup.search is not None, "lookup_uses_network_transport": isinstance(lookup.search, SearchAdapter) and lookup.search.transport is public_request_json, "vision_configured": bool(vision.endpoint and vision.model), "vision_uses_local_transport": vision.transport is request_json}
        scans = getattr(app.state, "scan_integration", None)
        report["scans"] = scans.status() if scans is not None else {"pipeline_registered": False}
        return report

    @app.get("/integrations/rehearsal-evidence")
    def rehearsal_evidence():
        from datetime import datetime, timezone
        from .router import digest
        kinds = {'draft_created', 'draft_reviewed', 'contact_resolution_requested', 'escalation', 'gmail_connection_consent', 'gmail_connected', 'gmail_disconnected', 'gmail_draft_created', 'gmail_draft_failed', 'gmail_reply_checked', 'manually_marked_sent', 'manually_marked_replied', 'local_vision_contact_extraction', 'attachment_reviewed', 'scan_ocr_completed', 'scan_ocr_corrected', 'scan_ocr_reviewed', 'scan_contacts_ingested'}
        rows = []
        for event in service.repo.list('events'):
            if event.get('kind') not in kinds:
                continue
            row = {'event_id': event['id'], 'kind': event['kind'], 'created_at': event.get('created_at'), 'record_sha256': digest(event)}
            if event.get('outreach_id'):
                row['outreach_key'] = digest(event['outreach_id'])[:20]
            for field in ('elapsed_seconds', 'finding_to_review_seconds'):
                value = event.get(field)
                if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
                    row[field] = value
            for field in ('can_handoff', 'sent_verified', 'replied', 'sent'):
                if isinstance(event.get(field), bool):
                    row[field] = event[field]
            if event.get('kind') == 'draft_created':
                mode = event.get('generation_mode', event.get('generation'))
                if isinstance(mode, dict):
                    mode = mode.get('mode')
                if mode in ('local_template', 'local_model_guarded'):
                    row['generation_mode'] = mode
            if event.get('kind') == 'escalation':
                payload = event.get('payload', {})
                company, country = payload.get('company'), payload.get('country')
                minimized = set(payload) == {'company', 'country'} and company in {p['display_name'] for p in service.directory.values()} and isinstance(country, str) and bool(re.fullmatch('[A-Z]{2}', country)) and event.get('query') == str(company) + ' ' + str(country) + ' public bereavement claims contact'
                row.update(payload_minimization_verified=minimized, status=event.get('status') if event.get('status') in ('started', 'completed', 'failed') else 'unknown')
            if event.get('kind') == 'gmail_draft_created':
                row['attachment_count'] = len(event.get('attachment_manifest', []))
            if event.get('kind', '').startswith('scan_'):
                for field in ('image_sha256', 'processing_sha256', 'ocr_sha256'):
                    if isinstance(event.get(field), str) and re.fullmatch('[a-f0-9]{64}', event[field]):
                        row[field] = event[field]
                if isinstance(event.get('contact_count'), int):
                    row['contact_count'] = event['contact_count']
                if isinstance(event.get('verbatim_gate'), bool):
                    row['verbatim_gate'] = event['verbatim_gate']
            if event.get('kind') == 'contact_resolution_requested' and event.get('selected_tier') in ('records', 'directory', 'lookup', 'none'):
                row['selected_tier'] = event['selected_tier']
            rows.append(row)
        return {'schema_version': 1, 'captured_at': datetime.now(timezone.utc).isoformat(), 'source': 'current_local_service_audit', 'records': rows, 'network_requests': 0, 'redaction': 'No addresses, bodies, actors, source text, OAuth tokens or document filenames included.', 'limitations': 'Audit records establish what this local service recorded. Real provider behavior and hardware identity require independent live evidence.'}

    @app.get("/providers/lookup-preview")
    def lookup_preview(finding_id: str, country: str = "US"):
        try:
            return lookup.preview(provider_for(finding_id), country)
        except IntegrationError as exc:
            fail(exc)

    @app.post("/providers/lookup")
    def public_lookup(data: LookupInput):
        try:
            result = lookup.lookup(provider_for(data.finding_id), data.country, data.approved, data.actor, data.preview_hash)
            for candidate in result["candidates"]:
                service.repo.put("providers", candidate["candidate_id"], candidate)
            service.repo.put("lookups", secrets.token_hex(12), {"finding_id": data.finding_id, "created_at": time.time(), "approved_by": data.actor, **result})
            return result
        except IntegrationError as exc:
            fail(exc)

    @app.get("/integrations/gmail/status")
    def gmail_status():
        try:
            return gmail.status()
        except IntegrationError as exc:
            fail(exc)

    @app.post("/integrations/gmail/authorize")
    def gmail_authorize(data: OAuthInput, response: Response):
        try:
            result = gmail.authorize(data.purpose, data.approved, data.actor)
            response.set_cookie("afterword_oauth", result.pop("browser_token"), max_age=600, httponly=True, secure=gmail.redirect_uri.startswith("https:"), samesite="lax", path="/integrations/gmail/callback")
            response.headers["Cache-Control"] = "no-store"
            service.log("gmail_connection_consent", actor=data.actor, purpose=data.purpose, requested_scopes=result["scopes"])
            return result
        except IntegrationError as exc:
            fail(exc)

    @app.get("/integrations/gmail/callback", response_class=HTMLResponse)
    def gmail_callback(request: Request, state: str = "", code: str = "", error: str = ""):
        # OAuth callback has no Origin on normal navigation. Compare with the fixed
        # operator-configured callback, never X-Forwarded-Host or a request redirect.
        if str(request.url).split("?", 1)[0] != gmail.redirect_uri:
            raise HTTPException(400, "Gmail callback does not match the configured URL.")
        if error:
            raise HTTPException(400, "Gmail connection was not approved. You can close this tab.")
        try:
            result = gmail.callback(state, code, request.cookies.get("afterword_oauth", ""))
            service.log("gmail_connected", **result)
            response = HTMLResponse("<!doctype html><html><meta name=referrer content=no-referrer><title>Gmail connected</title><body><h1>Gmail connected</h1><p>Return to Afterword. Nothing has been sent.</p></body></html>", headers={"Cache-Control": "no-store", "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'", "Referrer-Policy": "no-referrer"})
            response.delete_cookie("afterword_oauth", path="/integrations/gmail/callback")
            return response
        except IntegrationError as exc:
            fail(exc)

    @app.post("/integrations/gmail/disconnect")
    def gmail_disconnect():
        try:
            result = gmail.disconnect()
            service.log("gmail_disconnected", **result)
            return result
        except IntegrationError as exc:
            fail(exc)

    @app.post("/outreach/{outreach_id}/attachments")
    @serialized
    def stage_attachment(outreach_id: str, data: AttachmentInput):
        outreach = editable(outreach_id)
        previous = outreach.get("attachment_files", [])
        if len(previous) >= 5:
            raise HTTPException(409, "Remove an attachment before adding another (maximum five).")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,99}\.(?:pdf|txt|png|jpg|jpeg)", data.name, re.I):
            raise HTTPException(422, "Unsupported attachment filename")
        try:
            raw = base64.b64decode(data.content_base64, validate=True)
            if not raw or len(raw) > 10_000_000:
                raise IntegrationError("Attachments must be nonempty and at most 10 MB.")
            if sum(item["size"] for item in previous) + len(raw) > 10_000_000:
                raise IntegrationError("Combined attachments exceed the 10 MB limit.")
            mime = verified_mime(data.name, raw)
        except ValueError as exc:
            fail(IntegrationError(str(exc)))
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        ident = secrets.token_hex(16)
        path = root / ident
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
        metadata = {"id": ident, "outreach_id": outreach_id, "name": data.name, "size": len(raw), "mime": mime, "sha256": hashlib.sha256(raw).hexdigest()}
        service.repo.put("settings", "attachment:" + ident, metadata)
        outreach["attachment_files"] = previous + [{key: metadata[key] for key in ("id", "name", "size", "sha256")}]
        service.repo.put("outreach", outreach_id, outreach)
        return {**metadata, "review_required": True, "preview_url": f"/outreach/{outreach_id}/attachments/{ident}"}

    def attachment(outreach_id, attachment_id):
        if not re.fullmatch(r"[a-f0-9]{32}", attachment_id):
            raise HTTPException(404, "Attachment not found")
        item = service.repo.get("settings", "attachment:" + attachment_id)
        if not item or item["outreach_id"] != outreach_id:
            raise HTTPException(404, "Attachment not found")
        path = root / attachment_id
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 10_000_000:
            raise HTTPException(409, "Attachment is unavailable")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise HTTPException(409, "Attachment changed. Upload and review it again.")
        return item, raw

    @app.get("/outreach/{outreach_id}/attachments/{attachment_id}")
    def attachment_preview(outreach_id: str, attachment_id: str):
        item, raw = attachment(outreach_id, attachment_id)
        return Response(raw, media_type=item["mime"], headers={"Content-Disposition": 'attachment; filename="' + item["name"] + '"', "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})

    @app.post("/outreach/{outreach_id}/attachments/{attachment_id}/review")
    @serialized
    def attachment_review(outreach_id: str, attachment_id: str, data: AttachmentReview):
        editable(outreach_id)
        item, raw = attachment(outreach_id, attachment_id)
        if not data.reviewed or not data.actor.strip() or data.sha256 != item["sha256"]:
            raise HTTPException(409, "Confirm review of these exact attachment contents.")
        record = {"id": secrets.token_hex(16), "attachment_id": attachment_id, "outreach_id": outreach_id, "sha256": item["sha256"], "actor": data.actor.strip(), "reviewed": True, "created_at": time.time()}
        service.repo.put("settings", "attachment_review:" + record["id"], record)
        service.log("attachment_reviewed", **record)
        return record

    @app.delete("/outreach/{outreach_id}/attachments/{attachment_id}")
    @serialized
    def remove_attachment(outreach_id: str, attachment_id: str):
        item, raw = attachment(outreach_id, attachment_id)
        outreach = editable(outreach_id)
        outreach["attachment_files"] = [entry for entry in outreach.get("attachment_files", []) if entry["id"] != attachment_id]
        service.repo.put("outreach", outreach_id, outreach)
        (root / attachment_id).unlink(missing_ok=True)
        service.repo.delete("settings", "attachment:" + attachment_id)
        return {"removed": True}

    @app.post("/outreach/{outreach_id}/gmail-draft")
    @serialized
    def gmail_draft(outreach_id: str, data: DraftInput):
        editable(outreach_id)
        consent = service.validate_consent(outreach_id, data.consent_id, data.snapshot_hash)
        review = service.review(outreach_id)
        operation_key = "gmail_operation:" + data.consent_id
        existing = service.repo.get("settings", operation_key)
        if existing:
            if existing.get("result"):
                return existing["result"]
            raise HTTPException(409, "The previous draft request is unresolved. Check Gmail before requesting a new review; automatic retry could create a duplicate.")
        attachments, manifest, file_ids = [], [], []
        for review_id in data.attachment_review_ids:
            recorded = service.repo.get("settings", "attachment_review:" + review_id)
            if not recorded or recorded["outreach_id"] != outreach_id or recorded["actor"] != consent["actor"]:
                raise HTTPException(409, "Every attachment needs review by the consenting person.")
            item, raw = attachment(outreach_id, recorded["attachment_id"])
            if recorded["sha256"] != item["sha256"]:
                raise HTTPException(409, "Attachment review is stale.")
            attachments.append({"name": item["name"], "bytes": raw, "reviewed": True, "reviewed_sha256": item["sha256"]})
            manifest.append({"name": item["name"], "sha256": item["sha256"], "size": len(raw)})
            file_ids.append(item["id"])
        expected_files = review["snapshot"].get("attachment_files", [])
        expected_manifest = [{k: item[k] for k in ("name", "sha256", "size")} for item in expected_files]
        if file_ids != [item["id"] for item in expected_files] or manifest != expected_manifest:
            raise HTTPException(409, "The attachments differ from the reviewed draft. Review every attached file again.")
        # Files are disclosed only when this explicit create-draft action includes
        # their review IDs. The immutable additional consent binds the actual bytes.
        consent = {**consent, "attachment_manifest": manifest}
        if manifest:
            attachment_consent = {**consent, "id": "attachments-" + secrets.token_hex(12), "parent_consent_id": data.consent_id, "channel": "gmail_api_attachments", "created_at": time.time()}
            service.repo.put("consents", attachment_consent["id"], attachment_consent)
        try:
            # Validate local configuration before an operation becomes uncertain.
            if not gmail.status()["draft_scope_granted"]:
                raise IntegrationError("Connect Gmail for draft creation first.")
            with service.repo.lock:
                if service.repo.get("settings", operation_key):
                    raise HTTPException(409, "This reviewed draft is already being created. Check its status before trying again.")
                service.repo.put("settings", operation_key, {"state": "started", "outreach_id": outreach_id})
            result = gmail.create_draft(review, consent, attachments)
            service.repo.put("settings", operation_key, {"state": "created", "result": result})
            service.repo.put("settings", "gmail_tracking:" + outreach_id, result)
            service.log("gmail_draft_created", outreach_id=outreach_id, consent_id=data.consent_id, draft_id=result["draft_id"], attachment_manifest=manifest, sent=False)
            return result
        except IntegrationError as exc:
            if service.repo.get("settings", operation_key):
                service.repo.put("settings", operation_key, {"state": "uncertain", "outreach_id": outreach_id})
                service.log("gmail_draft_failed", outreach_id=outreach_id, consent_id=data.consent_id, status="check_gmail_before_retry")
            fail(exc)

    @app.post("/outreach/{outreach_id}/check-reply")
    @serialized
    def check_reply(outreach_id: str):
        outreach = service.get_outreach(outreach_id)
        tracking = service.repo.get("settings", "gmail_tracking:" + outreach_id)
        if not tracking:
            raise HTTPException(409, "Only a Gmail API draft can be tracked automatically.")
        if outreach.get("status") not in ("waiting", "review", "replied"):
            raise HTTPException(409, "Mark the message as sent after sending it in Gmail.")
        try:
            result = gmail.check_reply(tracking)
            if result.get("replied"):
                from datetime import datetime, timezone
                outreach.update(status="replied", gmail_reply=result, reply_confirmation="gmail_thread", replied_at=datetime.now(timezone.utc).isoformat())
                service.repo.put("outreach", outreach_id, outreach)
            service.log("gmail_reply_checked", outreach_id=outreach_id, sent_verified=result["sent_verified"], replied=result["replied"])
            return result
        except IntegrationError as exc:
            fail(exc)

    @app.post("/documents/{doc_id}/vision-contacts")
    def vision_contacts(doc_id: str, data: ScanInput):
        document = service.repo.get("documents", doc_id)
        if not document:
            raise HTTPException(404, "Document not found")
        provider = service.directory.get(document.get("provider_id"))
        if not provider:
            raise HTTPException(409, "Associate the document with a known provider first.")
        try:
            result = vision.extract(doc_id, data.image_base64, document.get("text", document.get("ocr_text", "")))
            if result["contacts"]:
                ident = "vision-" + secrets.token_hex(12)
                candidate = {"provider_id": provider["provider_id"], "candidate_id": ident, "display_name": provider["display_name"], "aliases": provider.get("aliases", []), "channels": [{k: v for k, v in c.items() if k != "evidence"} for c in result["contacts"]], "source_kind": "records", "evidence": [c["evidence"] for c in result["contacts"]], "confidence": 0.8, "verified_by_user": False, "account_hints": result["account_hints"]}
                service.repo.put("providers", ident, candidate)
            service.log("local_vision_contact_extraction", doc_id=doc_id, contact_count=len(result["contacts"]))
            return result
        except IntegrationError as exc:
            fail(exc)

    return {"gmail": gmail, "lookup": lookup, "vision": vision}


register_integrations = mount_integrations
