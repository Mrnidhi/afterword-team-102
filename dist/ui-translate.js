/* Whole-page translation: pure lookup against the static dictionary in
   dist/ui-strings.js. No DOM access, so tests/ui-translate.test.cjs runs it
   under node. See MULTILINGUAL-PLAN.md phase 8. */
const AfterwordUiTranslate = (() => {
  const DIGITS = /\d+/g;
  const templateCache = new WeakMap();

  // An entry also serves the same string with different numbers ("2
  // completed" -> "3 completed") only when its translation carries the
  // source's digit runs unchanged and in the same order. Otherwise swapping
  // numbers in by position could move an amount or date to the wrong place,
  // and a wrong amount is the one thing this app must never display.
  function templatesFor(dict) {
    let templates = templateCache.get(dict);
    if (templates) return templates;
    templates = new Map();
    for (const [source, translation] of Object.entries(dict)) {
      const sourceDigits = source.match(DIGITS);
      if (!sourceDigits) continue;
      const translatedDigits = translation.match(DIGITS) || [];
      if (translatedDigits.length === sourceDigits.length && translatedDigits.every((d, i) => d === sourceDigits[i])) {
        templates.set(source.replace(DIGITS, '#'), translation);
      }
    }
    templateCache.set(dict, templates);
    return templates;
  }

  function lookup(dict, text) {
    if (!dict || typeof text !== 'string') return null;
    if (Object.hasOwn(dict, text)) return dict[text];
    const digits = text.match(DIGITS);
    if (!digits) return null;
    const translation = templatesFor(dict).get(text.replace(DIGITS, '#'));
    if (translation === undefined) return null;
    let i = 0;
    return translation.replace(DIGITS, () => digits[i++]);
  }

  return {lookup};
})();
