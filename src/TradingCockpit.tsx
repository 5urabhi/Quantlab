import {useCallback, useEffect, useMemo, useRef, useState} from 'react'
import {Clock3, Database, RefreshCw, ShieldCheck} from 'lucide-react'
import './trading-cockpit.css'

type Candle = {timestamp_utc:string;session_ist:string;open:number;high:number;low:number;close:number;volume:number;ema9:number|null;ema21:number|null}
type Entry = {id:string;created_utc:string;identity:string;bar_utc:string;direction:string;reference_close:number;horizon_minutes:number;quote_mode:string;evaluation:string;observed_close:number|null;actual_direction:string|null}
type Snapshot = {identity:string;model_version:string;horizon_minutes:number;quote_mode:string;last_observed_utc:string;source_age_seconds:number;direction:'UP'|'DOWN'|'NO_TRADE';confidence:null;validation:string;latest_close:number;rsi14:number|null;atr14:number|null;ema9:number|null;ema21:number|null;rows:Candle[];note:string;source_warning:string;has_more:boolean}
type Catalog = {instruments:{identity:string;display_name?:string;asset_class?:string;ready:boolean;state:string}[]}
type History = {predictions:Entry[];summary:{evaluated_directions:number;correct_directions:number;direction_accuracy:number|null;qualification:string}}
type DaySummary = {session_ist:string;total:number;scored:number;correct:number;incorrect:number;pending:number;no_trade:number;flat:number;unverifiable:number;directional_accuracy:number|null}
type Report = {days:DaySummary[];overall:Omit<DaySummary,'session_ist'>;source:string;disclaimer:string;truncated:boolean}
type Replay = {mode:string;identity:string;model_version:string;horizon_minutes:number;observed_source_bars:number;overall:Omit<DaySummary,'session_ist'>;days:DaySummary[];has_more_history:boolean;source_warning:string;disclaimer:string}

async function api<T>(path:string,init?:RequestInit):Promise<T>{
  const response=await fetch(path,init)
  if(!response.ok){
    let detail='Local analysis unavailable'
    try{const result=await response.json() as {detail?:string};detail=result.detail||detail}catch{/* no body */}
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}
const fmt=(v:number|null|undefined,digits=2)=>v===null||v===undefined?'—':v.toLocaleString('en-IN',{maximumFractionDigits:digits})
const post=(path:string,body:unknown)=>api<unknown>(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})

function CandleChart({rows}:{rows:Candle[]}){
  const [hover,setHover]=useState<number|null>(null)
  const data=rows.slice(-150)
  if(!data.length)return <p className="tc-muted">No original one-minute data available.</p>
  const values=data.flatMap(c=>[c.low,c.high,c.ema9??c.close,c.ema21??c.close])
  const min=Math.min(...values),max=Math.max(...values),range=Math.max(0.001,max-min)
  const height=310, width=970, left=54,right=16,top=18,bottom=27,chartW=width-left-right,chartH=height-top-bottom
  const x=(i:number)=>left+(i+.5)*chartW/data.length
  const y=(p:number)=>top+(max-p)/range*chartH
  const line=(key:'ema9'|'ema21')=>data.map((r,i)=>r[key]===null?'':`${i===0?'M':'L'}${x(i).toFixed(1)},${y(r[key]!).toFixed(1)}`).join(' ')
  const step=chartW/data.length
  const selected=hover===null?data[data.length-1]:data[hover]
  return <div className="tc-chart">
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Observed one-minute OHLC candles with 9 and 21-period EMA" onMouseMove={event=>{
      const rect=event.currentTarget.getBoundingClientRect()
      const px=(event.clientX-rect.left)/rect.width*width
      setHover(Math.max(0,Math.min(data.length-1,Math.floor((px-left)/chartW*data.length))))
    }} onMouseLeave={()=>setHover(null)}>
      {[0,.25,.5,.75,1].map(f=><g key={f}><line x1={left} y1={top+f*chartH} x2={width-right} y2={top+f*chartH} stroke="#28364c" strokeDasharray="3 5"/><text x="4" y={top+f*chartH+4} fontSize="12" fill="#9eafc4">{fmt(max-f*range,0)}</text></g>)}
      {data.map((r,i)=><g key={r.timestamp_utc} stroke={r.close>=r.open?'#2ed3a2':'#f37b86'} fill={r.close>=r.open?'#2ed3a2':'#f37b86'}>
        <line x1={x(i)} x2={x(i)} y1={y(r.high)} y2={y(r.low)}/>
        <rect x={x(i)-Math.max(.7,step*.32)} y={Math.min(y(r.open),y(r.close))} width={Math.max(1.4,step*.64)} height={Math.max(1,Math.abs(y(r.open)-y(r.close)))}/>
      </g>)}
      <path d={line('ema9')} fill="none" stroke="#e9ae57" strokeWidth="1.8"/>
      <path d={line('ema21')} fill="none" stroke="#72b3fa" strokeWidth="1.8"/>
      {hover!==null&&<line x1={x(hover)} x2={x(hover)} y1={top} y2={top+chartH} stroke="#dce9f8" opacity=".65" strokeDasharray="3 5"/>}
      <text x={left} y={height-5} fill="#99aabd" fontSize="12">{data[0].session_ist}</text>
      <text x={width-110} y={height-5} fill="#99aabd" fontSize="12">{new Date(data[data.length-1].timestamp_utc).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit'})} IST</text>
    </svg>
    <div className="tc-chart-caption">{new Date(selected.timestamp_utc).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'})} · O {fmt(selected.open)} · H {fmt(selected.high)} · L {fmt(selected.low)} · C {fmt(selected.close)} · Vol {fmt(selected.volume,0)}</div>
  </div>
}

export default function TradingCockpit(){
  const [instruments,setInstruments]=useState<Catalog['instruments']>([])
  const [identity,setIdentity]=useState('')
  const [snapshot,setSnapshot]=useState<Snapshot|null>(null)
  const [history,setHistory]=useState<History|null>(null)
  const [report,setReport]=useState<Report|null>(null)
  const [replay,setReplay]=useState<Replay|null>(null)
  const [replayBusy,setReplayBusy]=useState(false)
  const [monitor,setMonitor]=useState(false)
  const monitorRef=useRef(false)
  const [horizon,setHorizon]=useState<3|6>(6)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [recordMessage,setRecordMessage]=useState('')
  const [now,setNow]=useState(()=>Date.now())
  const [startTime,setStartTime]=useState<number|null>(()=>{
    try{const stored=window.localStorage.getItem('quantlab:manual-six-minute-timer')
      const value=stored?Number(stored):null
      return value!==null&&Number.isFinite(value)&&value>0&&value<=Date.now()?value:null
    }catch{return null}
  })
  const [paused,setPaused]=useState(false)

  useEffect(()=>{
    try{
      if(startTime===null)window.localStorage.removeItem('quantlab:manual-six-minute-timer')
      else window.localStorage.setItem('quantlab:manual-six-minute-timer',String(startTime))
    }catch{/* private browsing or disabled storage */}
  },[startTime])
  useEffect(()=>{let active=true;void api<Catalog>('/api/trading-cockpit/instruments').then(data=>{
    if(!active)return
    setInstruments(data.instruments)
    setIdentity(previous=>data.instruments.some(x=>x.identity===previous)?previous:(data.instruments.find(x=>x.ready)?.identity||''))
  }).catch(e=>{if(active)setError(String(e))});return()=>{active=false}},[])
  const refresh=useCallback(async()=>{
    if(!identity)return
    setError('')
    try{
      if(monitorRef.current){
        await post('/api/trading-cockpit/monitor/tick',{identity,horizon_minutes:6})
      }
      const [observed,ledger,daily]=await Promise.all([
        api<Snapshot>('/api/trading-cockpit/snapshot?'+new URLSearchParams({identity,limit:'500'})),
        api<History>('/api/trading-cockpit/predictions?'+new URLSearchParams({identity,limit:'60'})),
        api<Report>('/api/trading-cockpit/report?'+new URLSearchParams({identity})),
      ])
      setSnapshot(observed);setHistory(ledger);setReport(daily)
    }catch(e){setError(e instanceof Error?e.message:String(e))}
  },[identity])
  useEffect(()=>{setSnapshot(null);setHistory(null);setReplay(null);setReport(null);void refresh()},[refresh])
  useEffect(()=>{
    const timer=window.setInterval(()=>setNow(Date.now()),1000)
    return()=>window.clearInterval(timer)
  },[])
  useEffect(()=>{
    if(!identity||paused)return
    const timer=window.setInterval(()=>{void refresh()},15000)
    return()=>window.clearInterval(timer)
  },[identity,refresh,paused])
  const action=async(kind:'record'|'evaluate')=>{
    if(!identity||busy)return
    setBusy(true);setRecordMessage('');setError('')
    try{
      if(kind==='record'){
        const recorded=await post('/api/trading-cockpit/predictions',{identity,horizon_minutes:horizon}) as Entry
        setRecordMessage('Saved unchanged: '+recorded.direction+' at '+recorded.bar_utc)
      }else{
        const data=await post('/api/trading-cockpit/evaluate',{identity,horizon_minutes:horizon}) as History & {updated:number}
        setRecordMessage('Evaluated '+data.updated+' predictions against available source bars.')
      }
      await refresh()
    }catch(e){setError(e instanceof Error?e.message:String(e))}
    finally{setBusy(false)}
  }
  const runReplay=async()=>{
    if(!identity||replayBusy)return
    setReplayBusy(true);setError('')
    try{
      const result=await api<Replay>('/api/trading-cockpit/replay?'+
        new URLSearchParams({identity,horizon_minutes:String(horizon),limit:'1500'}))
      setReplay(result)
    }catch(e){setError(e instanceof Error?e.message:String(e))}
    finally{setReplayBusy(false)}
  }
  const elapsed=startTime===null?0:Math.floor((now-startTime)/1000)
  const remaining=Math.max(0,6*60-elapsed)
  const countdown=`${String(Math.floor(remaining/60)).padStart(2,'0')}:${String(remaining%60).padStart(2,'0')}`
  const forecast=snapshot?.direction??'NO_TRADE'
  const sourceRecent=snapshot?.quote_mode==='RECENT_LOCAL_CANDLE_NOT_VERIFIED_LIVE'
  const summary=history?.summary
  const dataStatus=useMemo(()=>{
    if(!snapshot)return 'NO ORIGINAL DATA'
    return sourceRecent?'RECENT CANDLE · NOT LIVE QUOTE':'HISTORICAL · NOT LIVE'
  },[snapshot,sourceRecent])
  return <div className="tc-shell">
    <header className="tc-header"><div><div className="tc-eyebrow">QUANTLAB / READ-ONLY MARKET RESEARCH</div><h2>Intraday trading cockpit</h2><p>One-minute observed candles · 3/6-minute forecasts · permanent outcome audit</p></div><span className={'tc-data-badge '+(sourceRecent?'tc-recent':'')}>{dataStatus}</span></header>
    {error&&<div className="tc-error" role="alert">{error}</div>}
    <div className="tc-toolbar"><label>Local instrument <select aria-label="Trading cockpit instrument" value={identity} onChange={event=>setIdentity(event.target.value)}><option value="">Select prepared minute candles</option>{instruments.map(s=><option key={s.identity} value={s.identity} disabled={!s.ready}>{s.display_name||s.identity} ({s.identity}){s.ready?'':' · Source unavailable'}</option>)}</select></label><label className="tc-monitor-toggle"><input type="checkbox" checked={monitor} onChange={event=>{
  const enabled=event.target.checked;setMonitor(enabled);monitorRef.current=enabled
  if(enabled)void refresh()
}}/> Auto-audit while this page is open</label><button onClick={()=>void refresh()} disabled={!identity}><RefreshCw size={16}/> Refresh</button><button onClick={()=>setPaused(v=>!v)}>{paused?'Resume observations':'Pause updates'}</button><span className="tc-muted"><ShieldCheck size={14}/> No broker execution</span></div>
    {!instruments.some(x=>x.ready)&&<p className="tc-missing"><Database size={17}/> No prepared minute candles found. Use Data Library → Download market data. Bank Nifty and Nifty index analysis requires the original Dhan IDX_I one-minute spot batch. No surrogate or simulated prices are used.</p>}
    <div className="tc-layout">
      <section className="tc-panel tc-main">
        <div className="tc-panel-title"><strong>Price action</strong><span>1-minute original OHLC · EMA 9 / EMA 21</span></div>
        {snapshot?<><div className="tc-price">{fmt(snapshot.latest_close)} <small>at {new Date(snapshot.last_observed_utc).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'})} IST</small></div><CandleChart rows={snapshot.rows}/><div className="tc-metrics"><div>EMA 9 <strong>{fmt(snapshot.ema9)}</strong></div><div>EMA 21 <strong>{fmt(snapshot.ema21)}</strong></div><div>RSI 14 <strong>{fmt(snapshot.rsi14)}</strong></div><div>ATR 14 <strong>{fmt(snapshot.atr14)}</strong></div></div></>:<p className="tc-missing">Select an instrument with verified local one-minute candles.</p>}
      </section>
      <section className="tc-panel tc-signal">
        <div className="tc-panel-title"><strong>Next {horizon} minutes</strong><span>Rule baseline v1</span></div>
        <div className="tc-horizon"><button className={horizon===3?'active':''} onClick={()=>setHorizon(3)}>3 MIN</button><button className={horizon===6?'active':''} onClick={()=>setHorizon(6)}>6 MIN</button></div>
        <div className={'tc-direction '+forecast.toLowerCase()}>{forecast==='UP'?'UPWARD BIAS':forecast==='DOWN'?'DOWNWARD BIAS':'NO TRADE'}</div>
        <p className="tc-muted">Unvalidated technical rule. Not a measured win probability or options recommendation.</p>
        <div className="tc-audit-info"><div>Source age <strong>{snapshot?fmt(snapshot.source_age_seconds,0)+' sec':'—'}</strong></div><div>Confidence <strong>Not calibrated</strong></div><div>Option price <strong>Not connected</strong></div><div>Model status <strong>Research only</strong></div></div>
        <button className="tc-primary" disabled={!snapshot||busy||!sourceRecent} onClick={()=>void action('record')}>Record prospective prediction</button>
        {!sourceRecent&&<p className="tc-warning">Prediction recording is disabled for historical or stale candles. This prevents retroactively claiming a past observation as a live prediction.</p>}
      </section>
      <section className="tc-panel tc-timer">
        <div className="tc-panel-title"><strong>Six-minute trade discipline</strong><Clock3 size={16}/></div>
        <div className={'tc-clock '+(elapsed>=360?'tc-overdue':'')}>{countdown}</div>
        <p className="tc-muted">Local manual reminder. No order placement, automatic stop or guaranteed exit.</p>
        <div className="tc-actions"><button onClick={()=>setStartTime(Date.now())}>Start on fill</button><button onClick={()=>setStartTime(null)}>Reset</button></div>
        {startTime!==null&&<p className={elapsed>=360?'tc-warning':'tc-muted'}>{elapsed>=360?'Planned holding period exceeded — reassess or exit manually.':elapsed>=300?'Final minute — check exit plan.':'Timer running from your manual start.'}</p>}
      </section>
    </div>
    <section className="tc-panel tc-ledger"><div className="tc-panel-title"><strong>Permanent prediction ledger</strong><button onClick={()=>void action('evaluate')} disabled={!identity||busy}>Evaluate recorded outcomes</button></div>
      <div className="tc-ledger-summary"><span>Scored directions <strong>{summary?.evaluated_directions??0}</strong></span><span>Correct directions <strong>{summary?.correct_directions??0}</strong></span><span>Directional accuracy <strong>{summary?.direction_accuracy===null||summary?.direction_accuracy===undefined?'Not enough observations':(summary.direction_accuracy*100).toFixed(1)+'%'}</strong></span></div>
      {recordMessage&&<p role="status" className="tc-confirm">{recordMessage}</p>}
      <p className="tc-muted">Directional accuracy excludes no-trade decisions, flat moves and unverifiable source gaps. No historical option P&L is inferred from spot candles.</p>
      <div className="tc-table-scroll"><table><thead><tr><th>Recorded UTC</th><th>Source bar UTC</th><th>Signal</th><th>Horizon</th><th>Reference</th><th>Observed</th><th>Outcome</th></tr></thead><tbody>{history?.predictions.map(x=><tr key={x.id}><td>{x.created_utc.slice(0,19)}</td><td>{x.bar_utc.slice(0,19)}</td><td>{x.direction}</td><td>{x.horizon_minutes}m</td><td>{fmt(x.reference_close)}</td><td>{fmt(x.observed_close)}</td><td>{x.evaluation.replaceAll('_',' ')}</td></tr>)}{!history?.predictions.length&&<tr><td colSpan={7}>No prospective predictions logged for this instrument yet.</td></tr>}</tbody></table></div>
    </section>
  </div>
}
