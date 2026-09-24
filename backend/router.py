"""Explicitly approved, minimized provider lookups. No document text leaves here."""
import hashlib
import http.client
import ipaddress
import json
import re
import socket
import ssl
import urllib.parse
import urllib.request


class IntegrationError(ValueError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise IntegrationError("Redirects are not permitted for integration requests.")


def request_json(method, url, payload=None, headers=None, form=False):
    """Bounded transport. Never follows a redirect carrying secrets or family data."""
    data = None
    merged = {"Accept": "application/json", **(headers or {})}
    if payload is not None:
        data = (urllib.parse.urlencode(payload) if form else json.dumps(payload)).encode()
        merged["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
    request = urllib.request.Request(url, data=data, headers=merged, method=method)
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect).open(request, timeout=25) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise IntegrationError("Integration response exceeds the size limit.")
            return json.loads(raw) if raw else {}
    except (OSError, ValueError) as exc:
        # Do not put provider responses, bearer tokens or URL query strings in logs.
        raise IntegrationError("The integration request failed; no success was recorded.") from exc


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def public_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return False
    parsed = urllib.parse.urlparse(value)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or parsed.username or parsed.password or not host or "." not in host:
        return False
    if host.lower().endswith((".local", ".localhost", ".internal", ".invalid", ".test")):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return bool(re.fullmatch(r"[A-Za-z0-9.-]+", host))


def public_addresses(host, port):
    """Reject private answers and pin one resolved address for the HTTPS request."""
    try:
        values = list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
    except OSError as exc:
        raise IntegrationError("The public lookup host could not be resolved.") from exc
    if not values or any(not ipaddress.ip_address(value).is_global for value in values):
        raise IntegrationError("Public lookup cannot connect to a private or loopback address.")
    return values


def public_request_json(method, url, payload=None, headers=None):
    """HTTPS without proxies, redirects or a second hostname resolution."""
    if not public_url(url):
        raise IntegrationError("Public lookup requires a public HTTPS endpoint.")
    parsed = urllib.parse.urlparse(url)
    port = parsed.port or 443
    address = public_addresses(parsed.hostname, port)[0]
    class PinnedConnection(http.client.HTTPSConnection):
        def connect(self):
            self.sock = socket.create_connection((address, port), timeout=self.timeout)
            self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)
    connection = PinnedConnection(parsed.hostname, port=port, timeout=25, context=ssl.create_default_context())
    try:
        data = json.dumps(payload).encode() if payload is not None else None
        connection.request(method, urllib.parse.urlunparse(("", "", parsed.path or "/", parsed.params, parsed.query, "")), body=data, headers={"Accept": "application/json", "Content-Type": "application/json", **(headers or {})})
        response = connection.getresponse()
        if not 200 <= response.status < 300:
            raise IntegrationError("The public lookup request failed; redirects are not followed.")
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise IntegrationError("Public lookup response exceeds the size limit.")
        return json.loads(raw)
    except (OSError, ValueError, http.client.HTTPException) as exc:
        raise IntegrationError("The public lookup request failed.") from exc
    finally:
        connection.close()


EMAIL = re.compile(r"(?<![\w.+-])[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}(?![\w.-])")
BLOCKED = {"noreply", "no-reply", "donotreply", "notifications", "marketing"}


class ProviderLookup:
    def __init__(self, search=None, audit=None):
        self.search = search
        self.audit = audit or (lambda **fields: None)

    @staticmethod
    def preview(provider, country):
        company = provider.get("display_name", "")
        # Only a server-curated company name is accepted, never a user-written query.
        if not re.fullmatch(r"[A-Za-z][A-Za-z '&().,-]{1,118}", company):
            raise IntegrationError("The curated provider name is not safe for public lookup.")
        if not re.fullmatch(r"[A-Z]{2}", country):
            raise IntegrationError("Choose a two-letter country code.")
        payload = {"company": company, "country": country}
        return {"payload": payload, "query": f"{company} {country} public bereavement claims contact", "preview_hash": digest(payload)}

    def lookup(self, provider, country, approved, actor, preview_hash):
        preview = self.preview(provider, country)
        if approved is not True or not isinstance(actor, str) or not actor.strip() or len(actor) > 100:
            raise IntegrationError("Explicit approval and the consenting person are required.")
        if preview_hash != preview["preview_hash"]:
            raise IntegrationError("The lookup changed. Review the company and country again.")
        if self.search is None:
            raise IntegrationError("Public lookup is not configured; no request was made.")
        record = {"kind": "provider_lookup", "approved_by": actor.strip(), "payload": preview["payload"], "query": preview["query"], "personal_field_count": 0}
        self.audit(**record, status="started")
        try:
            pages = self.search(preview["query"])
            if not isinstance(pages, list):
                raise IntegrationError("Lookup adapter returned an invalid result.")
            candidates = []
            for page in pages[:5]:
                if not isinstance(page, dict) or not public_url(page.get("url")):
                    continue
                text = page.get("text", "")
                if not isinstance(text, str) or len(text) > 40_000:
                    continue
                for match in EMAIL.finditer(text):
                    address = match.group()
                    if address.split("@")[0].lower() in BLOCKED:
                        continue
                    candidates.append({"provider_id": provider["provider_id"], "candidate_id": "lookup-" + digest([page["url"], address])[:20], "display_name": provider["display_name"], "aliases": provider.get("aliases", []), "channels": [{"kind": "email", "value": address, "label": "Public contact — please verify", "preferred": True}], "source_kind": "lookup", "evidence": [{"url": page["url"], "quote": address, "start": match.start(), "end": match.end()}], "confidence": 0.35, "verified_by_user": False})
                    if len(candidates) == 10:
                        break
                if len(candidates) == 10:
                    break
            self.audit(**record, status="completed", candidate_count=len(candidates))
            return {**preview, "candidates": candidates, "verified_by_user": False}
        except Exception as exc:
            self.audit(**record, status="failed")
            raise IntegrationError("Public lookup failed; no contact was verified.") from exc


class SearchAdapter:
    """Operator-configured HTTPS adapter: POST {query}; reply {pages:[{url,text}]}."""
    def __init__(self, endpoint, token="", transport=public_request_json):
        if not public_url(endpoint):
            raise IntegrationError("The search adapter requires a public HTTPS endpoint.")
        self.endpoint, self.token, self.transport = endpoint, token, transport

    def __call__(self, query):
        headers = {"Authorization": "Bearer " + self.token} if self.token else {}
        result = self.transport("POST", self.endpoint, {"query": query}, headers)
        return result.get("pages", [])
