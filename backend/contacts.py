"""Evidence-bound local contact extraction. Offsets always refer to original text."""
import re
from datetime import date

EMAIL = re.compile(r'(?<![\w.+-])[A-Z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9-]*[A-Z0-9])?(?:\.[A-Z0-9](?:[A-Z0-9-]*[A-Z0-9])?)+',re.I)
PHONE = re.compile(r'(?<!\w)(?:\+\d{1,3}[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)')
NO_REPLY = re.compile(r'^(?:no[-_.]?reply|do[-_.]?not[-_.]?reply|notifications?|marketing)(?:[+._-]|$)',re.I)
ROLE = re.compile(r'(?:claims|bereavement|estates|support|service)',re.I)


def valid_email(value):
    return isinstance(value,str) and len(value)<=254 and EMAIL.fullmatch(value) is not None and '\r' not in value and '\n' not in value


def blocked_email(value):
    return not valid_email(value) or NO_REPLY.match(value.split('@')[0]) is not None


def fictional_email(value):
    domain = value.rsplit('@',1)[-1].lower()
    return domain.endswith(('.example','.invalid','.test','.localhost')) or domain in {'example.com','example.org','example.net','localhost'}


def canonical_provider(document, directory):
    explicit = document.get('provider_id')
    if explicit in directory:
        return explicit
    # Exact names/aliases only; no edit-distance match can establish identity.
    text = document.get('text','')
    matches=[]
    for key,provider in directory.items():
        names=[provider['display_name'],*provider.get('aliases',[])]
        if any(re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',text,re.I) for name in names if len(name)>3):
            matches.append(key)
    return matches[0] if len(matches)==1 else None


def email_matches_provider(email, provider, controlled_alias=None):
    if controlled_alias and email.lower()==controlled_alias.lower():
        return True
    if any(c.get('kind')=='email' and c['value'].lower()==email.lower() for c in provider.get('channels',[])):
        return True
    domain=email.rsplit('@',1)[-1].lower()
    return domain in [d.lower() for d in provider.get('domains',[])]


def mine_contacts(document, directory, controlled_aliases=None):
    text=document.get('text','')
    provider_id=canonical_provider(document,directory)
    if not provider_id:
        return []
    provider=directory[provider_id]
    ranges=[]
    is_email=document.get('type') in {'email','eml'}
    if is_email:
        separator=re.search(r'\r?\n\r?\n',text)
        header_end=separator.start() if separator else 0
        for header in re.finditer(r'^(From|Reply-To|Return-Path):[^\r\n]*(?:\r?\n[ \t]+[^\r\n]*)*',text[:header_end],re.I|re.M):
            ranges.append((header.start(),header.end(),'Email header'))
        body_start=separator.end() if separator else 0
        lines=list(re.finditer(r'^.*$',text[body_start:],re.M))
        footer_start=body_start+(lines[-15].start() if len(lines)>=15 else 0)
        ranges.append((footer_start,len(text),'Email footer'))
    else:
        # Native text and verified OCR: extractor never creates characters.
        ranges.append((0,len(text),'Document contact'))
    candidates=[]
    seen=set()
    for start,end,label in ranges:
        for pattern,kind in [(EMAIL,'email'),(PHONE,'phone')]:
            for match in pattern.finditer(text,start,end):
                value=match.group()
                key=(kind,value.lower())
                if key in seen or (kind=='email' and (blocked_email(value) or not email_matches_provider(value,provider,(controlled_aliases or {}).get(provider_id)))):
                    continue
                seen.add(key)
                candidates.append({
                    'candidate_id':f"record:{document['id']}:{match.start()}",
                    'provider_id':provider_id,'display_name':provider['display_name'],'aliases':provider.get('aliases',[]),
                    'channels':[{'kind':kind,'value':value,'label':label,'preferred':kind=='email' and bool(ROLE.search(value.split('@')[0]))}],
                    'source_kind':'records','evidence':[{'doc_id':document['id'],'quote':value,'start':match.start(),'end':match.end()}],
                    'confidence':1.0,'verified_by_user':False,'document_date':document.get('date','')
                })
    return candidates


def rank_candidate(candidate):
    email=next((c['value'] for c in candidate.get('channels',[]) if c['kind']=='email'),'')
    try:
        recency=date.fromisoformat(candidate.get('document_date','')[:10]).toordinal()
    except ValueError:
        recency=0
    return ({'records':0,'directory':1,'lookup':2,'user':3}.get(candidate.get('source_kind'),9),not bool(ROLE.search(email.split('@')[0])),-recency,email.lower())


def canonicalize_email(document):
    """Decode plain MIME bodies while retaining immutable raw source and its digest.

    Evidence offsets point into stored canonical text, which is displayed to the
    user. Attachments and HTML-only bodies are not silently treated as plain text.
    """
    if document.get('type')!='email':
        return document
    from email import policy
    from email.parser import Parser
    import hashlib
    raw=document.get('text','')
    message=Parser(policy=policy.default).parsestr(raw)
    if not message.get('Content-Transfer-Encoding') and not message.is_multipart():
        return document
    part=message.get_body(preferencelist=('plain',)) if message.is_multipart() else message
    if part is None or part.get_content_type()!='text/plain':
        return {**document,'source_representation':'raw_email','ingest_warning':'No plain text MIME body was found; HTML and attachments were not inspected.'}
    try:
        body=part.get_content()
    except (LookupError,UnicodeError,ValueError):
        return {**document,'source_representation':'raw_email','ingest_warning':'The message encoding could not be decoded; inspect the original message.'}
    headers='\n'.join(key+': '+str(value) for key,value in message.items() if key.lower() in {'from','reply-to','return-path','subject','date'})
    return {**document,'raw_text':raw,'raw_sha256':hashlib.sha256(raw.encode()).hexdigest(),'text':headers+'\n\n'+body,'source_representation':'decoded_email_text'}
