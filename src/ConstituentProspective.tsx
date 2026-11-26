import {useEffect,useState} from 'react'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
import ResearchPlot from './ResearchPlots'
import ConstituentCalibration from './ConstituentCalibration'

type Method='pressure'|'volume_pressure'|'ema_rsi'
type MethodStats={calls:number;abstained:number;unavailable:number;scored:number;correct:number;accuracy:number|null;scored_coverage:number|null;confusion:Record<string,number>}
type Paired={joint_scored:number;sessions:number;method_accuracy:number|null;ema_accuracy:number|null;difference:number|null;session_bootstrap_95:[number,number]|null}
type Summary={attempts:number;directional_outcomes:number;pending:number;flat:number;unverifiable:number;methods:Record<Method,MethodStats>;paired_vs_ema:Record<'pressure'|'volume_pressure',Paired>}
type Decision={slot_utc:string;decided_utc:string;target_utc:string;reference_price:number|null;observed_price:number|null;pressure:string;volume_pressure:string;ema_rsi:string;outcome:string}
type Report={horizon_minutes:number;protocol_sha256:string;summary:Summary;days:(Summary&{session_ist:string})[];latest:Decision[];truncated:boolean;note:string}
type Status={state:string;enabled:boolean;worker_running:boolean;last_attempt_utc:string|null;last_error:string|null;protocol_sha256:string;protocol:{version:string;feature_minutes:number;cadence_seconds:number;min_move_pct:number;min_breadth_pp:number;min_rvol_weight_pct:number;min_signed_rvol:number;ema_baseline:string;label:string};storage:{state:string;last_error:string|null};calibrated_probability:null}
const API='/api/trading-cockpit/constituents/prospective/'
const names:Record<Method,string>={pressure:'Constituent pressure',volume_pressure:'Volume-confirmed pressure',ema_rsi:'EMA 9/21 + RSI baseline'}
const methods:Method[]=['pressure','volume_pressure','ema_rsi']
const percent=(x:number|null|undefined)=>x==null?'—':(100*x).toFixed(2)+'%'
const number=(x:number|null)=>x==null?'—':x.toLocaleString('en-IN',{maximumFractionDigits:2})
const stamp=(x:string|null)=>x?new Date(x).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hourCycle:'h23'}):'—'

export default function ConstituentProspective(){
 const [status,setStatus]=useState<Status|null>(null)
 const [report,setReport]=useState<Report|null>(null)
 const [horizon,setHorizon]=useState(5)
 const [consent,setConsent]=useState(false)
 const [busy,setBusy]=useState(false)
 const [revision,setRevision]=useState(0)
 const [error,setError]=useState('')
 useEffect(()=>{
  let alive=true
  let timer:number|undefined
  let c:AbortController|undefined
  const load=async()=>{
   c=new AbortController()
   try{
    const [s,r]=await Promise.all([marketApi<Status>(API+'status',{signal:c.signal}),marketApi<Report>(API+'report?horizon='+horizon,{signal:c.signal})])
    if(alive){setStatus(s);setReport(r);setError('')}
   }catch(e){if(alive){setError(readableError(e));setReport(null)}}
   if(alive)timer=window.setTimeout(()=>void load(),30000)
  }
  setReport(null)
  void load()
  return()=>{alive=false;c?.abort();if(timer!==undefined)window.clearTimeout(timer)}
 },[horizon,revision])
 const configure=async()=>{
  if(!status||busy||(!status.enabled&&!consent))return
  setBusy(true);setError('')
  try{
   setStatus(await marketPost<Status>(API+'configure',{enabled:!status.enabled,confirm_local_research:consent}))
   setConsent(false);setRevision(n=>n+1)
  }catch(e){setError(readableError(e))}finally{setBusy(false)}
 }
 const summary=report?.horizon_minutes===horizon?report.summary:null
 return <section className="bci-panel" aria-label="Prospective constituent and EMA evaluation">
  <header><div><h3>Prospective directional research</h3><p>Fixed rules, shared clocks, real subsequent index observations. The local API worker records only future-facing decisions; no broker order, historical backfill or model training.</p></div><button type="button" className="ws-button" onClick={()=>setRevision(n=>n+1)}>Refresh research evidence</button></header>
  <div className="bci-grid">
   <div className="bci-stat"><span>Recorder state</span><strong>{status?.enabled?status.state.replaceAll('_',' '):status?'Disabled':'Checking…'}</strong><small>{status?.worker_running?'Local worker running':'Worker idle'}</small></div>
   <div className="bci-stat"><span>Last attempted slot</span><strong>{stamp(status?.last_attempt_utc||null)}</strong><small>IST · once per minute when eligible</small></div>
   <div className="bci-stat"><span>Forecast probabilities</span><strong>Unavailable</strong><small>Calibration requires separate frozen validation</small></div>
  </div>
  {!status?.enabled&&<label className="bci-check"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/> I authorize local prospective recording and subsequent outcome checks; no orders or new provider connection.</label>}
  <div className="bci-actions"><button className="ws-button primary" type="button" disabled={!status||busy||(!status.enabled&&!consent)} onClick={()=>void configure()}>{busy?'Saving…':status?.enabled?'Pause prospective recording':'Enable prospective recording'}</button><label>Outcome horizon<select aria-label="Prospective outcome horizon" value={horizon} onChange={e=>setHorizon(Number(e.target.value))}>{[1,5,10,30,60].map(n=><option key={n} value={n}>{n} minutes</option>)}</select></label></div>
  {error&&<p className="bci-error" role="alert">{error}</p>}
  {status?.last_error&&<p className="bci-note bci-warning">Worker: {status.last_error}</p>}
  {status?.storage.last_error&&<p className="bci-note bci-warning">Storage: {status.storage.last_error}</p>}
  {status&&<details><summary>Frozen rule and observation protocol</summary><p className="bci-note">Version {status.protocol.version} · SHA-256 {status.protocol_sha256}. Weighted {status.protocol.feature_minutes}-minute return must move at least ±{status.protocol.min_move_pct}% with aligned breadth ±{status.protocol.min_breadth_pp} percentage points. Volume confirmation additionally requires {status.protocol.min_rvol_weight_pct}% weight coverage and signed relative volume agreement. EMA-RSI baseline: {status.protocol.ema_baseline}. {status.protocol.label}. Pausing stops new research writes; pending outcomes resume when enabled.</p></details>}
  {summary&&report&&<>
   <div className="bci-grid">
    {([['Recorded attempts',summary.attempts],['Observed up/down targets',summary.directional_outcomes],['Pending',summary.pending],['Unverifiable / flat',summary.unverifiable+' / '+summary.flat]] as [string,string|number][]).map(([name,v])=><div className="bci-stat" key={name}><span>{name}</span><strong>{v}</strong><small>Returned {horizon}m ledger window</small></div>)}
   </div>
   <div className="bci-scroll"><table aria-label="Prospective rule scores"><thead><tr><th>Frozen method</th><th>Calls</th><th>Abstain</th><th>Unavailable</th><th>Scored</th><th>Accuracy</th><th>Scored coverage</th></tr></thead><tbody>{methods.map(m=>{const v=summary.methods[m];return <tr key={m}><td>{names[m]}</td><td>{v.calls}</td><td>{v.abstained}</td><td>{v.unavailable}</td><td>{v.scored}</td><td>{percent(v.accuracy)}</td><td>{percent(v.scored_coverage)}</td></tr>})}</tbody></table></div>
   <div className="bci-scroll"><table aria-label="Matched constituent versus EMA comparisons"><thead><tr><th>Matched method</th><th>Joint scored</th><th>Sessions</th><th>Rule accuracy</th><th>EMA accuracy</th><th>Difference (pp)</th><th>Session bootstrap interval (pp)</th></tr></thead><tbody>{(['pressure','volume_pressure'] as const).map(m=>{const v=summary.paired_vs_ema[m];return <tr key={m}><td>{names[m]}</td><td>{v.joint_scored}</td><td>{v.sessions}</td><td>{percent(v.method_accuracy)}</td><td>{percent(v.ema_accuracy)}</td><td>{v.difference===null?'—':(100*v.difference).toFixed(2)}</td><td>{v.session_bootstrap_95?v.session_bootstrap_95.map(n=>(100*n).toFixed(2)).join(' to '):'Insufficient paired sessions'}</td></tr>})}</tbody></table></div>
   <p className="bci-note">Different call counts cannot establish relative superiority. Compare paired rows and coverage; session-bootstrap intervals are descriptive and require at least 20 jointly scored sessions and 100 paired decisions. No probability or live P&amp;L follows from this scoreboard.</p>
   {report.days.length>0&&<><ResearchPlot provenance="Saved prospective decision ledger" plot={{kind:'line2d',title:'Daily prospective directional accuracy',x_label:'IST session',y_label:'Accuracy (%)',x:report.days.map(d=>d.session_ist),traces:methods.map(m=>({name:names[m],y:report.days.map(d=>d.methods[m].accuracy===null?null:100*d.methods[m].accuracy!)}))}}/><ResearchPlot provenance="Saved prospective decision ledger" plot={{kind:'bar2d',title:'Daily scored directional coverage',x_label:'IST session',y_label:'Scored calls',x:report.days.map(d=>d.session_ist),traces:methods.map(m=>({name:names[m],y:report.days.map(d=>d.methods[m].scored)}))}}/></>}
   <details><summary>Confusion matrices and latest recorded decisions</summary>
    <div className="bci-scroll"><table aria-label="Prospective confusion counts"><thead><tr><th>Method</th><th>Up / Up</th><th>Up / Down</th><th>Down / Up</th><th>Down / Down</th></tr></thead><tbody>{methods.map(m=><tr key={m}><td>{names[m]}</td>{['UP_UP','UP_DOWN','DOWN_UP','DOWN_DOWN'].map(k=><td key={k}>{summary.methods[m].confusion[k]}</td>)}</tr>)}</tbody></table></div>
    <div className="bci-scroll"><table aria-label="Latest prospective decisions"><thead><tr><th>Decision (IST)</th><th>Target (IST)</th><th>Reference spot</th><th>Pressure</th><th>Volume</th><th>EMA-RSI</th><th>Outcome</th><th>Observed spot</th></tr></thead><tbody>{report.latest.map(r=><tr key={r.slot_utc}><td>{stamp(r.decided_utc)}</td><td>{stamp(r.target_utc)}</td><td>{number(r.reference_price)}</td><td>{r.pressure}</td><td>{r.volume_pressure}</td><td>{r.ema_rsi}</td><td>{r.outcome}</td><td>{number(r.observed_price)}</td></tr>)}</tbody></table></div>
   </details>
   {summary.attempts===0&&<p className="bci-note">No prospective observations yet. Enable the constituent recorder and this research recorder, supply timely reviewed weights, and wait for actual observed NSE-session data.</p>}
   {report.truncated&&<p className="bci-note">Report is limited to the latest returned decisions; not lifetime performance.</p>}
   <p className="bci-note">{report.note}</p>
  </>}
  <ConstituentCalibration key={horizon} horizon={horizon}/>
 </section>
}
