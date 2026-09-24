# Fictional scanned-letter fixture

`cedar-life-scan.png` is a generated text document for repeatable OCR testing,
not a real provider record. Every contact uses reserved example data. The correct
email printed in the image is `claims@cedar-life.example`; the policy reference
is `Policy ending 4471`.

The actual Tesseract 5.5.3 development run misread the email as
`clains@cedar-life.example` and omitted the large `CEDAR LIFE` heading. Keep the
original fixture unchanged: that observed failure exercises the human correction
flow. Engine versions may produce different text. Tests assert readable source
facts and provenance, not a perfect transcription or a predetermined typo.

The raw OCR is retained separately from the reviewed correction. Exact matching
proves agreement with the approved text; it does not prove that OCR or a human
transcribed the image correctly. Compare the source image during review.

See `docs/outreach-ocr-verification.json` for the actual local browser/API result.
It is not evidence of a Nano model run or a live vision extraction.
