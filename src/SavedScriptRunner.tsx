import {useEffect,useRef,useState} from 'react'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
import ResearchPlot,{type ResearchPlotData} from './ResearchPlots'
import type {PythonSnapshot} from './pythonBridge'
export type SavedScriptMeta={id:string;name:string;kind:string;revision:number}
type Result={run_id:string;script_name:string;script_revision:number;plot:ResearchPlotData;warning:string;source_sha256:string;snapshot_sha256:string;ranking?:{rank:number;key:string;score:number;row:(string|number|boolean|null)[]}[];ranking_note?:string}
type Job={status:string;stage?:string;error?:string;result?:Result}
export default function SavedScriptRunner({kind,snapshot,initialScriptId='',onInspect,automatic=false}:{kind:'model'|'scanner';snapshot:PythonSnapshot|null;initialScriptId?:string;onInspect?:(key:string)=>void;automatic?:boolean}){
  const [scripts,setScripts]=useState<SavedScriptMeta[]>([])
  const [selected,setSelected]=useState(initialScriptId)
  const [profile,setProfile]=useState<'stdlib'|'scientific'>('stdlib')
  const [available,setAvailable]=useState<boolean|null>(null)
  const [job,setJob]=useState('')
  const [status,setStatus]=useState('')
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [auto,setAuto]=useState(false)
  const [result,setResult]=useState<Result|null>(null)
  const [resultKey,setResultKey]=useState('')
  const runningKey=useRef('')
  const lastLaunch=useRef('')
  const launching=useRef(false)
  const item=scripts.find(s=>s.id===selected)
  const key=snapshot&&item?JSON.stringify([item.id,item.revision,profile,snapshot]):''
  const same=!!key&&key===resultKey
  const refresh=async()=>{try{const data=await marketApi<{scripts:SavedScriptMeta[];sandbox:{available:boolean}}>('/api/user-scripts');setScripts(data.scripts.filter(s=>s.kind===kind));setAvailable(data.sandbox.available)}catch(e){setError(readableError(e))}}
  useEffect(()=>{void refresh()},[kind])
  useEffect(()=>{if(initialScriptId)setSelected(initialScriptId)},[initialScriptId])
  const launch=async()=>{
    if(!snapshot||!item||!key||launching.current||job||available!==true)return
    launching.current=true;setBusy(true);setError('');setStatus('Queuing saved revision');lastLaunch.current=key;runningKey.current=key;setResult(null)
    try{const r=await marketPost<{job_id:string}>('/api/user-scripts/'+item.id+'/run',{revision:item.revision,snapshot,profile,confirm_readonly:true});setJob(r.job_id)}
    catch(e){setError(readableError(e));setStatus('');setAuto(false)}finally{launching.current=false;setBusy(false)}
  }
  useEffect(()=>{
    if(!job)return
    let alive=true,reading=false
    const poll=async()=>{if(reading)return;reading=true;try{const j=await marketApi<Job>('/api/jobs/'+job);if(!alive)return;setStatus(j.stage||j.status)
      if(j.status==='complete'){setJob('');if(j.result){setResult(j.result);setResultKey(runningKey.current);setStatus('Saved result · revision '+j.result.script_revision)}else setError('Completed job has no available result. Reopen the saved run in My Scripts.')}
      else if(['error','cancelled','interrupted'].includes(j.status)){setJob('');setError(j.error||j.status);setAuto(false)}
    }catch(e){if(alive){setError(readableError(e));setAuto(false)}}finally{reading=false}}
    void poll();const timer=window.setInterval(()=>void poll(),1000);return()=>{alive=false;window.clearInterval(timer)}
  },[job])
  useEffect(()=>{if(automatic&&auto&&key&&key!==lastLaunch.current&&!busy&&!job&&available===true&&!document.hidden)void launch()},[automatic,auto,key,busy,job,available])
  const stop=async()=>{setAuto(false);try{await marketPost('/api/workspace/jobs/'+job+'/cancel',{});setStatus('Cancellation requested')}catch(e){setError(readableError(e))}}
  return <section className="ql-saved-runner" aria-label={kind==='model'?'Custom model execution':'Custom spread scanner execution'}>
    <div className="ql-saved-runner-head"><div><h3>{kind==='model'?'Run a registered Python model':'Custom Python spread ranking'}</h3><p className="ws-caption">Pinned saved revision · isolated computation · no order or built-in model approval.</p></div><button type="button" className="ws-button" onClick={()=>void refresh()}>Refresh scripts</button></div>
    <div className="ql-monitor-form"><label>Saved {kind}<select aria-label={'Saved '+kind+' revision'} value={selected} disabled={busy||!!job} onChange={e=>{setSelected(e.target.value);setAuto(false)}}><option value="">Choose a saved {kind}</option>{scripts.map(s=><option key={s.id} value={s.id}>{s.name} · v{s.revision}</option>)}</select></label><label>Profile<select value={profile} disabled={busy||!!job} onChange={e=>{setProfile(e.target.value as typeof profile);setAuto(false)}}><option value="stdlib">Standard library</option><option value="scientific">Scientific packages</option></select></label>
      <button type="button" className="ws-button primary" disabled={!item||!snapshot?.rows.length||busy||!!job||available!==true} onClick={()=>void launch()}>Run saved {kind}</button>{job&&<button type="button" className="ws-button" onClick={()=>void stop()}>Stop job</button>}
      {automatic&&<label className="ql-monitor-consent"><input type="checkbox" checked={auto} disabled={!item||!snapshot?.rows.length||available!==true} onChange={e=>setAuto(e.target.checked)}/> Re-score changed candidate sets while this page is open</label>}
    </div>
    <p className="ws-caption">{snapshot?snapshot.title+' · '+snapshot.rows.length+' rows · '+snapshot.provenance:'Attach input data first.'} {available===false?'Isolated runner unavailable. Check Settings → Python Environment.':''}</p>
    {error&&<p role="alert" className="qpw-error">{error}</p>}{status&&<p role="status">{status}</p>}
    {result&&!same&&<p className="ws-caption">Inputs or revision changed. Previous output remains saved but is no longer applied to these candidates.</p>}
    {result&&same&&<><p>{result.script_name} · v{result.script_revision} · {result.warning}</p>
      {result.ranking&&<div className="ws-table-scroll"><p>{result.ranking_note} The original feasibility gate is not changed by this score.</p><table><thead><tr><th>Custom rank</th><th>Candidate</th><th>Score</th>{onInspect&&<th>Details</th>}</tr></thead><tbody>{result.ranking.map(r=><tr key={r.rank}><td>{r.rank}</td><td>{String(r.row[1]??r.key)}</td><td>{r.score.toPrecision(6)}</td>{onInspect&&<td><button type="button" className="ws-button" onClick={()=>onInspect(r.key)}>Inspect candidate</button></td>}</tr>)}</tbody></table></div>}
      <ResearchPlot plot={result.plot} provenance="custom-python-snapshot" allowApply={false}/><details><summary>Saved execution evidence</summary><p>Run {result.run_id}</p><p>Code SHA-256 {result.source_sha256}</p><p>Input SHA-256 {result.snapshot_sha256}</p></details></>}
  </section>
}
