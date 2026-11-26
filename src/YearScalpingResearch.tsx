import {useEffect,useState} from 'react'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
import './market-intelligence-dashboard.css'

type Summary={sessions:number;censored_sessions:number;trades:number;net_inr:number|null;mean_net_per_day:number|null;mean_net_per_trade:number|null;win_pct:number|null;profit_factor:number|null;fees_inr:number|null;max_daily_drawdown_pct:number|null;stress_extra_25_inr:number|null;no_near_target:number}
type Candidate={id:string;rule:string;lots:number;hold_minutes:number;target_points:number|null;stop_points:number|null}
type Comparison=Candidate&{development:Summary;validation:Summary;development_eligible_days:number;development_censored_days:number;validation_censored_days:number}
type Study={study_id:string;start_date:string;end_date:string;state:string;requested_weekdays:number;coverage_states:Record<string,number>;verified_option_receipts:number;rejected_receipt_reads:number;excluded_conflicts:number;candidate_count:number;development_matched_days:number;validation_matched_days:number;comparison:Comparison[];selected:Candidate|null;test:Summary;coverage:{date:string;cohort:string;state:string;index_minutes:number;ce_minutes:number;pe_minutes:number}[];selected_test_days:{date:string;complete:boolean;net:number|null;trades:number;unscored:Record<string,number>}[];settings:Record<string,string|number|boolean>;warning:string}
type Job={status:string;stage?:string;percent?:number;error?:string;result?:Study}
const endpoint='/api/trading-cockpit/options/year-scalping'
const key='quantlab:year-scalping-job'
const before=(days:number)=>new Date(Date.now()-days*86400000).toLocaleDateString('sv-SE',{timeZone:'Asia/Kolkata'})
const fmt=(v:number|null|undefined)=>v==null?'—':v.toLocaleString('en-IN',{maximumFractionDigits:2})
const human=(v:string)=>v.replaceAll('_',' ')
const desc=(r:Candidate)=>human(r.rule)+' · '+r.lots+' lots · '+r.hold_minutes+'m cap · '+(r.target_points==null?'fixed hold':('+'+r.target_points+' / −'+r.stop_points+' points'))
function remembered(){try{return sessionStorage.getItem(key)||''}catch{return ''}}
function keep(v:string){try{if(v)sessionStorage.setItem(key,v);else sessionStorage.removeItem(key)}catch{/* local report remains saved */}}
export default function YearScalpingResearch(){
 const [start,setStart]=useState(()=>before(365)),[end,setEnd]=useState(()=>before(1))
 const [capital,setCapital]=useState('17000'),[lots,setLots]=useState('3'),[lotSize,setLotSize]=useState('30'),[premium,setPremium]=useState('180'),[wings,setWings]=useState('3'),[slip,setSlip]=useState('5'),[tolerance,setTolerance]=useState('60'),[compare,setCompare]=useState(false)
 const [job,setJob]=useState(remembered),[stage,setStage]=useState(''),[error,setError]=useState(''),[starting,setStarting]=useState(false)
 const [study,setStudy]=useState<Study|null>(null)
 useEffect(()=>{let active=true;marketApi<{study:Study|null}>(endpoint+'/latest').then(r=>{if(active)setStudy(r.study)}).catch(e=>{if(active)setError(readableError(e))});return()=>{active=false}},[])
 useEffect(()=>{if(!job)return;let active=true,busy=false
  const poll=async()=>{if(busy)return;busy=true
   try{const r=await marketApi<Job>('/api/jobs/'+encodeURIComponent(job));if(!active)return;setStage((r.stage||r.status)+' · '+(r.percent??0)+'%')
    if(r.status==='complete'){if(r.result)setStudy(r.result);keep('');setJob('')}
    else if(['error','cancelled','interrupted'].includes(r.status)){setError(r.error||r.status);keep('');setJob('')}
   }catch(e){if(active)setError(readableError(e))}finally{busy=false}}
  void poll();const timer=window.setInterval(()=>void poll(),2500);return()=>{active=false;window.clearInterval(timer)}
 },[job])
 async function run(){
  setStarting(true);setError('')
  try{const r=await marketPost<{job_id:string}>(endpoint,{start_date:start,end_date:end,capital:Number(capital),max_lots:Number(lots),compare_lots:compare,lot_size:Number(lotSize),target_premium:Number(premium),tolerance:Number(tolerance),wings:Number(wings),slippage_bps:Number(slip)});keep(r.job_id);setJob(r.job_id);setStage('Queued')}
  catch(e){setError(readableError(e))}finally{setStarting(false)}
 }
 return <section className="mi-card mi-risk" aria-label="Full-year scalping research lab">
  <header className="mi-heading"><div><span className="mi-kicker">SAVED DATA · CHRONOLOGICAL GRID</span><h3>Full-year Scalping Research Lab</h3><p className="mi-muted">Test 3 fixed strategies, 1–30 minute holding periods and small premium point targets/stops using verified saved index and near-monthly CE/PE candles. Current Zerodha charges. No download, broker order or recorder restart.</p></div><a href="#/data">Check or acquire missing data →</a></header>
  <form className="mi-risk-actions" onSubmit={e=>{e.preventDefault();void run()}}>
   <label>From (IST)<input type="date" aria-label="Year scalping start" required min={before(365)} max={end} value={start} onChange={e=>setStart(e.target.value)}/></label>
   <label>Through (IST)<input type="date" aria-label="Year scalping end" required min={start} max={before(1)} value={end} onChange={e=>setEnd(e.target.value)}/></label>
   <label>Daily capital ₹<input type="number" required min="1000" max="10000000" value={capital} onChange={e=>setCapital(e.target.value)} style={{width:100}}/></label>
   <label>Lots<select value={lots} onChange={e=>setLots(e.target.value)}>{[1,2,3].map(n=><option key={n}>{n}</option>)}</select></label>
   <label>Assumed units / lot<input type="number" required min="1" max="100" value={lotSize} onChange={e=>setLotSize(e.target.value)} style={{width:70}}/></label>
   <label>Target premium ₹<input type="number" required min="10" max="20000" value={premium} onChange={e=>setPremium(e.target.value)} style={{width:75}}/></label>
   <label><input type="checkbox" checked={compare} onChange={e=>setCompare(e.target.checked)}/> Compare 1 to {lots} lots</label>
   <details className="mpi-detail"><summary>Research assumptions</summary><div className="mi-risk-actions"><label>Premium tolerance ₹<input type="number" min="0" max="5000" required value={tolerance} onChange={e=>setTolerance(e.target.value)}/></label><label>ATM wings<select value={wings} onChange={e=>setWings(e.target.value)}>{[0,1,2,3,4,5].map(n=><option key={n}>{n}</option>)}</select></label><label>Adverse slippage bps/side<input type="number" required min="0" max="500" step="any" value={slip} onChange={e=>setSlip(e.target.value)}/></label></div></details>
   <button className="ws-button primary" type="submit" disabled={starting||!!job}>{starting||job?'Research running…':'Run all minute scalping experiments'}</button>
  </form>
  <p className="mi-muted">Development 60%, validation 20%, final test 20% by requested weekdays. Fixed holds 1, 2, 3, 5, 10, 15, 30m; 3/5/10m cap with targets/stops +1/−1, +2/−2, +3/−2, +5/−3, +10/−5. One candidate chosen using development only; no 15s/30s simulated from minute data.</p>
  {job&&<p role="status">{stage||'Queued'} · <a href="#/workspacejobs">Open job history</a></p>}
  {error&&<p role="alert" className="tc-error">{error}</p>}
  {study&&<><h4>Saved study · {study.start_date} to {study.end_date}</h4><p className="mi-muted">{human(study.state)} · {study.candidate_count} configurations · {study.verified_option_receipts} verified receipts · {study.rejected_receipt_reads} rejected reads · {study.excluded_conflicts} conflicting rows excluded. {study.requested_weekdays} requested weekdays, not verified exchange sessions.</p>
   <div className="mi-risk-grid">{Object.entries(study.coverage_states).map(([k,v])=><div className="mi-risk-stat" key={k}><span>{human(k)}</span><strong>{v}</strong></div>)}</div>
   <h4>Held-out result · development-selected configuration</h4>{study.selected?<><p>{desc(study.selected)}</p><div className="mi-risk-grid">{Object.entries({'Test days':study.test.sessions,'Censored test days':study.test.censored_sessions,'Trades':study.test.trades,'Net ₹':study.test.net_inr,'Mean net / trade ₹':study.test.mean_net_per_trade,'Win %':study.test.win_pct,'Fees ₹':study.test.fees_inr,'Extra ₹25/trade stress':study.test.stress_extra_25_inr,'Max daily drawdown %':study.test.max_daily_drawdown_pct}).map(([k,v])=><div className="mi-risk-stat" key={k}><span>{k}</span><strong>{fmt(v)}</strong></div>)}</div></>:<p className="mi-muted">Not enough matched development evidence to select a strategy (at least 15 common sessions and 30 trades). Fill gaps or broaden the historical scope. No final test ranking fabricated.</p>}
   <details className="mpi-detail" open><summary>Development and validation comparison · {study.development_matched_days} / {study.validation_matched_days} common scored days</summary><div className="tc-table-scroll"><table><thead><tr><th>Configuration</th><th>Dev trades</th><th>Dev net ₹</th><th>Dev avg/trade ₹</th><th>Dev censored</th><th>Validation trades</th><th>Validation net ₹</th><th>Validation avg/trade ₹</th><th>Validation fees ₹</th></tr></thead><tbody>{study.comparison.map(r=><tr key={r.id}><td>{desc(r)}</td><td>{r.development.trades}</td><td>{fmt(r.development.net_inr)}</td><td>{fmt(r.development.mean_net_per_trade)}</td><td>{r.development_censored_days}</td><td>{r.validation.trades}</td><td>{fmt(r.validation.net_inr)}</td><td>{fmt(r.validation.mean_net_per_trade)}</td><td>{fmt(r.validation.fees_inr)}</td></tr>)}</tbody></table></div></details>
   <details className="mpi-detail"><summary>Every requested weekday · data evidence</summary><div className="tc-table-scroll"><table><thead><tr><th>Date</th><th>Split</th><th>State</th><th>Index bars</th><th>CE minutes</th><th>PE minutes</th></tr></thead><tbody>{study.coverage.map(r=><tr key={r.date}><td>{r.date}</td><td>{r.cohort}</td><td>{human(r.state)}</td><td>{r.index_minutes}</td><td>{r.ce_minutes}</td><td>{r.pe_minutes}</td></tr>)}</tbody></table></div></details>
   <details className="mpi-detail"><summary>Selected test daily outcomes</summary><div className="tc-table-scroll"><table><thead><tr><th>Date</th><th>Complete</th><th>Trades</th><th>Net ₹</th><th>Skipped / unresolved</th></tr></thead><tbody>{study.selected_test_days.map(r=><tr key={r.date}><td>{r.date}</td><td>{r.complete?'Yes':'Censored'}</td><td>{r.trades}</td><td>{fmt(r.net)}</td><td>{Object.entries(r.unscored).map(([k,v])=>human(k)+': '+v).join(', ')}</td></tr>)}</tbody></table></div></details>
   <p className="mi-muted">{study.warning}</p>
  </>}
 </section>
}
