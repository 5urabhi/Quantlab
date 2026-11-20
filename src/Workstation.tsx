import {lazy, Suspense, useCallback, useEffect, useMemo, useState} from 'react'
import {
  Activity, ArrowDownToLine, ArrowRight, BarChart3, Beaker, BookOpen, Check,
  CheckCircle2, ChevronRight, CircleAlert, Clock3, Database, FileArchive,
  FileText, FlaskConical, Gauge, LoaderCircle,
  LockKeyhole, Menu, Play, RefreshCw, Settings2,
  ShieldCheck, Sigma, Upload, Trash2, RotateCcw, Search, X, TrendingUp
} from 'lucide-react'
import './workstation.css'
import {RecorderBadge,JobsDrawer,V2HomeLaunchers,StrategyLibraryV2,SettingsPreferencesV2,DiagnosticsV2,QuickPageNote} from './QuantLabV2Components'
import ResearchPythonLab from './ResearchPythonLab'
import AutoDepthRecorder from './AutoDepthRecorder'
import DataManager from './DataManager'
const MarketDataWorkspace = lazy(() => import('./MarketDataWorkspace'))
const TradingCockpit = lazy(() => import('./TradingCockpit'))
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
  'overview'|'trading'|'tradingchain'|'tradingdepth'|'tradingreplay'|'tradingjournal'|
  'strategies'|'strategyema'|'strategypython'|'strategybacktest'|
  'mathematics'|'models'|'research'|'factors'|'construction'|'risk'|'rolling'|'robustness'|
  'data'|'dhan'|'dataexplorer'|'dataquality'|'datadownloads'|'nse'|
  'history'|'workspace'|'chartstudio'|'comparisons'|'visual'|'workspacejobs'|
  'projects'|'reports'|'settings'|'connections'|'recordingsettings'|
  'storage'|'preferences'|'diagnostics'|'guide'|'journey'
type PrimarySection={id:Tab;label:string;icon:typeof Activity;tabs:Tab[];navTabs:Tab[]}
const primarySections:PrimarySection[]=[
  {id:'overview',label:'Home',icon:Gauge,tabs:['overview'],navTabs:['overview']},
  {id:'trading',label:'Trading',icon:Activity,
    tabs:['trading','tradingchain','tradingdepth','tradingreplay','tradingjournal'],
    navTabs:['trading','tradingchain','tradingdepth','tradingreplay','tradingjournal']},
  {id:'strategies',label:'Strategies',icon:TrendingUp,
    tabs:['strategies','strategyema','strategypython','strategybacktest'],
    navTabs:['strategies','strategyema','strategypython','strategybacktest']},
  {id:'mathematics',label:'Models',icon:Sigma,
    tabs:['mathematics','models','research','factors','construction','risk','rolling','robustness','journey'],
    navTabs:['mathematics','research','models']},
  {id:'data',label:'Data Center',icon:Database,
    tabs:['data','dhan','dataexplorer','dataquality','datadownloads','nse'],
    navTabs:['data','dhan','dataexplorer','dataquality','datadownloads']},
  {id:'history',label:'Results & Charts',icon:BarChart3,
    tabs:['history','workspace','chartstudio','comparisons','visual','workspacejobs'],
    navTabs:['history','workspace','chartstudio']},
  {id:'projects',label:'Projects',icon:BookOpen,
    tabs:['projects','reports'],navTabs:['projects','reports']},
  {id:'connections',label:'Settings',icon:Settings2,
    tabs:['connections','recordingsettings','storage','preferences','diagnostics','settings','guide'],
    navTabs:['connections','recordingsettings','storage','preferences','diagnostics']},
]
const titles:Record<Tab,string>={
  overview:'Home',trading:'Live Market',tradingchain:'Option Chain',
  tradingdepth:'20-Level Order Book',tradingreplay:'Market Replay',
  tradingjournal:'Trade Journal',strategies:'Strategy Library',
  strategyema:'EMA Explorer',strategypython:'Python Editor',
  strategybacktest:'BANKNIFTY Backtests',
  mathematics:'Model Catalog',models:'Advanced Mathematical Models',
  research:'Index Builder',factors:'Factor Research',
  construction:'Portfolio Construction',risk:'Risk Attribution',
  rolling:'Rolling Validation',robustness:'Robustness & Sensitivity',
  data:'Market Library',dhan:'Get Market Data',
  dataexplorer:'Data Explorer',dataquality:'Quality & Coverage',
  datadownloads:'Downloads',nse:'NSE Source Evidence',
  history:'All Research Results',workspace:'Compare Runs',
  chartstudio:'Chart Studio',comparisons:'Index Comparison',
  visual:'Historical Charts',workspacejobs:'Research Job History',
  projects:'My Projects & Notebooks',reports:'Research Reports',
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
  tradingreplay:'Explore recorded BANKNIFTY, option quotes and original market-depth observations.',
  tradingjournal:'Review manually entered fills and prospective signal accuracy separately.',
  strategies:'Choose a strategy, test real index signals, then study historical CE/PE contracts.',
  strategyema:'Test one EMA pair, chosen combinations or all 11,026 valid pairs.',
  strategypython:'Paste, run and save isolated Python research without interrupting Dhan capture.',
  strategybacktest:'Compare directional signal timing and original-contract CE/PE paper P&L.',
  mathematics:'Choose stochastic, volatility, options, risk and portfolio mathematical models.',
  models:'Explore advanced source-backed and theoretical model families.',
  research:'Construct, backtest and validate factor-based equity indices.',
  factors:'Inspect real saved factor ranking and exposure output.',
  construction:'Inspect constituent weights, concentration and rebalance consequences.',
  risk:'Measure portfolio concentration and rolling risk on archived runs.',
  rolling:'Use rolling time windows on saved historical index results.',
  robustness:'Study parameter stability and sensitivity in saved experiments.',
  data:'Browse one canonical library of market instruments and downloaded observations.',
  dhan:'Choose instruments and acquire only missing source-backed history.',
  dataexplorer:'Inspect market data rows, original vendor files and source fields.',
  dataquality:'Check completeness, duplicate data and market-data provenance.',
  datadownloads:'Review downloads and source-repair progress.',
  nse:'Inspect official NSE evidence and source provenance.',
  history:'Search and interpret saved mathematical and strategy research results.',
  workspace:'Overlay comparable saved runs and inspect differences.',
  chartstudio:'Build interactive two- and three-dimensional research figures.',
  comparisons:'Review historical methodology and transaction-cost comparisons.',
  visual:'Inspect saved source-backed historical return and factor charts.',
  workspacejobs:'Inspect research and acquisition job history.',
  projects:'Save reproducible research in projects, notebooks and linked run references.',
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
const factors=[['momentum','Momentum'],['low_volatility','Low volatility'],['value','Value'],['quality','Quality'],['size','Size']] as const
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
function EquityChart({rows,caption='Strategy vs benchmark',height=300}:{rows:Dict[];caption?:string;height?:number}){
  type View='wealth'|'excess'|'drawdown'
  const [view,setView]=useState<View>('wealth')
  const [hover,setHover]=useState<number|null>(null)
  const points=useMemo(()=>{
    let strategy=1,benchmark=1,strategyHigh=1,benchmarkHigh=1
    return rows.flatMap(r=>{
      const sr=Number(r.strategy_net),br=Number(r.benchmark)
      if(!Number.isFinite(sr)||!Number.isFinite(br)||sr<=-1||br<=-1)return []
      strategy*=1+sr;benchmark*=1+br
      strategyHigh=Math.max(strategyHigh,strategy)
      benchmarkHigh=Math.max(benchmarkHigh,benchmark)
      return [{
        date:String(r.date||''),strategy,benchmark,
        excess:(sr-br)*100,
        strategyDrawdown:(strategy/strategyHigh-1)*100,
        benchmarkDrawdown:(benchmark/benchmarkHigh-1)*100,
      }]
    })
  },[rows])
  if(points.length<2)return <Empty title="Awaiting observed return series">
    A saved backtest needs at least two valid strategy and benchmark returns.
    Demo or missing returns are never filled in.
  </Empty>
  const read=(p:(typeof points)[number],which:'strategy'|'benchmark')=>
    view==='wealth'?p[which]:view==='drawdown'?
      which==='strategy'?p.strategyDrawdown:p.benchmarkDrawdown:p.excess
  const values=points.flatMap(p=>view==='excess'?[p.excess]:[read(p,'strategy'),read(p,'benchmark')])
  const low=Math.min(...values,...(view==='wealth'?[]:[0]))
  const high=Math.max(...values,...(view==='wealth'?[]:[0]))
  const pad=Math.max(.0001,(high-low)*.08)
  const floor=low-pad,ceil=high+pad,range=ceil-floor
  const left=65,right=935,top=29,bottom=238,width=right-left
  const xAt=(i:number)=>left+(i/(points.length-1))*width
  const yAt=(value:number)=>bottom-(value-floor)/range*(bottom-top)
  const path=(key:'strategy'|'benchmark')=>points.map((p,i)=>
    (i===0?'M':'L')+xAt(i).toFixed(2)+' '+yAt(read(p,key)).toFixed(2)).join(' ')
  const selected=hover!==null?points[hover]:null
  const valueLabel=(n:number)=>view==='wealth'?n.toFixed(3)+'×':n.toFixed(2)+'%'
  const whichLabel=view==='drawdown'?'Drawdown':view==='excess'?'Monthly excess return':'Cumulative wealth'
  const captionText=view==='wealth'?
    'Normalized to 1.00× at the first valid month; from saved Python returns.':
    view==='drawdown'?'Drawdown from the previous observed cumulative peak; negative means underwater.':
      'Monthly net strategy return minus benchmark return, in percentage points.'
  return <div className="ws-chart ws-interactive-chart">
    <div className="ws-chartheader">
      <span>{caption}</span>
      <div className="ws-chart-views" role="group" aria-label="Performance graph type">
        {([['wealth','Growth line'],['excess','Monthly difference'],['drawdown','Drawdown area']] as const)
          .map(([id,name])=><button type="button" key={id}
            className={view===id?'active':''} aria-pressed={view===id}
            onClick={()=>{setView(id);setHover(null)}}>{name}</button>)}
      </div>
    </div>
    <div className="ws-chart-legend">
      <span>{whichLabel}</span>
      {view!=='excess'&&<span><i className="ws-dot mint"/> Strategy <i className="ws-dot gold"/> Benchmark</span>}
      {view==='excess'&&<span>Mint = outperformance · Amber = underperformance</span>}
    </div>
    <svg viewBox="0 0 980 280" preserveAspectRatio="none" style={{height}}
      className="ws-interactive-svg" tabIndex={0} role="img"
      aria-label={whichLabel+' from saved return observations. Hover for values, or use arrow keys.'}
      onMouseMove={event=>{
        const rect=event.currentTarget.getBoundingClientRect()
        if(!rect.width)return
        const relative=(event.clientX-rect.left)/rect.width*980
        setHover(Math.max(0,Math.min(points.length-1,Math.round(
          (relative-left)/width*(points.length-1)
        ))))
      }}
      onMouseLeave={()=>setHover(null)}
      onFocus={()=>setHover(points.length-1)}
      onBlur={()=>setHover(null)}
      onKeyDown={event=>{
        if(event.key==='ArrowLeft'||event.key==='ArrowRight'){
          event.preventDefault()
          setHover(v=>Math.max(0,Math.min(points.length-1,
            (v??points.length-1)+(event.key==='ArrowRight'?1:-1))))
        }
        if(event.key==='Home'){event.preventDefault();setHover(0)}
        if(event.key==='End'){event.preventDefault();setHover(points.length-1)}
      }}>
      {[0,.25,.5,.75,1].map(t=><g key={t}>
        <line x1={left} x2={right} y1={top+t*(bottom-top)}
          y2={top+t*(bottom-top)} stroke="#34485a" strokeDasharray="3 7"/>
        <text x={left-7} y={top+t*(bottom-top)+4} fill="#9db5c2"
          fontSize="12" textAnchor="end">{valueLabel(ceil-t*range)}</text>
      </g>)}
      {view==='excess'?<>
        <line x1={left} x2={right} y1={yAt(0)} y2={yAt(0)}
          stroke="#b3bac6" strokeWidth="1.2"/>
        {points.map((p,i)=>{
          const x=xAt(i),zero=yAt(0),value=yAt(p.excess)
          const barWidth=Math.max(1.6,Math.min(18,width/points.length*.7))
          return <rect key={i} x={x-barWidth/2}
            y={Math.min(zero,value)} width={barWidth}
            height={Math.max(1,Math.abs(zero-value))}
            fill={p.excess>=0?'#65ddc3':'#ecaf75'}
            opacity={hover===i?1:.82}/>
        })}
      </>:<>
        {view==='drawdown'&&(['benchmark','strategy'] as const).map((k,i)=>
          <path key={k} d={path(k)+' L '+right+','+yAt(0)+' L '+left+','+yAt(0)+' Z'}
            fill={i?'#58dcc4':'#e6b77b'} opacity=".13"/>)}
        <path d={path('benchmark')} stroke="#e3b675" fill="none" strokeWidth="2.2"
          vectorEffect="non-scaling-stroke"/>
        <path d={path('strategy')} stroke="#64dbc2" fill="none" strokeWidth="2.9"
          vectorEffect="non-scaling-stroke"/>
      </>}
      {selected&&hover!==null&&<g className="ws-chart-focus">
        <line x1={xAt(hover)} x2={xAt(hover)} y1={top} y2={bottom}
          stroke="#d2ecdf" strokeDasharray="4 4" strokeWidth="1.1"/>
        {view!=='excess'&&(['strategy','benchmark'] as const).map(k=>
          <circle key={k} cx={xAt(hover)} cy={yAt(read(selected,k))} r="4.6"
            stroke="#0b2230" strokeWidth="2" fill={k==='strategy'?'#64dbc2':'#e3b675'}/>)}
        <rect x={Math.min(xAt(hover)+12,right-202)} y={top+3}
          width="201" height={view==='excess'?63:87} rx="9" fill="#0c2533"
          stroke="#73938f" strokeOpacity=".8"/>
        <text x={Math.min(xAt(hover)+23,right-191)} y={top+21}
          fontSize="12" fill="#e3f5ed">{selected.date.slice(0,10)}</text>
        {view==='excess'?<text x={Math.min(xAt(hover)+23,right-191)} y={top+43}
          fill={selected.excess>=0?'#70efd0':'#ffc48f'} fontSize="12">
          {'Strategy − Benchmark: '+valueLabel(selected.excess)}
        </text>:<>
          <text x={Math.min(xAt(hover)+23,right-191)} y={top+43}
            fill="#6fe8ce" fontSize="12">Strategy: {valueLabel(read(selected,'strategy'))}</text>
          <text x={Math.min(xAt(hover)+23,right-191)} y={top+64}
            fill="#ffc98e" fontSize="12">Benchmark: {valueLabel(read(selected,'benchmark'))}</text>
        </>}
      </g>}
      <text x={left} y="271" fill="#9eb6c8" fontSize="11">{points[0].date.slice(0,10)}</text>
      <text x={right} y="271" fill="#9eb6c8" textAnchor="end"
        fontSize="11">{points[points.length-1].date.slice(0,10)}</text>
    </svg>
    <p className="ws-caption">{captionText} Hover to inspect dates and exact values.
      The chart is descriptive, not proof of investability.</p>
  </div>
}
function BarRows({rows,valueKey='weight',nameKey='name'}:{rows:Dict[];valueKey?:string;nameKey?:string}){
  if(!rows.length)return <Empty title="No exposure data">Select a completed research run to inspect portfolio exposures.</Empty>
  const top=rows.slice(0,14); const max=Math.max(...top.map(r=>Math.abs(Number(r[valueKey]||0))),.00001)
  return <div className="ws-bars">{top.map((r,i)=><div className="ws-bar-row" key={i}><span title={String(r[nameKey])}>{String(r[nameKey]??'—')}</span><div><i style={{width:(Math.abs(Number(r[valueKey]||0))/max*100)+'%'}}/></div><strong>{percent(Number(r[valueKey]))}</strong></div>)}</div>
}
function NumberInput({label:caption,value,onChange,min,max,step=1}:{label:string;value:number;onChange:(n:number)=>void;min?:number;max?:number;step?:number}){
  return <label className="ws-field"><span>{caption}</span><input type="number" value={value} onChange={e=>onChange(Number(e.target.value))} min={min} max={max} step={step}/></label>
}
function Field({label:caption,value,onChange,placeholder='',type='text'}:{label:string;value:string;onChange:(s:string)=>void;placeholder?:string;type?:string}){
  return <label className="ws-field"><span>{caption}</span><input type={type} value={value} placeholder={placeholder} onChange={e=>onChange(e.target.value)}/></label>
}
function Select({label:caption,value,options,onChange}:{label:string;value:string;options:{value:string;label:string}[];onChange:(v:string)=>void}){
  return <label className="ws-field"><span>{caption}</span><select value={value} onChange={e=>onChange(e.target.value)}>{options.map(opt=><option key={opt.value} value={opt.value}>{opt.label}</option>)}</select></label>
}
const weighted=(metric:Dict|undefined,key:string)=>metric?.[key]
function App(){
  const [tab,setTab]=useState<Tab>(hashTab)
  const [jobsOpen,setJobsOpen]=useState(false)
  const [menu,setMenu]=useState(false)
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
  const [detail,setDetail]=useState<Detail|null>(null)
  const [config,setConfig]=useState<RunConfig>(defaultConfig)
  const [job,setJob]=useState<Job|null>(null)
  const [busy,setBusy]=useState(false)
  const [notice,setNotice]=useState<{text:string;error:boolean}|null>(null)
  const [auditResult,setAuditResult]=useState<Dict|null>(null)
  const [dhan,setDhan]=useState<DhanStatus|null>(null)
  const dataset=datasets.find(d=>d.id===selectedDataset)
  const everydaySources=datasets.filter(d=>d.id==='dhan_shared'||d.kind!=='dhan'||d.id===selectedDataset)
  const selected=runs.find(r=>r.id===selectedRun)
  const metrics=detail?.meta.metrics_by_split??selected?.metrics_by_split??{}
  const split=Object.entries(metrics).at(-1)
  const metric=split?.[1]
  const monthlyCount=dataset?.monthly_price_observations??0
  const requiredWarmup=Math.max(
    (config.factor_weights.momentum||0)>0?config.momentum_formation+config.momentum_skip:0,
    (config.factor_weights.low_volatility||0)>0 || ['inverse_volatility','minimum_variance','risk_parity'].includes(config.weighting)
      ?config.volatility_lookback:0
  )
  const availableTestMonths=Math.max(0,monthlyCount-requiredWarmup-config.execution_lag)
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
  const runPicker=<select aria-label="Select completed experiment" className="ws-select" value={selectedRun} onChange={e=>setSelectedRun(e.target.value)}>{runs.length===0?<option value="">No runs yet</option>:runs.map(r=><option key={r.id} value={r.id}>{r.name} · {r.id}</option>)}</select>
  const dataPicker=<select className="ws-select" aria-label="Select research dataset" value={selectedDataset} onChange={e=>{setSelectedDataset(e.target.value)}}><option value="">Choose market source</option>{everydaySources.map(d=><option key={d.id} value={d.id}>{d.label}{d.ready?'':' (additional model evidence needed)'}</option>)}</select>
  const withRun=(content:React.ReactNode)=><>{runs.length===0?<Empty title="No research run selected" onAction={()=>begin('research')} action="Run an experiment">All charts are generated from Python research outputs, not hardcoded sample performance.</Empty>:<>{runPicker}{content}</>}</>
  const classification=<Tag tone={detail?.source.dataset_kind==='synthetic'?'warn':'blue'}>{detail?.source.dataset_kind==='synthetic'?'SYNTHETIC DATA — DEMONSTRATION':detail?'USER DATA · NOT INDEPENDENTLY AUDITED':'NO RESEARCH RUN'}</Tag>
  const chart=detail?<EquityChart rows={detail.returns}/>:null
  const panel=(key: keyof Detail,description:string)=>withRun(<Card title={description}><Table rows={(detail?.[key] as Dict[]|undefined)??[]} max={20}/></Card>)
  return <div className="ws-shell ws-v2">
    <aside className={'ws-sidebar '+(menu?'open':'')}>
      <div className="ws-brand"><span className="ws-brand-mark"><Activity size={23}/></span><div><strong>QUANT<span>LAB</span></strong><small>RESEARCH WORKSTATION</small></div><button type="button" className="ws-mobile-close" onClick={()=>setMenu(false)}><X size={19}/></button></div>
      <div className="ws-env"><span className={'ws-status-dot '+(health?.ok?'':'offline')}/><div><strong>{health?.ok?'LOCAL ENGINE CONNECTED':'ENGINE DISCONNECTED'}</strong><small>127.0.0.1 · NO BROKER EXECUTION</small></div></div>
      <nav aria-label="Primary QuantLab navigation">
        <div className="ws-nav-group"><span className="ws-nav-label">WORKSPACES</span>
          {primarySections.map((section,index)=><button type="button" key={section.id}
            title={'Ctrl+Alt+'+(index+1)+' · '+section.label}
            onClick={()=>begin(section.id)}
            aria-current={section.tabs.includes(tab)?'page':undefined}
            className={'ws-nav-item '+(section.tabs.includes(tab)?'active':'')}>
            <section.icon size={17} strokeWidth={1.9}/>{section.label}
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
          <RecorderBadge onOpen={()=>begin('recordingsettings')}/>
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
      <main className="ws-content">
        <div className="ws-titlebar">
          <div><div className="ws-overline">LOCAL QUANTITATIVE RESEARCH WORKSTATION</div>
            <h1>{titles[tab]}</h1><p>{descriptions[tab]}</p></div>
          <div className="ws-title-actions">
            {tab==='overview'&&<button className="ws-button primary"
              onClick={()=>begin('journey')}><Play size={15}/> New study</button>}
            {(['trading','tradingchain','tradingdepth','tradingreplay','tradingjournal'].includes(tab))&&
              <button className="ws-button secondary" onClick={()=>begin('recordingsettings')}>
                <Activity size={15}/> Recorder settings</button>}
            {(['strategies','strategyema','strategypython','strategybacktest'].includes(tab))&&
              <button className="ws-button secondary" onClick={()=>begin('data')}>
                <Database size={15}/> Data coverage</button>}
          </div>
        </div>
        {(()=>{
          const visible=primarySections.find(section=>section.tabs.includes(tab))?.navTabs||[]
          return visible.length>1?<nav className="ws-context-tabs"
              aria-label="Modules within selected research destination">
            {visible.map(module=><button type="button" key={module}
              aria-current={tab===module?'page':undefined}
              className={tab===module?'active':''} onClick={()=>begin(module)}>
              {titles[module]}</button>)}
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
        {(['trading','tradingchain','tradingdepth','tradingreplay',
            'tradingjournal','strategybacktest','connections'].includes(tab))&&
          <TradingCockpit
            integrated
            selectedView={tab==='tradingreplay'?'replay':
              tab==='tradingjournal'?'journal':
              tab==='strategybacktest'?'strategy':
              tab==='connections'?'setup':'live'}
            focusLive={tab==='trading'?'signals':
              tab==='tradingchain'?'options':
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
        {tab==='data'&&<>
          <MarketDataWorkspace key="v2-market-library" initialPage="datasets"
            activePage="datasets" integrated datasets={datasets}
            onDataChanged={refresh} onSelectDataset={setSelectedDataset}
            onOpenModels={()=>begin('mathematics')}
            onRequestDelete={id=>{const d=datasets.find(item=>item.id===id)
              if(d)inspectDatasetDeletion(d)}}/>
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
        {(['dhan','datadownloads'].includes(tab))&&
          <MarketDataWorkspace key="v2-market-acquire" initialPage="get"
            activePage={tab==='dhan'?'get':'downloads'} integrated datasets={datasets}
          onDataChanged={refresh} onSelectDataset={setSelectedDataset}
          onOpenModels={()=>begin('mathematics')}
          onRequestDelete={id=>{const d=datasets.find(item=>item.id===id)
            if(d)inspectDatasetDeletion(d)}}/>}
        {tab==='dataexplorer'&&<DataManager initialSection="explorer" integrated
          onSelectDataset={setSelectedDataset} onChanged={refresh}
          onOpenDhan={()=>begin('dhan')} onOpenModels={()=>begin('mathematics')}/>}
        {tab==='dataquality'&&<ResearchWorkspace key="v2-data-quality"
          initialPage="quality" integrated datasets={datasets}
          selectedDataset={selectedDataset} onSelectDataset={setSelectedDataset}
          onDataChanged={refresh} onOpenDhan={()=>begin('dhan')}
          onOpenModels={()=>begin('mathematics')}/>}
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

        {tab==='research'&&<>
          <div className="ws-grid two-thirds"><Card title="Experiment configuration" extra={<Tag tone="blue">BACKED BY PYTHON</Tag>}><div className="ws-setup-row"><span>Source dataset</span>{dataPicker}<Tag tone={dataset?.ready?'good':'warn'}>{dataset?.ready?'READY':'NEEDS INPUTS'}</Tag></div><div className="ws-form-grid"><Field label="Experiment name" value={config.name} onChange={v=>setConfig({...config,name:v})}/><Select label="Portfolio weighting" value={config.weighting} onChange={v=>setConfig({...config,weighting:v})} options={['equal','score','inverse_volatility','minimum_variance','risk_parity'].map(v=>({value:v,label:label(v)}))}/><NumberInput label="Constituents (top N)" value={config.top_n} min={2} max={300} onChange={v=>setConfig({...config,top_n:v})}/><NumberInput label="Maximum holding weight" value={config.max_weight} min={.01} max={1} step={.01} onChange={v=>setConfig({...config,max_weight:v})}/><NumberInput label="Rebalance frequency (months)" value={config.rebalance_every} min={1} max={12} onChange={v=>setConfig({...config,rebalance_every:v})}/><NumberInput label="Transaction costs (bps)" value={config.cost_bps} min={0} max={500} step={5} onChange={v=>setConfig({...config,cost_bps:v})}/><Select label="Execution lag" value={String(config.execution_lag)} onChange={v=>setConfig({...config,execution_lag:Number(v)})} options={[{value:'1',label:'One month (conservative)'},{value:'0',label:'Same-close idealization'}]}/><NumberInput label="Formation months" value={config.momentum_formation} min={2} max={60} onChange={v=>setConfig({...config,momentum_formation:v})}/><NumberInput label="Months to skip" value={config.momentum_skip} min={0} max={12} onChange={v=>setConfig({...config,momentum_skip:v})}/><NumberInput label="Volatility lookback (months)" value={config.volatility_lookback} min={3} max={60} onChange={v=>setConfig({...config,volatility_lookback:v})}/><Field label="Validation start (optional)" type="date" value={config.validation_start} onChange={v=>setConfig({...config,validation_start:v})}/><Field label="Frozen test start (optional)" type="date" value={config.final_test_start} onChange={v=>setConfig({...config,final_test_start:v})}/></div><label className="ws-checkbox"><input type="checkbox" checked={config.sector_cap!==null} onChange={e=>setConfig({...config,sector_cap:e.target.checked ? 0.4 : null})}/> Apply historical sector concentration cap</label>{config.sector_cap!==null&&<NumberInput label="Sector allocation cap" value={config.sector_cap} min={.1} max={1} step={.05} onChange={v=>setConfig({...config,sector_cap:v})}/>}{dataset?.has_prices&&monthlyCount>0&&availableTestMonths<12&&
              <div className="ws-rule" role="status"><CircleAlert size={16}/>
                <div><strong>Limited statistical window: {monthlyCount} price observations</strong>
                  <p>After approximately {requiredWarmup} months of signal history and {config.execution_lag} month(s) of execution lag, only up to {availableTestMonths} eligible months remain before other eligibility gates. CAGR, drawdown or inference may be undefined. Short-sample runs are exploratory, not resume-ready performance claims.</p>
                  {monthlyCount>4&&<button type="button" className="ws-textlink"
                    onClick={()=>setConfig(c=>({...c,momentum_formation:3,momentum_skip:1,volatility_lookback:3,rebalance_every:1}))}>
                    Apply explicit short-sample demonstration settings <ArrowRight size={13}/></button>}
                </div>
              </div>}
              <div className="ws-actions"><button className="ws-button primary" disabled={!dataset?.ready||busy||!!job&&['queued','running'].includes(job.status)} onClick={startRun}><Play size={15}/> Run Python backtest</button><span className="ws-caption">Uses saved datasets with explicit provenance; writes result artifacts to disk.</span></div></Card>
          <Card title="Factor allocation"><p className="ws-caption">Select a factor and adjust its relative contribution to the composite score.</p><div className="ws-sliders">{factors.map(([key,name])=><label className="ws-factor" key={key}><div><span>{name}</span><strong>{number(config.factor_weights[key],1)}</strong></div><input type="range" min="0" max="1" step=".1" value={config.factor_weights[key]??0} onChange={e=>setConfig({...config,factor_weights:{...config.factor_weights,[key]:Number(e.target.value)}})}/></label>)}</div><div className="ws-rule"><ShieldCheck size={16}/> A backtest cannot prove historical correctness when constituent histories, adjusted returns, and benchmark evidence are missing.</div></Card></div>
          <HistoricalValidationPanel datasetId={selectedDataset} config={config}
            hasDailyPrices={!!dataset?.has_daily_prices}
            onDataCreated={id=>{setSelectedDataset(id);void refresh();
              notify('New version created from original daily prices and dated events; evidence remains unverified.')}}
            onOpenData={()=>begin('data')} onOpenDhan={()=>begin('dhan')}
            onJobQueued={id=>{setJob({id,kind:'frozen_evaluation',status:'queued'});
              notify('Single-use frozen experiment queued; its result receipt will be checked.') }}/>
          {job&&<Card title="Current job"><div className="ws-job-row"><Tag tone={job.status==='error'?'bad':job.status==='complete'?'good':'blue'}>{job.status.toUpperCase()}</Tag><span>{job.kind}</span><small>{job.error||job.id}</small></div></Card>}
        </>}
        {tab==='history'&&<ResultsStudio
          selectedIndexRunId={selectedRun}
          onSelectIndexRun={setSelectedRun}
          onModels={()=>begin('models')}
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
        {(tab==='mathematics'||tab==='models')&&<ModelLaboratory
          section={tab} datasets={datasets} selectedDataset={selectedDataset}
          onSelectDataset={setSelectedDataset} onOpenGuide={()=>begin('guide')} onDataChanged={refresh}
          onOpenWorkspace={()=>begin('workspace')} onOpenData={()=>begin('data')}/>}
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
        {tab==='preferences'&&<SettingsPreferencesV2/>}
        {tab==='diagnostics'&&<DiagnosticsV2 onRepair={()=>begin('settings')}
          onData={()=>begin('dataquality')}/>}
        {tab==='settings'&&<div className="ws-grid halves"><Card title="Backend and privacy"><div className="ws-data-audit"><div><span>API address</span><strong>127.0.0.1:8765</strong></div><div><span>Frontend address</span><strong>127.0.0.1:5173</strong></div><div><span>Data directory</span><strong>data/ (Git-ignored)</strong></div><div><span>Run artifacts</span><strong>results/workstation_runs/</strong></div><div><span>Authentication</span><strong>Loopback-only; not for public exposure</strong></div><div><span>Broker trading</span><strong>DISABLED</strong></div><div><span>Dhan token</span><strong>{health?.dhan_token_configured?'CONFIGURED (HIDDEN)':'MISSING'}</strong></div></div></Card><Card title="Integrity controls"><div className="ws-rule"><ShieldCheck size={18}/> Local data import, explicit dataset status, safe path allowlists, no broker order operations, no credential output, and no historical-performance fabrication.</div><p className="ws-caption">This is a local research environment, not an authenticated public server. Do not expose port 8765 on a network or deploy it as-is.</p><button className="ws-button secondary" onClick={()=>void refresh()}><RefreshCw size={16}/> Refresh engine status</button></Card></div>}
        </Suspense>
        <footer className="ws-footer"><span>QUANTLAB / RESEARCH WORKSTATION</span><span>LOCAL ENGINE · HISTORICAL CLAIMS REQUIRE EXTERNAL VALIDATION</span><span>© PERSONAL RESEARCH</span></footer>
      </main>
    </div>
  </div>
}
export default App
