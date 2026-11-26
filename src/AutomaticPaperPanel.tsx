import {useEffect,useRef,useState} from 'react'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
import type {BrokerProfile} from './SpreadOpportunityScanner'

type ExitMode='fixed'|'target_stop'|'trailing'|'signal_reversal'|'adaptive'
type Config={exit_mode:ExitMode;stop_net:number;trail_net:number;liquidity_grace_seconds:number;slippage_bps:number;enabled:boolean;capital:number;max_loss:number;target_net:number;max_lots:number;hold_seconds:number;broker_profile:BrokerProfile}
type Leg={identity:string;strike:number;side:string;expiry:string;action:string;bid:number;ask:number;iv_pct:number;greeks:Record<string,number>;oi:number;volume:number;book_utc:string;activity:{receipts_120s:number;distinct_trade_times_120s:number}}
type Candidate={strategy:string;identities:string[];lots:number;units:number;modeled_risk_inr:number;entry_cashflow_inr:number;immediate_roundtrip_net_inr:number;entry_fees_inr:number;immediate_exit_fees_inr:number;stress_favorable_net_inr:number;scenario_net_inr:Record<string,number>;score:number;legs:Leg[]}
type Decision={config?:Config;peak_net_inr?:number|null;trail_armed?:boolean;trail_floor_inr?:number;latest_ema_direction?:string;liquidity_bad_since_utc?:string|null;hold_realized_seconds?:number;id:number;lane:string;state:string;action:string;reason:string;decision_utc:string;selected?:Candidate;candidates:Candidate[];source:{direction:string;valid_contracts:number;subscribed_contracts:number;scenario_move_points?:number;rsi14?:number;ema9?:number;ema21?:number;rejections?:Record<string,number>};rejections:Record<string,number>;entry_reason?:string;exit_reason?:string;exit_trigger?:string;mark_net_inr?:number;mark_observed_utc?:string;net_pnl_inr?:number;fees_inr?:number;observed_entry_risk_inr?:number;hold_deadline_utc?:string}
type Lane={decisions:number;no_trade:number;entries:number;scored:number;profitable:number;losing:number;target_hits:number;censored:number;entry_rejected:number;conditional_net_inr:number|null;remaining_session_risk_inr:number;halted:boolean;latest:Decision|null;active:Decision|null}
type Status={config:Config;session_ist:string;lanes:Record<string,Lane>;recent:Decision[];health:{state:string;last_cycle_utc:string|null;last_error:string|null};regular_session:boolean;warning:string}
const initial:Config={enabled:false,capital:17000,max_loss:4250,target_net:100,max_lots:3,hold_seconds:900,broker_profile:'zerodha',exit_mode:'adaptive',stop_net:250,trail_net:50,liquidity_grace_seconds:20,slippage_bps:0}
const base='/api/trading-cockpit/automatic-paper'
const fmt=(v:number|null|undefined,d=2)=>v==null||!Number.isFinite(v)?'—':v.toLocaleString('en-IN',{maximumFractionDigits:d})
const money=(v:number|null|undefined)=>v==null?'—':'₹'+fmt(v)
const label=(v:string|undefined)=>v?.replaceAll('_',' ')||'—'
const ist=(v:string|null|undefined)=>v?new Date(v).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour12:false}):'—'
const contracts=(c:Candidate|undefined)=>c?.legs.map(l=>l.action+' '+fmt(l.strike,0)+' '+l.side).join(' / ')||'—'

function CandidateDetails({c}:{c:Candidate}){
 return <div className="lq-section">
  <div className="lq-section-title"><div><strong>{label(c.strategy)} · {c.lots} lot(s) · {c.units} units/leg</strong><small>{contracts(c)} · {c.legs[0]?.expiry}</small></div></div>
  <div className="lq-results">
   <div className="lq-metric"><span>Modeled risk budget</span><strong>{money(c.modeled_risk_inr)}</strong><small>Not verified broker margin</small></div>
   <div className="lq-metric"><span>Entry cash flow</span><strong>{money(c.entry_cashflow_inr)}</strong><small>Negative = debit</small></div>
   <div className="lq-metric"><span>Crossing drag</span><strong>{money(c.immediate_roundtrip_net_inr)}</strong><small>Same-book hypothetical net</small></div>
   <div className="lq-metric"><span>Stressed favorable scenario</span><strong>{money(c.stress_favorable_net_inr)}</strong><small>Assumed move; not expected P&amp;L</small></div>
   <div className="lq-metric"><span>Estimated entry + exit fees</span><strong>{money(c.entry_fees_inr+c.immediate_exit_fees_inr)}</strong><small>Immediate close assumption</small></div>
   <div className="lq-metric"><span>Flat / adverse scenario</span><strong>{money(c.scenario_net_inr.flat)} / {money(c.scenario_net_inr.adverse)}</strong><small>Model stresses, not loss guarantees</small></div>
  </div>
  <details><summary>Legs, original receipt times &amp; Greeks</summary><div className="lq-scroll"><table className="lq-table"><thead><tr><th>Leg</th><th>Source time IST</th><th>Bid / ask</th><th>IV %</th><th>Delta</th><th>Gamma</th><th>Theta/day</th><th>Vega/IV pt</th><th>OI / volume</th><th>Recent books / trades</th></tr></thead><tbody>{c.legs.map(l=><tr key={l.identity}><td>{l.action} {l.strike} {l.side}<small>{l.identity}</small></td><td>{ist(l.book_utc)}</td><td>{money(l.bid)} / {money(l.ask)}</td><td>{fmt(l.iv_pct)}</td><td>{fmt(l.greeks.delta,4)}</td><td>{fmt(l.greeks.gamma,6)}</td><td>{fmt(l.greeks.theta_day)}</td><td>{fmt(l.greeks.vega_iv_point)}</td><td>{fmt(l.oi,0)} / {fmt(l.volume,0)}</td><td>{l.activity.receipts_120s} / {l.activity.distinct_trade_times_120s}</td></tr>)}</tbody></table></div></details>
 </div>
}

function LaneCard({name,lane}:{name:string;lane:Lane}){
 const r=lane.active||lane.latest
 const source=r?.source
 const reasons={...source?.rejections,...r?.rejections}
 return <section className="lq-section" aria-label={name+' paper engine'}>
  <div className="lq-section-title"><div><strong>{name}</strong><small>{lane.halted?'Halted for this session: unresolved conditional exposure':r?label(r.state)+' · '+ist(r.decision_utc)+' IST':'No paper decisions recorded this session'}</small></div><span className="lq-chip">{lane.halted?'HALTED':lane.active?'MONITORING':r?.state==='no_trade'?'NO TRADE':r?label(r.state).toUpperCase():'WAITING'}</span></div>
  <div className="lq-results">
   <div className="lq-metric"><span>Directional rule</span><strong>{source?.direction||'—'}</strong><small>EMA 9/21 · RSI {fmt(source?.rsi14,1)}</small></div>
   <div className="lq-metric"><span>Scored paper net</span><strong>{money(lane.conditional_net_inr)}</strong><small>{lane.profitable} positive / {lane.losing} negative · {lane.scored} scored</small></div>
   <div className="lq-metric"><span>Entry attempts</span><strong>{lane.entries}</strong><small>{lane.no_trade} no trade · {lane.entry_rejected} rejected · {lane.censored} censored</small></div>
   <div className="lq-metric"><span>Remaining session risk allowance</span><strong>{money(lane.remaining_session_risk_inr)}</strong><small>Scored losses reduce allowance; wins do not replenish it</small></div>
   <div className="lq-metric"><span>Latest observed close mark</span><strong>{money(r?.mark_net_inr)}</strong><small>{ist(r?.mark_observed_utc)} IST · not an actual fill</small></div>
  </div>
  {r&&<><p className="lq-hint">Applied exit: {label(r.config?.exit_mode||'target_stop')} · maximum hold {r.config?.hold_seconds!=null?fmt(r.config.hold_seconds/60)+'m':'—'} · actual conditional hold {r.hold_realized_seconds!=null?fmt(r.hold_realized_seconds)+'s':'—'} · peak net {money(r.peak_net_inr)} · trailing floor {r.trail_armed?money(r.trail_floor_inr):'Not armed'} · EMA {r.latest_ema_direction||'—'}. {r.liquidity_bad_since_utc?'Liquidity warning since '+ist(r.liquidity_bad_since_utc)+' IST.':''}</p><p className="lq-hint">{label(r.entry_reason||r.reason)}{r.exit_trigger?' · exit trigger: '+label(r.exit_trigger):''}{r.exit_reason?' · '+label(r.exit_reason):''}. {source?.valid_contracts??0} evidence-qualified contracts / {source?.subscribed_contracts??0} subscribed. {source?.scenario_move_points!=null?'ATR stress move '+fmt(source.scenario_move_points)+' points.':''}</p>
   {r.selected&&<CandidateDetails c={r.selected}/>}
   {!!r.candidates?.length&&<details><summary>Ranked alternatives &amp; heuristic scores</summary><div className="lq-scroll"><table className="lq-table"><thead><tr><th>Structure</th><th>Legs</th><th>Lots</th><th>Risk</th><th>Stress net</th><th>Score</th></tr></thead><tbody>{r.candidates.map(c=><tr key={c.strategy+c.identities.join()}><td>{label(c.strategy)}</td><td>{contracts(c)}</td><td>{c.lots}</td><td>{money(c.modeled_risk_inr)}</td><td>{money(c.stress_favorable_net_inr)}</td><td>{fmt(c.score,4)}</td></tr>)}</tbody></table></div></details>}
   {Object.keys(reasons).length>0&&<details><summary>Why other opportunities were rejected</summary><p className="lq-hint">{Object.entries(reasons).sort((a,b)=>b[1]-a[1]).map(([k,v])=>label(k)+': '+v).join(' · ')}</p></details>}
  </>}
 </section>
}

export default function AutomaticPaperPanel(){
 const [config,setConfig]=useState<Config>(initial)
 const [status,setStatus]=useState<Status|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false)
 const initialized=useRef(false)
 useEffect(()=>{let alive=true,pending=false
  const poll=async()=>{if(!alive||pending||document.hidden)return;pending=true
   try{const s=await marketApi<Status>(base);if(!alive)return;setStatus(s);setError('');if(!initialized.current){initialized.current=true;setConfig(s.config)}}catch(e){if(alive)setError(readableError(e))}finally{pending=false}}
  void poll();const timer=window.setInterval(()=>void poll(),5000);return()=>{alive=false;window.clearInterval(timer)}
 },[])
 const apply=async(enable:boolean)=>{if(busy)return;setBusy(true);setError('')
  try{const s=enable?await marketPost<Status>(base+'/configure',{...config,enabled:true}):await marketPost<Status>(base+'/pause',{});setStatus(s);setConfig(s.config)}catch(e){setError(readableError(e))}finally{setBusy(false)}}
 const set=(key:keyof Config,v:number|string)=>setConfig(prev=>({...prev,[key]:v}))
 return <section className="lq-section" aria-label="Automatic paper decisions">
  <div className="lq-section-title"><div><strong>Automatic paper decisions</strong><small>Directional CE/PE and defined-risk verticals · no manual strike selection</small></div><span className="lq-chip">{status?.config.enabled?'PAPER ENGINE ENABLED':'PAUSED'}</span></div>
  <p className="lq-hint">Set the budget once. Each lane is a separate virtual experiment; neither sends broker orders. Only fresh original evidence and an eligible unvalidated directional rule can produce a paper entry.</p>
  <div className="lq-form">
   <label>Paper capital (₹)<input type="number" min="1000" value={config.capital} onChange={e=>set('capital',Number(e.target.value))}/></label>
   <label>Target net (₹)<input type="number" min="1" value={config.target_net} onChange={e=>set('target_net',Number(e.target.value))}/></label>
   <label>Session modeled loss allowance (₹)<input type="number" min="1" max={config.capital} value={config.max_loss} onChange={e=>set('max_loss',Number(e.target.value))}/></label>
   <label>Exit policy<select value={config.exit_mode} onChange={e=>set('exit_mode',e.target.value)}><option value="adaptive">Adaptive · reversal + trailing + liquidity</option><option value="signal_reversal">Hold until EMA reversal</option><option value="trailing">Trailing net profit</option><option value="target_stop">Net target / stop loss</option><option value="fixed">Fixed duration + loss guard</option></select></label>
   <label>Stop-loss mark (₹)<input type="number" min="1" value={config.stop_net} onChange={e=>set('stop_net',Number(e.target.value))}/></label>
   <label>Trailing drawdown (₹)<input type="number" min="1" value={config.trail_net} onChange={e=>set('trail_net',Number(e.target.value))}/></label>
   <p className="lq-hint">All policies have a loss guard and maximum duration. Target/stop exits at the target mark; trailing/adaptive arms a trailing floor after the target is observed. Reversal waits for the opposite fresh EMA relation. An exit mark triggers a later conditional order-book attempt, not a guaranteed fill.</p>
   <details><summary>Advanced assumptions</summary><div className="lq-controls"><label>Liquidity grace (seconds)<input type="number" min="5" max="120" value={config.liquidity_grace_seconds} onChange={e=>set('liquidity_grace_seconds',Number(e.target.value))}/></label><label>Additional slippage (bps / side)<input type="number" min="0" max="500" value={config.slippage_bps} onChange={e=>set('slippage_bps',Number(e.target.value))}/></label><label>Maximum lots<input type="number" min="1" max="10" value={config.max_lots} onChange={e=>set('max_lots',Number(e.target.value))}/></label><label>Maximum hold<select value={config.hold_seconds} onChange={e=>set('hold_seconds',Number(e.target.value))}><option value="60">1 minute</option><option value="120">2 minutes</option><option value="300">5 minutes</option><option value="600">10 minutes</option><option value="900">15 minutes</option><option value="1800">30 minutes</option></select></label><label>Fee profile<select value={config.broker_profile} onChange={e=>set('broker_profile',e.target.value)}><option value="zerodha">Zerodha retail</option><option value="zerodha_debit_balance">Zerodha ₹40/order</option><option value="dhan">Dhan</option></select></label></div></details>
  </div>
  <div className="lq-actions"><button type="button" disabled={busy||!status} onClick={()=>void apply(true)}>{status?.config.enabled?'Apply to new paper decisions':'Enable automatic paper decisions'}</button>{status?.config.enabled&&<button type="button" disabled={busy} onClick={()=>void apply(false)}>Pause new entries</button>}<span className="lq-hint">Existing paper paths retain their original settings and continue monitoring when paused. New receipt events are checked at roughly 5-second intervals; one actual paper entry attempt per lane per minute. Last cycle: {ist(status?.health.last_cycle_utc)} IST · {label(status?.health.state)}</span></div>
  {error&&<p role="alert" className="lq-alert">{error}</p>}
  {status?.health.last_error&&<p role="alert" className="lq-alert">Local monitor error: {status.health.last_error}</p>}
  {status&&!status.regular_session&&<p className="lq-hint">Outside regular NSE session. Waiting for eligible market data.</p>}
  {status&&<><LaneCard name="Directional options" lane={status.lanes.directional}/><LaneCard name="Defined-risk vertical spreads" lane={status.lanes.spread}/>
  <details className="lq-section"><summary>Prospective decision &amp; outcome journal · latest {status.recent.length}</summary><div className="lq-scroll"><table className="lq-table"><thead><tr><th>Decision IST</th><th>Engine</th><th>Contract / basket</th><th>Lots</th><th>State</th><th>Trigger / reason</th><th>Conditional net</th></tr></thead><tbody>{status.recent.map(r=><tr key={r.id}><td>{r.decision_utc.slice(0,10)} · {ist(r.decision_utc)}</td><td>{label(r.lane)}</td><td>{contracts(r.selected)}</td><td>{r.selected?.lots??'—'}</td><td>{label(r.state)}</td><td>{label(r.exit_trigger||r.entry_reason||r.reason)}</td><td>{money(r.net_pnl_inr)}</td></tr>)}</tbody></table></div></details>
  <p className="lq-disclaimer">{status.warning} Passive bid/ask capture is not enabled: actual queue fills have not been measured.</p></>}
 </section>
}
