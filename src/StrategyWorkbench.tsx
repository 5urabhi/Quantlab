import {useState} from 'react'
import {Activity,AlertTriangle,ArrowRight,BarChart3,CheckCircle2,ClipboardCheck,Database} from 'lucide-react'
import {marketApi,readableError,MarketApiError} from './tradingCockpitApi'
type Source={identity:string;display_name?:string;ready:boolean;asset_class?:string}
type Summary={scored:number;correct:number;incorrect:number;no_trade:number;
  unverifiable:number;directional_accuracy:number|null}
type Result={identity:string;horizon_minutes:number;observed_source_bars:number;
  overall:Summary;days:{session_ist:string;scored:number;correct:number;incorrect:number;
    no_trade:number;unverifiable:number;directional_accuracy:number|null}[];
  source_warning:string;disclaimer:string;has_more_history:boolean;model_version:string}
const fmt=(v:number|null|undefined,decimal=1)=>v===null||v===undefined?'—':
  v.toLocaleString('en-IN',{maximumFractionDigits:decimal})
export default function StrategyWorkbench({instruments,onOpenData,onOpenReplay}:{
  instruments:Source[],onOpenData:()=>void,onOpenReplay:()=>void
}){
  const [index,setIndex]=useState<'INDEX:BANKNIFTY'|'INDEX:NIFTY50'>('INDEX:BANKNIFTY')
  const [horizon,setHorizon]=useState<'3'|'6'>('6')
  const [limit,setLimit]=useState<'500'|'1500'|'3000'|'5000'>('1500')
  const [result,setResult]=useState<Result|null>(null)
  const [loading,setLoading]=useState(false)
  const [error,setError]=useState<unknown>(null)
  const spotAvailable=instruments.some(s=>s.identity===index&&s.ready)
  const diagnostic=async()=>{
    if(loading||!spotAvailable)return
    setLoading(true);setError(null);setResult(null)
    try{
      const response=await marketApi<Result>('/api/trading-cockpit/replay?'+new URLSearchParams({
        identity:index,horizon_minutes:horizon,limit,
      }))
      setResult(response)
    }catch(e){setError(e)}
    finally{setLoading(false)}
  }
  return <div className="tc-strategy-workbench" aria-label="Trading strategy backtest workspace">
    <div className="tc-page-intro">
      <div><span className="tc-page-kicker">STRATEGY TESTING</span>
        <h3>Test a complete trade—not just index direction</h3>
        <p>Keep option execution/P&amp;L research separate from model-direction diagnostics.</p>
      </div><span className="tc-data-badge">SOURCE-AWARE BACKTESTING</span>
    </div>
    <section className="tc-panel tc-strategy-primary">
      <div className="tc-panel-title"><strong><BarChart3 size={17}/> BANKNIFTY options strategy backtest</strong>
        <span className="tc-token-state attention">Requires actual option history</span></div>
      <div className="tc-strategy-columns">
        <div className="tc-strategy-plan">
          <div className="tc-strategy-plan-header"><strong>Intraday options · example test plan</strong>
            <span>Read-only historical research</span></div>
          <div className="tc-strategy-plan-grid">
            <span>Underlying <b>BANKNIFTY spot</b></span>
            <span>Entry side <b>CE / PE chosen by strategy</b></span>
            <span>Profit exit <b>+5% option premium</b></span>
            <span>Stop loss <b>−2.5% option premium</b></span>
            <span>Maximum hold <b>6 minutes</b></span>
            <span>Prices <b>Actual contract OHLC / quoted spread</b></span>
          </div>
          <p className="tc-muted">Example parameters only, not a backtest result. The option's actual price path—not a BANKNIFTY point move—must determine profit targets and stops. Gaps, brokerage, spread and exit conditions must be accounted for before publishing P&amp;L.</p>
        </div>
        <div className="tc-strategy-readiness">
          <h4>Data readiness</h4>
          <div className="tc-strategy-check">
            {instruments.some(s=>s.identity==='INDEX:BANKNIFTY'&&s.ready)
              ?<CheckCircle2 size={18} className="tc-ok"/>
              :<AlertTriangle size={18} className="tc-warn"/>}
            <div><strong>Original BANKNIFTY one-minute index</strong>
              <small>{instruments.some(s=>s.identity==='INDEX:BANKNIFTY'&&s.ready)?
                'Available in shared market library':'Missing. Prepare original IDX_I historical candles.'}</small></div>
          </div>
          <div className="tc-strategy-check"><AlertTriangle size={18} className="tc-warn"/>
            <div><strong>Historical option contract prices</strong>
              <small>Not connected to this backtest engine. Actual selected CE/PE contract candles are required before computing trades.</small></div>
          </div>
          <div className="tc-strategy-check"><AlertTriangle size={18} className="tc-warn"/>
            <div><strong>Fill costs and expiry-specific contracts</strong>
              <small>Executable fill assumptions and per-contract historical expiry/strike mapping are not yet validated.</small></div>
          </div>
          <div className="tc-strategy-actions">
            <button type="button" onClick={onOpenData}>Review market sources <ArrowRight size={15}/></button>
            <button type="button" className="tc-secondary" onClick={onOpenReplay}>Replay historical index <ArrowRight size={15}/></button>
          </div>
        </div>
      </div>
      <p className="tc-strategy-boundary"><AlertTriangle size={16}/> Option P&amp;L, Sharpe, drawdown and win rate remain unavailable until real option price and trade data are connected. The app will not present index-direction accuracy as strategy profitability.</p>
    </section>
    <details className="tc-panel tc-strategy-diagnostics">
      <summary><Activity size={17}/> Model diagnostics · evaluate the existing EMA/RSI direction rule
        <small>Advanced research only · not a trade/backtest P&amp;L result</small></summary>
      <div className="tc-strategy-diag-body">
        <p>QuantLab's existing fixed EMA/RSI rule predicts the direction of an index after 3 or 6 minutes. Evaluate its historical classification accuracy without pretending to buy an option. This is a useful baseline when building a model, but does not account for fills, option premiums or trading costs.</p>
        <div className="tc-replay-picker">
          <label>Index
            <select aria-label="Diagnostic index" value={index} onChange={e=>{
              setIndex(e.target.value as 'INDEX:BANKNIFTY'|'INDEX:NIFTY50');setResult(null)}}>
              <option value="INDEX:BANKNIFTY">BANKNIFTY</option>
              <option value="INDEX:NIFTY50">NIFTY 50</option>
            </select></label>
          <label>Horizon
            <select aria-label="Diagnostic horizon" value={horizon} onChange={e=>{
              setHorizon(e.target.value as '3'|'6');setResult(null)}}>
              <option value="3">3 minutes</option><option value="6">6 minutes</option>
            </select></label>
          <label>Historical window
            <select aria-label="Diagnostic sample count" value={limit} onChange={e=>{
              setLimit(e.target.value as typeof limit);setResult(null)}}>
              <option value="500">Last 500 observed minutes</option>
              <option value="1500">Last 1,500 minutes</option>
              <option value="3000">Last 3,000 minutes</option>
              <option value="5000">Last 5,000 minutes</option>
            </select></label>
          <button type="button" disabled={loading||!spotAvailable} onClick={()=>void diagnostic()}>
            <ClipboardCheck size={16}/>{loading?'Evaluating genuine candles…':'Run signal diagnostics'}
          </button>
        </div>
        {!spotAvailable&&<div className="tc-replay-empty"><Database size={20}/>
          <span>Original {index.replace('INDEX:','')} minute history is unavailable.</span>
          <button type="button" onClick={onOpenData}>Open data setup</button></div>}
        {error&&<div className="tc-api-help" role="alert"><AlertTriangle size={18}/>
          <div><strong>Signal diagnostics could not run</strong><p>{readableError(error)}</p>
          <small>{error instanceof MarketApiError?error.hint:'Check the original source and retry.'}</small></div>
          <button type="button" onClick={onOpenData}>Review original source</button></div>}
        {result&&<><div className="tc-strategy-results">
            <span>Source observations <strong>{fmt(result.observed_source_bars,0)}</strong></span>
            <span>Scored directions <strong>{fmt(result.overall.scored,0)}</strong></span>
            <span>Correct directions <strong>{fmt(result.overall.correct,0)}</strong></span>
            <span>Accuracy <strong>{result.overall.directional_accuracy===null?'Insufficient evidence':
              fmt(result.overall.directional_accuracy*100)+'%'}</strong></span>
            <span>Unverifiable gaps <strong>{fmt(result.overall.unverifiable,0)}</strong></span>
          </div><div className="tc-table-scroll"><table><thead><tr>
            <th>IST session</th><th>Scored</th><th>Correct</th><th>Incorrect</th><th>No trade</th><th>Unverifiable</th><th>Accuracy</th>
          </tr></thead><tbody>{result.days.map(d=><tr key={d.session_ist}>
            <td>{d.session_ist}</td><td>{d.scored}</td><td>{d.correct}</td>
            <td>{d.incorrect}</td><td>{d.no_trade}</td><td>{d.unverifiable}</td>
            <td>{d.directional_accuracy===null?'—':fmt(d.directional_accuracy*100)+'%'}</td>
          </tr>)}</tbody></table></div>
          <p className="tc-muted">Evidence: {result.model_version}. {result.disclaimer} {result.source_warning}
            {result.has_more_history?' Additional older historical bars are not included.':''}</p>
        </>}
      </div>
    </details>
  </div>
}
