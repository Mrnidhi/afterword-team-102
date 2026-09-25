'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const tick = () => new Promise(resolve => setImmediate(resolve));

// Small DOM adapter keeps these regression tests dependency-free. The browser
// smoke test additionally exercises actual dialogs and saved preferences.
class Element {
  constructor(tag,attrs={},text='') {
    this.tagName=tag.toUpperCase();this.attrs={...attrs};this.children=[];this.parentElement=null;
    this.disabled=false;this.hidden=false;this.value=attrs.value||'';this.outerHTML='';
    this.classList={toggle(){}};
    if(text)this.appendText(text);
  }
  append(child){child.parentElement=this;this.children.push(child);return child;}
  appendText(text){return this.append({nodeValue:text,parentElement:null});}
  getAttribute(name){return this.attrs[name]??null;}
  setAttribute(name,value){this.attrs[name]=value;}
  get textContent(){return this.children.map(child=>child.nodeValue??child.textContent).join('');}
  set textContent(text){this.children=[];this.appendText(text);}
  get options(){return this.children.filter(child=>child.tagName==='OPTION');}
  matches(selectors){return selectors.split(',').some(raw=>{
    const selector=raw.trim();
    const child=selector.match(/^(.+) > (.+)$/);
    if(child)return this.matches(child[2])&&!!this.parentElement?.matches(child[1]);
    const ancestor=selector.match(/^([^ ]+) (.+)$/);
    if(ancestor)return this.matches(ancestor[2])&&!!this.parentElement?.closest(ancestor[1]);
    const attr=selector.match(/\[([^=\]]+)(?:="([^"]*)")?\]/);
    const base=selector.replace(/\[[^\]]+\]/g,'').replace(/:first-child$/,'');
    if(selector.endsWith(':first-child')&&this.parentElement?.children.find(child=>child.tagName)!==this)return false;
    if(attr&&(this.attrs[attr[1]]===undefined||(attr[2]!==undefined&&this.attrs[attr[1]]!==attr[2])))return false;
    if(!base)return true;
    if(base.startsWith('#'))return this.attrs.id===base.slice(1);
    if(base.startsWith('.'))return (this.attrs.class||'').split(' ').includes(base.slice(1));
    return this.tagName===base.toUpperCase();
  });}
  closest(selector){return this.matches(selector)?this:this.parentElement?.closest(selector)||null;}
  querySelectorAll(selector){return this.children.flatMap(child=>child.tagName?[...(child.matches(selector)?[child]:[]),...child.querySelectorAll(selector)]:[]);}
}
function harness({translation=false,health=true,lang='en'}={}) {
  const listeners={},calls=[],body=new Element('body'),root=new Element('html'),state={lang,route:'overview'};
  root.append(body);
  const document={body,documentElement:root,title:'',addEventListener:(type,fn)=>(listeners[type]??=[]).push(fn),
    querySelectorAll:selector=>body.querySelectorAll(selector),
    createTreeWalker:element=>{const nodes=[];const visit=el=>{for(const child of el.children)child.tagName?visit(child):nodes.push(child);};visit(element);let index=0;return {nextNode:()=>nodes[index++]||null};},
    getElementById:id=>body.querySelectorAll('#'+id)[0]||null};
  const select=body.append(new Element('select',{id:'reading-language'}));
  for(const value of ['en','es','vi','hi'])select.append(new Element('option',{value},value));
  const note=body.append(new Element('p',{id:'reading-language-note'}));
  let saved=null,serverUp=health;
  const context={console,Map,Set,WeakMap,Promise,Object,Array,String,AbortController,state,document,
    nav:[['overview','home','Overview']],AfterwordRuntime:{translation},actions:{},afterRender(){},
    setTimeout:()=>1,clearTimeout(){},icon:()=>'',escapeHTML:text=>String(text).replace(/</g,'&lt;'),
    $:selector=>body.querySelectorAll(selector)[0]||null,$$:selector=>body.querySelectorAll(selector),
    persist(){saved={...state};return true;},render(){context.afterRender();},
    fetch:async(url,options={})=>{calls.push({url,...options});if(url==='/health')return{ok:true,json:async()=>({capabilities:{translation:serverUp}})};return{ok:true,json:async()=>({text:'Información de la cuenta',lang:'es',protected_tokens_ok:true,low_confidence:false})};}};
  context.window=context;vm.createContext(context);vm.runInContext(fs.readFileSync('dist/i18n.js','utf8'),context);
  return {context,body,calls,select,note,get saved(){return saved;},setHealth:value=>{serverUp=value;},
    change:target=>listeners.change?.forEach(fn=>fn({target}))};
}

(async()=>{
  const h=harness();await tick();
  assert.equal(h.select.disabled,false,'Unavailable translation must not disable the language control.');
  assert.equal(h.select.options.find(option=>option.value==='es').disabled,false);
  assert.equal(h.select.options.find(option=>option.value==='en').disabled,false);
  assert.equal(h.select.options.find(option=>option.value==='hi').disabled,true);
  assert.equal(h.calls.length,0,'Static Pages must not probe a nonexistent API.');
  assert.match(h.context.languageField(),/value="es"/);
  assert.doesNotMatch(h.context.languageField(),/<select[^>]*disabled/);

  const sidebar=h.body.append(new Element('aside',{class:'sidebar'}));
  const navigation=sidebar.append(new Element('a',{class:'nav-link'},'  Documents  '));
  const profile=sidebar.append(new Element('div',{class:'profile'}));
  const name=profile.append(new Element('strong',{},'Documents'));
  const preferences=h.body.append(new Element('div',{class:'modal-head'},'Make yourself comfortable'));
  const source=h.body.append(new Element('article',{class:'record-paper'}));
  const sourceText=source.append(new Element('button',{'data-action':'document'},'Documents'));
  const editor=h.body.append(new Element('textarea',{'aria-label':'Your note'},'Documents'));
  const input=h.body.append(new Element('input',{'aria-label':'Your name'}));input.value='Documents';
  const optedOut=h.body.append(new Element('button',{'data-action':'foo','data-no-translate':''},'Documents'));
  const libraryTools=h.body.append(new Element('div',{class:'library-tools'}));
  const implicitOption=libraryTools.append(new Element('option',{},'Email'));
  const envelope=h.body.append(new Element('dl',{class:'outreach-review-envelope'}));
  const senderRow=envelope.append(new Element('div'));
  const senderLabel=senderRow.append(new Element('dt',{},'From'));
  const sender=senderRow.append(new Element('dd',{},'Chosen in your email app · not verified by Afterword'));
  const subjectRow=envelope.append(new Element('div'));
  subjectRow.append(new Element('dt',{},'Subject'));
  const subject=subjectRow.append(new Element('dd',{},'Documents'));
  const senderCheck=h.body.append(new Element('label',{class:'outreach-check'}));
  const senderText=senderCheck.append(new Element('span',{},'I will verify the sending account in my email app before pressing Send.'));
  const exportPlan=h.body.append(new Element('button',{'data-action':'export-plan'},'Export plan'));
  const exportActivity=h.body.append(new Element('button',{'data-action':'export-ledger'},'Export activity'));
  const facts=h.body.append(new Element('dl',{class:'settings-facts'}));
  const identity=facts.append(new Element('div'));identity.append(new Element('dt',{},'Organizer'));
  const identityName=identity.append(new Element('dd',{},'Documents'));
  const draftFact=facts.append(new Element('div'));draftFact.append(new Element('dt',{},'Working letters'));
  const draftCount=draftFact.append(new Element('dd',{},'4 saved drafts'));
  const outreachSettings=h.body.append(new Element('section',{class:'outreach-settings'}));
  const settingsTitle=outreachSettings.append(new Element('h2',{},'Provider outreach'));
  const recipient=outreachSettings.append(new Element('p'));
  const recipientLabel=recipient.append(new Element('strong',{},'Recipient for test letters:'));
  const recipientAddress=recipient.appendText(' team+demo@example.edu');
  const runtimeNote=outreachSettings.append(new Element('p',{},'No local service connected. Browser templates and Gmail compose work without one. No records are sent to another host for processing.'));
  const profileLanguages=[];h.context.AfterwordProfile={setLanguage:code=>profileLanguages.push(code)};
  assert.equal(h.context.AfterwordI18n.setLanguage('es'),true);
  assert.deepEqual(profileLanguages,['es'],'Compact language changes must update the profile preference too.');
  assert.equal(h.saved.lang,'es','Selection is persisted using the existing preferences store.');
  assert.equal(h.context.document.documentElement.lang,'es');
  assert.equal(h.context.document.title,'Resumen — Afterword');
  assert.equal(navigation.textContent,'  Documentos  ');
  assert.equal(preferences.textContent,'Lee a tu manera');
  assert.equal(name.textContent,'Documents','User names must be preserved even when they match a UI label.');
  assert.equal(sourceText.textContent,'Documents','Original source text is never localized.');
  assert.equal(editor.textContent,'Documents','Authored text is never rewritten.');
  assert.equal(editor.getAttribute('aria-label'),'Tu nota');
  assert.equal(input.getAttribute('aria-label'),'Tu nombre');
  assert.equal(input.value,'Documents');assert.equal(optedOut.textContent,'Documents');
  assert.equal(implicitOption.textContent,'Email','Implicit option values must not change when the language changes.');
  assert.equal(senderLabel.textContent,'De');
  assert.equal(sender.textContent,'Se elige en tu aplicación de correo · Afterword no lo ha verificado');
  assert.equal(subject.textContent,'Documents','Authored email subjects must not be translated as interface text.');
  assert.equal(senderText.textContent,'Comprobaré la cuenta del remitente en mi aplicación de correo antes de pulsar Enviar.');
  assert.equal(exportPlan.textContent,'Descargar plan');assert.equal(exportActivity.textContent,'Descargar actividad');
  assert.equal(identityName.textContent,'Documents','Settings must preserve the actual organizer name.');
  assert.equal(draftCount.textContent,'4 borradores guardados');
  assert.equal(settingsTitle.textContent,'Contacto con proveedores');
  assert.equal(recipientLabel.textContent,'Destinatario de las cartas de prueba:');
  assert.equal(recipientAddress.nodeValue,' team+demo@example.edu','Configured addresses must remain exact.');
  assert.match(runtimeNote.textContent,/No hay un servicio local conectado/);
  assert.equal(h.context.AfterwordI18n.t('Local service connected on http://127.0.0.1:4178 No records are sent to another host for processing.'),'Servicio local conectado en http://127.0.0.1:4178 No se envían documentos a otro equipo para procesarlos.');
  assert.match(h.context.languageField(),/español funciona sin conexión/);
  assert.match(h.context.translatedBlock('Original English','summary','offline-block'),/texto original/);
  assert.equal(h.calls.length,0,'Offline Spanish UI must not send document text to translation.');

  h.context.AfterwordI18n.setLanguage('en');
  assert.equal(navigation.textContent,'  Documents  ');
  assert.equal(preferences.textContent,'Make yourself comfortable');
  assert.equal(editor.getAttribute('aria-label'),'Your note');
  assert.equal(input.getAttribute('aria-label'),'Your name');
  assert.equal(draftCount.textContent,'4 saved drafts');assert.equal(settingsTitle.textContent,'Provider outreach');
  assert.equal(h.context.AfterwordI18n.setLanguage('unknown'),false);
  assert.equal(h.saved.lang,'en');
  h.context.AfterwordI18n.addMessages({'Complete setup':'Completar configuración'});
  h.context.AfterwordI18n.setLanguage('es');
  assert.equal(h.context.AfterwordI18n.t('Complete setup'),'Completar configuración');
  // New onboarding must use the same bundled language, without requesting a model.
  const profileSource=fs.readFileSync('dist/profile.js','utf8');
  for(const match of profileSource.matchAll(/\bt\('([^']+)'\)/g)) {
    assert.notEqual(h.context.AfterwordI18n.t(match[1]),match[1],`Missing Spanish onboarding string: ${match[1]}`);
  }

  const connected=harness({translation:true,lang:'es'});await tick();
  const block=connected.body.append(new Element('div',{id:'translated-test'}));
  assert.match(connected.context.translatedBlock('Account information','summary','translated-test'),/Traduciendo/);
  await tick();
  const request=connected.calls.find(call=>call.url==='/translate');
  assert.deepEqual(JSON.parse(request.body),{text:'Account information',target_lang:'es',kind:'summary'});
  assert.match(block.outerHTML,/Información de la cuenta/);
  assert.equal(connected.context.translatedText('Account information','summary'),'Información de la cuenta');
  connected.setHealth(false);await connected.context.checkTranslationHealth();
  assert.equal(connected.select.disabled,false,'A device outage must leave English and Spanish usable.');
  const count=connected.calls.length;
  assert.match(connected.context.translatedBlock('Another summary','summary','second'),/conecta el dispositivo/);
  assert.equal(connected.calls.length,count,'Unavailable dynamic translation must preserve the original without retry spam.');
  console.log('Reading languages: offline Spanish, persistence, reversible interface labels, unchanged originals and device-only translation passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
