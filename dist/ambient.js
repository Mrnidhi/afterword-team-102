/* A persistent, decorative scene independent of the frequently re-rendered workspace. */
(() => {
  const scene=document.getElementById('ambient-daylight');
  const root=document.documentElement;
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  const forced=matchMedia('(forced-colors: active)');
  let intro=null, visible=false, clockTimer;
  function setDaylight() {
    const hour=new Date().getHours();
    root.dataset.daylight=hour>=6&&hour<11?'morning':hour>=11&&hour<17?'day':hour>=17&&hour<20?'evening':'night';
  }
  function sync() {
    const allowed=state.ambientMotion&&!reduced.matches&&!forced.matches;
    const running=!!intro&&visible&&allowed&&!document.hidden&&!$('#detail-dialog').open;
    scene.dataset.running=String(running);
    clearTimeout(clockTimer);
    if(running){setDaylight();clockTimer=setTimeout(sync,60000);}
    const select=$('#background-motion');
    if(select)select.disabled=reduced.matches;
    const note=$('#motion-preference-note');
    if(note)note.textContent=reduced.matches?'Your device has reduced motion on. The background stays still.':'Slow daylight movement on Overview and Memories. Reading and editing areas stay still.';
  }
  function position() {
    if(!intro)return;
    const box=intro.getBoundingClientRect();
    Object.assign(scene.style,{left:box.left+window.scrollX+'px',top:box.top+window.scrollY+'px',width:box.width+'px',height:box.height+'px'});
  }
  const sizeObserver=new ResizeObserver(position);
  const visibilityObserver=new IntersectionObserver(entries=>{
    const entry=entries.find(e=>e.target===intro);
    if(entry){visible=entry.isIntersecting;sync();}
  });
  function attach() {
    sizeObserver.disconnect();visibilityObserver.disconnect();
    intro=['overview','memories'].includes(state.route)?$('.page-heading,.memory-top'):null;
    scene.dataset.visible=String(!!intro);visible=false;
    if(intro){
      intro.classList.add('ambient-intro');
      position();sizeObserver.observe(intro);visibilityObserver.observe(intro);
    }
    sync();
  }
  const earlierRender=afterRender;
  afterRender=()=>{earlierRender();attach();};
  window.appearanceFields=()=>`<label class="field"><span>Background motion</span><select id="background-motion" aria-describedby="motion-preference-note" ${reduced.matches?'disabled':''}><option value="gentle" ${state.ambientMotion?'selected':''}>Gentle motion</option><option value="still" ${!state.ambientMotion?'selected':''}>Still</option></select></label><p class="fine motion-preference-note" id="motion-preference-note">${reduced.matches?'Your device has reduced motion on. The background stays still.':'Slow daylight movement on Overview and Memories. Reading and editing areas stay still.'}</p>`;
  reduced.addEventListener('change',sync);forced.addEventListener('change',sync);
  document.addEventListener('visibilitychange',sync);
  new MutationObserver(sync).observe($('#detail-dialog'),{attributes:true,attributeFilter:['open']});
  window.addEventListener('resize',position,{passive:true});
  window.addEventListener('pagehide',()=>{clearTimeout(clockTimer);scene.dataset.running='false';});
  window.addEventListener('pageshow',()=>{position();sync();});
  setDaylight();attach();
})();
