import {useCallback,useEffect,useState} from 'react'
import {Activity,AlertTriangle,BarChart3,CheckCircle2,Database,
  FileUp,Play,RefreshCw,Square,ShieldCheck} from 'lucide-react'
type MinuteRow={timestamp_utc:string;session_ist:string;open:number;high:number;low:number;close:number;volume:number}
type MinuteState={identity:string;state:string;ready:boolean;built:boolean;source_available:boolean;
  observations:number;source_bytes:number;parquet_bytes:number;interval_minutes:number;note:string}
type MinuteSeries={rows:MinuteRow[];identity:string;has_more:boolean;warning:string}
type DepthCapture={id:string;identity:string;depth_levels:number;method:string;provider:string;
  snapshots:number;full_depth_snapshots:number;first_received:string|null;last_received:string|null;warning:string}
type DepthMetric={timestamp:string;mid_price:number;spread_bps:number;imbalance:number;
  bid_depth:number;ask_depth:number;full_depth:boolean}
type DepthResult={identity:string;captured_snapshots:number;metrics:DepthMetric[];
  summary:{average_spread_bps:number;average_imbalance:number;full_depth_fraction:number};
  warning:string}
type Job={id:string;status:string;percent?:number;stage?:string;error?:string;
  result?:Record<string,unknown>}
type SourceData={instruments:MinuteState[];interval_minutes:number}
type DepthList={captures:DepthCapture[];dhan_live_credential_present:boolean;
  historical_depth_download_supported:boolean;note:string}
const api=async<T,>(path:string,init?:RequestInit):Promise<T>=>{
  const response=await fetch(path,init)
  if(!response.ok){
    let msg='Data service unavailable'
    try{const r=await response.json() as {detail?:string};if(r.detail)msg=r.detail}catch{/* unavailable */}
    throw new Error(msg)
  }
  return response.json() as Promise<T>
}
const format=(v:number)=>v.toLocaleString('en-IN',{maximumFractionDigits:3})
function Spark({points,label}:{points:number[];label:string}){
  const [hover,setHover]=useState<number|null>(null)
  const low=Math.min(...points),high=Math.max(...points),span=high-low||1
  const x=(i:number)=>24+i/Math.max(1,points.length-1)*825
  const y=(n:number)=>180-(n-low)/span*145
  const path=points.map((n,i)=>(i?'L':'M')+x(i).toFixed(1)+' '+y(n).toFixed(1)).join(' ')
  return <div className="qm-columnar-plot"><svg viewBox="0 0 880 214" aria-label={label}
    role="img" onMouseMove={e=>{
      const rect=e.currentTarget.getBoundingClientRect()
      const xx=(e.clientX-rect.left)/rect.width*880
      setHover(Math.max(0,Math.min(points.length-1,Math.round((xx-24)/825*(points.length-1)))))
    }} onMouseLeave={()=>setHover(null)}>
    {[35,108,180].map(n=><line key={n} x1="24" x2="850" y1={n} y2={n}
      stroke="currentColor" opacity=".15"/>)}
    <path d={path} fill="none" stroke="#76baf1" strokeWidth="2.5"/>
    {hover!==null&&points[hover]!==undefined&&
      <circle cx={x(hover)} cy={y(points[hover])} r="5" fill="#8ce5b9"/>}
    <text x="24" y="18" fontSize="12" fill="currentColor">{format(high)}</text>
    <text x="24" y="200" fontSize="12" fill="currentColor">{format(low)}</text>
  </svg>
  <div className="qm-chart-tooltip">{hover!==null&&points[hover]!==undefined?
    label+' · '+format(points[hover]):'Hover over the observed values to inspect them'}</div></div>
}
export default function MarketMicrostructurePanel(){
  const [minutes,setMinutes]=useState<MinuteState[]>([])
  const [identity,setIdentity]=useState('')
  const [minState,setMinState]=useState<MinuteState|null>(null)
  const [minuteRows,setMinuteRows]=useState<MinuteRow[]>([])
  const [depths,setDepths]=useState<DepthCapture[]>([])
  const [depthConfigured,setDepthConfigured]=useState(false)
  const [session,setSession]=useState('')
  const [depthResult,setDepthResult]=useState<DepthResult|null>(null)
  const [depthIdentity,setDepthIdentity]=useState('')
  const [depthLevels,setDepthLevels]=useState<20|200>(20)
  const [duration,setDuration]=useState(120)
  const [sourceFile,setSourceFile]=useState<File|null>(null)
  const [provider,setProvider]=useState('authorized_vendor')
  const [sourceRights,setSourceRights]=useState(false)
  const [liveConsent,setLiveConsent]=useState(false)
  const [job,setJob]=useState<Job|null>(null)
  const [activeCapture,setActiveCapture]=useState('')
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')
  const [revision,setRevision]=useState(0)
  const [busy,setBusy]=useState(false)
  const reload=useCallback(async()=>{
    const [a,b]=await Promise.all([
      api<SourceData>('/api/data-manager/intraday/catalog?limit=200'),
      api<DepthList>('/api/data-manager/depth/catalog?limit=50')
    ])
    setMinutes(a.instruments)
    setIdentity(prev=>a.instruments.some(x=>x.identity===prev)?
      prev:a.instruments[0]?.identity||'')
    setDepths(b.captures)
    setDepthConfigured(b.dhan_live_credential_present)
    setSession(prev=>b.captures.some(x=>x.id===prev)?prev:b.captures[0]?.id||'')
  },[])
  useEffect(()=>{let mounted=true;void reload().catch(e=>{if(mounted)setError(String(e))});return()=>{mounted=false}},[reload,revision])
  useEffect(()=>{
    if(!identity){setMinState(null);setMinuteRows([]);return}
    let live=true
    const q=new URLSearchParams({identity})
    void api<MinuteState>('/api/data-manager/intraday/status?'+q).then(async r=>{
      if(!live)return
      setMinState(r)
      if(!r.ready){setMinuteRows([]);return}
      const values=await api<MinuteSeries>('/api/data-manager/intraday/series?'+
        new URLSearchParams({identity,limit:'450'}))
      if(live)setMinuteRows(values.rows)
    }).catch(e=>{if(live)setError(String(e))})
    return()=>{live=false}
  },[identity,revision])
  useEffect(()=>{
    if(!session){setDepthResult(null);return}
    let alive=true
    void api<DepthResult>('/api/data-manager/depth/analyze?'+
      new URLSearchParams({session_id:session,limit:'1200'})).then(x=>{
      if(alive)setDepthResult(x)
    }).catch(e=>{if(alive)setError(String(e))})
    return()=>{alive=false}
  },[session,revision])
  useEffect(()=>{
    if(!job||!['queued','running'].includes(job.status))return
    let live=true
    const timer=window.setTimeout(()=>{
      void api<Job>('/api/jobs/'+encodeURIComponent(job.id)).then(next=>{
        if(!live)return
        setJob(next)
        if(next.status==='complete'){
          setNotice('Original source processing finished; inspect the updated record.')
          setRevision(v=>v+1)
          setActiveCapture('')
        }else if(next.status==='error'||next.status==='cancelled'){
          setError(next.error||'Source operation failed without fabricating observations.')
          setActiveCapture('')
        }
      }).catch(e=>{if(live)setError(String(e))})
    },1400)
    return()=>{live=false;window.clearTimeout(timer)}
  },[job])
  const start=async(path:string,body:RequestInit)=>{
    setError('');setNotice('');setBusy(true);setJob(null)
    try{
      const r=await api<{job_id:string;status:string;session_id?:string}>(path,body)
      setJob({id:r.job_id,status:r.status})
      if(r.session_id)setActiveCapture(r.session_id)
    }catch(e){setError(e instanceof Error?e.message:String(e))}
    finally{setBusy(false)}
  }
  const importDepth=async()=>{
    if(!sourceFile||!sourceRights||!depthIdentity)return
    const form=new FormData()
    form.append('file',sourceFile,sourceFile.name)
    form.append('identity',depthIdentity)
    form.append('depth',String(depthLevels))
    form.append('provider',provider)
    form.append('confirm_authorized','true')
    await start('/api/data-manager/depth/import',{method:'POST',body:form})
  }
  const running=busy||Boolean(job&&['queued','running'].includes(job.status))
  return <div className="qm-microstructure">
    {error&&<div className="qm-alert" role="alert"><AlertTriangle size={16}/>{error}</div>}
    {notice&&<div className="qm-notice" role="status"><CheckCircle2 size={16}/>{notice}</div>}
    <section className="qm-panel" aria-label="One-minute Parquet research">
      <div className="qm-panel-title"><h3><BarChart3 size={18}/> Original 1-minute candle analytics</h3>
        <span>SHA-verified Dhan OHLCV → Parquet, no interpolation</span></div>
      <p className="qm-caption">Explore the minute bars you actually downloaded.
        QuantLab never manufactures the missing minutes, and an updated source invalidates
        the previous Parquet mirror until rebuilt.</p>
      <div className="qm-micro-controls">
        <label>Downloaded one-minute instrument
          <select aria-label="One-minute instrument" value={identity}
            onChange={e=>setIdentity(e.target.value)}>
            <option value="">Select local one-minute candles</option>
            {minutes.map(x=><option value={x.identity} key={x.identity}>{x.identity}</option>)}
          </select></label>
        <button className="ws-button primary" disabled={!identity||running}
          onClick={()=>void start('/api/data-manager/intraday/build',{
            method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({identity})})}>
          <Database size={15}/> {minState?.ready?'Rebuild mirror':'Build minute Parquet'}</button>
        <button className="ws-button secondary" onClick={()=>setRevision(v=>v+1)}>
          <RefreshCw size={15}/> Refresh</button>
      </div>
      {minState&&<div className="qm-acquire-metrics">
        <div><small>Source state</small><strong className="qm-small-stat">{minState.state.replaceAll('_',' ')}</strong></div>
        <div><small>Original minute bars</small><strong>{format(minState.observations)}</strong></div>
        <div><small>Raw source</small><strong>{(minState.source_bytes/1024**2).toFixed(1)} MB</strong></div>
        <div><small>Parquet mirror</small><strong>{(minState.parquet_bytes/1024**2).toFixed(1)} MB</strong></div>
      </div>}
      {minuteRows.length>0&&<>
        <Spark points={minuteRows.map(r=>r.close)}
          label={'Original close (₹) · '+identity}/>
        <div className="qm-scroll qm-columnar-rows"><table><thead><tr>
          <th>UTC timestamp</th><th>NSE session</th><th>Close (₹)</th><th>Volume</th>
        </tr></thead><tbody>{minuteRows.slice(-30).map(x=><tr key={x.timestamp_utc}>
          <td>{x.timestamp_utc}</td><td>{x.session_ist}</td>
          <td>{format(x.close)}</td><td>{format(x.volume)}</td></tr>)}
        </tbody></table></div>
      </>}
      {!minutes.length&&<p className="qm-caption">No downloaded 1-minute source is present.
        Use the existing Dhan manager to request authorized one-minute history.</p>}
    </section>
    <section className="qm-panel" aria-label="Real market depth research">
      <div className="qm-panel-title"><h3><Activity size={18}/> Historical order-book laboratory</h3>
        <span>20 or 200 original levels · spread / imbalance / depth</span></div>
      <div className="qm-alert"><AlertTriangle size={17}/> Dhan publishes a live depth stream,
        not a downloadable archive of historical 20/200-level books. QuantLab records
        from the time you start or imports original licensed snapshots; it cannot reconstruct
        order books from OHLCV candles.</div>
      <div className="qm-micro-controls">
        <label>Exact NSE cash or derivatives Security ID
          <input aria-label="Order book instrument" value={depthIdentity}
            onChange={e=>setDepthIdentity(e.target.value)}
            placeholder="NSE_EQ:1333 or NSE_FNO:12345"/></label>
        <label>Depth levels
          <select aria-label="Order book levels" value={depthLevels}
            onChange={e=>setDepthLevels(Number(e.target.value) as 20|200)}>
            <option value={20}>20 levels</option><option value={200}>200 levels</option>
          </select></label>
        <label>Live recording length
          <select aria-label="Live capture seconds" value={duration}
            onChange={e=>setDuration(Number(e.target.value))}>
            {[30,60,120,300,600,1800].map(n=><option key={n} value={n}>{n}s</option>)}
          </select></label>
      </div>
      <div className="qm-fallback-consent"><label>
        <input type="checkbox" checked={liveConsent}
          onChange={e=>setLiveConsent(e.target.checked)}/>
        I authorize read-only capture of real-time Dhan depth on this machine.</label></div>
      <div className="qm-readiness-action-row">
        <button className="ws-button primary" disabled={!depthConfigured||!liveConsent||
          !/^NSE_(EQ|FNO):[0-9]{1,12}$/.test(depthIdentity)||running}
          onClick={()=>void start('/api/data-manager/depth/start',{
            method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({identity:depthIdentity,depth:depthLevels,
              duration_seconds:duration,confirm_live_data:true})})}>
          <Play size={15}/> Start genuine live depth recording</button>
        {activeCapture&&<button className="ws-button secondary" onClick={()=>void api(
          '/api/data-manager/depth/stop',{method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({session_id:activeCapture})}).then(()=>setNotice('Stop requested; saving actual captured snapshots.'))
            .catch(e=>setError(String(e)))}>
          <Square size={15}/> Stop and save</button>}
      </div>
      {!depthConfigured&&<p className="qm-caption">To enable live capture, set
        DHAN_ACCESS_TOKEN and DHAN_CLIENT_ID in your local ignored .env; live
        depth API entitlement is also required.</p>}
      <h4><FileUp size={16}/> Import authorized historical depth</h4>
      <p className="qm-caption">Actual captured/archived CSV fields:
        timestamp_utc, side (bid/ask), level, price, quantity, orders.
        Each complete snapshot needs paired sides; source time must include UTC offset.</p>
      <div className="qm-fallback-grid">
        <label>Original historical depth CSV
          <input aria-label="Historical order book CSV" type="file" accept=".csv"
            onChange={e=>setSourceFile(e.target.files?.[0]||null)}/></label>
        <label>Licensed original provider
          <input aria-label="Historical depth provider" value={provider}
            onChange={e=>setProvider(e.target.value)}/></label>
      </div>
      <div className="qm-fallback-consent"><label>
        <input type="checkbox" checked={sourceRights}
          onChange={e=>setSourceRights(e.target.checked)}/>
        I have rights to use these original historical depth snapshots for research.</label></div>
      <button className="ws-button secondary"
        disabled={!sourceFile||!sourceRights||!depthIdentity||running}
        onClick={()=>void importDepth()}><ShieldCheck size={15}/> Verify and import depth evidence</button>
      {job&&running&&<div className="qm-acquire-status" role="status"><RefreshCw size={16}/>
        <div><strong>{job.stage||'Processing original microstructure evidence'}</strong>
          <small>{Math.round(job.percent||0)}% · {job.id}</small></div></div>}
      <div className="qm-panel-title qm-depth-results"><h3>Recorded / imported original sessions</h3>
        <select aria-label="Depth analysis session" value={session}
          onChange={e=>setSession(e.target.value)}>
          <option value="">Choose saved genuine snapshots</option>
          {depths.map(d=><option value={d.id} key={d.id}>
            {d.identity} · {d.snapshots} snapshots · {d.method}</option>)}
        </select>
      </div>
      {depthResult&&<>
        <div className="qm-acquire-metrics">
          <div><small>Original snapshots</small><strong>{depthResult.captured_snapshots}</strong></div>
          <div><small>Avg spread (bps)</small><strong>{format(depthResult.summary.average_spread_bps)}</strong></div>
          <div><small>Avg depth imbalance</small><strong>{format(depthResult.summary.average_imbalance)}</strong></div>
          <div><small>Full depth share</small><strong>{(100*depthResult.summary.full_depth_fraction).toFixed(1)}%</strong></div>
        </div>
        {depthResult.metrics.length>0&&<Spark
          points={depthResult.metrics.map(r=>r.spread_bps)} label="Observed spread (bps)"/>}
        <p className="qm-caption">{depthResult.warning}</p>
      </>}
      {!depths.length&&<p className="qm-caption">No market-depth history exists on this machine.
        Start a real-time recording or import licensed original captures; QuantLab will not seed examples as actual history.</p>}
    </section>
  </div>
}
