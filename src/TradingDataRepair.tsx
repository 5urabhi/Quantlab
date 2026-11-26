import {useEffect,useState} from 'react'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
import MarketPatternIntelligence from './MarketPatternIntelligence'
import './market-inventory.css'

type Source={id:string;label:string;state:string;detail:string;count:number|null;first:string|null;last:string|null;sample_present?:boolean|null}
type Plan={start_date:string;end_date:string;wings:number;eligible_intervals:{from:string;through:string}[];eligible_calendar_days:number;excluded_active_calendar_days:number;full_scope_request_estimate:number;max_missing_requests:number;warning:string}
type Result=Plan&{split_rejected_windows?:number;processed_windows?:number;existing_verified_receipts:number;unreadable_receipts_encountered:number;planned_missing_requests:number;new_receipts:number;exact_cache_reuses:number;empty_processed_receipts:number;usable_rows_in_processed_receipts:number;note:string}
type Job={status:string;stage?:string;percent?:number;error?:string;result?:Result}
const dateBefore=(days:number)=>new Date(Date.now()-days*86400000).toLocaleDateString('sv-SE',{timeZone:'Asia/Kolkata'})
const KEY='quantlab:expired-history-acquisition'
const route='/api/data-manager/options-history/'
const fmt=(v:number|null|undefined)=>v==null?'Not verified':v.toLocaleString('en-IN')
function savedJob(){try{return sessionStorage.getItem(KEY)||''}catch{return ''}}
function keepJob(v:string){try{if(v)sessionStorage.setItem(KEY,v);else sessionStorage.removeItem(KEY)}catch{/* local job remains available in Jobs */}}
const status=(s:Source|undefined)=>!s?'Awaiting inventory':s.count!=null&&s.count>0?fmt(s.count)+' stored / receipt rows':s.sample_present?'Records found · full count unverified':s.state==='partial'||s.state==='not_verified'?'Needs inspection · not assumed missing':s.state==='empty'?'No rows observed':'No verified records'
export default function TradingDataRepair({sources,onOpenStocks,onInspect,onDone}:{sources:Source[];onOpenStocks?:()=>void;onInspect:(id:string)=>void;onDone:()=>void}){
 const [start,setStart]=useState(()=>dateBefore(365)),[end,setEnd]=useState(()=>dateBefore(1)),[wings,setWings]=useState(3)
 const [plan,setPlan]=useState<Plan|null>(null),[planning,setPlanning]=useState(false),[consent,setConsent]=useState(false)
 const [error,setError]=useState(''),[jobId,setJobId]=useState(savedJob),[job,setJob]=useState<Job|null>(null),[starting,setStarting]=useState(false)
 const [result,setResult]=useState<Result|null>(null)
 const src=(id:string)=>sources.find(s=>s.id===id)
 useEffect(()=>{let active=true;setPlan(null);setConsent(false);setError('');setPlanning(true)
  const t=window.setTimeout(()=>{marketApi<Plan>(route+'plan?'+new URLSearchParams({start_date:start,end_date:end,wings:String(wings)})).then(p=>{if(active)setPlan(p)}).catch(e=>{if(active)setError(readableError(e))}).finally(()=>{if(active)setPlanning(false)})},250)
  return()=>{active=false;window.clearTimeout(t)}
 },[start,end,wings])
 useEffect(()=>{if(!jobId)return
  let active=true,busy=false
  const poll=async()=>{if(busy)return;busy=true
   try{const v=await marketApi<Job>('/api/jobs/'+encodeURIComponent(jobId));if(!active)return;setJob(v)
    if(v.status==='complete'){setResult(v.result||null);keepJob('');setJobId('');onDone()}
    else if(['error','cancelled','interrupted'].includes(v.status)){setError(v.error||v.status);keepJob('');setJobId('');onDone()}
   }catch(e){if(active)setError(readableError(e))}
   finally{busy=false}
  }
  void poll();const t=window.setInterval(()=>void poll(),2000)
  return()=>{active=false;window.clearInterval(t)}
 },[jobId,onDone])
 async function acquire(){
  if(!plan||!consent||jobId||starting)return
  setStarting(true);setError('');setResult(null);setJob(null)
  try{const v=await marketPost<{job_id:string}>(route+'start',{start_date:start,end_date:end,wings,confirm_readonly:true});keepJob(v.job_id);setJobId(v.job_id)}
  catch(e){setError(readableError(e))}finally{setStarting(false)}
 }
 return <section className="mi-repair" aria-label="Repair missing Bank Nifty trading data">
  <header><small className="mi-repair-kicker">SCALPING DATA · ONE SHARED LIBRARY</small><h3>Complete your Bank Nifty trading data</h3><p className="mi-caption">Historical downloads and original live recording are different. Fill the appropriate gaps without re-downloading your entire equity universe.</p></header>
  <MarketPatternIntelligence coverageOnly/>
  <div className="mi-repair-card">
   <div className="mi-section-title"><div><h3>2 · Expired CE/PE history</h3><p>{status(src('expired_options'))} · original Dhan rolling-option receipts</p></div><button type="button" className="ws-button" onClick={()=>onInspect('expired_options')}>Inspect saved option history</button></div>
   <p className="mi-caption">Acquire original one-minute near-monthly CE/PE OHLC, IV, OI and volume in bounded 30-day requests. Reuse verified saved receipt windows. Active expiries use the separate active-contract workflow; original historical depth cannot be backfilled this way. For Dhan DH-905 only, the downloader tries equivalent REST/SDK field encodings and one shorter-window split; authentication or rate-limit errors stop acquisition.</p>
   <div className="mi-filter"><label>From (IST)<input aria-label="Expired option history start" type="date" value={start} disabled={!!jobId||starting} max={end} onChange={e=>setStart(e.target.value)}/></label><label>Through (IST)<input aria-label="Expired option history end" type="date" value={end} disabled={!!jobId||starting} min={start} max={dateBefore(1)} onChange={e=>setEnd(e.target.value)}/></label><label>Rolling strikes<select aria-label="Expired option strike wings" value={wings} disabled={!!jobId||starting} onChange={e=>setWings(Number(e.target.value))}>{[0,1,2,3,4,5].map(n=><option key={n} value={n}>{n===0?'ATM only':'ATM ± '+n}</option>)}</select></label></div>
   {planning&&<p role="status" className="mi-caption">Checking eligible date windows…</p>}
   {plan&&<><p className="mi-caption">{plan.eligible_calendar_days} eligible calendar days · {plan.excluded_active_calendar_days} calendar days excluded because expiry may still be active · {plan.full_scope_request_estimate} requests for the full empty-cache scope. Verified overlapping windows will be skipped; at most {plan.max_missing_requests} missing requests per job. {plan.warning}</p>
    <label className="mi-repair-consent"><input type="checkbox" checked={consent} disabled={!!jobId||starting} onChange={e=>setConsent(e.target.checked)}/> Approve read-only Dhan historical requests for this scope.</label>
    <button type="button" className="ws-button primary" disabled={!consent||!plan.eligible_calendar_days||!!jobId||starting} onClick={()=>void acquire()}>{jobId||starting?'Acquisition running…':'Download missing expired-option history'}</button></>}
   {jobId&&<p role="status" className="mi-caption">{job?.stage||'Queued'} · {job?.percent??0}% · Job {jobId}</p>}
   {error&&<p role="alert" className="mi-error">{error} Existing saved receipts are retained.</p>}
   {result&&<div className="mi-source-info"><strong>Request windows checked</strong><p>{result.new_receipts} new receipts · {result.existing_verified_receipts} prior verified receipts · {result.exact_cache_reuses} exact cache reuses · {result.empty_processed_receipts} empty processed receipts · {fmt(result.usable_rows_in_processed_receipts)} usable rows in processed receipts · {result.unreadable_receipts_encountered} unreadable receipts encountered. {result.split_rejected_windows||0} rejected windows split into shorter requests.</p><p>{result.note}</p></div>}
  </div>
  <div className="mi-repair-card">
   <div className="mi-section-title"><div><h3>3 · Live execution evidence</h3><p>Required for 15–30-second scalping. Inspect, then repair recording if needed.</p></div><a className="ws-button" href="#/recordingsettings">Automatic Recording →</a></div>
   <div className="mi-repair-grid">{['live_ticks','live_minute_bars','option_quote','option_oi','live_depth_books','constituent_quotes','constituent_derivative_quote','option_chain'].map(id=>{const s=src(id);return <div key={id}><strong>{s?.label||id.replaceAll('_',' ')}</strong><span>{status(s)}</span>{s?.last&&<small>Last observed: {s.last}</small>}<small>{s?.detail}</small><button type="button" className="ws-button" onClick={()=>onInspect(id)}>Inspect</button></div>})}</div>
   <p className="mi-caption">A count timeout is not an empty table. Check recorder connection and last received packets; old missing ticks/books cannot be recreated from minute candles. No capture is stopped or restarted here.</p>
  </div>
  <div className="mi-repair-card">
   <div className="mi-section-title"><div><h3>4 · Banking constituent history</h3><p>{status(src('raw_intraday'))} across inspected equity receipts. Use dated membership and the existing shared store.</p></div>{onOpenStocks&&<button type="button" className="ws-button" onClick={onOpenStocks}>Update banking-stock history →</button>}</div>
   <p className="mi-caption">Stock history is a separate scope. The equity downloader is only opened for this action, not when repairing option or index history.</p>
  </div>
  <p className="mi-caption">After downloading, refresh the inventory and run Quality &amp; Coverage. Historical price coverage does not establish actual tradable fills, and current subscription access is checked locally.</p>
 </section>
}
