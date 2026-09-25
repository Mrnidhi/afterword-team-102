/* Browser-local demo state. This is not an encrypted archive or a backend. */
const AfterwordStore = (() => {
  const KEY = 'afterword-workspace-v3';
  const taskIds = ['insurance','storage','subscriptions','medical','bonds','notify-employer','gather-records'];
  const findingIds = ['insurance','medical','storage'];
  const memoryIds = ['tea','sunday','walk'];
  const object = v => v !== null && typeof v === 'object' && !Array.isArray(v);
  const text = (v, limit = 2000) => typeof v === 'string' ? v.slice(0, limit) : '';
  const ids = (v, allowed, fallback = []) => Array.isArray(v) ? [...new Set(v.filter(x => allowed.includes(x)))] : fallback;
  const validDate = v => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) && !Number.isNaN(Date.parse(v)) && new Date(v).toISOString().slice(0,10) === v;
  const languageIds = ['en','es','vi','hi'];
  const defaults = () => ({completed:['notify-employer','gather-records'],waiting:[],outreachReview:[],reviewed:[],favorite:[],drafts:{},lastDraft:'insurance',taskNotes:{},reminders:{},reviewNotes:{},reviewTimes:{},staged:[],imported:false,largeText:false,ambientMotion:true,lang:'en',activity:[]});
  function clean(input) {
    const d = defaults(), v = object(input) ? input : {};
    d.completed = ids(v.completed, taskIds, d.completed);
    d.waiting = ids(v.waiting, taskIds).filter(id => !d.completed.includes(id));
    d.reviewed = ids(v.reviewed, findingIds);
    d.outreachReview = ids(v.outreachReview, taskIds).filter(id => !d.completed.includes(id) && !d.waiting.includes(id));
    d.favorite = ids(v.favorite, memoryIds);
    d.largeText = v.largeText === true;
    d.ambientMotion = typeof v.ambientMotion === 'boolean' ? v.ambientMotion : true;
    d.imported = v.imported === true;
    d.lang = languageIds.includes(v.lang) ? v.lang : 'en';
    d.lastDraft = findingIds.includes(v.lastDraft) ? v.lastDraft : 'insurance';
    for (const id of taskIds) {
      if (object(v.taskNotes)) d.taskNotes[id] = text(v.taskNotes[id]);
      if (object(v.reminders) && validDate(v.reminders[id])) d.reminders[id] = v.reminders[id];
    }
    for (const id of findingIds) {
      if (object(v.reviewNotes)) d.reviewNotes[id] = text(v.reviewNotes[id]);
      if (object(v.reviewTimes) && typeof v.reviewTimes[id] === 'string' && Number.isFinite(Date.parse(v.reviewTimes[id]))) d.reviewTimes[id] = v.reviewTimes[id];
      const draft = object(v.drafts) && v.drafts[id];
      if (object(draft) && ['name','recipient','subject','body'].every(k => typeof draft[k] === 'string')) {
        d.drafts[id] = {name:text(draft.name,120),recipient:text(draft.recipient,200),subject:text(draft.subject,240),body:text(draft.body,12000)};
      }
    }
    // Migrate the single-draft prototype without trusting arbitrary stored keys.
    if (object(v.savedDraft) && findingIds.includes(v.savedDraft.template) && !d.drafts[v.savedDraft.template] && ['name','recipient','subject','body'].every(k => typeof v.savedDraft[k] === 'string')) {
      const old = v.savedDraft;
      if(!findingIds.includes(v.lastDraft))d.lastDraft=old.template;
      d.drafts[old.template] = {name:text(old.name,120),recipient:text(old.recipient,200),subject:text(old.subject,240),body:text(old.body,12000)};
    }
    d.staged = Array.isArray(v.staged) ? v.staged.filter(f => object(f) && /^local-[\w-]+$/.test(f.id) && typeof f.name === 'string' && Number.isFinite(f.size) && f.size > 0 && f.size <= 20*1024*1024).slice(0,20).map(f => ({id:f.id,name:text(f.name,255),size:f.size,type:text(f.type,20),added:text(f.added,40)})) : [];
    d.activity = Array.isArray(v.activity) ? v.activity.filter(a => object(a) && typeof a.text === 'string' && typeof a.at === 'string' && Number.isFinite(Date.parse(a.at))).slice(0,60).map(a => ({text:text(a.text,240),at:a.at})) : [];
    return d;
  }
  function load() {
    try {
      const current = localStorage.getItem(KEY);
      return clean(JSON.parse(current || localStorage.getItem('afterword-design-v2') || '{}'));
    } catch { return defaults(); }
  }
  function save(value) {
    try { localStorage.setItem(KEY, JSON.stringify({version:3,...clean(value)})); return true; }
    catch { return false; }
  }
  function validateFile(file) {
    if (!/\.(pdf|txt|csv|eml|md)$/i.test(file.name)) return 'Use a PDF, TXT, CSV, EML or Markdown file.';
    if (!file.size) return 'This file is empty.';
    if (file.size > 20*1024*1024) return 'This file exceeds the 20 MB limit.';
    return '';
  }
  return {KEY,defaults,clean,load,save,validateFile,validDate};
})();
