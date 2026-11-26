import {useEffect,useState} from 'react'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
type Candidate={model_id:string;name:string;source:string;horizon_minutes:number;training_dates:string[];calibration_dates:string[];reference_holdout_dates:string[];reference_holdout_brier:number;reference_holdout_samples:number}
type Report={state:string;later_dates:string[];required_sessions:number;support:{samples:number;sessions:number};reference_holdout_brier:number;metrics:{brier:number;directional_calls:number;directional_hit_pct:number|null}|null;deterioration_flag:boolean|null;audit_id:string;warning:string}
type Retraining={config:{enabled:boolean;horizon:number};cadence_sessions:number;required_sessions:number;safe_window:boolean;worker_running:boolean;last_run:{state:string;window_end:string;models:{model_id:string;name:string}[];audit_id?:string}|null;note:string}
type Job={status:string;stage?:string;percent?:number;error?:string;result?:Report}
const base='/api/market-intelligence/model-registry'
const fmt=(x:number|null|undefined)=>x==null?'—':x.toFixed(4)
export default function AlphaCandidateRegistry(){
 const [retraining,setRetraining]=useState<Retraining|null>(null),[retrainingHorizon,setRetrainingHorizon]=useState(15),[retrainingConsent,setRetrainingConsent]=useState(false),[retrainingBusy,setRetrainingBusy]=useState(false)
 const [models,setModels]=useState<Candidate[]>([]),[revision,setRevision]=useState(0),[job,setJob]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[stage,setStage]=useState(''),[result,setResult]=useState<Report|null>(null)
 useEffect(()=>{let live=true;marketApi<{models:Candidate[]}>(base).then(r=>{if(live)setModels(r.models)}).catch(e=>{if(live)setError(readableError(e))});return()=>{live=false}},[revision])
 useEffect(()=>{let live=true
 const load=async(initial=false)=>{try{const r=await marketApi<Retraining>(base+'/retraining');if(live){setRetraining(r);if(initial)setRetrainingHorizon(r.config.horizon)}}catch(e){if(live)setError(readableError(e))}}
 void load(true);const timer=window.setInterval(()=>void load(),15000)
 return()=>{live=false;window.clearInterval(timer)}},[])
 const configureRetraining=async(enabled:boolean)=>{setRetrainingBusy(true);setError('');try{const r=await marketPost<Retraining>(base+'/retraining',{enabled,horizon:retrainingHorizon,confirm_local_research:enabled&&retrainingConsent});setRetraining(r);setRetrainingConsent(false);setRevision(v=>v+1)}catch(e){setError(readableError(e))}finally{setRetrainingBusy(false)}}
 useEffect(()=>{if(!job)return;let live=true,polling=false
 const poll=async()=>{if(polling)return;polling=true;try{const r=await marketApi<Job>('/api/jobs/'+encodeURIComponent(job));if(!live)return;setStage(r.stage||r.status);if(r.status==='complete'){setResult(r.result||null);setJob('')}else if(['error','cancelled','interrupted'].includes(r.status)){setError(r.error||r.status);setJob('')}}catch(e){if(live)setError(readableError(e))}finally{polling=false}}
 void poll();const timer=window.setInterval(()=>void poll(),2000);return()=>{live=false;window.clearInterval(timer)}},[job])
 const monitor=async(id:string)=>{if(busy||job)return;setBusy(true);setResult(null);setError('');try{const r=await marketPost<{job_id:string}>(base+'/monitor',{model_id:id});setJob(r.job_id)}catch(e){setError(readableError(e))}finally{setBusy(false)}}
 return <details className="bci-note"><summary><strong>Model registry · frozen research candidates</strong></summary><p>Predictive option studies automatically save portable, checksum-identified logistic candidates when training and calibration are supported. These are not live-approved models. Historical and prospective feature schemas stay separate.</p><button className="ws-button" onClick={()=>setRevision(v=>v+1)}>Refresh model versions</button>
 <details className="bci-note"><summary><strong>Automatic rolling retraining</strong></summary>
 <p>Research only. Runs outside Indian market priority hours while the backend is open, after five additional recorded sessions. Never promotes a model or places an order.</p>
 {retraining&&<><p role="status">{retraining.config.enabled?'Enabled':'Disabled'} · {retraining.required_sessions} recorded sessions required · {retraining.safe_window?'Outside market priority window':'Waiting for market close'}</p>
 <label>Horizon <select value={retrainingHorizon} onChange={e=>setRetrainingHorizon(Number(e.target.value))}>{[5,10,15,30,60,0].map(h=><option key={h} value={h}>{h===0?'Near close':h+' min'}</option>)}</select></label>
 <label><input type="checkbox" checked={retrainingConsent} onChange={e=>setRetrainingConsent(e.target.checked)}/> Authorize recurring local research, without live promotion</label>
 <button className="ws-button" disabled={retrainingBusy||!retrainingConsent} onClick={()=>void configureRetraining(true)}>Enable / update automatic retraining</button>
 <button className="ws-button" disabled={retrainingBusy||!retraining.config.enabled} onClick={()=>void configureRetraining(false)}>Disable automatic retraining</button>
 {retraining.last_run&&<><p>Last completed attempt: {retraining.last_run.state.replaceAll('_',' ')} · through {retraining.last_run.window_end} · {retraining.last_run.models.length} saved candidates.</p>{retraining.last_run.audit_id&&<a className="ws-button" download href={'/api/trading-cockpit/constituents/alpha/audit/'+encodeURIComponent(retraining.last_run.audit_id)}>Download rolling retraining audit</a>}</>}
 <p>{retraining.note}</p></>}
 </details>
 <div className="bci-scroll"><table aria-label="Frozen alpha candidates"><thead><tr><th>Candidate / version</th><th>Source</th><th>Horizon</th><th>Reference holdout</th><th>Brier ↓</th><th>Monitoring</th></tr></thead><tbody>{models.map(m=><tr key={m.model_id}><td>{m.name.replaceAll('_',' ')}<small style={{display:'block'}}>{m.model_id.slice(0,16)}</small></td><td>{m.source}</td><td>{m.horizon_minutes===0?'Near close':m.horizon_minutes+' min'}</td><td>{m.reference_holdout_dates[0]} – {m.reference_holdout_dates.at(-1)} · {m.reference_holdout_samples}</td><td>{fmt(m.reference_holdout_brier)}</td><td>{m.source==='prospective'?<button className="ws-button" disabled={busy||!!job} onClick={()=>void monitor(m.model_id)}>Assess next 20 recorded sessions</button>:'Different historical schema'}</td></tr>)}{!models.length&&<tr><td colSpan={6}>No frozen candidates yet. Run a predictive options study after sufficient data is available.</td></tr>}</tbody></table></div>
 {stage&&<p role="status">{stage}</p>}{error&&<p role="alert">{error}</p>}
 {result&&<><p>{result.state.replaceAll('_',' ')} · {result.later_dates.length}/{result.required_sessions} later dates · {result.support.samples} matched samples. Reference Brier {fmt(result.reference_holdout_brier)}, later Brier {fmt(result.metrics?.brier)}. Deterioration: {result.deterioration_flag==null?'Unverified':result.deterioration_flag?'Flagged':'Not flagged by this descriptive threshold'}.</p><p>{result.warning}</p><a className="ws-button" download href={'/api/trading-cockpit/constituents/alpha/audit/'+encodeURIComponent(result.audit_id)}>Download monitoring audit</a></>}
 </details>
}
