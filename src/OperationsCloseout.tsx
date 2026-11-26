import {useCallback,useEffect,useState} from 'react'
import {marketApi,readableError} from './tradingCockpitApi'
import ResearchPlot from './ResearchPlots'
import './operations-closeout.css'

type Nav=(route:string)=>void
type Recorder={armed:boolean;state:string;connected:boolean;last_packet_utc:string|null;snapshots_saved:number;received_pairs:number}
type Job={id:string;kind:string;status:string;stage?:string}
type Inventory={checked_utc:string;cache_age_seconds:number;sources:{id:string;label:string;count:number|null;unit:string;first:string|null;last:string|null;state:string;time_basis:string}[]}
type Storage={checked_utc:string;overall_state:string;read_only:boolean;market_data_certified:boolean;databases:{id:string;label:string;state:string;size_bytes?:number}[];storage:{free_bytes:number|null;total_bytes:number|null;low_space:boolean|null};blockers:{component:string;kind:string;action:string}[];warnings:{kind:string;message:string}[];note:string}
type ReportRecord={id:string;title:string;updated_utc:string;payload:Record<string,unknown>;archived:boolean;trashed:boolean}
type RunDetail={id:string;source:Record<string,unknown>;meta:{first_price_date:string;last_price_date:string;generated_utc:string;limitations:string[]};artifacts:string[]}
const fmt=(n:number|null|undefined)=>typeof n==='number'&&Number.isFinite(n)?n.toLocaleString('en-IN'):'Unavailable'
const label=(s:string)=>s.replaceAll('_',' ')
const stamp=(s:string|null|undefined)=>s?s.replace('T',' ').replace('+00:00',' UTC'):'Unavailable'
const bytes=(n:number|null|undefined)=>typeof n==='number'&&Number.isFinite(n)&&n>=0?(n/1073741824).toLocaleString('en-IN',{maximumFractionDigits:3})+' GiB':'Unavailable'
function useLocal<T>(path:string,initial=true){
 const [data,setData]=useState<T|null>(null)
 const [error,setError]=useState('')
 const [busy,setBusy]=useState(initial)
 const [revision,setRevision]=useState(initial?1:0)
 const refresh=useCallback(()=>setRevision(n=>n+1),[])
 useEffect(()=>{
   if(!revision)return
   let active=true
   const c=new AbortController()
   setBusy(true);setError('')
   void marketApi<T>(path,{signal:c.signal}).then(result=>{if(active)setData(result)}).catch(e=>{if(active)setError(readableError(e))}).finally(()=>{if(active)setBusy(false)})
   return()=>{active=false;c.abort()}
 },[path,revision])
 return {data,error,busy,refresh}
}
function PanelError({error,stale=false}:{error:string;stale?:boolean}){
 return error?<p className="qoc-error" role="alert">{error}{stale?' Last successful response remains visible; refresh before relying on it.':''}</p>:null
}
function Stat({name,value,detail}:{name:string;value:string|number;detail:string}){
 return <div className="qoc-stat"><span>{name}</span><strong>{value}</strong><small>{detail}</small></div>
}
export function HomeOperations({onNavigate}:{onNavigate:Nav}){
 const recorder=useLocal<Recorder>('/api/trading-cockpit/auto-depth/status')
 const jobs=useLocal<{jobs:Job[]}>('/api/workspace/jobs')
 const inventory=useLocal<Inventory>('/api/data-manager/inventory?per_page=1',false)
 const [now,setNow]=useState(Date.now())
 useEffect(()=>{
   const timer=window.setInterval(()=>{setNow(Date.now());if(!document.hidden){recorder.refresh();jobs.refresh()}},30000)
   return()=>window.clearInterval(timer)
 },[recorder.refresh,jobs.refresh])
 const r=recorder.data
 const packetAge=r?.last_packet_utc?Math.max(0,Math.floor((now-Date.parse(r.last_packet_utc))/1000)):null
 const fresh=Boolean(r?.armed&&r.connected&&r.state==='recording_original_depth'&&packetAge!==null&&Number.isFinite(packetAge)&&packetAge<=30)
 const j=jobs.data?.jobs
 const inv=inventory.data
 return <section className="qoc-panel" aria-label="Workstation operations overview">
   <header><div><small>LOCAL WORKSTATION · SOURCE EVIDENCE</small><h2>Operations overview</h2><p>Recorder, research jobs and stored market observations have separate states. Opening this page does not start a market connection or download.</p></div><button type="button" className="ws-button" disabled={recorder.busy||jobs.busy} onClick={()=>{setNow(Date.now());recorder.refresh();jobs.refresh()}}>Refresh operational status</button></header>
   <div className="qoc-grid">
     <Stat name="Automatic depth capture" value={recorder.error?'Unavailable':!r?'Checking…':fresh?'Receiving original depth':r.armed?'Armed · '+label(r.state):'Disarmed'} detail={r?.last_packet_utc?'Last packet '+stamp(r.last_packet_utc):'No reported packet timestamp'}/>
     <Stat name="Saved depth snapshots" value={recorder.error?'Unavailable':fmt(r?.snapshots_saved)} detail="Recorder-reported counter, not total database size"/>
     <Stat name="Research queue" value={jobs.error?'Unavailable':j?j.filter(v=>['queued','running'].includes(v.status)).length:'Checking…'} detail="Active jobs among returned local job records"/>
     <Stat name="Recent jobs needing review" value={jobs.error?'Unavailable':j?j.filter(v=>['error','interrupted','cancelled'].includes(v.status)).length:'Checking…'} detail="Recent queue results, not lifetime totals"/>
   </div>
   <PanelError error={recorder.error} stale={Boolean(r)}/><PanelError error={jobs.error} stale={Boolean(j)}/>
   <div className="qoc-actions"><button className="ws-button" onClick={()=>onNavigate('recordingsettings')}>Recorder settings</button><button className="ws-button" onClick={()=>onNavigate('workspacejobs')}>Research job history</button><button className="ws-button" onClick={()=>onNavigate('tradingreplay')}>Review saved market</button></div>
   <div className="qoc-subpanel"><header><div><h3>Saved market coverage</h3><p>Inspect the cached inventory without opening another provider session. Counts for different data types are never summed.</p></div><button className="ws-button" type="button" disabled={inventory.busy} onClick={inventory.refresh}>{inventory.busy?'Inspecting…':'Inspect saved coverage'}</button></header>
    <PanelError error={inventory.error} stale={Boolean(inv)}/>
    {inv?<><p className="qoc-note">Checked {stamp(inv.checked_utc)} · {inv.cache_age_seconds} seconds cache age at response.</p><div className="qoc-scroll"><table aria-label="Home stored source coverage"><thead><tr><th>Source</th><th>Saved count</th><th>First observed</th><th>Last observed</th><th>Status</th></tr></thead><tbody>{inv.sources.map(s=><tr key={s.id}><td>{s.label}<small>{s.time_basis}</small></td><td>{fmt(s.count)} {s.unit}</td><td>{stamp(s.first)}</td><td>{stamp(s.last)}</td><td>{label(s.state)}</td></tr>)}</tbody></table></div><p className="qoc-note">Observed endpoints do not imply continuous market coverage.</p></>:<p className="qoc-note">Inspect saved coverage to view actual stored dates. No data has been inferred from the connection status.</p>}
    <button className="ws-button" type="button" onClick={()=>onNavigate('data')}>Open complete Market Library</button>
   </div>
 </section>
}
export function StorageOverview({onNavigate}:{onNavigate:Nav}){
 const report=useLocal<Storage>('/api/data-manager/system-health',false)
 const h=report.data
 const total=h?.storage.total_bytes
 const free=h?.storage.free_bytes
 const used=typeof total==='number'&&typeof free==='number'&&total>0?Math.max(0,total-free):null
 const dbs=h?.databases.filter(d=>typeof d.size_bytes==='number'&&Number.isFinite(d.size_bytes))||[]
 return <section className="qoc-panel" aria-label="Local storage inventory">
   <header><div><small>LOCAL DISK · READ-ONLY CHECK</small><h2>Storage & recovery overview</h2><p>Measure the actual database files and disk free space using the operational-health endpoint. This does not purge, repair or download anything.</p></div><button className="ws-button primary" type="button" disabled={report.busy} onClick={report.refresh}>{report.busy?'Inspecting…':'Inspect storage health'}</button></header>
   <PanelError error={report.error} stale={Boolean(h)}/>
   {h&&<><div className="qoc-grid"><Stat name="Operational state" value={label(h.overall_state)} detail="Not a certification of market data"/><Stat name="Free disk space" value={bytes(free)} detail={h.storage.low_space===true?'Low-space warning':h.storage.low_space===false?'No reported low-space warning':'Not verified'}/><Stat name="Disk capacity" value={bytes(total)} detail="Filesystem capacity, not QuantLab-only usage"/><Stat name="Measured databases" value={dbs.length} detail="Main database file sizes, not all cache/WAL/archive bytes"/></div>
     {used!==null&&<div className="qoc-subpanel"><strong>Filesystem usage</strong><div className="qoc-meter" role="progressbar" aria-label="Filesystem disk usage" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.min(100,100*used/total!)}><i style={{width:Math.min(100,100*used/total!)+'%'}}/></div><span className="qoc-note">{bytes(used)} used · {bytes(free)} free</span></div>}
     {dbs.length>0&&<ResearchPlot provenance="Local measured database files" plot={{kind:'bar2d',title:'Managed database file sizes',x_label:'Managed database',y_label:'File size (MiB)',x:dbs.map(d=>d.label),traces:[{name:'Main database file',y:dbs.map(d=>d.size_bytes!/1048576)}]}}/>}
     <div className="qoc-scroll"><table aria-label="Managed database integrity"><thead><tr><th>Database</th><th>State</th><th>Main file size</th></tr></thead><tbody>{h.databases.map(d=><tr key={d.id}><td>{d.label}</td><td>{label(d.state)}</td><td>{bytes(d.size_bytes)}</td></tr>)}</tbody></table></div>
     {h.blockers.map((b,i)=><p className="qoc-error" key={i}>{b.component}: {b.action}</p>)}{h.warnings.map((w,i)=><p className="qoc-note" key={i}>{w.message}</p>)}<p className="qoc-note">{h.note} Checked {stamp(h.checked_utc)}.</p></>}
   <div className="qoc-actions"><button className="ws-button" onClick={()=>onNavigate('dataquality')}>Source quality and coverage</button><button className="ws-button" onClick={()=>onNavigate('data')}>Market Library</button></div>
 </section>
}
export function ReportWorkspace({detail,runId,runPicker,busy,onBuild,onNavigate}:{detail:RunDetail|null;runId:string;runPicker:React.ReactNode;busy:boolean;onBuild:()=>void;onNavigate:Nav}){
 const library=useLocal<{records:ReportRecord[]}>('/api/workspace/records?kind=report')
 const [query,setQuery]=useState('')
 const d=detail?.id===runId?detail:null
 const reports=(library.data?.records||[]).filter(r=>!r.trashed&&!r.archived&&r.title.toLowerCase().includes(query.toLowerCase().trim()))
 const files=d?.artifacts||[]
 const fileLink=(name:string)=>'/api/runs/'+encodeURIComponent(runId)+'/files/'+encodeURIComponent(name)
 const groups=[{title:'Research reports',files:files.filter(n=>n.endsWith('.pdf')||n.endsWith('.html'))},{title:'Data and numerical evidence',files:files.filter(n=>n.endsWith('.csv'))},{title:'Audit, manifest and provenance',files:files.filter(n=>!n.endsWith('.csv')&&!n.endsWith('.pdf')&&!n.endsWith('.html'))}]
 return <section className="qoc-panel" aria-label="Research report workspace">
  <header><div><small>REPRODUCIBLE RESEARCH</small><h2>Generate reproducible research report</h2><p>Generate and download the actual backend artifacts for a saved index experiment. Project reports are available separately below.</p></div><button className="ws-button" onClick={()=>onNavigate('projects')}>Manage projects and report sources</button></header>
  <div className="qoc-subpanel"><label className="qoc-field">Completed index experiment{runPicker}</label>
   {d?<><div className="qoc-grid"><Stat name="Run" value={d.id} detail={stamp(d.meta.generated_utc)}/><Stat name="Source classification" value={d.source.dataset_kind==='synthetic'?'Synthetic demonstration':String(d.source.dataset_kind||'User data')} detail="Not independently audited"/><Stat name="Input window" value={String(d.meta.first_price_date||'—')} detail={'Through '+String(d.meta.last_price_date||'—')}/><Stat name="Existing artifacts" value={files.length} detail="Actual saved files, not planned exports"/></div>
     <button className="ws-button primary" disabled={busy} onClick={onBuild}>Build HTML + PDF</button>
     {!groups[0].files.length&&<p className="qoc-note">No generated HTML/PDF file is present for this run. Build the report first.</p>}
     {groups.filter(g=>g.files.length).map(g=><div key={g.title}><h3>{g.title}</h3><div className="qoc-file-list">{g.files.map(name=><a className="ws-button" key={name} href={fileLink(name)} download>{name}</a>)}</div></div>)}
     {d.meta.limitations?.length>0&&<details><summary>Saved interpretation limitations</summary>{d.meta.limitations.map((s,i)=><p className="qoc-note" key={i}>{s}</p>)}</details>}</>:<p className="qoc-note">{runId?'Loading the selected saved experiment…':'No completed index experiment. Run an experiment first.'}</p>}
  </div>
  <div className="qoc-subpanel"><header><div><h3>Saved project reports</h3><p>Existing records from the research library. Report editing remains in Projects.</p></div><button className="ws-button" disabled={library.busy} onClick={library.refresh}>Refresh reports</button></header>
   <label className="qoc-field">Search reports<input aria-label="Search saved reports" type="search" value={query} onChange={e=>setQuery(e.target.value)}/></label><PanelError error={library.error} stale={Boolean(library.data)}/>
   {library.data&&!reports.length&&<p className="qoc-note">No matching active project reports.</p>}
   {reports.map(r=><div className="qoc-record" key={r.id}><div><strong>{r.title}</strong><small>{stamp(r.updated_utc)}</small></div><div className="qoc-actions">{['html','markdown','pdf'].map(format=><a className="ws-button" href={'/api/workspace/reports/'+encodeURIComponent(r.id)+'/'+format} key={format} download>{format.toUpperCase()}</a>)}</div></div>)}
  </div>
 </section>
}
export function PrivacyChecks({onNavigate}:{onNavigate:Nav}){
 const status=useLocal<{ok:boolean;read_only_market_data:boolean;broker_orders_enabled:boolean;dhan_token_configured:boolean}>('/api/health')
 const s=status.data
 return <section className="qoc-panel" aria-label="Backend safety checks"><header><div><small>LOCAL API · PERMISSIONS</small><h2>Runtime safety checks</h2><p>These values are reported by the running local API, not assumed from the theme or a stored preference.</p></div><button className="ws-button" disabled={status.busy} onClick={status.refresh}>Refresh runtime checks</button></header>
 <PanelError error={status.error} stale={Boolean(s)}/><div className="qoc-grid"><Stat name="Python API" value={status.error?'Unavailable':s?s.ok?'Responding':'Needs attention':'Checking…'} detail="Loopback health endpoint"/><Stat name="Market data access" value={!s||status.error?'Unverified':s.read_only_market_data?'Read-only':'Unexpected mode'} detail="No order permission inferred"/><Stat name="Broker execution" value={!s||status.error?'Unverified':s.broker_orders_enabled?'Unexpectedly enabled':'Disabled'} detail="Actual API-reported flag"/><Stat name="Dhan credential" value={!s||status.error?'Unverified':s.dhan_token_configured?'Configured · hidden':'Not configured'} detail="Presence does not establish token validity"/></div><div className="qoc-actions"><button className="ws-button" onClick={()=>onNavigate('connections')}>Connection management</button><button className="ws-button" onClick={()=>onNavigate('pythonenvironment')}>Python sandbox and packages</button><button className="ws-button" onClick={()=>onNavigate('diagnostics')}>System diagnostics</button></div></section>
}
