/* Local, selectable-text PDF exports. Dependencies load only when an export is requested. */
(function (root, factory) {
  const api = factory(root, typeof module === 'object' && !!module.exports);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.AfterwordReports = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function (root, isNode) {
  'use strict';
  const assetBase = !isNode && root.document.currentScript ? root.document.currentScript.src : '';
  const color = { ink:'#18212C', muted:'#536171', blue:'#195BA6', line:'#D8DFE7' };
  let dependencies;
  const plain = value => typeof value === 'string' ? value : typeof value === 'number' && Number.isFinite(value) ? String(value) : '';
  const present = (value, fallback = 'Not recorded') => plain(value).trim() ? plain(value) : fallback;

  function loadScript(path) {
    return new Promise((resolve, reject) => {
      const script = root.document.createElement('script');
      script.src = new URL(path, assetBase || root.location.href).href;
      script.onload = resolve;
      script.onerror = () => { script.remove(); reject(new Error('PDF export files could not load. Reconnect to the Afterword site and try again.')); };
      root.document.head.appendChild(script);
    });
  }
  function getDependencies() {
    if (!dependencies) dependencies = (async () => {
      const engine = isNode ? require('./vendor/pdfmake.min.js') : (root.pdfMake || (await loadScript('vendor/pdfmake.min.js'), root.pdfMake));
      const fonts = isNode ? require('./vendor/report-fonts.js') : (root.AfterwordReportFonts || (await loadScript('vendor/report-fonts.js'), root.AfterwordReportFonts));
      if (!engine || !fonts) throw new Error('PDF export files are unavailable. Reload Afterword and try again.');
      engine.addVirtualFileSystem(fonts.vfs);
      engine.addFonts({
        Noto:{normal:'NotoSans-Regular.ttf',bold:'NotoSans-Bold.ttf',italics:'NotoSans-Regular.ttf',bolditalics:'NotoSans-Bold.ttf'},
        Devanagari:{normal:'NotoSansDevanagari-Regular.ttf',bold:'NotoSansDevanagari-Bold.ttf',italics:'NotoSansDevanagari-Regular.ttf',bolditalics:'NotoSansDevanagari-Bold.ttf'},
        Symbols:{normal:'NotoSansSymbols2-Regular.ttf',bold:'NotoSansSymbols2-Regular.ttf',italics:'NotoSansSymbols2-Regular.ttf',bolditalics:'NotoSansSymbols2-Regular.ttf'}
      });
      return { engine, fonts };
    })().catch(error => { dependencies = null; throw error; });
    return dependencies;
  }

  function validExportDate(value) {
    if (value === undefined) return new Date();
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T/.test(value) || !Number.isFinite(Date.parse(value))) throw new Error('The report export date must be an ISO timestamp.');
    return new Date(value);
  }
  function displayTimestamp(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value) || !Number.isFinite(Date.parse(value))) return present(value);
    return new Date(value).toISOString().replace('T',' ').replace(/\.\d{3}Z$/, ' UTC');
  }
  function hasCodePoint(ranges, codepoint) {
    let low = 0, high = (ranges || []).length - 1;
    while (low <= high) {
      const mid = (low + high) >>> 1, range = ranges[mid];
      if (codepoint < range[0]) high = mid - 1;
      else if (codepoint > range[1]) low = mid + 1;
      else return true;
    }
    return false;
  }

  // pdfmake treats every value below as text, never HTML or a document-definition object.
  // Unsupported glyphs stay visible as code points rather than becoming blank squares.
  function textWriter(coverage) {
    const unsupported = new Set();
    function text(value, bold = false) {
      const runs = [];
      function append(value, font) {
        if (runs.length && runs[runs.length - 1].font === font) runs[runs.length - 1].text += value;
        else runs.push({text:value,font,bold});
      }
      for (const ch of plain(value).replace(/\r\n?/g,'\n')) {
        const cp = ch.codePointAt(0), weight = bold ? 'Bold' : 'Regular';
        const printable = cp >= 32 && !(cp >= 0x7f && cp <= 0x9f);
        let font;
        if (/^[\n\t ]$/.test(ch) || cp === 0x200c || cp === 0x200d) font = runs.length ? runs[runs.length-1].font : 'Noto';
        else if (printable && hasCodePoint(coverage['NotoSans-'+weight+'.ttf'],cp)) font = 'Noto';
        else if (printable && hasCodePoint(coverage['NotoSansDevanagari-'+weight+'.ttf'],cp)) font = 'Devanagari';
        else if (printable && hasCodePoint(coverage['NotoSansSymbols2-Regular.ttf'],cp)) font = 'Symbols';
        if (font) append(ch === '\t' ? '    ' : ch,font);
        else {
          const code = 'U+' + cp.toString(16).toUpperCase().padStart(4,'0');
          unsupported.add(code); append('['+code+']','Noto');
        }
      }
      return runs.length ? runs : [{text:'',font:'Noto'}];
    }
    return {text,unsupported};
  }

  function buildDefinition(kind, input, coverage) {
    if (!['plan','activity'].includes(kind)) throw new Error('Unknown report type.');
    if (!input || !Array.isArray(input.items) || input.items.some(item => !item || typeof item !== 'object' || Array.isArray(item))) throw new Error('A report needs a list of saved records.');
    if (!['preview','live'].includes(input.mode)) throw new Error('Choose the source workspace for this report.');
    const generated = validExportDate(input.exportedAt);
    const reportTitle = kind === 'plan' ? 'Action plan' : 'Workspace activity';
    const sample = input.mode === 'preview';
    const writer = textWriter(coverage), t = writer.text;
    const sourceNotice = sample ? 'Sample workspace - fictional records. Notes and changes are saved in this browser.' : 'Local workspace - exported records and browser-saved changes.';
    const scope = plain(input.scope);
    const content = [
      {text:'AFTERWORD',color:color.blue,fontSize:9,bold:true,characterSpacing:1.8,margin:[0,0,0,12]},
      {text:reportTitle,fontSize:27,bold:true,margin:[0,0,0,8]},
      {text:'Exported '+displayTimestamp(generated.toISOString()),style:'muted',margin:[0,0,0,5]},
      {text:t(sourceNotice),style:'muted',margin:[0,0,0,4]},
      ...(scope ? [{text:t(scope),style:'muted',margin:[0,0,0,4]}] : []),
      {text:kind === 'plan' ? 'Review original records before acting. Amounts and dates may need confirmation.' : 'This report reproduces the available recorded updates. It is a workspace history, not an independently verified audit trail.',style:'muted',margin:[0,0,0,4]},
      {text:`${input.items.length} ${kind === 'plan' ? 'action' : 'update'}${input.items.length === 1 ? '' : 's'} in this export`,fontSize:10,bold:true,margin:[0,10,0,20]}
    ];
    const introEnd = content.length - 1;
    function line(label, value, fallback) {
      return {columns:[{text:label,width:100,color:color.muted,fontSize:9},{text:t(present(value,fallback)),width:'*'}],columnGap:10,margin:[0,0,0,3]};
    }
    input.items.forEach((item,index) => {
      content.push({canvas:[{type:'line',x1:0,y1:0,x2:499.28,y2:0,lineWidth:.65,lineColor:color.line}],margin:[0,index ? 14 : 0,0,12]});
      if (kind === 'plan') {
        content.push({text:t(String(index+1).padStart(2,'0')+'  '+present(item.title,'Untitled action'),true),style:'itemHeading',headlineLevel:1});
        content.push(line('Status',item.status),line('Category',item.category),line('Date / reminder',item.date),line('Source',item.source),line('Amount',item.amount,'Not recorded'));
        if (plain(item.id)) content.push(line('Record ID',item.id));
        if (plain(item.details)) content.push({text:t(item.details),style:'muted',margin:[0,3,0,7]});
        if (plain(item.note).trim()) content.push({text:'Your note',fontSize:9,bold:true,margin:[0,6,0,4]},{text:t(item.note),margin:[0,0,0,8]});
      } else {
        content.push({text:t(present(item.text,'Recorded update'),true),style:'itemHeading',headlineLevel:1});
        content.push(line('Recorded at',displayTimestamp(item.at)));
        if (plain(item.status)) content.push(line('Status',item.status));
        if (plain(item.source)) content.push(line('Source',item.source));
        if (plain(item.id)) content.push(line('Record ID',item.id));
        if (plain(item.details)) content.push({text:t(item.details),margin:[0,3,0,7]});
      }
    });
    if (!input.items.length) content.push({text:kind === 'plan' ? 'There are no actions in this view.' : 'There are no recorded updates in this view.',fontSize:13,margin:[0,15,0,20]});
    if (writer.unsupported.size) content.splice(introEnd,0,{text:'Character note: the embedded fonts support English, Spanish, Vietnamese, Hindi and common symbols. Other characters are preserved as visible Unicode codes, such as [U+4E2D], rather than omitted.',style:'muted',margin:[0,0,0,4]});
    return {
      pageSize:'A4',pageMargins:[48,48,48,52],compress:true,
      info:{title:reportTitle+' - Afterword',author:'Afterword',subject:sample?'Sample workspace report':'Local workspace report',creator:'Afterword local PDF export',creationDate:generated},
      defaultStyle:{font:'Noto',fontSize:10,color:color.ink,lineHeight:1.25},
      styles:{muted:{fontSize:8.5,color:color.muted,lineHeight:1.3},itemHeading:{fontSize:12,bold:true,margin:[0,0,0,11]}},
      footer:(page,pages)=>({columns:[{text:'Afterword / '+reportTitle,color:color.muted},{text:page+' / '+pages,alignment:'right',color:color.muted}],fontSize:8,margin:[48,15,48,0]}),
      pageBreakBefore:(node,following)=>node.headlineLevel === 1 && (following.length === 0 || node.startPosition.top > 640),
      content
    };
  }

  async function generate(kind,input) {
    const {engine,fonts} = await getDependencies();
    const definition = buildDefinition(kind,input,fonts.coverage);
    return new Promise((resolve,reject) => {
      try { engine.createPdf(definition).getBuffer(buffer => resolve(new Uint8Array(buffer))); }
      catch (error) { reject(error); }
    });
  }
  async function download(kind,input) {
    if (!root.document || !root.URL || !root.Blob) throw new Error('A browser is needed to download this PDF.');
    const bytes = await generate(kind,input);
    const filename = kind === 'plan' ? 'afterword-action-plan.pdf' : 'afterword-workspace-activity.pdf';
    const url = root.URL.createObjectURL(new Blob([bytes],{type:'application/pdf'}));
    const anchor = root.document.createElement('a');
    anchor.href = url; anchor.download = filename; anchor.hidden = true;
    root.document.body.appendChild(anchor);
    anchor.click(); anchor.remove();
    root.setTimeout(()=>root.URL.revokeObjectURL(url),60000);
    return {filename,byteLength:bytes.length};
  }
  return Object.freeze({generate,downloadPlan:input=>download('plan',input),downloadActivity:input=>download('activity',input),buildDefinition,textWriter,displayTimestamp});
});
