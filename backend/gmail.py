"""Optional Gmail draft creation. There is deliberately no sending operation."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import threading
import time
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import getaddresses, formatdate
from urllib.parse import urlencode, urlparse

from .router import EMAIL, IntegrationError, digest, request_json

COMPOSE = "https://www.googleapis.com/auth/gmail.compose"
READONLY = "https://www.googleapis.com/auth/gmail.readonly"
API = "https://gmail.googleapis.com/gmail/v1/users/me/"
TOKEN = "https://oauth2.googleapis.com/token"
AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
REVOKE = "https://oauth2.googleapis.com/revoke"


class TokenStore:
    def __init__(self, path, repo_root=None):
        self.path = Path(path).expanduser().absolute()
        root = Path(repo_root or Path(__file__).resolve().parents[1]).resolve()
        resolved = self.path.resolve()
        if self.path.is_symlink() or resolved == root or root in resolved.parents:
            raise IntegrationError("Gmail tokens must be stored outside the repository.")
        self.lock = threading.RLock()

    def read(self):
        with self.lock:
            if not self.path.exists():
                return {}
            if self.path.is_symlink() or self.path.stat().st_mode & 0o077:
                raise IntegrationError("Gmail token permissions must be owner-only (0600).")
            if self.path.stat().st_size > 32_000:
                raise IntegrationError("Invalid Gmail credential store.")
            return json.loads(self.path.read_text())

    def write(self, value):
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary = self.path.with_name(self.path.name + "." + secrets.token_hex(8))
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, "w") as handle:
                    json.dump(value, handle)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
                os.chmod(self.path, 0o600)
            finally:
                temporary.unlink(missing_ok=True)

    def delete(self):
        with self.lock:
            self.path.unlink(missing_ok=True)


class GmailIntegration:
    def __init__(self, client_id="", client_secret="", redirect_uri="", token_store=None, transport=request_json, clock=time.time):
        if redirect_uri:
            parsed = urlparse(redirect_uri)
            local = parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1")
            if not (local or parsed.scheme == "https") or parsed.query or parsed.fragment or parsed.username or parsed.password:
                raise IntegrationError("Use a fixed HTTPS or loopback OAuth callback URL.")
        self.client_id, self.client_secret, self.redirect_uri = client_id, client_secret, redirect_uri
        self.store, self.transport, self.clock = token_store, transport, clock
        self.pending = {}
        self.lock = threading.RLock()

    @property
    def configured(self):
        return bool(self.client_id and self.client_secret and self.redirect_uri and self.store)

    def status(self):
        token = self.store.read() if self.store else {}
        return {"configured": self.configured, "connected": bool(token.get("refresh_token") or token.get("access_token")), "draft_scope_granted": COMPOSE in token.get("scopes", []), "reply_tracking_granted": READONLY in token.get("scopes", []), "can_send_from_afterword": False, "permission_notice": "Google's gmail.compose permission can manage drafts and send mail. Afterword only implements draft creation; you press Send in Gmail."}

    def authorize(self, purpose, approved, actor):
        if not self.configured:
            raise IntegrationError("Configure a Google OAuth client before connecting Gmail.")
        if approved is not True or not isinstance(actor, str) or not actor.strip() or len(actor) > 100:
            raise IntegrationError("Explicit account-connection consent is required.")
        if purpose not in ("drafts", "reply_tracking"):
            raise IntegrationError("Unknown Gmail permission purpose.")
        # Connecting drafts never silently adds mailbox-read permission.
        scopes = [COMPOSE] if purpose == "drafts" else [COMPOSE, READONLY]
        state, verifier, browser_token = secrets.token_urlsafe(32), secrets.token_urlsafe(64), secrets.token_urlsafe(32)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        with self.lock:
            self.pending = {k: v for k, v in self.pending.items() if v["expires"] > self.clock()}
            if len(self.pending) >= 10:
                raise IntegrationError("Too many pending connections. Try again shortly.")
            self.pending[state] = {"verifier": verifier, "browser_token": browser_token, "expires": self.clock() + 600, "scopes": scopes, "actor": actor.strip(), "purpose": purpose}
        query = urlencode({"client_id": self.client_id, "redirect_uri": self.redirect_uri, "response_type": "code", "scope": " ".join(scopes), "state": state, "access_type": "offline", "prompt": "consent", "code_challenge": challenge, "code_challenge_method": "S256"})
        return {"authorization_url": AUTH + "?" + query, "browser_token": browser_token, "purpose": purpose, "scopes": scopes}

    def callback(self, state, code, browser_token):
        with self.lock:
            pending = self.pending.get(state)
            if not pending or pending["expires"] <= self.clock() or not secrets.compare_digest(pending["browser_token"], browser_token or ""):
                raise IntegrationError("Gmail connection expired or came from a different browser. Start again.")
            self.pending.pop(state)
        if not isinstance(code, str) or not 1 <= len(code) <= 4096:
            raise IntegrationError("Invalid OAuth authorization code.")
        result = self.transport("POST", TOKEN, {"client_id": self.client_id, "client_secret": self.client_secret, "redirect_uri": self.redirect_uri, "grant_type": "authorization_code", "code": code, "code_verifier": pending["verifier"]}, form=True)
        scopes = result.get("scope", "").split()
        if not result.get("access_token") or not set(pending["scopes"]).issubset(scopes) or not set(scopes).issubset({COMPOSE, READONLY}):
            raise IntegrationError("Gmail did not grant the requested permissions. No tokens were stored.")
        # Never combine tokens from different account authorizations. A refresh token
        # from an older connection must not be attached to a new access token.
        self.store.write({"access_token": result["access_token"], "refresh_token": result.get("refresh_token", ""), "scopes": scopes, "expires_at": self.clock() + min(int(result.get("expires_in", 3600)), 86400), "authorized_by": pending["actor"]})
        return {"connected": True, "purpose": pending["purpose"], "actor": pending["actor"], "scopes": scopes}

    def _access(self, scope):
        if not self.configured:
            raise IntegrationError("Gmail is not configured.")
        with self.lock:
            token = self.store.read()
            if scope not in token.get("scopes", []):
                raise IntegrationError("Connect Gmail and approve the required permission first.")
            if token.get("access_token") and token.get("expires_at", 0) > self.clock() + 60:
                return token["access_token"]
            if not token.get("refresh_token"):
                raise IntegrationError("The Gmail connection expired. Connect again.")
            result = self.transport("POST", TOKEN, {"client_id": self.client_id, "client_secret": self.client_secret, "refresh_token": token["refresh_token"], "grant_type": "refresh_token"}, form=True)
            if not result.get("access_token"):
                raise IntegrationError("Could not refresh Gmail access. Connect again.")
            token.update(access_token=result["access_token"], expires_at=self.clock() + min(int(result.get("expires_in", 3600)), 86400))
            self.store.write(token)
            return token["access_token"]

    def _api(self, method, resource, payload=None, scope=COMPOSE):
        allowed = method == "POST" and resource == "drafts"
        allowed |= method == "GET" and resource == "profile"
        allowed |= method == "GET" and bool(re.fullmatch(r"(?:messages|threads)(?:/[A-Za-z0-9_-]+)?(?:\?[^\r\n]*)?", resource))
        if not allowed:
            raise IntegrationError("This Gmail operation is not allowed by Afterword.")
        return self.transport(method, API + resource, payload, {"Authorization": "Bearer " + self._access(scope)})

    def create_draft(self, review, consent, attachments=()):
        snapshot = review.get("snapshot", {})
        if not review.get("can_handoff") or consent.get("snapshot_hash") != review.get("snapshot_hash") or consent.get("snapshot") != snapshot or consent.get("channel") != "gmail_api":
            raise IntegrationError("Review and explicitly approve this exact Gmail draft first.")
        if review.get("recipient_confirmation_required") and not consent.get("recipient_confirmed"):
            raise IntegrationError("Confirm the recipient before creating a Gmail draft.")
        recipient, subject, body = snapshot.get("recipient", ""), snapshot.get("subject", ""), snapshot.get("body", "")
        if not EMAIL.fullmatch(recipient) or "\r" in subject or "\n" in subject or len(subject) > 300 or len(body) > 20_000:
            raise IntegrationError("Invalid draft recipient, subject or body.")
        message = EmailMessage(policy=SMTP)
        message["To"], message["Subject"] = recipient, subject
        message["Date"] = formatdate(self.clock(), usegmt=True)
        message_id = "<" + secrets.token_hex(20) + "@afterword.local>"
        message["Message-ID"] = message_id
        message.set_content(body)
        attachment_manifest = []
        total = 0
        for item in attachments:
            raw, name = item["bytes"], item["name"]
            sha = hashlib.sha256(raw).hexdigest()
            if item.get("reviewed_sha256") != sha or item.get("reviewed") is not True:
                raise IntegrationError("Review the exact attachment bytes before sharing them.")
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,99}\.(?:pdf|txt|png|jpg|jpeg)", name, re.I):
                raise IntegrationError("Attachment filename is unsupported.")
            total += len(raw)
            if total > 10_000_000 or len(attachments) > 5:
                raise IntegrationError("Attachments exceed the demo's 10 MB / five file limit.")
            mime = verified_mime(name, raw)
            main, sub = mime.split("/")
            message.add_attachment(raw, maintype=main, subtype=sub, filename=name)
            attachment_manifest.append({"name": name, "sha256": sha, "size": len(raw)})
        if attachments and consent.get("attachment_manifest") != attachment_manifest:
            raise IntegrationError("Attachment consent does not match the reviewed files.")
        if attachments and re.search(r"\bno (?:documents?|files?) (?:are )?attached\b", body, re.I):
            raise IntegrationError("The body says no documents are attached. Correct and review the letter first.")
        # Profile is permitted by gmail.compose; no extra identity or read scope
        # is requested. This avoids fabricating a From header or choosing an account.
        sender = self._api("GET", "profile").get("emailAddress", "")
        if not EMAIL.fullmatch(sender):
            raise IntegrationError("Could not verify the connected Gmail sender address.")
        message["From"] = sender
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        result = self._api("POST", "drafts", {"message": {"raw": raw}})
        if not isinstance(result.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", result["id"]):
            raise IntegrationError("Gmail returned no usable draft ID; check Gmail before retrying.")
        return {"draft_id": result["id"], "draft_message_id": result.get("message", {}).get("id"), "draft_thread_id": result.get("message", {}).get("threadId"), "rfc_message_id": message_id, "created_at_ms": int(self.clock() * 1000), "gmail_url": "https://mail.google.com/mail/#drafts", "link_kind": "drafts_folder", "link_note": "Open Drafts in the connected Google account and choose this subject. Google does not document a REST draft-ID permalink.", "sender": sender, "subject": subject, "recipient": recipient, "attachment_manifest": attachment_manifest, "sent": False}

    def check_reply(self, tracking):
        # Never assume the draft's thread ID survived editing/sending. Discover the
        # actual SENT message by the RFC Message-ID preserved by Gmail, or report
        # unavailable if Gmail rewrote it. A manual status control remains usable.
        message_id = tracking.get("rfc_message_id", "")
        if not re.fullmatch(r"<[a-f0-9]{40}@afterword\.local>", message_id):
            raise IntegrationError("This outreach has no trackable Gmail message identifier.")
        query = urlencode({"q": "in:sent rfc822msgid:" + message_id, "maxResults": 10})
        listed = self._api("GET", "messages?" + query, scope=READONLY)
        sent = None
        for candidate in listed.get("messages", [])[:10]:
            ident = candidate.get("id", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", ident):
                continue
            item = self._api("GET", f"messages/{ident}?format=metadata", scope=READONLY)
            headers = {h.get("name", "").lower(): h.get("value", "") for h in item.get("payload", {}).get("headers", [])}
            recipients = {x[1].lower() for x in getaddresses([headers.get("to", "")])}
            if "SENT" in item.get("labelIds", []) and "DRAFT" not in item.get("labelIds", []) and headers.get("message-id") == message_id and tracking["recipient"].lower() in recipients and headers.get("subject") == tracking["subject"]:
                sent = item
                break
        if not sent:
            return {"sent_verified": False, "replied": False, "reason": "No matching sent message found. Sending or editing a draft can change its identifiers; use manual tracking if needed."}
        thread_id = sent.get("threadId", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", thread_id):
            raise IntegrationError("Gmail returned an invalid thread ID.")
        thread = self._api("GET", f"threads/{thread_id}?format=metadata", scope=READONLY)
        replies = []
        for item in thread.get("messages", [])[:200]:
            labels = set(item.get("labelIds", []))
            if labels.intersection({"SENT", "DRAFT", "SPAM", "TRASH"}) or item.get("id") == sent.get("id") or int(item.get("internalDate", 0)) <= int(sent.get("internalDate", 0)):
                continue
            headers = {h.get("name", "").lower(): h.get("value", "") for h in item.get("payload", {}).get("headers", [])}
            senders = {x[1].lower() for x in getaddresses([headers.get("from", "")])}
            references = headers.get("in-reply-to", "") + " " + headers.get("references", "")
            if tracking["recipient"].lower() in senders and message_id in references:
                replies.append(item["id"])
        return {"sent_verified": True, "replied": bool(replies), "reply_ids": replies, "thread_id": thread_id, "gmail_url": "https://mail.google.com/mail/#all/" + thread_id, "link_kind": "thread_hint", "link_note": "Gmail browser thread link; use Gmail search if your account view does not open it."}

    def disconnect(self):
        unreadable = False
        try:
            token = self.store.read() if self.store else {}
        except (IntegrationError, ValueError, OSError):
            token, unreadable = {}, True
        revoked = False
        value = None
        try:
            value = token.get("refresh_token") or token.get("access_token")
            if value:
                self.transport("POST", REVOKE, {"token": value}, form=True)
                revoked = True
        except IntegrationError:
            # Local disconnection must still succeed if Google is unreachable.
            pass
        finally:
            if self.store:
                self.store.delete()
            self.pending.clear()
        return {"connected": False, "tokens_deleted": True, "revoked_at_google": revoked, "note": "If revocation could not be confirmed, remove Afterword in your Google account connections." if unreadable or (value and not revoked) else "Gmail disconnected."}


def verified_mime(name, raw):
    suffix = name.rsplit(".", 1)[-1].lower()
    if suffix == "pdf" and raw.startswith(b"%PDF-"):
        return "application/pdf"
    if suffix == "png" and raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if suffix in ("jpg", "jpeg") and raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if suffix == "txt":
        try:
            raw.decode("utf-8")
            return "text/plain"
        except UnicodeDecodeError:
            pass
    raise IntegrationError("Attachment contents do not match its supported file type.")
