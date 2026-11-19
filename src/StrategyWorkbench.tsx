import {useCallback,useEffect,useState} from 'react'
import {AlertTriangle,ArrowRight,BarChart3,CheckCircle2,Database,RefreshCw,Target,TrendingDown,TrendingUp,Clock3} from 'lucide-react'
import {marketApi,marketPost,MarketApiError,readableError} from './tradingCockpitApi'
import './signal-backtest.css'
import IndexExposureScenario,{type ScenarioResult} from './IndexExposureScenario'
import HistoricalOptionsBacktest from './HistoricalOptionsBacktest'

type Source={identity:string;display_name?:string;ready:boolean;asset_class?:string}
type Counts={
  total:number;scored:number;correct:number;incorrect:number;pending:number;
  no_trade:number;flat:number;unverifiable:number;directional_accuracy:number|null;
  up_signals:number;down_signals:number;actual_up:number;actual_down:number;
  live_observed:number;local_observed:number;
  unscored_after_last_bar:number;unscored_missing_minute:number
}
type Day=Counts&{session_ist:string}
type HistoricalEvent={
  bar_utc:string;session_ist:string;horizon_minutes:number;
  direction:'UP'|'DOWN'|'NO_TRADE';reference_close:number;
  observed_close:number|null;movement_bps:number|null;
  actual_direction:'UP'|'DOWN'|'FLAT'|null;evaluation:string;
  unscored_reason?:'after_last_observed_bar'|'missing_original_minute'|null
}
type HistoricalResult={
  identity:string;horizon_minutes:HistoricalHorizon;observed_source_bars:number;
  model_version:string;mode:'RETROSPECTIVE_HISTORICAL_RULE_REPLAY';
  overall:Counts;days:Day[];latest_events:HistoricalEvent[];
  latest_signal_events:HistoricalEvent[];
  index_exposure_scenario:ScenarioResult;
  holding_rule_comparison?:HoldingComparison[];
  selected_holding_rule_id?:string;
  disclaimer:string;source_warning:string;has_more_history:boolean
}
type HoldingComparison={
  rule_id:string;label:string;hold_rule:string;hold_minutes:number;
  trade_count:number;win_rate:number|null;net_pnl_inr:number;
  net_return_pct:number;ending_capital_inr:number;
  max_closed_trade_drawdown_pct:number;average_hold_minutes:number|null;
  missing_paths:number;
}
type HoldingRule='fixed'|'signal_reversal'|'signal_reversal_or_cap'
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
const HISTORICAL_HORIZONS=[1,3,5,6,10,30,60] as const
type HistoricalHorizon=typeof HISTORICAL_HORIZONS[number]
const fmt=(n:number|null|undefined,d=2)=>
  n===null||n===undefined?'—':n.toLocaleString('en-IN',{maximumFractionDigits:d})
const score=(n:number|null)=>n===null?'Not enough scored signals':fmt(n*100,1)+'%'
const pct=(n:number)=>fmt(n,2)+'%'
const cash=(n:number)=>new Intl.NumberFormat('en-IN',{
  style:'currency',currency:'INR',minimumFractionDigits:2,maximumFractionDigits:2,
}).format(n)
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

export default function StrategyWorkbench({instruments,onOpenData,onOpenReplay,onOpenOptions}:{
  instruments:Source[],onOpenData:()=>void,onOpenReplay:()=>void,onOpenOptions?:()=>void
}){
  const [limit,setLimit]=useState<'500'|'1500'|'3000'|'5000'>('1500')
  const [result,setResult]=useState<HistoricalResult|null>(null)
  const [selected,setSelected]=useState<HistoricalHorizon>(5)
  const [holdRule,setHoldRule]=useState<HoldingRule>('fixed')
  const [reversalCap,setReversalCap]=useState(10)
  const [capital,setCapital]=useState(50_000)
  const [allocation,setAllocation]=useState(100)
  const [costBps,setCostBps]=useState(0)
  const [forwardSelected,setForwardSelected]=useState<3|6>(6)
  const [showAll,setShowAll]=useState(false)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState<unknown>(null)
  const [recorded,setRecorded]=useState<Partial<Record<3|6,ForwardReport>>>({})
  const [ledger,setLedger]=useState<ForwardLedger|null>(null)
  const [recordedBusy,setRecordedBusy]=useState(false)
  const [scoredNew,setScoredNew]=useState<number|null>(null)
  const [recordedError,setRecordedError]=useState<unknown>(null)
  const ready=instruments.some(s=>s.identity===INDEX&&s.ready)
  const tested=result?.horizon_minutes===selected?result:null
  const testsDone=Boolean(tested)
  const noActionable=Boolean(tested&&tested.overall.scored===0)

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
    setBusy(true);setError(null);setResult(null)
    try{
      const scenario=await marketApi<HistoricalResult>(
        '/api/trading-cockpit/replay?'+new URLSearchParams({
          identity:INDEX,horizon_minutes:String(selected),limit,
          hold_rule:holdRule,hold_minutes:String(selected),
          reversal_cap_minutes:String(reversalCap),
          starting_capital:String(capital),allocation_pct:String(allocation),
          cost_bps_per_side:String(costBps),
        }))
      setResult(scenario)
    }catch(e){setError(e)}
    finally{setBusy(false)}
  }
  // Older API responses and browser-test fixtures expose latest_events only.
  // Prefer the new last-100-actionable feed, but never render a blank table
  // while the API/client revision is being upgraded locally.
  const detailed=showAll
    ?(tested?.latest_events||[])
    :(tested?.latest_signal_events||
      (tested?.latest_events||[]).filter(row=>row.direction!=='NO_TRADE'))
  const recentForward=(ledger?.predictions||[]).filter(row=>row.horizon_minutes===forwardSelected)
    .slice(0,25)

  return <div className="tc-signal-workbench" aria-label="BANKNIFTY signal backtest workspace">
    <div className="tc-v4-intro">
      <div><span className="tc-page-kicker">PHASE 1 · DIRECTION FIRST</span>
        <h3>BANKNIFTY Signal Backtest</h3>
        <p>Choose when a position opens and closes, test how accurately the model predicted BANKNIFTY, and inspect a separately labeled illustrative rupee-denominated index-exposure scenario. Real options profits require option-contract history.</p>
      </div>
      <span className="tc-signal-tag"><Target size={15}/> Index signal + illustrative investment · no option P&amp;L</span>
    </div>

    <section className="tc-panel tc-signal-main" aria-label="Historical BANKNIFTY signal accuracy">
      <div className="tc-panel-title">
        <div><strong><BarChart3 size={17}/> Historical signal backtest</strong>
          <p className="tc-muted">Test the same existing EMA/RSI rule with a clear entry, holding period and exit. All calculated scenario balances are illustrative, never executed broker trades.</p>
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
            onChange={e=>{setLimit(e.target.value as typeof limit);setResult(null)}}>
            <option value="500">Last 500 minutes</option>
            <option value="1500">Last 1,500 minutes</option>
            <option value="3000">Last 3,000 minutes</option>
            <option value="5000">Last 5,000 minutes</option>
          </select>
        </label>
        <label>Hold position
          <select aria-label="Trade holding period" value={selected}
            onChange={e=>{setSelected(Number(e.target.value) as HistoricalHorizon);setResult(null)}}>
            {HISTORICAL_HORIZONS.map(h=><option key={h} value={h}>{h===60?'1 hour':h+' minutes'}</option>)}
          </select>
        </label>
        <label>Exit / hold rule
          <select aria-label="Exit strategy" value={holdRule}
            onChange={e=>{setHoldRule(e.target.value as HoldingRule);setResult(null)}}>
            <option value="fixed">Fixed time</option>
            <option value="signal_reversal">Until opposite signal or session end</option>
            <option value="signal_reversal_or_cap">Opposite signal or time cap</option>
          </select>
        </label>
        {holdRule==='signal_reversal_or_cap'&&<label>Maximum hold
          <select aria-label="Reversal time cap" value={reversalCap}
            onChange={e=>{setReversalCap(Number(e.target.value));setResult(null)}}>
            {[3,5,6,10,15,30,60].map(value=><option key={value} value={value}>{value} minutes</option>)}
          </select>
        </label>}
        <label>Illustrative capital (₹)
          <input type="number" aria-label="Illustrative starting capital" min="1000" max="100000000"
            step="1000" value={capital} onChange={e=>{setCapital(Number(e.target.value));setResult(null)}}/>
        </label>
        <label>Capital used per position
          <select aria-label="Capital allocation" value={allocation}
            onChange={e=>{setAllocation(Number(e.target.value));setResult(null)}}>
            <option value="25">25%</option><option value="50">50%</option>
            <option value="75">75%</option><option value="100">100%</option>
          </select>
        </label>
        <label>Assumed cost per side
          <select aria-label="Hypothetical cost per side" value={costBps}
            onChange={e=>{setCostBps(Number(e.target.value));setResult(null)}}>
            <option value="0">0 bps (gross)</option><option value="2">2 bps</option>
            <option value="5">5 bps</option><option value="10">10 bps</option>
          </select>
        </label>
        <button className="tc-signal-run" type="button" onClick={()=>void runTest()}
          disabled={busy||!ready||!Number.isFinite(capital)||capital<1000||capital>100000000}>
          <Target size={16}/>{busy?'Testing original candles…':'Run signal + trade simulation'}
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
        <div className="tc-signal-scorecard selected">
          <div className="tc-signal-scorecard-title"><span>Directional accuracy · {selected===60?'1 hour':selected+'m'}</span>
            <strong>{score(tested!.overall.directional_accuracy)}</strong></div>
          <div className="tc-signal-tally">
            <span><b className="good">{tested!.overall.correct}</b> Correct</span>
            <span><b className="bad">{tested!.overall.incorrect}</b> Incorrect</span>
            <span><b>{tested!.overall.no_trade}</b> No trade</span>
            <span><b>{tested!.overall.unverifiable}</b> Unscored</span>
          </div>
          <small>Measured on historical index closes after the selected horizon; overlapping signal observations are not independent trades. Entries in the illustration begin at the next observed opening price.</small>
        </div>
        <div className="tc-signal-scorecard tc-signal-investment-summary">
          <div className="tc-signal-scorecard-title"><span>Illustrative account change · not options P&amp;L</span>
            <strong>{tested!.index_exposure_scenario.net_return_pct>=0?'+':''}{pct(tested!.index_exposure_scenario.net_return_pct)}</strong></div>
          <strong className="tc-signal-scenario-pnl">{tested!.index_exposure_scenario.net_pnl_inr>=0?'+':''}{cash(tested!.index_exposure_scenario.net_pnl_inr)}</strong>
          <small>{tested!.index_exposure_scenario.trade_count} nonoverlapping positions, next-bar entries and {holdRule==='fixed'?'fixed '+selected+'-minute exits':holdRule==='signal_reversal'?'reversal or session-end exits':'reversal or '+reversalCap+'-minute capped exits'}. Assumed costs are configurable above.</small>
        </div>
      </div>:!busy&&ready&&<div className="tc-signal-prompt">
        <TrendingUp size={22}/><div><strong>Select a holding period and run a simulation.</strong>
          <p>We enter on the next observed minute's open after an actionable UP/DOWN signal, hold the selected number of minutes, and exit at the next eligible observed open. No overlapping positions or overnight carry.</p></div>
      </div>}
      {noActionable&&<p className="tc-signal-caution"><AlertTriangle size={18}/>
        The current EMA/RSI baseline produced no scored UP/DOWN predictions in this window.
        This is a valid finding, not 100% accuracy; review the NO TRADE count and source coverage.</p>}
      {tested&&<>
        {tested.holding_rule_comparison&&<section className="tc-panel tc-holding-compare" aria-label="Hold rule comparison">
          <div className="tc-panel-title"><div>
            <strong><BarChart3 size={17}/> Compare all exit rules</strong>
            <p className="tc-muted">Same historical entry signals and starting capital for every rule. Each rule has its own non-overlapping trade sequence; no historical option premium or actual investment return is implied. Missing paths are excluded, not filled.</p>
          </div></div>
          <div className="tc-table-scroll"><table><thead><tr>
            <th>Exit rule</th><th>Trades</th><th>Win rate</th><th>Average hold</th>
            <th>Illustrative net ₹</th><th>Illustrative return</th><th>Ending balance</th>
            <th>Closed-trade drawdown</th><th>Missing paths</th></tr></thead><tbody>
            {tested.holding_rule_comparison.map(rule=><tr key={rule.rule_id}
              className={rule.rule_id===tested.selected_holding_rule_id?'tc-hold-selected':''}>
              <td><strong>{rule.label}</strong>{rule.rule_id===tested.selected_holding_rule_id?' · SELECTED':''}</td>
              <td>{rule.trade_count}</td><td>{rule.win_rate===null?'—':pct(rule.win_rate*100)}</td>
              <td>{rule.average_hold_minutes===null?'—':fmt(rule.average_hold_minutes,1)+'m'}</td>
              <td className={rule.net_pnl_inr>=0?'good':'bad'}>{rule.net_pnl_inr>=0?'+':''}{cash(rule.net_pnl_inr)}</td>
              <td>{rule.net_return_pct>=0?'+':''}{pct(rule.net_return_pct)}</td>
              <td>{cash(rule.ending_capital_inr)}</td>
              <td>{pct(rule.max_closed_trade_drawdown_pct)}</td><td>{rule.missing_paths}</td>
            </tr>)}
          </tbody></table></div>
          <p className="tc-muted">A reversal requires a confirmed completed opposite-direction candle; exit is assumed at the next original minute's open. NO TRADE does not reverse a position. Remaining positions close only at an observed 15:29 IST opening price, never overnight.</p>
        </section>}
        {tested.index_exposure_scenario&&<IndexExposureScenario scenario={tested.index_exposure_scenario}/>}
        <details className="tc-signal-raw-details"><summary>Inspect the underlying signals and daily accuracy</summary>
        <div className="tc-signal-detail">
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
          <span title="Missing source minute or the prediction horizon falls after the last recorded bar.">Unscored UP/DOWN<strong>{tested.overall.unverifiable}</strong></span>
        </div>
        {tested.overall.unverifiable>0&&<p className="tc-muted">
          {tested.overall.unscored_after_last_bar||0} horizons beyond the last recorded minute;
          {' '}{tested.overall.unscored_missing_minute||0} missing interior minute observations.
          NO TRADE decisions do not count as missed predictions.
        </p>}
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
              <td><span className={'tc-result '+row.evaluation.toLowerCase()}
                title={row.unscored_reason==='after_last_observed_bar'?'No later observed minute in this session':
                  row.unscored_reason==='missing_original_minute'?'Exact future observed minute missing':undefined}>
                {outcome(row.evaluation)}</span></td>
            </tr>)}
            {!detailed.length&&<tr><td colSpan={7}>No UP/DOWN signals were produced in this historical window. Enable NO TRADE decisions to inspect recent skipped minutes.</td></tr>}
            </tbody></table>
        </div>
        <p className="tc-muted">Table shows the latest 100 {showAll?'historical decisions, including NO TRADE':'UP/DOWN signals'} for this horizon. Scorecards cover the complete selected window. Historical decisions are never presented as predictions recorded live.</p>
        <h4 className="tc-signal-subtitle">Accuracy by Indian trading session</h4>
        <div className="tc-table-scroll"><table><thead><tr><th>IST date</th><th>Correct</th><th>Incorrect</th><th>Accuracy</th><th>No trade</th><th>Flat</th><th>Unscored UP/DOWN</th></tr></thead>
          <tbody>{tested.days.map(day=><tr key={day.session_ist}>
            <td>{day.session_ist}</td><td>{day.correct}</td><td>{day.incorrect}</td>
            <td>{score(day.directional_accuracy)}</td><td>{day.no_trade}</td><td>{day.flat}</td><td>{day.unverifiable}</td>
          </tr>)}</tbody></table></div>
        <p className="tc-muted">Model: {tested.model_version}. {tested.disclaimer} {tested.source_warning}
          {tested.has_more_history?' Older observations exist outside this run.':''}</p>
      </div></details></>}
    </section>

    <HistoricalOptionsBacktest ready={ready} limit={Number(limit)}
      capital={capital} holdRule={holdRule} holdMinutes={selected}
      reversalCap={reversalCap} onOpenData={onOpenData}/>

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
          return <button type="button" className={'tc-signal-forward-card '+(forwardSelected===horizon?'selected':'')}
            key={horizon} aria-pressed={forwardSelected===horizon} onClick={()=>setForwardSelected(horizon)}>
            <span>{horizon}-minute recorded predictions</span>
            <strong>{info?score(info.overall.directional_accuracy):'—'}</strong>
            <div><b>{info?.overall.correct??0}</b> right · <b>{info?.overall.incorrect??0}</b> wrong ·
              <b> {info?.overall.pending??0}</b> pending</div>
            <small>{info?.overall.live_observed??0} live-broker observations · {info?.overall.local_observed??0} locally observed bar records.
              {info?.truncated?' Report truncated; increase source coverage.':''}</small>
          </button>
        })}
      </div>
      <div className="tc-signal-detail-head">
        <strong>Latest recorded {forwardSelected}-minute calls</strong>
        <span className="tc-muted">Prospective recording currently supports 3m and 6m; select either card below. Other periods are historical-only until their live evaluation is implemented.</span>
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
        {!recentForward.length&&<tr><td colSpan={7}>No {forwardSelected}-minute predictions have been recorded yet. The live recorder starts a prospective ledger only with permitted fresh observations.</td></tr>}
        </tbody></table></div>
      <p className="tc-muted">Forward scorecards use persistent, timestamped predictions—not signals reconstructed after the market moved. A successfully scored historical replay is not proof of live predictive accuracy.</p>
    </section>

    <section className="tc-signal-next" aria-label="Options P&L follow-up phase">
      <div><strong>Phase 2 · BANKNIFTY options P&amp;L backtest</strong>
        <p>After assessing signal correctness, we can map each call to a real CE/PE contract and test premium changes, the +5% target, −2.5% stop, six-minute exits, fees, and slippage. Not included in Phase 1 metrics.</p></div>
      <div className="tc-signal-followup-actions">
        <button type="button" onClick={onOpenReplay}>Review underlying replay <ArrowRight size={15}/></button>
        {onOpenOptions&&<button type="button" onClick={onOpenOptions}>Inspect actual BANKNIFTY CE/PE chain <ArrowRight size={15}/></button>}
      </div>
    </section>
  </div>
}
