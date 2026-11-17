import {lazy, Suspense, useCallback, useEffect, useMemo, useState} from 'react'
import {
  Activity, AlertCircle, ArrowRight, BookOpen, CalendarDays, Check, CheckCircle2,
  ChevronDown, CircleHelp, Clock3, Database, Download, FileCheck2, HardDrive,
  Layers, LoaderCircle, Pause, Play, RefreshCw, RotateCcw, Search, Settings2,
  ShieldCheck, Trash2, X
} from 'lucide-react'
import './market-data-workspace.css'

const DhanDataManager = lazy(() => import('./DhanDataManager'))
const DataManager = lazy(() => import('./DataManager'))
const SourceFallbackPanel = lazy(() => import('./SourceFallbackPanel'))
const DataAcquisitionPanel = lazy(() => import('./DataAcquisitionPanel'))

type Page = 'get'|'datasets'|'downloads'
type Selection = 'nifty50_pit'|'banknifty_pit'|'watchlist'|'all_nse'|'all_bse'
type Advanced = 'providers'|'manual'|'database'|null
type Datum = {id:string;label:string;kind:string;ready:boolean;has_prices?:boolean;
  has_daily_prices?:boolean;daily_session_count?:number;monthly_price_observations?:number;
  missing?:string[];basis?:string}
type Model = {id:string;title:string;mode:string;min_observations:number}
type Action = {kind:string;label:string}
type Plan = {selection:Selection;from_date:string;to_date:string;interval:number|null;
  preview_token:string;can_start:boolean;instrument_count:number;unresolved_count:number;
  unresolved:{symbol:string;reason:string}[];warnings:string[];blockers:string[];
  next_actions:Action[];estimated_request_upper_bound:number;estimate_note:string;
  membership:{state:string;covered_through?:string|null;earliest?:string|null;
    union_count?:number;changes?:number};
  model_requirements?:{model_id:string;title:string;mode:string;minimum?:number;
    preferred?:number;suggested_from?:string;note:string}|null;
  capacity:{rows_upper_estimate:number;bytes_upper_estimate:number;large:boolean;
    over_limit:boolean;note:string};
  model_followup:{eligible:boolean;params:Record<string,number>;note:string};
  dhan:{token_present:boolean;catalog_available:boolean;credential_verified:boolean;note:string};
  provider_policy:string}
type Batch = {id:string;selection:string;status:string;from_date:string;to_date:string;
  created_utc:string;interval:number|null;total:number;processed:number;
  counts:Record<string,number>;errors:number;current_symbol?:string|null;
  current_window?:string|null;prepared_dataset_id?:string|null;
  failure_examples?:{symbol:string;code:string;diagnostic:string;explanation:string}[];
  historical_unresolved?:{symbol:string;reason:string}[];
  rejected_provider_bars?:number;recovered_checkpoints?:number;
  preparation_error?:string}
type Job = {id:string;status:string;stage?:string;percent?:number;error?:string;
  result?:Record<string,unknown>}
type SecondaryPlan = {batch_id:string;status:string;preview_token:string;
  can_recover:boolean;candidate_count:number;eligible_count:number;
  blockers:string[];note:string;items:{instrument_id:string;symbol:string;
    original_status:string;eligible:boolean;reason:string}[]}
type Connection = {token_configured:boolean;instrument_master_available:boolean}
type DhanCheck = {ok:boolean;code:string;message:string;token_valid:boolean|null;
  data_plan_active:boolean|null}
type KiteStatus = {api_key_configured:boolean;api_secret_configured:boolean;
  token_present:boolean;master_current:boolean;note?:string}
type Props = {initialPage?:Page;datasets:Datum[];onDataChanged:()=>void;
  onSelectDataset:(id:string)=>void;onOpenModels:()=>void;
  onRequestDelete:(datasetId:string)=>void}

const modeNames:Record<Selection,string>={
  nifty50_pit:'NIFTY 50',banknifty_pit:'BANK NIFTY',watchlist:'My stocks',
  all_nse:'All NSE stocks',all_bse:'All BSE stocks'
}
const stepLabels = ['Choose data','Check requirements','Download & prepare'] as const
const today = ()=>{
  const d = new Date()
  d.setMinutes(d.getMinutes()-d.getTimezoneOffset())
  return d.toISOString().slice(0,10)
}
const yearsAgo = (years:number)=>{
  const d=new Date()
  d.setFullYear(d.getFullYear()-years)
  d.setMinutes(d.getMinutes()-d.getTimezoneOffset())
  return d.toISOString().slice(0,10)
}
const nextDay=(value:string)=>{
  const d=new Date(value+'T12:00:00Z')
  if(!Number.isFinite(d.getTime()))return ''
  d.setUTCDate(d.getUTCDate()+1)
  return d.toISOString().slice(0,10)
}
const previousDay=(value:string)=>{
  const d=new Date(value+'T12:00:00Z')
  if(!Number.isFinite(d.getTime()))return ''
  d.setUTCDate(d.getUTCDate()-1)
  return d.toISOString().slice(0,10)
}
const fmt=(n:number)=>Number(n||0).toLocaleString('en-US')
const statusLabel=(s:string)=>s.replaceAll('_',' ')
const symbolList=(raw:string)=>Array.from(new Set(
  raw.toUpperCase().split(/[,;\s]+/).map(s=>s.trim()).filter(Boolean)
))
async function api<T>(path:string,options?:RequestInit):Promise<T>{
  let response:Response
  try{response=await fetch('/api'+path,options)}
  catch{throw new Error('Cannot reach the local Python data engine. Start QuantLab using bash run.sh.')}
  if(!response.ok){
    let reason='Request failed ('+response.status+')'
    try{
      const body=await response.json() as {detail?:unknown}
      if(typeof body.detail==='string')reason=body.detail
    }catch{/* Server returned no details. */}
    throw new Error(reason)
  }
  return response.json() as Promise<T>
}
function post<T>(path:string,body:object){
  return api<T>(path,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(body)})
}
const errorText=(err:unknown)=>err instanceof Error?err.message:String(err)
function stateMessage(batch:Batch){
  if(batch.prepared_dataset_id)return 'Prepared dataset is available for compatible research models.'
  if(['queued','running'].includes(batch.status))return 'Original candles are downloading; verified progress is saved.'
  if(batch.status==='interrupted')return 'This download stopped unexpectedly. Saved candles are preserved. Resume when ready.'
  if(batch.status==='paused')return 'This download is paused. Check errors or resume remaining instruments.'
  if(batch.status==='cancelled')return 'This download was stopped. Previously verified candles remain saved.'
  if(batch.errors)return 'Some securities failed. Inspect the reason before retrying.'
  if(batch.status==='completed')return 'Download finished. Preparation status is shown below.'
  return 'This batch is waiting for attention.'
}
const fault=(batch:Batch)=>{
  const f=batch.failure_examples?.[0]
  if(!f)return null
  const code=f.code.toUpperCase()
  if(code.includes('401')||code.includes('403'))
    return {title:'Dhan access needs attention',
      action:'Verify your token and historical Data API entitlement before retrying.'}
  if(code.includes('429'))
    return {title:'Dhan rate limit reached',
      action:'Retry after the provider allows additional requests. Completed downloads are safe.'}
  if(code.includes('5')&&code.includes('HTTP'))
    return {title:'Dhan is temporarily unavailable',
      action:'Resume the remaining instruments when the service recovers.'}
  if(code.includes('400'))
    return {title:'Provider rejected an instrument or date request',
      action:'Review the affected stock, exchange ID and date window in diagnostics.'}
  return {title:'Some original candles could not be downloaded',
    action:'Open the failure details and retry only unresolved work.'}
}

export default function MarketDataWorkspace({initialPage='get',datasets,onDataChanged,
  onSelectDataset,onOpenModels,onRequestDelete}:Props){
  const [page,setPage]=useState<Page>(initialPage)
  const [stage,setStage]=useState<0|1|2>(0)
  const [advanced,setAdvanced]=useState<Advanced>(null)
  const [selection,setSelection]=useState<Selection>('nifty50_pit')
  const [fromDate,setFromDate]=useState(()=>yearsAgo(3))
  const [throughDate,setThroughDate]=useState(today)
  const [interval,setInterval]=useState<string>('daily')
  const [tickerText,setTickerText]=useState('')
  const [tickerQuery,setTickerQuery]=useState('')
  const [tickerSuggestions,setTickerSuggestions]=useState<{symbol:string;display_name:string}[]>([])
  const [modelId,setModelId]=useState('')
  const [modelDataset,setModelDataset]=useState('')
  const [models,setModels]=useState<Model[]>([])
  const [plan,setPlan]=useState<Plan|null>(null)
  const [planError,setPlanError]=useState('')
  const [checkingPlan,setCheckingPlan]=useState(false)
  const [connection,setConnection]=useState<Connection|null>(null)
  const [check,setCheck]=useState<DhanCheck|null>(null)
  const [kite,setKite]=useState<KiteStatus|null>(null)
  const [verifying,setVerifying]=useState(false)
  const [connectOpen,setConnectOpen]=useState(false)
  const [dhanToken,setDhanToken]=useState('')
  const [consentLocal,setConsentLocal]=useState(false)
  const [savingToken,setSavingToken]=useState(false)
  const [sourceWorking,setSourceWorking]=useState(false)
  const [batches,setBatches]=useState<Batch[]>([])
  const [deleted,setDeleted]=useState<Batch[]>([])
  const [selectedBatch,setSelectedBatch]=useState('')
  const [detail,setDetail]=useState<Batch|null>(null)
  const [job,setJob]=useState<Job|null>(null)
  const [sourceJob,setSourceJob]=useState<Job|null>(null)
  const [actionBusy,setActionBusy]=useState(false)
  const [allowPartial,setAllowPartial]=useState(false)
  const [confirmBulk,setConfirmBulk]=useState(false)
  const [confirmLarge,setConfirmLarge]=useState(false)
  const [runModelAfter,setRunModelAfter]=useState(true)
  const [allowAutoFallback,setAllowAutoFallback]=useState(false)
  const [secondaryPlan,setSecondaryPlan]=useState<SecondaryPlan|null>(null)
  const [secondaryBusy,setSecondaryBusy]=useState(false)
  const [secondaryConsent,setSecondaryConsent]=useState(false)
  const [indexSpot,setIndexSpot]=useState(false)
  const [showDiagnostics,setShowDiagnostics]=useState(false)
  const [message,setMessage]=useState('')
  const [error,setError]=useState('')
  const [revision,setRevision]=useState(0)

  const tickers=useMemo(()=>symbolList(tickerText),[tickerText])
  const completion=useMemo(()=>batches.find(b=>b.id===selectedBatch)||detail,[batches,selectedBatch,detail])
  const selected=useMemo(()=>datasets.find(d=>d.id===modelDataset),[datasets,modelDataset])
  const currentBatchState=completion?.status

  const refresh=useCallback(async()=>{
    const results=await Promise.allSettled([
      api<Connection>('/dhan/status'),
      api<{batches:Batch[]}>('/dhan/batches'),
      api<{batches:Batch[]}>('/dhan/batches/trash'),
      api<{models:Model[]}>('/data-manager/model-catalog'),
      api<KiteStatus>('/data-manager/zerodha/status')
    ])
    if(results[0].status==='fulfilled')setConnection(results[0].value)
    if(results[1].status==='fulfilled'){
      const rows=results[1].value.batches
      setBatches(rows);setSelectedBatch(id=>rows.some(b=>b.id===id)?id:rows[0]?.id||'')
    }
    if(results[2].status==='fulfilled')setDeleted(results[2].value.batches)
    if(results[3].status==='fulfilled')
      setModels(results[3].value.models.filter(m=>m.mode==='historical'))
    if(results[4].status==='fulfilled')setKite(results[4].value)
    const failures=results.filter(x=>x.status==='rejected') as PromiseRejectedResult[]
    if(failures.length===results.length)setError('Cannot load the local market data service. Start bash run.sh.')
  },[])
  useEffect(()=>{void refresh()},[refresh])
  useEffect(()=>{
    if(page!=='get')return
    const controller=new AbortController()
    const timer=window.setTimeout(()=>{
      setCheckingPlan(true);setPlanError('')
      const qs=new URLSearchParams({selection,from_date:fromDate,to_date:nextDay(throughDate),
        tickers:selection==='watchlist'?tickers.join(','):'',model_id:modelId})
      if(interval!=='daily')qs.set('interval',interval)
      void api<Plan>('/market-data/plan?'+qs.toString(),{signal:controller.signal})
        .then(data=>{if(!controller.signal.aborted)setPlan(data)})
        .catch(e=>{if(!controller.signal.aborted){
          setPlan(null);setPlanError(errorText(e))
        }})
        .finally(()=>{if(!controller.signal.aborted)setCheckingPlan(false)})
    },260)
    return()=>{controller.abort();window.clearTimeout(timer)}
  },[page,selection,fromDate,throughDate,interval,tickers,modelId,revision])
  useEffect(()=>{
    if(selection!=='watchlist'||!tickerQuery.trim()||!connection?.instrument_master_available){
      setTickerSuggestions([]);return
    }
    let active=true
    const timer=window.setTimeout(()=>{
      void api<{items:{symbol:string;display_name:string}[]}>(
        '/dhan/catalog?'+new URLSearchParams({
          exchange:'NSE',regular_only:'true',query:tickerQuery,per_page:'12'
        }).toString()).then(r=>{if(active)setTickerSuggestions(r.items)})
        .catch(()=>{if(active)setTickerSuggestions([])})
    },220)
    return()=>{active=false;window.clearTimeout(timer)}
  },[tickerQuery,selection,connection?.instrument_master_available])
  useEffect(()=>{
    if(!selectedBatch){setDetail(null);return}
    let active=true
    const update=async()=>{
      try{
        const response=await api<Batch>('/dhan/batches/'+encodeURIComponent(selectedBatch))
        if(active){
          setDetail(response)
          setBatches(prev=>prev.map(b=>b.id===response.id?response:b))
        }
      }catch(e){if(active)setError(errorText(e))}
    }
    void update()
    const timer=window.setInterval(()=>{
      if(active)void update()
    },2200)
    return()=>{active=false;window.clearInterval(timer)}
  },[selectedBatch])
  useEffect(()=>{
    if(!job||!['queued','running'].includes(job.status))return
    let active=true
    const timer=window.setTimeout(()=>{
      void api<Job>('/jobs/'+encodeURIComponent(job.id)).then(next=>{
        if(!active)return
        setJob(next)
        if(next.status==='complete'){
          setMessage('Download job finished. Checking the saved dataset and source coverage.')
          void refresh();onDataChanged();setRevision(v=>v+1)
        }else if(['error','cancelled'].includes(next.status)){
          setError(next.error||'Download was interrupted. Your existing candles remain saved.')
          void refresh()
        }
      }).catch(e=>{if(active)setError(errorText(e))})
    },1400)
    return()=>{active=false;window.clearTimeout(timer)}
  },[job,refresh,onDataChanged])
  useEffect(()=>{
    if(!sourceJob||!['queued','running'].includes(sourceJob.status))return
    let active=true
    const timer=window.setTimeout(()=>{
      void api<Job>('/jobs/'+encodeURIComponent(sourceJob.id)).then(next=>{
        if(!active)return
        setSourceJob(next)
        if(next.status==='complete'){
          setSourceWorking(false);setMessage('Source setup completed. Rechecking the requested period.')
          void refresh();setRevision(v=>v+1)
        }else if(['error','cancelled'].includes(next.status)){
          setSourceWorking(false)
          setError(next.error||'The public index or instrument source needs attention.')
        }
      }).catch(e=>{if(active)setError(errorText(e))})
    },1450)
    return()=>{active=false;window.clearTimeout(timer)}
  },[sourceJob,refresh])
  useEffect(()=>{
    if(page!=='downloads'||!selectedBatch){setSecondaryPlan(null);return}
    let active=true
    void api<SecondaryPlan>('/market-data/secondary/plan?'+
      new URLSearchParams({batch_id:selectedBatch}).toString())
      .then(value=>{if(active)setSecondaryPlan(value)})
      .catch(()=>{if(active)setSecondaryPlan(null)})
    return()=>{active=false}
  },[page,selectedBatch,currentBatchState,revision])

  const runAction=async<T,>(action:()=>Promise<T>,success:(result:T)=>void)=>{
    setActionBusy(true);setError('');setMessage('')
    try{success(await action())}
    catch(e){setError(errorText(e))}
    finally{setActionBusy(false)}
  }
  const verify=async():Promise<boolean>=>{
    setVerifying(true);setError('')
    try{
      const next=await api<DhanCheck>('/dhan/credentials/check')
      setCheck(next)
      if(!next.ok)setError(next.message)
      return next.ok
    }catch(e){setError(errorText(e));return false}
    finally{setVerifying(false)}
  }
  const connectDhan=async()=>{
    if(!dhanToken.trim()||!consentLocal||savingToken)return
    setSavingToken(true);setError('');setMessage('')
    try{
      const result=await post<{connected:boolean;message:string}>(
        '/market-data/providers/dhan/connect',{
          access_token:dhanToken,confirm_local_storage:true
        })
      setDhanToken('');setConsentLocal(false);setConnectOpen(false)
      setCheck(null);setMessage(result.message)
      void refresh();setRevision(v=>v+1)
    }catch(e){setError(errorText(e))}
    finally{setSavingToken(false)}
  }
  const prepareSources=()=>void runAction(
    ()=>post<{job_id:string;status:string}>('/market-data/sources/prepare',{
      selection,to_date:nextDay(throughDate),confirm_public_sources:true
    }),result=>{
      setSourceWorking(true)
      setSourceJob({id:result.job_id,status:result.status})
      setMessage('Checking historical membership and instrument catalog automatically.')
    })
  const start=async()=>{
    if(!plan?.can_start||checkingPlan||actionBusy)return
    const verified=await verify()
    if(!verified)return
    void runAction(
      ()=>post<{job_id:string;status:string;batch:Batch}>('/market-data/start',{
        selection,from_date:fromDate,to_date:nextDay(throughDate),
        interval:interval==='daily'?null:Number(interval),
        tickers:selection==='watchlist'?tickers:[],model_id:modelId,
        preview_token:plan.preview_token,confirm_readonly:true,
        confirm_incomplete:allowPartial,confirm_bulk:confirmBulk,
        confirm_large_history:confirmLarge,
        run_model_after_prepare:Boolean(modelId&&plan.model_followup.eligible&&runModelAfter),
        confirm_secondary_fallback:Boolean(allowAutoFallback&&interval==='daily'&&kite?.token_present),
        include_index_spot:indexSpot
      }),result=>{
        setJob({id:result.job_id,status:result.status})
        setSelectedBatch(result.batch.id)
        setPage('downloads')
        setMessage('Download approved. Existing verified candles will be reused; preparation runs automatically if all instruments succeed.')
        void refresh()
      })
  }
  const batchAction=(batch:Batch,action:'resume'|'cancel'|'prepare')=>{
    const route=action==='resume'?'resume':action==='cancel'?'cancel':'prepare'
    void runAction(()=>post<{job_id?:string;status?:string}>(
      '/dhan/batches/'+encodeURIComponent(batch.id)+'/'+route,{}),result=>{
      if(result.job_id)setJob({id:result.job_id,status:result.status||'queued'})
      setSelectedBatch(batch.id)
      setMessage(action==='resume'?'Resuming unfinished instruments. Previously saved candles are preserved.':
        action==='cancel'?'Stop requested; the current request may finish first.':
          'Preparing a source-limited dataset from the downloaded instruments.')
      void refresh()
    })
  }
  const recoverSecondary=async()=>{
    if(!secondaryPlan?.can_recover||!secondaryConsent||secondaryBusy)return
    setSecondaryBusy(true);setError('');setMessage('')
    try{
      const response=await post<{job_id:string;status:string}>(
        '/market-data/secondary/recover',{
          batch_id:secondaryPlan.batch_id,preview_token:secondaryPlan.preview_token,
          confirm_secondary:true})
      setJob({id:response.job_id,status:response.status})
      setSecondaryConsent(false)
      setMessage('Authorized Zerodha close recovery started. Original Dhan OHLCV and batch statuses stay unchanged.')
    }catch(e){setError(errorText(e))}
    finally{setSecondaryBusy(false)}
  }
  const trashBatch=(batch:Batch)=>{
    if(!window.confirm('Move this download queue to Trash? Its original cached candles and prepared datasets are preserved.'))return
    void runAction(()=>api('/dhan/batches/'+encodeURIComponent(batch.id)+'?confirm=true',{
      method:'DELETE'}),()=>{
      if(selectedBatch===batch.id){setSelectedBatch('');setDetail(null)}
      setMessage('Queue moved to Trash; original cached observations preserved.')
      void refresh()
    })
  }
  const restoreBatch=(batch:Batch)=>{
    void runAction(()=>post('/dhan/batches/trash/'+encodeURIComponent(batch.id)+'/restore',{}),()=>{
      setMessage('Download queue restored.');void refresh()
    })
  }
  const purgeBatch=(batch:Batch)=>{
    if(!window.confirm('Permanently remove this deleted queue? Original market candles remain preserved.'))return
    void runAction(()=>api('/dhan/batches/trash/'+encodeURIComponent(batch.id)+'?confirm=true',{
      method:'DELETE'}),()=>{setMessage('Deleted queue permanently removed.');void refresh()})
  }
  const addTicker=(s:string)=>{
    setTickerText(prev=>Array.from(new Set([...symbolList(prev),s])).join('\n'))
    setTickerQuery('')
  }
  const sourceNeedsSetup=Boolean(plan?.next_actions.some(a=>
    a.kind==='sync_membership'||a.kind==='refresh_catalog'))
  const batch=detail?.id===selectedBatch?detail:completion
  const percent=batch?.total?Math.round(batch.processed/batch.total*100):0
  const active=Boolean(batch&&['running','queued'].includes(batch.status))
  const availableDatasets=datasets.filter(d=>d.kind!=='synthetic')
  const summary = batch?fault(batch):null

  return <div className="mdw-root">
    <div className="mdw-hero">
      <div><span className="mdw-eyebrow"><Database size={15}/> MARKET DATA WORKSPACE</span>
        <h2>Get the data. QuantLab handles the preparation.</h2>
        <p>Choose an index, stock universe or research model. We check original sources,
          reuse cached observations and show exactly what is missing.</p>
      </div>
      <div className="mdw-safety"><ShieldCheck size={17}/> Read-only market data · No orders</div>
    </div>
    <div className="mdw-tabs" role="tablist" aria-label="Market data views">
      {([['get','Get Data',Download],['datasets','My Datasets',Database],
        ['downloads','Downloads & Jobs',Activity]] as const).map(([key,label,Icon])=>
        <button key={key} role="tab" type="button" aria-selected={page===key}
          className={page===key?'active':''} onClick={()=>setPage(key)}>
          <Icon size={17}/>{label}</button>)}
    </div>
    {error&&<div className="mdw-alert error" role="alert"><AlertCircle size={17}/>
      <span>{error}</span><button type="button" aria-label="Dismiss error"
        onClick={()=>setError('')}><X size={15}/></button></div>}
    {message&&<div className="mdw-alert good" role="status"><CheckCircle2 size={17}/>
      <span>{message}</span><button type="button" aria-label="Dismiss message"
        onClick={()=>setMessage('')}><X size={15}/></button></div>}
    {page==='get'&&<div className="mdw-flow">
      <nav className="mdw-steps" aria-label="Market data setup steps">
        {stepLabels.map((title,i)=><button type="button" key={title}
          className={stage===i?'active':''}
          aria-current={stage===i?'step':undefined}
          onClick={()=>setStage(i as 0|1|2)}>
          <span>{i+1}</span>{title}</button>)}
      </nav>
      {selected&&<div className="mdw-active-extension" role="status">
        <div><strong>Extending: {selected.label}</strong>
          <p>The existing dataset is selected. Choose a model to calculate exact missing
            observations and reuse the existing original source files.</p></div>
        <button className="mdw-button secondary" type="button"
          onClick={()=>setModelDataset('')}>Start a new dataset instead</button>
      </div>}
      {stage===0&&<section className="mdw-card">
        <div className="mdw-section-top"><div><span className="mdw-kicker">STEP 1 · WHAT TO COLLECT</span>
          <h3>Choose your research data</h3><p>Start from a universe, not an API or file format.</p>
        </div></div>
        <div className="mdw-choice-grid">
          {(['nifty50_pit','banknifty_pit','watchlist'] as Selection[]).map((key,i)=>
            <button type="button" key={key} className={'mdw-choice '+(selection===key?'selected':'')}
              aria-pressed={selection===key} onClick={()=>{setSelection(key);setAllowPartial(false);setConfirmBulk(false)}}>
              <span className="mdw-choice-icon">{i===0?<Layers size={22}/>:
                i===1?<Activity size={22}/>:<Search size={22}/>}</span>
              <strong>{modeNames[key]}</strong><small>{i===0?'Historical constituents, not just today’s companies':
                i===1?'Historically accurate bank index universe':
                  'Find stocks by name or paste an exact ticker list'}</small>
              {selection===key&&<Check size={18} className="mdw-choice-check"/>}
            </button>)}
        </div>
        {selection==='watchlist'&&<div className="mdw-symbols">
          <label>Search NSE stocks
            <div className="mdw-search"><Search size={17}/><input type="search"
              value={tickerQuery} onChange={e=>setTickerQuery(e.target.value)}
              aria-label="Search stocks by name or ticker"
              placeholder="RELIANCE, TCS or company name"/></div>
          </label>
          {!!tickerSuggestions.length&&<div className="mdw-suggestions">
            {tickerSuggestions.map(s=><button type="button" key={s.symbol}
              onClick={()=>addTicker(s.symbol)}><strong>{s.symbol}</strong>
                <small>{s.display_name}</small><span>Add +</span></button>)}
          </div>}
          <label>Selected tickers · one per line or separated by commas
            <textarea rows={3} value={tickerText} onChange={e=>setTickerText(e.target.value)}
              aria-label="Stock ticker list" placeholder={'RELIANCE\nTCS\nINFY'}/>
          </label>
          <small>{fmt(tickers.length)} unique tickers · exact Dhan master matching; no guessed identities.</small>
        </div>}
        <details className="mdw-options"><summary>Large or custom exchange universe <ChevronDown size={16}/></summary>
          <div className="mdw-choice-grid two">
            {(['all_nse','all_bse'] as Selection[]).map(key=><button key={key}
              type="button" className={'mdw-choice '+(selection===key?'selected':'')}
              onClick={()=>setSelection(key)} aria-pressed={selection===key}>
              <Layers size={18}/><strong>{modeNames[key]}</strong>
              <small>Current listed cash equities; may contain thousands of instruments.</small>
            </button>)}
          </div>
        </details>
        <div className="mdw-step-actions">
          <button type="button" className="mdw-button next" onClick={()=>setStage(1)}>
            Continue to history & source checks <ArrowRight size={16}/>
          </button>
        </div>
      </section>}
      {stage===1&&<section className="mdw-card">
        <div className="mdw-section-top"><div><span className="mdw-kicker">STEP 2 · HISTORY & READINESS</span>
          <h3>What history do you need?</h3>
          <p>Daily candles are recommended for equity-factor research. For a model,
            QuantLab estimates the preferred additional 20% before you download.</p></div>
        </div>
        <div className="mdw-form">
          <label><CalendarDays size={15}/> From date
            <input type="date" value={fromDate} max={throughDate} aria-label="Start date"
              onChange={e=>setFromDate(e.target.value)}/></label>
          <label><CalendarDays size={15}/> Through date · inclusive
            <input type="date" value={throughDate} max={today()} min={fromDate}
              aria-label="Through date" onChange={e=>setThroughDate(e.target.value)}/></label>
          <label>Frequency
            <select value={interval} aria-label="Candle frequency"
              onChange={e=>setInterval(e.target.value)}>
              <option value="daily">Daily · recommended</option>
              <option value="60">60-minute</option>
              <option value="15">15-minute</option>
              <option value="5">5-minute</option>
              <option value="1">1-minute · large download</option>
            </select></label>
          <label>Research model · optional
            <select value={modelId} aria-label="Optional research model"
              onChange={e=>setModelId(e.target.value)}>
              <option value="">General-purpose history</option>
              {models.map(m=><option key={m.id} value={m.id}>{m.title}</option>)}
            </select></label>
        </div>
        {modelId&&<p className="mdw-help">Choosing a model guides the sample estimate.
          After download, the actual observed returns are checked before a model can run.</p>}
        {checkingPlan&&<p className="mdw-inline-status" role="status">
          <LoaderCircle size={16} className="mdw-spin"/> Checking catalog, dates and coverage…</p>}
        {planError&&<div className="mdw-callout warn" role="alert">
          <AlertCircle size={17}/>{planError}</div>}
        {plan?.model_requirements?.mode==='historical'&&
          <div className="mdw-model-readiness">
            <div><span>Model minimum</span><strong>{fmt(plan.model_requirements.minimum||0)} returns</strong></div>
            <div><span>Preferred (+20%)</span><strong>{fmt(plan.model_requirements.preferred||0)} returns</strong></div>
            {plan.model_requirements.suggested_from&&fromDate>plan.model_requirements.suggested_from&&
              <button type="button" onClick={()=>setFromDate(plan.model_requirements?.suggested_from||fromDate)}>
                Use suggested earlier start · {plan.model_requirements.suggested_from}
                <ArrowRight size={15}/></button>}
          </div>}
        <div className="mdw-plan">
          <div className="mdw-plan-head">
            <span className="mdw-kicker">LIVE SOURCE PLAN · READ-ONLY PREVIEW</span>
            <button type="button" onClick={()=>setRevision(v=>v+1)}
              aria-label="Recheck data plan"><RefreshCw size={15}/> Recheck</button>
          </div>
          <div className="mdw-plan-stats">
            <div><small>Instruments matched</small><strong>{plan?fmt(plan.instrument_count):'…'}</strong></div>
            <div><small>Unresolved identities</small><strong>{plan?fmt(plan.unresolved_count):'…'}</strong></div>
            <div><small>Request upper bound</small><strong>{plan?fmt(plan.estimated_request_upper_bound):'…'}</strong></div>
            <div><small>Data frequency</small><strong>{interval==='daily'?'Daily':interval+' min'}</strong></div>
          </div>
          <p className="mdw-footnote">{plan?.estimate_note||
            'Planning uses local metadata. No historical broker data is requested yet.'}</p>
          {plan?.membership.state==='ready'&&<p className="mdw-goodline"><CheckCircle2 size={16}/>
            Dated membership available · {fmt(plan.membership.union_count||0)}
            {' '}distinct historical members across these dates.</p>}
          {plan?.blockers.map((text,i)=><div key={i} className="mdw-callout warn" role="status">
            <AlertCircle size={16}/>{text}</div>)}
          {plan?.membership.state==='needs_source'&&plan.membership.covered_through&&
            fromDate<=plan.membership.covered_through&&
            throughDate>plan.membership.covered_through&&
            <button type="button" className="mdw-button secondary"
              onClick={()=>setThroughDate(plan.membership.covered_through||throughDate)}>
              Use latest documented membership date ({plan.membership.covered_through})
              <ArrowRight size={14}/>
            </button>}
          {plan?.warnings.map((text,i)=><p key={i} className="mdw-warning">{text}</p>)}
          {plan?.unresolved_count? <details className="mdw-details">
            <summary>Review {plan.unresolved_count} unresolved historical stocks</summary>
            {plan.unresolved.map(u=><div className="mdw-diagnostic" key={u.symbol}>
              <strong>{u.symbol}</strong><span>{u.reason}</span></div>)}
            <label className="mdw-consent"><input type="checkbox" checked={allowPartial}
              onChange={e=>setAllowPartial(e.target.checked)}/>
              I understand this source will be incomplete because historical instruments cannot be mapped.</label>
          </details>:null}
          {plan&&plan.capacity.large&&
            <div className="mdw-callout warn"><HardDrive size={16}/>
              <span>Large request: about {(plan.capacity.bytes_upper_estimate/2**30).toFixed(1)} GiB
                across all instruments before cached-window reuse. Estimate only;
                confirm available disk space before starting.</span>
            </div>}
          {plan&&plan.instrument_count>100&&
            <label className="mdw-consent"><input type="checkbox" checked={confirmBulk}
              onChange={e=>setConfirmBulk(e.target.checked)}/>
              Approve this large read-only request across {fmt(plan.instrument_count)} instruments.</label>}
          {sourceNeedsSetup&&<div className="mdw-action-strip">
            <div><strong>Set up the missing public sources</strong>
              <p>Sync the dated index-membership file and/or the current instrument catalog.
                No broker candles are requested in this step.</p></div>
            <button className="mdw-button" type="button" disabled={actionBusy||sourceWorking}
              onClick={prepareSources}>{sourceWorking?
              <LoaderCircle size={16} className="mdw-spin"/>:<RefreshCw size={16}/>}
              {sourceWorking?'Preparing sources…':'Prepare missing sources'}</button>
          </div>}
          {sourceJob&&['queued','running'].includes(sourceJob.status)&&
            <div className="mdw-inline-status" role="status"><LoaderCircle className="mdw-spin" size={16}/>
              {sourceJob.stage||'Syncing public source'} · {Math.round(sourceJob.percent||0)}%</div>}
        </div>
        <div className="mdw-step-actions">
          <button type="button" className="mdw-button secondary" onClick={()=>setStage(0)}>
            Back to data selection
          </button>
          <button type="button" className="mdw-button next" onClick={()=>setStage(2)}>
            Continue to provider & download <ArrowRight size={16}/>
          </button>
        </div>
      </section>}
      {stage===2&&<section className="mdw-card mdw-commit">
        <div className="mdw-section-top"><div><span className="mdw-kicker">STEP 3 · AUTHORIZE</span>
          <h3>{modelId&&selected?'Complete your existing model dataset':
            'Get data and prepare automatically'}</h3>
          {modelId&&selected?
            <p>Reuse this dataset’s verified original observations, then acquire only
              compatible missing history for the selected model.</p>:
            <p>We check your local Dhan credentials and Data API access before creating a
              download. Only missing windows are requested; verified source files remain intact.</p>}
        </div></div>
        <div className="mdw-provider-line">
          <div><span className={'mdw-led '+(connection?.token_configured?'ok':'')}/>
            <strong>Dhan · primary</strong><small>{check?.ok?'Historical Data API verified':
              check&&!check.ok?check.message:
                connection?.token_configured?'Token detected · live access not yet verified':'Token missing'}</small></div>
          <div className="mdw-provider-actions">
            <button className="mdw-button secondary" type="button"
              onClick={()=>setConnectOpen(v=>!v)}>
              {connection?.token_configured?'Replace token':'Connect Dhan'}
            </button>
            <button type="button" onClick={()=>void verify()} disabled={verifying||!connection?.token_configured}
              className="mdw-button secondary">
              {verifying?<LoaderCircle size={15} className="mdw-spin"/>:<ShieldCheck size={15}/>}
              Verify access</button>
          </div>
        </div>
        {connectOpen&&<div className="mdw-connect-form">
          <strong>Connect Dhan historical Data API</strong>
          <p>Paste the access token generated by Dhan Web. QuantLab verifies the token
            and its Data API entitlement, then stores it only in this machine's ignored
            private .env file. The token is never shown in results or saved in the browser.</p>
          <label>One-time Dhan access token
            <input type="password" value={dhanToken} autoComplete="off"
              aria-label="Dhan access token"
              onChange={e=>setDhanToken(e.target.value)}
              placeholder="Paste your Dhan Web token"/>
          </label>
          <label className="mdw-consent"><input type="checkbox" checked={consentLocal}
            onChange={e=>setConsentLocal(e.target.checked)}/>
            I approve storing a verified token in the private local configuration.</label>
          <button type="button" className="mdw-button"
            disabled={savingToken||!consentLocal||!dhanToken.trim()} onClick={()=>void connectDhan()}>
            {savingToken?<LoaderCircle size={15} className="mdw-spin"/>:<ShieldCheck size={15}/>}
            Verify & save locally
          </button>
          <p className="mdw-footnote">If Dhan expires this token, replace it here with a fresh one.
            Data API access and permitted historical windows still depend on Dhan's account entitlement.</p>
        </div>}
        <div className="mdw-provider-line">
          <div><span className={'mdw-led '+(kite?.token_present?'ok':'')}/>
            <strong>Zerodha · eligible secondary</strong>
            <small>{kite?.token_present?'Session present (entitlements require verification)':
              'Not connected'}
              {' '}· Automatic fallback is currently restricted to compatible model-data extensions.</small></div>
          <button type="button" className="mdw-button secondary"
            onClick={()=>setAdvanced(advanced==='providers'?null:'providers')}>Manage providers</button>
        </div>
        {interval==='daily'&&kite?.token_present&&
          <label className="mdw-consent">
            <input type="checkbox" aria-label="Approve automatic Zerodha recovery"
              checked={allowAutoFallback} onChange={e=>setAllowAutoFallback(e.target.checked)}/>
            If Dhan fails, automatically attempt compatible verified Zerodha daily-close recovery
            in the separate shared store. Requires exact Kite mapping and three agreeing
            original Dhan sessions; original Dhan OHLCV will remain incomplete.
          </label>}
        <details className="mdw-options">
          <summary>Optional index spot price & source policy <ChevronDown size={15}/></summary>
          <label className="mdw-consent"><input type="checkbox"
            checked={indexSpot} onChange={e=>setIndexSpot(e.target.checked)}/>
            Include observed index spot candles (price-only, not dividend-reinvested TRI).</label>
          <p className="mdw-help">{plan?.provider_policy}</p>
        </details>
        {!(modelId&&selected)&&<>
          {plan?.capacity.large&&<label className="mdw-consent">
            <input type="checkbox" checked={confirmLarge}
              aria-label="Approve large historical data download"
              onChange={e=>setConfirmLarge(e.target.checked)}/>
            I reviewed the approximately {(plan.capacity.bytes_upper_estimate/2**30).toFixed(1)} GiB
            source estimate and approve this large download.
          </label>}
          {modelId&&<div className="mdw-model-run-consent">
            {plan?.model_followup.eligible?
              <label className="mdw-consent"><input type="checkbox"
                aria-label="Run model after download" checked={runModelAfter}
                onChange={e=>setRunModelAfter(e.target.checked)}/>
                After downloading, run and save {models.find(m=>m.id===modelId)?.title||'the model'}
                only if actual aligned source returns meet its preferred +20% history.
              </label>:<p className="mdw-help">{plan?.model_followup.note||
                'Complete this model using its exact input selectors after downloading.'}</p>}
          </div>}

        <button type="button" className="mdw-primary" disabled={!plan?.can_start||
          (plan.unresolved_count>0&&!allowPartial)||
          (plan.instrument_count>100&&!confirmBulk)||
          (plan.capacity.large&&!confirmLarge)||
          actionBusy||verifying||checkingPlan||sourceWorking||Boolean(job&&
            ['queued','running'].includes(job.status))}
          onClick={()=>void start()}>
          {actionBusy||verifying?<LoaderCircle size={19} className="mdw-spin"/>:
            <Download size={19}/>}
          {modelId&&plan?.model_followup.eligible&&runModelAfter?
            'Get, prepare & run model':'Get & prepare data'} <ArrowRight size={19}/>
        </button>
        <p className="mdw-footnote">This button approves read-only data requests
          only for this signed date and instrument scope. Complete batches prepare
          automatically. If model execution is selected, it runs only after genuine
          observations pass the preferred sample check. Missing market history,
          historical membership or entitlements cannot be invented.</p>
        </>}
        {modelId&&<div className="mdw-model-link"><BookOpen size={17}/>
          Already have a dataset for this model?
          <select aria-label="Existing dataset for model acquisition" value={modelDataset}
            onChange={e=>setModelDataset(e.target.value)}>
            <option value="">Choose to extend one</option>
            {availableDatasets.filter(d=>d.has_prices).map(d=><option value={d.id} key={d.id}>{d.label}</option>)}
          </select>
        </div>}
        {modelId&&selected&&<div id="mdw-model-extension" className="mdw-extension">
          <h4>Complete the selected dataset for {models.find(m=>m.id===modelId)?.title||'this model'}</h4>
          <p>QuantLab calculates exact model readiness, reuses existing verified candles,
            and only proposes additional provider requests when compatible.</p>
          <Suspense fallback={<p>Loading model-specific acquisition…</p>}>
            <DataAcquisitionPanel datasets={availableDatasets}
              initialModelId={modelId} initialDatasetId={selected.id}
              onCompleted={id=>{onSelectDataset(id);onDataChanged();setPage('datasets')}}
              onOpenDhan={()=>setPage('get')} onOpenModels={onOpenModels}/>
          </Suspense>
        </div>}
        <div className="mdw-step-actions">
          <button type="button" className="mdw-button secondary" onClick={()=>setStage(1)}>
            Back to history & source plan
          </button>
        </div>
      </section>}
    </div>}
    {page==='datasets'&&<section className="mdw-card">
      <div className="mdw-section-top"><div><span className="mdw-kicker">MY DATASETS</span>
        <h3>Everything you've collected</h3>
        <p>Actual source files, preparation and model readiness are separate checks.
          A downloaded candle is not automatically a certified index backtest.</p></div>
        <button className="mdw-button" onClick={()=>setPage('get')}>
          <Download size={16}/> Get more data</button></div>
      {!availableDatasets.length&&<div className="mdw-empty"><HardDrive size={30}/>
        <strong>No observed datasets yet</strong>
        <p>Choose NIFTY 50, BANK NIFTY or your stocks and prepare your first dataset.</p>
        <button className="mdw-button" onClick={()=>setPage('get')}>Get your first dataset <ArrowRight size={15}/></button>
      </div>}
      <div className="mdw-dataset-list">{availableDatasets.map(d=><article className="mdw-dataset" key={d.id}>
        <div className="mdw-dataset-icon"><Database size={22}/></div>
        <div className="mdw-dataset-body"><strong>{d.label}</strong>
          <small>{d.kind} · {fmt(d.daily_session_count||0)} daily sessions
            {' '}· {fmt(d.monthly_price_observations||0)} monthly marks</small>
          <p>{d.has_prices?'Price observations saved':'Awaiting observed prices'}
            {d.ready?' · Source files satisfy this dataset’s structural readiness checks':
              ' · Not yet research-ready for all workflows'}</p>
          {!!d.missing?.length&&<details><summary>{d.missing.length} missing requirement(s)</summary>
            {d.missing.map((m,i)=><p key={i} className="mdw-warning">{m}</p>)}</details>}
        </div>
        <div className="mdw-dataset-actions">
          <span className={'mdw-badge '+(d.ready?'good':'warn')}>{d.ready?'Files ready':'Needs inputs'}</span>
          <button type="button" onClick={()=>{onSelectDataset(d.id);onOpenModels()}}>
            Use in models <ArrowRight size={15}/></button>
          <button type="button" onClick={()=>{
            setModelDataset(d.id)
            setModelId(v=>v||'min_variance')
            setPage('get')
            setStage(2)
            window.setTimeout(()=>document.getElementById('mdw-model-extension')
              ?.scrollIntoView({behavior:'smooth',block:'start'}),180)
          }}>Extend / complete</button>
          <button type="button" className="mdw-delete"
            onClick={()=>onRequestDelete(d.id)}><Trash2 size={15}/> Delete</button>
        </div>
      </article>)}</div>
    </section>}
    {page==='downloads'&&<section className="mdw-card">
      <div className="mdw-section-top"><div><span className="mdw-kicker">DOWNLOADS & JOBS</span>
        <h3>See exactly what's happening</h3>
        <p>Queues are resumable; downloading, verification and preparation have distinct states.</p>
      </div><button type="button" className="mdw-button" onClick={()=>void refresh()}>
        <RefreshCw size={16}/> Refresh</button></div>
      {job&&['queued','running'].includes(job.status)&&<div className="mdw-job" role="status">
        <LoaderCircle size={22} className="mdw-spin"/><div><strong>{job.stage||'Original market data job'}</strong>
          <small>{Math.round(job.percent||0)}% · Job {job.id}</small></div></div>}
      {job?.status==='complete'&&Boolean(job.result?.secondary_recovery)&&
        <div className="mdw-callout warn" role="status">
          <ShieldCheck size={17}/>
          <div><strong>Secondary source: {(
            job.result?.secondary_recovery as {status?:string}).status||'review needed'}</strong>
            <p>{(job.result?.secondary_recovery as {message?:string}).message||
              'Only eligible, exact-source-matched secondary records were retained.'}</p>
          </div>
        </div>}
      {job?.status==='complete'&&job.result?.original_dhan_batch_changed===false&&
        <div className="mdw-callout success">
          Original Dhan batch unchanged. Review validated secondary receipts in Advanced Data Tools.
        </div>}
      {job?.status==='complete'&&Boolean(job.result?.model_research)&&
        <div className={'mdw-callout '+(
          (job.result?.model_research as {status?:string}).status==='complete'?
            'success':'warn')} role="status">
          <FileCheck2 size={17}/>
          <div><strong>Model continuation: {(
            job.result?.model_research as {status?:string}).status||'review needed'}</strong>
            <p>{(job.result?.model_research as {message?:string}).message||
              'Source-bound research is saved only when its required real returns are available.'}</p>
            <button type="button" onClick={onOpenModels}>
              View Model Laboratory <ArrowRight size={14}/>
            </button></div>
        </div>}
      {!batches.length&&<div className="mdw-empty"><Clock3 size={27}/>
        <strong>No downloads yet</strong><p>Data acquisition jobs appear here immediately after authorization.</p>
        <button className="mdw-button" onClick={()=>setPage('get')}>Get data</button>
      </div>}
      {batches.length>0&&<div className="mdw-batch-layout">
        <div className="mdw-batch-list">{batches.slice(0,100).map(b=><button type="button"
          key={b.id} className={selectedBatch===b.id?'active':''}
          onClick={()=>{setSelectedBatch(b.id);setShowDiagnostics(false)}}>
          <span><strong>{modeNames[b.selection as Selection]||statusLabel(b.selection)}</strong>
            <small>{b.from_date} → {previousDay(b.to_date)} · {b.interval||'Daily'} {b.interval?'min':''}</small></span>
          <span className={'mdw-badge '+(b.prepared_dataset_id?'good':b.errors?'warn':'')}>
            {b.prepared_dataset_id?'Prepared':statusLabel(b.status)}</span></button>)}</div>
        {batch&&<div className="mdw-batch-detail">
          <div className="mdw-batch-detail-head"><strong>{modeNames[batch.selection as Selection]||batch.selection}</strong>
            <span className={'mdw-badge '+(batch.prepared_dataset_id?'good':'')}>
              {batch.prepared_dataset_id?'Dataset prepared':statusLabel(batch.status)}</span></div>
          <p>{stateMessage(batch)}</p>
          <div className="mdw-progress" role="progressbar" aria-label="Instruments processed"
            aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100}>
            <span style={{width:percent+'%'}}/></div>
          <div className="mdw-batch-stats">
            <div><strong>{fmt(batch.processed)} / {fmt(batch.total)}</strong><small>Processed</small></div>
            <div><strong>{fmt((batch.counts.complete||0)+(batch.counts.cached||0))}</strong><small>Downloaded / reused</small></div>
            <div><strong>{fmt(batch.counts.failed||0)}</strong><small>Failed</small></div>
            <div><strong>{fmt(batch.counts.no_data||0)}</strong><small>No source candles</small></div>
          </div>
          {batch.current_symbol&&<p className="mdw-inline-status" role="status">
            {active?<LoaderCircle size={16} className="mdw-spin"/>:<Clock3 size={16}/>}
            {active?'Working on':'Last attempted'} {batch.current_symbol}
            {batch.current_window?' · Window '+batch.current_window:''}</p>}
          {!!batch.rejected_provider_bars&&<div className="mdw-callout warn">
            <AlertCircle size={17}/> {fmt(batch.rejected_provider_bars)} invalid source bars
            were excluded and recorded; missing prices were not invented.</div>}
          {summary&&<div className="mdw-callout warn"><AlertCircle size={17}/><div>
            <strong>{summary.title}</strong><p>{summary.action}</p>
            <button type="button" onClick={()=>setShowDiagnostics(v=>!v)}>
              {showDiagnostics?'Hide':'View'} technical details <ChevronDown size={13}/></button></div></div>}
          {showDiagnostics&&<div className="mdw-diagnostics">
            {(batch.failure_examples||[]).map((f,i)=><div key={i}>
              <strong>{f.symbol} · {f.code}</strong><p>{f.explanation}</p>
              <code>{f.diagnostic}</code></div>)}
          </div>}
          {batch.prepared_dataset_id&&<div className="mdw-callout success">
            <FileCheck2 size={17}/><span>Dataset: {batch.prepared_dataset_id}.
              Source pricing can still lack TRI, corporate actions and original delisting observations.</span>
            <button type="button" onClick={()=>{onSelectDataset(batch.prepared_dataset_id||'');
              onDataChanged();setPage('datasets')}}>Open dataset <ArrowRight size={14}/></button>
          </div>}
          {batch.preparation_error&&<div className="mdw-callout warn">
            <AlertCircle size={17}/> Preparation needs attention: {batch.preparation_error}</div>}
          {batch.interval===null&&secondaryPlan&&secondaryPlan.candidate_count>0&&
            <div className="mdw-secondary">
              <div className="mdw-secondary-title"><ShieldCheck size={17}/>
                <strong>Secondary-source recovery · daily closes only</strong></div>
              <p>{secondaryPlan.eligible_count} of {secondaryPlan.candidate_count}
                {' '}unresolved securities have a currently eligible exact Zerodha mapping.</p>
              <p className="mdw-footnote">{secondaryPlan.note}</p>
              {secondaryPlan.blockers.map((m,i)=><p className="mdw-warning" key={i}>{m}</p>)}
              <details className="mdw-details">
                <summary>Review instrument eligibility</summary>
                {secondaryPlan.items.map(item=><div className="mdw-diagnostic" key={item.instrument_id}>
                  <strong>{item.symbol}</strong>
                  <span>{item.eligible?'Eligible mapping':'Blocked'} · {item.reason}</span>
                </div>)}
              </details>
              {secondaryPlan.can_recover&&<>
                <label className="mdw-consent"><input type="checkbox"
                  aria-label="Approve secondary recovered closes"
                  checked={secondaryConsent}
                  onChange={e=>setSecondaryConsent(e.target.checked)}/>
                  Authorize read-only Zerodha history for these exact daily securities.
                  I understand that original Dhan batch status will NOT be changed.
                </label>
                <button type="button" className="mdw-button" disabled={!secondaryConsent||
                  secondaryBusy||Boolean(job&&['queued','running'].includes(job.status))}
                  onClick={()=>void recoverSecondary()}>
                  {secondaryBusy?<LoaderCircle size={16} className="mdw-spin"/>:<RotateCcw size={16}/>}
                  Recover eligible daily closes via Zerodha
                </button>
              </>}
              {!secondaryPlan.can_recover&&<button type="button" className="mdw-button secondary"
                onClick={()=>setAdvanced('providers')}>Manage secondary provider</button>}
            </div>}
          <div className="mdw-batch-actions">
            {active?<button className="mdw-button" disabled={actionBusy}
              onClick={()=>batchAction(batch,'cancel')}><Pause size={15}/> Pause safely</button>:
              !batch.prepared_dataset_id&&<button className="mdw-button" disabled={actionBusy}
                onClick={()=>batchAction(batch,'resume')}><Play size={15}/> Resume / retry missing</button>}
            {!active&&!batch.prepared_dataset_id&&
              (batch.counts.complete||0)+(batch.counts.cached||0)>0&&
              <button type="button" className="mdw-button"
                onClick={()=>{if(window.confirm(
                  'Prepare a PARTIAL dataset from verified downloaded stocks? Missing instruments remain documented.'))
                  batchAction(batch,'prepare')}} disabled={actionBusy}>
                <FileCheck2 size={15}/> Prepare available data</button>}
            {!active&&<button type="button" className="mdw-button danger"
              disabled={actionBusy} onClick={()=>trashBatch(batch)}>
              <Trash2 size={15}/> Delete queue</button>}
          </div>
          <details className="mdw-details"><summary>Original download metadata</summary>
            <div className="mdw-diagnostic"><strong>Batch ID</strong><span>{batch.id}</span></div>
            <div className="mdw-diagnostic"><strong>Dates</strong><span>{batch.from_date} – {batch.to_date} (exclusive)</span></div>
            <p className="mdw-help">Original Dhan candles remain cached after deleting a queue.
              Historical membership, adjusted total returns and corporate-action data
              have separate evidence requirements.</p></details>
        </div>}
      </div>}
      <details className="mdw-options"><summary>Deleted queues ({deleted.length}) · restore or purge <ChevronDown size={15}/></summary>
        {deleted.map(b=><div key={b.id} className="mdw-deleted-row">
          <span>{modeNames[b.selection as Selection]||b.selection} · {b.id}</span>
          <button type="button" onClick={()=>restoreBatch(b)}><RotateCcw size={15}/> Restore</button>
          <button type="button" onClick={()=>purgeBatch(b)}><Trash2 size={15}/> Delete permanently</button>
        </div>)}
        {!deleted.length&&<p className="mdw-help">Trash is empty.</p>}
      </details>
    </section>}
    <div className="mdw-advanced">
      <div><Settings2 size={20}/><div><strong>Advanced Data Tools</strong>
        <p>Original-source inspection, Dhan manual controls, database tables and provider setup.</p></div></div>
      <div className="mdw-advanced-actions">
        {([['providers','Providers & sources'],['manual','Detailed downloader'],
          ['database','Database Manager']] as const).map(([key,label])=>
          <button key={key} type="button" className={advanced===key?'active':''}
            onClick={()=>setAdvanced(advanced===key?null:key)}>{label}</button>)}
      </div>
    </div>
    {advanced&&<Suspense fallback={<div className="mdw-card" role="status">
      <LoaderCircle size={17} className="mdw-spin"/> Opening advanced data tools…</div>}>
      {advanced==='providers'&&<SourceFallbackPanel onChanged={()=>{
        void refresh();onDataChanged();setRevision(v=>v+1)}}/>}
      {advanced==='manual'&&<DhanDataManager onDataChanged={()=>{
        void refresh();onDataChanged();setRevision(v=>v+1)}}/>}
      {advanced==='database'&&<DataManager onSelectDataset={onSelectDataset}
        onChanged={onDataChanged} onOpenDhan={()=>{setPage('get');setAdvanced(null)}}
        onOpenModels={onOpenModels}/>}
    </Suspense>}
    <p className="mdw-last-note"><CircleHelp size={14}/> This workspace runs locally. Data API access,
      historic instrument mappings, adjusted total returns and benchmark licensing
      cannot be invented or silently substituted. Every limitation remains inspectable.</p>
  </div>
}
