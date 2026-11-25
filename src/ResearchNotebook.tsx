import {useEffect,useState} from 'react'
import PythonCodeEditor from './PythonCodeEditor'
import ResearchPlot,{type ResearchPlotData} from './ResearchPlots'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
import type {PythonSnapshot} from './pythonBridge'
import './research-notebook.css'

type Cell={kind:'markdown'|'code';source:string}
type Draft={title:string;cells:Cell[];snapshot:PythonSnapshot|null}
type Meta={id:string;title:string;revision:number}
type Receipt={id:string;revision:number;created_utc:string}
type Doc=Draft&Meta&{source_sha256:string;revisions:{revision:number;created_utc:string}[];runs:Receipt[]}
type Output={index:number;text:string;error:string|null;charts:ResearchPlotData[]}
type Result={id:string;notebook_id:string;revision:number;profile:string;source_sha256:string;input_sha256:string;complete:boolean;outputs:Output[]}
type Job={status:string;stage?:string;error?:string;result?:Result}
const newDraft=():Draft=>({title:'Untitled research notebook',cells:[{kind:'markdown',source:'# Research question\nDocument assumptions, data source and method.'},{kind:'code',source:'import math\nvalues = [math.sqrt(x) for x in range(1, 6)]\nprint(values)\nshow_chart("Example square roots", "Input", "Square root", list(range(1, 6)), [{"name": "sqrt", "y": values}])'}],snapshot:null})
function draftFromStorage():Draft{
  try{const attached=sessionStorage.getItem('ql-notebook-attachment');if(attached){sessionStorage.removeItem('ql-notebook-attachment');sessionStorage.removeItem('ql-notebook-doc');const d=JSON.parse(attached);return {title:d.title,cells:d.cells,snapshot:d.snapshot}}
    const draft=sessionStorage.getItem('ql-notebook-draft');if(draft)return JSON.parse(draft)
  }catch{/* recoverable local browser state */}
  return newDraft()
}
function download(name:string,value:unknown){
  const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}))
  const link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
}
export default function ResearchNotebook(){
  const [draft,setDraft]=useState<Draft>(draftFromStorage)
  const [library,setLibrary]=useState<Meta[]>([])
  const [doc,setDoc]=useState<Doc|null>(()=>{try{const saved=sessionStorage.getItem('ql-notebook-doc');return saved?JSON.parse(saved):null}catch{return null}})
  const [result,setResult]=useState<Result|null>(null)
  const [jobId,setJobId]=useState(()=>{try{return sessionStorage.getItem('ql-notebook-job')||''}catch{return ''}})
  const [status,setStatus]=useState('')
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  const [profile,setProfile]=useState<'stdlib'|'scientific'>('stdlib')
  const [input,setInput]=useState('')
  const [inputOpen,setInputOpen]=useState(false)
  const [collapsed,setCollapsed]=useState<number[]>([])
  const dirty=!doc||JSON.stringify(draft)!==JSON.stringify({title:doc.title,cells:doc.cells,snapshot:doc.snapshot})
  const locked=busy||!!jobId
  const refresh=async()=>{try{setLibrary((await marketApi<{notebooks:Meta[]}>('/api/research-notebooks')).notebooks)}catch(e){setError(readableError(e))}}
  useEffect(()=>{void refresh()},[])
  useEffect(()=>{try{sessionStorage.setItem('ql-notebook-draft',JSON.stringify(draft))}catch{/* durable Save still available */}},[draft])
  useEffect(()=>{try{if(doc)sessionStorage.setItem('ql-notebook-doc',JSON.stringify(doc));else sessionStorage.removeItem('ql-notebook-doc')}catch{/* saved backend revisions remain available */}},[doc])
  const showDoc=(d:Doc)=>{setDoc(d);setDraft({title:d.title,cells:d.cells,snapshot:d.snapshot});setResult(null);setCollapsed([])}
  const load=async(id:string,revision?:number,confirm=true)=>{
    if(confirm&&dirty&&!window.confirm('Open another revision? Unsaved edits will be replaced.'))return
    setBusy(true);setError('')
    try{showDoc(await marketApi<Doc>('/api/research-notebooks/'+id+(revision?'?revision='+revision:'')));setStatus('Opened saved notebook revision.')}
    catch(e){setError(readableError(e))}finally{setBusy(false)}
  }
  useEffect(()=>{
    if(!jobId)return
    let active=true,reading=false
    const poll=async()=>{
      if(reading)return;reading=true
      try{const j=await marketApi<Job>('/api/jobs/'+jobId);if(!active)return
        setStatus(j.stage||j.status)
        if(['complete','error','cancelled','interrupted'].includes(j.status)){
          if(j.status==='complete'&&j.result){
            const d=await marketApi<Doc>('/api/research-notebooks/'+j.result.notebook_id+'?revision='+j.result.revision)
            if(!active)return
            showDoc(d);setResult(j.result);setStatus(j.result.complete?'Notebook run saved.':'Run saved; stopped at first failing cell.');void refresh()
          }else setError(j.error||'Notebook execution '+j.status+'. Open a saved revision to recover completed runs.')
          setJobId('');try{sessionStorage.removeItem('ql-notebook-job')}catch{/* optional */}
        }
      }catch(e){if(active)setError(readableError(e))}finally{reading=false}
    }
    void poll();const timer=window.setInterval(()=>void poll(),1000)
    return()=>{active=false;window.clearInterval(timer)}
  },[jobId])
  const save=async(asNew=false)=>{
    const d=await marketPost<Doc>('/api/research-notebooks',{...draft,...(doc&&!asNew?{notebook_id:doc.id,expected_revision:doc.revision}:{})})
    showDoc(d);setStatus('Saved revision '+d.revision);void refresh();return d
  }
  const saveAction=async(asNew=false)=>{setBusy(true);setError('');try{await save(asNew)}catch(e){setError(readableError(e))}finally{setBusy(false)}}
  const run=async(through?:number)=>{
    setBusy(true);setError('');setResult(null)
    try{const d=dirty?await save():doc!;const j=await marketPost<{job_id:string}>('/api/research-notebooks/'+d.id+'/run',{revision:d.revision,through,profile,confirm_readonly:true})
      setJobId(j.job_id);setStatus('Queued isolated notebook');try{sessionStorage.setItem('ql-notebook-job',j.job_id)}catch{/* optional */}
    }catch(e){setError(readableError(e))}finally{setBusy(false)}
  }
  const stop=async()=>{try{await marketPost('/api/workspace/jobs/'+jobId+'/cancel',{});setStatus('Cancellation requested')}catch(e){setError(readableError(e))}}
  const openRun=async(id:string)=>{
    if(!doc)return
    if(dirty&&!window.confirm('Restore the exact notebook revision for this run? Unsaved edits will be replaced.'))return
    setBusy(true);setError('')
    try{const r=await marketApi<Result>('/api/research-notebooks/'+doc.id+'/runs/'+id);const d=await marketApi<Doc>('/api/research-notebooks/'+doc.id+'?revision='+r.revision);showDoc(d);setResult(r);setStatus('Restored saved run.')}
    catch(e){setError(readableError(e))}finally{setBusy(false)}
  }
  const changeCells=(cells:Cell[])=>{setDraft(d=>({...d,cells}));setResult(null);setCollapsed([])}
  const edit=(index:number,source:string)=>{setDraft(d=>({...d,cells:d.cells.map((c,i)=>i===index?{...c,source}:c)}));setResult(null)}
  const move=(index:number,delta:number)=>{const cells=[...draft.cells],to=index+delta;if(to<0||to>=cells.length)return;[cells[index],cells[to]]=[cells[to],cells[index]];changeCells(cells)}
  const attach=()=>{
    setError('')
    try{const snapshot=JSON.parse(input) as PythonSnapshot
      if(!Array.isArray(snapshot.columns)||!Array.isArray(snapshot.rows)||!snapshot.rows.length||snapshot.rows.length>3000||new Blob([JSON.stringify(snapshot)]).size>450000)throw Error('Use named columns and 1–3,000 rows, under 450 KB.')
      setDraft(d=>({...d,snapshot}));setResult(null);setInputOpen(false)
    }catch(e){setError(readableError(e))}
  }
  const exportNotebook=()=>{
    const current=result&&!dirty&&result.revision===doc?.revision?result:null
    const cells=draft.cells.map((c,i)=>{
      if(c.kind==='markdown')return {cell_type:'markdown',metadata:{},source:c.source}
      const r=current?.outputs.find(o=>o.index===i)
      const outputs:unknown[]=[]
      if(r?.text)outputs.push({output_type:'stream',name:'stdout',text:r.text})
      if(r?.error)outputs.push({output_type:'stream',name:'stderr',text:r.error})
      for(const p of r?.charts||[])outputs.push({output_type:'display_data',data:{'application/json':p,'text/plain':p.title},metadata:{}})
      return {cell_type:'code',metadata:{},source:c.source,execution_count:null,outputs}
    })
    download((draft.title.replace(/[^a-zA-Z0-9_-]+/g,'-')||'notebook')+'.ipynb',{nbformat:4,nbformat_minor:4,metadata:{kernelspec:{display_name:'Python 3',language:'python',name:'python3'},quantlab:{snapshot:draft.snapshot,revision:doc?.revision,source_sha256:current?.source_sha256,notes:'QuantLab supplies data and show_chart in its isolated runner; outside QuantLab reproduce these helpers and read metadata.quantlab.snapshot.'}},cells})
  }
  return <section className="ql-notebook" aria-label="Research notebook editor">
    <aside className="ql-nb-library"><h3>My notebooks</h3><button type="button" className="ws-button primary" disabled={locked} onClick={()=>{if(dirty&&!window.confirm('Start a new notebook? Unsaved edits will be replaced.'))return;setDoc(null);setDraft(newDraft());setResult(null);setCollapsed([])}}>New notebook</button><button type="button" className="ws-button" onClick={()=>void refresh()}>Refresh library</button>{library.map(n=><button type="button" key={n.id} className={'ql-nb-item '+(doc?.id===n.id?'active':'')} disabled={locked} onClick={()=>void load(n.id)}>{n.title}<small>v{n.revision}</small></button>)}</aside>
    <div className="ql-nb-main"><header className="ql-nb-header"><div><label>Notebook title<input value={draft.title} maxLength={100} disabled={locked} onChange={e=>{setDraft(d=>({...d,title:e.target.value}));setResult(null)}}/></label><small>{dirty?'Unsaved draft':'Saved revision '+doc?.revision} · {draft.cells.length}/30 cells</small></div><div className="ws-actions"><button className="ws-button primary" type="button" disabled={locked} onClick={()=>void saveAction()}>Save notebook</button><button className="ws-button" type="button" disabled={locked} onClick={()=>void saveAction(true)}>Save as new</button><button className="ws-button" type="button" onClick={exportNotebook}>Export .ipynb</button></div></header>
      <div className="ql-nb-toolbar"><label>Python profile<select value={profile} disabled={locked} onChange={e=>setProfile(e.target.value as typeof profile)}><option value="stdlib">Standard library</option><option value="scientific">Scientific packages</option></select></label><button className="ws-button primary" type="button" disabled={locked||!draft.cells.some(c=>c.kind==='code')} onClick={()=>void run()}>Run all cells</button>{jobId&&<button className="ws-button" type="button" onClick={()=>void stop()}>Stop run</button>}{doc&&<label>Version<select value={doc.revision} disabled={locked} onChange={e=>void load(doc.id,Number(e.target.value))}>{doc.revisions.map(r=><option key={r.revision} value={r.revision}>v{r.revision}</option>)}</select></label>}</div>
      <p className="ws-caption">Every run starts a clean isolated Python process. Run through cell replays preceding Python cells in order. Edits are saved before execution. No network, broker credentials or order execution.</p>
      {error&&<p className="qpw-error" role="alert">{error}</p>}{status&&<p role="status">{status}</p>}
      <details className="ql-nb-input" open={inputOpen} onToggle={e=>setInputOpen(e.currentTarget.open)}><summary>Input data · {draft.snapshot?draft.snapshot.title+' · '+draft.snapshot.rows.length+' rows':'None (standalone calculations)'}</summary>
        <p className="ws-caption">Optional copied input is available in Python as data (columns, rows, title, provenance). Use a chart's Python analysis → Create notebook, or paste a JSON snapshot.</p>
        {draft.snapshot&&<><p>{draft.snapshot.provenance}</p><button type="button" className="ws-button" disabled={locked} onClick={()=>{setDraft(d=>({...d,snapshot:null}));setResult(null)}}>Detach input</button><button type="button" className="ws-button" onClick={()=>download('notebook-input.json',draft.snapshot)}>Export input</button></>}
        <textarea aria-label="Notebook input JSON" value={input} disabled={locked} maxLength={450000} placeholder='{"title":"Parameters","provenance":"User input","columns":["x","value"],"rows":[[1,2],[2,3]]}' onChange={e=>setInput(e.target.value)}/><button type="button" className="ws-button" disabled={locked||!input.trim()} onClick={attach}>Attach JSON</button>
      </details>
      {draft.cells.map((cell,i)=>{const out=!dirty&&result?.outputs.find(o=>o.index===i);return <article key={i} className="ql-nb-cell"><header><strong>{i+1} · {cell.kind==='code'?'Python':'Markdown notes'}</strong><div className="ws-actions">{cell.kind==='code'&&<button type="button" className="ws-button primary" disabled={locked} onClick={()=>void run(i)}>Run through cell {i+1}</button>}<button type="button" className="ws-button" aria-label={'Move cell '+(i+1)+' up'} disabled={locked||i===0} onClick={()=>move(i,-1)}>↑</button><button type="button" className="ws-button" aria-label={'Move cell '+(i+1)+' down'} disabled={locked||i===draft.cells.length-1} onClick={()=>move(i,1)}>↓</button><button type="button" className="ws-button" onClick={()=>setCollapsed(v=>v.includes(i)?v.filter(n=>n!==i):[...v,i])}>{collapsed.includes(i)?'Expand':'Collapse'}</button><button type="button" className="ws-button" disabled={locked||draft.cells.length===1} onClick={()=>{if(window.confirm('Remove this cell from the draft? Saved revisions are retained.'))changeCells(draft.cells.filter((_,k)=>k!==i))}}>Remove</button></div></header>
        {!collapsed.includes(i)&&(cell.kind==='code'?<PythonCodeEditor label={'Python cell '+(i+1)} value={cell.source} onChange={v=>{if(!locked)edit(i,v)}}/>:<textarea aria-label={'Markdown cell '+(i+1)} value={cell.source} disabled={locked} maxLength={20000} onChange={e=>edit(i,e.target.value)}/>)}
        {out&&<div className="ql-nb-output"><strong>Cell output</strong>{out.text&&<pre>{out.text}</pre>}{out.error&&<p role="alert">{out.error}</p>}{out.charts.map((plot,k)=><ResearchPlot key={k} plot={plot} provenance="custom-python-snapshot" allowApply={false}/>)}</div>}
      </article>})}
      <div className="ws-actions"><button type="button" className="ws-button" disabled={locked||draft.cells.length>=30} onClick={()=>changeCells([...draft.cells,{kind:'code',source:''}])}>Add Python cell</button><button type="button" className="ws-button" disabled={locked||draft.cells.length>=30} onClick={()=>changeCells([...draft.cells,{kind:'markdown',source:''}])}>Add Markdown cell</button></div>
      {doc&&doc.runs.length>0&&<details><summary>Saved notebook runs</summary>{doc.runs.map(r=><button type="button" key={r.id} className="ws-button" disabled={locked} onClick={()=>void openRun(r.id)}>{r.created_utc} · v{r.revision}</button>)}</details>}
      {result&&!dirty&&<details><summary>Run evidence</summary><p>Code and document SHA-256: {result.source_sha256}</p><p>Copied execution input SHA-256: {result.input_sha256}</p></details>}
    </div>
  </section>
}
