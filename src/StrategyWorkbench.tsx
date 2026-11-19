import {useCallback,useEffect,useState} from 'react'
import {AlertTriangle,ArrowRight,BarChart3,CheckCircle2,Database,RefreshCw,Target,TrendingDown,TrendingUp,Clock3} from 'lucide-react'
import {marketApi,marketPost,MarketApiError,readableError} from './tradingCockpitApi'
import './signal-backtest.css'

type Source={identity:string;display_name?:string;ready:boolean;asset_class?:string}
type Counts={
  total:number;scored:number;correct:number;incorrect:number;pending:number;
  no_trade:number;flat:number;unverifiable:number;directional_accuracy:number|null;
  up_signals:number;down_signals:number;actual_up:number;actual_down:number;
  live_observed:number;local_observed:number
}
type Day=Counts&{session_ist:string}
type HistoricalEvent={
  bar_utc:string;session_ist:string;horizon_minutes:number;
  direction:'UP'|'DOWN'|'NO_TRADE';reference_close:number;
  observed_close:number|null;movement_bps:number|null;
  actual_direction:'UP'|'DOWN'|'FLAT'|null;evaluation:string
}
type HistoricalResult={
  identity:string;horizon_minutes:3|6;observed_source_bars:number;
  model_version:string;mode:'RETROSPECTIVE_HISTORICAL_RULE_REPLAY';
  overall:Counts;days:Day[];latest_events:HistoricalEvent[];
  disclaimer:string;source_warning:string;has_more_history:boolean
}
type ForwardReport={
  identity:string;horizon_minutes:number|null;
  overall:Counts;days:Day[];source:string;disclaimer:string;truncated:boolean
}
type ForwardEntry={
  id:string;created_utc:string;bar_utc:string;identity:string;
  reference_close:number;observed_close:number|null;actual_direction:string|null;
  direction:string;horizon_minutes:number;quote_mode:string;evaluation:string
}
type ForwardLedger={predictions:ForwardEntry[]}

const INDEX='INDEX:BANKNIFTY'
const fmt=(n:number|null|undefined,d=2)=>
  n===null||n===undefined?'—':n.toLocaleString('en-IN',{maximumFractionDigits:d})
const score=(n:number|null)=>n===null?'Not enough scored signals':fmt(n*100,1)+'%'
const timeIST=(date:string)=>new Date(date).toLocaleString('en-IN',{
  timeZone:'Asia/Kolkata',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})
const moveText=(bps:number|null)=>{
  if(bps===null)return '—'
  return (bps>0?'+':'')+fmt(bps/100,3)+'%'
}
const outcome=(value:string)=>({
  CORRECT:'Correct',INCORRECT:'Incorrect',NO_TRADE_REVIEWED:'No trade',
  FLAT:'Flat',PENDING:'Awaiting outcome',UNVERIFIABLE_GAP:'Missing observation',
}[value]||value.replaceAll('_',' '))

export default function StrategyWorkbench({instruments,onOpenData,onOpenReplay}:{
  instruments:Source[],onOpenData:()=>void,onOpenReplay:()=>void
}){
  const [limit,setLimit]=useState<'500'|'1500'|'3000'|'5000'>('1500')
  const [results,setResults]=useState<Partial<Record<3|6,HistoricalResult>>>({})
  const [selected,setSelected]=useState<3|6>(6)
  const [showAll,setShowAll]=useState(false)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState<unknown>(null)
  const [recorded,setRecorded]=useState<Partial<Record<3|6,ForwardReport>>>({})
  const [ledger,setLedger]=useState<ForwardLedger|null>(null)
  const [recordedBusy,setRecordedBusy]=useState(false)
  const [scoredNew,setScoredNew]=useState<number|null>(null)
  const [recordedError,setRecordedError]=useState<unknown>(null)
  const ready=instruments.some(s=>s.identity===INDEX&&s.ready)
  const tested=results[selected]
  const testsDone=Boolean(results[3]&&results[6])
  const noActionable=testsDone&&results[3]?.overall.scored===0&&results[6]?.overall.scored===0

  const refreshForward=useCallback(async()=>{
    setRecordedBusy(true);setRecordedError(null);setScoredNew(null)
    try{
      // Reconcile only from original prepared or locally captured live bars,
      // each with its own source provenance. These are read-only local APIs.
      const request={identity:INDEX,horizon_minutes:6}
      const reconciled=await Promise.allSettled([
        marketPost<{updated:number}>('/api/trading-cockpit/evaluate',request),
        marketPost<{updated:number}>('/api/trading-cockpit/live/evaluate',request),
      ])
      const updated=reconciled.reduce((sum,r)=>
        sum+(r.status==='fulfilled'?r.value.updated:0),0)
      setScoredNew(updated)
      const [three,six,observed]=await Promise.all([
        marketApi<ForwardReport>('/api/trading-cockpit/report?'+new URLSearchParams({
          identity:INDEX,horizon_minutes:'3'})),
        marketApi<ForwardReport>('/api/trading-cockpit/report?'+new URLSearchParams({
          identity:INDEX,horizon_minutes:'6'})),
        marketApi<ForwardLedger>('/api/trading-cockpit/predictions?'+new URLSearchParams({
          identity:INDEX,limit:'100'})),
      ])
      setRecorded({3:three,6:six});setLedger(observed)
    }catch(e){setRecordedError(e)}
    finally{setRecordedBusy(false)}
  },[])
  useEffect(()=>{void refreshForward()},[refreshForward])

  const runTest=async()=>{
    if(busy||!ready)return
    setBusy(true);setError(null);setResults({})
    try{
      const [three,six]=await Promise.all([3,6].map(horizon=>
        marketApi<HistoricalResult>('/api/trading-cockpit/replay?'+
          new URLSearchParams({identity:INDEX,horizon_minutes:String(horizon),limit}))))
      setResults({3:three,6:six})
    }catch(e){setError(e)}
    finally{setBusy(false)}
  }
  const detailed=(tested?.latest_events||[]).filter(row=>
    showAll||row.direction!=='NO_TRADE')
  const recentForward=(ledger?.predictions||[]).filter(row=>row.horizon_minutes===selected)
    .slice(0,25)

  return <div className="tc-signal-workbench" aria-label="BANKNIFTY signal backtest workspace">
    <div className="tc-v4-intro">
      <div><span className="tc-page-kicker">PHASE 1 · DIRECTION FIRST</span>
        <h3>BANKNIFTY Signal Backtest</h3>
        <p>Did our UP or DOWN signal correctly predict the BANKNIFTY index after 3 or 6 minutes? Compare historical rule replay with predictions actually recorded forward in time.</p>
      </div>
      <span className="tc-signal-tag"><Target size={15}/> Direction only · no option P&amp;L</span>
    </div>

    <section className="tc-panel tc-signal-main" aria-label="Historical BANKNIFTY signal accuracy">
      <div className="tc-panel-title">
        <div><strong><BarChart3 size={17}/> Historical signal backtest</strong>
          <p className="tc-muted">Fixed EMA/RSI rule, evaluated minute-by-minute on original BANKNIFTY index candles. The rule sees no future data when issuing a signal.</p>
        </div>
        <span className="tc-signal-provenance">HISTORICAL REPLAY · NOT RECORDED LIVE</span>
      </div>
      <div className="tc-signal-controls">
        <div className="tc-signal-source">
          {ready?<CheckCircle2 size={20}/>:<AlertTriangle size={20}/>}
          <div><strong>BANKNIFTY spot (IDX_I)</strong>
            <span>{ready?'Original one-minute source available in dhan_shared':
              'Original BANKNIFTY one-minute source is missing or not prepared'}</span></div>
        </div>
        <label>Historical window
          <select aria-label="Historical signal window" value={limit}
            onChange={e=>{setLimit(e.target.value as typeof limit);setResults({})}}>
            <option value="500">Last 500 minutes</option>
            <option value="1500">Last 1,500 minutes</option>
            <option value="3000">Last 3,000 minutes</option>
            <option value="5000">Last 5,000 minutes</option>
          </select>
        </label>
        <button className="tc-signal-run" type="button" onClick={()=>void runTest()} disabled={busy||!ready}>
          <Target size={16}/>{busy?'Checking both horizons…':'Test 3m and 6m signals'}
        </button>
      </div>
      {!ready&&<div className="tc-signal-recover">
        <Database size={19}/><div><strong>Only the actual index can answer this question.</strong>
          <p>Existing bank-stock data cannot substitute for the BANKNIFTY index. Reuse or fetch original IDX_I minute observations through the shared data library.</p></div>
        <button type="button" onClick={onOpenData}>Prepare BANKNIFTY data <ArrowRight size={15}/></button>
      </div>}
      {error!==null&&<div className="tc-api-help" role="alert"><AlertTriangle size={19}/>
        <div><strong>Historical signal backtest could not run</strong>
          <p>{readableError(error)}</p>
          <small>{error instanceof MarketApiError?error.hint:
            'Inspect the original source; the software has not invented missing candles.'}</small></div>
        <button type="button" onClick={onOpenData}>Review source</button></div>}
      {testsDone?<div className="tc-signal-scorecards">
        {([3,6] as const).map(horizon=>{
          const data=results[horizon]!
          return <button key={horizon} type="button" className={'tc-signal-scorecard '+(selected===horizon?'selected':'')}
            onClick={()=>setSelected(horizon)} aria-pressed={selected===horizon}>
            <div className="tc-signal-scorecard-title"><span>{horizon}-minute horizon</span>
              <strong>{score(data.overall.directional_accuracy)}</strong></div>
            <div className="tc-signal-tally">
              <span><b className="good">{data.overall.correct}</b> Correct</span>
              <span><b className="bad">{data.overall.incorrect}</b> Incorrect</span>
              <span><b>{data.overall.no_trade}</b> No trade</span>
              <span><b>{data.overall.unverifiable}</b> Source gaps</span>
            </div>
            <small>Accuracy = correct ÷ ({data.overall.correct} correct + {data.overall.incorrect} incorrect). Flat outcomes excluded.</small>
          </button>
        })}
      </div>:!busy&&ready&&<div className="tc-signal-prompt">
        <TrendingUp size={22}/><div><strong>Run the 3-minute and 6-minute tests together.</strong>
          <p>The tool will replay each historical bar using the information available at that point, then compare the signal with the observed BANKNIFTY move.</p></div>
      </div>}
      {noActionable&&<p className="tc-signal-caution"><AlertTriangle size={18}/>
        The current EMA/RSI baseline produced no scored UP/DOWN predictions in this window.
        This is a valid finding, not 100% accuracy; review the NO TRADE count and source coverage.</p>}
      {tested&&<div className="tc-signal-detail">
        <div className="tc-signal-detail-head">
          <div><span className="tc-page-kicker">HISTORICAL REPLAY · {selected} MINUTES</span>
            <h4>What the model predicted versus what happened</h4></div>
          <label><input type="checkbox" checked={showAll} onChange={e=>setShowAll(e.target.checked)}/>
            Include NO TRADE decisions</label>
        </div>
        <div className="tc-signal-metrics">
          <span>Historical minutes <strong>{fmt(tested.observed_source_bars,0)}</strong></span>
          <span>UP signals <strong>{tested.overall.up_signals}</strong></span>
          <span>DOWN signals <strong>{tested.overall.down_signals}</strong></span>
          <span>Flat outcome <strong>{tested.overall.flat}</strong></span>
          <span>Not scorable <strong>{tested.overall.unverifiable}</strong></span>
        </div>
        <div className="tc-table-scroll tc-signal-event-table">
          <table><thead><tr>
            <th>IST signal time</th><th>Predicted</th><th>Index at signal</th>
            <th>Index after {selected}m</th><th>Observed movement</th>
            <th>Actually moved</th><th>Result</th></tr></thead>
            <tbody>{[...detailed].reverse().map(row=><tr key={row.bar_utc}>
              <td>{timeIST(row.bar_utc)}</td>
              <td><span className={'tc-direction '+row.direction.toLowerCase()}>
                {row.direction==='UP'?<TrendingUp size={13}/>:row.direction==='DOWN'?<TrendingDown size={13}/>:null}
                {row.direction.replace('_',' ')}</span></td>
              <td>{fmt(row.reference_close)}</td><td>{fmt(row.observed_close)}</td>
              <td className={row.movement_bps===null?'':row.movement_bps>=0?'tc-replay-positive':'tc-replay-negative'}>{moveText(row.movement_bps)}</td>
              <td>{row.actual_direction||'—'}</td>
              <td><span className={'tc-result '+row.evaluation.toLowerCase()}>{outcome(row.evaluation)}</span></td>
            </tr>)}
            {!detailed.length&&<tr><td colSpan={7}>No UP/DOWN signals among the latest 100 historical decisions. Enable NO TRADE decisions to see why this window was skipped.</td></tr>}
            </tbody></table>
        </div>
        <p className="tc-muted">Table shows the latest 100 historical decisions for the selected horizon; scores cover the full selected historical window. Past candles are not permanently logged real-time predictions.</p>
        <h4 className="tc-signal-subtitle">Accuracy by Indian trading session</h4>
        <div className="tc-table-scroll"><table><thead><tr><th>IST date</th><th>Correct</th><th>Incorrect</th><th>Accuracy</th><th>No trade</th><th>Flat</th><th>Gaps</th></tr></thead>
          <tbody>{tested.days.map(day=><tr key={day.session_ist}>
            <td>{day.session_ist}</td><td>{day.correct}</td><td>{day.incorrect}</td>
            <td>{score(day.directional_accuracy)}</td><td>{day.no_trade}</td><td>{day.flat}</td><td>{day.unverifiable}</td>
          </tr>)}</tbody></table></div>
        <p className="tc-muted">Model: {tested.model_version}. {tested.disclaimer} {tested.source_warning}
          {tested.has_more_history?' Older observations exist outside this run.':''}</p>
      </div>}
    </section>

    <section className="tc-panel tc-signal-forward" aria-label="Recorded prospective BANKNIFTY signal accuracy">
      <div className="tc-panel-title"><div><strong><Clock3 size={17}/> Recorded forward predictions</strong>
        <p className="tc-muted">Signals stored at the time of observation are scored separately from any retrospective simulation.</p></div>
        <button type="button" onClick={()=>void refreshForward()} disabled={recordedBusy}>
          <RefreshCw size={15}/>{recordedBusy?'Scoring available outcomes…':'Refresh and score recorded signals'}</button></div>
      {recordedError!==null&&<div className="tc-api-help" role="alert">
        <AlertTriangle size={19}/><div><strong>Unable to load the prediction ledger</strong>
        <p>{readableError(recordedError)}</p></div></div>}
      {scoredNew!==null&&scoredNew>0&&<p className="tc-confirm" role="status">
        Evaluated {scoredNew} recorded predictions using source-matched observed minute candles.</p>}
      <div className="tc-signal-forward-grid">
        {([3,6] as const).map(horizon=>{
          const info=recorded[horizon]
          return <div className="tc-signal-forward-card" key={horizon}>
            <span>{horizon}-minute recorded predictions</span>
            <strong>{info?score(info.overall.directional_accuracy):'—'}</strong>
            <div><b>{info?.overall.correct??0}</b> right · <b>{info?.overall.incorrect??0}</b> wrong ·
              <b> {info?.overall.pending??0}</b> pending</div>
            <small>{info?.overall.live_observed??0} live-broker observations · {info?.overall.local_observed??0} locally observed bar records.
              {info?.truncated?' Report truncated; increase source coverage.':''}</small>
          </div>
        })}
      </div>
      <div className="tc-signal-detail-head">
        <strong>Latest recorded {selected}-minute calls</strong>
        <span className="tc-muted">Select the matching horizon card above to compare the same window.</span>
      </div>
      <div className="tc-table-scroll tc-signal-event-table">
        <table><thead><tr><th>Recorded IST</th><th>Signal</th><th>Index then</th><th>Index at outcome</th><th>Observed</th><th>Result</th><th>Source</th></tr></thead>
        <tbody>{recentForward.map(row=><tr key={row.id}>
          <td>{timeIST(row.bar_utc)}</td><td>{row.direction}</td>
          <td>{fmt(row.reference_close)}</td><td>{fmt(row.observed_close)}</td>
          <td>{row.actual_direction||'—'}</td><td>{outcome(row.evaluation)}</td>
          <td>{row.quote_mode==='LIVE_OBSERVED'?'Live Dhan broker':
            row.quote_mode==='RECENT_LOCAL_CANDLE_NOT_VERIFIED_LIVE'?'Observed local bar, live unverified':
            row.quote_mode}</td>
        </tr>)}
        {!recentForward.length&&<tr><td colSpan={7}>No {selected}-minute predictions have been recorded yet. The live recorder starts a prospective ledger only with permitted fresh observations.</td></tr>}
        </tbody></table></div>
      <p className="tc-muted">Forward scorecards use persistent, timestamped predictions—not signals reconstructed after the market moved. A successfully scored historical replay is not proof of live predictive accuracy.</p>
    </section>

    <section className="tc-signal-next" aria-label="Options P&L follow-up phase">
      <div><strong>Phase 2 · BANKNIFTY options P&amp;L backtest</strong>
        <p>After assessing signal correctness, we can map each call to a real CE/PE contract and test premium changes, the +5% target, −2.5% stop, six-minute exits, fees, and slippage. Not included in Phase 1 metrics.</p></div>
      <button type="button" onClick={onOpenReplay}>Review underlying replay <ArrowRight size={15}/></button>
    </section>
  </div>
}
