import {useCallback,useEffect,useState} from 'react'
import {AlertTriangle,ArrowRight,CheckCircle2,Database,Play,RefreshCw,ShieldCheck} from 'lucide-react'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
import './historical-options-backtest.css'

type Rule='fixed'|'signal_reversal'|'signal_reversal_or_cap'|'premium_target_stop'|'hybrid'
type OptionTrade={
  signal_utc:string;entry_utc:string;exit_utc:string;session_ist:string
  underlying_direction:string;option_side:'CE'|'PE';strike:number
  selection_ltp:number;entry_premium:number;exit_premium:number
  lots:number;lot_size_assumed:number;units:number;capital_deployed_inr:number
  net_pnl_inr:number;account_balance_inr:number;exit_reason:string
  hold_minutes:number;source_identity:string
}
type OptionScenario={
  policy:Rule;trade_count:number;win_rate:number|null;winning_trades:number
  losing_trades:number;starting_capital_inr:number;ending_capital_inr:number
  net_pnl_inr:number;return_pct:number;max_closed_trade_drawdown_pct:number
  average_hold_minutes:number|null;total_assumed_fees_inr:number
  unscored:Record<string,number>;trades:OptionTrade[]
  equity_curve:{timestamp_utc:string;equity_inr:number}[]
}
type CompareRow={
  rule_id:string;label:string;trade_count:number;win_rate:number|null
  net_pnl_inr:number;return_pct:number;ending_capital_inr:number
  max_closed_trade_drawdown_pct:number;average_hold_minutes:number|null
  unscored:Record<string,number>
}
type BacktestResult={
  mode:string;underlying:string;signal_source:string;signal_model:string
  signal_events:number;actionable_signals:number
  historical_window:{first:string;through_exclusive:string;observed_index_bars:number}
  data_evidence:{request_count:number;fresh_requests:number;cached_requests:number
    empty_requests:number;unique_option_minute_bars:number;conflicted_excluded:number
    source:string;expiry_flag:string;expiry_code:number;strike_wings:number}
  selected_rule_id:string;selected:OptionScenario;comparison:CompareRow[]
  assumptions:{premium_target_inr:number;premium_tolerance_inr:number
    lots:number;historical_lot_size_units:number;lot_size_basis:string
    slippage_bps_per_side:number;brokerage_inr_per_side:number
    profit_target_pct:number;stop_loss_pct:number}
  limitations:string;read_only:boolean;orders_placed:number
}
type Job={id:string;status:string;stage?:string;percent?:number;error?:string;result?:BacktestResult}
type Props={
  ready:boolean;limit:number;capital:number;holdRule:Rule
  holdMinutes:number;reversalCap:number;onOpenData:()=>void
}
const CASH=(value:number)=>new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:2}).format(value)
const DEC=(value:number,d=2)=>value.toLocaleString('en-IN',{maximumFractionDigits:d})
const PCT=(value:number)=>DEC(value,2)+'%'
const IST=(value:string)=>new Date(value).toLocaleString('en-IN',{
  timeZone:'Asia/Kolkata',month:'short',day:'numeric',hour:'2-digit',
  minute:'2-digit',hourCycle:'h23',
})
const OPTIONS_JOB_KEY='quantlab_banknifty_historical_options_job'
const MODE_LABEL:Record<Rule,string>={
  fixed:'Fixed-time exit',
  signal_reversal:'Until opposite BANKNIFTY signal',
  signal_reversal_or_cap:'Signal reversal or capped hold',
  premium_target_stop:'Option premium target/stop',
  hybrid:'Signal reversal, time cap or premium stop/target',
}
export default function HistoricalOptionsBacktest({
  ready,limit,capital,holdRule,holdMinutes,reversalCap,onOpenData,
}:Props){
  const [jobId,setJobId]=useState(()=>sessionStorage.getItem(OPTIONS_JOB_KEY)||'')
  const [job,setJob]=useState<Job|null>(null)
  const [result,setResult]=useState<BacktestResult|null>(null)
  const [error,setError]=useState('')
  const [startingCapital,setStartingCapital]=useState(capital)
  const [lots,setLots]=useState(3)
  const [lotSize,setLotSize]=useState(30)
  const [targetLtp,setTargetLtp]=useState(300)
  const [tolerance,setTolerance]=useState(50)
  const [wings,setWings]=useState(3)
  const [expiryFlag,setExpiryFlag]=useState<'MONTH'|'WEEK'>('MONTH')
  const [expiryCode,setExpiryCode]=useState<0|1|2>(0)
  const [profitTarget,setProfitTarget]=useState(5)
  const [stopLoss,setStopLoss]=useState(2.5)
  const [slippage,setSlippage]=useState(5)
  const [feePerSide,setFeePerSide]=useState(20)
  const [selectedRule,setSelectedRule]=useState<Rule|'inherit'>('inherit')

  const refreshJob=useCallback(async(id:string)=>{
    const status=await marketApi<Job>('/api/jobs/'+encodeURIComponent(id))
    setJob(status)
    if(status.status==='complete'){
      setResult(status.result||null)
      sessionStorage.removeItem(OPTIONS_JOB_KEY)
      setJobId('')
    }else if(['error','cancelled','interrupted'].includes(status.status)){
      setError(status.error||'Historical options research was interrupted. Check your Data API connection and original source coverage.')
      sessionStorage.removeItem(OPTIONS_JOB_KEY)
      setJobId('')
    }
  },[])
  useEffect(()=>{
    if(!jobId)return
    let active=true
    let pending=false
    const poll=async()=>{
      if(pending)return
      pending=true
      try{await refreshJob(jobId)}
      catch(e){if(active)setError(readableError(e))}
      finally{pending=false}
    }
    void poll()
    const timer=window.setInterval(()=>{if(active)void poll()},2000)
    return()=>{active=false;window.clearInterval(timer)}
  },[jobId,refreshJob])

  const run=async()=>{
    if(jobId||!ready)return
    setError('');setResult(null);setJob(null)
    try{
      const chosen=selectedRule==='inherit'?holdRule:selectedRule
      const request={
        limit,starting_capital:startingCapital,expiry_flag:expiryFlag,expiry_code:expiryCode,
        wings,target_ltp:targetLtp,tolerance,lots,lot_size:lotSize,
        stop_pct:stopLoss,target_pct:profitTarget,slippage_bps:slippage,
        fee_per_side:feePerSide,hold_rule:chosen,hold_minutes:holdMinutes,
        reversal_cap_minutes:reversalCap,confirm_readonly:true,
      }
      const started=await marketPost<{job_id:string}>('/api/trading-cockpit/options/backtest',request)
      sessionStorage.setItem(OPTIONS_JOB_KEY,started.job_id)
      setJobId(started.job_id)
    }catch(e){setError(readableError(e))}
  }
  const running=Boolean(jobId)
  const requestedPairs=2*(2*wings+1)
  const scenario=result?.selected
  const coverage=scenario?.unscored||{}
  return <section className="tc-panel hob-root" aria-label="Historical BANKNIFTY signals to options backtest">
    <header className="hob-head"><div>
      <span className="tc-page-kicker">PHASE 2 · TRADE OPTION PREMIUMS, NOT INDEX POINTS</span>
      <h3>BANKNIFTY Signal → Historical CE/PE Backtest</h3>
      <p>Use the same completed BANKNIFTY EMA/RSI signal to select a real historical CE/PE strike near ₹300, buy its next observed option-candle open and exit under competing rules. No option trading orders are sent.</p>
    </div><span className="hob-badge"><ShieldCheck size={15}/> Read-only historical research</span></header>

    <div className="hob-flow" aria-label="Historical strategy execution flow">
      <span>1 · BANKNIFTY signal</span><ArrowRight size={16}/><span>2 · CE / PE at ₹300</span>
      <ArrowRight size={16}/><span>3 · Three option lots</span>
      <ArrowRight size={16}/><span>4 · Exit rule → ₹ P&amp;L</span>
    </div>

    <div className="hob-controls">
      <label>Expiry family
        <select aria-label="Historical Dhan expiry family" value={expiryFlag}
          onChange={e=>setExpiryFlag(e.target.value as 'MONTH'|'WEEK')}>
          <option value="MONTH">Monthly (default)</option>
          <option value="WEEK">Weekly (only when historical data exists)</option>
        </select>
      </label>
      <label>Expiry series
        <select aria-label="Historical option expiry code" value={expiryCode}
          onChange={e=>setExpiryCode(Number(e.target.value) as 0|1|2)}>
          <option value={0}>Current / near expiry</option>
          <option value={1}>Next expiry</option>
          <option value={2}>Far expiry</option>
        </select>
      </label>
      <label>Preferred entry option LTP ₹
        <input aria-label="Historical option target LTP" type="number" min="10" max="20000" step="5"
          value={targetLtp} onChange={e=>setTargetLtp(Number(e.target.value))}/>
      </label>
      <label>Allowed difference ±₹
        <input aria-label="Historical option price tolerance" type="number" min="0" max="5000"
          value={tolerance} onChange={e=>setTolerance(Number(e.target.value))}/>
      </label>
      <label>Option lots
        <input aria-label="Historical option lots" type="number" min="1" max="20" step="1"
          value={lots} onChange={e=>setLots(Number(e.target.value))}/>
      </label>
      <label title="Dhan rolling history does not contain historical exchange lot size. You must validate it for your dates.">Historical units per lot · assumption
        <input aria-label="Historical lot size assumption" type="number" min="1" max="100" step="1"
          value={lotSize} onChange={e=>setLotSize(Number(e.target.value))}/>
      </label>
      <label>Starting account ₹
        <input aria-label="Historical options starting capital" type="number" min="1000" max="100000000" step="1000"
          value={startingCapital} onChange={e=>setStartingCapital(Number(e.target.value))}/>
      </label>
      <label>ATM strike wings
        <select aria-label="Historical option strike wings" value={wings}
          onChange={e=>setWings(Number(e.target.value))}>
          {[0,1,2,3,4,5].map(n=><option key={n} value={n}>ATM ±{n} ({2*(2*n+1)} side/strike requests per 30d)</option>)}
        </select>
      </label>
      <label>Highlighted exit rule
        <select aria-label="Highlighted option exit rule" value={selectedRule}
          onChange={e=>setSelectedRule(e.target.value as Rule|'inherit')}>
          <option value="inherit">Same as index backtest: {MODE_LABEL[holdRule]}</option>
          {(Object.keys(MODE_LABEL) as Rule[]).map(rule=><option key={rule} value={rule}>{MODE_LABEL[rule]}</option>)}
        </select>
      </label>
      <label>Profit target % · option premium
        <input aria-label="Historical option profit target percent" type="number" min=".1" max="100" step=".5"
          value={profitTarget} onChange={e=>setProfitTarget(Number(e.target.value))}/>
      </label>
      <label>Stop loss % · option premium
        <input aria-label="Historical option stop loss percent" type="number" min=".1" max="50" step=".5"
          value={stopLoss} onChange={e=>setStopLoss(Number(e.target.value))}/>
      </label>
      <label>Assumed slippage bps per side
        <input aria-label="Historical option slippage bps" type="number" min="0" max="500" step="1"
          value={slippage} onChange={e=>setSlippage(Number(e.target.value))}/>
      </label>
      <label>Assumed brokerage ₹ per side
        <input aria-label="Historical option brokerage per side" type="number" min="0" max="1000" step="1"
          value={feePerSide} onChange={e=>setFeePerSide(Number(e.target.value))}/>
      </label>
    </div>
    <div className="hob-description">
      <span><Database size={16}/> {requestedPairs} Dhan contract-series requests per 30-day chunk, minus cached receipts</span>
      <span>Preferred {lots} lots × {lotSize} assumed units = <strong>{lots*lotSize} option units</strong></span>
      <span>Estimated ₹{DEC(targetLtp*lots*lotSize,0)} at target LTP, excluding spread and charges.</span>
    </div>
    {!ready&&<div className="tc-warning">Historical BANKNIFTY original index data is missing.
      <button type="button" onClick={onOpenData}>Prepare index history <ArrowRight size={15}/></button>
    </div>}
    <div className="hob-run">
      <button type="button" onClick={()=>void run()} disabled={running||!ready}>
        {running?<RefreshCw size={17}/>:<Play size={17}/>}
        {running?'Loading option history and running scenarios…':'Run BANKNIFTY → CE/PE backtest (auto-fetch missing data)'}
      </button>
      <p>Runs locally using your configured Dhan token. Reuses verified cached source receipts on repeat runs. The historical lot size and execution costs are user assumptions; no orders, historical bid/ask or broker fills are claimed.</p>
    </div>
    {job&&running&&<div className="hob-job" role="status">
      <span>{job.stage||'Loading original historical options'}</span>
      <strong>{Math.round(job.percent||0)}%</strong>
      <progress max="100" value={job.percent||0}/>
    </div>}
    {error&&<div className="tc-warning" role="alert"><AlertTriangle size={17}/><div>
      <strong>Historical option backtest needs attention</strong><p>{error}</p>
      <p>Check your Dhan expired-options Data API entitlement, original index history, expiry selection and cached source integrity.</p>
    </div><button type="button" onClick={onOpenData}>Connections <ArrowRight size={14}/></button></div>}
    {result&&scenario&&<div className="hob-results">
      <header className="hob-results-head"><div>
        <span className="tc-page-kicker"><CheckCircle2 size={15}/> ORIGINAL DHAN OPTION CANDLES · SIMULATED FILLS</span>
        <h4>Historical CE/PE account results</h4>
        <p>{result.historical_window.first} through {result.historical_window.through_exclusive} (end exclusive) ·
          {' '}{result.actionable_signals} BANKNIFTY UP/DOWN signals ·
          {' '}{result.data_evidence.unique_option_minute_bars} actual-strike option minute bars.</p>
      </div></header>
      <div className="hob-metrics">
        <div><span>Selected policy return</span><strong className={scenario.net_pnl_inr>=0?'hob-positive':'hob-negative'}>{scenario.net_pnl_inr>=0?'+':''}{CASH(scenario.net_pnl_inr)}</strong><small>{scenario.return_pct>=0?'+':''}{PCT(scenario.return_pct)}</small></div>
        <div><span>Account balance</span><strong>{CASH(scenario.ending_capital_inr)}</strong><small>Started {CASH(scenario.starting_capital_inr)}</small></div>
        <div><span>Option trades scored</span><strong>{scenario.trade_count}</strong><small>{scenario.winning_trades} winners · {scenario.losing_trades} losers</small></div>
        <div><span>Option trade win rate</span><strong>{scenario.win_rate===null?'Insufficient data':PCT(scenario.win_rate*100)}</strong></div>
        <div><span>Closed-trade drawdown</span><strong>{PCT(scenario.max_closed_trade_drawdown_pct)}</strong><small>Intratrade drawdown not modeled</small></div>
        <div><span>Original Dhan request usage</span><strong>{result.data_evidence.fresh_requests} fetched</strong><small>{result.data_evidence.cached_requests} reused · {result.data_evidence.empty_requests} empty</small></div>
      </div>
      {scenario.trade_count===0&&<div className="tc-warning">
        <AlertTriangle size={17}/> No complete historical CE/PE trades were scored for this sample.
        This is not zero-risk profitability or a failed trade signal; inspect the missing-data counts below.
        Try a wider premium range or more ATM wings, but never substitute index returns for option premiums.
      </div>}
      <div className="tc-table-scroll hob-table">
        <table><thead><tr><th>Exit strategy</th><th>Trades</th><th>Win rate</th><th>Option net P&amp;L</th>
          <th>Account return</th><th>Ending balance</th><th>Average hold</th><th>Closed drawdown</th></tr></thead>
          <tbody>{result.comparison.map(rule=><tr key={rule.rule_id} className={rule.rule_id===result.selected_rule_id?'hob-selected':''}>
            <td>{rule.label}{rule.rule_id===result.selected_rule_id?' · selected':''}</td>
            <td>{rule.trade_count}</td><td>{rule.win_rate===null?'—':PCT(rule.win_rate*100)}</td>
            <td className={rule.net_pnl_inr>=0?'hob-positive':'hob-negative'}>{rule.net_pnl_inr>=0?'+':''}{CASH(rule.net_pnl_inr)}</td>
            <td>{rule.return_pct>=0?'+':''}{PCT(rule.return_pct)}</td><td>{CASH(rule.ending_capital_inr)}</td>
            <td>{rule.average_hold_minutes===null?'—':DEC(rule.average_hold_minutes,1)+'m'}</td>
            <td>{PCT(rule.max_closed_trade_drawdown_pct)}</td>
          </tr>)}</tbody>
        </table>
      </div>
      <details className="hob-detail"><summary>Why were some options trades unscored?</summary>
        <div className="hob-skips">
          {Object.entries(coverage).length===0?<p>All attempted entries and exits had the required historical source observations.</p>:
            Object.entries(coverage).map(([reason,count])=><div key={reason}><span>{reason.replaceAll('_',' ')}</span><strong>{count}</strong></div>)}
          <div><span>Conflicting source candles excluded</span><strong>{result.data_evidence.conflicted_excluded}</strong></div>
        </div>
      </details>
      <details className="hob-detail"><summary>See the last {scenario.trades.length} actual-strike option simulations</summary>
        <div className="tc-table-scroll hob-table"><table><thead><tr>
          <th>Signal (IST)</th><th>Index</th><th>Contract side</th><th>Strike</th>
          <th>Entry option ₹</th><th>Exit option ₹</th><th>Lots / units</th>
          <th>Exit reason</th><th>Hold</th><th>Net ₹</th><th>Balance ₹</th>
        </tr></thead><tbody>{[...scenario.trades].reverse().map(t=><tr key={t.signal_utc}>
          <td>{IST(t.signal_utc)}</td><td>{t.underlying_direction}</td><td>{t.option_side}</td><td>{DEC(t.strike,0)}</td>
          <td>{DEC(t.entry_premium)}</td><td>{DEC(t.exit_premium)}</td>
          <td>{t.lots} / {t.units}</td><td>{t.exit_reason.replaceAll('_',' ')}</td>
          <td>{t.hold_minutes}m</td><td className={t.net_pnl_inr>=0?'hob-positive':'hob-negative'}>{CASH(t.net_pnl_inr)}</td>
          <td>{CASH(t.account_balance_inr)}</td>
        </tr>)}</tbody></table></div>
      </details>
      <p className="hob-limitations"><AlertTriangle size={17}/>
        <span><strong>Historical execution proxy, not verified broker fills.</strong> {result.limitations}</span></p>
    </div>}
  </section>
}
