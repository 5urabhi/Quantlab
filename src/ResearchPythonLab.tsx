import {useEffect,useMemo,useRef,useState} from 'react'
import {Activity,Code2,Database,Download,Play,Save,ShieldCheck,SlidersHorizontal} from 'lucide-react'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
import {STRATEGY_SCRIPT_EVENT,openScriptInPython} from './pythonBridge'
import PythonCodeEditor from './PythonCodeEditor'
import ResearchPlot,{type ResearchPlotData} from './ResearchPlots'
import './research-python-lab.css'

type SourceMode='historical'|'recorded_live'
type Tab='sweep'|'python'
type EmaMode='pair'|'selected'|'all'
type JobResponse={job_id:string;status:string}
type Job={id:string;status:string;stage?:string;percent?:number;error?:string;result?:LabResult}
type PaperTrade={
  direction:'UP'|'DOWN';entry_utc:string;exit_utc:string;entry_price:number
  exit_price:number;hold_minutes:number;index_points:number
  net_pnl_proxy_inr:number;equity_inr:number;exit_reason:string
}
type Stat={
  trade_count:number;crossovers:number;win_rate_pct:number|null
  pnl_proxy_inr:number;return_proxy_pct:number;ending_capital_proxy_inr:number
  index_points:number;max_closed_trade_drawdown_pct:number
  profit_factor:number|null;trade_sharpe_unannualized:number|null
  avg_hold_minutes:number|null;unscored:Record<string,number>
}
type CurveBar={time:string;price:number;account:number;signal:'UP'|'DOWN'|'HOLD';position:string}
type Overlay={
  time:string;price:number;open:number;high:number;low:number
  fast_ema:number|null;slow_ema:number|null;ema_spread_bps:number|null
  momentum_roc5_pct:number|null;rsi14:number|null
  signal:'UP'|'DOWN'|'HOLD'
}
type LabResult={
  kind:'ema_sweep'|'ema_pair'|'python_strategy';run_id:string
  identity:string;read_only:boolean;orders_placed:number
  evidence:{identity:string;basis:string;source_mode:string
    original_sha256?:string|null;source_warning?:string|null
    rows:number;sessions:number;first_utc:string;last_utc:string}
  model?:string;reference_ema?:{fast:number;slow:number;note:string}
  best_pair?:{fast:number;slow:number};combinations_tested?:number
  ranked?:{fast:number;slow:number;training:Stat;holdout?:Stat
    ranking_eligible?:boolean}[]
  top_five?:{fast:number;slow:number;training:Stat;holdout?:Stat
    ranking_eligible?:boolean}[]
  search_mode?:'selected'|'all'
  ranked_returned?:number;qualifying_combinations?:number
  min_completed_trades_to_rank?:number;ranking_basis?:string
  validation?:{whole_sessions_train:number;whole_sessions_holdout:number
    holdout_available:boolean;warning:string}
  selected:{metrics:Stat;trades:PaperTrade[];chart:CurveBar[]
    basis:string;read_only:boolean;orders_placed:number}
  overlays:Overlay[]
  sandbox?:{engine:string;source_sha256:string;input_candles:number
    network_allowed:boolean;broker_access_allowed:boolean;orders_placed:number}
  bid_ask_spread_source:string
}
type Status={python_sandbox:{available:boolean;engine:string
  requires:string[];note:string};live_capture_isolated:boolean
  broker_orders_enabled:boolean;note:string}
type SavedRun={run_id:string;modified_utc:string;file_bytes:number}
const KEY='quantlab_python_editor_v1'
const JOB='quantlab_research_lab_job_v1'
const STARTING_SCRIPT=[
  '# Paste or type any standard-library Python strategy here.',
  '# Called once per CLOSED 1-minute BANKNIFTY candle.',
  '# history includes THIS candle and earlier candles from the SAME session.',
  '# Return UP (buy CE/long-index proxy), DOWN (buy PE/short-index proxy),',
  '# or HOLD (keep the existing position). No time cap.',
  '',
  'def ema(prices, period):',
  '    if len(prices) < period:',
  '        return None',
  '    level = sum(prices[:period]) / period',
  '    multiplier = 2.0 / (period + 1)',
  '    for close in prices[period:]:',
  '        level = multiplier * close + (1 - multiplier) * level',
  '    return level',
  '',
  'def signal(history):',
  '    closes = [bar["close"] for bar in history]',
  '    if len(closes) < 22:',
  '        return "HOLD"',
  '    fast_before = ema(closes[:-1], 9)',
  '    slow_before = ema(closes[:-1], 21)',
  '    fast_now = ema(closes, 9)',
  '    slow_now = ema(closes, 21)',
  '    if fast_before <= slow_before and fast_now > slow_now:',
  '        return "UP"',
  '    if fast_before >= slow_before and fast_now < slow_now:',
  '        return "DOWN"',
  '    return "HOLD"',
].join('\n')
const dec=(n:number|null|undefined,d=2)=>n===null||n===undefined||!Number.isFinite(n)
  ?'—':n.toLocaleString('en-IN',{maximumFractionDigits:d})
const money=(n:number|null|undefined)=>n===null||n===undefined?'—':
  new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',
    maximumFractionDigits:2}).format(n)
const ist=(value:string)=>new Date(value).toLocaleString('en-IN',{
  timeZone:'Asia/Kolkata',month:'short',day:'numeric',hour:'2-digit',
  minute:'2-digit',hourCycle:'h23',
})
const periods=(s:string)=>[...new Set(s.split(/[\s,;]+/).filter(Boolean).map(Number))]
const metrics=(row:Stat)=>[
  ['Net paper P&L',money(row.pnl_proxy_inr)],
  ['Paper account return',dec(row.return_proxy_pct)+'%'],
  ['BANKNIFTY points',dec(row.index_points,2)],
  ['Completed positions',dec(row.trade_count,0)],
  ['Confirmed crossovers',dec(row.crossovers,0)],
  ['Win rate',row.win_rate_pct==null?'—':dec(row.win_rate_pct)+'%'],
  ['Average hold',row.avg_hold_minutes==null?'—':dec(row.avg_hold_minutes)+' min'],
  ['Closed-trade drawdown',dec(row.max_closed_trade_drawdown_pct)+'%'],
  ['Profit factor',dec(row.profit_factor)],
  ['Trade Sharpe (unannualized)',dec(row.trade_sharpe_unannualized)],
]
type ChartKey='price'|'momentum_roc5_pct'|'ema_spread_bps'|'rsi14'|'account'
type ChartSource={time:string;[key:string]:number|string|null|undefined}
function MiniLine({data,kind,label}:{data:ChartSource[];kind:ChartKey;label:string}){
  const number=(v:unknown)=>typeof v==='number'&&Number.isFinite(v)?v:null
  const units:Record<ChartKey,string>={price:'Index level (points)',momentum_roc5_pct:'5-minute return (%)',ema_spread_bps:'EMA difference (bps)',rsi14:'RSI (0–100)',account:'Paper index equity (₹)'}
  const values=data.map(r=>number(r[kind]))
  if(!values.some(v=>v!==null))return <p className="rpl-graph-empty">No {label.toLowerCase()} observations in this window.</p>
  const plot:ResearchPlotData={kind:'line2d',title:label,x:data.map(r=>r.time),x_label:'Bar start time (IST)',y_label:units[kind],
    traces:[{name:kind==='price'?'Index close':label,y:values,color:'#f5c542'}],
    break_before:kind==='account'?undefined:data.map((r,i)=>i>0&&Date.parse(r.time)-Date.parse(data[i-1].time)!==60000),
    reference_lines:kind==='rsi14'?[{value:30,label:'Oversold 30'},{value:70,label:'Overbought 70'}]:kind==='momentum_roc5_pct'||kind==='ema_spread_bps'?[{value:0,label:'Zero'}]:undefined}
  if(kind==='price'){
    plot.traces!.push({name:'Fast EMA',color:'#ff8192',y:data.map(r=>number(r.fast_ema))},{name:'Slow EMA',color:'#70e1ad',y:data.map(r=>number(r.slow_ema))})
    plot.point_markers=data.filter(r=>r.signal==='UP'||r.signal==='DOWN').flatMap(r=>typeof r.price==='number'?[{x:r.time,y:r.price,label:String(r.signal)+' crossover (signal, not a fill)',color:r.signal==='UP'?'#70e1ad':'#ff8192'}]:[])
  }
  return <ResearchPlot plot={plot} provenance="historical" syncGroup="strategy-lab" formatX={x=>ist(String(x))} formatY={v=>dec(v,3)}/>
}
function PriceChart({data}:{data:Overlay[]}){
  return <div className="rpl-price-chart"><MiniLine data={data as unknown as ChartSource[]} kind="price" label="BANKNIFTY index price · CE / PE crossover markers"/><p className="rpl-note">Red = fast EMA · green = slow EMA. Crossover markers are research signals, not executed options fills.</p></div>
}

export default function ResearchPythonLab({displayMode,integrated=false}:{
  displayMode?:Tab;integrated?:boolean
}={}){
  const [tab,setTab]=useState<Tab>(displayMode||'python')
  useEffect(()=>{if(displayMode)setTab(displayMode)},[displayMode])
  const [sourceMode,setSourceMode]=useState<SourceMode>('historical')
  const [limit,setLimit]=useState<500|1500|3000|5000>(1500)
  const [startingCapital,setStartingCapital]=useState(50000)
  const [costBps,setCostBps]=useState(5)
  const [emaMode,setEmaMode]=useState<EmaMode>('pair')
  const [pairFast,setPairFast]=useState(9)
  const [pairSlow,setPairSlow]=useState(21)
  const [fast,setFast]=useState('3,5,7,9,12,15,21')
  const [slow,setSlow]=useState('13,21,26,34,50,55,89')
  const [script,setScript]=useState(()=>{
    try{return sessionStorage.getItem('ql-v2-python-unsaved-draft')||STARTING_SCRIPT}
    catch{return STARTING_SCRIPT}
  })
  // Navigating away from the editor must never discard unsaved typed code.
  // Only the local browser session keeps this draft; nothing goes to Dhan.
  useEffect(()=>{
    try{sessionStorage.setItem('ql-v2-python-unsaved-draft',script.slice(0,50000))}
    catch{/* session storage can be disabled without affecting explicit Save */}
  },[script])
  useEffect(()=>{
    const load=(e:Event)=>{const code=(e as CustomEvent<string>).detail;if(typeof code==='string'){setScript(code);setTab('python')}}
    window.addEventListener(STRATEGY_SCRIPT_EVENT,load)
    return()=>window.removeEventListener(STRATEGY_SCRIPT_EVENT,load)
  },[])
  const [profile,setProfile]=useState<'stdlib'|'scientific'>(()=>{try{return localStorage.getItem('ql-python-profile')==='scientific'?'scientific':'stdlib'}catch{return 'stdlib'}})
  useEffect(()=>{try{localStorage.setItem('ql-python-profile',profile)}catch{/* optional */}},[profile])
  const [savedName,setSavedName]=useState('EMA 9/21 example')
  const [status,setStatus]=useState<Status|null>(null)
  const [jobId,setJobId]=useState(()=>sessionStorage.getItem(JOB)||'')
  const [job,setJob]=useState<Job|null>(null)
  const [result,setResult]=useState<LabResult|null>(null)
  const [sweep,setSweep]=useState<LabResult|null>(null)
  const [savedRuns,setSavedRuns]=useState<SavedRun[]>([])
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')
  const [zoom,setZoom]=useState(100)
  const [busy,setBusy]=useState(false)
  const editor=useRef<HTMLTextAreaElement>(null)

  useEffect(()=>{
    let current=true
    marketApi<Status>('/api/trading-cockpit/research-lab/status')
      .then(data=>{if(current)setStatus(data)})
      .catch(()=>{/* no browser crash if local API is disconnected */})
    marketApi<{runs:SavedRun[]}>('/api/trading-cockpit/research-lab/runs')
      .then(data=>{if(current)setSavedRuns(data.runs)})
      .catch(()=>{})
    return ()=>{current=false}
  },[])
  useEffect(()=>{
    if(!jobId)return
    let enabled=true,reading=false
    const check=async()=>{
      if(reading)return
      reading=true
      try{
        const value=await marketApi<Job>('/api/jobs/'+encodeURIComponent(jobId))
        if(!enabled)return
        setJob(value)
        if(value.status==='complete'){
          if(value.result){
            setResult(value.result)
            if(value.result.kind==='ema_sweep')setSweep(value.result)
            setZoom(100)
            setSavedRuns(old=>[{run_id:value.result!.run_id,
              modified_utc:new Date().toISOString(),file_bytes:0},
              ...old.filter(x=>x.run_id!==value.result!.run_id)].slice(0,25))
          }
          setJobId('')
          sessionStorage.removeItem(JOB)
          setBusy(false)
        }else if(['error','cancelled','interrupted'].includes(value.status)){
          setError(value.error||'Local research job did not complete; live recorder remains independent.')
          setJobId('')
          sessionStorage.removeItem(JOB)
          setBusy(false)
        }
      }catch(err){if(enabled)setError(readableError(err))}
      finally{reading=false}
    }
    void check()
    const interval=setInterval(()=>{void check()},1300)
    return ()=>{enabled=false;clearInterval(interval)}
  },[jobId])

  const start=async(endpoint:string,body:Record<string,unknown>)=>{
    setError('');setNotice('');setBusy(true)
    try{
      const submitted=await marketPost<JobResponse>(
        '/api/trading-cockpit/research-lab/'+endpoint,
        {...body,source_mode:sourceMode,starting_capital:startingCapital,
          cost_bps:costBps,limit:tab==='python'?Math.min(limit,1500):limit,
          confirm_readonly:true})
      setJob({id:submitted.job_id,status:submitted.status,stage:'Queued'})
      setJobId(submitted.job_id)
      sessionStorage.setItem(JOB,submitted.job_id)
    }catch(err){setBusy(false);setError(readableError(err))}
  }
  const runSweep=()=>{
    setError('')
    if(emaMode==='pair'){
      if(!Number.isInteger(pairFast)||!Number.isInteger(pairSlow)
          ||pairFast<2||pairSlow>150||pairFast>=pairSlow){
        setError('Choose integer fast/slow EMA periods with 2 ≤ fast < slow ≤ 150.')
        return
      }
      runPair(pairFast,pairSlow)
      return
    }
    if(emaMode==='all'){
      // The backend generates every integer fast < slow from 2..150,
      // rather than quietly testing only a sample of pairs.
      void start('ema-sweep',{mode:'all'})
      return
    }
    const f=periods(fast),s=periods(slow)
    const pairs=f.flatMap(a=>s.filter(b=>b>a).map(b=>[a,b]))
    if(!f.length||!s.length||f.length>32||s.length>32
        ||f.some(n=>!Number.isInteger(n)||n<2||n>150)
        ||s.some(n=>!Number.isInteger(n)||n<2||n>150)
        ||pairs.length>256||!pairs.length){
      setError('Enter 1–256 distinct valid fast < slow combinations (periods 2–150).')
      return
    }
    void start('ema-sweep',{mode:'selected',fast_periods:f,slow_periods:s})
  }
  const runPython=()=>{
    setTab('python')
    if(script.length>20000||!script.includes('def signal(')){
      setError('Define def signal(history): returning UP, DOWN or HOLD; maximum 20,000 characters.')
      return
    }
    void start('python',{code:script,profile})
  }
  const runPair=(f:number,s:number)=>{
    setTab('sweep');void start('ema-pair',{fast:f,slow:s})
  }
  const saveScript=()=>{
    try{
      const key=savedName.trim().slice(0,65)||'My custom strategy'
      const current=JSON.parse(localStorage.getItem(KEY)||'{}') as Record<string,string>
      current[key]=script
      localStorage.setItem(KEY,JSON.stringify(current))
      setLocalNames(Object.keys(current))
      setNotice('Saved '+key+' in this browser only. The code is never sent to Dhan.')
    }catch{setError('Browser storage unavailable; copy your code to a private file.')}
  }
  const [localNames,setLocalNames]=useState<string[]>([])
  const loadSavedList=()=>{
    try{
      setLocalNames(Object.keys(JSON.parse(localStorage.getItem(KEY)||'{}')))
    }catch{setLocalNames([])}
  }
  const downloadScript=()=>{
    const url=URL.createObjectURL(new Blob([script],{type:'text/x-python;charset=utf-8'}))
    const anchor=document.createElement('a')
    anchor.href=url
    anchor.download=(savedName.trim().replace(/[^a-zA-Z0-9_-]+/g,'-')||'quantlab-strategy')+'.py'
    anchor.click()
    setTimeout(()=>URL.revokeObjectURL(url),1000)
  }
  const loadCode=(name:string)=>{
    try{
      const stored=JSON.parse(localStorage.getItem(KEY)||'{}') as Record<string,string>
      if(typeof stored[name]==='string'){
        setScript(stored[name]);setSavedName(name)
        setNotice('Loaded '+name+' into the editable Python panel.')
      }
    }catch{setError('Could not read the selected locally saved script.')}
  }
  const openRun=async(id:string)=>{
    setError('');setBusy(true)
    try{
      const next=await marketApi<LabResult>(
        '/api/trading-cockpit/research-lab/runs/'+encodeURIComponent(id))
      setResult(next)
      if(next.kind==='ema_sweep')setSweep(next)
      setZoom(100)
      setNotice('Loaded saved research result '+id+'.')
    }catch(e){setError(readableError(e))}
    finally{setBusy(false)}
  }
  const exportResult=()=>{
    if(!result)return
    const blob=new Blob([JSON.stringify(result,null,2)],{type:'application/json'})
    const url=URL.createObjectURL(blob)
    const a=document.createElement('a')
    a.href=url;a.download=result.run_id+'.json';a.click()
    setTimeout(()=>URL.revokeObjectURL(url),1000)
  }
  const currentChart=result?.overlays||[]
  const chart=useMemo(()=>{
    const from=Math.max(0,Math.floor(currentChart.length*(1-zoom/100)))
    const view=currentChart.slice(from)
    // Pure display decimation; all metric and trade calculations use all bars.
    if(view.length<=640)return view
    const step=Math.ceil(view.length/640)
    const picks=view.filter((row,index)=>index%step===0||row.signal!=='HOLD')
    return picks.length<=750?picks:picks.filter((_,index)=>index%2===0)
  },[currentChart,zoom])
  const account=useMemo(()=>{
    const samples=result?.selected.chart||[]
    if(!samples.length)return []
    const wanted=new Set(chart.map(x=>x.time))
    return samples.filter(x=>wanted.has(x.time))
  },[chart,result])
  const drawing=chart.map((x,i)=>({...x,account:account[i]?.account??null})) as ChartSource[]
  const busyNow=busy||Boolean(jobId)
  return <section className="rpl-shell" role="region" aria-label="BANKNIFTY Python strategy research lab">
    <header className="rpl-intro">
      <div><span className="tc-page-kicker">QUANTLAB · ISOLATED BANKNIFTY RESEARCH</span>
        <h2>{integrated?(tab==='sweep'?'EMA Crossover Explorer':'Python Strategy Editor'):'Python Strategy Lab'}</h2>
        <p>{tab==='sweep'?
          'Test chosen EMA values or every supported combination, inspect the top five and verify crossover timing on original BANKNIFTY index candles.':
          'Paste or type Python, backtest BANKNIFTY index direction and inspect charts. No restart, no broker orders.'}</p></div>
      <div className="rpl-safety"><ShieldCheck size={17}/> Live Dhan recording stays separate
        <small>Read-only snapshots · no changes to depth subscriptions</small></div>
    </header>
    {!integrated&&<div className="rpl-tabs" role="tablist" aria-label="Strategy research modes">
      <button role="tab" aria-selected={tab==='python'} onClick={()=>setTab('python')}>
        <Code2 size={17}/> Paste or type Python</button>
      <button role="tab" aria-selected={tab==='sweep'} onClick={()=>setTab('sweep')}>
        <SlidersHorizontal size={17}/> All EMA combinations</button>
    </div>}
    <div className="rpl-panel">
      <div className="rpl-controls" aria-label="Research data and capital settings">
        <label>Original source
          <select aria-label="Strategy Lab source" value={sourceMode}
            onChange={e=>setSourceMode(e.target.value as SourceMode)}>
            <option value="historical">Dhan IDX_I historical BANKNIFTY candles</option>
            <option value="recorded_live">Already recorded live BANKNIFTY minutes</option>
          </select>
        </label>
        <label>Completed minute bars
          <select aria-label="Strategy Lab source minutes" value={limit}
            onChange={e=>setLimit(Number(e.target.value) as typeof limit)}>
            {(tab==='python'?[500,1500]:[500,1500,3000,5000]).map(count=>
              <option value={count} key={count}>{dec(count,0)} minute candles</option>)}
          </select>
        </label>
        <label>Hypothetical paper account (₹)
          <input aria-label="Strategy Lab starting capital" type="number" min={1000} max={100000000}
            step={1000} value={startingCapital} onChange={e=>setStartingCapital(Number(e.target.value))}/>
        </label>
        <label>Trading cost (bps per side)
          <input aria-label="Strategy Lab cost bps" type="number" min={0} max={500} step={1}
            value={costBps} onChange={e=>setCostBps(Number(e.target.value))}/>
        </label>
      </div>
      <p className="rpl-note"><Database size={16}/> The direct BANKNIFTY results are a
        hypothetical long/short <strong>index-directional P&L proxy</strong>. The cash
        BANKNIFTY index itself cannot be bought or shorted. Real CE/PE profit and
        slippage must be checked in Options Backtest with actual contract prices.</p>
      {tab==='python'?<>
        <div className="rpl-editor-title"><h3><Code2 size={18}/> Python code editor</h3>
          <div className="rpl-editor-actions">
            <button type="button" onClick={()=>{setScript(STARTING_SCRIPT);setNotice('Loaded the safe 9/21 example.')}}>
              Restore EMA example</button>
            <button type="button" onClick={()=>editor.current?.focus()}>Focus editor</button>
          </div></div>
        <p className="rpl-note">Define <code>def signal(history):</code> and return
          <code> "UP"</code>, <code>"DOWN"</code>, or <code>"HOLD"</code>.
          The function receives only completed original candles up through the
          current minute, never future candles. Standard-library Python only.</p>
        <label>Python profile <select value={profile} onChange={e=>setProfile(e.target.value as typeof profile)}><option value="stdlib">Standard library</option><option value="scientific">Scientific packages (test in Settings)</option></select></label>
        <PythonCodeEditor ref={editor} value={script} onChange={setScript} label="Paste or type Python backtest code" onRun={runPython}/>
        <div className="rpl-editor-foot">
          <div className="rpl-editor-actions">
            <input aria-label="Custom strategy name" value={savedName}
              onChange={e=>setSavedName(e.target.value)} maxLength={65}/>
            <button type="button" onClick={saveScript}><Save size={15}/> Save code locally</button>
            <button type="button" onClick={downloadScript}><Download size={15}/> Export Python file</button>
            <button type="button" onClick={()=>openScriptInPython(savedName,script)}>Open in My Scripts</button>
            <button type="button" onClick={loadSavedList}>Load saved code</button>
            {localNames.length>0&&<select aria-label="Locally saved Python scripts"
              defaultValue="" onChange={e=>loadCode(e.target.value)}>
              <option value="" disabled>Choose saved code</option>
              {localNames.map(name=><option key={name}>{name}</option>)}
            </select>}
          </div>
          <span>{script.split('\n').length} lines · {dec(script.length,0)}/20,000 characters</span>
        </div>
        {status&&!status.python_sandbox.available&&
          <p className="rpl-error" role="status"><strong>Python isolation dependency missing.</strong>
            {' '}On Ubuntu, install <code>sudo apt install bubblewrap util-linux</code> once.
            The editor can still save code; execution remains disabled until
            a network/filesystem-isolated subprocess is available.
            Built-in EMA sweeps work without bubblewrap.</p>}
        <button className="rpl-run" type="button" onClick={runPython} disabled={busyNow||!status?.python_sandbox.available}>
          <Play size={18}/> {busyNow?'Research job running':'Run pasted Python backtest'}</button>
      </>:<>
        <h3><SlidersHorizontal size={18}/> Choose EMA values or find the best five</h3>
        <div className="rpl-ema-modes" role="radiogroup" aria-label="EMA backtest search mode">
          <label><input type="radio" name="ema-search-mode" checked={emaMode==='pair'}
              onChange={()=>setEmaMode('pair')}/>
            <strong>Choose one EMA pair</strong><small>Example: 9 / 21</small></label>
          <label><input type="radio" name="ema-search-mode" checked={emaMode==='selected'}
              onChange={()=>setEmaMode('selected')}/>
            <strong>Choose several EMA values</strong><small>Compare up to 256 pairs</small></label>
          <label><input type="radio" name="ema-search-mode" checked={emaMode==='all'}
              onChange={()=>setEmaMode('all')}/>
            <strong>Test all supported pairs</strong><small>2–150 · 11,026 pairs</small></label>
        </div>
        {emaMode==='pair'&&<>
          <p className="rpl-note">Backtest your chosen fast and slow EMA settings
            using completed BANKNIFTY candles; hold until the opposite
            confirmed crossover or the observed intraday session close.</p>
          <div className="rpl-ema-inputs">
            <label>Fast EMA period
              <input aria-label="Chosen fast EMA period" type="number" min={2} max={149}
                value={pairFast} onChange={e=>setPairFast(Number(e.target.value))}/></label>
            <label>Slow EMA period
              <input aria-label="Chosen slow EMA period" type="number" min={3} max={150}
                value={pairSlow} onChange={e=>setPairSlow(Number(e.target.value))}/></label>
          </div>
        </>}
        {emaMode==='selected'&&<>
          <p className="rpl-note">Enter comma-separated values. QuantLab tests
            every valid fast &lt; slow combination from your two lists
            (up to 256 pairs), and ranks the strongest five.</p>
          <div className="rpl-ema-inputs">
            <label>Fast EMA periods
              <input aria-label="Fast EMA combination list" value={fast}
                onChange={e=>setFast(e.target.value)}/></label>
            <label>Slow EMA periods
              <input aria-label="Slow EMA combination list" value={slow}
                onChange={e=>setSlow(e.target.value)}/></label>
          </div>
        </>}
        {emaMode==='all'&&<div className="rpl-all-warning" role="note">
          <strong>Exhaustive search: 11,026 combinations.</strong>
          Every integer EMA fast &lt; slow, from 2 through 150, is
          evaluated on the selected BANKNIFTY historical window.
          Research runs at low OS priority in a separate process while Dhan
          continues recording. Rankings use training sessions only;
          later sessions are reserved for an independent check if available.
          The top five and top 100 summaries are saved—not just a sample
          of tested pairs.
        </div>}
        <button className="rpl-run" type="button" onClick={runSweep} disabled={busyNow}>
          <Play size={18}/> {busyNow?'Research job running':
            emaMode==='pair'?'Backtest chosen EMA pair':
            emaMode==='all'?'Test all 11,026 EMA combinations':
            'Compare chosen EMA combinations'}</button>
      </>}
    </div>
    {(jobId||job)&&<div className="rpl-progress" role="status">
      <Activity size={18}/>
      <span>{job?.status==='complete'?'Completed and archived':
        (job?.stage||'Preparing local research job')} · {dec(job?.percent||0,0)}%</span>
    </div>}
    {error&&<div className="rpl-error" role="alert">{error}</div>}
    {notice&&<div className="rpl-notice" role="status">{notice}</div>}
    {savedRuns.length>0&&<details className="rpl-saved">
      <summary><Save size={16}/> Load saved research results ({savedRuns.length})</summary>
      <div className="rpl-saved-items">{savedRuns.slice(0,20).map(run=>
        <button key={run.run_id} disabled={busyNow} onClick={()=>{void openRun(run.run_id)}}>
          {run.run_id} · {ist(run.modified_utc)}</button>)}</div>
    </details>}
    {result&&<div className="rpl-results" aria-label="BANKNIFTY Strategy Lab results">
      <div className="rpl-results-head">
        <div><span className="tc-page-kicker">SOURCE-VERIFIED PAPER RESEARCH</span>
          <h3>{result.kind==='python_strategy'?'Custom Python strategy':
            'EMA '+result.best_pair?.fast+' / '+result.best_pair?.slow+' crossover'}</h3>
          <p>{result.evidence.rows} original minute bars across {result.evidence.sessions} sessions
            · {result.evidence.basis}</p></div>
        <button onClick={exportResult}><Download size={16}/> Export JSON</button>
      </div>
      <div className="rpl-kpis">{metrics(result.selected.metrics).map(([name,value])=>
        <div key={name}><small>{name}</small><strong>{value}</strong></div>)}</div>
      {result.validation&&<p className="rpl-note">{result.validation.warning}
        {' '}Train sessions: {result.validation.whole_sessions_train}.
        Holdout sessions: {result.validation.whole_sessions_holdout}.</p>}
      {result.evidence.source_warning&&<p className="rpl-note">{result.evidence.source_warning}</p>}
      {Object.keys(result.selected.metrics.unscored).length>0&&
        <p className="rpl-note">Excluded or incomplete positions: {JSON.stringify(
          result.selected.metrics.unscored)}. No synthetic missing candles or
          invented closing prices are used.</p>}
      {result.overlays.length>0&&<>
        <div className="rpl-graph-controls">
          <label>Graph time window <select aria-label="Research graph zoom" value={zoom}
            onChange={e=>{setZoom(Number(e.target.value))}}>
            <option value={100}>All bars</option>
            <option value={50}>Latest half</option>
            <option value={25}>Latest quarter</option>
            <option value={10}>Latest 10%</option>
          </select></label>
          <span>Hover for synchronized time, prices, and signals. Chart display
            may be decimated; every bar is used for P&L.</span>
        </div>
        <PriceChart data={chart}/>
        <div className="rpl-graph-grid">
          <MiniLine data={drawing} kind="momentum_roc5_pct" label="Momentum · 5-minute rate of change (%)"
           />
          <MiniLine data={drawing} kind="ema_spread_bps" label="EMA spread · fast minus slow (bps)"
           />
          <MiniLine data={drawing} kind="rsi14" label="RSI 14 · overbought 70 / oversold 30"
           />
          <MiniLine data={drawing} kind="account" label="Paper account equity (₹) · index proxy"
           />
        </div>
      </>}
      <p className="rpl-note">EMA spread is the distance between moving averages.
        It is <strong>not</strong> the market bid–ask spread. Real option bid–ask
        spread requires matching recorded Dhan 20-level books, available separately
        under Market Replay; no spread is inferred from index candles.</p>
      {tab==='sweep'&&sweep?.ranked?.length&&<div className="rpl-ranking">
        <h3>Top five EMA strategies · {dec(sweep.combinations_tested,0)} pairs tested</h3>
        <p className="rpl-note">{sweep.ranking_basis||
          'Ranked by training-session index-directional paper returns.'}
          {' '}At least {sweep.min_completed_trades_to_rank||3} completed trades
          required to qualify for the primary ranking.
          {' '}{sweep.qualifying_combinations===undefined?'':dec(sweep.qualifying_combinations,0)+
            ' pairs met that minimum.'}</p>
        <div className="rpl-top-five" aria-label="Top five EMA crossover combinations">
          {(sweep.top_five||sweep.ranked.slice(0,5)).map((row,i)=>
            <article className="rpl-top-card" key={row.fast+'-'+row.slow}>
              <span className="rpl-top-rank">#{i+1} · EMA {row.fast} / {row.slow}</span>
              <strong>{dec(row.training.return_proxy_pct)}% training return</strong>
              <small>{row.training.trade_count} closed trades · {dec(
                row.training.max_closed_trade_drawdown_pct)}% closed-trade drawdown</small>
              <small>{row.holdout?'Holdout: '+dec(row.holdout.return_proxy_pct)+'%':
                'Holdout: insufficient sessions'}</small>
              {row.ranking_eligible===false&&
                <small className="rpl-incomplete">Below minimum trade count · exploratory</small>}
              <button type="button" disabled={busyNow}
                onClick={()=>runPair(row.fast,row.slow)}>View EMA chart and trades</button>
            </article>)}
        </div>
        <details className="rpl-all-ranking">
          <summary>View ranked comparison table · {dec(sweep.ranked_returned||
            sweep.ranked.length,0)} saved of {dec(sweep.combinations_tested,0)} tested</summary>
          <div className="rpl-table-scroll"><table>
            <thead><tr><th>Rank</th><th>Fast / slow</th><th>Train trades</th>
              <th>Train return</th><th>Win rate</th><th>Train max DD</th>
              <th>Holdout return</th><th>Graph</th></tr></thead>
            <tbody>{sweep.ranked.map((row,i)=><tr key={row.fast+'-'+row.slow}>
              <td>{i+1}{row.ranking_eligible===false?'*':''}</td>
              <td>{row.fast} / {row.slow}</td>
              <td>{row.training.trade_count}</td>
              <td>{dec(row.training.return_proxy_pct)}%</td>
              <td>{dec(row.training.win_rate_pct)}%</td>
              <td>{dec(row.training.max_closed_trade_drawdown_pct)}%</td>
              <td>{row.holdout?dec(row.holdout.return_proxy_pct)+'%':'not scored'}</td>
              <td><button type="button" disabled={busyNow}
                onClick={()=>runPair(row.fast,row.slow)}>View chart</button></td>
            </tr>)}</tbody></table>
          </div>
          <p className="rpl-note">* Fewer than three completed positions.
            Results use BANKNIFTY index exposure proxies, not executable CE/PE P&amp;L.</p>
        </details>
      </div>}
      {result.selected.trades.length>0&&<div className="rpl-ranking">
        <h3>Exact signal → next-open paper trades</h3>
        <div className="rpl-table-scroll"><table><thead><tr><th>Direction</th>
          <th>Entry (IST)</th><th>Exit (IST)</th><th>Hold</th><th>Index points</th>
          <th>Paper net P&L</th><th>Exit trigger</th></tr></thead>
          <tbody>{result.selected.trades.slice(-150).map((trade,i)=><tr key={i}>
            <td className={trade.direction==='UP'?'rpl-up':'rpl-down'}>
              {trade.direction==='UP'?'UP · CE signal':'DOWN · PE signal'}</td>
            <td>{ist(trade.entry_utc)}</td><td>{ist(trade.exit_utc)}</td>
            <td>{dec(trade.hold_minutes)} min</td>
            <td>{dec(trade.index_points)}</td>
            <td>{money(trade.net_pnl_proxy_inr)}</td>
            <td>{trade.exit_reason}</td>
          </tr>)}</tbody></table></div>
      </div>}
      <p className="rpl-disclaimer"><ShieldCheck size={15}/> Read-only research. No broker orders.
        A BANKNIFTY index P&L proxy cannot represent executable CE/PE fills;
        always verify contract lot size, premiums, slippage, liquidity and costs
        in the separate historical options backtester.</p>
    </div>}
  </section>
}
