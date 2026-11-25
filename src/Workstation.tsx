import {lazy, Suspense, useCallback, useEffect, useMemo, useState} from 'react'
import {
  Activity, ArrowDownToLine, ArrowRight, BarChart3, Beaker, BookOpen, Check,
  CheckCircle2, ChevronDown, ChevronRight, CircleAlert, Clock3, Database, FileArchive,
  FileText, Gauge, LoaderCircle,
  LockKeyhole, Menu, Play, RefreshCw, Settings2,
  ShieldCheck, Sigma, Upload, Trash2, RotateCcw, Search, X, TrendingUp
} from 'lucide-react'
import './workstation.css'
import './quantlab-v3-modules.css'
import {RecorderBadge,JobsDrawer,V2HomeLaunchers,StrategyLibraryV2,ConnectionsLandingV2,SettingsPreferencesV2,DiagnosticsV2,QuickPageNote} from './QuantLabV2Components'
import ResearchPythonLab from './ResearchPythonLab'
import AutoDepthRecorder from './AutoDepthRecorder'
import DataManager from './DataManager'
import IndexBuilderWorkspace from './IndexBuilderWorkspace'
import GlobalSearchV2 from './GlobalSearchV2'
import PythonWorkbench from './PythonWorkbench'
import PythonMonitors from './PythonMonitors'
import PythonEnvironment from './PythonEnvironment'
import ResearchPlot from './ResearchPlots'
const CustomModelWorkspace = lazy(() => import('./CustomModelWorkspace'))
const ResearchNotebook = lazy(() => import('./ResearchNotebook'))
const PaperTradingWorkspace = lazy(() => import('./PaperTradingWorkspace'))
const MarketDataWorkspace = lazy(() => import('./MarketDataWorkspace'))
const TradingCockpit = lazy(() => import('./TradingCockpit'))
const LiquiditySpreadsWorkspace = lazy(() => import('./LiquiditySpreadsWorkspace'))
const ModelLaboratory = lazy(() => import('./ModelLaboratory'))
const ResearchGuide = lazy(() => import('./ResearchGuide'))
const ResearchWorkspace = lazy(() => import('./ResearchWorkspace'))
const NSESourceAssistant = lazy(() => import('./NSESourceAssistant'))
const ResultsStudio = lazy(() => import('./ResultsStudio'))
const ResearchJourney = lazy(() => import('./ResearchJourney'))
const HistoricalValidationPanel = lazy(() => import('./HistoricalValidationPanel'))

type Dict = Record<string, unknown>
type Dataset = {id:string; label:string; kind:string; ready:boolean; monthly_price_observations?:number; missing:string[]; files:string[]; has_prices:boolean; has_daily_prices?:boolean; has_daily_ohlcv?:boolean; source_interval_minutes?:number|null; daily_session_count?:number; benchmark_kind?:string; benchmark_is_total_return?:boolean; independently_verified?:boolean; has_fundamentals:boolean; has_sectors:boolean; basis:string}
type Run = {id:string; name:string; dataset_id?:string; dataset_kind:string; created_utc?:string; metrics_by_split:Record<string,Dict>; coverage:Dict; status:string; first_price_date?:string; last_price_date?:string}
type Job = {id:string; kind:string; status:'queued'|'running'|'complete'|'error'; error?:string; result?:unknown}
type Detail = {id:string;meta:{config:Dict; metrics_by_split:Record<string,Dict>; coverage:Dict; limitations:string[]; first_price_date:string;last_price_date:string; generated_utc:string};source:Dict;returns:Dict[];latest_weights:{name:string;weight:number}[];rank_ic:Dict[];factor_exposures:Dict[];concentration:Dict[];rolling:Dict[];cost_sensitivity:Dict[];robustness:Dict[];methodologies:Dict[];audit:Dict;data_quality:Dict;artifacts:string[]}
type Health = {ok:boolean; mode:string; framework:string; read_only_market_data:boolean; broker_orders_enabled:boolean; dhan_token_configured:boolean; datasets:number;completed_runs:number}
type DhanStatus = {token_configured:boolean;instrument_master_available:boolean;instrument_master_bytes:number;read_only:boolean}
type DatasetTrash = {id:string;kind:string;title:string;trashed:boolean;archived:boolean;protected:boolean}
type DatasetDeletePlan = {dataset_id:string;label:string;can_archive:boolean;
  can_delete_all:boolean;dependent_count:number;dependent_run_count:number;
  dependent_items:{kind:string;id:string;title:string;reason:string}[];
  blocking_references:{kind:string;id:string;title:string;reason?:string}[];
  counts:Record<string,number>;preview_token:string;recoverable:boolean;
  raw_market_data_preserved:boolean;summary:string}

type RunConfig = {
  name:string;factor_weights:Record<string,number>;top_n:number;weighting:string;
  max_weight:number;rebalance_every:number;cost_bps:number;execution_lag:number;
  momentum_formation:number;momentum_skip:number;volatility_lookback:number;
  validation_start:string;final_test_start:string;sector_cap:number|null
}
const defaultConfig:RunConfig = {name:'quant_research_v1', factor_weights:{momentum:1,low_volatility:0,value:0,quality:0,size:0},top_n:10,weighting:'equal',max_weight:.2,rebalance_every:3,cost_bps:10,execution_lag:1,momentum_formation:12,momentum_skip:1,volatility_lookback:12,validation_start:'',final_test_start:'',sector_cap:null}
type Tab =
  'overview'|'trading'|'tradingchain'|'tradingdepth'|'tradingspreads'|'tradingreplay'|'tradingjournal'|'tradingpaper'|'tradinganalytics'|'tradingdirectional'|
  'strategies'|'strategyema'|'strategypython'|'strategybacktest'|
  'mathematics'|'models'|'research'|'factors'|'construction'|'risk'|'rolling'|'robustness'|'modelgrids'|'indexstudio'|
  'data'|'dhan'|'dataexplorer'|'dataquality'|'datadownloads'|'nse'|'evidence'|
  'history'|'workspace'|'chartstudio'|'comparisons'|'visual'|'workspacejobs'|
  'projects'|'reports'|'resourcebrowser'|'settings'|'connections'|'recordingsettings'|
  'storage'|'preferences'|'diagnostics'|'guide'|'journey'|'pythonmonitors'|'pythonenvironment'|'custommodels'|'customscanners'|'notebooks'
type PrimarySection={id:Tab;label:string;icon:typeof Activity;tabs:Tab[];navTabs:Tab[]}
const primarySections:PrimarySection[]=[
  {id:'overview',label:'Home',icon:Gauge,tabs:['overview'],navTabs:['overview']},
  {id:'trading',label:'Trading',icon:Activity,
    tabs:['trading','tradingchain','tradingdepth','tradingspreads','tradingreplay','tradingjournal','tradingpaper','tradinganalytics','tradingdirectional','customscanners'],
    navTabs:['trading','tradingchain','tradingdepth','tradingspreads','tradingreplay','tradingjournal','tradingpaper']},
  {id:'strategies',label:'Strategies',icon:TrendingUp,
    tabs:['strategies','strategyema','strategypython','strategybacktest','pythonmonitors'],
    navTabs:['strategies','strategyema','strategypython','strategybacktest']},
  {id:'mathematics',label:'Models',icon:Sigma,
    tabs:['mathematics','models','research','factors','construction','risk','rolling','robustness','modelgrids','indexstudio','journey','custommodels'],
    navTabs:['mathematics','research','models']},
  {id:'data',label:'Data Center',icon:Database,
    tabs:['data','dhan','dataexplorer','dataquality','datadownloads','nse','evidence'],
    navTabs:['data','dhan','dataexplorer','dataquality','datadownloads']},
  {id:'history',label:'Results & Charts',icon:BarChart3,
    tabs:['history','workspace','chartstudio','comparisons','visual','workspacejobs'],
    navTabs:['history','workspace','chartstudio']},
  {id:'projects',label:'Projects',icon:BookOpen,
    tabs:['projects','notebooks','reports','resourcebrowser'],navTabs:['projects','notebooks','reports']},
  {id:'connections',label:'Settings',icon:Settings2,
    tabs:['connections','recordingsettings','storage','preferences','diagnostics','settings','guide','pythonenvironment'],
    navTabs:['connections','recordingsettings','diagnostics']},
]
const titles:Record<Tab,string>={
  overview:'Home',trading:'Live Market',tradingchain:'Option Chain',
  tradingdepth:'20-Level Order Book',tradingspreads:'Liquidity & Spreads',
  tradingreplay:'Market Replay',
  tradingjournal:'Trade Journal',tradingpaper:'Paper Trading',tradinganalytics:'Options Analytics',tradingdirectional:'Directional Trading',strategies:'Strategy Library',
  strategyema:'EMA Explorer',strategypython:'Python Editor',
  strategybacktest:'BANKNIFTY Backtests',pythonmonitors:'Running Python',custommodels:'Custom Models',customscanners:'Custom Scanners',pythonenvironment:'Python Environment',
  mathematics:'Model Catalog',models:'Advanced Research Tools',
  research:'Index Builder',factors:'Factor Research',
  construction:'Portfolio Construction',risk:'Risk Attribution',
  rolling:'Rolling Validation',robustness:'Robustness & Sensitivity',
  modelgrids:'Guided Model Grids',indexstudio:'Index Research Studio',
  data:'Market Library',dhan:'Get Market Data',
  dataexplorer:'Data Explorer',dataquality:'Quality & Coverage',
  datadownloads:'Downloads',nse:'NSE Source Evidence',
  evidence:'Evidence & Machine Learning',
  history:'All Research Results',workspace:'Compare Runs',
  chartstudio:'Chart Studio',comparisons:'Index Comparison',
  visual:'Historical Charts',workspacejobs:'Research Job History',
  projects:'My Projects & Notebooks',notebooks:'Research Notebooks',reports:'Research Reports',
  resourcebrowser:'Saved Resource Library',
  connections:'Connections',recordingsettings:'Automatic Recording',
  storage:'Storage & Data Management',preferences:'Preferences',
  diagnostics:'System Diagnostics',settings:'Backend & Privacy',
  guide:'Help & How It Works',journey:'New Guided Study',
}
const descriptions:Record<Tab,string>={
  overview:'Monitor your data and resume research. Nothing shown here is a simulated profit claim.',
  trading:'Monitor real BANKNIFTY index packets and signals without submitting broker orders.',
  tradingchain:'Inspect source-backed BANKNIFTY CE/PE strikes, expiries, premium and lot sizes.',
  tradingdepth:'Inspect original Dhan 20-bid/20-ask books and actual recorded source packets.',
  tradingspreads:'Compare actual Dhan bid/ask liquidity, estimate execution costs and investigate spread research without orders.',
  tradingreplay:'Explore recorded BANKNIFTY, option quotes and original market-depth observations.',
  tradingjournal:'Review manually entered fills and prospective signal accuracy separately.',
  tradingpaper:'Manage virtual cash, simulated orders and original-depth historical replays without broker execution.',
  tradinganalytics:'Compare Greek sensitivities, volatility, liquidity and contract scenarios.',
  tradingdirectional:'Evaluate directional option research and scenario-driven contract selection without placing orders.',
  strategies:'Choose a strategy, test real index signals, then study historical CE/PE contracts.',
  strategyema:'Test one EMA pair, chosen combinations or all 11,026 valid pairs.',
  strategypython:'Paste, run and save isolated Python research without interrupting Dhan capture.',
  strategybacktest:'Compare directional signal timing and original-contract CE/PE paper P&L.',
  pythonmonitors:'Run saved Python revisions on incoming recorded observations.',
  custommodels:'Maintain and execute user-defined snapshot-based quantitative calculations.',
  customscanners:'Rank source-backed option contracts using your saved Python score.',
  pythonenvironment:'Inspect and test optional scientific packages in an isolated environment.',
  notebooks:'Save versioned Python and Markdown cells, attach input data and run reproducible calculations.',
  mathematics:'Choose stochastic, volatility, options, risk and portfolio mathematical models.',
  models:'Sweep parameters, test walk-forward stability, study shocks and inspect advanced research tools.',
  research:'Construct, backtest and validate factor-based equity indices.',
  factors:'Inspect real saved factor ranking and exposure output.',
  construction:'Inspect constituent weights, concentration and rebalance consequences.',
  risk:'Measure portfolio concentration and rolling risk on archived runs.',
  rolling:'Use rolling time windows on saved historical index results.',
  robustness:'Study parameter stability and sensitivity in saved experiments.',
  modelgrids:'Run guided research questions, two-parameter grids and constrained optimization.',
  indexstudio:'Inspect advanced researcher index methods, data passports and explanations.',
  data:'Browse one canonical library of market instruments and downloaded observations.',
  dhan:'Choose instruments and acquire only missing source-backed history.',
  dataexplorer:'Inspect market data rows, original vendor files and source fields.',
  dataquality:'Check completeness, duplicate data and market-data provenance.',
  datadownloads:'Review downloads and source-repair progress.',
  evidence:'Inspect original source evidence, research readiness and trained machine-learning validation.',
  nse:'Inspect official NSE evidence and source provenance.',
  history:'Search and interpret saved mathematical and strategy research results.',
  workspace:'Overlay comparable saved runs and inspect differences.',
  chartstudio:'Build interactive two- and three-dimensional research figures.',
  comparisons:'Review historical methodology and transaction-cost comparisons.',
  visual:'Inspect saved source-backed historical return and factor charts.',
  workspacejobs:'Inspect research and acquisition job history.',
  projects:'Save reproducible research in projects, notebooks and linked run references.',
  resourcebrowser:'Search, organize, archive and restore saved model runs, charts and research records.',
  reports:'Generate and export reports from actually saved research evidence.',
  connections:'Check local data-provider access and permissions safely.',
  recordingsettings:'Configure automatic read-only CE/PE recording and inspect source coverage.',
  storage:'Manage source files, cache, archival status and recoverable data.',
  preferences:'Choose comfortable or compact workspace settings and reduced motion.',
  diagnostics:'Inspect API health, source errors and actual next-step repair tools.',
  settings:'Local-only backend, broker permissions and data privacy.',
  guide:'Help for market data, model readiness, results and backtests.',
  journey:'Follow one five-step research workflow using the same existing models.',
}
const validTabs=new Set<Tab>(Object.keys(titles) as Tab[])
function hashTab():Tab{
  const value=decodeURIComponent(window.location.hash.replace(/^#\/?/,''))
  return validTabs.has(value as Tab)?value as Tab:'overview'
}
const number=(v:unknown,d=2)=>typeof v==='number' && Number.isFinite(v) ? v.toLocaleString('en-US',{maximumFractionDigits:d,minimumFractionDigits:d}) : '—'
const percent=(v:unknown,d=2)=>typeof v==='number' && Number.isFinite(v) ? (v*100).toFixed(d)+'%' : '—'
const label=(s:string)=>s.replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase())
const date=(s?:string)=>s ? new Date(s).toLocaleString(undefined,{month:'short',day:'numeric',year:'numeric'}) : '—'
function errorMessage(error:unknown){return error instanceof Error?error.message:String(error)}
async function request<T>(url:string, options?:RequestInit):Promise<T>{
  let response:Response
  try {response=await fetch('/api'+url,options)}catch{throw new Error('Cannot reach the Python research engine. Start the workstation using bash run.sh.')}
  if(!response.ok){let payload:Dict={};try{payload=await response.json()}catch{/* empty */}
    const detail=payload.detail
    throw new Error(typeof detail==='string'?detail:response.status+' '+response.statusText)
  }
  return await response.json() as T
}
function post<T>(url:string,body:unknown){return request<T>(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})}
function Tag({children,tone='neutral'}:{children:React.ReactNode;tone?:'neutral'|'good'|'warn'|'bad'|'blue'}){
  return <span className={'ws-tag '+tone}>{children}</span>
}
function Card({title,children,extra,className=''}:{title?:string;children:React.ReactNode;extra?:React.ReactNode;className?:string}){
  return <section className={'ws-card '+className}>{title&&<div className="ws-cardhead"><h3>{title}</h3>{extra}</div>}{children}</section>
}
function Empty({title,children,onAction,action}:{title:string;children?:React.ReactNode;onAction?:()=>void;action?:string}){
  return <div className="ws-empty"><Database size={26} strokeWidth={1.5}/><strong>{title}</strong><p>{children}</p>{onAction&&<button className="ws-button" type="button" onClick={onAction}>{action||'Open data manager'} <ArrowRight size={14}/></button>}</div>
}
function Metric({label:caption,value,caption:note,highlight}:{label:string;value:string;caption?:string;highlight?:boolean}){
  return <div className={'ws-metric '+(highlight?'highlight':'')}><span>{caption}</span><strong>{value}</strong><small>{note}</small></div>
}
function Table({rows,max=15}:{rows:Dict[];max?:number}){
  if(!rows.length)return <div className="ws-table-empty">No saved observations for this panel. Run an experiment first.</div>
  const keys=Object.keys(rows[0]).slice(0,11)
  return <div className="ws-table-scroll"><table><thead><tr>{keys.map(k=><th key={k}>{label(k)}</th>)}</tr></thead><tbody>{rows.slice(0,max).map((row,i)=><tr key={i}>{keys.map(k=><td key={k} title={String(row[k]??'')}>{typeof row[k]==='number'?number(row[k],4):String(row[k]??'—')}</td>)}</tr>)}</tbody></table></div>
}
function EquityChart({rows,caption='Strategy vs benchmark',provenance='historical'}:{rows:Dict[];caption?:string;provenance?:string}){
  type View='wealth'|'excess'|'drawdown'
  const [view,setView]=useState<View>('wealth')
  const points=useMemo(()=>{
    let strategy=1,benchmark=1,strategyHigh=1,benchmarkHigh=1,chainValid=true
    return rows.map(r=>{
      const sr=r.strategy_net==null||r.strategy_net===''?NaN:Number(r.strategy_net),br=r.benchmark==null||r.benchmark===''?NaN:Number(r.benchmark)
      if(!Number.isFinite(sr)||!Number.isFinite(br)||sr<=-1||br<=-1)chainValid=false
      const excess=Number.isFinite(sr)&&Number.isFinite(br)?(sr-br)*100:null
      if(chainValid){strategy*=1+sr;benchmark*=1+br;strategyHigh=Math.max(strategyHigh,strategy);benchmarkHigh=Math.max(benchmarkHigh,benchmark)}
      return {date:String(r.date||''),strategy:chainValid?strategy:null,benchmark:chainValid?benchmark:null,excess,strategyDrawdown:chainValid?(strategy/strategyHigh-1)*100:null,benchmarkDrawdown:chainValid?(benchmark/benchmarkHigh-1)*100:null}
    })
  },[rows])
  if(points.length<2)return <Empty title="Awaiting observed return series">A saved backtest needs at least two valid strategy and benchmark returns.</Empty>
  const label=view==='wealth'?'Cumulative wealth (× initial capital)':view==='drawdown'?'Drawdown (%)':'Net monthly excess return (percentage points)'
  const traces=view==='excess'?[{name:'Strategy − benchmark',y:points.map(p=>p.excess)}]:[{name:'Strategy',color:'#f5c542',y:points.map(p=>view==='wealth'?p.strategy:p.strategyDrawdown)},{name:'Benchmark',color:'#78a8ff',y:points.map(p=>view==='wealth'?p.benchmark:p.benchmarkDrawdown)}]
  return <div className="ws-chart ws-interactive-chart"><div className="ws-chart-views" role="group" aria-label="Performance graph type">{([['wealth','Growth line'],['excess','Monthly difference'],['drawdown','Drawdown area']] as const).map(([id,name])=><button type="button" key={id} aria-pressed={view===id} className={view===id?'active':''} onClick={()=>setView(id)}>{name}</button>)}</div>
    <ResearchPlot plot={{kind:view==='excess'?'bar2d':view==='drawdown'?'area2d':'line2d',title:caption+' · '+label,x_label:'Observation date',y_label:label,x:points.map(p=>p.date),traces,reference_lines:[{value:view==='wealth'?1:0,label:view==='wealth'?'Initial capital = 1×':'Zero'}]}} provenance={provenance} formatY={v=>v.toFixed(view==='wealth'?3:2)}/>
    <p className="ws-caption">Cumulative wealth starts at 1× before the first observed return. Missing or invalid returns stop the cumulative path rather than silently fill missing data. Historical simulation, not proof of investability.</p></div>
}
function BarRows({rows,valueKey='weight',nameKey='name'}:{rows:Dict[];valueKey?:string;nameKey?:string}){
  if(!rows.length)return <Empty title="No exposure data">Select a completed research run to inspect portfolio exposures.</Empty>
  const top=rows.slice(0,14); const max=Math.max(...top.map(r=>Math.abs(Number(r[valueKey]||0))),.00001)
  return <div className="ws-bars">{top.map((r,i)=><div className="ws-bar-row" key={i}><span title={String(r[nameKey])}>{String(r[nameKey]??'—')}</span><div><i style={{width:(Math.abs(Number(r[valueKey]||0))/max*100)+'%'}}/></div><strong>{percent(Number(r[valueKey]))}</strong></div>)}</div>
}
const weighted=(metric:Dict|undefined,key:string)=>metric?.[key]
function App(){
  const [tab,setTab]=useState<Tab>(hashTab)
  const [jobsOpen,setJobsOpen]=useState(false)
  const [connectionEditing,setConnectionEditing]=useState(false)
  const [searchOpen,setSearchOpen]=useState(false)
  const [pythonOpen,setPythonOpen]=useState(false)
  const showPython=useCallback(()=>setPythonOpen(true),[])
  const [menu,setMenu]=useState(false)
  const [compactNav,setCompactNav]=useState(()=>{try{return localStorage.getItem('ql-v3-compact-nav')==='1'}catch{return false}})
  useEffect(()=>{try{localStorage.setItem('ql-v3-compact-nav',compactNav?'1':'0')}catch{/* optional preference */}},[compactNav])
  const [health,setHealth]=useState<Health|null>(null)
  const [datasets,setDatasets]=useState<Dataset[]>([])
  const [selectedDataset,setSelectedDataset]=useState('')
  const [deletedDatasets,setDeletedDatasets]=useState<DatasetTrash[]>([])
  const [archivedDatasets,setArchivedDatasets]=useState<DatasetTrash[]>([])
  const [deletePlan,setDeletePlan]=useState<DatasetDeletePlan|null>(null)
  const [triFile,setTriFile]=useState<File|null>(null)
  const [triDateColumn,setTriDateColumn]=useState('Date')
  const [triLevelColumn,setTriLevelColumn]=useState('Total Returns Index')
  const [triConfirmed,setTriConfirmed]=useState(false)
  const [triConvention,setTriConvention]=useState('gross_total_return')
  const [runs,setRuns]=useState<Run[]>([])
  const [selectedRun,setSelectedRun]=useState('')
  const [focusedModelRun,setFocusedModelRun]=useState('')
  const [detail,setDetail]=useState<Detail|null>(null)
  const [config,setConfig]=useState<RunConfig>(defaultConfig)
  const [job,setJob]=useState<Job|null>(null)
  const [busy,setBusy]=useState(false)
  const [notice,setNotice]=useState<{text:string;error:boolean}|null>(null)
  const [auditResult,setAuditResult]=useState<Dict|null>(null)
  const [dhan,setDhan]=useState<DhanStatus|null>(null)
  useEffect(()=>{if(tab!=='connections')setConnectionEditing(false)},[tab])
  const dataset=datasets.find(d=>d.id===selectedDataset)
  const everydaySources=datasets.filter(d=>d.id==='dhan_shared'||d.kind!=='dhan'||d.id===selectedDataset)
  const selected=runs.find(r=>r.id===selectedRun)
  const metrics=detail?.meta.metrics_by_split??selected?.metrics_by_split??{}
  const split=Object.entries(metrics).at(-1)
  const metric=split?.[1]
  const notify=(text:string,error=false)=>setNotice({text,error})
  const refresh=useCallback(async()=>{
    try {
      const [h, ds, rr, dh, resources]=await Promise.all([
        request<Health>('/health'),request<{datasets:Dataset[]}>('/datasets'),
        request<{runs:Run[]}>('/runs'),request<DhanStatus>('/dhan/status'),
        request<{resources:DatasetTrash[]}>('/workspace/resources?include_trashed=true')
      ])
      setHealth(h);setDatasets(ds.datasets);setRuns(rr.runs);setDhan(dh)
      setDeletedDatasets(resources.resources.filter(r=>r.kind==='dataset'&&r.trashed))
      setArchivedDatasets(resources.resources.filter(r=>r.kind==='dataset'&&r.archived&&!r.trashed))
      setSelectedDataset(s=>{
        const existing=ds.datasets.find(d=>d.id===s)
        if(existing&&existing.kind!=='synthetic')return s
        const shared=ds.datasets.find(d=>d.id==='dhan_shared'&&d.has_prices)
        const research=ds.datasets.find(d=>d.kind!=='dhan'&&d.kind!=='synthetic'&&d.has_prices)
        return shared?.id||research?.id||existing?.id||ds.datasets.find(d=>d.ready)?.id||ds.datasets[0]?.id||''
      })
      setSelectedRun(s=>rr.runs.some(r=>r.id===s)?s:rr.runs[0]?.id||'')
    }catch(e){notify(errorMessage(e),true)}
  },[])
  useEffect(()=>{void refresh()},[refresh])
  useEffect(()=>{
    if(!selectedRun){setDetail(null);return}
    let active=true
    request<Detail>('/runs/'+encodeURIComponent(selectedRun)).then(d=>{if(active)setDetail(d)}).catch(e=>{if(active){setDetail(null);notify(errorMessage(e),true)}})
    return()=>{active=false}
  },[selectedRun])
  useEffect(()=>{
    if(!job||!['queued','running'].includes(job.status))return
    const timer=setTimeout(()=>{
      request<Job>('/jobs/'+job.id).then(j=>{
        setJob(j)
        if(j.status==='complete'){
          notify(['experiment','frozen_evaluation'].includes(j.kind)?'Research run completed; saved to Results Studio.':'Operation completed.')
          void refresh()
          if(['experiment','frozen_evaluation'].includes(j.kind) && typeof j.result==='string'){setSelectedRun(j.result);setTab(j.kind==='frozen_evaluation'?'history':'overview')}
        }
        if(j.status==='error')notify(j.error||'Job failed',true)
      }).catch(e=>notify(errorMessage(e),true))
    },1400)
    return()=>clearTimeout(timer)
  },[job,refresh])
  const execute=async<T,>(f:()=>Promise<T>,callback?:(value:T)=>void)=>{
    setBusy(true)
    try {const value=await f();callback?.(value)}catch(e){notify(errorMessage(e),true)}finally{setBusy(false)}
  }
  const begin=(id:Tab)=>{
    setTab(id);setMenu(false)
    window.history.pushState({quantlab_view:id},'',window.location.pathname+
      window.location.search+'#/'+id)
    window.scrollTo(0,0)
  }
  useEffect(()=>{
    const navigateHistory=()=>{setTab(hashTab());setMenu(false)}
    window.addEventListener('popstate',navigateHistory)
    window.addEventListener('hashchange',navigateHistory)
    return()=>{
      window.removeEventListener('popstate',navigateHistory)
      window.removeEventListener('hashchange',navigateHistory)
    }
  },[])
  useEffect(()=>{
    const searchShortcut=(event:KeyboardEvent)=>{
      if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){
        event.preventDefault();setSearchOpen(open=>!open)
      }
    }
    window.addEventListener('keydown',searchShortcut)
    return()=>window.removeEventListener('keydown',searchShortcut)
  },[])
  useEffect(()=>{
    const navigate=(event:KeyboardEvent)=>{
      if((event.ctrlKey||event.metaKey)&&event.altKey&&
         !event.shiftKey&&/^[1-9]$/.test(event.key)){
        event.preventDefault()
        const target=primarySections[Number(event.key)-1]
        if(target){
          setTab(target.id);setMenu(false)
          window.history.pushState({quantlab_view:target.id},'','#/'+target.id)
          window.scrollTo(0,0)
        }
      }
    }
    window.addEventListener('keydown',navigate)
    return()=>window.removeEventListener('keydown',navigate)
  },[])
  const startRun=()=>execute(()=>post<{job_id:string;status:Job['status']}>('/experiments',{...config,dataset_id:selectedDataset}),r=>{setJob({id:r.job_id,kind:'experiment',status:'queued'});notify('Python research job queued.')})
  const synthetic=()=>execute(()=>post<Dataset>('/datasets/synthetic',{}),r=>{void refresh();setSelectedDataset(r.id);notify('Synthetic fixture created. This is not historical market evidence.')})
  const upload=async(file:File)=>{
    await execute(async()=>{
      const form=new FormData();form.append('file',file)
      return request<Dataset>('/datasets/import',{method:'POST',body:form})
    },r=>{void refresh();setSelectedDataset(r.id);notify('Dataset imported for internal validation; provenance remains unverified.')})
  }
  const attachTri=async()=>{
    if(!dataset||!triFile||!triConfirmed)return
    await execute(async()=>{
      const form=new FormData()
      form.append('file',triFile)
      form.append('confirmed_tri','true')
      form.append('date_column',triDateColumn)
      form.append('level_column',triLevelColumn)
      form.append('convention',triConvention)
      form.append('index_name',dataset.label.toLowerCase().includes('bank')?'NIFTY BANK TRI':'NIFTY 50 TRI')
      return request<Dataset & {benchmark_caveat:string;benchmark_alignment?:{matched_months:number;calendar_end_label_matches:number;exact_trading_date_matches:number}}>(
        '/datasets/'+encodeURIComponent(dataset.id)+'/add-tri',{method:'POST',body:form})
    },r=>{
      void refresh();setSelectedDataset(r.id);setTriFile(null);setTriConfirmed(false)
      notify('TRI aligned automatically for '+(r.benchmark_alignment?.matched_months||'saved')+
        ' stock months ('+(r.benchmark_alignment?.calendar_end_label_matches||0)+
        ' calendar-end labels resolved). No missing prices fabricated. Source reviews remain unverified.')
    })
  }
  const inspectDatasetDeletion=(d:Dataset)=>{
    setDeletePlan(null)
    setNotice(null)
    void execute(()=>request<DatasetDeletePlan>(
      '/workspace/datasets/'+encodeURIComponent(d.id)+'/delete-plan'),
      plan=>setDeletePlan({...plan,label:d.label}))
  }
  const archiveDataset=(plan:DatasetDeletePlan)=>{
    void execute(()=>post('/workspace/resources/action',{
      kind:'dataset',item_id:plan.dataset_id,action:'archive',
    }),()=>{setDeletePlan(null);void refresh();notify(
      'Dataset archived. All saved research results and original market data remain available.')})
  }
  const trashDataset=(plan:DatasetDeletePlan)=>{
    if(!plan.can_delete_all)return
    void execute(()=>post<{deleted_count:number;dependent_count:number}>(
      '/workspace/datasets/'+encodeURIComponent(plan.dataset_id)+'/trash-with-saved-runs',
      {preview_token:plan.preview_token,confirm:true}),
      result=>{setDeletePlan(null);void refresh();notify(
        'Deleted dataset and '+result.dependent_count+' linked saved item(s) from the active library. Everything is recoverable in Trash.')})
  }
  const restoreDataset=(id:string)=>{
    void execute(()=>post('/workspace/resources/action',{
      kind:'dataset',item_id:id,action:'restore',
    }),()=>{void refresh();setSelectedDataset(id);notify('Dataset restored.')})
  }
  const unarchiveDataset=(id:string)=>{
    void execute(()=>post('/workspace/resources/action',{
      kind:'dataset',item_id:id,action:'unarchive',
    }),()=>{void refresh();notify('Archived dataset restored to Data Library.')})
  }
  const purgeDataset=(id:string)=>{
    if(!window.confirm('Permanently delete this trashed derived dataset? This cannot be undone. Shared original candles are not removed.'))return
    void execute(()=>post('/workspace/resources/action',{
      kind:'dataset',item_id:id,action:'purge',confirm:true,
    }),()=>{void refresh();notify('Derived dataset permanently removed.')})
  }
  const downloadReport=()=>execute(()=>post<{job_id:string}>('/runs/'+selectedRun+'/reports',{}),r=>{setJob({id:r.job_id,kind:'reports',status:'queued'});notify('Report export queued.')})
  const dataPicker=<select className="ws-select" aria-label="Select research dataset" value={selectedDataset} onChange={e=>{setSelectedDataset(e.target.value)}}><option value="">Choose market source</option>{everydaySources.map(d=><option key={d.id} value={d.id}>{d.label}{d.ready?'':' (additional model evidence needed)'}</option>)}</select>
  const runPicker=<select aria-label="Select completed experiment" className="ws-select" value={selectedRun} onChange={e=>setSelectedRun(e.target.value)}>{runs.length===0?<option value="">No runs yet</option>:runs.map(r=><option key={r.id} value={r.id}>{r.name} · {r.id}</option>)}</select>
  const withRun=(content:React.ReactNode)=><>{runs.length===0?<Empty title="No research run selected" onAction={()=>begin('research')} action="Run an experiment">All charts are generated from Python research outputs, not hardcoded sample performance.</Empty>:<>{runPicker}{content}</>}</>
  const classification=<Tag tone={detail?.source.dataset_kind==='synthetic'?'warn':'blue'}>{detail?.source.dataset_kind==='synthetic'?'SYNTHETIC DATA — DEMONSTRATION':detail?'USER DATA · NOT INDEPENDENTLY AUDITED':'NO RESEARCH RUN'}</Tag>
  const chart=detail?<EquityChart rows={detail.returns} provenance={detail.source.dataset_kind==='synthetic'?'synthetic':'historical'}/>:null
  const panel=(key: keyof Detail,description:string)=>withRun(<Card title={description}><Table rows={(detail?.[key] as Dict[]|undefined)??[]} max={20}/></Card>)
  return <div className={'ws-shell ws-v2 ql-v3 '+(compactNav?'ql-nav-compact':'')}>
    <aside className={'ws-sidebar '+(menu?'open':'')}>
      <div className="ws-brand"><span className="ws-brand-mark"><Activity size={23}/></span><div><strong>QUANT<span>LAB</span></strong><small>RESEARCH WORKSTATION</small></div><button type="button" className="ws-mobile-close" onClick={()=>setMenu(false)}><X size={19}/></button></div>
      <div className="ws-env"><span className={'ws-status-dot '+(health?.ok?'':'offline')}/><div><strong>{health?.ok?'LOCAL ENGINE CONNECTED':'ENGINE DISCONNECTED'}</strong><small>127.0.0.1 · NO BROKER EXECUTION</small></div></div>
      <nav aria-label="Primary QuantLab navigation">
        <div className="ws-nav-group"><span className="ws-nav-label">WORKSPACES</span>
          <button type="button" className="ql-nav-toggle" onClick={()=>setCompactNav(v=>!v)} aria-label={compactNav?'Expand sidebar':'Collapse sidebar'} aria-expanded={!compactNav}><Menu size={17}/><span className="ql-nav-text">Collapse sidebar</span></button>
          {primarySections.map((section,index)=><button type="button" key={section.id}
            title={'Ctrl+Alt+'+(index+1)+' · '+section.label}
            onClick={()=>begin(section.id)}
            aria-current={section.tabs.includes(tab)?'page':undefined}
            className={'ws-nav-item '+(section.tabs.includes(tab)?'active':'')}>
            <section.icon size={17} strokeWidth={1.9}/><span className="ql-nav-text">{section.label}</span>
            {section.tabs.includes(tab)&&<span className="ws-nav-select"/>}</button>)}
        </div></nav>
      <div className="ws-sidefoot"><LockKeyhole size={15}/><div><strong>PRIVATE / LOCAL FIRST</strong><small>Credentials never sent to browser</small></div></div>
    </aside>
    {menu&&<button className="ws-backdrop" onClick={()=>setMenu(false)} aria-label="Close navigation"/>}
    <div className="ws-main">
      <header className="ws-topbar">
        <div className="v2-shell-top-left ws-top-left">
          <button type="button" className="ws-menu" onClick={()=>setMenu(true)} aria-label="Open navigation">
            <Menu size={19}/></button>
          <span className="ws-breadcrumb">QUANTLAB</span><ChevronRight size={14}/>
          <strong>{primarySections.find(section=>section.tabs.includes(tab))?.label||'Research'}</strong>
          {titles[tab]!==primarySections.find(section=>section.tabs.includes(tab))?.label&&
            <><ChevronRight size={14}/><strong>{titles[tab]}</strong></>}
        </div>
        <div className="v2-top-actions">
          <button type="button" className="v2-top-btn" onClick={()=>setSearchOpen(true)}
            aria-label="Search QuantLab" title="Search QuantLab · Ctrl K">
            <Search size={16}/><span>Search</span></button>
          <RecorderBadge onOpen={()=>begin('recordingsettings')}/>
          <button type="button" className="v2-top-btn" onClick={showPython} title="Open reusable Python workspace"><Sigma size={16}/><span>Python</span></button>
          <button type="button" className="v2-top-btn" onClick={()=>setJobsOpen(true)}
            aria-label="Open Jobs and downloads" title="Jobs and downloads">
            <Clock3 size={16}/><span>Jobs</span></button>
          <button type="button" className="v2-top-btn" onClick={()=>begin('guide')}
            aria-label="Open Help" title="Help and documentation">
            <BookOpen size={16}/><span>Help</span></button>
          <button type="button" className="v2-top-btn primary" onClick={()=>begin('journey')}>
            <Play size={15}/><span>New Study</span></button>
          <button title="Refresh workstation sources" aria-label="Refresh data" className="ws-icon"
            onClick={()=>void refresh()}><RefreshCw size={16}/></button>
        </div>
      </header>
      <JobsDrawer open={jobsOpen} onClose={()=>setJobsOpen(false)}
        onOpenFull={()=>begin('workspacejobs')}/>
      <GlobalSearchV2 open={searchOpen} onClose={()=>setSearchOpen(false)}
        onOpen={destination=>begin(destination)}/>
      <PythonWorkbench open={pythonOpen} onOpen={showPython} onClose={()=>setPythonOpen(false)} onStrategy={()=>begin('strategypython')} onNotebook={()=>{setPythonOpen(false);begin('notebooks')}} contextLabel={titles[tab]}/>
      <main className="ws-content">
        <div className={'ws-titlebar '+(
          ['mathematics','history','data','dataexplorer','workspace','chartstudio',
           'models','research','dhan','dataquality'].includes(tab)?
           'v2-titlebar-compact':'')}>
          <div><div className="ws-overline">LOCAL QUANTITATIVE RESEARCH WORKSTATION</div>
            <h1>{titles[tab]}</h1><p>{descriptions[tab]}</p></div>
          <div className="ws-title-actions">

            {(['strategies','strategyema','strategypython','strategybacktest'].includes(tab))&&
              <button className="ws-button secondary" onClick={()=>begin('data')}>
                <Database size={15}/> Data coverage</button>}
          </div>
        </div>
        {(()=>{
          const section=primarySections.find(group=>group.tabs.includes(tab))
          const visible=section?.navTabs||[]
          const extra=(section?.tabs||[]).filter(module=>!visible.includes(module))
          return visible.length>1?<nav className="ws-context-tabs"
              aria-label="Modules within selected research destination">
            <div className="ws-context-primary">
              {visible.map(module=><button type="button" key={module}
                aria-current={tab===module?'page':undefined}
                className={tab===module?'active':''} onClick={()=>begin(module)}>
                {titles[module]}</button>)}
            </div>
            {extra.length>0&&<details key={section?.id} className="ws-context-more">
              <summary aria-label={'More tools in '+section?.label}>
                {extra.includes(tab)?titles[tab]:'More tools'}
                <ChevronDown size={15}/>
              </summary>
              <div className="ws-context-extra" role="group"
                aria-label="Additional research tools">
                {extra.map(module=><button type="button" key={module}
                  aria-current={tab===module?'page':undefined}
                  className={tab===module?'active':''}
                  onClick={event=>{
                    event.currentTarget.closest('details')?.removeAttribute('open')
                    begin(module)
                  }}>
                  <span>{titles[module]}</span>
                  <ArrowRight size={14}/>
                </button>)}
              </div>
            </details>}
          </nav>:null
        })()}
        {deletePlan&&<div className="ws-delete-overlay">
          <section className="ws-delete-dialog" role="dialog" aria-modal="true"
            aria-label={'Delete dataset '+deletePlan.label}>
            <header>
              <div><span className="ws-overline">DATA LIBRARY · DELETE CONFIRMATION</span>
                <h2>Delete {deletePlan.label}?</h2></div>
              <button type="button" className="ws-icon" aria-label="Close deletion popup"
                disabled={busy} onClick={()=>setDeletePlan(null)}><X size={16}/></button>
            </header>
            <p className="ws-delete-intro">
              This will remove the dataset and <strong>{deletePlan.dependent_count} linked saved
              {deletePlan.dependent_count===1?' item':' items'}</strong> from QuantLab in one action.
              All of them will move to recoverable Trash.
            </p>
            <div className="ws-delete-summary">
              <span><strong>{deletePlan.dependent_count+1}</strong> total items to delete</span>
              <span><CheckCircle2 size={15}/> Shared raw Dhan history remains safe</span>
            </div>
            {deletePlan.dependent_items.length>0&&
              <div className="ws-delete-dependencies">
                <h3>These saved items will also be deleted</h3>
                <ul>{deletePlan.dependent_items.map(item=>
                  <li key={item.kind+':'+item.id}>
                    <strong>{item.title}</strong>
                    <small>{label(item.kind)} · {item.id}</small>
                  </li>)}</ul>
              </div>}
            {deletePlan.blocking_references.length>0&&
              <div className="ws-delete-blocked" role="alert">
                <h3>Some items cannot be moved safely</h3>
                <ul>{deletePlan.blocking_references.map((item,i)=>
                  <li key={item.kind+':'+item.id+':'+i}>
                    <strong>{item.title}</strong><small>{item.reason||item.id}</small>
                  </li>)}</ul>
                <p>Archive the dataset to hide it, or resolve the unsafe source before deleting.</p>
              </div>}
            <div className="ws-delete-actions">
              <button type="button" className="ws-button secondary"
                disabled={busy} onClick={()=>setDeletePlan(null)}>No, keep everything</button>
              <button type="button" className="ws-button ws-delete-confirm"
                disabled={busy||!deletePlan.can_delete_all}
                onClick={()=>trashDataset(deletePlan)}>
                <Trash2 size={15}/> Yes, delete dataset
                {deletePlan.dependent_count>0?' + '+deletePlan.dependent_count+' saved items':''}
              </button>
            </div>
            <p className="ws-delete-footnote">
              Deletion is recoverable; this action does not permanently erase files.
              Shared original market-data caches are never removed.
              <button type="button" disabled={busy}
                onClick={()=>archiveDataset(deletePlan)}>Archive instead</button>
            </p>
          </section>
        </div>}
        {notice&&<div role="status" className={'ws-notice '+(notice.error?'error':'')}><span>{notice.error?<CircleAlert size={17}/>:<CheckCircle2 size={17}/>}</span>{notice.text}<button onClick={()=>setNotice(null)} aria-label="Dismiss"><X size={16}/></button></div>}
        <Suspense fallback={<div className="ws-empty" role="status" aria-live="polite">
          <LoaderCircle size={18}/> Loading {titles[tab]}…
        </div>}>
        {(['trading','tradingchain','tradinganalytics','tradingdirectional','tradingdepth','tradingreplay',
            'tradingjournal','strategybacktest'].includes(tab)||
            (tab==='connections'&&connectionEditing))&&
          <TradingCockpit
            integrated
            selectedView={tab==='tradingreplay'?'replay':
              tab==='tradingjournal'?'journal':
              tab==='strategybacktest'?'strategy':
              tab==='connections'?'setup':'live'}
            initialOptionMode={tab==='tradinganalytics'?'analytics':tab==='tradingdirectional'?'directional':tab==='tradingchain'?'overview':undefined}
            focusLive={tab==='trading'?'signals':
              ['tradingchain','tradinganalytics','tradingdirectional'].includes(tab)?'options':
              tab==='tradingdepth'?'depth':undefined}
            onNavigateLiveView={view=>begin(({
              signals:'trading',options:'tradingchain',depth:'tradingdepth'
            } as const)[view])}
            onNavigateView={view=>begin(({
              live:'trading',replay:'tradingreplay',
              strategy:'strategybacktest',research:'strategypython',
              journal:'tradingjournal',setup:'connections',
            } as const)[view])}
          />}
        {tab==='tradingpaper'&&<PaperTradingWorkspace onOpenChain={()=>begin('tradingchain')} onOpenDepth={()=>begin('tradingdepth')}/>}
        {tab==='tradingspreads'&&<LiquiditySpreadsWorkspace
          onOpenRecording={()=>begin('recordingsettings')}
          onOpenReplay={()=>begin('tradingreplay')}/>}
        {tab==='connections'&&!connectionEditing&&
          <ConnectionsLandingV2 apiHealthy={Boolean(health?.ok)}
            tokenConfigured={Boolean(health?.dhan_token_configured)}
            onConfigure={()=>setConnectionEditing(true)}
            onRecording={()=>begin('recordingsettings')}
            onDiagnostics={()=>begin('diagnostics')}
            onData={()=>begin('data')}/>}
        {tab==='connections'&&connectionEditing&&
          <button type="button" className="ws-button secondary v2-connection-back"
            onClick={()=>setConnectionEditing(false)}>
            ← Back to Connections
          </button>}
        {tab==='strategies'&&<StrategyLibraryV2
          onEMA={()=>begin('strategyema')}
          onPython={()=>begin('strategypython')}
          onOptions={()=>begin('strategybacktest')}
          onData={()=>begin('data')}/>}
        {(['strategyema','strategypython'].includes(tab))&&
          <ResearchPythonLab integrated
            displayMode={tab==='strategyema'?'sweep':'python'}/>}
        {tab==='journey'&&<ResearchJourney datasets={datasets}
          selectedDataset={selectedDataset} onSelectDataset={setSelectedDataset}
          onDataChanged={refresh} onOpenData={()=>begin('data')}
          onOpenDhan={()=>begin('dhan')} onOpenWorkspace={()=>begin('workspace')}
          onOpenGuide={()=>begin('guide')} onOpenExperiments={()=>begin('research')}
          onOpenModels={()=>begin('mathematics')} onOpenResults={()=>begin('history')}/>}
        {tab==='overview'&&<>
          <V2HomeLaunchers
            onStrategy={()=>begin('strategyema')}
            onModel={()=>begin('mathematics')}
            onData={()=>begin('dhan')}/>
          <QuickPageNote title="Read-only market intelligence"
            description="Market collection continues in the local backend. No broker orders or unobserved price series are generated."
            ><button className="v2-secondary" type="button" onClick={()=>begin('trading')}>
              Open live market <ArrowRight size={15}/></button></QuickPageNote>
          <div className="ws-metrics-grid"><Metric label="Market data library" value={datasets.some(d=>d.id==='dhan_shared')?'1':'—'} caption="One canonical set of downloaded stock prices"/><Metric label="Completed runs" value={String(runs.length)} caption="Stored locally on disk"/><Metric label="DhanHQ data access" value={dhan?.token_configured?'SET':'NOT SET'} caption="Read-only market data"/><Metric label="Python computation" value={health?.ok?'ONLINE':'OFFLINE'} caption="127.0.0.1:8765" highlight/></div>
          <div className="ws-grid two-thirds"><Card title="Portfolio research performance" extra={classification}>{chart??<Empty title="No historical run selected" onAction={()=>begin('research')} action="Configure experiment">Run the research engine to generate actual saved series and metrics.</Empty>}</Card><Card title="Latest research snapshot">{detail?<><div className="ws-overview-stat"><span>Strategy CAGR</span><strong>{percent(weighted(metric,'strategy_cagr'))}</strong></div><div className="ws-overview-stat"><span>Max drawdown</span><strong>{percent(weighted(metric,'max_drawdown'))}</strong></div><div className="ws-overview-stat"><span>Tracking error</span><strong>{percent(weighted(metric,'tracking_error'))}</strong></div><div className="ws-overview-stat"><span>Sample window</span><strong>{detail.meta.first_price_date?.slice(0,7)}–{detail.meta.last_price_date?.slice(0,7)}</strong></div><button className="ws-textlink" onClick={()=>begin('history')}>Inspect full run <ArrowRight size={15}/></button></>:<Empty title="Nothing to report">No metrics will appear until a Python experiment completes.</Empty>}</Card></div>
          <div className="ws-grid halves"><Card title="Market library & research inputs" extra={<button className="ws-textlink" onClick={()=>begin('data')}>Manage <ArrowRight size={13}/></button>}><div className="ws-item-list">{everydaySources.slice(0,5).map(d=><button className="ws-dataset-row" key={d.id} onClick={()=>{setSelectedDataset(d.id);begin('data')}}><Database size={17}/><span><strong>{d.label}</strong><small>{d.basis}</small></span><Tag tone={d.ready?'good':'warn'}>{d.ready?'READY':'INCOMPLETE'}</Tag></button>)}{everydaySources.length===0&&<p className="ws-caption">No market sources found.</p>}</div></Card><Card title="Recent experiments" extra={<button className="ws-textlink" onClick={()=>begin('history')}>View history <ArrowRight size={13}/></button>}><div className="ws-item-list">{runs.slice(0,5).map(r=><button className="ws-dataset-row" key={r.id} onClick={()=>{setSelectedRun(r.id);begin('history')}}><Clock3 size={17}/><span><strong>{r.name}</strong><small>{r.id} · {date(r.created_utc)}</small></span><Tag tone={r.dataset_kind==='synthetic'?'warn':'blue'}>{r.dataset_kind}</Tag></button>)}{runs.length===0&&<p className="ws-caption">No completed runs yet.</p>}</div></Card></div>
        </>}
        {(['data','dhan','datadownloads'].includes(tab))&&
          <MarketDataWorkspace key="v2-one-canonical-market-library"
            initialPage="datasets"
            activePage={tab==='data'?'datasets':tab==='dhan'?'get':'downloads'}
            integrated datasets={datasets}
            onDataChanged={refresh} onSelectDataset={setSelectedDataset}
            onOpenModels={()=>begin('mathematics')}
            onRequestDelete={id=>{const d=datasets.find(item=>item.id===id)
              if(d)inspectDatasetDeletion(d)}}/>}
        {tab==='data'&&<>
          <details className="ws-tri-advanced ws-data-advanced"><summary>Advanced datasets · TRI import, ZIPs, archived items and source audits</summary>
          <Card title="Your datasets" className="ws-data-library-card">
            <p className="ws-caption">Choose a dataset to use, or delete an old one.
              If saved work depends on it, the confirmation shows everything that will
              be deleted together. Shared original Dhan data stays protected.</p>
            <div className="ws-dataset-manage-list">
              {datasets.map(d=><div className="ws-dataset-manage-row" key={d.id}>
                <div><strong>{d.label}</strong>
                  <small>{d.id} · {d.ready?'Input files available': 'Incomplete — '+(d.missing.join(', ')||'missing inputs')}</small>
                </div>
                <Tag tone={d.ready?'good':'warn'}>{d.ready?'FILES READY':'INCOMPLETE'}</Tag>
                <button className="ws-button" type="button"
                  onClick={()=>{setSelectedDataset(d.id);window.scrollTo({top:0,behavior:'smooth'})}}>
                  Use
                </button>
                {(d.id.startsWith('upload_')||d.id.startsWith('dhan_batch_'))?
                  <button type="button" className="ws-button ws-delete" disabled={busy}
                    aria-label={'Delete dataset '+d.label} onClick={()=>inspectDatasetDeletion(d)}>
                    <Trash2 size={14}/> Delete
                  </button>:<small className="ws-protected-label">Protected source</small>}
              </div>)}
            </div>
            <details className="ws-tri-advanced ws-dataset-archive">
              <summary>Archived datasets ({archivedDatasets.length}) · restore to Data Library</summary>
              {archivedDatasets.length===0?<p className="ws-caption">No archived datasets.</p>:
                <div className="ws-dataset-manage-list">{archivedDatasets.map(d=>
                  <div className="ws-dataset-manage-row" key={d.id}>
                    <div><strong>{d.title}</strong><small>{d.id} · Saved work remains available</small></div>
                    <button type="button" className="ws-button secondary" disabled={busy}
                      onClick={()=>unarchiveDataset(d.id)}><RotateCcw size={14}/> Unarchive</button>
                  </div>)}</div>}
            </details>
            <details className="ws-tri-advanced ws-dataset-trash">
              <summary>Deleted datasets ({deletedDatasets.length}) · restore or permanently delete</summary>
              {deletedDatasets.length===0?<p className="ws-caption">No deleted datasets.</p>:
                <div className="ws-dataset-manage-list">{deletedDatasets.map(d=>
                  <div className="ws-dataset-manage-row" key={d.id}>
                    <div><strong>{d.title}</strong><small>{d.id}</small></div>
                    <button type="button" className="ws-button" disabled={busy}
                      onClick={()=>restoreDataset(d.id)}><RotateCcw size={14}/> Restore</button>
                    <button type="button" className="ws-button ws-delete" disabled={busy}
                      onClick={()=>purgeDataset(d.id)}><Trash2 size={14}/> Delete permanently</button>
                  </div>)}</div>}
            </details>
          </Card>
          <div className="ws-grid halves ws-data-setup"><Card title="Add or import data"><p className="ws-caption">Download prices, check an NSE source, or import a prepared research ZIP.
              Existing downloads and your saved TRI are reused where available.</p><div className="ws-actions"><button className="ws-button primary" onClick={()=>begin('dhan')}><Database size={15}/> Download market data</button><button className="ws-button secondary" onClick={()=>begin('nse')}><Search size={15}/> NSE Sources · official MCP</button><details className="ws-tri-advanced ws-synthetic-option">
                <summary>Advanced: create synthetic test data</summary>
                <p className="ws-caption">Artificial examples are only for learning and testing calculations,
                  not historical investment research.</p>
                <button className="ws-button" disabled={busy} onClick={synthetic}>
                  <Beaker size={15}/> Create synthetic test dataset</button>
              </details><label className={'ws-button secondary '+(busy?'disabled':'')}><Upload size={15}/> Import research ZIP<input hidden type="file" accept=".zip" disabled={busy} onChange={e=>{const f=e.target.files?.[0];if(f)void upload(f);e.target.value=''}}/></label></div><p className="ws-caption">ZIP requires prices.csv, membership.csv and benchmark.csv; optionally fundamentals.csv, sectors.csv and corporate_actions.csv. Import does not certify the data.</p></Card><Card title="Selected dataset" extra={dataPicker}>{dataset?<><div className="ws-selected-dataset"><strong>{dataset.label}</strong><Tag tone={dataset.ready?'good':'warn'}>{dataset.ready?'FILES AVAILABLE':'INCOMPLETE'}</Tag></div>
          {!dataset.ready&&dataset.has_prices&&<div className="ws-complete-guide">
            <div className="ws-complete-heading">
              <strong>Complete the missing dataset inputs</strong>
              <span>{dataset.missing.includes('benchmark.csv')?'1 essential input missing':'Check required data below'}</span>
            </div>
            {dataset.missing.includes('benchmark.csv')?<div className="ws-tri-import">
              <p><b>Missing: Official NIFTY total-return benchmark.</b> Your stock prices and
                historical membership are already saved. Don't download those again.</p>
              <a href="https://www.niftyindices.com/reports/historical-data"
                target="_blank" rel="noreferrer">Get NIFTY Total Returns Index levels from the exchange ↗</a>
              <p>Choose an original TRI levels CSV covering the stock period,
                <b> including the prior month.</b> QuantLab automatically matches daily TRI
                observations to your saved stock dates—no manual date editing or repeated
                stock downloads. A Dhan spot price index is not TRI.</p>
              <label className="ws-file-input"><span>1. Choose TRI CSV</span>
                <input key={dataset.id} aria-label="Choose NIFTY TRI levels CSV" type="file" accept=".csv,text/csv"
                  onChange={e=>{setTriFile(e.target.files?.[0]||null)}}/>
                {triFile&&<small>Selected: {triFile.name}</small>}
              </label>
              <details className="ws-tri-advanced"><summary>CSV column names (change only if different)</summary>
                <label>Date column <input aria-label="TRI date column" value={triDateColumn}
                  onChange={e=>setTriDateColumn(e.target.value)}/></label>
                <label>TRI index level column <input aria-label="TRI level column" value={triLevelColumn}
                  onChange={e=>setTriLevelColumn(e.target.value)}/></label>
                <label>Index return convention <select aria-label="TRI return convention"
                    value={triConvention} onChange={e=>setTriConvention(e.target.value)}>
                    <option value="gross_total_return">Gross total return</option>
                    <option value="net_total_return">Net total return</option>
                  </select></label>
              </details>
              <label className="ws-tri-ack"><input type="checkbox" checked={triConfirmed}
                onChange={e=>setTriConfirmed(e.target.checked)}/>
                I confirm this authorized CSV contains original total-return <b>levels</b>, not price-index closes.
              </label>
              <button className="ws-button primary" type="button"
                disabled={busy||!triFile||!triConfirmed} onClick={()=>void attachTri()}>
                {busy?<LoaderCircle size={14}/>:<Upload size={14}/>} 2. Validate and add TRI benchmark
              </button>
              <p className="ws-caption">QuantLab creates a <b>new</b> dataset version, verifies exact monthly
                alignment, and leaves the original dataset unchanged. Adding TRI does not automatically verify
                constituent dividends, corporate events or research publication rights.</p>
            </div>:<p className="ws-caption">The dataset is missing required monthly price or
              historical membership records. Use Download market data to prepare them.</p>}
            <p className="ws-caption"><b>Optional inputs:</b> fundamentals.csv for Value/Quality/Size/Yield
              factors; sectors.csv for sector constraints. These are not required for price-only
              momentum and volatility research.</p>
          </div>}
          {dataset.benchmark_kind==='price_index_spot_only'&&<div className="ws-warning">
            <p>PRICE-INDEX BENCHMARK ONLY — Dhan NIFTY spot data does not include reinvested dividends. Files may be structurally complete for exploratory comparisons, but this is NOT an independently verified total-return benchmark or research certification. Stock splits, dividends and corporate actions still require review.</p>
          </div>}<details className="ws-tri-advanced ws-data-advanced">
              <summary>View file list, source evidence and technical details</summary>
              <p className="ws-caption">{dataset.basis}</p><div className="ws-checklist">{['prices.csv','daily_prices.csv','membership.csv','benchmark.csv','fundamentals.csv','sectors.csv'].map(name=><div key={name}>{dataset.files.includes(name)?<Check size={16}/>:<CircleAlert size={16}/>}<span>{name}</span><small>{dataset.files.includes(name)?'PRESENT':(['daily_prices.csv','fundamentals.csv','sectors.csv'].includes(name)?'OPTIONAL':'MISSING')}</small></div>)}</div></details><div className="ws-actions"><button className="ws-button secondary" disabled={!dataset.ready||busy} onClick={()=>execute(()=>request<Dict>('/datasets/'+dataset.id+'/audit'),r=>{notify('Internal consistency audit completed; external validation remains required.');setAuditResult(r)})}>Run data audit</button><button className="ws-button primary" onClick={()=>begin('research')}>Use in research <ArrowRight size={14}/></button></div></>:<Empty title="Choose a dataset">Upload verified input files or create a synthetic software demonstration.</Empty>}</Card></div>
          {auditResult&&<Card title="Internal consistency audit"><div className="ws-data-audit">{Object.entries(auditResult).filter(([k])=>k!=='warnings').map(([k,v])=><div key={k}><span>{label(k)}</span><strong>{typeof v==='object'?JSON.stringify(v):String(v)}</strong></div>)}</div>{Array.isArray(auditResult.warnings)&&<div className="ws-warning">{auditResult.warnings.map((w,i)=><p key={i}>• {String(w)}</p>)}</div>}</Card>}
          <details className="ws-tri-advanced ws-dataset-advanced">
            <summary>Advanced · Dataset source metadata and technical comparison</summary>
            <p className="ws-caption">These fields are useful for technical audits but not required
              to choose, use, or delete a dataset.</p>
            <Table rows={datasets.map(d=>({name:d.label,kind:d.kind,ready:d.ready,
              benchmark:d.benchmark_kind==='price_index_spot_only'?'PRICE INDEX (not TRI)':d.benchmark_kind||'missing',
              daily_prices:d.has_daily_prices?'yes':'no',
              source_resolution:d.source_interval_minutes===null?'daily':d.source_interval_minutes?d.source_interval_minutes+' min':'unreported',
              missing:d.missing.join(', ')||'none',basis:d.basis}))}/>
          </details>

        </details></>}
        {tab==='dataexplorer'&&<DataManager initialSection="explorer" integrated
          onSelectDataset={setSelectedDataset} onChanged={refresh}
          onOpenDhan={()=>begin('dhan')} onOpenModels={()=>begin('mathematics')}/>}
        {tab==='dataquality'&&<>
          <ResearchWorkspace key="v2-data-quality"
          initialPage="quality" integrated datasets={datasets}
          selectedDataset={selectedDataset} onSelectDataset={setSelectedDataset}
          onDataChanged={refresh} onOpenDhan={()=>begin('dhan')}
          onOpenModels={()=>begin('mathematics')}/>
          <details className="v2-advanced-links">
            <summary>Source audits, mathematical evidence, learning validation and NSE documents</summary>
            <div className="v2-action-row">
              <button className="v2-secondary" onClick={()=>begin('evidence')}>
                Evidence & ML <ArrowRight size={14}/></button>
              <button className="v2-secondary" onClick={()=>begin('nse')}>
                NSE Source Evidence <ArrowRight size={14}/></button>
            </div>
          </details>
        </>}
        {tab==='nse'&&<NSESourceAssistant datasetId={selectedDataset}
          onOpenDhan={()=>begin('dhan')} onOpenData={()=>begin('data')}/>}
        {(tab==='workspace'||tab==='chartstudio'||tab==='workspacejobs'||
          tab==='projects')&&<ResearchWorkspace key={tab} integrated
          initialPage={tab==='projects'?'projects':
            tab==='chartstudio'?'plots':
            tab==='workspacejobs'?'jobs':'compare'} datasets={datasets}
          selectedDataset={selectedDataset} onSelectDataset={setSelectedDataset}
          onDataChanged={refresh} onOpenDhan={()=>begin('dhan')}
          onOpenModels={()=>begin('models')}/>}

        {tab==='notebooks'&&<ResearchNotebook/>}
        {tab==='projects'&&<div className="ws-actions"><button type="button" className="ws-button primary" onClick={()=>begin('notebooks')}>Open research notebooks</button></div>}
        {tab==='projects'&&<details className="v2-advanced-links">
          <summary>Advanced project resource library, archive and Trash management</summary>
          <div className="v2-action-row">
            <button className="v2-secondary" onClick={()=>begin('resourcebrowser')}>
              Browse saved resource records <ArrowRight size={14}/></button>
          </div>
        </details>}
        {tab==='research'&&<>
          <IndexBuilderWorkspace config={config} onConfigChange={setConfig}
            datasets={datasets} selectedDataset={selectedDataset}
            onSelectDataset={setSelectedDataset} busy={busy}
            jobActive={Boolean(job&&['queued','running'].includes(job.status))}
            onRun={startRun}
            onOpenData={()=>begin('data')} onGetData={()=>begin('dhan')}
            onOpenNse={()=>begin('nse')} onOpenResults={()=>begin('history')}
            onOpenStudio={()=>begin('indexstudio')}/>
          <details className="idx-advanced" aria-label="Advanced historical validation and source preparation">
            <summary>Historical source preparation, PIT validation and frozen evaluation</summary>
          <HistoricalValidationPanel datasetId={selectedDataset} config={config}
            hasDailyPrices={!!dataset?.has_daily_prices}
            onDataCreated={id=>{setSelectedDataset(id);void refresh();
              notify('New version created from original daily prices and dated events; evidence remains unverified.')}}
            onOpenData={()=>begin('data')} onOpenDhan={()=>begin('dhan')}
            onJobQueued={id=>{setJob({id,kind:'frozen_evaluation',status:'queued'});
              notify('Single-use frozen experiment queued; its result receipt will be checked.') }}/>
          </details>
          {job&&<Card title="Current job"><div className="ws-job-row"><Tag tone={job.status==='error'?'bad':job.status==='complete'?'good':'blue'}>{job.status.toUpperCase()}</Tag><span>{job.kind}</span><small>{job.error||job.id}</small></div></Card>}
        </>}
        {tab==='history'&&<ResultsStudio integrated
          selectedIndexRunId={selectedRun}
          selectedModelRunId={focusedModelRun||undefined}
          onSelectIndexRun={setSelectedRun}
          onModels={()=>begin('mathematics')}
          onExperiments={()=>begin('research')}
          onWorkspace={()=>begin('workspace')}
          onData={()=>begin('data')}
          onReports={()=>begin('reports')}/>}
        {tab==='factors'&&<>{withRun(<div className="ws-grid halves"><Card title="Factor rank information coefficient"><Table rows={detail?.rank_ic||[]}/></Card><Card title="Portfolio factor exposures"><Table rows={detail?.factor_exposures||[]}/></Card></div>)}</>}
        {tab==='construction'&&<>{withRun(<div className="ws-grid halves"><Card title="Current allocation"><BarRows rows={detail?.latest_weights||[]}/></Card><Card title="Concentration history"><Table rows={detail?.concentration||[]}/></Card></div>)}</>}
        {tab==='comparisons'&&<>{panel('methodologies','Methodology comparison outputs')}{panel('cost_sensitivity','Transaction cost sensitivity')}</>}
        {tab==='rolling'&&<>{panel('rolling','Rolling relative return and tracking metrics')}</>}
        {tab==='risk'&&<>{panel('concentration','Risk concentration over time')}{panel('rolling','Rolling relative risk metrics')}</>}
        {tab==='robustness'&&<>{panel('robustness','Parameter sensitivity and robustness grid')}</>}
        {tab==='visual'&&<>{withRun(<Card title="Cumulative strategy / benchmark path" extra={classification}>{chart}</Card>)}{panel('rank_ic','Cross-sectional factor validation')}</>}
        {tab==='mathematics'&&<>
          <ModelLaboratory
            section="mathematics" enableCustomModels datasets={datasets} selectedDataset={selectedDataset}
            onSelectDataset={setSelectedDataset} onOpenGuide={()=>begin('guide')}
            onDataChanged={refresh}
            onOpenWorkspace={()=>begin('workspace')} onOpenData={()=>begin('data')}
            onOpenResults={runId=>{setFocusedModelRun(runId||'');begin('history')}}/>
          <details className="v2-advanced-links">
            <summary>Specialized model diagnostics · factor exposures, risk, concentration & validation</summary>
            <div className="v2-action-row">
              {([
                ['factors','Factor Research'],['construction','Portfolio Construction'],
                ['risk','Risk Attribution'],['rolling','Rolling Validation'],
                ['robustness','Robustness & Sensitivity'],
              ] as const).map(([route,title])=><button key={route}
                className="v2-secondary" onClick={()=>begin(route)}>{title}
                <ArrowRight size={14}/></button>)}
              <button className="v2-secondary" onClick={()=>begin('modelgrids')}>
                Guided Model Grids <ArrowRight size={14}/></button>
              <button className="v2-secondary" onClick={()=>begin('indexstudio')}>
                Index Research Studio <ArrowRight size={14}/></button>
            </div>
          </details>
        </>}
        {(['models','modelgrids','indexstudio','evidence','resourcebrowser'].includes(tab))&&
          <ResearchWorkspace key={'v2-tool-'+tab}
            initialPage={tab==='models'?'automation':
              tab==='modelgrids'?'guided':
              tab==='indexstudio'?'scholar':
              tab==='evidence'?'integrity':'library'}
            integrated datasets={datasets}
            selectedDataset={selectedDataset} onSelectDataset={setSelectedDataset}
            onDataChanged={refresh} onOpenDhan={()=>begin('dhan')}
            onOpenModels={()=>begin('mathematics')}/>}
        {tab==='guide'&&<ResearchGuide onNavigate={route=>begin(route as Tab)}/>}
        {tab==='reports'&&<>{withRun(<Card title="Generate reproducible research report"><p className="ws-caption">Generate an offline HTML report and PDF draft from selected saved Python run artifacts. Synthetic demonstrations are explicitly labeled.</p><div className="ws-actions"><button className="ws-button primary" disabled={!selectedRun||busy} onClick={downloadReport}><FileText size={15}/> Build HTML + PDF</button></div><div className="ws-artifact-list">{(detail?.artifacts||[]).map(name=><a key={name} href={'/api/runs/'+encodeURIComponent(selectedRun)+'/files/'+encodeURIComponent(name)} download><FileArchive size={16}/><span>{name}</span><ArrowDownToLine size={14}/></a>)}</div></Card>)}</>}
        {tab==='recordingsettings'&&<div className="v2-layout-section">
          <QuickPageNote title="Automatic BANKNIFTY CE/PE recording"
            description="Configure read-only original 20-level capture. Collector processes remain active regardless of which QuantLab page is open."/>
          <AutoDepthRecorder onOpenSaved={()=>begin('tradingreplay')}/>
        </div>}
        {tab==='storage'&&<DataManager initialSection="database" integrated
          onSelectDataset={setSelectedDataset} onChanged={refresh}
          onOpenDhan={()=>begin('dhan')} onOpenModels={()=>begin('mathematics')}/>}
        {tab==='pythonenvironment'&&<PythonEnvironment/>}
        {tab==='custommodels'&&<CustomModelWorkspace datasets={datasets} selectedDataset={selectedDataset}/>}
        {(['pythonmonitors','custommodels','customscanners'].includes(tab))&&<PythonMonitors key={tab} initialKind={tab==='custommodels'?'model':tab==='customscanners'?'scanner':undefined} onEdit={id=>{showPython();if(id)window.dispatchEvent(new CustomEvent('quantlab:open-saved-script',{detail:id}))}}/>}
        {tab==='preferences'&&<SettingsPreferencesV2/>}
        {tab==='diagnostics'&&<DiagnosticsV2 onRepair={()=>begin('settings')}
          onData={()=>begin('dataquality')}/>}
        {tab==='settings'&&<div className="ws-grid halves"><Card title="Backend and privacy"><div className="ws-data-audit"><div><span>API address</span><strong>127.0.0.1:8765</strong></div><div><span>Frontend address</span><strong>127.0.0.1:5173</strong></div><div><span>Data directory</span><strong>data/ (Git-ignored)</strong></div><div><span>Run artifacts</span><strong>results/workstation_runs/</strong></div><div><span>Authentication</span><strong>Loopback-only; not for public exposure</strong></div><div><span>Broker trading</span><strong>DISABLED</strong></div><div><span>Dhan token</span><strong>{health?.dhan_token_configured?'CONFIGURED (HIDDEN)':'MISSING'}</strong></div></div></Card><Card title="Integrity controls"><div className="ws-rule"><ShieldCheck size={18}/> Local data import, explicit dataset status, safe path allowlists, no broker order operations, no credential output, and no historical-performance fabrication.</div><p className="ws-caption">This is a local research environment, not an authenticated public server. Do not expose port 8765 on a network or deploy it as-is.</p><button className="ws-button secondary" onClick={()=>void refresh()}><RefreshCw size={16}/> Refresh engine status</button></Card></div>}
        </Suspense>
        <footer className="ws-footer"><span>QUANTLAB / RESEARCH WORKSTATION</span><span>LOCAL ENGINE · HISTORICAL CLAIMS REQUIRE EXTERNAL VALIDATION</span><span>© PERSONAL RESEARCH</span></footer>
      </main>
      <div className="ql-statusbar" aria-label="Workstation status"><button type="button" onClick={()=>begin('diagnostics')}>Engine: {health?.ok?'Online':health?'Offline':'Checking'}</button><button type="button" onClick={()=>begin('connections')}>Dhan: {dhan?.token_configured?'Token configured':'Not confirmed'}</button><span>Read-only research · no orders</span><button type="button" onClick={()=>setJobsOpen(true)}>Jobs &amp; downloads</button></div>
    </div>
  </div>
}
export default App
