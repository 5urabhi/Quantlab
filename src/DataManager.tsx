import {lazy,Suspense,useCallback, useEffect, useState} from 'react'
import {Activity, AlertTriangle, ArrowRight, CheckCircle2, ChevronLeft, ChevronRight,
  Database, FileSpreadsheet, HardDrive, History, RefreshCw, Search, ShieldCheck, Wrench} from 'lucide-react'
import './data-manager.css'
import {openSnapshotInPython,type PythonSnapshot} from './pythonBridge'
import ContextDrawer from './ContextDrawer'
const MarketLibraryPanel=lazy(()=>import('./MarketLibraryPanel'))
const DataAcquisitionPanel=lazy(()=>import('./DataAcquisitionPanel'))
const ManagedDatabaseBrowser=lazy(()=>import('./ManagedDatabaseBrowser'))
const ColumnarAnalyticsPanel=lazy(()=>import('./ColumnarAnalyticsPanel'))
const SourceFallbackPanel=lazy(()=>import('./SourceFallbackPanel'))
const ResearchReadinessPanel=lazy(()=>import('./ResearchReadinessPanel'))
const MarketMicrostructurePanel=lazy(()=>import('./MarketMicrostructurePanel'))

type Dataset = {id:string;label:string;kind:string;ready:boolean;missing:string[];basis:string}
type Event = {id:number;occurred_utc:string;category:string;status:string;summary:string}
type Batch = {id:string;status:string;selection:string;processed:number;total:number;errors:number;recovered_checkpoints?:number}
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
type OperationalHealth = {
  checked_utc:string;overall_state:'operational'|'needs_attention'|'needs_repair';
  read_only:boolean;market_data_certified:boolean;
  databases:{id:string;label:string;state:string;size_bytes?:number}[];
  storage:{free_bytes:number|null;total_bytes:number|null;low_space:boolean|null};
  derived_views?:{state:string;source_rows?:number;reason?:string;verified_content?:boolean};
  job_failures_or_interrupted:number|null;dhan_interrupted_batches:number|null;
  dhan_paused_batches:number|null;columnar:{state:string;ready?:boolean};
  kite:{app_configured:boolean;local_session_present:boolean;master_current:boolean};
  blockers:{component:string;kind:string;action:string}[];
  warnings:{kind:string;message:string}[];note:string
}
type Section = 'library'|'datasets'|'research'|'acquire'|'explorer'|'database'|'analytics'|'microstructure'|'sources'|'activity'
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
export default function DataManager({
  onSelectDataset,onChanged,onOpenDhan,onOpenModels,initialSection='library',integrated=false
}:{
  onSelectDataset:(id:string)=>void;onChanged:()=>void;
  onOpenDhan?:()=>void;onOpenModels?:()=>void
  initialSection?:Section;integrated?:boolean
}){
  const [section,setSection]=useState<Section>(initialSection)
  useEffect(()=>setSection(initialSection),[initialSection])
  const [systemHealth,setSystemHealth]=useState<OperationalHealth|null>(null)
  const [healthBusy,setHealthBusy]=useState(false)
  const [healthError,setHealthError]=useState('')
  const [overview,setOverview]=useState<Overview|null>(null)
  const [selected,setSelected]=useState('')
  const [detail,setDetail]=useState<Detail|null>(null)
  const [file,setFile]=useState('prices.csv')
  const [table,setTable]=useState<Table|null>(null)
  const [inspection,setInspection]=useState<PythonSnapshot|null>(null)
  useEffect(()=>setInspection(null),[selected,file,section])
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
  const checkHealth=useCallback(async()=>{
    setHealthBusy(true);setHealthError('')
    try{setSystemHealth(await get<OperationalHealth>('/system-health'))}
    catch(e){setHealthError(e instanceof Error?e.message:String(e))}
    finally{setHealthBusy(false)}
  },[])
  useEffect(()=>{
    if(section==='activity')void checkHealth()
  },[section,checkHealth])
  const select=(id:string)=>{setSelected(id);setPage(1);setQuery('');setInput('');setSection('explorer')}
  const items=overview?.datasets||[]
  const onAcquisitionComplete=useCallback((datasetId:string)=>{
    onSelectDataset(datasetId)
    setSelected(datasetId)
    void refresh()
    onChanged()
  },[onSelectDataset,onChanged,refresh])
  return <div className={'qm-root'+(integrated?' v2-integrated':'')}>
    <div className="qm-hero">
      <div><div className="qm-eyebrow"><Database size={15}/> QUANTLAB · DATA CONTROL CENTER</div>
        <h2>Database Manager</h2><p>Explore market data, inspect its provenance and monitor automatic recovery in one place.</p>
      </div>
      {!integrated&&<div className="qm-hero-actions">
        <button type="button" className="ws-button secondary" onClick={()=>void refresh()}><RefreshCw size={15}/> Refresh</button>
        <button type="button" className="ws-button primary" disabled={busy} onClick={()=>void repair()}>
          <Wrench size={15}/>{busy?'Checking...':'Check & repair safely'}
        </button>
      </div>}
    </div>
    {error&&<div role="alert" className="qm-alert"><AlertTriangle size={16}/>{error}</div>}
    {notice&&<div role="status" className="qm-notice"><CheckCircle2 size={16}/>{notice}</div>}
    {integrated&&<section className="qm-task-overview" aria-label="Choose a data task">
      <div className="qm-task-head"><h3>What would you like to do?</h3>
        <p>Pick one task. Your data stays in the shared library.</p></div>
      <div className="qm-task-grid">
        {([
          {id:'library',title:'Browse market data',detail:'Search instruments, indexes and sectors.',
            icon:Database},
          {id:'acquire',title:'Get missing data',detail:'Reuse saved history or append what a model needs.',
            icon:ArrowRight},
          {id:'explorer',title:'Inspect stored records',detail:'Open real prices, tables, and original files.',
            icon:Search},
          {id:'activity',title:'Health & recovery',detail:'Check local data quality and interrupted jobs.',
            icon:ShieldCheck},
        ] as const).map(task=><button key={task.id} type="button"
          className={'qm-task-card '+(section===task.id?'active':'')}
          aria-current={section===task.id?'step':undefined}
          onClick={()=>setSection(task.id)}>
          <task.icon size={20}/>
          <span><strong>{task.title}</strong><small>{task.detail}</small></span>
          <ArrowRight size={16}/></button>)}
      </div>
    </section>}
    <div className="qm-stat-grid">
      <div><Database size={18}/><span>Source snapshots</span><strong>{overview?fmt(overview.statistics.datasets):'…'}</strong></div>
      <div><ShieldCheck size={18}/><span>Files ready</span><strong>{overview?fmt(overview.statistics.file_ready):'…'}</strong></div>
      <div><AlertTriangle size={18}/><span>Need attention</span><strong>{overview?fmt(overview.statistics.needs_attention):'…'}</strong></div>
      <div><HardDrive size={18}/><span>Catalog databases</span><strong>{overview?humanBytes(overview.statistics.catalog_database_bytes):'…'}</strong></div>
    </div>
    <details className={integrated?'v2-database-tools':'v2-database-expanded'} open={!integrated}>
      <summary>Additional database tools · original snapshots, analytics, microstructure & maintenance</summary>
    <nav aria-label="Database Manager sections" className="qm-tabs">
      {(['library','acquire','research','datasets','explorer','database','analytics','microstructure','sources','activity'] as Section[]).map(key=>
        <button key={key} className={section===key?'active':''} onClick={()=>setSection(key)}>
          {{library:'Market Library',datasets:'Source snapshots',research:'Research readiness',acquire:'Get model data',explorer:'Data Explorer',database:'Database tables',analytics:'Fast analytics',microstructure:'Minute & order book',sources:'Sources & provenance',activity:'Activity & recovery'}[key]}
        </button>)}
    </nav>
    </details>
    <Suspense fallback={<div className="qm-panel" role="status">
      Loading data tools for {section.replaceAll('_',' ')}…
    </div>}>
    {section==='library'&&<MarketLibraryPanel
      onOpenDownloads={onOpenDhan} onChooseModel={()=>setSection('acquire')}
      onInspectOriginal={id=>select(id)}
      onChanged={()=>{void refresh();onChanged()}}/>}
    {section==='datasets'&&<div className="qm-panel">
      <div className="qm-panel-title"><h3>Original snapshots & research source files</h3>
        <span>Advanced · raw evidence retained for reproducibility</span></div>
      {items.length===0?<p>No datasets available yet. Use Download Market Data to acquire data.</p>:
      <div className="qm-datasets">{items.map(d=><button key={d.id} onClick={()=>select(d.id)}>
        <div className="qm-dataset-icon"><FileSpreadsheet size={19}/></div>
        <div className="qm-dataset-name"><strong>{d.label}</strong><small>{d.id} · {d.kind}</small></div>
        <span className={'qm-badge '+(d.ready?'ok':'warn')}>{d.ready?'Files ready':'Needs inputs'}</span>
        <ArrowRight size={17}/>
      </button>)}</div>}
      <p className="qm-caption">These are original, immutable source snapshots and legacy imports,
        not separate stock databases to manage. Browse the unified Market Library
        for deduplicated stocks and dated index or sector views. Files ready does
        not independently certify financial data.</p>
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
        {integrated&&table&&table.rows.length>0&&<button type="button" className="ws-button secondary" onClick={()=>openSnapshotInPython({title:detail.dataset.label+' · '+file,provenance:'Displayed source-table page '+page+' · original cell text',columns:table.selected_columns,rows:table.rows.map(row=>table.selected_columns.map(key=>row[key]??null))})}>Analyze displayed page in Python</button>}
        {table?<div className="qm-scroll"><table><thead><tr>{table.selected_columns.map(h=><th key={h}>{h}</th>)}<th>Details</th></tr></thead>
          <tbody>{table.rows.map((r,i)=><tr key={i}>{table.selected_columns.map(k=><td key={k} title={r[k]}>{r[k]}</td>)}<td><button type="button" className="ws-button secondary" aria-label={"Inspect displayed row "+(i+1)} onClick={()=>setInspection({title:detail.dataset.label+" · "+file,provenance:"Dataset "+selected+" · displayed page "+page+", row "+(i+1)+" · original cell text",columns:[...table.selected_columns],rows:[table.selected_columns.map(key=>r[key]??null)]})}>Inspect</button></td></tr>)}</tbody></table>
          {table.rows.length===0&&<p>No matching rows.</p>}</div>:<p>{detail.available_tables.length?'Loading observations…':'No inspectable CSV tables are present.'}</p>}
        {table&&<div className="qm-pager"><span>{table.scan_limit_reached?'Bounded scan':'Source rows scanned'}: {fmt(table.scanned_rows)}</span>
          <div><button disabled={page===1} onClick={()=>setPage(v=>Math.max(1,v-1))}><ChevronLeft size={15}/> Previous</button>
            <span>Page {page}</span><button disabled={!table.has_more} onClick={()=>setPage(v=>v+1)}>Next <ChevronRight size={15}/></button></div></div>}
        {inspection&&<ContextDrawer title={inspection.title} subtitle={inspection.provenance} onClose={()=>setInspection(null)}><div className="ws-actions">{integrated&&<button type="button" className="ws-button primary" onClick={()=>{openSnapshotInPython(inspection);setInspection(null)}}>Analyze row in Python</button>}<button type="button" className="ws-button secondary" onClick={()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(inspection,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='quantlab-source-row.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}}>Export row JSON</button></div><dl>{inspection.columns.map((column,i)=><div key={column}><dt>{column}</dt><dd>{inspection.rows[0][i]===null?'Not present':String(inspection.rows[0][i])}</dd></div>)}</dl></ContextDrawer>}
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
    {section==='activity'&&<div className="qm-panel">
      <div className="qm-panel-title"><h3><ShieldCheck size={18}/> Whole-workstation health</h3>
        <div className="qm-hero-actions">
          <button className="ws-button secondary" disabled={healthBusy}
            onClick={()=>void checkHealth()}>
            <RefreshCw size={14}/>{healthBusy?'Checking…':'Run integrity checks'}
          </button>
          <button className="ws-button primary" disabled={busy}
            onClick={()=>void repair()}>
            <Wrench size={14}/>{busy?'Running safe maintenance…':'Repair local indexes'}
          </button>
        </div></div>
      <p className="qm-caption">Read-only local checks of research databases, disk space,
        source-mirror freshness and interrupted jobs. No broker calls, no automatic
        source rewrite and no claim of verified historical market evidence.</p>
      {healthError&&<p className="qm-alert" role="alert"><AlertTriangle size={16}/>{healthError}</p>}
      {systemHealth&&<div>
        <div className="qm-stat-grid">
          <div><ShieldCheck size={16}/><span>Operational state</span>
            <strong>{systemHealth.overall_state.replaceAll('_',' ')}</strong></div>
          <div><HardDrive size={16}/><span>Available storage</span>
            <strong>{systemHealth.storage.free_bytes===null?'Unavailable':
              humanBytes(systemHealth.storage.free_bytes)}</strong></div>
          <div><Activity size={16}/><span>Failed/interrupted jobs</span>
            <strong>{systemHealth.job_failures_or_interrupted??'Unavailable'}</strong></div>
          <div><Database size={16}/><span>Data cache</span>
            <strong>{systemHealth.columnar.state.replaceAll('_',' ')}</strong></div>
        </div>
        <div className="qm-job-grid">
          <div><strong>Managed database integrity</strong>
            {systemHealth.databases.map(x=><div className="qm-job" key={x.id}>
              <span>{x.label}</span><small>{x.state.replaceAll('_',' ')}
                {x.size_bytes!==undefined?' · '+humanBytes(x.size_bytes):''}</small>
            </div>)}</div>
          <div><strong>Recovery readiness</strong>
            <div className="qm-job"><span>Shared model price views</span>
              <small>{systemHealth.derived_views?
                systemHealth.derived_views.state.replaceAll('_',' '):'Not inspected'}
                {systemHealth.derived_views?.source_rows!==undefined?
                  ' · '+fmt(systemHealth.derived_views.source_rows)+' source rows':''}
              </small></div>
            <div className="qm-job"><span>Dhan interrupted batches</span>
              <small>{systemHealth.dhan_interrupted_batches??'Unavailable'} ·
                {' '}{systemHealth.dhan_paused_batches??'Unavailable'} paused</small></div>
            <div className="qm-job"><span>Zerodha local configuration</span>
              <small>{systemHealth.kite.app_configured?'Configured':'Not configured'} ·
                {' '}{systemHealth.kite.local_session_present?'Session present':'Sign-in required'}</small></div>
          </div>
        </div>
        {systemHealth.blockers.map((x,i)=><div className="qm-alert" key={i}>
          <AlertTriangle size={15}/><div><strong>{x.component.replaceAll('_',' ')}</strong>
            <small>{x.action}</small></div></div>)}
        {systemHealth.warnings.map((x,i)=><div className="qm-event" key={i}>
          <AlertTriangle size={15}/><div><strong>{x.kind.replaceAll('_',' ')}</strong>
            <small>{x.message}</small></div></div>)}
      </div>}
    </div>}
    {section==='activity'&&<div className="qm-panel"><div className="qm-panel-title"><h3><Activity size={18}/> Jobs and recovery</h3>
        <button className="ws-button secondary" onClick={()=>void refresh()}><RefreshCw size={14}/> Refresh</button></div>
      <div className="qm-job-grid"><div><strong>Recent jobs</strong>
        {(overview?.jobs||[]).map(j=><div className="qm-job" key={j.id}><span>{j.kind}</span>
          <small>{j.status}{j.error?' · '+j.error:''}</small></div>)}
        {!overview?.jobs.length&&<p>No recent jobs.</p>}</div><div><strong>Dhan download batches</strong>
        {(overview?.batches||[]).map(b=><div className="qm-job" key={b.id}><span>{b.selection} · {b.status}</span>
          <small>{b.processed}/{b.total} instruments · {b.errors} failed
            {(b.recovered_checkpoints||0)>0&&<> · {b.recovered_checkpoints}
              {' '}source-verified checkpoint{b.recovered_checkpoints===1?'':'s'} recovered</>}
          </small></div>)}
        {!overview?.batches.length&&<p>No saved download batches.</p>}</div></div>
      <h4><History size={16}/> Automatic maintenance history</h4>
      {(overview?.events||[]).map(e=><div className="qm-event" key={e.id}>
        {e.status==='complete'?<CheckCircle2 size={16}/>:<AlertTriangle size={16}/>}
        <div><strong>{e.summary}</strong><small>{e.category.replaceAll('_',' ')} · {e.occurred_utc}</small></div></div>)}
      {!overview?.events.length&&<p>No automatic repair events recorded yet.</p>}
    </div>}
    </Suspense>
  </div>
}
