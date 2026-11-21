import {useCallback,useEffect,useState} from 'react'
import {
  Activity,ArrowRight,BarChart3,CheckCircle2,Code2,
  Database,FlaskConical,LoaderCircle,RefreshCw,Settings2,ShieldCheck,
  SlidersHorizontal,TrendingUp,X,AlertTriangle
} from 'lucide-react'
import './quantlab-v2.css'

type Recorder={
  armed:boolean;state:string;connected:boolean;received_pairs:number
  snapshots_saved:number;last_packet_utc:string|null;last_error:string|null
  contracts?:unknown[];sockets_connected?:number;contracts_above?:number
  contracts_below?:number
}
type Job={id:string;kind:string;status:string;stage?:string;percent?:number
  error?:string;created_utc?:string;result?:unknown}
type RecorderReply={value:Recorder|null;error:string}

function getError(error:unknown){return error instanceof Error?error.message:String(error)}
function useRecorder():RecorderReply{
  const [value,setValue]=useState<Recorder|null>(null)
  const [error,setError]=useState('')
  useEffect(()=>{
    let mounted=true
    const check=async()=>{
      try{
        const response=await fetch('/api/trading-cockpit/auto-depth/status')
        if(!response.ok)throw Error('Recorder status: HTTP '+response.status)
        const result=await response.json() as Recorder
        if(mounted){setValue(result);setError('')}
      }catch(e){if(mounted)setError(getError(e))}
    }
    void check()
    const timer=window.setInterval(()=>{void check()},15000)
    return()=>{mounted=false;window.clearInterval(timer)}
  },[])
  return {value,error}
}
export function RecorderBadge({onOpen}:{onOpen:()=>void}){
  const {value,error}=useRecorder()
  const [now,setNow]=useState(Date.now())
  useEffect(()=>{const timer=window.setInterval(()=>setNow(Date.now()),10000)
    return()=>window.clearInterval(timer)},[])
  const age=value?.last_packet_utc?Math.max(0,Math.floor((now-Date.parse(value.last_packet_utc))/1000)):null
  const fresh=Boolean(value?.armed&&value.state==='recording_original_depth'&&age!==null&&age<=30)
  const armed=Boolean(value?.armed)
  const label=error?'Recorder unavailable':fresh?'Recording 20-level':
    armed?'Recorder armed':'Recorder off'
  const detail=error?error:fresh?String(value?.snapshots_saved??0)+' saved · '+String(age)+'s packet age':
    armed?'Last source packet '+(age===null?'unavailable':age+'s ago'):
    'Enable in Settings'
  return <button type="button" className={'v2-recorder '+(fresh?'fresh':armed?'armed':'idle')}
    onClick={onOpen} aria-label={'Recorder status: '+label+'. '+detail}
    title={label+' · '+detail}>
    <span className="v2-status-light"/><span className="v2-recorder-text">
      <strong>{label}</strong><small>{detail}</small>
    </span>
  </button>
}
export function JobsDrawer({open,onClose,onOpenFull}:{
  open:boolean;onClose:()=>void;onOpenFull:()=>void
}){
  const [jobs,setJobs]=useState<Job[]>([])
  const [error,setError]=useState('')
  const [loading,setLoading]=useState(true)
  const refresh=useCallback(async()=>{
    try{
      const response=await fetch('/api/workspace/jobs')
      if(!response.ok)throw Error('Job feed HTTP '+response.status)
      const result=await response.json() as {jobs?:Job[]}
      setJobs(Array.isArray(result.jobs)?result.jobs:[])
      setError('')
    }catch(e){setError(getError(e))}
    finally{setLoading(false)}
  },[])
  useEffect(()=>{
    if(!open)return
    void refresh()
    const timer=window.setInterval(()=>{void refresh()},5000)
    const onEscape=(event:KeyboardEvent)=>{if(event.key==='Escape')onClose()}
    window.addEventListener('keydown',onEscape)
    return()=>{window.clearInterval(timer);window.removeEventListener('keydown',onEscape)}
  },[open,refresh,onClose])
  if(!open)return null
  const active=jobs.filter(x=>['queued','running'].includes(x.status))
  const previous=jobs.filter(x=>!['queued','running'].includes(x.status))
  const entry=(item:Job)=><article className="v2-job" key={item.id}>
    <div><strong>{item.kind.replaceAll('_',' ')}</strong>
      <span className={'v2-job-status '+item.status}>{item.status}</span>
    </div>
    <small>{item.stage||item.id}</small>
    {typeof item.percent==='number'&&<progress max="100" value={Math.max(0,Math.min(100,item.percent))}
      aria-label={'Progress for '+item.kind}/>}
    {item.error&&<p className="v2-job-error" role="alert">{item.error}</p>}
  </article>
  return <div className="v2-drawer-backdrop" onMouseDown={event=>{
    if(event.target===event.currentTarget)onClose()
  }}>
    <aside className="v2-jobs-drawer" role="dialog" aria-modal="true"
      aria-label="QuantLab research jobs">
      <header><div><span className="v2-eyebrow">TASK CENTER</span>
        <h2>Jobs & downloads</h2><p>Follow work without leaving your current page.</p></div>
        <button type="button" onClick={onClose} aria-label="Close jobs"><X size={18}/></button></header>
      <div className="v2-drawer-actions">
        <button onClick={()=>void refresh()}><RefreshCw size={15}/> Refresh</button>
        <button onClick={()=>{onClose();onOpenFull()}}>Full job history <ArrowRight size={14}/></button>
      </div>
      {error&&<p className="v2-job-error" role="alert">{error}</p>}
      {loading&&<p className="v2-muteds"><LoaderCircle size={15}/> Reading local job queue…</p>}
      <h3>Active · {active.length}</h3>
      {active.length?active.map(entry):<p className="v2-empty-compact">No running research jobs.</p>}
      <h3>Recent results · {previous.length}</h3>
      {previous.length?previous.slice(0,25).map(entry):
        <p className="v2-empty-compact">No completed research jobs in this queue yet.</p>}
      <p className="v2-drawer-note">Live Dhan WebSocket recording is a separate service and
        continues when you open or close this drawer.</p>
    </aside>
  </div>
}

type CardSpec={title:string;subtitle:string;caption:string;icon:typeof Activity;
  onOpen:()=>void;readiness?:string}
function LaunchCard({title,subtitle,caption,icon:Icon,onOpen,readiness}:CardSpec){
  return <button type="button" className="v2-launch-card" onClick={onOpen}>
    <span className="v2-launch-icon"><Icon size={23}/></span>
    <strong>{title}</strong><p>{subtitle}</p>
    <span className="v2-launch-caption">{readiness&&<i>{readiness}</i>}{caption}
      <ArrowRight size={17}/></span>
  </button>
}
export function StrategyLibraryV2({onEMA,onPython,onOptions,onData}:{
  onEMA:()=>void;onPython:()=>void;onOptions:()=>void;onData:()=>void
}){
  return <div className="v2-layout-section">
    <div className="v2-section-head">
      <div><span className="v2-eyebrow">BUILD → BACKTEST → UNDERSTAND</span>
        <h2>Strategy Library</h2>
        <p>Study BANKNIFTY signals against real recorded index candles, then
          measure options outcomes only when genuine contract history is available.</p></div>
      <button className="v2-secondary" onClick={onData}><Database size={15}/> Source readiness</button>
    </div>
    <div className="v2-launch-grid">
      <LaunchCard title="EMA Crossover" subtitle="One pair, chosen values, or every 11,026 valid fast/slow combinations. Inspect the top five and trade timing."
        caption="Open EMA Explorer" icon={TrendingUp} onOpen={onEMA} readiness="Ready for index research"/>
      <LaunchCard title="Python Strategy Editor" subtitle="Paste your own signal(history) callback, run isolated index backtests and inspect charts without stopping market capture."
        caption="Open Python Editor" icon={Code2} onOpen={onPython} readiness="Read-only sandbox"/>
      <LaunchCard title="BANKNIFTY Options Backtest" subtitle="Map index signals to genuine CE/PE contract snapshots, verify lots and premium fills, and compare after-cost outcomes."
        caption="Open Backtest" icon={BarChart3} onOpen={onOptions} readiness="Historical options evidence required"/>
    </div>
    <div className="v2-method-banner">
      <ShieldCheck size={19}/>
      <div><strong>Source-first research, never paper profits labeled as real trades.</strong>
        <p>Index-directional P&L is a hypothetical reference; executable CE/PE performance
          requires actual option-chain or historical contract observations.</p></div>
    </div>
  </div>
}
export function V2HomeLaunchers({onStrategy,onModel,onData}:{
  onStrategy:()=>void;onModel:()=>void;onData:()=>void
}){
  return <section className="v2-layout-section" aria-label="Choose your next research task">
    <div className="v2-section-head"><div><span className="v2-eyebrow">TODAY IN QUANTLAB</span>
      <h2>What would you like to research?</h2>
      <p>Start with a question. QuantLab reuses your local source history and archives the result.</p>
    </div></div>
    <div className="v2-launch-grid">
      <LaunchCard title="Test BANKNIFTY signals" subtitle="Explore EMA crossovers, replay signals or paste Python. No live recording interruption."
        caption="Open Strategies" icon={TrendingUp} onOpen={onStrategy}/>
      <LaunchCard title="Run mathematical models" subtitle="Choose stochastic, optimization, volatility, risk or index-construction research."
        caption="Browse Model Catalog" icon={FlaskConical} onOpen={onModel}/>
      <LaunchCard title="Complete missing data" subtitle="Reuse, download and inspect original market observations in one shared data library."
        caption="Open Data Center" icon={Database} onOpen={onData}/>
    </div>
  </section>
}
export function ConnectionsLandingV2({apiHealthy,tokenConfigured,onConfigure,
  onRecording,onDiagnostics,onData}:{
  apiHealthy:boolean;tokenConfigured:boolean;onConfigure:()=>void;
  onRecording:()=>void;onDiagnostics:()=>void;onData:()=>void
}){
  return <section className="v2-layout-section v2-connections-home"
    aria-label="Connections overview">
    <div className="v2-section-head"><div>
      <span className="v2-eyebrow">LOCAL DATA ACCESS</span>
      <h2>Your connections</h2>
      <p>Manage only what needs attention. QuantLab keeps collection independent
        of which screen you open.</p>
    </div></div>
    <div className="v2-connection-status" role="status">
      <div><span>Local Python engine</span><strong>
        {apiHealthy?'Available':'Unavailable'}
      </strong><small>127.0.0.1:8765 · local computer only</small></div>
      <div><span>Dhan credentials</span><strong>
        {tokenConfigured?'Configured':'Not configured'}
      </strong><small>Presence does not guarantee an unexpired token</small></div>
      <div><span>Trading permissions</span><strong>Orders disabled</strong>
        <small>Read-only market research</small></div>
    </div>
    <div className="v2-launch-grid">
      <LaunchCard title="Manage Dhan connection"
        subtitle="Inspect token validity or supply a new authorized market-data token."
        caption="Open connection details" icon={Database} onOpen={onConfigure}/>
      <LaunchCard title="Automatic recording"
        subtitle="Choose original 20-level BANKNIFTY depth capture and check packet coverage."
        caption="Recorder settings" icon={Activity} onOpen={onRecording}/>
      <LaunchCard title="Check system health"
        subtitle="Review backend, saved jobs, source integrity and recent market packets."
        caption="Open diagnostics" icon={ShieldCheck} onOpen={onDiagnostics}/>
    </div>
    <button type="button" className="v2-secondary v2-connection-data-action"
      onClick={onData}><Database size={15}/> Browse saved market data
      <ArrowRight size={15}/></button>
  </section>
}

export function SettingsPreferencesV2(){
  const [density,setDensity]=useState(()=>{
    try{return localStorage.getItem('ql-v2-density')==='compact'?'compact':'comfortable'}
    catch{return 'comfortable'}
  })
  const [motion,setMotion]=useState(()=>{
    try{return localStorage.getItem('ql-v2-motion')!=='reduced'}catch{return true}
  })
  useEffect(()=>{
    document.documentElement.dataset.qlDensity=density
    try{localStorage.setItem('ql-v2-density',density)}catch{}
  },[density])
  useEffect(()=>{
    document.documentElement.dataset.qlMotion=motion?'normal':'reduced'
    try{localStorage.setItem('ql-v2-motion',motion?'normal':'reduced')}catch{}
  },[motion])
  return <section className="v2-layout-section">
    <div className="v2-section-head"><div><h2>Appearance & units</h2>
      <p>Readability settings apply to this browser only.</p></div></div>
    <div className="v2-settings-grid">
      <label>Workspace density
        <select value={density} onChange={event=>setDensity(event.target.value as typeof density)}>
          <option value="comfortable">Comfortable (recommended)</option>
          <option value="compact">Compact</option>
        </select>
      </label>
      <label>Animation & motion
        <select value={motion?'normal':'reduced'} onChange={event=>setMotion(event.target.value==='normal')}>
          <option value="normal">Normal motion</option>
          <option value="reduced">Reduced motion</option>
        </select>
      </label>
    </div>
    <div className="v2-method-banner"><Settings2 size={18}/><div><strong>Market units remain explicit.</strong>
      <p>Indian market sessions use IST; money uses ₹, return uses %, transaction
      costs use bps and the BANKNIFTY index uses points.</p></div></div>
  </section>
}
type DiagnosticCheck={
  name:string;status:'healthy'|'waiting'|'attention';detail:string
}
function recorderEvidence(source:Recorder):DiagnosticCheck{
  const name='Dhan market capture'
  const timestamp=Date.parse(source.last_packet_utc||'')
  const age=Number.isFinite(timestamp)
    ?Math.max(0,Math.floor((Date.now()-timestamp)/1000)):null
  const ageLabel=age===null?'no original packets recorded':age+'s since last original packet'
  if(!source.armed)return {name,status:'waiting',
    detail:'Recorder off · enable it in Settings → Automatic Recording'}
  if(source.state==='armed_waiting_for_nse_hours')return {name,status:'waiting',
    detail:'Armed · waiting for regular NSE market hours · '+ageLabel}
  if(source.state==='other_local_worker')return {name,status:'waiting',
    detail:'Another local QuantLab worker owns the recorder · inspect that process'}
  if(source.state==='recording_original_depth'&&source.connected&&age!==null&&age<=30){
    return {name,status:'healthy',
      detail:'Recording original 20-level depth · '+source.snapshots_saved+
      ' snapshots saved · '+age+'s packet age'}
  }
  const state=source.state?.replaceAll('_',' ')||'unknown'
  return {name,status:'attention',
    detail:'No verified fresh 20-level depth · '+state+' · '+ageLabel+
      (source.last_error?' · '+source.last_error:'')}
}
async function diagnosticJson<T>(path:string):Promise<T>{
  const response=await fetch(path,{cache:'no-store'})
  if(!response.ok)throw Error('HTTP '+response.status)
  return (await response.json()) as T
}
export function DiagnosticsV2({onRepair,onData}:{
  onRepair:()=>void;onData:()=>void
}){
  const [checks,setChecks]=useState<DiagnosticCheck[]>([])
  const [busy,setBusy]=useState(true)
  const refresh=useCallback(async()=>{
    setBusy(true)
    const [api,recorder,jobs]=await Promise.allSettled([
      diagnosticJson<unknown>('/api/health'),
      diagnosticJson<Recorder>('/api/trading-cockpit/auto-depth/status'),
      diagnosticJson<{jobs?:Job[]}>('/api/workspace/jobs')
    ])
    const rows:DiagnosticCheck[]=[
      api.status==='fulfilled'
        ?{name:'Python API',status:'healthy',detail:'Health endpoint responded successfully'}
        :{name:'Python API',status:'attention',detail:getError(api.reason)},
      recorder.status==='fulfilled'
        ?recorderEvidence(recorder.value)
        :{name:'Dhan market capture',status:'attention',
          detail:'Recorder status unavailable · '+getError(recorder.reason)},
      jobs.status==='fulfilled'&&Array.isArray(jobs.value.jobs)
        ?{name:'Research job queue',status:'healthy',
          detail:jobs.value.jobs.filter(x=>['queued','running'].includes(x.status)).length+
            ' active · '+jobs.value.jobs.length+' recent jobs'}
        :{name:'Research job queue',status:'attention',
          detail:jobs.status==='rejected'?getError(jobs.reason):'Job list not returned'}
    ]
    setChecks(rows)
    setBusy(false)
  },[])
  useEffect(()=>{
    void refresh()
    const timer=window.setInterval(()=>{void refresh()},15000)
    return()=>window.clearInterval(timer)
  },[refresh])
  return <section className="v2-layout-section">
    <div className="v2-section-head"><div><h2>Diagnostics</h2>
      <p>Source-aware local checks update automatically every 15 seconds. An HTTP 200
        alone does not mean Dhan is sending original 20-level packets.</p></div>
      <button className="v2-secondary" onClick={()=>void refresh()} disabled={busy}>
        <RefreshCw size={15}/> Recheck</button></div>
    <div className="v2-health-list" aria-live="polite">{checks.map(item=><div
      key={item.name} data-status={item.status}>
      {item.status==='healthy'?<CheckCircle2 size={19}/>:
        item.status==='waiting'?<Activity size={19}/>:<AlertTriangle size={19}/>}
      <strong>{item.name}</strong>
      <span>{item.status==='healthy'?'Healthy':
        item.status==='waiting'?'Waiting':'Needs attention'} · {item.detail}</span>
    </div>)}</div>
    <div className="v2-action-row">
      <button className="v2-primary" onClick={onRepair}><SlidersHorizontal size={17}/> Open detailed provider diagnostics</button>
      <button className="v2-secondary" onClick={onData}><Database size={17}/> Review data quality</button>
    </div>
    <p className="v2-microcopy">When the market is closed, an armed recorder may correctly be waiting.
      During live NSE hours, confirm the original packet age stays fresh while you
      navigate pages and run a separate Python/EMA backtest. These checks are read-only.</p>
  </section>
}
export function QuickPageNote({title,description,children}:{
  title:string;description:string;children?:React.ReactNode
}){
  return <div className="v2-workspace-guide"><div>
    <strong>{title}</strong><p>{description}</p>
  </div>{children}</div>
}
