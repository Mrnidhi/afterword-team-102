"""Offline document intake for the finding/v1 contract.

Each emitted item is one source message or page. Its exact ``text`` is the
model input and must be stored unchanged by the extraction service.
"""
from __future__ import annotations

import base64
import binascii
import csv
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
import io
import mailbox
import math
from pathlib import Path
import re
import tempfile
import threading
import xml.etree.ElementTree as ET
import hashlib

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_BASE64_CHARS = 4 * math.ceil(MAX_UPLOAD_BYTES / 3)
MAX_DOCUMENTS = 100
MAX_TEXT_CHARS = 2_000_000
MAX_TOTAL_TEXT_BYTES = 20_000_000
MAX_IMAGE_PIXELS = 25_000_000
# Bound individual CSV fields as well as whole uploads. Python defaults to 128 KB.
csv.field_size_limit(MAX_TEXT_CHARS)
SUPPORTED_EXTENSIONS = ('.eml', '.mbox', '.csv', '.xml', '.txt', '.md', '.pdf', '.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff')


class IngestionError(ValueError):
    """An input cannot safely be interpreted; the message is safe for the UI."""


class DependencyUnavailable(IngestionError):
    """A required local parser/model is not installed. Never download it here."""


# The recovered team helper has no model or dataset work at import time. Its
# download/training routine is guarded by __main__ and is never invoked here.
from model.prep_public import group_lines


def decode_upload(filename: str, content_base64: str) -> bytes:
    if not filename or len(filename) > 255 or filename != Path(filename).name or '\\' in filename or any(ord(c) < 32 for c in filename):
        raise IngestionError('Use a filename without a directory or control characters.')
    if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise IngestionError('Supported files: EML, MBOX, SMS CSV/XML, text, PDF, PNG, JPEG, WebP and TIFF.')
    if not content_base64 or len(content_base64) > MAX_BASE64_CHARS:
        raise IngestionError('Choose a nonempty file no larger than 10 MB.')
    try:
        raw = base64.b64decode(content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise IngestionError('The upload is not valid base64.') from None
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise IngestionError('Choose a nonempty file no larger than 10 MB.')
    return raw


def _decode_text(raw: bytes) -> str:
    # UTF-16 exports are common on Windows; do not silently replace source bytes.
    encoding = 'utf-16' if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
    try:
        return raw.decode(encoding)
    except UnicodeDecodeError:
        raise IngestionError('Save this text export as UTF-8 or UTF-16 and try again.') from None


def _sms_csv_rows(raw):
    try:
        reader = csv.DictReader(io.StringIO(_decode_text(raw), newline=''), strict=True)
        if not reader.fieldnames or not {'date', 'sender', 'body'}.issubset(reader.fieldnames):
            raise IngestionError('SMS CSV must have date,sender,body column headers.')
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise IngestionError('SMS CSV has duplicate column headers.')
        rows = []
        for row in reader:
            if len(rows) >= MAX_DOCUMENTS:
                raise IngestionError('Split this export into files of at most 100 messages.')
            rows.append(row)
        return rows
    except csv.Error:
        raise IngestionError('This SMS CSV is malformed or contains a field larger than 2 MB. Export a smaller CSV and try again.') from None


class _HTMLText(HTMLParser):
    BLOCKS = {'p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'section', 'table', 'hr'}
    HIDDEN = {'script', 'style', 'head', 'noscript'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fragments = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.HIDDEN:
            self.hidden += 1
        elif not self.hidden and tag in self.BLOCKS:
            self.fragments.append('\n')

    def handle_endtag(self, tag):
        if tag in self.HIDDEN:
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden and tag in self.BLOCKS:
            self.fragments.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.fragments.append(data)

    def text(self):
        # HTML whitespace has display semantics; canonicalize once before storage.
        lines = [re.sub(r'[\t\r\f\v ]+', ' ', line).strip() for line in ''.join(self.fragments).splitlines()]
        return '\n'.join(line for line in lines if line)


def _message_body(message, warnings):
    if message.get_content_disposition() == 'attachment' or message.get_filename():
        return ''
    kind = message.get_content_type()
    if kind == 'message/rfc822':
        warnings.append('An attached email was not merged into this message; upload it separately.')
        return ''
    if message.is_multipart():
        parts = list(message.iter_parts())
        if message.get_content_subtype() == 'alternative':
            for preferred in ('text/plain', 'text/html'):
                for part in parts:
                    if part.get_content_type() == preferred:
                        body = _message_body(part, warnings)
                        if body.strip():
                            return body
            # Some alternatives wrap HTML with related images.
            for part in parts:
                body = _message_body(part, warnings)
                if body.strip():
                    return body
            return ''
        return '\n\n'.join(body for part in parts if (body := _message_body(part, warnings)).strip())
    if kind not in ('text/plain', 'text/html'):
        return ''
    payload = message.get_payload(decode=True)
    if payload is None:
        return ''
    charset = message.get_content_charset() or 'utf-8'
    try:
        body = payload.decode(charset, errors='strict')
    except (LookupError, UnicodeDecodeError):
        body = payload.decode('utf-8', errors='replace')
        warnings.append('An unknown or invalid email character encoding was decoded as UTF-8; review the source.')
    if kind == 'text/html':
        parser = _HTMLText()
        parser.feed(body)
        parser.close()
        return parser.text()
    return body


def _email_text(raw: bytes):
    message = BytesParser(policy=policy.default).parsebytes(raw)
    warnings = []
    body = _message_body(message, warnings)
    if not body.strip():
        raise IngestionError('This email has no readable message body. Save encrypted content or attachments separately.')
    headers = []
    for name in ('Subject', 'From', 'Date'):
        try:
            value = str(message.get(name, ''))
        except (ValueError, IndexError, AttributeError):
            value = next((value for key, value in message.raw_items() if key.lower() == name.lower()), '')
            warnings.append('A malformed email header needs review.')
        value = re.sub(r'[\r\n]+\s*', ' ', value)
        headers.append(f'{name}: {value}')
    if message.defects:
        warnings.append('The email export contains malformed MIME structure; review the extracted text.')
    return '\n'.join(headers) + '\n\n' + body, warnings


class RapidOCRCPU:
    """Lazy, serialized OCR with packaged local weights and CPU-only sessions."""

    def __init__(self):
        self._engine = None
        self._lock = threading.Lock()

    def _load(self):
        # The 1.4.4 package includes ONNX models; unlike newer rapidocr packages it
        # does not fetch weights during construction. All paths are checked first.
        try:
            import rapidocr_onnxruntime
            from rapidocr_onnxruntime import RapidOCR
        except ImportError:
            raise DependencyUnavailable('Install rapidocr-onnxruntime 1.4.4 and its bundled ONNX models before going offline.') from None
        root = Path(rapidocr_onnxruntime.__file__).resolve().parent
        paths = {
            'det_model_path': root / 'models/ch_PP-OCRv4_det_infer.onnx',
            'cls_model_path': root / 'models/ch_ppocr_mobile_v2.0_cls_infer.onnx',
            'rec_model_path': root / 'models/ch_PP-OCRv4_rec_infer.onnx',
        }
        if any(not path.is_file() for path in paths.values()):
            raise DependencyUnavailable('RapidOCR local ONNX assets are missing. Install the complete 1.4.4 package before going offline.')
        engine = RapidOCR(
            **{key: str(path) for key, path in paths.items()},
            det_use_cuda=False, cls_use_cuda=False, rec_use_cuda=False,
            det_use_dml=False, cls_use_dml=False, rec_use_dml=False,
            intra_op_num_threads=1, inter_op_num_threads=1,
        )
        # Fail closed if a differently configured package selected an accelerator.
        for session in (engine.text_det.infer.session, engine.text_cls.infer.session, engine.text_rec.session.session):
            providers = session.get_providers()
            if providers != ['CPUExecutionProvider']:
                self._engine = None
                raise DependencyUnavailable('RapidOCR must use only CPUExecutionProvider for this shared machine.')
        self._engine = engine

    def extract(self, image):
        with self._lock:
            if self._engine is None:
                self._load()
            result, _elapsed = self._engine(image)
            return '\n'.join(group_lines(result))


# PDFium is not thread-safe even for distinct documents. FastAPI runs sync
# handlers on different threads, so every native render and cleanup shares this
# process-wide lock, separately from the later serialized OCR/model stages.
_PDFIUM_LOCK = threading.Lock()


class PDFPages:
    def __init__(self, raw):
        try:
            from pypdf import PdfReader
        except ImportError:
            raise DependencyUnavailable('Install pypdf before importing PDF files offline.') from None
        try:
            self.reader = PdfReader(io.BytesIO(raw), strict=False)
            if self.reader.is_encrypted:
                raise IngestionError('Unlock this PDF and save a decrypted copy before importing it.')
            self.count = len(self.reader.pages)
        except IngestionError:
            raise
        except Exception:
            raise IngestionError('This PDF could not be read. Export a fresh PDF and try again.') from None
        self.raw = raw

    def text(self, index):
        return self.reader.pages[index].extract_text() or ''

    def image(self, index):
        try:
            import pypdfium2 as pdfium
        except ImportError:
            raise DependencyUnavailable('Install pypdfium2 to render scanned PDF pages offline.') from None
        with _PDFIUM_LOCK, pdfium.PdfDocument(self.raw) as document:
            page = document[index]
            try:
                width, height = page.get_size()
                scale = 2.0
                if width <= 0 or height <= 0 or width * height * scale * scale > MAX_IMAGE_PIXELS:
                    raise IngestionError('This PDF page is too large to render safely; export it at a smaller size.')
                bitmap = page.render(scale=scale)
                try:
                    return bitmap.to_pil().convert('RGB').copy()
                finally:
                    bitmap.close()
            finally:
                page.close()


class DocumentIngestor:
    def __init__(self, ocr=None, pdf_factory=None):
        self.ocr = ocr if ocr is not None else RapidOCRCPU()
        self.pdf_factory = pdf_factory or PDFPages

    def parse(self, filename: str, raw: bytes):
        if not raw or len(raw) > MAX_UPLOAD_BYTES:
            raise IngestionError('Choose a nonempty file no larger than 10 MB.')
        extension = Path(filename).suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise IngestionError('This file format is not supported.')
        checksum = hashlib.sha256(raw).hexdigest()
        documents, errors = [], []
        total_text = 0

        def document_id(position):
            return f'upload-{checksum[:32]}-{position:04d}'

        def emit(position, source, text, representation, warnings=None):
            nonlocal total_text
            if position > MAX_DOCUMENTS:
                raise IngestionError('Split this export into files of at most 100 messages or pages.')
            if not text.strip():
                raise IngestionError('No readable text was found in this item.')
            if '\x00' in text:
                raise IngestionError('The source contains binary null characters; export a plain-text copy.')
            text_bytes = len(text.encode('utf-8'))
            if len(text) > MAX_TEXT_CHARS or total_text + text_bytes > MAX_TOTAL_TEXT_BYTES:
                raise IngestionError('This item exceeds the text limit; split the source into smaller files.')
            total_text += text_bytes
            documents.append({'id': document_id(position), 'source': source, 'text': text,
                              'filename': filename, 'position': position,
                              'source_representation': representation,
                              'warnings': list(dict.fromkeys(warnings or []))})

        def error(position, exc):
            message = str(exc) if isinstance(exc, IngestionError) else 'This item could not be parsed. Check the original and try a fresh export.'
            errors.append({'id': document_id(position), 'position': position, 'message': message,
                           'retryable': isinstance(exc, DependencyUnavailable)})

        if extension == '.eml':
            try:
                text, warnings = _email_text(raw)
                emit(1, 'email', text, 'canonical_email', warnings)
            except Exception as exc:
                error(1, exc)
        elif extension == '.mbox':
            # mailbox expects a path. Keep the temporary source private and remove
            # it immediately after parsing; no uploaded binary is stored in Git.
            with tempfile.TemporaryDirectory(prefix='afterword-mbox-') as directory:
                path = Path(directory) / 'source.mbox'
                path.write_bytes(raw)
                path.chmod(0o600)
                box = mailbox.mbox(str(path), create=False)
                try:
                    if len(box) > MAX_DOCUMENTS:
                        raise IngestionError('Split this export into files of at most 100 messages.')
                    if not len(box):
                        raise IngestionError('This MBOX contains no messages.')
                    for position, key in enumerate(box.iterkeys(), 1):
                        try:
                            text, warnings = _email_text(box.get_bytes(key, from_=False))
                            emit(position, 'email', text, 'canonical_email', warnings)
                        except Exception as exc:
                            error(position, exc)
                finally:
                    box.close()
        elif extension == '.csv':
            for position, row in enumerate(_sms_csv_rows(raw), 1):
                if position > MAX_DOCUMENTS:
                    raise IngestionError('Split this export into files of at most 100 messages.')
                try:
                    if None in row or any(row.get(key) is None for key in ('date', 'sender', 'body')):
                        raise IngestionError('This SMS row has missing or extra CSV fields.')
                    if not row['body'].strip():
                        raise IngestionError('This SMS has an empty body.')
                    date = re.sub(r'[\r\n]+', ' ', row['date'])
                    sender = re.sub(r'[\r\n]+', ' ', row['sender'])
                    emit(position, 'sms', f'Date: {date}\nFrom: {sender}\n\n{row["body"]}', 'canonical_sms')
                except Exception as exc:
                    error(position, exc)
            if not documents and not errors:
                raise IngestionError('This SMS CSV contains no messages.')
        elif extension == '.xml':
            text = _decode_text(raw)
            if re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', text, re.I):
                raise IngestionError('XML declarations for DTDs or entities are not supported.')
            try:
                root = ET.fromstring(text)
            except ET.ParseError:
                raise IngestionError('This is not a readable SMS Backup & Restore XML export.') from None
            if root.tag != 'smses':
                raise IngestionError('Expected an SMS Backup & Restore XML file with a smses root.')
            messages = list(root)
            if not messages:
                raise IngestionError('This SMS XML contains no messages.')
            if len(messages) > MAX_DOCUMENTS:
                raise IngestionError('Split this export into files of at most 100 messages.')
            for position, sms in enumerate(messages, 1):
                try:
                    if sms.tag != 'sms':
                        raise IngestionError('Only SMS entries are supported; export MMS attachments separately.')
                    body, sender, stamp = sms.get('body', ''), sms.get('address', ''), sms.get('date', '')
                    if not body.strip():
                        raise IngestionError('This SMS has an empty body.')
                    try:
                        date = datetime.fromtimestamp(int(stamp) / 1000, timezone.utc).isoformat()
                    except (ValueError, OverflowError, OSError):
                        raise IngestionError('This SMS has an invalid millisecond timestamp.') from None
                    emit(position, 'sms', f'Date: {date}\nFrom: {sender}\n\n{body}', 'canonical_sms')
                except Exception as exc:
                    error(position, exc)
        elif extension in ('.txt', '.md'):
            try:
                emit(1, 'letter', _decode_text(raw), 'plain_text')
            except Exception as exc:
                error(1, exc)
        elif extension == '.pdf':
            pages = self.pdf_factory(raw)
            if not pages.count or pages.count > MAX_DOCUMENTS:
                raise IngestionError('Choose a PDF with between 1 and 100 pages.')
            for index in range(pages.count):
                try:
                    warnings = []
                    try:
                        text = pages.text(index)
                    except Exception:
                        text = ''
                        warnings.append('PDF text extraction failed; this page was read with local OCR.')
                    representation = 'pdf_text'
                    if not text.strip():
                        image = pages.image(index)
                        try:
                            text = self.ocr.extract(image)
                        finally:
                            image.close()
                        representation = 'rapidocr_cpu'
                        warnings.append('OCR can misread characters; review the cited source lines.')
                    emit(index + 1, 'letter', text, representation, warnings)
                except Exception as exc:
                    error(index + 1, exc)
        else:
            try:
                from PIL import Image, ImageOps
                with Image.open(io.BytesIO(raw)) as image:
                    frames = getattr(image, 'n_frames', 1)
                    if frames > MAX_DOCUMENTS:
                        raise IngestionError('Split this image into files of at most 100 pages.')
                    for index in range(frames):
                        try:
                            image.seek(index)
                            if image.width * image.height > MAX_IMAGE_PIXELS:
                                raise IngestionError('This image is too large; use an image under 25 megapixels.')
                            with ImageOps.exif_transpose(image).convert('RGB') as frame:
                                text = self.ocr.extract(frame)
                            emit(index + 1, 'letter', text, 'rapidocr_cpu', ['OCR can misread characters; review the cited source lines.'])
                        except Exception as exc:
                            error(index + 1, exc)
            except IngestionError:
                raise
            except Exception:
                raise IngestionError('This image could not be read. Export a PNG or JPEG and try again.') from None
        return {'filename': filename, 'upload_sha256': checksum, 'documents': documents, 'errors': errors,
                'document_count': len(documents), 'error_count': len(errors), 'cloud_calls': 0}
