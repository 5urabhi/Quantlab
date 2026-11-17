import {useCallback,useEffect,useMemo,useState} from 'react'
import {AlertTriangle,ArrowRight,CheckCircle2,Database,Download,FileUp,Layers,
  LoaderCircle,RefreshCw,ShieldCheck} from 'lucide-react'
import './market-library.css'

type Group={id:string;label:string;source_state:string}
type Stock={identity:string;symbol:string;name:string;exchange:string;security_id:string;
  observations:number;first_date:string|null;last_date:string|null;
  sector:string|null;sector_effective_date:string|null;sector_source:string}
type Library={library_id:string;available:boolean;as_of:string;as_of_defaulted?:boolean;
  view:string;sector:string;total:number;items:Stock[];groups:Group[];sectors:string[];
  has_more:boolean;page?:number;source_state:{state:string;reason:string};
  sector_source_status?:string;message:string}
type Job={id:string;status:string;stage?:string;percent?:number;error?:string;
  result?:{status:string;original_snapshots_preserved?:boolean;
    sources_scanned?:number;sources_ingested?:number;sources_blocked?:unknown[]}}
const urls=(params:Record<string,string>)=>
  '/api/data-manager/market-library?'+new URLSearchParams(params).toString()
const message=(err:unknown)=>err instanceof Error?err.message:String(err)
async function get<T>(url:string):Promise<T>{
  const response=await fetch(url)
  if(!response.ok){
    let detail='Request failed ('+response.status+')'
    try{const parsed=await response.json() as {detail?:string};detail=parsed.detail||detail}
    catch{/* no JSON */}
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export default function MarketLibraryPanel({onOpenDownloads,onChooseModel,onInspectOriginal,onChanged}:{
  onOpenDownloads?:()=>void;onChooseModel?:()=>void;
  onInspectOriginal?:(datasetId:string)=>void;onChanged?:()=>void
}){
  const [view,setView]=useState('all')
  const [sector,setSector]=useState('')
  const [asOf,setAsOf]=useState('')
  const [search,setSearch]=useState('')
  const [debounced,setDebounced]=useState('')
  const [page,setPage]=useState(1)
  const [version,setVersion]=useState(0)
  const [library,setLibrary]=useState<Library|null>(null)
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')
  const [busy,setBusy]=useState(false)
  const [job,setJob]=useState<Job|null>(null)
  const [sectorFile,setSectorFile]=useState<File|null>(null)
  const [sectorRights,setSectorRights]=useState(false)
  const [advanced,setAdvanced]=useState(false)
  useEffect(()=>{
    const t=window.setTimeout(()=>setDebounced(search.trim()),260)
    return()=>window.clearTimeout(t)
  },[search])
  useEffect(()=>{setPage(1)},[view,sector,asOf,debounced])
  const refresh=useCallback(()=>setVersion(n=>n+1),[])
  useEffect(()=>{
    let active=true
    void get<Library>(urls({view,sector,as_of:asOf,query:debounced,
      page:String(page),per_page:'35'}))
      .then(r=>{if(active){setLibrary(r);setError('')}})
      .catch(e=>{if(active)setError(message(e))})
    return()=>{active=false}
  },[view,sector,asOf,debounced,page,version])
  useEffect(()=>{
    if(!job||!['running','queued'].includes(job.status))return
    let active=true
    const timer=window.setTimeout(()=>{
      void get<Job>('/api/jobs/'+encodeURIComponent(job.id))
        .then(next=>{
          if(!active)return
          setJob(next)
          if(next.status==='complete'){
            setNotice('Saved original Dhan sources indexed into your one Market Data Library. '
              +'Original source snapshots were preserved.')
            onChanged?.();refresh()
          }else if(next.status==='error'||next.status==='cancelled'){
            setError(next.error||'The source consolidation needs review.')
          }
        }).catch(e=>{if(active)setError(message(e))})
    },1400)
    return()=>{active=false;window.clearTimeout(timer)}
  },[job,refresh,onChanged])
  const groups=useMemo(()=>library?.groups||[
    {id:'all',label:'All downloaded stocks',source_state:'canonical'},
    {id:'nifty50',label:'NIFTY 50',source_state:'dated_reconstruction'},
    {id:'nifty100',label:'NIFTY 100',source_state:'missing_source'},
    {id:'banknifty',label:'BANK NIFTY',source_state:'dated_reconstruction'},
    {id:'nse',label:'NSE stocks',source_state:'canonical'},
    {id:'bse',label:'BSE stocks',source_state:'canonical'},
    {id:'sector',label:'By sector',source_state:'original_dated_classifications'},
  ],[library?.groups])
  const consolidate=async()=>{
    if(busy||!window.confirm('Index existing, original Dhan prepared stocks into the one '
      +'shared market database? Original snapshots and saved research will be preserved.'))return
    setBusy(true);setNotice('');setError('')
    try{
      const response=await fetch('/api/data-manager/market-library/consolidate',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({confirm_preserve_originals:true})})
      if(!response.ok){
        const parsed=await response.json() as {detail?:string}
        throw new Error(parsed.detail||'Could not index existing history.')
      }
      const data=await response.json() as {job_id:string;status:string}
      setJob({id:data.job_id,status:data.status})
      setNotice('Reading existing source snapshots locally. No broker download is required.')
    }catch(e){setError(message(e))}
    finally{setBusy(false)}
  }
  const importSectors=async()=>{
    if(!sectorFile||!sectorRights||busy)return
    setBusy(true);setError('');setNotice('')
    try{
      const data=new FormData()
      data.append('file',sectorFile)
      data.append('confirm_original','true')
      const response=await fetch('/api/data-manager/market-library/sectors/import',{
        method:'POST',body:data})
      if(!response.ok){
        const parsed=await response.json() as {detail?:string}
        throw new Error(parsed.detail||'Sector source import was rejected.')
      }
      const result=await response.json() as {new_classifications:number}
      setNotice('Imported '+result.new_classifications+' dated classifications. '
        +'Sector labels remain user-sourced until independently verified.')
      setSectorFile(null);setSectorRights(false)
      onChanged?.();refresh()
    }catch(e){setError(message(e))}
    finally{setBusy(false)}
  }
  return <section className="ml-root" aria-label="One Market Data Library">
    <div className="ml-header">
      <div><div className="ml-kicker"><Database size={16}/> ONE MARKET DATA LIBRARY</div>
        <h3>All your stocks. One source-backed library.</h3>
        <p>Each exchange/security has one canonical daily-close history. NIFTY indices and
          sectors are dated views—not separate duplicate downloads.</p>
      </div>
      <div className="ml-actions">
        <button type="button" className="ws-button secondary" onClick={refresh}>
          <RefreshCw size={15}/> Refresh</button>
        {onOpenDownloads&&<button type="button" className="ws-button secondary"
          onClick={onOpenDownloads}><Download size={15}/> Get more history</button>}
        {onChooseModel&&<button type="button" className="ws-button primary"
          onClick={onChooseModel}><Layers size={15}/> Choose model <ArrowRight size={14}/></button>}
      </div>
    </div>
    {error&&<div role="alert" className="ml-alert"><AlertTriangle size={15}/>{error}</div>}
    {notice&&<div role="status" className="ml-notice"><CheckCircle2 size={15}/>{notice}</div>}
    <nav className="ml-groups" aria-label="Stock universe views">
      {groups.map(g=><button type="button" key={g.id}
        className={view===g.id?'active':''}
        aria-pressed={view===g.id}
        onClick={()=>{setView(g.id);setSector('');setAsOf('')}}>{g.label}
        {g.source_state==='missing_source'&&<span>needs source</span>}
      </button>)}
    </nav>
    <div className="ml-filters">
      <label>Search company, ticker, or Security ID
        <input type="search" aria-label="Search market library stocks" value={search}
          onChange={e=>setSearch(e.target.value)} placeholder="e.g. RELIANCE, TCS, HDFCBANK" /></label>
      <label>Membership / sector as of
        <input type="date" aria-label="Market library as-of date" value={asOf}
          onChange={e=>setAsOf(e.target.value)}/></label>
      {view==='sector'&&<label>Original sector classification
        <select aria-label="Sector view" value={sector} onChange={e=>setSector(e.target.value)}>
          <option value="">Choose sector</option>
          {(library?.sectors||[]).map(s=><option key={s} value={s}>{s}</option>)}
        </select></label>}
    </div>
    {library&&<div className="ml-summary">
      <div><small>One canonical store</small><strong>{library.library_id}</strong></div>
      <div><small>Matching stocks with history</small><strong>{library.total.toLocaleString()}</strong></div>
      <div><small>Effective membership date</small><strong>{library.as_of}</strong></div>
      <p>{library.message}</p>
      {library.as_of_defaulted&&<p className="ml-note">
        Index membership is shown at the source's last covered date, not silently
        assumed to extend to today's membership.</p>}
    </div>}
    {library?.source_state.state!=='canonical'&&
      <p className="ml-context"><ShieldCheck size={15}/>
        <strong>{library?.source_state.state.replaceAll('_',' ')||'Source status'}:</strong>
        {' '}{library?.source_state.reason||'Original dated source data required.'}</p>}
    <div className="ml-table-wrap">
      <table className="ml-table">
        <thead><tr><th>Stock</th><th>Exchange / ID</th><th>Sector</th>
          <th>Observed daily closes</th><th>Observed range</th></tr></thead>
        <tbody>{(library?.items||[]).map(stock=><tr key={stock.identity}>
          <td><strong>{stock.symbol}</strong><small>{stock.name}</small></td>
          <td>{stock.exchange} · {stock.security_id}</td>
          <td>{stock.sector||'Unclassified'}{stock.sector&&<small>
            Effective {stock.sector_effective_date} · user source</small>}</td>
          <td>{stock.observations.toLocaleString()}</td>
          <td>{stock.first_date||'—'} → {stock.last_date||'—'}</td>
        </tr>)}</tbody>
      </table>
      {!library&&!error&&<p className="ml-empty"><LoaderCircle size={16}/> Reading canonical library…</p>}
      {library&&library.items.length===0&&<div className="ml-empty">
        <AlertTriangle size={20}/>
        <p>{library.source_state.reason||'No locally observed stocks match this view yet.'}</p>
        {onOpenDownloads&&<button type="button" className="ws-button primary"
          onClick={onOpenDownloads}>Get source-backed market data <ArrowRight size={14}/></button>}
      </div>}
    </div>
    {library&&library.total>35&&<div className="ml-pager">
      <span>Page {page} · {library.total.toLocaleString()} stocks</span>
      <button disabled={page===1} onClick={()=>setPage(v=>Math.max(1,v-1))}>Previous</button>
      <button disabled={!library.has_more} onClick={()=>setPage(v=>v+1)}>Next</button>
    </div>}
    <details className="ml-advanced" open={advanced} onToggle={e=>setAdvanced(e.currentTarget.open)}>
      <summary><ShieldCheck size={16}/> Source maintenance & dated classifications</summary>
      <p>The original Dhan batches and uploaded evidence are preserved for auditing.
        This library adds indexed views; it never merges incompatible source identities.</p>
      <button type="button" className="ws-button secondary"
        disabled={busy||Boolean(job&&['queued','running'].includes(job.status))}
        onClick={()=>void consolidate()}>
        {busy?<LoaderCircle size={15}/>:<RefreshCw size={15}/>}
        Index my existing prepared Dhan batches
      </button>
      {job&&<p role="status" className="ml-context">
        {job.status} · {job.stage||'Locally inspecting source data'}
        {job.percent!==undefined?' · '+job.percent+'%':''}</p>}
      <div className="ml-import">
        <h4>Import original effective-dated sector classifications</h4>
        <p>CSV columns: <code>exchange_segment,security_id,effective_date,sector</code>.
          Use NSE_EQ/BSE_EQ and the exact Security ID already in the library.
          Unknown historical classifications remain unclassified.</p>
        <input type="file" accept=".csv,text/csv" aria-label="Original dated sector CSV"
          onChange={e=>setSectorFile(e.target.files?.[0]||null)}/>
        <label><input type="checkbox" checked={sectorRights}
          onChange={e=>setSectorRights(e.target.checked)}/>
          I have the rights to import original effective-dated sector information.</label>
        <button type="button" className="ws-button secondary"
          disabled={!sectorRights||!sectorFile||busy}
          onClick={()=>void importSectors()}>
          <FileUp size={15}/> Import sector source
        </button>
      </div>
      {onInspectOriginal&&<button type="button" className="ws-button secondary"
        onClick={()=>onInspectOriginal('dhan_shared')}>
        Inspect canonical records and source receipts <ArrowRight size={14}/></button>}
    </details>
  </section>
}
