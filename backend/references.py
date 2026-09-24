"""Source-bound account references. Last-four matches never establish identity."""
import hashlib
import json
import re

from .contacts import canonical_provider

# Conservatively support labelled, contiguous references and numeric space groups.
# A source occurrence is its own choice: two accounts ending alike are not merged.
REFERENCE=re.compile(r'\b(?P<kind>policy|account|reference)\s*[:#=-]?\s*(?P<mode>ending|number|no\.?|id|#)?\s*[:#=-]?\s*(?P<token>[A-Z0-9][A-Z0-9-]{3,39}(?:[ \t]+\d{2,16})*)\b',re.I)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def source_references(documents,directory,provider_ids):
    allowed=set(provider_ids)
    references=[]
    for document in documents:
        provider_id=canonical_provider(document,directory)
        if not provider_id or provider_id not in allowed:
            continue
        text=document.get('text','')
        source_hash=hashlib.sha256(text.encode()).hexdigest()
        for match in REFERENCE.finditer(text):
            token=match.group('token')
            if not re.search(r'\d',token):
                continue
            normalized=re.sub(r'[^A-Za-z0-9]','',token)
            tail=text[match.end():]
            # Never accept a prefix of a format we do not support. The source
            # must actually terminate here, rather than continue through a slash,
            # punctuation-separated segment or an oversized spaced group.
            continued=bool(tail and (tail[0].isalnum() or tail[0] in '-/_\\:+@#='))
            continued=continued or bool(len(tail)>1 and tail[0]=='.' and tail[1].isalnum())
            next_group=re.match(r'[ \t]+([^ \t\r\n,;]+)',tail)
            continued=continued or bool(next_group and re.search(r'\d',next_group.group(1)))
            if len(normalized)<4 or len(normalized)>40 or continued:
                continue
            kind=match.group('kind').lower()
            evidence={'doc_id':document['id'],'quote':match.group(),'start':match.start(),'end':match.end()}
            ident='ref-'+digest([provider_id,source_hash,evidence])
            references.append({'id':ident,'provider_id':provider_id,'kind':kind,'masked_identifier':kind+' ending '+normalized[-4:],'evidence':[evidence],'source_sha256':source_hash,'source_title':document.get('title') or document.get('filename') or document['id'],'source_date':document.get('date',''),'partial_source':str(match.group('mode')).lower()=='ending','source_representation':document.get('source_representation','native_text')})
    return sorted(references,key=lambda row:(row['provider_id'],row['source_title'],row['evidence'][0]['start']))


def reference_is_current(reference,documents,directory,provider_id):
    if not reference or reference.get('provider_id')!=provider_id:
        return False
    return any(candidate==reference for candidate in source_references(documents,directory,[provider_id]))
