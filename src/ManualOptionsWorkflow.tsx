import {useEffect,useRef,useState} from 'react'
import {Bell,RefreshCw,AlertTriangle} from 'lucide-react'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
import type {OptionContract} from './OptionChainLive'
import './manual-options-workflow.css'

export type WorkflowScenario={
  capital:number;max_lots:number;direction:'BOTH'|'UP'|'DOWN';move_points:number
  horizon_minutes:number;iv_change_points:number;rate_pct:number;dividend_pct:number
  max_spread_bps:number;risk_pct:number;target_premium:number;slippage_bps:number
  broker_profile:'zerodha'|'dhan'|'zerodha_debit_balance'
}
type Mode='compare'|'positions'|'alerts'|'review'
type CompareRow=OptionContract&{as_of_utc:string;rank:number;score:number;rank_quality:string;
  units:number;scenario_lots:number;entry_debit_inr:number;spread_bps:number;
  scenarios:Record<string,{net_pnl_inr:number}|null>}
type Compare={rows:CompareRow[];ranked_count:number;coverage:{expiry:string;state:string;age_seconds:number|null;
  received_utc?:string;ranked_count:number}[];truncated:boolean;generated_utc:string;warning:string;settings:WorkflowScenario;
  shortlist_records_saved?:number;shortlist_recording_error?:string}
type Level={target_net_inr:number;sell_bid:number|null;model_underlying_move_points:number|null}
type Greeks={delta:number;gamma:number;theta_day:number;vega_iv_point:number;rho_rate_point:number}
type Position={id:string;symbol:string;direction:string;quantity:number;entry_price:number;
  entry_recorded_utc:string;contract_identity:string|null;expiry:string|null;strike:number|null;
  lot_size:number|null;broker_profile:WorkflowScenario['broker_profile']|null;
  state:string;last_chain_bid:number|null;mark:{received_utc:string;bid:number|null;top_bid:number|null;
    covered_units:number|null;source:string}|null;estimated_net_pnl_inr:number|null;estimated_charges_inr:number|null;
  greeks:Greeks|null;iv_pct:number|null;model_receipt_utc:string|null;exit_levels:Record<string,Level>|null}
type Positions={positions:Position[];total_open:number;marked_count:number;marked_net_pnl_inr:number|null;
  all_positions_marked:boolean;coverage_limited:boolean;aggregate_greeks:Greeks|null;fresh_greeks_count:number;
  generated_utc:string;warning:string}
type Rule={id:string;identity:string;expiry:string;strike:number;side:string;conditions:Record<string,number>;
  enabled:boolean;state:string;last_receipt_utc:string|null}
type AlertEvent={id:number;rule_id:string;observed_utc:string;created_utc:string;identity:string;expiry:string;
  strike:number;side:string;values:Record<string,number|null>}
type Sample={id:string;identity:string;expiry:string;strike:number;side:string;units:number;score:number;
  evidence:string;decision_utc:string;quote_utc:string;horizon_minutes:number;decision_ask:number;
  entry_utc:string|null;entry_ask:number|null;exit_due_utc:string|null;exit_utc:string|null;exit_bid:number|null;
  state:string;net_pnl_inr:number|null;reason:string|null;cohort?:string;pair_key?:string;rank_at_decision?:number}
type Overview={tracking_enabled:boolean;rules:Rule[];events:AlertEvent[];samples:Sample[];
  sample_counts:Record<string,number>;observed_count:number;positive_count:number;negative_count:number;
  mean_markout_inr:number|null;sum_markout_inr:number|null;worker:{alive:boolean;state:string;last_cycle_utc:string|null;last_error:string|null};
  warning:string;paired_count?:number;paired_mean_return_difference_pp?:number|null;control_observed_count?:number}
type Vix={value:number|null;identity:string|null;received_utc:string|null;state:string;reason:string|null;source:string}
const api='/api/trading-cockpit/options/'
const money=(n:number|null|undefined)=>n==null||!Number.isFinite(n)?'—':'₹'+n.toLocaleString('en-IN',{maximumFractionDigits:2})
const fmt=(n:number|null|undefined,d=2)=>n==null||!Number.isFinite(n)?'—':n.toLocaleString('en-IN',{maximumFractionDigits:d})
const stamp=(s?:string|null)=>s?new Date(s).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',second:'2-digit'})+' IST':'—'
const age=(s:string|null|undefined,now:number)=>s?Math.max(0,(now-Date.parse(s))/1000):Infinity
const signed=(v?:number|null)=>v==null?'':v>=0?'ao-positive':'ao-negative'
const human=(s:string)=>s.replaceAll('_',' ')
const metricFields:[string,string][]=[
 ['max_ask','Maximum ask ₹'],['max_spread_bps','Maximum spread bps'],
 ['min_abs_delta','Minimum |delta|'],['max_abs_delta','Maximum |delta|'],
 ['min_iv_pct','Minimum model IV %'],['max_iv_pct','Maximum model IV %'],
 ['min_bid','Minimum bid ₹'],['max_bid','Maximum bid ₹'],['min_top_units','Minimum top units (both sides)']
]
function Box({label,value,detail}:{label:string;value:string;detail?:string}){
  return <div className="ao-metric"><span>{label}</span><strong>{value}</strong>{detail&&<small>{detail}</small>}</div>
}
function Warn({children}:{children:React.ReactNode}){return <div className="ao-warning"><AlertTriangle size={15}/><span>{children}</span></div>}
function GreeksStrip({g}:{g:Greeks}){return <div className="ao-grid ao-summary">
  <Box label="Position Δ" value={fmt(g.delta,3)}/><Box label="Position Γ" value={fmt(g.gamma,6)}/>
  <Box label="Theta / day" value={money(g.theta_day)}/><Box label="Vega / IV pp" value={money(g.vega_iv_point)}/>
  <Box label="Rho / rate pp" value={money(g.rho_rate_point)}/>
</div>}

export function IndiaVixMetric(){
  const [v,setV]=useState<Vix|null>(null)
  const [error,setError]=useState('')
  useEffect(()=>{
    let alive=true,running=false
    const load=async()=>{if(running||!alive)return;running=true
      try{const result=await marketApi<Vix>(api+'india-vix');if(alive){setV(result);setError('')}}
      catch(e){if(alive)setError(readableError(e))}
      finally{running=false}}
    void load();const timer=window.setInterval(()=>{if(!document.hidden)void load()},60000)
    return()=>{alive=false;window.clearInterval(timer)}
  },[])
  return <Box label="India VIX · Dhan index" value={v?.value!=null?fmt(v.value):'Unavailable'}
    detail={v?.value!=null?(stamp(v.received_utc)+' · local REST receipt, not exchange clock'+(error?' · refresh failed':'')):
      error||v?.reason||'Checking exact official index identity…'}/>
}

function PositionCard({p,now,onChange}:{p:Position;now:number;onChange:()=>void}){
  const [link,setLink]=useState('')
  const [broker,setBroker]=useState<WorkflowScenario['broker_profile']>('zerodha')
  const [exit,setExit]=useState('')
  const [charges,setCharges]=useState('')
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const marked=p.mark&&p.mark.bid!==null&&p.estimated_net_pnl_inr!==null&&age(p.mark.received_utc,now)<=(p.mark.source==='original_20_level_bid_walk'?8:30)
  const greekFresh=age(p.model_receipt_utc,now)<=30
  const submit=async(url:string,body:unknown)=>{
    setBusy(true);setError('')
    try{await marketPost(url,body);onChange()}catch(e){setError(readableError(e))}finally{setBusy(false)}
  }
  return <article className="mw-position ao-panel">
    <header className="ao-header"><div><span className="ao-eyebrow">{p.contract_identity||'Manual record · identity not linked'}</span>
      <h4>{p.symbol} · {p.direction} · {p.quantity} units</h4><p>Entered {stamp(p.entry_recorded_utc)} · {p.expiry||'Unlinked expiry'} · user-entered fill</p></div>
      <span className={marked?'mw-badge':'mw-badge mw-delayed'}>{marked?human(p.state):'No current full-size mark'}</span></header>
    {error&&<Warn>{error}</Warn>}
    {!p.contract_identity&&<form className="mw-form" onSubmit={e=>{e.preventDefault();void submit('/api/trading-cockpit/trades/'+p.id+'/link',{contract_identity:link,broker_profile:broker})}}>
      <label>Exact Dhan identity<input required pattern="NSE_FNO:[0-9]{1,12}" value={link} onChange={e=>setLink(e.target.value.toUpperCase())} placeholder="NSE_FNO:12345"/></label>
      <label>Fee profile<select value={broker} onChange={e=>setBroker(e.target.value as typeof broker)}><option value="zerodha">Zerodha regular</option><option value="dhan">Dhan regular</option><option value="zerodha_debit_balance">Zerodha debit-balance</option></select></label>
      <button type="submit" disabled={busy}>Verify and link existing fill</button>
    </form>}
    <div className="ao-grid ao-summary">
      <Box label="Actual entered premium" value={money(p.entry_price)} detail="Not broker verified"/>
      <Box label="Entry premium notional" value={money(p.entry_price*p.quantity)}/>
      <Box label="Current full-size bid mark" value={marked?money(p.mark?.bid):'Unavailable'} detail={p.mark?human(p.mark.source)+' · '+stamp(p.mark.received_utc):'No recent source quote'}/>
      <Box label="Estimated net mark P&L" value={marked?money(p.estimated_net_pnl_inr):'Unavailable'} detail="Includes estimated round-trip charges"/>
      <Box label="Estimated charges" value={marked?money(p.estimated_charges_inr):'Unavailable'}/>
      <Box label="Last saved chain bid" value={money(p.last_chain_bid)} detail={stamp(p.model_receipt_utc)}/>
    </div>
    {p.greeks&&<><p className="ao-muted">Model Greeks · {greekFresh?'recent chain receipt':'historical / delayed model receipt'} · {stamp(p.model_receipt_utc)} · IV {fmt(p.iv_pct)}%</p><GreeksStrip g={p.greeks}/></>}
    {p.exit_levels&&<div className="ao-table-wrap"><table className="ao-table"><thead><tr><th>Exit condition</th><th>Net P&L threshold</th><th>Required sell premium</th><th>Modeled spot move</th></tr></thead><tbody>
      {Object.entries(p.exit_levels).map(([k,v])=><tr key={k}><td>{human(k)}</td><td className={signed(v.target_net_inr)}>{money(v.target_net_inr)}</td>
        <td>{money(v.sell_bid)}</td><td>{greekFresh&&v.model_underlying_move_points!=null?fmt(v.model_underlying_move_points)+' pts':'Unavailable'}</td></tr>)}
    </tbody></table></div>}
    <details className="ao-assumptions"><summary>Record actual exit (journal only)</summary>
      <form className="mw-form" onSubmit={e=>{e.preventDefault();void submit('/api/trading-cockpit/trades/'+p.id+'/exit',{exit_price:Number(exit),fees_inr:Number(charges)})}}>
        <label>Actual sell fill premium ₹<input required type="number" min="0" max="1000000" step=".01" value={exit} onChange={e=>setExit(e.target.value)}/></label>
        <label>Actual combined charges ₹<input required type="number" min="0" max="100000" step=".01" value={charges} onChange={e=>setCharges(e.target.value)}/></label>
        <button type="submit" disabled={busy}>Close manual journal record</button>
      </form><p>Enter your actual completed broker fill and combined charges. This cannot execute, modify or close a broker order.</p>
    </details>
  </article>
}

export default function ManualOptionsWorkflow({visible,onOpen,scenario,selected,onChooseContract}:{
  visible:boolean;onOpen:()=>void;scenario:WorkflowScenario;selected:OptionContract|null;
  onChooseContract:(expiry:string,identity:string)=>void
}){
  const [mode,setMode]=useState<Mode>('compare')
  const [status,setStatus]=useState<Overview|null>(null)
  const [statusError,setStatusError]=useState('')
  const [compare,setCompare]=useState<Compare|null>(null)
  const [positions,setPositions]=useState<Positions|null>(null)
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  const [revision,setRevision]=useState(0)
  const [now,setNow]=useState(Date.now())
  const [target,setTarget]=useState('5')
  const [stop,setStop]=useState('2.5')
  const [exitSettings,setExitSettings]=useState({target_pct:5,stop_pct:2.5})
  const [alertIdentity,setAlertIdentity]=useState('')
  const [thresholds,setThresholds]=useState<Record<string,string>>({})
  const [compareSide,setCompareSide]=useState<'ALL'|'CE'|'PE'>('ALL')
  const [notice,setNotice]=useState('')
  const [notify,setNotify]=useState(()=>{try{return localStorage.getItem('quantlab:manual-options-notifications')==='1'}catch{return false}})
  const lastEvent=useRef<number|null>(null)
  const scenarioKey=JSON.stringify(scenario)
  useEffect(()=>{const t=window.setInterval(()=>setNow(Date.now()),1000);return()=>window.clearInterval(t)},[])
  useEffect(()=>{if(selected?.identity)setAlertIdentity(selected.identity)},[selected?.identity])
  useEffect(()=>{
    let alive=true,running=false
    const load=async()=>{if(running||!alive)return;running=true
      try{
        const v=await marketApi<Overview>(api+'workflow')
        if(!alive)return
        const previous=lastEvent.current
        const newest=v.events[0]?.id||0
        if(previous!==null&&newest>previous&&notify&&typeof Notification!=='undefined'&&Notification.permission==='granted'){
          for(const ev of v.events.filter(x=>x.id>previous).slice(0,5).reverse()){
            try{new Notification('QuantLab contract alert',{body:ev.strike+' '+ev.side+' · '+ev.expiry+' · observed '+stamp(ev.observed_utc)})}catch{/* optional browser permission */}
          }
        }
        lastEvent.current=Math.max(previous||0,newest);setStatus(v);setStatusError('')
      }catch(e){if(alive)setStatusError(readableError(e))}
      finally{running=false}}
    void load();const t=window.setInterval(()=>void load(),10000)
    return()=>{alive=false;window.clearInterval(t)}
  },[revision,notify])
  useEffect(()=>{
    if(!visible||!['compare','positions'].includes(mode))return
    let alive=true,running=false
    const load=async()=>{if(running||!alive)return;running=true;setBusy(true);setError('')
      try{
        if(mode==='compare'){
          const v=await marketPost<Compare>(api+'compare',scenario)
          if(alive)setCompare(v)
        }else{
          const q=new URLSearchParams(Object.entries({...exitSettings,horizon_minutes:scenario.horizon_minutes,
            iv_change_points:scenario.iv_change_points,rate_pct:scenario.rate_pct,
            dividend_pct:scenario.dividend_pct,slippage_bps:scenario.slippage_bps}).map(([k,v])=>[k,String(v)]))
          const v=await marketApi<Positions>(api+'positions?'+q)
          if(alive)setPositions(v)
        }
      }catch(e){if(alive)setError(readableError(e))}
      finally{running=false;if(alive)setBusy(false)}}
    void load();const t=window.setInterval(()=>{if(!document.hidden)void load()},mode==='compare'?30000:10000)
    return()=>{alive=false;window.clearInterval(t)}
  },[visible,mode,scenarioKey,exitSettings,revision])
  const action=async(path:string,body:unknown,message:string)=>{
    setBusy(true);setError('')
    try{await marketPost(path,body);setNotice(message);setRevision(r=>r+1)}
    catch(e){setError(readableError(e))}
    finally{setBusy(false)}
  }
  const enableNotifications=async()=>{
    if(typeof Notification==='undefined'){setNotice('This browser does not support notifications. In-app event history still works.');return}
    try{const permission=await Notification.requestPermission()
      setNotify(permission==='granted');try{localStorage.setItem('quantlab:manual-options-notifications',permission==='granted'?'1':'0')}catch{/* private storage */}
      setNotice(permission==='granted'?'Browser alerts enabled while Advanced Analytics is open.':'Permission not granted; use the in-app alert ledger.')
    }catch(e){setError(readableError(e))}
  }
  const recentEvent=status?.events.find(e=>age(e.created_utc,now)<=120)
  const compareRows=(compare?.rows||[]).filter(r=>(compareSide==='ALL'||r.option_type===compareSide)&&age(r.as_of_utc,now)<=30)
  const resultsCurrent=compare&&age(compare.generated_utc,now)<=35&&!error&&Object.entries(scenario).every(([k,v])=>compare.settings?.[k as keyof WorkflowScenario]===v)
  return <>
    <div className="mw-monitor-banner" role="status"><Bell size={15}/><span>
      {status?'Local monitor '+human(status.worker.state)+' · '+status.rules.filter(r=>r.enabled).length+' enabled alerts · shortlist tracking '+(status.tracking_enabled?'on':'off'):'Manual monitor status unavailable'}
      {recentEvent?' · Recent alert: '+recentEvent.strike+' '+recentEvent.side+' at '+stamp(recentEvent.observed_utc):''}
      {statusError?' · '+statusError:''}
    </span>{!visible&&<button type="button" onClick={onOpen}>Open monitor</button>}</div>
    {visible&&<section className="ao-panel mw-root" aria-label="Manual options workflow">
      <header className="ao-header"><div><span className="ao-eyebrow">CONTRACT DISCOVERY TO OBSERVED OUTCOMES</span>
        <h3>Manual trading workflow</h3><p>Uses saved original Dhan receipts and the existing manual trade journal. No orders.</p></div>
        <button type="button" disabled={busy} onClick={()=>setRevision(r=>r+1)}><RefreshCw size={14}/>Refresh</button></header>
      <nav className="ao-tabs" role="tablist" aria-label="Manual trading workflow views">
        {([['compare','Across Expiries'],['positions','Positions & Exits'],['alerts','Contract Alerts'],['review','Ranking Review']] as [Mode,string][]).map(([k,v])=>
          <button key={k} type="button" role="tab" aria-selected={mode===k} onClick={()=>{setMode(k);setError('');setNotice('')}}>{v}</button>)}
      </nav>
      {error&&<Warn>{error}</Warn>}{notice&&<p className="ao-muted" role="status">{notice}</p>}
      {mode==='compare'&&<>
        <h4>Compare recorded expiries under the same assumptions</h4><p>₹{fmt(scenario.capital)} capital · up to {scenario.max_lots} lots · {scenario.direction} · {scenario.move_points} points · {scenario.horizon_minutes} minutes. Every expiry has its own receipt time. Missing and delayed expiries are excluded; no extra Dhan subscription.</p>
        {!compare?<p className="ao-muted">Reading saved original option chains…</p>:<>
          <div className="ao-grid ao-summary"><Box label="Currently displayable ranked contracts" value={resultsCurrent?String(compareRows.length):'0'} detail={'Last scan ranked '+compare.ranked_count+' across expiries'}/><Box label="Saved expiry coverage" value={String(compare.coverage.length)} detail={compare.truncated?'Nearest 12 only':'Latest saved per expiry'}/><Box label="Last comparison" value={stamp(compare.generated_utc)}/></div>
          <div className="ao-table-wrap"><table className="ao-table"><thead><tr><th>Expiry</th><th>Receipt state</th><th>Receipt age (s)</th><th>Ranked at scan</th></tr></thead><tbody>
            {compare.coverage.map(c=><tr key={c.expiry}><td>{c.expiry}</td><td>{c.received_utc&&age(c.received_utc,now)>30?'delayed':human(c.state)}</td><td>{c.received_utc?fmt(age(c.received_utc,now),1):'—'}</td><td>{c.ranked_count}</td></tr>)}
            {!compare.coverage.length&&<tr><td colSpan={4}>No verified saved expiry receipts. Arm the existing automatic chain recorder.</td></tr>}</tbody></table></div>
          <label>Contract side<select value={compareSide} onChange={e=>setCompareSide(e.target.value as typeof compareSide)}><option value="ALL">Both directions</option><option value="CE">CE</option><option value="PE">PE</option></select></label>
          {(!resultsCurrent||!compareRows.length)&&<Warn>No current cross-expiry shortlist. Wait for fresh saved chain receipts or adjust the applied scenario.</Warn>}
          <div className="ao-table-wrap"><table className="ao-table"><thead><tr><th>Rank at scan</th><th>Expiry</th><th>Strike</th><th>Side</th><th>Ask</th><th>Lots</th><th>Capital</th><th>Favorable net</th><th>Adverse net</th><th>Score</th><th>Evidence at scan</th><th>Receipt age</th><th>Inspect</th></tr></thead><tbody>
            {(resultsCurrent?compareRows:[]).map(r=><tr key={r.expiry+':'+r.identity}><td>{r.rank}</td><td>{r.expiry}</td><td>{fmt(r.strike,0)}</td><td>{r.option_type}</td>
              <td>{money(r.ask)}</td><td>{r.scenario_lots}</td><td>{money(r.entry_debit_inr)}</td><td className={signed(r.scenarios.favorable?.net_pnl_inr)}>{money(r.scenarios.favorable?.net_pnl_inr)}</td><td className={signed(r.scenarios.adverse?.net_pnl_inr)}>{money(r.scenarios.adverse?.net_pnl_inr)}</td><td>{fmt(r.score)}</td><td>{human(r.rank_quality)}</td><td>{fmt(age(r.as_of_utc,now),1)}s</td><td><button disabled={!r.identity} onClick={()=>r.identity&&onChooseContract(r.expiry,r.identity)}>Inspect</button></td></tr>)}
          </tbody></table></div>
          {compare.shortlist_recording_error&&<Warn>Shortlist audit write failed: {compare.shortlist_recording_error}</Warn>}
          <p className="ao-muted">{compare.warning} Showing up to 100 returned rankings. Conditional scenarios are not forecasts.</p>
        </>}
      </>}
      {mode==='positions'&&<>
        <h4>Open manual positions and exit levels</h4>
        <form className="mw-form" onSubmit={e=>{e.preventDefault();setExitSettings({target_pct:Number(target),stop_pct:Number(stop)})}}>
          <label>Illustrative net profit target % of premium notional<input required type="number" min=".01" max="1000" step=".01" value={target} onChange={e=>setTarget(e.target.value)}/></label>
          <label>Illustrative net loss threshold %<input required type="number" min=".01" max="100" step=".01" value={stop} onChange={e=>setStop(e.target.value)}/></label>
          <button type="submit">Apply exit analysis</button>
        </form><p className="ao-muted">The initial 5% / 2.5% thresholds are adjustable examples, not recommended stops or targets. Underlying moves use applied {scenario.horizon_minutes}m horizon and {scenario.iv_change_points}pp IV shock. All levels are informational.</p>
        {positions?<><div className="ao-grid ao-summary"><Box label="Open journal positions" value={String(positions.total_open)} detail={positions.coverage_limited?'Showing up to 100':'No broker connection for orders'}/>
          <Box label="Observed mark coverage at scan" value={positions.marked_count+'/'+positions.total_open}/>
          <Box label="Estimated net marks at scan" value={age(positions.generated_utc,now)<=12&&!error?money(positions.marked_net_pnl_inr):'Delayed'} detail={positions.all_positions_marked?'All displayed positions covered':'Partial coverage; excludes missing marks'}/>
          <Box label="Fresh Greek coverage at scan" value={positions.fresh_greeks_count+'/'+positions.total_open}/><Box label="Last scan" value={stamp(positions.generated_utc)}/></div>
          {positions.aggregate_greeks&&age(positions.generated_utc,now)<=12&&<><p className="ao-muted">Aggregate fresh-at-scan model sensitivities, covered positions only.</p><GreeksStrip g={positions.aggregate_greeks}/></>}
          {positions.positions.map(p=><PositionCard p={p} now={now} key={p.id} onChange={()=>setRevision(r=>r+1)}/>)}
          {!positions.positions.length&&<p className="ao-muted">No open user-entered trades. Select a contract in the calculator and prepare a manual journal entry after your actual fill.</p>}
          <p className="ao-muted">{positions.warning}</p></>:<p className="ao-muted">Reading the existing manual trade journal…</p>}
      </>}
      {mode==='alerts'&&<>
        <h4>Persistent contract alerts</h4><p>All entered thresholds must match one fresh saved chain receipt. Blank thresholds are ignored. New events are recorded only when a rule changes from nonmatching to matching. The local API monitors while QuantLab runs; browser notifications require permission and this Advanced Analytics page open. Not a stop-loss order.</p>
        <form className="mw-form" onSubmit={e=>{e.preventDefault();const conditions=Object.fromEntries(Object.entries(thresholds).filter(([,v])=>v.trim()!=='').map(([k,v])=>[k,Number(v)]))
          void action(api+'workflow/alerts',{identity:alertIdentity,conditions},'Alert saved. Waiting for a new verified receipt.')}}>
          <label>Verified contract identity<input required pattern="NSE_FNO:[0-9]{1,12}" value={alertIdentity} onChange={e=>setAlertIdentity(e.target.value.toUpperCase())} placeholder="NSE_FNO:12345"/></label>
          {metricFields.map(([k,label])=><label key={k}>{label}<input type="number" min="0" step="any" value={thresholds[k]||''} onChange={e=>setThresholds(old=>({...old,[k]:e.target.value}))} placeholder="Optional"/></label>)}
          <button type="submit" disabled={busy||!Object.values(thresholds).some(v=>v.trim())}>Create alert</button>
        </form>
        <button type="button" onClick={()=>void enableNotifications()}><Bell size={14}/>{notify?'Browser alerts enabled':'Enable browser alerts'}</button>
        {status&&<><div className="ao-table-wrap"><table className="ao-table"><thead><tr><th>Contract</th><th>Conditions</th><th>State</th><th>Last receipt</th><th>Action</th></tr></thead><tbody>
          {status.rules.map(r=><tr key={r.id}><td>{r.strike} {r.side} · {r.expiry}<br/>{r.identity}</td><td>{Object.entries(r.conditions).map(([k,v])=>human(k)+' '+v).join(' · ')}</td><td>{human(r.state)}</td><td>{stamp(r.last_receipt_utc)}</td><td><button disabled={!r.enabled||busy} onClick={()=>void action(api+'workflow/alerts/'+r.id+'/disable',{},'Alert disabled; event history preserved.')}>Disable</button></td></tr>)}
          {!status.rules.length&&<tr><td colSpan={5}>No alert rules configured.</td></tr>}</tbody></table></div>
          <h4>Recorded alert events</h4><div className="ao-table-wrap"><table className="ao-table"><thead><tr><th>Observed time</th><th>Contract</th><th>Observed metrics</th></tr></thead><tbody>
            {status.events.map(e=><tr key={e.id}><td>{stamp(e.observed_utc)}</td><td>{e.strike} {e.side} · {e.expiry}</td><td>{Object.entries(e.values).map(([k,v])=>human(k)+' '+fmt(v,4)).join(' · ')}</td></tr>)}
            {!status.events.length&&<tr><td colSpan={3}>No matching alerts observed yet.</td></tr>}</tbody></table></div></>}
      </>}
      {mode==='review'&&<>
        <h4>Prospective ranking review</h4>
        <p>When enabled, upcoming analytics scans record leading candidates before later observations arrive. The local monitor uses the first saved full-size ask after the decision, then the first saved full-size bid at or after the registered holding horizon. Each window is limited to 60 seconds. Missing evidence is censored; no order or assumed fill is recorded.</p>
        <button type="button" disabled={busy||!status} onClick={()=>void action(api+'workflow/tracking',{enabled:!status?.tracking_enabled},status?.tracking_enabled?'New shortlist recording disabled. Existing evaluations continue.':'New shortlist recording enabled for future analytics scans.')}>{status?.tracking_enabled?'Disable automatic shortlist recording':'Enable automatic shortlist recording'}</button>
        {status&&<>
          <div className="ao-grid ao-summary"><Box label="Observed top-candidate markouts" value={String(status.observed_count)}/><Box label="Positive observed net" value={String(status.positive_count)}/><Box label="Negative observed net" value={String(status.negative_count)}/>
            <Box label="Mean observed net" value={money(status.mean_markout_inr)} detail="Not expected return"/>
            <Box label="Matched comparison pairs" value={String(status.paired_count??0)} detail="Same scenario, preselected lower-ranked comparison"/>
            <Box label="Mean paired return difference" value={status.paired_mean_return_difference_pp==null?'Unavailable':fmt(status.paired_mean_return_difference_pp)+' pp'} detail="Descriptive, no significance claim"/></div>
          <div className="mw-state-counts">{Object.entries(status.sample_counts).map(([k,v])=><span key={k}>{human(k)}: <b>{v}</b></span>)}</div>
          <div className="ao-table-wrap"><table className="ao-table"><thead><tr><th>Decision time</th><th>Contract</th><th>Cohort / rank</th><th>Units</th><th>Score</th><th>Horizon</th><th>Entry receipt / ask</th><th>Exit receipt / bid</th><th>Net quote markout</th><th>State</th></tr></thead><tbody>
            {status.samples.map(r=><tr key={r.id}><td>{stamp(r.decision_utc)}</td><td>{r.strike} {r.side} · {r.expiry}</td><td>{r.cohort||'top'} · {r.rank_at_decision??'—'}</td><td>{r.units}</td><td>{fmt(r.score)}</td><td>{r.horizon_minutes}m</td><td>{stamp(r.entry_utc)}<br/>{money(r.entry_ask)}</td><td>{stamp(r.exit_utc)}<br/>{money(r.exit_bid)}</td><td className={signed(r.net_pnl_inr)}>{money(r.net_pnl_inr)}</td><td title={r.reason||''}>{human(r.state)}</td></tr>)}
            {!status.samples.length&&<tr><td colSpan={10}>No prospective shortlist decisions recorded yet.</td></tr>}</tbody></table></div>
          <p className="ao-muted">{status.warning} Most recent 100 records shown. Open Advanced Analytics or Across Expiries for new decisions; existing pending observations continue while the backend runs.</p>
        </>}
      </>}
      {status?.worker.last_error&&<Warn>Local monitor degraded: {status.worker.last_error}. Existing records are preserved.</Warn>}
    </section>}
  </>
}
