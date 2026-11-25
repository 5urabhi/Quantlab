import ResearchPlot from './ResearchPlots'
import {useCallback, useEffect, useState} from 'react'
import {AlertTriangle, BarChart3, CheckCircle2, Database, RefreshCw, ShieldCheck} from 'lucide-react'

type CacheState={
  state:string;ready:boolean;built:boolean;engine_available:boolean;source_available:boolean;
  source_database_bytes:number;observations:number;years:number[];parquet_bytes:number;
  generated_utc?:string|null;note:string
}
type Instrument={identity:string;label:string}
type Series={identity:string;rows:{date:string;close:number;source_sha256:string}[];
  has_more:boolean;limit:number;basis:string;note:string}
type Job={id:string;status:string;stage?:string;percent?:number;error?:string;result?:CacheState}
const get=async<T,>(path:string,init?:RequestInit):Promise<T>=>{
  const response=await fetch('/api/data-manager'+path,init)
  if(!response.ok){
    let msg='Unable to inspect analytical cache'
    try{const r=await response.json() as {detail?:string};if(r.detail)msg=r.detail}catch{/* ignore */}
    throw new Error(msg)
  }
  return response.json() as Promise<T>
}
const bytes=(n:number)=>n>=1024*1024*1024?(n/1024**3).toFixed(2)+' GB':
  n>=1024*1024?(n/1024**2).toFixed(1)+' MB':(n/1024).toFixed(1)+' KB'
const money=(n:number)=>'₹'+n.toLocaleString('en-IN',{maximumFractionDigits:2})
export default function ColumnarAnalyticsPanel(){
  const [state,setState]=useState<CacheState|null>(null)
  const [job,setJob]=useState<Job|null>(null)
  const [error,setError]=useState('')
  const [statusMessage,setStatusMessage]=useState('')
  const [busy,setBusy]=useState(false)
  const [instruments,setInstruments]=useState<Instrument[]>([])
  const [identity,setIdentity]=useState('')
  const [limit,setLimit]=useState(250)
  const [first,setFirst]=useState('')
  const [last,setLast]=useState('')
  const [data,setData]=useState<Series|null>(null)
  const [revision,setRevision]=useState(0)
  const reload=useCallback(async()=>{
    try{const r=await get<CacheState>('/columnar/status');setState(r);setError('')}
    catch(e){setError(e instanceof Error?e.message:String(e))}
  },[])
  useEffect(()=>{void reload()},[reload,revision])
  useEffect(()=>{
    if(!state?.ready)return
    let alive=true
    void get<{instruments:Instrument[]}>('/columnar/instruments?limit=150').then(r=>{
      if(!alive)return
      setInstruments(r.instruments)
      setIdentity(id=>r.instruments.some(x=>x.identity===id)?id:r.instruments[0]?.identity||'')
    }).catch(e=>{if(alive)setError(String(e))})
    return()=>{alive=false}
  },[state?.ready,revision])
  useEffect(()=>{
    if(!state?.ready||!identity){setData(null);return}
    let alive=true
    const query=new URLSearchParams({identity,limit:String(limit)})
    if(first)query.set('start',first)
    if(last)query.set('end',last)
    setData(null)
    void get<Series>('/columnar/series?'+query.toString()).then(r=>{
      if(alive){setData(r);setError('')}
    }).catch(e=>{if(alive)setError(e instanceof Error?e.message:String(e))})
    return()=>{alive=false}
  },[state?.ready,identity,limit,first,last,revision])
  useEffect(()=>{
    if(!job||!['queued','running'].includes(job.status))return
    let live=true
    const timer=window.setTimeout(()=>{
      void fetch('/api/jobs/'+encodeURIComponent(job.id)).then(async r=>{
        if(!r.ok)throw new Error('Unable to read columnar build job')
        return r.json() as Promise<Job>
      }).then(r=>{
        if(!live)return
        setJob(r)
        if(r.status==='complete'){setStatusMessage('Columnar source mirror rebuilt and verified.');setRevision(x=>x+1)}
        if(r.status==='error'||r.status==='cancelled')setError(r.error||'Columnar cache build failed.')
      }).catch(e=>{if(live)setError(String(e))})
    },1450)
    return()=>{live=false;window.clearTimeout(timer)}
  },[job])
  const build=async()=>{
    if(busy)return
    setBusy(true);setJob(null);setStatusMessage('');setError('')
    try{
      const r=await get<{job_id:string;status:string}>('/columnar/build',{method:'POST'})
      setJob({id:r.job_id,status:r.status})
    }catch(e){setError(e instanceof Error?e.message:String(e))}
    finally{setBusy(false)}
  }

  const waiting=busy||(job!==null&&['queued','running'].includes(job.status))
  return <section className="qm-panel qm-columnar" aria-label="Columnar analytical cache">
    <div className="qm-panel-title"><h3><BarChart3 size={18}/> Fast historical-data analytics</h3>
      <span>Local DuckDB · year-partitioned Parquet · original SQLite unchanged</span></div>
    <p className="qm-caption">A compact analytical copy of verified daily closes.
      When source data changes, QuantLab refuses stale Parquet results.
      Once enabled, smaller caches update automatically after supported data imports.</p>
    {error&&<div className="qm-alert" role="alert"><AlertTriangle size={16}/>{error}</div>}
    {statusMessage&&<div className="qm-notice" role="status"><CheckCircle2 size={16}/>{statusMessage}</div>}
    <div className="qm-acquire-metrics">
      <div><small>Analytics cache status</small><strong className="qm-small-stat">{state?.state.replaceAll('_',' ')||'Loading...'}</strong></div>
      <div><small>Source observations</small><strong>{(state?.observations??0).toLocaleString('en-IN')}</strong></div>
      <div><small>SQLite source size</small><strong>{bytes(state?.source_database_bytes??0)}</strong></div>
      <div><small>Parquet size</small><strong>{bytes(state?.parquet_bytes??0)}</strong></div>
    </div>
    <div className="qm-columnar-actions">
      <button type="button" className="ws-button primary"
        disabled={!state?.source_available||!state?.engine_available||waiting}
        onClick={()=>void build()}>
        {waiting?<RefreshCw size={15}/>:<Database size={15}/>}
        {waiting?'Rebuilding analytics cache…':state?.ready?'Rebuild / verify cache':'Build / refresh Parquet cache'}
      </button>
      <button type="button" className="ws-button secondary" onClick={()=>void reload()}>
        <RefreshCw size={15}/> Check status</button>
      {state&&!state.engine_available&&<p className="qm-caption">DuckDB is not installed. Restart using the updated requirements.txt installation.</p>}
      {state&&!state.source_available&&<p className="qm-caption">Acquire original Dhan market data first; no synthetic source will be materialized.</p>}
      {job&&['queued','running'].includes(job.status)&&<p className="qm-caption" role="status">
        {job.stage||'Writing verified Parquet partitions'} · {Math.round(job.percent??0)}%</p>}
    </div>
    {state?.ready&&<div className="qm-columnar-view">
      <div className="qm-panel-title"><h3>Explore accelerated original closes</h3>
        <span><ShieldCheck size={14}/> Source-checked before every query</span></div>
      <div className="qm-fallback-grid">
        <label>Stock / instrument
          <select aria-label="Parquet instrument" value={identity} onChange={e=>setIdentity(e.target.value)}>
            {instruments.map(x=><option key={x.identity} value={x.identity}>{x.label} · {x.identity}</option>)}
          </select></label>
        <label>From date
          <input type="date" aria-label="Parquet from date" value={first} onChange={e=>setFirst(e.target.value)}/></label>
        <label>Through date
          <input type="date" aria-label="Parquet through date" value={last} onChange={e=>setLast(e.target.value)}/></label>
        <label>Max observations
          <select aria-label="Parquet row limit" value={limit} onChange={e=>setLimit(Number(e.target.value))}>
            {[100,250,500,1000,2500].map(n=><option key={n} value={n}>{n}</option>)}
          </select></label>
      </div>
      {data&&data.rows.length>0&&<div className="qm-columnar-plot"><ResearchPlot plot={{kind:'line2d',title:'Interactive chart of original market closes · '+identity,x_label:'Trading date',y_label:identity.startsWith('INDEX:')?'Index level (points)':'Unadjusted close (₹)',x:data.rows.map(r=>r.date),traces:[{name:'Original close',y:data.rows.map(r=>r.close)}]}} provenance="historical" formatY={v=>v.toLocaleString('en-IN',{maximumFractionDigits:2})}/><p className="qm-caption">{data.rows.length} observations · {data.has_more?'More rows available':'Displayed source query complete'}</p></div>}
      {data&&<div className="qm-scroll qm-columnar-rows"><table>
        <thead><tr><th>Trading date</th><th>Unadjusted close (INR)</th><th>Source checksum</th></tr></thead>
        <tbody>{data.rows.slice(-30).map(row=><tr key={row.date}>
          <td>{row.date}</td><td>{money(row.close)}</td>
          <td title={row.source_sha256}>{row.source_sha256.slice(0,14)}…</td>
        </tr>)}</tbody></table></div>}
      <p className="qm-caption">{data?.note}</p>
    </div>}
  </section>
}
