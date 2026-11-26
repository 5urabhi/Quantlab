import {useEffect,useState} from 'react'
import ResearchPlot from './ResearchPlots'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
import './operations-closeout.css'

type Backup={id:string;created_utc:string;databases:string[];total_snapshot_bytes:number}
type Inventory={preview:{databases:{id:string;label:string;state:string;source_bytes:number|null;can_snapshot:boolean}[];can_create:boolean;warning:string};snapshots:Backup[];partial:boolean}
type Verify={id:string;verified:boolean;checked_databases:string[];checked_utc:string}
type Job={status:string;stage?:string;error?:string}
const API='/api/workspace/metadata-backups'
const mb=(v:number|null)=>v===null?'—':(v/1048576).toFixed(2)+' MiB'
export function LocalMetadataBackups(){
 const [inventory,setInventory]=useState<Inventory|null>(null)
 const [busy,setBusy]=useState(false)
 const [consent,setConsent]=useState(false)
 const [job,setJob]=useState('')
 const [stage,setStage]=useState('')
 const [error,setError]=useState('')
 const [verified,setVerified]=useState<Verify|null>(null)
 const refresh=async()=>{
  setBusy(true);setError('')
  try{setInventory(await marketApi<Inventory>(API))}catch(e){setError(readableError(e));setInventory(null)}finally{setBusy(false)}
 }
 const create=async()=>{
  if(!consent||busy||job)return
  setBusy(true);setError('')
  try{
    const r=await marketPost<{job_id:string}>(API,{confirm_authorized:true})
    setJob(r.job_id);setStage('Queued');setConsent(false)
  }catch(e){setError(readableError(e))}finally{setBusy(false)}
 }
 useEffect(()=>{
  if(!job)return
  let alive=true
  let timer:number|undefined
  const poll=async()=>{
   try{
    const r=await marketApi<Job>('/api/jobs/'+encodeURIComponent(job))
    if(!alive)return
    setStage(r.stage||r.status)
    if(r.status==='complete'){setJob('');setStage('Snapshot created; verify it before relying on it.');void refresh()}
    else if(['error','cancelled','interrupted'].includes(r.status)){setJob('');setError(r.error||r.status)}
    else timer=window.setTimeout(()=>void poll(),1500)
   }catch(e){if(alive){setJob('');setError(readableError(e)+' · Review the research job history before retrying.')}}
  }
  void poll()
  return()=>{alive=false;if(timer!==undefined)window.clearTimeout(timer)}
 },[job])
 const verify=async(id:string)=>{
  setBusy(true);setError('');setVerified(null)
  try{setVerified(await marketPost<Verify>(API+'/'+encodeURIComponent(id)+'/verify',{}))}catch(e){setError(readableError(e))}finally{setBusy(false)}
 }
 return <section className="qoc-panel" aria-label="Research metadata backups">
  <header><div><h2>Local metadata snapshots</h2><p>Checksummed consistent copies of each saved research metadata database. No original market prices, provider credential files or model result payloads are included. Sensitive user-entered notes may be present. Use encrypted local storage. Automatic restore is not supported.</p></div><button type="button" className="ws-button" disabled={busy||Boolean(job)} onClick={()=>void refresh()}>Inspect metadata backups</button></header>
  {error&&<p role="alert" className="qoc-error">{error}</p>}
  {inventory&&<><div className="qoc-scroll"><table aria-label="Metadata backup source inventory"><thead><tr><th>Database</th><th>Source state</th><th>Size incl. WAL</th></tr></thead><tbody>{inventory.preview.databases.map(r=><tr key={r.id}><td>{r.label}</td><td>{r.can_snapshot?'Eligible':r.state.replaceAll('_',' ')}</td><td>{mb(r.source_bytes)}</td></tr>)}</tbody></table></div>
   <label><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/> I authorize a sensitive metadata snapshot on this local disk.</label>
   <div className="qoc-actions"><button type="button" className="ws-button primary" disabled={!inventory.preview.can_create||!consent||busy||Boolean(job)} onClick={()=>void create()}>Create metadata snapshot</button></div>
   <p className="qoc-note">{inventory.preview.warning}</p>
   {inventory.partial&&<p className="qoc-note">Partial backup inventory.</p>}
   {inventory.snapshots.map(r=><div key={r.id} className="qoc-record"><div><strong>{r.id}</strong><small>{r.created_utc} · {r.databases.join(', ')} · {mb(r.total_snapshot_bytes)}</small></div><button type="button" className="ws-button" disabled={busy||Boolean(job)} onClick={()=>void verify(r.id)}>Verify snapshot</button></div>)}
   {!inventory.snapshots.length&&<p className="qoc-note">No saved metadata snapshots found.</p>}</>}
  {stage&&<p role="status" className="qoc-note">{stage}</p>}
  {verified&&<p role="status" className="qoc-note">Verified {verified.id}: {verified.checked_databases.join(', ')} · SHA-256 and SQLite checks passed. Not a complete research backup.</p>}
 </section>
}

type StressRow={date:string;original_wealth:number;stressed_wealth:number;benchmark_wealth:number;extra_modeled_cost_fraction:number;observed_turnover:number}
type Stress={run_id:string;evidence_class:string;original_monthly_sha256:string;incremental_per_turnover_bps:number;observations:number;metrics:Record<string,number>;rows:StressRow[];warnings:string[]}
const defaults={extra_fee_bps:0,extra_half_spread_bps:5,impact_coefficient_bps:40,assumed_participation:.02}
const fields:[keyof typeof defaults,string,number,number][]=[
 ['extra_fee_bps','Additional fee (bps)',250,1],['extra_half_spread_bps','Additional half-spread (bps)',250,1],['impact_coefficient_bps','Impact coefficient (bps)',500,1],['assumed_participation','Assumed participation fraction',.2,.01]]
const pc=(v:number)=>Number.isFinite(v)?(100*v).toFixed(2)+'%':'—'
export function ExecutionCostStress({runId,provenance}:{runId:string;provenance:string}){
 const [form,setForm]=useState(defaults)
 const [result,setResult]=useState<Stress|null>(null)
 const [busy,setBusy]=useState(false)
 const [error,setError]=useState('')
 const run=async()=>{
  setBusy(true);setError('');setResult(null)
  try{setResult(await marketPost<Stress>('/api/workspace/execution-stress/'+encodeURIComponent(runId),form))}catch(e){setError(readableError(e))}finally{setBusy(false)}
 }
 const r=result?.run_id===runId?result:null
 return <section className="qoc-panel" aria-label="Incremental execution cost stress">
  <header><div><h3>Incremental execution friction</h3><p>Stress archived monthly gross returns using observed saved turnover and explicitly assumed extra costs. Original base costs remain in place. These are not observed fills, broker fees, actual market impact or capacity estimates.</p></div></header>
  <div className="qoc-grid">{fields.map(([k,name,max,step])=><label className="qoc-field" key={k}>{name}<input type="number" min={0} max={max} step={step} value={form[k]} onChange={e=>{setForm(v=>({...v,[k]:Number(e.target.value)}));setResult(null)}}/></label>)}</div>
  <div className="qoc-actions"><button className="ws-button primary" type="button" disabled={busy||fields.some(([k,_,max])=>!Number.isFinite(form[k])||form[k]<0||form[k]>max)} onClick={()=>void run()}>{busy?'Evaluating…':'Run incremental cost scenario'}</button></div>
  {error&&<p role="alert" className="qoc-error">{error}</p>}
  {r&&<><p className="qoc-note">{r.observations} archived observations · {r.incremental_per_turnover_bps.toFixed(2)} assumed incremental bps per unit of turnover · {r.evidence_class.replaceAll('_',' ')}.</p><div className="qoc-grid">{[['Original net return',r.metrics.original_compounded_net_return],['Stressed net return',r.metrics.stressed_compounded_net_return],['Incremental return drag',r.metrics.incremental_compounded_return_drag],['Stressed max drawdown',r.metrics.stressed_max_drawdown]].map(([name,v])=><div className="qoc-stat" key={String(name)}><span>{name}</span><strong>{pc(Number(v))}</strong><small>Saved-path scenario</small></div>)}</div>
   <ResearchPlot provenance={provenance} plot={{kind:'line2d',title:'Original versus cost-stressed wealth',x_label:'Saved observation date',y_label:'Wealth multiple',x:r.rows.map(x=>x.date),traces:[{name:'Original net',y:r.rows.map(x=>x.original_wealth)},{name:'Hypothetical stressed net',y:r.rows.map(x=>x.stressed_wealth)},{name:'Benchmark',y:r.rows.map(x=>x.benchmark_wealth)}]}}/>
   <ResearchPlot provenance={provenance} plot={{kind:'bar2d',title:'Additional modeled monthly costs',x_label:'Saved observation date',y_label:'Additional cost (%)',x:r.rows.map(x=>x.date),traces:[{name:'Incremental cost',y:r.rows.map(x=>100*x.extra_modeled_cost_fraction)}]}}/>
   <p className="qoc-note">Original monthly result SHA-256: {r.original_monthly_sha256}</p>{r.warnings.map((w,i)=><p key={i} className="qoc-note">{w}</p>)}</>}
 </section>
}
