import {useEffect,useState} from 'react'
import ResearchPlot from './ResearchPlots'
import {marketApi,readableError} from './tradingCockpitApi'
import './market-intelligence-dashboard.css'

type Greek={delta:number;gamma:number;theta_day:number;vega_iv_point:number;rho_rate_point:number}
type Position={id:string;symbol:string;quantity:number;entry_price:number;expiry:string|null;strike:number|null;contract_identity:string|null;gross_notional_inr:number;estimated_net_pnl_inr:number|null;estimated_charges_inr:number|null;greeks:Greek|null;iv_pct:number|null;model_receipt_utc:string|null;state:string;mark:{bid:number|null;received_utc:string;source:string}|null;exit_levels:Record<string,{sell_bid:number|null;model_underlying_move_points:number|null}>|null}
type Scenario={move_points:number;net_pnl_inr:number}
type Risk={positions:Position[];total_open:number;marked_count:number;coverage_limited:boolean;marked_net_pnl_inr:number|null;all_positions_marked:boolean;aggregate_greeks:Greek|null;fresh_greeks_count:number;generated_utc:string;warning:string;portfolio_scenario?:{state:string;reason:string;anchor_spot:number|null;points:Scenario[];premium_at_risk:number|null;horizon_minutes:number;iv_change_points:number;max_receipt_skew_seconds:number|null}}
const fmt=(n:number|null|undefined,d=2)=>n==null?'—':n.toLocaleString('en-IN',{maximumFractionDigits:d})
const money=(n:number|null|undefined)=>n==null?'—':(n<0?'−₹':'₹')+fmt(Math.abs(n))
const tm=(v:string|null|undefined)=>v?new Date(v).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',dateStyle:'short',timeStyle:'medium'}):'—'
function Stat({label,value,detail}:{label:string;value:string;detail?:string}){return <div className="mi-risk-stat"><span>{label}</span><strong>{value}</strong>{detail&&<small>{detail}</small>}</div>}
export default function PositionsRisk({onOpenJournal,onOpenChain,compact=false}:{onOpenJournal?:()=>void;onOpenChain?:()=>void;compact?:boolean}){
 const [data,setData]=useState<Risk|null>(null),[error,setError]=useState('')
 const [iv,setIv]=useState('0'),[horizon,setHorizon]=useState('5')
 const [settings,setSettings]=useState({iv:0,horizon:5})
 useEffect(()=>{
   let active=true,busy=false
   const c=new AbortController()
   setData(null);setError('')
   const poll=async()=>{if(busy)return;busy=true;try{const r=await marketApi<Risk>('/api/trading-cockpit/options/positions?horizon_minutes='+settings.horizon+'&iv_change_points='+settings.iv,{signal:c.signal});if(active){setData(r);setError('')}}catch(e){if(active)setError(readableError(e))}finally{busy=false}}
   void poll();const t=window.setInterval(()=>{if(!document.hidden)void poll()},15000)
   return()=>{active=false;c.abort();window.clearInterval(t)}
 },[settings])
 const safe=error?null:data
 const g=safe?.aggregate_greeks,sc=safe?.portfolio_scenario
 const debit=safe&&!safe.coverage_limited?safe.positions.reduce((sum,p)=>sum+p.gross_notional_inr,0):null
 const allGreeks=!!safe&&!safe.coverage_limited&&safe.fresh_greeks_count===safe.total_open
 if(compact)return <section className="mi-card" aria-label="Open option positions summary">
  <div className="mi-heading"><div><span className="mi-kicker">MANUAL JOURNAL · READ-ONLY</span><h3>Open positions</h3></div><a href="#/tradingpositions">Portfolio risk →</a></div>
  {safe?<><div className="mi-risk-grid"><Stat label="Recorded open positions" value={String(safe.total_open)}/><Stat label={safe.all_positions_marked?'Estimated net P&L':'Marked subset P&L'} value={money(safe.marked_net_pnl_inr)} detail={safe.marked_count+'/'+safe.total_open+' fresh bid marks'}/></div><p className="mi-muted">Premium debit {money(debit)} · {tm(safe.generated_utc)} IST. Not a broker account balance.</p></>:<p className="mi-muted">{error?'Current position marks unavailable.':'Checking manual positions…'}</p>}
 </section>
 return <section className="mi-risk" aria-label="Options positions and portfolio risk">
  <header className="mi-card mi-heading"><div><span className="mi-kicker">READ-ONLY · LONG OPTIONS</span><h3>Positions &amp; risk</h3><p className="mi-muted">Reuses your manual trade journal and original quote/depth evidence. This is not a connected Zerodha account balance.</p></div><div className="mi-risk-actions"><button className="ws-button" onClick={onOpenChain}>Find contract</button><button className="ws-button" onClick={onOpenJournal}>Manage manual fills</button></div></header>
  {error&&<p className="tc-error" role="alert">{error} · previous marks withheld.</p>}
  {!data&&!error&&<p role="status">Reading open journal positions and saved original bids…</p>}
  {safe&&<>
   <div className="mi-card"><h4>Portfolio exposure</h4><p className="mi-muted">Calculated {tm(safe.generated_utc)} IST · {safe.total_open} recorded open positions · {safe.marked_count} with sufficient fresh bid evidence.</p><div className="mi-risk-grid">
    <Stat label="Open premium debit" value={money(debit)} detail="Entry premium only; full long-option premium is at risk"/>
    <Stat label={safe.all_positions_marked?'Estimated combined net P&L':'Marked subset net P&L'} value={money(safe.marked_net_pnl_inr)} detail={safe.marked_count+'/'+safe.total_open+' positions · estimated fees'}/>
    <Stat label="Net delta" value={fmt(g?.delta,3)} detail={(allGreeks?'All positions':'Fresh-model subset')+' · INR per index point'}/>
    <Stat label="Net gamma" value={fmt(g?.gamma,5)} detail="Delta change per index point"/>
    <Stat label="Net theta / day" value={money(g?.theta_day)} detail="Model time decay"/>
    <Stat label="Net vega / IV point" value={money(g?.vega_iv_point)} detail="One volatility percentage point"/>
   </div>{!allGreeks&&<p className="mi-muted">Greek coverage {safe.fresh_greeks_count}/{safe.total_open}; missing exposures are not zero-filled. {safe.coverage_limited?'Journal result may be truncated.':''}</p>}</div>
   <div className="mi-card"><h4>Combined spot / volatility scenarios</h4><p className="mi-muted">One common spot shock and IV shock applied to all eligible linked legs. Uses independently inverted quote IV, model time decay, current half-spread, assumed slippage and estimated round-trip charges. Not a fill or forecast.</p>
    <form className="mi-risk-actions" onSubmit={e=>{e.preventDefault();const a=Number(iv),b=Number(horizon);if(Number.isFinite(a)&&Number.isInteger(b)&&a>=-50&&a<=50&&b>=1&&b<=1440)setSettings({iv:a,horizon:b})}}>
      <label>IV change (pp)<input aria-label="Portfolio IV change" type="number" required min="-50" max="50" step=".5" value={iv} onChange={e=>setIv(e.target.value)} style={{width:75}}/></label><label>Hold (minutes)<input aria-label="Portfolio hold minutes" type="number" required min="1" max="1440" step="1" value={horizon} onChange={e=>setHorizon(e.target.value)} style={{width:85}}/></label><button className="ws-button" type="submit">Recalculate</button>
    </form>
    {sc?.state==='ready'&&sc.points.length>0?<><p className="mi-muted">Reference spot {fmt(sc.anchor_spot)} · receipt skew {fmt(sc.max_receipt_skew_seconds,1)} s · {sc.horizon_minutes} min · IV {fmt(sc.iv_change_points)} pp</p><ResearchPlot provenance="Conditional BSM model; source-backed quote IV, not executable prices" plot={{kind:'line2d',title:'Combined modeled net P&L after spot shock',x:sc.points.map(p=>p.move_points),x_label:'Bank Nifty move (points)',y_label:'Net INR',traces:[{name:'Modeled net P&L',y:sc.points.map(p=>p.net_pnl_inr)}],reference_lines:[{value:0,label:'Break-even'}]}}/><div className="tc-table-scroll"><table><thead><tr><th>Spot move</th><th>Modeled combined net P&L</th></tr></thead><tbody>{sc.points.map(p=><tr key={p.move_points}><td>{fmt(p.move_points,0)}</td><td className={p.net_pnl_inr>=0?'mi-positive':'mi-negative'}>{money(p.net_pnl_inr)}</td></tr>)}</tbody></table></div></>:<p className="mi-muted">{sc?.reason||'Combined scenario unavailable until all open legs have fresh model receipts.'}</p>}
   </div>
   <div className="mi-card"><h4>All journal positions</h4>{!safe.positions.length?<p className="mi-muted">No manual open positions. Use Find contract and log actual fills; no broker order is placed.</p>:<div className="tc-table-scroll"><table aria-label="Open option position risk"><thead><tr><th>Contract</th><th>Units</th><th>Entry</th><th>Observed exit bid</th><th>Est. net P&L</th><th>Model IV</th><th>Break-even bid</th><th>State</th></tr></thead><tbody>{safe.positions.map(p=><tr key={p.id}><td>{p.symbol}<br/><small>{p.expiry||'Unlinked contract'}</small></td><td>{p.quantity}</td><td>{money(p.entry_price)}</td><td>{money(p.mark?.bid)}</td><td>{money(p.estimated_net_pnl_inr)}</td><td>{p.iv_pct==null?'—':fmt(p.iv_pct)+'%'}</td><td>{money(p.exit_levels?.break_even?.sell_bid)}</td><td>{p.state.replaceAll('_',' ')}</td></tr>)}</tbody></table></div>}</div>
   <p className="mi-muted">{safe.warning}</p>
  </>}
 </section>
}
