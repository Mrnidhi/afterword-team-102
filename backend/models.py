from typing import Literal, Optional
from pydantic import BaseModel, Field, ConfigDict

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Evidence(StrictModel):
    doc_id: Optional[str] = None
    quote: str = ''
    start: Optional[int] = None
    end: Optional[int] = None
    url: Optional[str] = None

class Channel(StrictModel):
    kind: Literal['email','phone','postal','portal']
    value: str
    label: str = 'Contact'
    preferred: bool = False

class Provider(BaseModel):
    provider_id: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    channels: list[Channel] = Field(default_factory=list)
    source_kind: Literal['records','directory','lookup','user']
    evidence: list[Evidence] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=1)
    verified_by_user: bool = False

class Outreach(BaseModel):
    id: str
    finding_id: str
    template_id: str
    recipient: str
    subject: str
    body: str
    attachments: list[str] = Field(default_factory=list)
    fields: dict[str,str] = Field(default_factory=dict)
    status: Literal['draft','waiting','replied'] = 'draft'
    created_at: str
    updated_at: str

class ConsentLog(BaseModel):
    id: str
    outreach_id: str
    actor: str
    channel: str
    snapshot_hash: str
    snapshot: dict
    disclosed_fields: list[str]
    recipient_confirmed: bool = False
    created_at: str

class ResolveRequest(StrictModel):
    finding_id: str = Field(min_length=1,max_length=100)
    provider_id: Optional[str] = None

class FamilyFields(StrictModel):
    writer_name: str = Field(default='',max_length=150)
    writer_phone: str = Field(default='',max_length=80)
    relationship: str = Field(default='',max_length=200)
    date_of_death: str = Field(default='',max_length=100)

class DraftRequest(StrictModel):
    finding_id: str
    provider_id: Optional[str] = None
    session_id: Optional[str] = None
    reference_id: Optional[str] = Field(default=None,max_length=100)
    template_id: Literal['policy_information','account_status','cancel_service','balance_confirmation','request_records']
    fields: FamilyFields = Field(default_factory=FamilyFields)
    recipient: Optional[str] = Field(default=None,max_length=254)

class EditRequest(StrictModel):
    provider_id: Optional[str] = None
    recipient: Optional[str] = Field(default=None,max_length=254)
    subject: Optional[str] = Field(default=None,max_length=200)
    body: Optional[str] = Field(default=None,max_length=10000)
    fields: Optional[FamilyFields] = None
    attachments: Optional[list[str]] = Field(default=None,max_length=12)

class ConsentRequest(StrictModel):
    snapshot_hash: str
    actor: str = Field(min_length=1,max_length=150)
    channel: Literal['gmail','mailto','copy','gmail-draft','gmail_api']
    recipient_confirmed: bool = False

class SentRequest(StrictModel):
    confirmed_sent: bool
    consent_id: Optional[str] = None
    actor: str = Field(default='Family member',min_length=1,max_length=150)

class RepliedRequest(StrictModel):
    confirmed_replied: bool = True
    actor: str = Field(default='Family member',min_length=1,max_length=150)

class MailboxRequest(StrictModel):
    email: str = Field(max_length=254)
    confirmed_control: bool

class IngestRequest(StrictModel):
    id: str = Field(min_length=1,max_length=120,pattern=r'^[\w.\-]+$')
    text: str = Field(min_length=1,max_length=2000000)
    provider_id: Optional[str] = None
    type: Literal['text','email','ocr'] = 'text'
    date: str = ''
    filename: Optional[str] = Field(default=None,max_length=255)
    title: Optional[str] = Field(default=None,max_length=255)
