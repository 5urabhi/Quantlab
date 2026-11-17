import {useCallback, useEffect, useState} from 'react'
import {Activity, AlertTriangle, ArrowRight, CheckCircle2, ChevronLeft, ChevronRight,
  Database, FileSpreadsheet, HardDrive, History, RefreshCw, Search, ShieldCheck, Wrench} from 'lucide-react'
import './data-manager.css'
import DataAcquisitionPanel from './DataAcquisitionPanel'
import ManagedDatabaseBrowser from './ManagedDatabaseBrowser'
import ColumnarAnalyticsPanel from './ColumnarAnalyticsPanel'
import SourceFallbackPanel from './SourceFallbackPanel'
import ResearchReadinessPanel from './ResearchReadinessPanel'
import MarketMicrostructurePanel from './MarketMicrostructurePanel'

type Dataset = {id:string;label:string;kind:string;ready:boolean;missing:string[];basis:string}
type Event = {id:number;occurred_utc:string;category:string;status:string;summary:string}
type Batch = {id:string;status:string;selection:string;processed:number;total:number;errors:number}
type Job = {id:string;kind:string;status:string;error?:string}
type Overview = {
  datasets:Dataset[]
  statistics:{datasets:number;file_ready:number;needs_attention:number;active_batches:number;
    recent_failed_jobs:number;catalog_database_bytes:number}
  batches:Batch[];jobs:Job[];events:Event[]
  source_status:Record<string,Record<string,unknown>>
}
type File = {name:string;bytes:number;modified_utc:string;inspectable:boolean;manifest:boolean}
type Detail = {
  dataset:Dataset;files:File[];available_tables:string[]
  manifests:Record<string,Record<string,unknown>>
  dependencies:Array<{kind:string;id:string;title:string}>
  raw_shared_cache_protected:boolean
}
type Table = {columns:string[];selected_columns:string[];rows:Array<Record<string,string>>;
  page:number;has_more:boolean;scanned_rows:number;scan_limit_reached:boolean;warning:string}
type Quality = {file:string;sampled_rows:number;sample_limit_reached:boolean;
  first_date_in_sample:string|null;last_date_in_sample:string|null;
  checks:Record<string,number>;status:string;caveat:string}
type Section = 'datasets'|'research'|'acquire'|'explorer'|'database'|'analytics'|'microstructure'|'sources'|'activity'
const fmt = (n:number)=>n.toLocaleString()
const humanBytes = (bytes:number)=>bytes<1024?bytes+' B':bytes<1024*1024?(bytes/1024).toFixed(1)+' KB':
  (bytes/(1024*1024)).toFixed(1)+' MB'
async function get<T>(path:string,options?:RequestInit):Promise<T>{
  const r=await fetch('/api/data-manager'+path,options)
  if(!r.ok){
    let reason = 'Request failed ('+r.status+')'
    try{const b=await r.json() as {detail?:string}; if(typeof b.detail==='string')reason=b.detail}catch{/* no JSON */}
    throw new Error(reason)
  }
  return r.json() as Promise<T>
}
export default function DataManager({onSelectDataset,onChanged,onOpenDhan,onOpenModels}:{
  onSelectDataset:(id:string)=>void;onChanged:()=>void;
  onOpenDhan?:()=>void;onOpenModels?:()=>void
}){
  const [section,setSection]=useState<Section>('datasets')
  const [overview,setOverview]=useState<Overview|null>(null)
  const [selected,setSelected]=useState('')
  const [detail,setDetail]=useState<Detail|null>(null)
  const [file,setFile]=useState('prices.csv')
  const [table,setTable]=useState<Table|null>(null)
  const [quality,setQuality]=useState<Quality|null>(null)
  const [page,setPage]=useState(1)
  const [query,setQuery]=useState('')
  const [input,setInput]=useState('')
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')
  const refresh=useCallback(async()=>{
    try{const value=await get<Overview>('/overview');setOverview(value);setError('')}
    catch(e){setError(e instanceof Error?e.message:String(e))}
  },[])
  useEffect(()=>{void refresh()},[refresh])
  useEffect(()=>{
    if(!selected){setDetail(null);return}
    let live=true
    setError('')
    void get<Detail>('/datasets/'+encodeURIComponent(selected)).then(r=>{
      if(live){setDetail(r);onSelectDataset(selected);
        setFile(old=>r.available_tables.includes(old)?old:r.available_tables[0]||'prices.csv')
      }
    }).catch(e=>{if(live)setError(String(e))})
    return()=>{live=false}
  },[selected,onSelectDataset])
  useEffect(()=>{
    if(!selected||!detail||!detail.available_tables.includes(file)){setTable(null);setQuality(null);return}
    let live=true
    const params=new URLSearchParams({file,page:String(page),per_page:'35',query})
    setTable(null)
    void Promise.all([
      get<Table>('/datasets/'+encodeURIComponent(selected)+'/table?'+params.toString()),
      get<Quality>('/datasets/'+encodeURIComponent(selected)+'/quality?'+new URLSearchParams({file}).toString())
    ]).then(([t,q])=>{if(live){setTable(t);setQuality(q)}})
      .catch(e=>{if(live)setError(e instanceof Error?e.message:String(e))})
    return()=>{live=false}
  },[selected,detail,file,page,query])
  const repair=async()=>{
    setBusy(true);setNotice('');setError('')
    try{
      const r=await get<{job_id:string}>('/maintenance',{method:'POST'})
      setNotice('Safe maintenance queued as job '+r.job_id+'. Inspect Activity for results.')
      await refresh();onChanged()
    }catch(e){setError(e instanceof Error?e.message:String(e))}
    finally{setBusy(false)}
  }
  const select=(id:string)=>{setSelected(id);setPage(1);setQuery('');setInput('');setSection('explorer')}
  const items=overview?.datasets||[]
  const onAcquisitionComplete=useCallback((datasetId:string)=>{
    onSelectDataset(datasetId)
    setSelected(datasetId)
    void refresh()
    onChanged()
  },[onSelectDataset,onChanged,refresh])
  return <div className="qm-root">
    <div className="qm-hero">
      <div><div className="qm-eyebrow"><Database size={15}/> QUANTLAB · DATA CONTROL CENTER</div>
        <h2>Database Manager</h2><p>Explore market data, inspect its provenance and monitor automatic recovery in one place.</p>
      </div>
      <div className="qm-hero-actions">
        <button type="button" className="ws-button secondary" onClick={()=>void refresh()}><RefreshCw size={15}/> Refresh</button>
        <button type="button" className="ws-button primary" disabled={busy} onClick={()=>void repair()}>
          <Wrench size={15}/>{busy?'Checking...':'Check & repair safely'}
        </button>
      </div>
    </div>
    {error&&<div role="alert" className="qm-alert"><AlertTriangle size={16}/>{error}</div>}
    {notice&&<div role="status" className="qm-notice"><CheckCircle2 size={16}/>{notice}</div>}
    <div className="qm-stat-grid">
      <div><Database size={18}/><span>Datasets</span><strong>{overview?fmt(overview.statistics.datasets):'…'}</strong></div>
      <div><ShieldCheck size={18}/><span>Files ready</span><strong>{overview?fmt(overview.statistics.file_ready):'…'}</strong></div>
      <div><AlertTriangle size={18}/><span>Need attention</span><strong>{overview?fmt(overview.statistics.needs_attention):'…'}</strong></div>
      <div><HardDrive size={18}/><span>Catalog databases</span><strong>{overview?humanBytes(overview.statistics.catalog_database_bytes):'…'}</strong></div>
    </div>
    <nav aria-label="Database Manager sections" className="qm-tabs">
      {(['datasets','research','acquire','explorer','database','analytics','microstructure','sources','activity'] as Section[]).map(key=>
        <button key={key} className={section===key?'active':''} onClick={()=>setSection(key)}>
          {{datasets:'Datasets',research:'Research readiness',acquire:'Get model data',explorer:'Data Explorer',database:'Database tables',analytics:'Fast analytics',microstructure:'Minute & order book',sources:'Sources & provenance',activity:'Activity & recovery'}[key]}
        </button>)}
    </nav>
    {section==='datasets'&&<div className="qm-panel">
      <div className="qm-panel-title"><h3>Dataset inventory</h3><span>Original market history is protected</span></div>
      {items.length===0?<p>No datasets available yet. Use Download Market Data to acquire data.</p>:
      <div className="qm-datasets">{items.map(d=><button key={d.id} onClick={()=>select(d.id)}>
        <div className="qm-dataset-icon"><FileSpreadsheet size={19}/></div>
        <div className="qm-dataset-name"><strong>{d.label}</strong><small>{d.id} · {d.kind}</small></div>
        <span className={'qm-badge '+(d.ready?'ok':'warn')}>{d.ready?'Files ready':'Needs inputs'}</span>
        <ArrowRight size={17}/>
      </button>)}</div>}
      <p className="qm-caption">Files ready means required files are present, not that financial data is independently verified.</p>
    </div>}
    {section==='research'&&<ResearchReadinessPanel datasets={items}
      onAcquire={()=>setSection('acquire')} onModel={onOpenModels||(()=>setSection('acquire'))}/>}
    {section==='microstructure'&&<MarketMicrostructurePanel/>}
    {section==='acquire'&&<DataAcquisitionPanel datasets={items} onCompleted={onAcquisitionComplete}
      onOpenDhan={onOpenDhan} onOpenModels={onOpenModels}/>}
    {section==='database'&&<ManagedDatabaseBrowser/>}
    {section==='analytics'&&<ColumnarAnalyticsPanel/>}
    {section==='explorer'&&<div className="qm-panel">
      <div className="qm-panel-title"><h3>Data Explorer</h3>
        <select aria-label="Inspect dataset" value={selected} onChange={e=>select(e.target.value)}>
          <option value="">Select dataset</option>{items.map(d=><option value={d.id} key={d.id}>{d.label}</option>)}
        </select></div>
      {!detail?<p>Select any dataset above to view actual stored records, quality and dependencies.</p>:<>
        <div className="qm-info"><div><span>Dataset</span><strong>{detail.dataset.label}</strong></div>
          <div><span>Research readiness</span><strong>{detail.dataset.ready?'Required files available':'Missing inputs'}</strong></div>
          <div><span>Files</span><strong>{detail.files.length}</strong></div>
          <div><span>Saved dependencies</span><strong>{detail.dependencies.length}</strong></div></div>
        {detail.dataset.missing.length>0&&<div className="qm-alert"><AlertTriangle size={16}/>
          Missing: {detail.dataset.missing.join(', ')}</div>}
        <div className="qm-toolbar">
          <select aria-label="Choose data table" value={file} onChange={e=>{setFile(e.target.value);setPage(1)}}>
            {detail.available_tables.map(name=><option key={name} value={name}>{name}</option>)}
          </select>
          <form onSubmit={e=>{e.preventDefault();setQuery(input);setPage(1)}}>
            <Search size={15}/><input aria-label="Filter table rows" placeholder="Search stored observations"
              value={input} onChange={e=>setInput(e.target.value)}/>
            <button type="submit">Search</button>
          </form>
        </div>
        {table?<div className="qm-scroll"><table><thead><tr>{table.selected_columns.map(h=><th key={h}>{h}</th>)}</tr></thead>
          <tbody>{table.rows.map((r,i)=><tr key={i}>{table.selected_columns.map(k=><td key={k} title={r[k]}>{r[k]}</td>)}</tr>)}</tbody></table>
          {table.rows.length===0&&<p>No matching rows.</p>}</div>:<p>{detail.available_tables.length?'Loading observations…':'No inspectable CSV tables are present.'}</p>}
        {table&&<div className="qm-pager"><span>{table.scan_limit_reached?'Bounded scan':'Source rows scanned'}: {fmt(table.scanned_rows)}</span>
          <div><button disabled={page===1} onClick={()=>setPage(v=>Math.max(1,v-1))}><ChevronLeft size={15}/> Previous</button>
            <span>Page {page}</span><button disabled={!table.has_more} onClick={()=>setPage(v=>v+1)}>Next <ChevronRight size={15}/></button></div></div>}
        {table?.warning&&<p className="qm-caption">{table.warning}</p>}
        {quality&&<div className="qm-quality"><div className="qm-panel-title"><h3>Quality profile</h3>
          <span className={'qm-badge '+(quality.status==='sample_pass'?'ok':'warn')}>{quality.status.replaceAll('_',' ')}</span></div>
          <p>Sample: {fmt(quality.sampled_rows)} records · {quality.first_date_in_sample||'Unknown'} to {quality.last_date_in_sample||'Unknown'}</p>
          {Object.keys(quality.checks).length===0?<p>No structural anomalies detected in the inspected sample.</p>:
            <div className="qm-flags">{Object.entries(quality.checks).map(([k,v])=><span key={k}>{k.replaceAll('_',' ')}: {fmt(v)}</span>)}</div>}
          <small>{quality.caveat}</small></div>}
        <details className="qm-details"><summary>Original files and provenance</summary>
          {detail.files.map(f=><div className="qm-file" key={f.name}><span>{f.name}</span><small>{humanBytes(f.bytes)} · {f.modified_utc.slice(0,10)}</small></div>)}
          {Object.entries(detail.manifests).map(([name,meta])=><details key={name}><summary>{name}</summary>
            <pre>{JSON.stringify(meta,null,2)}</pre></details>)}
        </details>
        <details className="qm-details"><summary>Linked saved research ({detail.dependencies.length})</summary>
          {detail.dependencies.length===0?<p>Nothing linked in the saved resource index.</p>:
            detail.dependencies.map((x,i)=><p key={x.kind+x.id+i}>{x.kind}: {x.title} <small>({x.id})</small></p>)}
        </details>
      </>}
    </div>}
    {section==='sources'&&<><SourceFallbackPanel onChanged={()=>{void refresh();onChanged()}}/><div className="qm-panel"><div className="qm-panel-title"><h3>Source registry</h3><span>Read-only connections</span></div>
      {Object.entries(overview?.source_status||{}).map(([name,entry])=><div className="qm-source" key={name}>
        <strong>{name.replaceAll('_',' ').toUpperCase()}</strong>
        <div>{Object.entries(entry).map(([k,v])=><p key={k}><span>{k.replaceAll('_',' ')}</span><b>{typeof v==='boolean'?(v?'Yes':'No'):String(v)}</b></p>)}</div>
      </div>)}
      <p className="qm-caption">An informational NSE MCP lookup is not an authorized replacement for original backtest data or TRI.</p>
    </div></>}
    {section==='activity'&&<div className="qm-panel"><div className="qm-panel-title"><h3><Activity size={18}/> Jobs and recovery</h3>
        <button className="ws-button secondary" onClick={()=>void refresh()}><RefreshCw size={14}/> Refresh</button></div>
      <div className="qm-job-grid"><div><strong>Recent jobs</strong>
        {(overview?.jobs||[]).map(j=><div className="qm-job" key={j.id}><span>{j.kind}</span>
          <small>{j.status}{j.error?' · '+j.error:''}</small></div>)}
        {!overview?.jobs.length&&<p>No recent jobs.</p>}</div><div><strong>Dhan download batches</strong>
        {(overview?.batches||[]).map(b=><div className="qm-job" key={b.id}><span>{b.selection} · {b.status}</span>
          <small>{b.processed}/{b.total} instruments · {b.errors} failed</small></div>)}
        {!overview?.batches.length&&<p>No saved download batches.</p>}</div></div>
      <h4><History size={16}/> Automatic maintenance history</h4>
      {(overview?.events||[]).map(e=><div className="qm-event" key={e.id}>
        {e.status==='complete'?<CheckCircle2 size={16}/>:<AlertTriangle size={16}/>}
        <div><strong>{e.summary}</strong><small>{e.category.replaceAll('_',' ')} · {e.occurred_utc}</small></div></div>)}
      {!overview?.events.length&&<p>No automatic repair events recorded yet.</p>}
    </div>}
  </div>
}
