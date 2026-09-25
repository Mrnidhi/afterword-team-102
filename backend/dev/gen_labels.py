"""Phase 7 (L9): generates the raw candidates for dist/i18n.js's UI_LABELS
table by calling the live /translate endpoint on the 12 chosen chrome
strings. Output is the *unreviewed* model output, saved to labels_raw.json
for the record — the final table in i18n.js was hand-corrected afterward
(see the comment above UI_LABELS there for what was wrong and why)."""
import json
import urllib.request
from pathlib import Path

LABELS = [
    "Overview", "Action plan", "Documents", "Evidence review", "Letters",
    "Memories", "Privacy", "Activity", "Settings",
    "Save draft", "Print letter", "Open in Gmail",
]
LANGS = ["es", "vi", "hi"]

results = {lang: {} for lang in LANGS}
for text in LABELS:
    for lang in LANGS:
        body = json.dumps({"text": text, "target_lang": lang, "kind": "instruction"}).encode()
        req = urllib.request.Request(
            "http://localhost:8010/translate", data=body,
            headers={"content-type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.load(r)
        results[lang][text] = data
        print(f"{lang:3} | {text:20} -> {data['text']!r:30} score={data['round_trip_score']:.3f} tokens_ok={data['protected_tokens_ok']} low_conf={data['low_confidence']}")

with open(Path(__file__).resolve().parent / "labels_raw.json", "w") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
