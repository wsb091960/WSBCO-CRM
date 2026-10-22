document.addEventListener("DOMContentLoaded",()=>{
 const host=document.querySelector("[data-lead-id]");
 if(!host)return;
 const leadId=host.dataset.leadId;
 const list=document.getElementById("v33-activity-list");
 const empty=document.getElementById("v33-empty");
 const form=document.getElementById("v33-add-activity");

 const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
 const icon=t=>({call:"bi-telephone",disposition:"bi-check2-circle",note:"bi-journal-text",followup:"bi-calendar-check",email:"bi-envelope",status:"bi-arrow-repeat"}[t]||"bi-clock-history");
 const pretty=d=>{try{return new Date(d).toLocaleString()}catch{return d}};

 async function load(){
   const r=await fetch(`/api/leads/${leadId}/activities`);
   if(!r.ok)return;
   const data=await r.json(), rows=data.activities||[];
   if(empty)empty.style.display=rows.length?"none":"grid";
   if(!list)return;
   list.innerHTML=rows.map(a=>`<article class="v33-event">
      <div class="v33-icon"><i class="bi ${icon(a.activity_type)}"></i></div>
      <div class="v33-event-body"><div class="v33-event-top"><b>${esc(a.title)}</b><time>${esc(pretty(a.created_at))}</time></div>
      ${a.outcome?`<span class="v33-outcome">${esc(a.outcome)}</span>`:""}
      ${a.detail?`<p>${esc(a.detail)}</p>`:""}
      ${a.agent?`<small>Agent: ${esc(a.agent)}</small>`:""}</div></article>`).join("");
 }

 async function add(type,title,detail="",outcome=""){
   const fd=new FormData();fd.append("activity_type",type);fd.append("title",title);fd.append("detail",detail);fd.append("outcome",outcome);
   await fetch(`/api/leads/${leadId}/activities`,{method:"POST",body:fd});
 }

 if(form)form.addEventListener("submit",async e=>{
   e.preventDefault();
   const fd=new FormData(form);
   await add(fd.get("activity_type")||"note",fd.get("title")||"Note",fd.get("detail")||"");
   form.reset();load();
 });

 // Log call start without delaying the existing call form.
 document.querySelectorAll(`form[action="/leads/${leadId}/call"]`).forEach(f=>{
   f.addEventListener("submit",()=>{try{navigator.sendBeacon(`/api/leads/${leadId}/activities`,new URLSearchParams({activity_type:"call",title:"Outbound call started",detail:"Twilio agent-first call initiated"}))}catch(e){}});
 });

 // Log disposition selection before the existing disposition form navigates away.
 document.querySelectorAll('form[action^="/calls/"][action$="/disposition"]').forEach(f=>{
   f.addEventListener("submit",()=>{const d=document.getElementById("disp")?.value||document.getElementById("cc-disposition-value")?.value||"Call result";
     const note=f.querySelector('[name="notes"]')?.value||"";
     try{navigator.sendBeacon(`/api/leads/${leadId}/activities`,new URLSearchParams({activity_type:"disposition",title:"Call completed",outcome:d,detail:note}))}catch(e){}});
 });

 load();
});