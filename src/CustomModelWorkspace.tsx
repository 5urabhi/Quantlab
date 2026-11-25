import {useEffect,useState} from 'react'
import {marketApi,readableError} from './tradingCockpitApi'
import SavedScriptRunner from './SavedScriptRunner'
import type {PythonSnapshot} from './pythonBridge'
type Dataset={id:string;label:string}
type Table={selected_columns:string[];rows:Record<string,string>[];has_more:boolean;warning:string}
const example=JSON.stringify({title:'User-defined parameter grid',provenance:'User-provided theoretical inputs, not market observations',columns:['x','value'],rows:[[1,1],[2,4],[3,9]]},null,2)
export default function CustomModelWorkspace({datasets,selectedDataset,initialScriptId,onBack}:{datasets:Dataset[];selectedDataset:string;initialScriptId?:string;onBack?:()=>void}){
  const [source,setSource]=useState<'dataset'|'manual'>('dataset')
  const [dataset,setDataset]=useState(selectedDataset)
  const [tables,setTables]=useState<string[]>([])
  const [file,setFile]=useState('')
  const [page,setPage]=useState(1)
  const [query,setQuery]=useState('')
  const [manual,setManual]=useState(example)
  const [snapshot,setSnapshot]=useState<PythonSnapshot|null>(null)
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  const [more,setMore]=useState(false)
  useEffect(()=>{let alive=true;setTables([]);setFile('');setSnapshot(null);if(!dataset)return
    void marketApi<{available_tables:string[]}>('/api/data-manager/datasets/'+encodeURIComponent(dataset)).then(d=>{if(alive){setTables(d.available_tables);setFile(d.available_tables[0]||'')}}).catch(e=>{if(alive)setError(readableError(e))})
    return()=>{alive=false}
  },[dataset])
  const change=()=>{setSnapshot(null);setError('');setMore(false)}
  const load=async()=>{
    setBusy(true);setError('');setSnapshot(null)
    try{
      if(source==='manual'){
        const d=JSON.parse(manual) as PythonSnapshot
        if(!d||typeof d.title!=='string'||!Array.isArray(d.columns)||!d.columns.length||!d.columns.every(c=>typeof c==='string'&&c.trim())||new Set(d.columns).size!==d.columns.length||!Array.isArray(d.rows)||!d.rows.length||d.rows.length>3000||!d.rows.every(r=>Array.isArray(r)&&r.length===d.columns.length&&r.every(v=>v===null||typeof v==='string'||typeof v==='boolean'||(typeof v==='number'&&Number.isFinite(v)))))throw Error('Provide a named-column snapshot with 1–3,000 rows.')
        setSnapshot({...d,provenance:'User-provided input; not independently source verified'})
      }else{
        const p=new URLSearchParams({file,page:String(page),per_page:'100',query})
        const d=await marketApi<Table>('/api/data-manager/datasets/'+encodeURIComponent(dataset)+'/table?'+p)
        if(!d.rows.length)throw Error('No source rows match this selection')
        setSnapshot({title:(datasets.find(x=>x.id===dataset)?.label||dataset)+' · '+file,provenance:'Local source table page '+page+'; original cell text (parse numeric fields in Python)',columns:d.selected_columns,rows:d.rows.map(r=>d.selected_columns.map(c=>r[c]??null))})
        setMore(d.has_more);if(d.warning)setError(d.warning)
      }
    }catch(e){setError(readableError(e))}finally{setBusy(false)}
  }
  return <section className="ql-custom-model" aria-label="Native custom model workspace">
    <header className="ql-saved-runner-head"><div><h2>Custom model laboratory</h2><p className="ws-caption">Use the same saved model code for theoretical parameter grids or selected local source tables. Results are custom calculations, not approved built-in model results.</p></div>{onBack&&<button type="button" className="ws-button" onClick={onBack}>← Model catalog</button>}</header>
    <div className="ws-actions"><button type="button" className="ws-button primary" onClick={()=>window.dispatchEvent(new CustomEvent('quantlab:python-script',{detail:{name:'New custom model',kind:'model',code:'def analyze(data):\n    x = [float(row[1]) for row in data["rows"]]\n    return {"title": "Custom result", "x_label": data["columns"][0], "y_label": "Squared value", "traces": [{"name": "Squared", "y": [v*v for v in x]}]}'}}))}>Create model in Python</button>{initialScriptId&&<button type="button" className="ws-button" onClick={()=>window.dispatchEvent(new CustomEvent('quantlab:open-saved-script',{detail:initialScriptId}))}>Edit selected model</button>}</div>
    <section className="ql-saved-runner"><h3>Model inputs</h3><div className="ql-monitor-form"><label>Input type<select value={source} onChange={e=>{setSource(e.target.value as typeof source);change()}}><option value="dataset">Local dataset table</option><option value="manual">Parameter / scenario grid</option></select></label>
      {source==='dataset'&&<><label>Dataset<select disabled={busy} value={dataset} onChange={e=>{setDataset(e.target.value);setPage(1);change()}}><option value="">Choose dataset</option>{datasets.map(d=><option value={d.id} key={d.id}>{d.label}</option>)}</select></label><label>Table<select disabled={busy} value={file} onChange={e=>{setFile(e.target.value);setPage(1);change()}}>{tables.map(t=><option value={t} key={t}>{t}</option>)}</select></label><label>Page<input type="number" min={1} max={1000} value={page} disabled={busy} onChange={e=>{setPage(Math.min(1000,Math.max(1,Number(e.target.value)||1)));change()}}/></label><label>Source row filter<input value={query} maxLength={100} disabled={busy} onChange={e=>{setQuery(e.target.value);setPage(1);change()}}/></label></>}
      <button type="button" className="ws-button primary" disabled={busy||(source==='dataset'&&(!dataset||!file))} onClick={()=>void load()}>{busy?'Reading…':'Attach model inputs'}</button></div>
      {source==='manual'&&<textarea aria-label="Model parameter grid JSON" value={manual} disabled={busy} maxLength={400000} onChange={e=>{setManual(e.target.value);change()}}/>}
      {error&&<p role="alert">{error}</p>}{snapshot&&<details open><summary>{snapshot.rows.length} attached rows {more?'· more source rows available':''}</summary><div className="ws-table-scroll"><table><thead><tr>{snapshot.columns.map((c,i)=><th key={i}>{c}</th>)}</tr></thead><tbody>{snapshot.rows.slice(0,8).map((r,i)=><tr key={i}>{r.map((c,j)=><td key={j}>{String(c??'Missing')}</td>)}</tr>)}</tbody></table></div><p className="ws-caption">{snapshot.provenance}</p></details>}
    </section><SavedScriptRunner kind="model" snapshot={snapshot} initialScriptId={initialScriptId}/></section>
}
