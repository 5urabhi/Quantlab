import {useMemo,useState} from 'react'
import {AlertTriangle,ArrowDownRight,ArrowUpRight,ChartLine,ShieldCheck} from 'lucide-react'
import './index-exposure.css'

export type IndexTrade={
  session_ist:string;signal_utc:string;entry_utc:string;exit_utc:string
  direction:'UP'|'DOWN';side:string;entry_points:number;exit_points:number
  index_move_pct:number;exposure_return_pct:number;allocated_inr:number
  gross_pnl_inr:number;illustrative_cost_inr:number;net_pnl_inr:number
  equity_inr:number;actual_hold_minutes?:number;exit_reason?:string
}
export type ScenarioResult={
  mode:'ILLUSTRATIVE_SIGNED_INDEX_EXPOSURE_ONLY';horizon_minutes:number
  hold_rule?:'fixed'|'signal_reversal'|'signal_reversal_or_cap';reversal_cap_minutes?:number|null
  average_hold_minutes?:number|null
  starting_capital_inr:number;ending_capital_inr:number
  net_pnl_inr:number;net_return_pct:number
  max_closed_trade_drawdown_pct:number;cost_bps_per_side:number
  allocation_pct:number;trade_count:number;winning_trades:number
  losing_trades:number;breakeven_trades:number;win_rate:number|null
  total_illustrative_cost_inr:number
  skipped:{no_signal:number;position_open:number;session_cutoff:number
    missing_entry:number;missing_exit_or_path:number;missing_session_close?:number}
  equity_curve:{timestamp_utc:string;equity_inr:number}[]
  latest_trades:IndexTrade[];entry_policy:string;exit_policy:string
  disclaimer:string
}
const cash=(value:number)=>new Intl.NumberFormat('en-IN',{
  style:'currency',currency:'INR',minimumFractionDigits:2,maximumFractionDigits:2,
}).format(value)
const pct=(n:number)=>new Intl.NumberFormat('en-IN',{
  minimumFractionDigits:2,maximumFractionDigits:3,
}).format(n)+'%'
const clock=(utc:string)=>new Date(utc).toLocaleString('en-IN',{
  timeZone:'Asia/Kolkata',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',
  hourCycle:'h23',
})
const pts=(n:number)=>new Intl.NumberFormat('en-IN',{
  maximumFractionDigits:2,minimumFractionDigits:2,
}).format(n)

function EquityCurve({data}:{data:ScenarioResult['equity_curve']}){
  const [focus,setFocus]=useState<number|null>(null)
  const width=860,height=220,left=66,right=18,top=14,bottom=35
  const plotWidth=width-left-right,plotHeight=height-top-bottom
  const minimum=Math.min(...data.map(x=>x.equity_inr))
  const maximum=Math.max(...data.map(x=>x.equity_inr))
  const pad=Math.max(1,(maximum-minimum)*.13)
  const low=minimum-pad,high=maximum+pad
  const loc=(index:number)=>{
    const x=left+plotWidth*index/Math.max(1,data.length-1)
    const y=top+plotHeight*(high-data[index].equity_inr)/(high-low)
    return {x,y}
  }
  const shape=useMemo(()=>{
    if(data.length<2)return ''
    return data.map((_,i)=>{
      const {x,y}=loc(i)
      return (i===0?'M':'L')+x.toFixed(2)+','+y.toFixed(2)
    }).join(' ')
  // The line is derived from source-verified scenario trades, never future price estimates.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[data])
  const current=focus!==null?data[focus]:null
  const point=focus!==null?loc(focus):null
  const rows=[0,.5,1]
  return <div className="tc-index-chart" aria-label="Illustrative investment balance over closed trades">
    <div className="tc-index-chart-head">
      <strong><ChartLine size={17}/> Simulated account balance after each completed trade</strong>
      <small>{current?clock(current.timestamp_utc)+' · '+cash(current.equity_inr):
        'Move over chart to inspect hypothetical balances'}</small>
    </div>
    <svg viewBox={`0 0 ${width} ${height}`} role="img"
      aria-label="Illustrative index-exposure balance curve; exact values also appear in trade journal">
      {rows.map((n,i)=>{
        const y=top+n*plotHeight
        const val=high-n*(high-low)
        return <g key={i}>
          <line x1={left} x2={width-right} y1={y} y2={y} className="tc-index-grid"/>
          <text x={left-9} y={y+3} textAnchor="end" className="tc-index-axis">{Math.round(val).toLocaleString('en-IN')}</text>
        </g>
      })}
      {data.length>1&&<path d={shape} className="tc-index-curve"/>}
      {data.length===1&&<line x1={left} x2={width-right}
        y1={loc(0).y} y2={loc(0).y} className="tc-index-curve"/>}
      {point&&<g>
        <line x1={point.x} x2={point.x} y1={top} y2={height-bottom}
          className="tc-index-guide"/>
        <circle cx={point.x} cy={point.y} r="5" className="tc-index-dot"/>
      </g>}
      <text x={left} y={height-12} className="tc-index-axis">
        {data.length?clock(data[0].timestamp_utc):'Start'}</text>
      <text x={width-right} y={height-12} textAnchor="end" className="tc-index-axis">
        {data.length?clock(data[data.length-1].timestamp_utc):'End'}</text>
      <rect x={left} y={top} width={plotWidth} height={plotHeight}
        fill="transparent" onMouseMove={event=>{
          const bounds=event.currentTarget.getBoundingClientRect()
          const share=(event.clientX-bounds.left)/bounds.width
          setFocus(Math.max(0,Math.min(data.length-1,
            Math.round(share*Math.max(0,data.length-1)))))
        }} onMouseLeave={()=>setFocus(null)}/>
    </svg>
    <p className="tc-muted">This plots account values only at completed simulated exits. It does not display intratrade drawdown or executable account performance.</p>
  </div>
}

export default function IndexExposureScenario({scenario}:{scenario:ScenarioResult}){
  const change=scenario.net_pnl_inr
  const wins=scenario.winning_trades,losses=scenario.losing_trades
  return <section className="tc-index-scenario" aria-label="Illustrative BANKNIFTY index-exposure investment simulation">
    <header className="tc-index-scenario-head">
      <div><span className="tc-page-kicker">NON-EXECUTABLE INDEX EXPOSURE SCENARIO</span>
        <h3>What would happen to your illustrative investment?</h3>
        <p>Hypothetical 1× exposure to BANKNIFTY's index-point movement, not BANKNIFTY CE/PE prices.</p>
      </div>
      <span className="tc-index-nonoption"><ShieldCheck size={15}/> Not an option P&amp;L estimate</span>
    </header>
    <div className="tc-index-stats">
      <div><span>Starting capital</span><strong>{cash(scenario.starting_capital_inr)}</strong></div>
      <div><span>Ending illustrative balance</span><strong>{cash(scenario.ending_capital_inr)}</strong></div>
      <div><span>Illustrative net change</span>
        <strong className={change>=0?'tc-illustrative-positive':'tc-illustrative-negative'}>
          {change>=0?'+':''}{cash(change)}
        </strong><small>{scenario.net_return_pct>=0?'+':''}{pct(scenario.net_return_pct)}</small></div>
      <div><span>Non-overlapping simulated trades</span><strong>{scenario.trade_count}</strong>
        <small>{wins} profitable / {losses} unprofitable</small></div>
      <div><span>Profitability of simulated trades</span>
        <strong>{scenario.win_rate===null?'No trades':pct(scenario.win_rate*100)}</strong></div>
      <div><span>Worst closed-trade drawdown</span>
        <strong>{pct(scenario.max_closed_trade_drawdown_pct)}</strong>
        <small>Excludes unrealized/intratrade losses</small></div>
    </div>
    <div className="tc-index-exit-rules" aria-label="Precise entry and exit logic">
      <div><strong>1 · Enter only after a signal</strong>
        <p>UP = hypothetical long exposure; DOWN = hypothetical short exposure. Ignore NO TRADE.</p></div>
      <div><strong>2 · Assume next observed open</strong>
        <p>A signal needs a completed one-minute candle. Entry uses the following observed candle's opening index level, not the signal's close.</p></div>
      <div><strong>3 · {scenario.hold_rule==='signal_reversal'?'Hold until opposite signal':
        scenario.hold_rule==='signal_reversal_or_cap'?'Hold until reversal or time cap':
        'Hold '+scenario.horizon_minutes+' minute'+(scenario.horizon_minutes===1?'':'s')}</strong>
        <p>{scenario.hold_rule==='signal_reversal'?
          'Exit only after the opposite completed signal, at the next observed open. Otherwise exit by the observed session-close opening price. NO TRADE is neutral.':
          scenario.hold_rule==='signal_reversal_or_cap'?
          'Exit after the opposite completed signal, or at the '+scenario.reversal_cap_minutes+'-minute cap, whichever comes first. Force flat before session end.':
          'Ignore overlapping signals while the position is open. Exit at the observed opening index level after the selected holding period.'}</p></div>
      <div><strong>4 · Stay flat across session close</strong>
        <p>No synthetic missing-minute fills or overnight positions. Incomplete trades are excluded and counted separately.</p></div>
    </div>
    {scenario.trade_count>0?<EquityCurve data={scenario.equity_curve}/>:<div className="tc-index-zero">
      <AlertTriangle size={20}/><div><strong>No complete simulated trades in this sample</strong>
        <p>There may be no actionable signals, insufficient source history, missing entry/exit observations, or insufficient session time for a {scenario.horizon_minutes}-minute hold.</p></div>
    </div>}
    <div className="tc-index-footnotes">
      <span>Capital allocation <b>{pct(scenario.allocation_pct)}</b></span>
      <span>Assumed costs per side <b>{scenario.cost_bps_per_side} bps</b></span>
      <span>Illustrative round-trip costs <b>{cash(scenario.total_illustrative_cost_inr)}</b></span>
      <span>Other hypothetical costs <b>Not modeled</b></span>
    </div>
    <details className="tc-index-trade-details">
      <summary>See {scenario.latest_trades.length} latest complete entries and exits</summary>
      <div className="tc-table-scroll"><table><thead><tr>
        <th>Signal IST</th><th>Direction</th><th>Exit reason</th><th>Hold</th><th>Entry (IST / index)</th>
        <th>Exit (IST / index)</th><th>Index move (points)</th>
        <th>Index move (%)</th><th>Scenario return</th>
        <th>Gross ₹</th><th>Assumed cost ₹</th>
        <th>Illustrative net ₹</th><th>Balance ₹</th></tr></thead>
        <tbody>{[...scenario.latest_trades].reverse().map(t=><tr key={t.signal_utc}>
          <td>{clock(t.signal_utc)}</td>
          <td><span className={'tc-direction '+t.direction.toLowerCase()}>
            {t.direction==='UP'?<ArrowUpRight size={13}/>:<ArrowDownRight size={13}/>}
            {t.direction==='UP'?'Long proxy':'Short proxy'}</span></td>
          <td>{t.exit_reason?.replaceAll('_',' ')||'Fixed hold'}</td><td>{t.actual_hold_minutes??scenario.horizon_minutes}m</td>
          <td>{clock(t.entry_utc)} · {pts(t.entry_points)}</td>
          <td>{clock(t.exit_utc)} · {pts(t.exit_points)}</td>
          <td className={t.exit_points>=t.entry_points?'tc-illustrative-positive':'tc-illustrative-negative'}>
            {t.exit_points>=t.entry_points?'+':''}{pts(t.exit_points-t.entry_points)}</td>
          <td>{t.index_move_pct>=0?'+':''}{pct(t.index_move_pct)}</td>
          <td>{t.exposure_return_pct>=0?'+':''}{pct(t.exposure_return_pct)}</td>
          <td>{t.gross_pnl_inr>=0?'+':''}{cash(t.gross_pnl_inr)}</td>
          <td>{cash(t.illustrative_cost_inr)}</td>
          <td className={t.net_pnl_inr>=0?'tc-illustrative-positive':'tc-illustrative-negative'}>
            {t.net_pnl_inr>=0?'+':''}{cash(t.net_pnl_inr)}</td>
          <td>{cash(t.equity_inr)}</td>
        </tr>)}</tbody></table></div>
    </details>
    <p className="tc-index-skips">Source and rule exclusions:
      {' '}{scenario.skipped.position_open} overlapping signals;
      {' '}{scenario.skipped.session_cutoff} too close to session end;
      {' '}{scenario.skipped.missing_entry} no exact entry bar;
      {' '}{scenario.skipped.missing_exit_or_path} incomplete observed paths;
      {' '}{scenario.skipped.missing_session_close||0} missing observed session-close bars.
    </p>
    <div className="tc-index-disclaimer"><AlertTriangle size={18}/>
      <p><strong>Not actual investment or options P&amp;L.</strong> {scenario.disclaimer}</p></div>
  </section>
}
