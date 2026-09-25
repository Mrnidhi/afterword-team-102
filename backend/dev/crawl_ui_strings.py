"""Phase 8: builds the source list for the whole-page translation dictionary.

Drives the real frontend (served same-origin by the backend on :8010) through
every page and dialog in headless Firefox and calls dist/i18n.js's own
collectUiStrings() -- the exact rules the runtime translator applies -- so the
list can't drift from what actually gets translated. Crawls in each language
because some chrome only renders outside English (the "For you to read"
column, the translated-block labels). Toasts and status text only appear after
specific actions, so those are also pulled straight from the JS source.

Needs the stack running (see HANDOFF.md), and Selenium -- present in the base
miniforge python, not the zgx env. Output: ui_strings_source.json.
  /home/hp24/miniforge3/bin/python3 backend/dev/crawl_ui_strings.py

After generating the dictionary, --check walks the same pages with
translation on and lists every string still showing in English:
  /home/hp24/miniforge3/bin/python3 backend/dev/crawl_ui_strings.py --check [es vi hi]
"""
import json
import re
import sys
import tempfile
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / 'ui_strings_source.json'
URL = 'http://127.0.0.1:8010/'
FIREFOX = '/snap/firefox/8926/usr/lib/firefox/firefox'

ROUTES = ['overview', 'plan', 'documents', 'evidence?finding=insurance', 'evidence?finding=medical',
          'evidence?finding=storage', 'letters?template=insurance', 'letters?template=medical',
          'letters?template=storage', 'memories', 'exposure', 'ledger', 'settings', 'ask']
TASKS = ['insurance', 'storage', 'subscriptions', 'medical', 'bonds', 'notify-employer', 'gather-records']
RECORDS = ['policy', 'will', 'storage', 'statement', 'medical', 'receipt', 'voice', 'pension']
MEMORIES = ['tea', 'sunday', 'walk']


class Crawler:
    def __init__(self, check=False):
        # check=True: leave translation on and report what still shows in
        # English, instead of collecting source strings.
        self.check = check
        opts = Options()
        opts.binary_location = FIREFOX
        opts.add_argument('--headless')
        # The export dialogs trigger real downloads; keep them out of ~/Downloads.
        opts.set_preference('browser.download.folderList', 2)
        opts.set_preference('browser.download.dir', tempfile.mkdtemp(prefix='afterword-crawl-'))
        opts.set_preference('browser.download.useDownloadDir', True)
        self.driver = webdriver.Firefox(options=opts)
        self.driver.set_window_size(1440, 1000)
        self.strings = set()

    def js(self, script, *args):
        return self.driver.execute_script(script, *args)

    def collect(self, pause=0.6):
        time.sleep(pause)
        if not self.check:
            self.strings.update(self.js('return window.collectUiStrings()'))

    def start(self, lang):
        self.driver.get(URL + '#overview')
        time.sleep(1)
        self.js("localStorage.setItem('afterword-workspace-v3', JSON.stringify({lang: arguments[0]}))", lang)
        self.driver.refresh()  # not get(): a same-URL get() never re-runs scripts here (phase 3)
        time.sleep(1.5)
        if not self.check:
            self.js('window.AFTERWORD_I18N_CRAWL = true; render();')

    def misses(self):
        return self.js('return window.uiTranslationMisses()')

    def route(self, route):
        self.js('location.hash = arguments[0]', route)
        self.collect(1.2 if route.startswith(('letters', 'evidence')) else 0.6)

    def click(self, selector):
        els = self.driver.find_elements(By.CSS_SELECTOR, selector)
        if els:
            self.js('arguments[0].click()', els[0])
        return bool(els)

    def dialog(self, script):
        self.js(script)
        self.collect()
        self.js("document.getElementById('detail-dialog').close()")

    def type_into(self, selector, text):
        el = self.driver.find_element(By.CSS_SELECTOR, selector)
        el.clear()
        el.send_keys(text)

    def crawl(self, lang):
        self.start(lang)
        for r in ROUTES:
            self.route(r)

        self.route('plan')
        for f in ['all', 'ready', 'review', 'waiting', 'done']:
            self.click(f'[data-action="filter-plan"][data-filter="{f}"]')
            self.collect()
        self.type_into('#plan-search', 'zzzz')
        self.collect()

        self.route('documents')
        self.type_into('#document-search', 'zzzz')
        self.collect()

        self.route('ledger')
        self.type_into('#activity-search', 'zzzz')
        self.collect()

        self.route('memories')
        self.click('[data-action="memory-filter"][data-filter="saved"]')
        self.collect()

        for t in TASKS:
            self.dialog(f'openTask({t!r})')
        for r in RECORDS:
            self.dialog(f'openDocument({r!r})')
        for m in MEMORIES:
            self.route('memories')
            self.click(f'[data-action="read-memory"][data-id="{m}"]')
            self.collect()
            self.js("document.getElementById('detail-dialog').close()")
        self.dialog('openImport()')
        self.dialog("document.querySelector('[data-action=\"preferences\"]').click()")
        self.dialog("window.actions['workspace-info']()")
        self.dialog("window.actions['connection-help']?.()")
        self.route('exposure')
        self.dialog("window.actions['inspect-payload']()")
        self.route('settings')
        self.dialog("window.actions['reset-workspace']()")
        self.route('letters?template=insurance')
        self.dialog("window.actions['reset-letter']()")
        self.click('[data-action="letter-preview"]')
        self.collect(1.2)
        self.click('[data-action="letter-preview"]')

        self.js("document.querySelector('[data-action=\"command\"]').click()")
        self.collect()
        self.type_into('#command-input', 'insurance')
        self.collect()
        self.js("document.getElementById('detail-dialog').close()")

        self.route('ask')
        for i in range(4):
            self.click(f'[data-action="sample-question"][data-index="{i}"]')
            self.collect()
        self.type_into('#ask-input', 'What is the weather tomorrow?')
        self.js("document.getElementById('ask-form').requestSubmit()")
        self.collect()

        # Export dialogs (the file download itself is harmless in a test profile).
        for route, action in [('plan', 'export-plan'), ('evidence?finding=insurance', 'export-evidence'),
                              ('ledger', 'export-ledger'), ('exposure', 'export-exposure'),
                              ('settings', 'export-workspace'), ('letters?template=insurance', 'download-letter')]:
            self.route(route)
            self.dialog(f"window.actions[{action!r}]()")
        for template in ('medical', 'storage'):
            self.route(f'letters?template={template}')
            self.dialog("window.actions['reset-letter']()")

        # Task buttons and statuses change once a task is waiting or done.
        self.route('plan')
        self.js("openTask('storage'); window.actions['task-wait']()")
        self.collect()
        self.dialog("openTask('storage')")
        self.js("openTask('subscriptions'); window.actions['task-complete']()")
        self.collect()
        self.dialog("openTask('subscriptions')")

        # A second pass after importing the sample letter: the library, the
        # overview count and the import dialog all change wording.
        self.route('documents')
        self.dialog('openImport()')
        self.js("window.actions['sample-import']()")
        self.collect(1.0)
        self.dialog('openImport()')

    def close(self):
        self.driver.quit()


# Only on screen for a moment (a translation loading) or when something is
# down, so a crawl rarely sees them. Kept in sync with dist/i18n.js by hand.
TRANSIENT = [
    'Translating on this device…',
    "Couldn't translate right now. The English above is complete.",
    "The Afterword device isn't reachable right now. The English above is complete.",
]


def source_strings():
    """Toasts and status messages only render after specific actions; take
    their literals straight from the JS instead. Fragments of a concatenation
    (leading or trailing space, e.g. ' of 3 drafts') are skipped -- the crawl
    captures those from the rendered page, whole."""
    found = set()
    call = re.compile(r'(?:toast|saveNotice)\(|\.textContent\s*=')
    literal = re.compile(r"'((?:[^'\\]|\\.)*)'")
    for path in (ROOT / 'dist').glob('*.js'):
        if path.name in ('ui-strings.js', 'ui-translate.js'):
            continue
        src = path.read_text()
        for m in call.finditer(src):
            end = src.find(';', m.end())
            for s in literal.findall(src[m.end():end if end > 0 else m.end() + 400]):
                s = s.replace("\\'", "'")
                # Needs a space: single tokens here are action ids and
                # selectors ('task-wait', 'import'), never visible text.
                if ' ' in s and re.search(r'[A-Za-z]', s) and s == s.strip() and '#' not in s:
                    found.add(re.sub(r'\s+', ' ', s))
    return found


def check_coverage(langs):
    """Walks every page and dialog with translation on and prints whatever
    still showed in English (the page's own uiTranslationMisses())."""
    for lang in langs:
        crawler = Crawler(check=True)
        try:
            crawler.crawl(lang)
            misses = sorted(crawler.misses())
        finally:
            crawler.close()
        print(f'{lang}: {len(misses)} strings still in English')
        for m in misses:
            print('   ', repr(m))


def main():
    if '--check' in sys.argv:
        return check_coverage([a for a in sys.argv[1:] if not a.startswith('--')] or ['es', 'vi', 'hi'])
    crawler = Crawler()
    try:
        for lang in ('en', 'es', 'vi', 'hi'):
            crawler.crawl(lang)
            print(f'after {lang}: {len(crawler.strings)} strings', flush=True)
    finally:
        crawler.close()
    strings = crawler.strings | source_strings() | set(TRANSIENT)
    OUT.write_text(json.dumps(sorted(strings), ensure_ascii=False, indent=1))
    print(f'wrote {len(strings)} strings to {OUT}')


if __name__ == '__main__':
    main()
