// Chat need-cards and action-plan details. All amounts and dates are fictional sample data.
(()=>{
const META={
  insurance:{short:'Sep 24',who:'Cedar Life',amt:250000,priority:'high',theme:'lilac',need:'Insurance',due:'Follow up Sep 24',
    why:'Two records name different people, and neither proves a benefit exists today.',
    facts:[['2019 policy letter','Cedar Life · $250,000 coverage · beneficiary Maya Rao'],['2024 family will','Names Priya Rao for the estate residue · unsigned copy'],['Unknown','Whether the policy is still active, or the beneficiary changed after 2019']],
    steps:[{when:'Today',t:'Put the two records side by side',d:'Note that the letter is about one policy and the will is about the estate. They may cover different assets.'},{when:'This week',t:'Contact Cedar Life’s claims or customer service line',d:'Use the policy details on the 2019 letter. Explain that the policyholder has died and you are the family contact.'},{when:'On the call',t:'Ask the questions below',d:'Take notes: the date, the person’s name and a reference number.'},{when:'After',t:'Ask for their answer in writing',d:'A written reply is what you can rely on, and what a lawyer would want to see.'}],
    ask:['Is the policy still in force?','Who is the beneficiary on record today, and were there changes after 2019?','What documents do you need to process a claim?'],
    ready:['2019 policy letter','A copy of the death certificate','Your photo ID and relationship to the policyholder'],
    note:'Do not assume anyone is entitled to the $250,000. If the two records seem to conflict, consider asking a probate or estate lawyer.'},
  medical:{short:'Sep 30',who:'Northside Clinic',amt:1240,priority:'high',theme:'rose',need:'Medical bill',due:'Reply by Sep 30',
    why:'The provider wants a reply by Sep 30, and it is unclear whether the $400 payment reduced this invoice.',
    facts:[['Invoice · Sep 10','$1,240 billed'],['Receipt · Sep 14','$400 paid'],['If applied to this invoice','$840 would remain, but the receipt does not say so']],
    steps:[{when:'Today',t:'Check the invoice number on the receipt',d:'See whether the $400 receipt lists the same invoice number as the $1,240 bill.'},{when:'Before Sep 30',t:'Reply to the provider’s billing office',d:'Send the reply they asked for, even if it is only to say you are checking the balance.'},{when:'In the reply',t:'Ask for an updated itemized balance',d:'Ask them to show where the $400 was applied.'},{when:'After',t:'Only pay once the balance is confirmed',d:'Keep the itemized statement with the records.'}],
    ask:['Which invoice was the $400 payment applied to?','What is the current balance, itemized?','Is a payment plan or insurance adjustment still possible?'],
    ready:['The Sep 10 invoice','The Sep 14 receipt','The account or invoice number'],
    note:'Do not pay the full $1,240 until the provider confirms whether the $400 was already applied.'},
  'car-emi':{short:'Oct 3',who:'Harbor Federal Credit Union',amt:412,priority:'high',theme:'mint',need:'EMI',due:'Next EMI Oct 3',
    why:'A $412 payment is due Oct 3. Missing it can add fees while the account status is unclear.',
    facts:[['Monthly EMI','$412.00 (fictional)'],['Next due','Oct 3, 2026'],['Unknown','Whether autopay is active and who the account is in']],
    steps:[{when:'Today',t:'Check the statement for the account and due date',d:'Find the lender name, the last digits of the account and whether an automatic payment is shown.'},{when:'Before Oct 3',t:'Call the lender’s customer service',d:'Say the account holder has died and ask which team handles deceased accounts.'},{when:'On the call',t:'Ask what happens to the loan and the vehicle',d:'Ask if payments should continue while this is sorted out.'},{when:'After',t:'Get the answer in writing',d:'Keep the letter with the loan records.'}],
    ask:['Should the Oct 3 payment still be made?','Is autopay active, and can it be paused?','What are the options for the loan and the vehicle?'],
    ready:['The latest loan statement','A copy of the death certificate','The vehicle registration'],
    note:'Do not stop payments before the lender confirms what to do. Don’t sign anything that makes you personally liable without advice.'},
  storage:{short:'Sep 26',who:'Valley Storage',amt:129,priority:'medium',theme:'butter',need:'Storage',due:'Visit Sep 26',
    why:'There may be belongings inside, and cancelling first could cost you access.',
    facts:[['Charge','$129 a month · Valley Storage'],['Renewal','Renews monthly'],['Unknown','What is stored, and who is allowed access']],
    steps:[{when:'Today',t:'Call Valley Storage about access',d:'Ask what they need to let a family member in.'},{when:'Sep 26',t:'Visit the unit and take photos',d:'List the items, and note anything that looks important.'},{when:'After the visit',t:'Decide what to keep',d:'Arrange to collect the items before closing the space.'},{when:'Last',t:'Ask about closing the rental',d:'Ask for the cancellation date and any final charge.'}],
    ask:['What proof do you need for access?','What is the notice period for cancelling?','Will I be charged for the current month?'],
    ready:['Rental agreement or renewal email','Your photo ID','A copy of the death certificate'],
    note:'Do not cancel or discard anything before you have seen what is inside.'},
  subscriptions:{short:'Anytime',who:'Harbor Gym +1 same account',amt:55.48,priority:'medium',theme:'sky',need:'Subscriptions',due:'When you’re ready',
    why:'$55.48 leaves the account every month until each subscription is cancelled.',
    facts:[['Harbor Gym','$39.99 a month'],['Streamly','$15.49 a month'],['Total','$55.48 a month']],
    steps:[{when:'Today',t:'Confirm both charges on the statement',d:'Check the dates and the last four digits of the card used.'},{when:'This week',t:'Contact each provider',d:'Ask how a deceased member’s account is closed. Many need a written request.'},{when:'After',t:'Ask for confirmation of cancellation',d:'Keep the confirmation, and check the next statement.'}],
    ask:['What proof do you need to close the account?','Is there a cancellation fee?','Can you refund charges made after the date of death?'],
    ready:['Latest statement','A copy of the death certificate','Membership or account number'],
    note:'A statement charge doesn’t prove who owns the account. Check before you cancel.'},
  'personal-loan':{short:'Anytime',who:'Harbor Federal Credit Union',amt:8600,priority:'medium',theme:'peach',need:'Loan',due:'When you’re ready',
    why:'You don’t yet know the payoff amount or whether the loan has any protection attached.',
    facts:[['Remaining balance','About $8,600 (fictional)'],['Next due','Not shown in the sample record'],['Unknown','Any credit insurance or co-signer on the loan']],
    steps:[{when:'Today',t:'Find the loan agreement or the latest statement',d:'Look for the lender name, account number and any mention of insurance or a co-signer.'},{when:'This week',t:'Ask the lender for a written payoff statement',d:'It should show the exact balance and any interest or fees.'},{when:'On the call',t:'Ask about protection on the loan',d:'Some loans come with credit insurance that may clear the balance.'},{when:'After',t:'Decide how to handle the balance',d:'Consider whether the estate will pay it, once you have the figures.'}],
    ask:['What is the payoff amount today?','Does this loan have credit insurance or a co-signer?','Who should payments be made to in the meantime?'],
    ready:['Loan agreement or statement','A copy of the death certificate'],
    note:'Do not pay from personal funds until you know whether the estate or an insurer is responsible.'},
  bonds:{short:'No date',who:'Family papers',amt:null,priority:'low',theme:'teal',need:'Belongings',due:'No date set',
    why:'A voice note mentions savings bonds, but nothing confirms they exist or their value.',
    facts:[['Source','Voice-note transcript'],['Location mentioned','Blue folder in the hall closet'],['Value','Unknown']],
    steps:[{when:'When you’re ready',t:'Look in the hall closet for the blue folder',d:'Check for bond certificates or account letters.'},{when:'If found',t:'Photograph the papers and add them as records',d:'Keep the originals somewhere safe.'}],
    ask:['What is the bond’s issuer and its current value?'],
    ready:['The folder and its papers'],
    note:'Nothing here confirms the bonds exist. Treat this as a lead, not an asset.'}
};
// Sample-task UI only; prod's findings.js owns these views when the model service is live.
const live=()=>Boolean(window.AfterwordFindings?.active?.());
const PRI={high:{label:'High priority',rank:0},medium:{label:'Medium priority',rank:1},low:{label:'Low priority',rank:2}};
const meta=id=>META[id]||{priority:'low',theme:'teal',need:'Task',due:'',why:'',steps:[]};
const open=()=>tasks.filter(t=>(state.filter==='all'?status(t)!=='done':status(t)===state.filter)&&META[t.id]).sort((a,b)=>PRI[meta(a.id).priority].rank-PRI[meta(b.id).priority].rank);
const money=n=>n==null?'Unknown':'$'+n.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const pcode=id=>'P'+(PRI[meta(id).priority].rank+1);
const rankedCards=(list,attr)=>`<div class="rk-grid">${list.map((t,n)=>{const m=meta(t.id);return `<button type="button" class="rk-card" style="--i:${n}" ${attr}="${t.id}" aria-label="${escapeHTML(t.title)}, ${PRI[m.priority].label}. Open in action plan"><span class="rk-card-head"><strong>${escapeHTML(m.need)}</strong><small>1 action${m.amt!=null?' · '+money(m.amt):''}</small></span><span class="rk-item"><span class="rk-num">1.</span><span class="rk-pill p${pcode(t.id)[1]}">${pcode(t.id)}</span><span class="rk-text">${escapeHTML(t.title)} <small>· ${escapeHTML(m.who)}</small></span></span></button>`}).join('')}</div>`;

// Task details: priority, why it matters and the steps.
const previousOpenTask=window.openTask;
window.openTask=function(id){
  previousOpenTask(id);
  const m=META[id];if(!m||live())return;
  const t=tasks.find(t=>t.id===id),p=PRI[m.priority];
  const body=document.querySelector('#dialog-content .modal-body');if(!body)return;
  body.querySelector('.action-plan-block')?.remove();
  const e=escapeHTML;
  body.querySelector(':scope > p')?.remove();
  body.insertAdjacentHTML('afterbegin',`<div class="action-plan-block pri-${m.priority}"><div class="apb-top"><span class="need-icon">${icon(t.icon)}</span><span class="need-tag">${m.need}</span><span class="need-pri pri-${m.priority}"><i></i>${p.label}</span></div><p class="apb-why">${e(m.why)}</p>
  <h3>What the records say</h3><dl class="apb-facts">${m.facts.map(([k,v])=>`<div><dt>${e(k)}</dt><dd>${e(v)}</dd></div>`).join('')}</dl>
  <h3>Action plan</h3><ol class="apb-steps">${m.steps.map(x=>`<li><span class="apb-when">${e(x.when)}</span><strong>${e(x.t)}</strong><span>${e(x.d)}</span></li>`).join('')}</ol>
  <div class="apb-cols"><div><h3>Questions to ask</h3><ul>${m.ask.map(x=>`<li>${e(x)}</li>`).join('')}</ul></div><div><h3>Have ready</h3><ul>${m.ready.map(x=>`<li>${e(x)}</li>`).join('')}</ul></div></div>
  <div class="apb-note"><b>Watch out:</b> ${e(m.note)}</div><small>${e(m.due||t.date)} · Suggestions only. Nothing is sent to anyone, and this is not legal advice.</small></div>`);
};

// Priority chip on plan rows, and card click → action plan.
function decoratePlan(){
  if(live())return;
  const layout=document.querySelector('.plan-layout');
  if(layout&&!document.querySelector('.rk-plan')){const list=open();const label=state.filter==='all'?'open':statusNames[state.filter].toLowerCase();layout.insertAdjacentHTML('beforebegin',`<section class="rk-plan rk-section"><div class="rk-title"><h3>Ranked by category</h3><span class="rk-count">${list.length} ${label}</span></div>${rankedCards(list,'data-task')}</section>`)}
  document.querySelectorAll('.plan-row').forEach(row=>{
    const id=row.querySelector('[data-task]')?.dataset.task;if(!id)return;
    row.dataset.rowId=id;
    const m=META[id];const over=row.querySelector('.row-overline');
    if(m&&over&&!over.querySelector('.need-pri')){const p=PRI[m.priority];over.insertAdjacentHTML('beforeend',`<span class="need-pri pri-${m.priority}"><i></i>${p.label}</span>`)}
  });
}
const previousAfterRender=afterRender;
afterRender=()=>{previousAfterRender();decoratePlan()};
document.addEventListener('click',e=>{
  const card=e.target.closest('[data-plan-card]');if(!card)return;
  const id=card.dataset.planCard;
  state.filter='all';go('plan');
  setTimeout(()=>{
    decoratePlan();
    const row=document.querySelector(`.plan-row[data-row-id="${id}"]`);
    if(row){row.scrollIntoView({block:'center'});row.classList.add('plan-flash');setTimeout(()=>row.classList.remove('plan-flash'),2400)}
    window.openTask(id);
  },120);
});
decoratePlan();
render();
})();
