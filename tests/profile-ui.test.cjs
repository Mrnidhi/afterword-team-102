'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const C=require('../dist/outreach-core.js');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const person={display_name:'Test family',writer_name:'Test family',estate_name:'Test workspace',person_name:'Fictional person',writer_phone:'',relationship:'',date_of_death:'',reading_language:'en',demo_mailbox:'',demo_mailbox_confirmed:false};
const envelope=(authenticated=false,changes={})=>({enabled:true,require_login:true,setup_required:false,authenticated,profile:authenticated?{...person}:null,...changes});
const response=(value,status=200)=>({ok:status>=200&&status<300,status,json:async()=>value});
function harness({required=true,initial=envelope(),connected=true}={}){
  const listeners={},events=[],calls=[],nodes=new Map(),saved=new Map();let handler=null,html='',closed=0,findingsRefresh=0;
  const errorNode={hidden:true,textContent:''};nodes.set('#profile-error',errorNode);
  const context={console,Date,Map,Set,Object,Array,String,JSON,Promise,OutreachCore:C,state:{route:'overview',lang:'en'},AfterwordRuntime:{workspace:connected,requireLogin:required},
    localStorage:{getItem:key=>saved.get(key)||null,setItem:(key,value)=>saved.set(key,value)},
    document:{addEventListener:(name,fn)=>(listeners[name]??=[]).push(fn)},
    addEventListener:(name,fn)=>(listeners[name]??=[]).push(fn),dispatchEvent:event=>{events.push(event.type);for(const fn of listeners[event.type]||[])fn(event);},CustomEvent:class{constructor(type,init){this.type=type;this.detail=init?.detail;}},
    FormData:class{constructor(form){this.values=form.values;}get(key){return this.values[key]??null;}},
    escapeHTML:value=>String(value??'').replace(/[&<>"']/g,x=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x])),icon:()=>'',persist:()=>true,
    $:selector=>nodes.get(selector)||null,actions:{},views:{},afterRender(){},closeDialog(){closed++;},toast(){},
    render(){html=context.AfterwordProfile?.gate()||context.views.profile?.()||'';},go(route){context.state.route=route;},
    AfterwordFindings:{refresh:async()=>{findingsRefresh++;}},
    fetch:async(path,options)=>{calls.push({path,...options});return handler?handler(path,options):response(initial);}};
  context.window=context;vm.createContext(context);vm.runInContext(fs.readFileSync('dist/profile.js','utf8'),context);
  return {context,events,calls,nodes,saved,errorNode,get html(){return html;},get closed(){return closed;},get findingsRefresh(){return findingsRefresh;},
    setHandler:fn=>handler=fn,render:()=>context.render(),
    event:(type,target)=>Promise.all((listeners[type]||[]).map(fn=>fn({target,preventDefault(){}}))),
    form(values={},setup=false,id='workspace-profile-form'){const button={disabled:false};const form={id,dataset:{setup:String(setup)},values:{...values},querySelector:()=>button};nodes.set('#'+id,form);return form;}};
}
(async()=>{
  let h=harness();assert.match(h.context.AfterwordProfile.gate(),/Opening your workspace/);await tick();
  assert.match(h.context.AfterwordProfile.gate(),/workspace-login-form/);
  assert.equal(h.context.AfterwordProfile.canAccessData(),false);
  h.setHandler(()=>response({detail:'The password is incorrect.'},401));
  await h.event('submit',h.form({password:'wrong-test-password'},false,'workspace-login-form'));
  assert.equal(h.errorNode.textContent,'The password is incorrect.');
  assert.match(h.context.AfterwordProfile.gate(),/workspace-login-form/);
  assert.doesNotMatch(h.context.AfterwordProfile.gate(),/Reconnect to your workspace/);

  h=harness({initial:{}});await tick();assert.equal(h.context.AfterwordProfile.canAccessData(),false);
  assert.match(h.context.AfterwordProfile.gate(),/unexpected session/);
  for(const bad of [envelope(true,{profile:[]}),envelope(true,{profile:{...person,writer_name:[]}}),envelope(false,{authenticated:'true'})]){
    h=harness({initial:bad});await tick();assert.equal(h.context.AfterwordProfile.canAccessData(),false);assert.match(h.context.AfterwordProfile.gate(),/Reconnect/);
  }

  h=harness({required:false,initial:envelope(false,{require_login:false})});await tick();
  assert.equal(h.context.AfterwordProfile.gate(),null,'Explicitly disabled login does not lock the data workspace.');
  h.context.state.route='profile';assert.match(h.context.AfterwordProfile.gate(),/workspace-login-form/,'Profile editing still needs authentication.');
  h=harness({required:true,initial:envelope(false,{require_login:false})});await tick();
  assert.equal(h.context.AfterwordProfile.canAccessData(),false,'A contradictory session must not weaken runtime login policy.');

  h=harness({initial:envelope(true)});await tick();assert.equal(h.findingsRefresh,1,'A valid stored session reloads records after the initial gate.');
  h.context.state.route='profile';
  const f=h.form({...person,writer_name:'Unsaved family name',estate_name:'Unsaved workspace',password:'never-store-me'});
  await h.event('input',{id:'profile-writer_name',closest:()=>f});h.render();
  assert.match(h.html,/Unsaved family name/);assert.match(h.html,/Unsaved workspace/);
  assert.doesNotMatch(h.html,/never-store-me/);assert.equal(h.saved.size,0,'Unsaved fields and passwords are not persisted.');
  const checkbox={checked:true};h.nodes.set('[name="demo_mailbox_confirmed"]',checkbox);
  f.values.demo_mailbox='another@university.edu';await h.event('input',{id:'profile-demo_mailbox',closest:()=>f});assert.equal(checkbox.checked,false);
  h.context.AfterwordProfile.lock();assert.equal(h.context.AfterwordProfile.current(),null);assert.ok(h.events.includes('afterword-locked'));assert.ok(h.closed>0);assert.match(h.html,/workspace-login-form/);

  h=harness({initial:envelope(true)});await tick();
  h.setHandler(()=>response({detail:'Sign in to continue.'},401));
  await h.context.AfterwordProfile.setLanguage('es');
  assert.equal(h.context.AfterwordProfile.current(),null);assert.equal(h.context.AfterwordProfile.canAccessData(),false,'A profile API 401 locks the workspace.');

  h=harness({initial:envelope(false,{setup_required:true})});await tick();
  h.setHandler(()=>response(envelope(true)));
  await h.event('submit',h.form({...person,password:'fictional-password'},true));
  assert.equal(h.context.AfterwordProfile.current().display_name,person.display_name);assert.equal(h.context.AfterwordProfile.canAccessData(),true);
  assert.equal(h.calls.at(-1).path,'/workspace/setup');assert.equal(h.calls.at(-1).method,'POST');
  h.setHandler(()=>response(envelope(true,{profile:{...person,estate_name:'Updated workspace'}})));
  await h.event('submit',h.form({...person,estate_name:'Updated workspace'}));
  assert.equal(h.calls.at(-1).method,'PATCH');assert.equal(h.context.AfterwordProfile.current().estate_name,'Updated workspace');

  let resolveStale;h.setHandler(path=>path.endsWith('/logout')?response(envelope()):new Promise(resolve=>resolveStale=resolve));
  const stale=h.context.AfterwordProfile.setLanguage('es');await h.context.actions['profile-logout']();
  resolveStale(response(envelope(true,{profile:{...person,reading_language:'es'}})));await stale;
  assert.equal(h.context.AfterwordProfile.current(),null,'An in-flight save cannot restore a signed-out profile.');

  // Exercise the actual initial render function before profile.js exists.
  const source=fs.readFileSync('dist/app.js','utf8'),start=source.indexOf('function render() {'),end=source.indexOf('\nfunction navItem',start);
  const appNode={innerHTML:''},early={window:{AfterwordRuntime:{workspace:true}},$:()=>appNode};
  vm.createContext(early);vm.runInContext(source.slice(start,end)+'\nrender();',early);
  assert.match(appNode.innerHTML,/Opening your local workspace/);
  const workspaceSource=fs.readFileSync('dist/workspace.js','utf8'),routeStart=workspaceSource.indexOf('window.prepareRoute = () => {'),routeEnd=workspaceSource.indexOf('\n};',routeStart)+3;
  const route={window:{},state:{route:'overview'},nav:[['overview']],location:{hash:'#profile'},previousRouteHash:null,URLSearchParams};
  vm.createContext(route);vm.runInContext(workspaceSource.slice(routeStart,routeEnd)+'\nwindow.prepareRoute();',route);
  assert.equal(route.state.route,'profile','The static route guard must preserve the new profile page.');
  console.log('Profile UI: initial gate, typed session contract, login errors, optional gate, transient edits, setup/save and lock races passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
