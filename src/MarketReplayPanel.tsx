import {useEffect,useMemo,useState} from 'react'
import {CalendarDays,ChevronLeft,ChevronRight,Pause,Play,RotateCcw,Database,AlertTriangle} from 'lucide-react'
import CandleChart,{type Candle} from './TradingCandleChart'
import {marketApi,readableError,MarketApiError} from './tradingCockpitApi'

type Instrument={identity:string;display_name?:string;asset_class?:string;ready:boolean}
type OriginalBar=Omit<Candle,'ema9'|'ema21'>
type Session={date_ist:string;observed_bars:number;first_utc:string;last_utc:string}
type OriginalSeries={identity:string;interval_minutes:number;rows:OriginalBar[];sessions:Session[];
  source:string;source_warning:string;has_more:boolean;kind:string;note:string}
const fmt=(v:number|null|undefined,digits=2)=>
  v===null||v===undefined?'—':v.toLocaleString('en-IN',{maximumFractionDigits:digits})
const showTime=(v:string)=>new Date(v).toLocaleTimeString('en-IN',{
  timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit',hourCycle:'h23'})
function decorate(rows:OriginalBar[]):Candle[]{
  let ema9=0,ema21=0
  const closes:number[]=[]
  return rows.map(row=>{
    closes.push(row.close)
    if(closes.length===9)ema9=closes.slice(0,9).reduce((a,b)=>a+b,0)/9
    else if(closes.length>9)ema9=(2/10)*row.close+(1-2/10)*ema9
    if(closes.length===21)ema21=closes.slice(0,21).reduce((a,b)=>a+b,0)/21
    else if(closes.length>21)ema21=(2/22)*row.close+(1-2/22)*ema21
    return {...row,ema9:closes.length>=9?ema9:null,ema21:closes.length>=21?ema21:null}
  })
}

export default function MarketReplayPanel({instruments,onOpenData}:{
  instruments:Instrument[],onOpenData:()=>void
}){
  const ready=instruments.filter(x=>x.ready)
  const [identity,setIdentity]=useState('INDEX:BANKNIFTY')
  const [series,setSeries]=useState<OriginalSeries|null>(null)
  const [session,setSession]=useState('')
  const [cursor,setCursor]=useState(0)
  const [speed,setSpeed]=useState<1|3|6>(1)
  const [playing,setPlaying]=useState(false)
  const [loading,setLoading]=useState(false)
  const [error,setError]=useState<unknown>(null)
  useEffect(()=>{
    setIdentity(current=>ready.some(x=>x.identity===current)?current:
      ready.find(x=>x.identity==='INDEX:BANKNIFTY')?.identity||
      ready.find(x=>x.identity==='INDEX:NIFTY50')?.identity||
      ready[0]?.identity||'')
  },[instruments])
  useEffect(()=>{
    if(!identity){setSeries(null);setError(null);setLoading(false);return}
    let mounted=true
    setLoading(true);setError(null);setSeries(null);setPlaying(false)
    void marketApi<OriginalSeries>('/api/trading-cockpit/historical/series?'+
      new URLSearchParams({identity,limit:'5000'}))
      .then(data=>{if(mounted){
        setSeries(data)
        setSession(data.sessions[0]?.date_ist||'')
        setCursor(0)
      }})
      .catch(err=>{if(mounted)setError(err)})
      .finally(()=>{if(mounted)setLoading(false)})
    return()=>{mounted=false}
  },[identity])
  const dayRows=useMemo(()=>series?.rows.filter(x=>x.session_ist===session)||[],
    [series,session])
  const augmented=useMemo(()=>decorate(dayRows),[dayRows])
  const at=Math.min(cursor,Math.max(0,dayRows.length-1))
  const shown=augmented.slice(0,at+1)
  const current=dayRows[at]
  const first=dayRows[0]
  const elapsedPct=dayRows.length<2?0:100*at/(dayRows.length-1)
  const move=current&&first?(current.close/first.open-1)*100:0
  const missingBefore=at>0?Math.round((Date.parse(dayRows[at].timestamp_utc)-
     Date.parse(dayRows[at-1].timestamp_utc))/60000)-1:0
  const stop=()=>setPlaying(false)
  useEffect(()=>{
    if(!playing||dayRows.length<2)return
    const timer=window.setInterval(()=>{
      setCursor(index=>{
        if(index>=dayRows.length-1){setPlaying(false);return dayRows.length-1}
        return index+1
      })
    },Math.round(700/speed))
    return()=>window.clearInterval(timer)
  },[playing,dayRows.length,speed])
  return <section className="tc-replay-market" aria-label="Historical market replay">
    <div className="tc-page-intro tc-replay-head">
      <div><span className="tc-page-kicker">HISTORICAL MARKET REPLAY</span>
        <h3>Replay an actual market session</h3>
        <p>Move through original one-minute candles as they happened. Future bars remain hidden until you reach them.</p>
      </div>
      <span className="tc-data-badge">HISTORICAL · NEVER LIVE</span>
    </div>
    <div className="tc-replay-picker">
      <label>Instrument
        <select aria-label="Historical replay instrument" value={identity}
          onChange={e=>{stop();setIdentity(e.target.value)}}>
          {ready.length===0&&<option value="">No prepared sources</option>}
          {ready.map(i=><option key={i.identity} value={i.identity}>{i.display_name||i.identity}</option>)}
        </select>
      </label>
      <label>Recorded IST session
        <select aria-label="Replay trading session" value={session} disabled={!series?.sessions.length}
          onChange={e=>{stop();setSession(e.target.value);setCursor(0)}}>
          {(series?.sessions||[]).map(d=><option value={d.date_ist} key={d.date_ist}>
            {d.date_ist} · {d.observed_bars} observed minutes
          </option>)}
        </select>
      </label>
      <div className="tc-replay-source-status">
        <strong>{loading?'Loading original candles':series?'Source ready':'No chart source loaded'}</strong>
        <small>{series?.has_more?'Latest 5,000 observed candles shown; older source data exists':
          series?'Only original saved candles are shown': 'No fabricated price history'}</small>
      </div>
    </div>
    {error!==null&&<div className="tc-api-help" role="alert">
      <AlertTriangle size={21}/><div><strong>Unable to open this historical source</strong>
        <p>{readableError(error)}</p>
        <small>{error instanceof MarketApiError?error.hint:
          'The original data may need preparation or a new download.'}</small>
      </div><button type="button" onClick={onOpenData}>Open Connections &amp; Data</button>
    </div>}
    {!loading&&!ready.length&&<div className="tc-replay-empty"><Database size={24}/>
      <div><strong>Prepare one source, not another dataset</strong>
        <p>Your shared Market Library can reuse previously downloaded BANKNIFTY/NIFTY 50 candles.</p></div>
      <button type="button" onClick={onOpenData}>Prepare original minute candles</button></div>}
    {series&&current&&<div className="tc-replay-card">
      <div className="tc-replay-overview">
        <div><span className="tc-page-kicker"><CalendarDays size={14}/> {session} · recorded session</span>
          <strong>{fmt(current.close)} <small>index points / source price</small></strong>
          <p>{showTime(current.timestamp_utc)} IST · Bar {at+1} of {dayRows.length} ·
            <span className={move>=0?'tc-replay-positive':'tc-replay-negative'}> {move>=0?'+':''}{fmt(move,2)}% since first observed open</span></p>
        </div>
        <span className="tc-replay-tag">RECORDED DATA · NO LIVE FEED</span>
      </div>
      <CandleChart rows={shown}/>
      {missingBefore>0&&<p className="tc-warning"><AlertTriangle size={15}/> The original source has a {missingBefore}-minute gap before this observation. QuantLab did not fill it.</p>}
      <div className="tc-replay-controls">
        <button aria-label="Start of session" type="button" onClick={()=>{stop();setCursor(0)}}><RotateCcw size={16}/></button>
        <button aria-label="Previous observed minute" type="button"
          onClick={()=>{stop();setCursor(v=>Math.max(0,v-1))}} disabled={at===0}>
          <ChevronLeft size={16}/> Previous</button>
        <button className="tc-replay-play" type="button"
          onClick={()=>{if(dayRows.length<2)return;if(at>=dayRows.length-1)setCursor(0);setPlaying(v=>!v)}}>
          {playing?<><Pause size={17}/> Pause</>:<><Play size={17}/> Play session</>}</button>
        <button aria-label="Next observed minute" type="button" disabled={at>=dayRows.length-1}
          onClick={()=>{stop();setCursor(v=>Math.min(dayRows.length-1,v+1))}}>Next <ChevronRight size={16}/></button>
        <label>Speed <select value={speed} onChange={e=>setSpeed(Number(e.target.value) as 1|3|6)}>
          <option value="1">1×</option><option value="3">3×</option><option value="6">6×</option>
        </select></label>
      </div>
      <label className="tc-replay-timeline">Observed timeline <span>{Math.round(elapsedPct)}%</span>
        <input type="range" min="0" max={Math.max(0,dayRows.length-1)} value={at}
          onChange={e=>{stop();setCursor(Number(e.target.value))}}/>
        <div><small>{showTime(dayRows[0].timestamp_utc)}</small>
          <small>{showTime(dayRows[dayRows.length-1].timestamp_utc)}</small></div>
      </label>
      <div className="tc-replay-metrics">
        <span>Open <b>{fmt(current.open)}</b></span><span>High <b>{fmt(current.high)}</b></span>
        <span>Low <b>{fmt(current.low)}</b></span><span>Close <b>{fmt(current.close)}</b></span>
        <span>EMA 9 <b>{fmt(shown[shown.length-1]?.ema9)}</b></span>
        <span>EMA 21 <b>{fmt(shown[shown.length-1]?.ema21)}</b></span>
      </div>
      <p className="tc-muted">Source: {series.source}. {series.source_warning||'Original Dhan minute observations.'}
        No historical option fills, broker execution, or future-candle predictions are implied.</p>
    </div>}
    {!loading&&!series&&!error&&ready.length>0&&<p className="tc-missing">
      Choose a prepared original index or equity source to start a recorded session.</p>}
  </section>
}
