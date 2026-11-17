import {useCallback, useEffect, useState} from 'react'
import {AlertTriangle, CheckCircle2, FileUp, RefreshCw, ShieldCheck} from 'lucide-react'

type Provider = {id:string;label:string;mode:string;compatible:boolean}
type Registry = {providers:Provider[];source_claims_independently_audited:boolean}
type Instrument = {identity:string;label:string}
type Receipt = {
  id:string;status:string;identity:string;provider_label:string;
  source_rows:number;matched_sessions:number;conflicting_sessions:number;
  new_sessions:number;rows_added?:number;reused_rows?:number;blockers:string[];
  warning:string;first_date:string;last_date:string
}
type Job = {id:string;status:string;stage?:string;percent?:number;error?:string;result?:Receipt}
const api=async<T,>(path:string, init?:RequestInit):Promise<T>=>{
  const r=await fetch('/api/data-manager'+path,init)
  if(!r.ok){
    let msg='Source service unavailable'
    try{const b=await r.json() as {detail?:string};if(b.detail)msg=b.detail}catch{/* ignore */}
    throw new Error(msg)
  }
  return r.json() as Promise<T>
}

export default function SourceFallbackPanel({onChanged}:{onChanged:()=>void}){
  const [registry,setRegistry]=useState<Registry|null>(null)
  const [instruments,setInstruments]=useState<Instrument[]>([])
  const [receipts,setReceipts]=useState<Receipt[]>([])
  const [search,setSearch]=useState('')
  const [identity,setIdentity]=useState('')
  const [provider,setProvider]=useState('dhan_export')
  const [original,setOriginal]=useState<File|null>(null)
  const [rights,setRights]=useState(false)
  const [unadjusted,setUnadjusted]=useState(false)
  const [job,setJob]=useState<Job|null>(null)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [result,setResult]=useState<Receipt|null>(null)
  const [refreshNo,setRefreshNo]=useState(0)

  const refresh=useCallback(async()=>{
    const [r,history]=await Promise.all([
      api<Registry>('/fallback/registry'),
      api<{sources:Receipt[]}>('/fallback/receipts')
    ])
    setRegistry(r);setReceipts(history.sources)
  },[])
  useEffect(()=>{let live=true;void refresh().catch(e=>{if(live)setError(String(e))});return()=>{live=false}},[refresh,refreshNo])
  useEffect(()=>{
    let live=true
    const timeout=window.setTimeout(()=>{
      void api<{instruments:Instrument[]}>('/columnar/instruments?'+new URLSearchParams({
        query:search,limit:'80'}).toString()).then(r=>{
        if(live){setInstruments(r.instruments);setError('')}
      }).catch(()=>{if(live)setInstruments([])})
    },230)
    return()=>{live=false;window.clearTimeout(timeout)}
  },[search,refreshNo])
  useEffect(()=>{
    if(!job||!['queued','running'].includes(job.status))return
    let live=true
    const timer=window.setTimeout(()=>{
      void fetch('/api/jobs/'+encodeURIComponent(job.id)).then(async r=>{
        if(!r.ok)throw new Error('Unable to read original import job status')
        return r.json() as Promise<Job>
      }).then(next=>{
        if(!live)return
        setJob(next)
        if(next.status==='complete'){
          setResult(next.result||null)
          setRefreshNo(n=>n+1)
          if(next.result?.status==='imported')onChanged()
        }else if(next.status==='error'||next.status==='cancelled'){
          setError(next.error||'The fallback source could not be verified.')
        }
      }).catch(e=>{if(live)setError(String(e))})
    },1300)
    return()=>{live=false;window.clearTimeout(timer)}
  },[job,onChanged])
  const submit=async()=>{
    if(!original||!identity||!rights||!unadjusted||busy)return
    setBusy(true);setError('');setResult(null);setJob(null)
    try{
      const body=new FormData()
      body.append('file',original,original.name)
      body.append('identity',identity)
      body.append('provider',provider)
      body.append('confirm_authorized','true')
      body.append('confirm_unadjusted','true')
      const started=await api<{job_id:string;status:string}>('/fallback/import',{
        method:'POST',body})
      setJob({id:started.job_id,status:started.status})
    }catch(e){setError(e instanceof Error?e.message:String(e))}
    finally{setBusy(false)}
  }
  const running=busy||(job!==null&&['queued','running'].includes(job.status))
  return <div className="qm-source-fallback-stack"><ZerodhaProviderPanel onSourceChange={()=>setRefreshNo(n=>n+1)}/><section className="qm-panel qm-fallback" aria-label="Compatible alternate historical source">
    <div className="qm-panel-title"><h3><FileUp size={18}/> Compatible source fallback</h3>
      <span>Only original observations · no alias-based matching</span></div>
    <p className="qm-caption">If Dhan cannot provide a missing historical window, you can add an
      <strong> authorized original daily-close CSV</strong>. QuantLab automatically checks
      the same exchange and Security ID, unadjusted price basis, at least three
      matching Dhan sessions, and conflicting values before it appends anything.
      Unsupported files are kept as blocked evidence, never added to research data.</p>
    {error&&<div role="alert" className="qm-alert"><AlertTriangle size={16}/>{error}</div>}
    <div className="qm-fallback-grid">
      <label>Authorized original source
        <select aria-label="Fallback provider" value={provider} onChange={e=>setProvider(e.target.value)}>
          {registry?.providers.filter(p=>p.id==='dhan_export'||p.id==='licensed_vendor_csv').map(p=>
            <option key={p.id} value={p.id}>{p.label}</option>)}
        </select></label>
      <label>Find an existing instrument
        <input aria-label="Find instrument for fallback" value={search}
          placeholder="Search RELIANCE or NSE_EQ:..." onChange={e=>{setSearch(e.target.value);setIdentity('')}}/>
        <select aria-label="Canonical identity" value={identity} onChange={e=>setIdentity(e.target.value)}>
          <option value="">Choose exact exchange + security ID</option>
          {instruments.map(x=><option value={x.identity} key={x.identity}>
            {x.label} · {x.identity}
          </option>)}
        </select></label>
      <label>Original UTF-8 daily-close CSV
        <input aria-label="Original fallback CSV" type="file" accept=".csv,text/csv"
          onChange={e=>setOriginal(e.target.files?.[0]||null)}/>
        <small>Required columns: date (YYYY-MM-DD), close. Maximum 20 MB.</small></label>
    </div>
    <div className="qm-fallback-consent">
      <label><input type="checkbox" checked={rights} onChange={e=>setRights(e.target.checked)}/>
        I have the right to use this source for my local research.</label>
      <label><input type="checkbox" checked={unadjusted} onChange={e=>setUnadjusted(e.target.checked)}/>
        These are original daily unadjusted closes for this exact security, not TRI or adjusted prices.</label>
    </div>
    <button type="button" className="ws-button primary"
      disabled={!original||!identity||!rights||!unadjusted||running}
      onClick={()=>void submit()}>
      {running?<RefreshCw size={15}/>:<ShieldCheck size={15}/>}
      {running?'Checking overlap and preserving evidence…':'Validate & append compatible source'}
    </button>
    {job&&['queued','running'].includes(job.status)&&<p className="qm-caption" role="status">
      Job {job.id} · {job.stage||'Comparing source with original Dhan data'}
    </p>}
    {result&&<div className={result.status==='imported'?'qm-notice':'qm-alert'} role="status">
      {result.status==='imported'?<CheckCircle2 size={17}/>:<AlertTriangle size={17}/>}
      <div><strong>{result.status==='imported'?'Compatible original closes appended':'Source blocked — no rows promoted'}</strong>
        <p>{result.identity} · {result.matched_sessions} agreeing sessions ·
          {result.new_sessions} candidate new sessions · {result.rows_added??0} appended.</p>
        {result.blockers.map((reason,i)=><p key={i}>{reason}</p>)}
        <small>{result.warning}</small></div>
    </div>}
    <details className="qm-details"><summary>Source registry and compatibility rules</summary>
      {registry?.providers.map(p=><div key={p.id} className="qm-file">
        <span>{p.label}</span><small>{p.compatible?'Compatible with checks':'Not interchangeable'} · {p.mode.replaceAll('_',' ')}</small>
      </div>)}
    </details>
    <details className="qm-details"><summary>Past original source imports ({receipts.length})</summary>
      {receipts.length===0?<p className="qm-caption">No alternate source receipts yet.</p>:
        receipts.slice(0,25).map(r=><div key={r.id} className="qm-file">
          <span>{r.identity} · {r.provider_label}</span>
          <small>{r.status} · {r.matched_sessions} matched · {r.rows_added??0} added</small>
        </div>)}
    </details>
  </section></div>
}
