import {useEffect,useState} from 'react'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
import './market-intelligence-dashboard.css'

type Trade={signal:string;decision_utc:string;identity:string;entry_utc:string;exit_utc:string;net_pnl_inr:number;fees_inr:number}
type DayRule={rule:string;state:string;signals:number;attempts:number;completed:number;resolved_subset_net_inr:number|null;session_net_inr:number|null;reasons:Record<string,number>;trades:Trade[]}
type Day={date:string;cohort:string;index_minutes:number;state:string;matched_complete:boolean;rules:DayRule[];selection?:Record<string,{identity:string;strike:number;expiry:string;lot_size:number;ask:number}>;selection_receipt_utc?:string}
type Summary={rule:string;matched_sessions:number;trades:number;wins:number;losses:number;flat:number;win_rate_pct:number|null;net_pnl_inr:number|null;average_net_inr:number|null;fees_inr:number|null;profit_factor:number|null;stress_extra_25_inr:number|null;stress_extra_50_inr:number|null;worst_session_inr:number|null;max_intraday_closed_drawdown_inr:number|null}
type Study={study_id:string;version:string;generated_utc:string;state:string;start_date:string;end_date:string;requested_weekdays:number;matched_days:number;evaluation_requested_weekdays:number;evaluation_matched_days:number;development:Summary[];evaluation:Summary[];days:Day[];day_states:Record<string,number>;warning:string;settings:Record<string,string|number>}
type Job={status:string;stage?:string;percent?:number;error?:string;result?:Study}
const api='/api/trading-cockpit/paper/scalping-validation'
const dateBefore=(days:number)=>new Date(Date.now()-days*86400000).toLocaleDateString('en-CA',{timeZone:'Asia/Kolkata'})
const fmt=(v:number|null|undefined,d=2)=>v==null?'—':v.toLocaleString('en-IN',{maximumFractionDigits:d})
const money=(v:number|null|undefined)=>v==null?'—':(v<0?'−₹':'₹')+fmt(Math.abs(v))
const human=(s:string)=>s.replaceAll('_',' ')
function SummaryTable({rows}:{rows:Summary[]}){
 return <div className="tc-table-scroll"><table aria-label="Matched strategy comparison"><thead><tr><th>Rule</th><th>Matched days</th><th>Trades</th><th>Win %</th><th>Net P&L</th><th>Average net</th><th>Fees</th><th>Profit factor</th><th>Extra ₹25/trade</th><th>Extra ₹50/trade</th><th>Worst day</th></tr></thead><tbody>{rows.map(r=><tr key={r.rule}><td>{human(r.rule)}</td><td>{r.matched_sessions}</td><td>{r.trades}</td><td>{fmt(r.win_rate_pct)}</td><td className={r.net_pnl_inr==null?'':r.net_pnl_inr>0?'mi-positive':'mi-negative'}>{money(r.net_pnl_inr)}</td><td>{money(r.average_net_inr)}</td><td>{money(r.fees_inr)}</td><td>{fmt(r.profit_factor)}</td><td>{money(r.stress_extra_25_inr)}</td><td>{money(r.stress_extra_50_inr)}</td><td>{money(r.worst_session_inr)}</td></tr>)}</tbody></table></div>
}
export default function ScalpingValidation(){
 const [start,setStart]=useState(()=>dateBefore(30)),[end,setEnd]=useState(()=>dateBefore(1))
 const [capital,setCapital]=useState('17000'),[lots,setLots]=useState('3'),[premium,setPremium]=useState('180')
 const [hold,setHold]=useState('5'),[fee,setFee]=useState('50'),[loss,setLoss]=useState('10')
 const [job,setJob]=useState(''),[progress,setProgress]=useState(''),[error,setError]=useState('')
 const [study,setStudy]=useState<Study|null>(null)
 const [starting,setStarting]=useState(false)
 useEffect(()=>{let alive=true
  marketApi<{study:Study|null}>(api+'/latest').then(r=>{if(alive)setStudy(r.study)}).catch(e=>{if(alive)setError(readableError(e))})
  return()=>{alive=false}},[])
 useEffect(()=>{if(!job)return
  let active=true,busy=false
  const poll=async()=>{if(!active||busy)return;busy=true
   try{const r=await marketApi<Job>('/api/jobs/'+job);if(!active)return
    setProgress((r.stage||r.status)+' · '+(r.percent??0)+'%')
    if(r.status==='complete'){setStudy(r.result||null);setJob('');setProgress('')}
    else if(['error','cancelled','interrupted'].includes(r.status)){setError(r.error||r.status);setJob('');setProgress('')}
   }catch(e){if(active){setError(readableError(e));setJob('')}}
   finally{busy=false}
  }
  void poll();const timer=window.setInterval(()=>void poll(),2000)
  return()=>{active=false;window.clearInterval(timer)}
 },[job])
 async function run(){
  setStarting(true);setError('')
  try{const r=await marketPost<{job_id:string}>(api,{start_date:start,end_date:end,capital:Number(capital),lots:Number(lots),target_premium:Number(premium),hold_minutes:Number(hold),fee_floor_per_side:Number(fee),daily_loss_limit_pct:Number(loss)});setJob(r.job_id);setProgress('Queued')}
  catch(e){setError(readableError(e))}
  finally{setStarting(false)}
 }
 return <section className="mi-card mi-risk" aria-label="Historical net scalping comparison">
  <header className="mi-heading"><div><span className="mi-kicker">ORIGINAL DEPTH · MATCHED RULES</span><h3>Is sideways scalping profitable after costs?</h3><p className="mi-muted">Compare range reversal, ordinary mean reversion and EMA 9/21 using the same prior-selected CE/PE contracts and recorded original bid/ask depth. No download, new connection or broker order.</p></div></header>
  <form className="mi-risk-actions" onSubmit={e=>{e.preventDefault();void run()}}>
   <label>Start (IST)<input aria-label="Scalping start date" type="date" required value={start} onChange={e=>setStart(e.target.value)}/></label>
   <label>End (IST)<input aria-label="Scalping end date" type="date" required max={dateBefore(1)} value={end} onChange={e=>setEnd(e.target.value)}/></label>
   <label>Daily research capital ₹<input type="number" required min="1000" max="10000000" value={capital} onChange={e=>setCapital(e.target.value)} style={{width:100}}/></label>
   <label>Lots<input type="number" required min="1" max="50" value={lots} onChange={e=>setLots(e.target.value)} style={{width:60}}/></label>
   <label>Target premium ₹<input type="number" required min="10" max="20000" value={premium} onChange={e=>setPremium(e.target.value)} style={{width:75}}/></label>
   <label>Hold<select value={hold} onChange={e=>setHold(e.target.value)}>{[1,3,5,10,15].map(n=><option key={n} value={n}>{n} min</option>)}</select></label>
   <label>Minimum fee / side ₹<input type="number" required min="0" max="1000" value={fee} onChange={e=>setFee(e.target.value)} style={{width:70}}/></label>
   <label>Daily loss budget %<input type="number" required min="1" max="100" value={loss} onChange={e=>setLoss(e.target.value)} style={{width:65}}/></label>
   <button type="submit" className="ws-button primary" disabled={starting||!!job}>{starting||job?'Research running…':'Run matched validation'}</button>
  </form>
  <p className="mi-muted">Fixed 09:45 prior chain selection; ₹60 premium tolerance, 150 bps maximum quoted spread, 1s latency, 30s receipt windows, 25% displayed depth participation, 5 bps adverse slippage per execution. Fees are the greater of your per-side floor and estimated Zerodha fees, not their sum. No trade-count target; loss budget is a simulated stop after closed trades, not a guaranteed maximum loss.</p>
  {progress&&<p role="status">{progress}</p>}
  {error&&<p role="alert" className="tc-error">{error}</p>}
  {study&&<><h4>Saved study · {study.start_date} to {study.end_date}</h4>
   <p className="mi-muted">{study.study_id} · {human(study.state)} · {study.matched_days}/{study.requested_weekdays} requested weekdays fully matched; evaluation {study.evaluation_matched_days}/{study.evaluation_requested_weekdays}. Not a verified exchange calendar.</p>
   <div className="mi-risk-actions">{Object.entries(study.day_states).map(([k,v])=><span key={k}>{human(k)}: <b>{v}</b></span>)}</div>
   <h4>Chronological evaluation · matched complete subset</h4><SummaryTable rows={study.evaluation}/>
   <details className="mpi-detail"><summary>Development comparison</summary><SummaryTable rows={study.development}/></details>
   <details className="mpi-detail"><summary>Study settings and evidence</summary><div className="mi-risk-grid">{Object.entries(study.settings).map(([k,v])=><div className="mi-risk-stat" key={k}><span>{human(k)}</span><strong>{String(v)}</strong></div>)}</div></details>
   <details className="mpi-detail"><summary>Every requested date · coverage, rules and realized proxy trades</summary>{study.days.map(d=><details key={d.date} className="mpi-detail"><summary>{d.date} · {d.cohort} · {human(d.state)} · {d.index_minutes} minutes</summary>
    {d.selection&&<p className="mi-muted">Prior selection {d.selection_receipt_utc} · {Object.entries(d.selection).map(([s,r])=>s+' '+r.strike+' '+r.expiry+' ('+r.identity+', '+r.lot_size+' units/lot)').join(' | ')}</p>}
    {d.rules.map(r=><details className="mpi-detail" key={r.rule}><summary>{human(r.rule)} · {r.completed} completed / {r.attempts} attempts · {money(r.session_net_inr)} complete session net</summary><p className="mi-muted">{human(r.state)} · {r.signals} signals · completed subset {money(r.resolved_subset_net_inr)} · {Object.entries(r.reasons).map(([k,v])=>human(k)+': '+v).join(', ')}</p><div className="tc-table-scroll"><table><thead><tr><th>Signal</th><th>Contract</th><th>Entry receipt</th><th>Exit receipt</th><th>Fees</th><th>Net P&L</th></tr></thead><tbody>{r.trades.map(t=><tr key={t.decision_utc}><td>{t.signal}</td><td>{t.identity}</td><td>{t.entry_utc}</td><td>{t.exit_utc}</td><td>{money(t.fees_inr)}</td><td>{money(t.net_pnl_inr)}</td></tr>)}</tbody></table></div></details>)}
   </details>)}</details>
   <p className="mi-muted">{study.warning}</p>
  </>}
 </section>
}
