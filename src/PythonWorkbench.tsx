import {useEffect,useState} from 'react'
import ResearchPlot,{type ResearchPlotData} from './ResearchPlots'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
import {PYTHON_SNAPSHOT_EVENT,PYTHON_SCRIPT_EVENT,STRATEGY_SCRIPT_EVENT,applyPythonResult,type PythonSnapshot} from './pythonBridge'
import './python-workbench.css'
import PythonCodeEditor from './PythonCodeEditor'

type Kind='strategy'|'indicator'|'chart'|'research'|'model'|'scanner'|'risk'|'transform'
type Meta={id:string;name:string;kind:Kind;revision:number;updated_utc:string}
type Revision={revision:number;created_utc:string;name:string;kind:Kind}
type Script={script_id:string;revision:number;name:string;kind:Kind;code:string;revisions:Revision[]}
type SavedRun={id:string;title:string;created_utc:string;input_rows:number}
type Result={run_id:string;plot:ResearchPlotData;source_sha256:string;snapshot_sha256:string;input_rows:number;warning:string;ranking?:{rank:number;key:string;score:number;row:(string|number|null)[]}[];ranking_columns?:string[];ranking_note?:string}
type Job={id:string;status:string;stage?:string;error?:string;result?:Result}
const KINDS:Kind[]=['strategy','indicator','chart','research','model','scanner','risk','transform']
const EXAMPLE=`# Standard-library Python. The first column is the chart X coordinate.
def analyze(data):
    columns = data["columns"]
    rows = data["rows"]
    # Select the first numeric value column. Missing inputs stay missing.
    i = next((j for j in range(1, len(columns))
              if any(type(row[j]) in (int, float) for row in rows)), None)
    if i is None:
        raise ValueError("Choose a numeric value column")
    values = [row[i] if type(row[i]) in (int, float) else None for row in rows]
    return {"title": "Custom snapshot analysis",
            "x_label": columns[0], "y_label": columns[i],
            "traces": [{"name": columns[i], "y": values}]}
`
const STRATEGY=`# Current-session completed candles only
def signal(history):
    if len(history) < 10:
        return "HOLD"
    return "UP" if history[-1]["close"] > history[-10]["close"] else "DOWN"
`
const DRAFT='ql-v3-python-draft'
const SCRIPT_IDENTITY='ql-v3-python-identity'
function initialIdentity():Script|null{
  try{const item=JSON.parse(sessionStorage.getItem(SCRIPT_IDENTITY)||'null');if(item&&typeof item.script_id==='string'&&Number.isInteger(item.revision)&&Array.isArray(item.revisions))return item as Script}catch{/* optional recovery */}
  return null
}
function initialDraft(){
  try{const saved=JSON.parse(sessionStorage.getItem(DRAFT)||'null')
    if(saved&&typeof saved.code==='string'&&typeof saved.name==='string'&&KINDS.includes(saved.kind))return saved as {code:string;name:string;kind:Kind}
  }catch{/* optional browser recovery */}
  return {name:'My Python analysis',kind:'chart' as Kind,code:EXAMPLE}
}
export default function PythonWorkbench({open,onOpen,onClose,onStrategy,onNotebook,contextLabel}:{open:boolean;onOpen:()=>void;onClose:()=>void;onStrategy:()=>void;onNotebook?:()=>void;contextLabel:string}){
  const [draft,setDraft]=useState(initialDraft)
  const [scripts,setScripts]=useState<Meta[]>([])
  const [current,setCurrent]=useState<Script|null>(initialIdentity)
  useEffect(()=>{try{if(current)sessionStorage.setItem(SCRIPT_IDENTITY,JSON.stringify(current));else sessionStorage.removeItem(SCRIPT_IDENTITY)}catch{/* optional recovery */}},[current])
  const [profile,setProfile]=useState<'stdlib'|'scientific'>(()=>{try{return localStorage.getItem('ql-python-profile')==='scientific'?'scientific':'stdlib'}catch{return 'stdlib'}})
  useEffect(()=>{try{localStorage.setItem('ql-python-profile',profile)}catch{/* optional */}},[profile])
  const [snapshot,setSnapshot]=useState<PythonSnapshot|null>(null)
  const [available,setAvailable]=useState<boolean|null>(null)
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')
  const [busy,setBusy]=useState(false)
  const [jobId,setJobId]=useState(()=>{try{return sessionStorage.getItem('ql-v3-chart-job')||''}catch{return ''}})
  const [job,setJob]=useState<Job|null>(null)
  const [result,setResult]=useState<Result|null>(null)
  const [runSource,setRunSource]=useState<PythonSnapshot|null>(null)
  const [runs,setRuns]=useState<SavedRun[]>([])
  const [expanded,setExpanded]=useState(false)
  const [view,setView]=useState<'output'|'input'>('output')
  const [legacy,setLegacy]=useState<Record<string,string>>({})
  useEffect(()=>{try{sessionStorage.setItem(DRAFT,JSON.stringify(draft))}catch{/* explicit backend save remains available */}},[draft])
  useEffect(()=>{
    const handler=(e:Event)=>{
      setSnapshot((e as CustomEvent<PythonSnapshot>).detail);setError('');setNotice('Snapshot attached. It is fixed until you attach another.');setView('input');onOpen()
    }
    const scriptHandler=(e:Event)=>{const item=(e as CustomEvent<{name:string;code:string;kind:Kind}>).detail;setCurrent(null);setDraft(item);setNotice('Python script attached. Save to keep a backend revision.');onOpen()}
    window.addEventListener(PYTHON_SNAPSHOT_EVENT,handler)
    window.addEventListener(PYTHON_SCRIPT_EVENT,scriptHandler)
    return()=>{window.removeEventListener(PYTHON_SNAPSHOT_EVENT,handler);window.removeEventListener(PYTHON_SCRIPT_EVENT,scriptHandler)}
  },[onOpen])
  const refresh=async()=>{
    try{const data=await marketApi<{scripts:Meta[];sandbox:{available:boolean}}>('/api/user-scripts');setScripts(data.scripts);setAvailable(data.sandbox.available)}
    catch(e){setError(readableError(e))}
    try{const r=await marketApi<{runs:SavedRun[]}>('/api/user-script-runs');setRuns(r.runs)}catch{/* library may be temporarily unavailable */}
    try{const local=JSON.parse(localStorage.getItem('quantlab_python_editor_v1')||'{}');setLegacy(Object.fromEntries(Object.entries(local).filter(([,v])=>typeof v==='string')) as Record<string,string>)}catch{setLegacy({})}
  }
  useEffect(()=>{if(open)void refresh()},[open])
  useEffect(()=>{
    if(!jobId)return
    let alive=true,reading=false
    const poll=async()=>{
      if(reading)return;reading=true
      try{const next=await marketApi<Job>('/api/jobs/'+encodeURIComponent(jobId))
        if(!alive)return;setJob(next)
        if(next.status==='complete'){
          if(next.result?.plot){setResult(next.result);setView('output');setNotice('Custom analysis complete and saved locally.');void refresh()}
          else setError('Completed job has no available chart payload. Rerun with the saved script.')
          setJobId('');try{sessionStorage.removeItem('ql-v3-chart-job')}catch{/* optional */}
        }else if(['error','cancelled','interrupted'].includes(next.status)){
          setError(next.error||'Research job '+next.status);setJobId('');try{sessionStorage.removeItem('ql-v3-chart-job')}catch{/* optional */}
        }
      }catch(e){if(alive)setError(readableError(e))}
      finally{reading=false}
    }
    void poll();const timer=window.setInterval(()=>void poll(),1200)
    return()=>{alive=false;window.clearInterval(timer)}
  },[jobId])
  const load=async(id:string,revision?:number)=>{
    setBusy(true);setError('')
    try{const item=await marketApi<Script>('/api/user-scripts/'+encodeURIComponent(id)+(revision?'?revision='+revision:''))
      setCurrent(item);setDraft({name:item.name,kind:item.kind,code:item.code});setNotice('Loaded revision '+item.revision+'. Saving an older revision requires Save as new.')
    }catch(e){setError(readableError(e))}finally{setBusy(false)}
  }
  useEffect(()=>{const handler=(e:Event)=>{const id=(e as CustomEvent<string>).detail;if(typeof id==='string'){onOpen();void load(id)}};window.addEventListener('quantlab:open-saved-script',handler);return()=>window.removeEventListener('quantlab:open-saved-script',handler)},[])
  const save=async(asNew=false)=>{
    setBusy(true);setError('');setNotice('')
    try{const item=await marketPost<Script>('/api/user-scripts',{...draft,...(current&&!asNew?{script_id:current.script_id,expected_revision:current.revision}:{})})
      setCurrent(item);setNotice('Saved to local backend · revision '+item.revision);await refresh()
    }catch(e){setError(readableError(e))}finally{setBusy(false)}
  }
  const run=async()=>{
    if(!snapshot||jobId)return
    setBusy(true);setError('');setNotice('');setRunSource(snapshot);setResult(null)
    try{const data=await marketPost<{job_id:string;status:string}>('/api/user-scripts/chart/run',{code:draft.code,snapshot,profile,kind:draft.kind,confirm_readonly:true})
      setJobId(data.job_id);setJob({id:data.job_id,status:data.status});setView('output');try{sessionStorage.setItem('ql-v3-chart-job',data.job_id)}catch{/* optional */}
    }catch(e){setError(readableError(e))}finally{setBusy(false)}
  }
  const stopJob=async()=>{
    if(!jobId)return
    try{await marketPost('/api/workspace/jobs/'+encodeURIComponent(jobId)+'/cancel',{});setNotice('Cancellation requested.')}
    catch(e){setError(readableError(e))}
  }
  const openRun=async(id:string)=>{
    try{const next=await marketApi<Result>('/api/user-script-runs/'+encodeURIComponent(id));setResult(next);setRunSource(null);setView('output')}
    catch(e){setError(readableError(e))}
  }
  const apply=(mode:'companion'|'overlay')=>{
    if(!result||!runSource?.targetId)return
    const ok=applyPythonResult({snapshot:runSource,plot:result.plot,runId:result.run_id,mode})
    if(ok){setNotice('Custom output attached to original chart.');onClose()}
    else setError('Source chart or its observations changed, or overlay units do not match. Reattach the current snapshot or use a companion plot.')
  }
  const launchStrategy=()=>{
    if(draft.kind!=='strategy')return
    try{sessionStorage.setItem('ql-v2-python-unsaved-draft',draft.code);localStorage.setItem('ql-python-profile',profile)}catch{setError('Browser draft storage unavailable. Export and paste into the strategy editor.');return}
    onStrategy();window.dispatchEvent(new CustomEvent(STRATEGY_SCRIPT_EVENT,{detail:draft.code}));onClose()
  }
  const notebook=()=>{
    if(!onNotebook)return
    try{
      const cells=[{kind:'markdown',source:'# '+draft.name+'\nCopied from My Scripts. Review the input and assumptions.'},{kind:'code',source:draft.code}]
      if(snapshot&&draft.kind!=='strategy')cells.push({kind:'code',source:'result = analyze(data)\nshow_chart(result["title"], result["x_label"], result["y_label"], [row[0] for row in data["rows"]], result["traces"])'})
      const raw=JSON.stringify({title:draft.name,cells,snapshot:snapshot?{title:snapshot.title,provenance:snapshot.provenance,columns:snapshot.columns,rows:snapshot.rows}:null})
      if(new Blob([raw]).size>450000)throw Error('Snapshot is too large for a saved notebook. Select a smaller viewport.')
      sessionStorage.setItem('ql-notebook-attachment',raw);onNotebook()
    }catch(e){setError(readableError(e))}
  }
  const exportCode=()=>{
    const url=URL.createObjectURL(new Blob([draft.code],{type:'text/x-python;charset=utf-8'}))
    const a=document.createElement('a');a.href=url;a.download=(draft.name.replace(/[^a-zA-Z0-9_-]+/g,'-')||'quantlab-script')+'.py';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
  }
  const locked=busy||!!jobId
  const runnable=['chart','indicator','research','model','scanner','risk','transform'].includes(draft.kind)
  return <section className={'qpw-shell '+(expanded?'qpw-expanded':'')} hidden={!open} aria-label="Python research workspace">
    <header className="qpw-header"><div><strong>Python workspace</strong><small>{contextLabel} · isolated snapshot research</small></div><div className="qpw-actions">
      <button type="button" onClick={()=>setExpanded(v=>!v)}>{expanded?'Restore':'Expand'}</button>
      <button type="button" onClick={onClose}>Minimize</button></div></header>
    <div className="qpw-body">
      <aside className="qpw-library"><h3>My scripts</h3><button type="button" disabled={locked} onClick={()=>{setCurrent(null);setDraft({name:'New script',kind:'chart',code:EXAMPLE})}}>New script</button>
        <button type="button" onClick={()=>void refresh()}>Refresh library</button>
        {scripts.map(s=><button className={current?.script_id===s.id?'selected':''} type="button" key={s.id} disabled={locked} onClick={()=>void load(s.id)}>{s.name}<small>{s.kind} · v{s.revision}</small></button>)}
        {runs.length>0&&<details><summary>Saved custom chart runs</summary>{runs.map(r=><button type="button" key={r.id} disabled={locked} onClick={()=>void openRun(r.id)}>{r.title}<small>{r.created_utc.slice(0,10)} · {r.input_rows} rows</small></button>)}</details>}
        {Object.keys(legacy).length>0&&<details><summary>Browser-saved strategies</summary>{Object.entries(legacy).map(([name,code])=><button type="button" key={name} disabled={locked} onClick={()=>{setCurrent(null);setDraft({name,kind:'strategy',code});setNotice('Use Save to import this script to the local backend.')}}>{name}</button>)}</details>}
      </aside>
      <div className="qpw-editor">
        <div className="qpw-actions"><label>Name<input value={draft.name} maxLength={100} onChange={e=>setDraft(d=>({...d,name:e.target.value}))}/></label><label>Category<select value={draft.kind} onChange={e=>setDraft(d=>({...d,kind:e.target.value as Kind}))}>{KINDS.map(k=><option key={k}>{k}</option>)}</select></label>
          <label>Profile<select value={profile} onChange={e=>setProfile(e.target.value as typeof profile)}><option value="stdlib">Standard library</option><option value="scientific">Scientific packages</option></select></label><button type="button" disabled={locked} onClick={()=>setDraft(d=>({...d,code:d.kind==='strategy'?STRATEGY:EXAMPLE}))}>Load example</button></div>
        <PythonCodeEditor value={draft.code} onChange={code=>setDraft(d=>({...d,code}))} label="Reusable Python code" disabled={locked} onRun={runnable&&snapshot&&!locked&&available!==false?()=>void run():undefined}/>
        <div className="qpw-actions"><button className="primary" type="button" disabled={locked} onClick={()=>void save()}>Save</button><button type="button" disabled={locked} onClick={()=>void save(true)}>Save as new</button><button type="button" onClick={exportCode}>Export .py</button>{onNotebook&&<button type="button" disabled={locked} onClick={notebook}>Create notebook</button>}
          {current&&<label>Version<select value={current.revision} disabled={locked} onChange={e=>void load(current.script_id,Number(e.target.value))}>{current.revisions.map(v=><option key={v.revision} value={v.revision}>v{v.revision} · {v.created_utc.slice(0,10)}</option>)}</select></label>}
          {jobId&&<button type="button" onClick={()=>void stopJob()}>Stop job</button>}
          {draft.kind==='strategy'?<button className="primary" type="button" onClick={launchStrategy}>Open in strategy editor</button>:<button className="primary" type="button" onClick={()=>void run()} disabled={!runnable||!snapshot||locked||available===false}>Run snapshot</button>}
        </div>
        <p className="qpw-note">{draft.kind==='strategy'?'Strategies run through the existing causal BANKNIFTY backtest editor.':'Define analyze(data) returning title, x_label, y_label and traces (one finite number or null per input row). Other categories use this snapshot interface. Saved revisions can also be scheduled in Strategies → Running Python or the custom model/scanner catalog.'}</p>
      </div>
      <div className="qpw-context"><div className="qpw-actions"><button type="button" onClick={()=>setView('input')} aria-pressed={view==='input'}>Input</button><button type="button" onClick={()=>setView('output')} aria-pressed={view==='output'}>Output</button></div>
        {error&&<p role="alert" className="qpw-error">{error}</p>}{notice&&<p role="status">{notice}</p>}
        <p className="qpw-note">Sandbox: {available===null?'Checking':available?'Installed · kernel permission checked at run':'Unavailable · install bubblewrap and prlimit'}. {profile==='scientific'?'Scientific system packages must pass the isolated import test in Settings → Python Environment.':'Standard library profile.'} No orders or broker credentials.</p>
        {view==='input'?snapshot?<><h4>{snapshot.title}</h4><p>{snapshot.rows.length} rows · {snapshot.provenance}</p><p>Columns: {snapshot.columns.join(' · ')}</p><pre>{JSON.stringify(snapshot.rows.slice(0,5),null,2)}</pre><button type="button" disabled={locked} onClick={()=>setSnapshot(null)}>Detach snapshot</button></>:<p>Choose Python analysis on a compatible chart to attach a fixed data snapshot.</p>:<>{jobId&&<p role="status">{job?.status||'queued'} · {job?.stage||'Isolated analysis'}</p>}{result?<><p>{result.warning} · {result.input_rows} rows</p>{runSource?.targetId&&<div className="qpw-actions"><button type="button" onClick={()=>apply('companion')}>Add companion chart</button><button type="button" onClick={()=>apply('overlay')}>Overlay same units</button></div>}{result.ranking&&<><p>{result.ranking_note}</p><div className="ws-table-scroll"><table><thead><tr><th>Rank</th><th>Custom score</th>{result.ranking_columns?.map((c,i)=><th key={i}>{c}</th>)}</tr></thead><tbody>{result.ranking.map(r=><tr key={r.rank}><td>{r.rank}</td><td>{r.score.toPrecision(5)}</td>{r.row.map((v,i)=><td key={i}>{v??'Missing'}</td>)}</tr>)}</tbody></table></div></>}<ResearchPlot plot={result.plot} provenance="custom-python-snapshot" allowApply={false}/><details><summary>Reproducibility hashes</summary><p>Code: {result.source_sha256}</p><p>Input: {result.snapshot_sha256}</p></details></>:<p>No custom result yet.</p>}</>}
      </div>
    </div>
  </section>
}
