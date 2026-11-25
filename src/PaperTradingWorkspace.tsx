import ResearchPlot from './ResearchPlots'
import {useEffect,useState} from 'react'
import {AlertTriangle,RefreshCw,Wallet,Activity} from 'lucide-react'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
import './advanced-options.css'
import './paper-trading.css'

const api='/api/trading-cockpit/paper/'
const fmt=(v:number|null|undefined,d=2)=>v==null||!Number.isFinite(v)?'—':v.toLocaleString('en-IN',{maximumFractionDigits:d})
const money=(v:number|null|undefined)=>v==null?'—':'₹'+fmt(v)
const time=(v?:string|null)=>v?new Date(v).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',second:'2-digit'})+' IST':'—'
const human=(s:string)=>s.replaceAll('_',' ')
const sign=(v?:number|null)=>v==null?'':v>=0?'ao-positive':'ao-negative'
const dayIST=()=>new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Kolkata'})
type Account={id:string;label:string;initial_cash:number;cash:number;realized:number;fees_paid:number;risk_pct:number;loss_limit_pct:number;max_positions:number;broker_profile:string}
type Order={id:string;identity:string;symbol:string;action:string;kind:string;quantity:number;filled:number;state:string;created_utc:string;ready_utc:string;deadline_utc:string;cancel_requested_utc:string|null;protection_price:number;turnover:number;fees:number;reserved_cash:number;valid_books:number;invalid_books:number;terminal_reason:string|null}
type Position={identity:string;symbol:string;expiry:string;quantity:number;lot_size:number;cost_basis:number;mark:number|null;mark_utc:string|null;liquidation_credit:number|null;unrealized_net:number|null;state:string}
type Fill={id:number;order_id:string;identity:string;book_received_utc:string;units:number;vwap:number;turnover:number;incremental_fees:number;realized_delta:number}
type Overview={account:Account;orders:Order[];positions:Position[];fills:Fill[];equity:number|null;available_cash:number;reserved_cash:number;marked_count:number;
  equity_samples:{minute_utc:string;marked_equity:number|null;cash:number;realized:number}[];
  worker:{alive:boolean;state:string;last_error:string|null};generated_utc:string;warning:string}
type Leg={identity:string;action:string;option_type:string;strike:number;expiry:string;received_utc:string;requested_units:number;displayed_fill_units:number;vwap:number|null;fees:number;cashflow:number}
type Replay={strategy:string;decision_utc:string;state:string;entries:Leg[];exits:Leg[];missing:{identity:string;stage:string;reason:string}[];net_pnl_inr:number|null;entry_risk_proxy:number|null;total_fees_inr?:number;entry_skew_seconds?:number;exit_skew_seconds?:number;warning:string;signal?:string;cash_after_completed_trade?:number;signal_decision_utc?:string}
type RuleReplay={state:string;day?:string;rule?:string;bars:number;signals:number;trades:Replay[];completed:number;net_pnl_inr:number|null;completed_subset_net_pnl_inr?:number|null;positive?:number;negative?:number;warning?:string}
const strategyOptions:Record<string,string>={
  LONG_OPTION:'Long single option',bull_call_debit:'Bull call debit · buy lower CE, sell higher CE',
  bear_put_debit:'Bear put debit · buy higher PE, sell lower PE',
  bull_put_credit:'Bull put credit · buy lower PE, sell higher PE',
  bear_call_credit:'Bear call credit · buy higher CE, sell lower CE',
  iron_condor:'Iron condor · buy low PE, sell PE, sell CE, buy high CE',
  iron_butterfly:'Iron butterfly · buy low PE, sell center PE/CE, buy high CE'}
function Metric({label,value,detail}:{label:string;value:string;detail?:string}){
  return <div className="ao-metric"><span>{label}</span><strong>{value}</strong>{detail&&<small>{detail}</small>}</div>
}
function Num({label,value,set,min,max,step=1}:{label:string;value:string;set:(v:string)=>void;min:number;max:number;step?:number|string}){
  return <label>{label}<input required aria-label={label} type="number" value={value} min={min} max={max} step={step} onChange={e=>set(e.target.value)}/></label>
}
function Broker({value,set}:{value:string;set:(v:string)=>void}){return <label>Estimated fee profile<select value={value} onChange={e=>set(e.target.value)}>
  <option value="zerodha">Zerodha regular</option><option value="dhan">Dhan regular</option><option value="zerodha_debit_balance">Zerodha debit-balance scenario</option></select></label>}
function Equity({rows}:{rows:Overview['equity_samples']}){
  const good=rows.filter(r=>r.marked_equity!==null)
  if(!good.length)return <p className="ao-muted">No complete equity marks yet. Missing marks remain gaps.</p>
  return <div className="ao-plot"><ResearchPlot plot={{kind:'line2d',title:'Observed paper liquidation equity',x_label:'Mark minute (IST)',y_label:'Simulated liquidation equity (₹)',x:rows.map(r=>r.minute_utc),traces:[{name:'Marked paper equity',y:rows.map(r=>r.marked_equity)}],break_before:rows.map((r,i)=>i>0&&Date.parse(r.minute_utc)-Date.parse(rows[i-1].minute_utc)>120000)}} provenance="paper-mark" formatX={v=>time(String(v))} formatY={money}/><small>{good.length}/{rows.length} complete marks · missing marks remain gaps · not realized returns.</small></div>
}
function ReplayDetail({result}:{result:Replay}){
  return <section className="ao-panel"><h4>{human(result.strategy)} · {human(result.state)}</h4>
    <div className="ao-grid ao-summary"><Metric label="Conditional net P&L" value={money(result.net_pnl_inr)} detail="Unavailable when entry or exit incomplete"/><Metric label="Risk-capital proxy" value={money(result.entry_risk_proxy)} detail="Not broker margin"/><Metric label="Estimated charges" value={money(result.total_fees_inr)}/></div>
    {!!result.missing?.length&&<p className="ao-warning">{result.missing.map(x=>x.stage+' '+x.identity+': '+human(x.reason)).join(' · ')}</p>}
    <div className="ao-table-wrap"><table className="ao-table"><thead><tr><th>Stage</th><th>Contract</th><th>Side</th><th>Receipt</th><th>Displayed units / requested</th><th>VWAP</th><th>Fees</th><th>Cashflow</th></tr></thead><tbody>
      {([['Entry',result.entries],['Exit',result.exits]] as const).flatMap(([stage,legs])=>legs.map(l=><tr key={stage+l.identity}><td>{stage}</td><td>{l.strike} {l.option_type} · {l.identity}</td><td>{l.action}</td><td>{time(l.received_utc)}</td><td>{l.displayed_fill_units}/{l.requested_units}</td><td>{money(l.vwap)}</td><td>{money(l.fees)}</td><td className={sign(l.cashflow)}>{money(l.cashflow)}</td></tr>))}
      {!result.entries.length&&!result.exits.length&&<tr><td colSpan={8}>No complete observable depth evidence.</td></tr>}</tbody></table></div>
    <p className="ao-muted">{result.warning}</p>
  </section>
}
export default function PaperTradingWorkspace({onOpenChain,onOpenDepth}:{onOpenChain:()=>void;onOpenDepth:()=>void}){
  const [mode,setMode]=useState<'account'|'replay'|'rules'>('account')
  const [accounts,setAccounts]=useState<Account[]>([])
  const [aid,setAid]=useState('')
  const [data,setData]=useState<Overview|null>(null)
  const [revision,setRevision]=useState(0)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')
  const [label,setLabel]=useState('Options paper research')
  const [cash,setCash]=useState('17000')
  const [risk,setRisk]=useState('25')
  const [loss,setLoss]=useState('10')
  const [maxPositions,setMaxPositions]=useState('4')
  const [broker,setBroker]=useState('zerodha')
  const [identity,setIdentity]=useState('')
  const [action,setAction]=useState('BUY')
  const [kind,setKind]=useState('PROTECTED_MARKET')
  const [lots,setLots]=useState('1')
  const [price,setPrice]=useState('180')
  const [latency,setLatency]=useState('1000')
  const [ttl,setTtl]=useState('60')
  const [participation,setParticipation]=useState('25')
  const [slippage,setSlippage]=useState('5')
  const [day,setDay]=useState(dayIST)
  const [decision,setDecision]=useState('10:00:00')
  const [hold,setHold]=useState('5')
  const [skew,setSkew]=useState('2')
  const [strategy,setStrategy]=useState('LONG_OPTION')
  const [ids,setIds]=useState('')
  const [rule,setRule]=useState('EMA_CROSSOVER')
  const [ce,setCe]=useState('');const [pe,setPe]=useState('')
  const [fast,setFast]=useState('9');const [slow,setSlow]=useState('21')
  const [lookback,setLookback]=useState('10');const [threshold,setThreshold]=useState('0.1')
  const [holdRule,setHoldRule]=useState('FIXED')
  const [replay,setReplay]=useState<Replay|null>(null);const [rules,setRules]=useState<RuleReplay|null>(null)
  useEffect(()=>{let active=true
    marketApi<{accounts:Account[]}>(api+'accounts').then(v=>{if(active){setAccounts(v.accounts);setAid(old=>v.accounts.some(a=>a.id===old)?old:v.accounts[0]?.id||'')}}).catch(e=>{if(active)setError(readableError(e))})
    return()=>{active=false}},[revision])
  useEffect(()=>{if(!aid||mode!=='account')return
    let active=true,running=false
    const load=async()=>{if(running||!active)return;running=true
      try{const v=await marketApi<Overview>(api+'accounts/'+aid);if(active)setData(v)}
      catch(e){if(active)setError(readableError(e))}finally{running=false}}
    void load();const t=window.setInterval(()=>{if(!document.hidden)void load()},5000);return()=>{active=false;window.clearInterval(t)}},[aid,revision,mode])
  const run=async<T,>(path:string,body:unknown,done:(v:T)=>void)=>{
    setBusy(true);setError('');setNotice('')
    try{const v=await marketPost<T>(api+path,body);done(v)}catch(e){setError(readableError(e))}finally{setBusy(false)}
  }
  const current=data?.account.id===aid?data:null
  const modelAssumptions={lots:Number(lots),capital:Number(cash),hold_minutes:Number(hold),latency_ms:Number(latency),
    window_seconds:Number(ttl),participation_pct:Number(participation),slippage_bps:Number(slippage),broker_profile:broker}
  const controls=<><Num label="Lots" value={lots} set={setLots} min={1} max={50}/>
    <Num label="Latency (ms)" value={latency} set={setLatency} min={0} max={60000}/>
    <Num label={mode==='account'?'Time in force (s)':'Observation window (s)'} value={ttl} set={setTtl} min={1} max={mode==='account'?1800:180}/>
    <Num label="Displayed depth participation %" value={participation} set={setParticipation} min={1} max={100} step=".1"/>
    <Num label="Adverse slippage (bps)" value={slippage} set={setSlippage} min={0} max={500} step=".1"/></>
  return <section className="ao-root pt-workspace" aria-label="Paper Trading and Depth Replay">
    <div className="ao-warning"><AlertTriangle size={18}/><span><b>SIMULATED ONLY.</b> No broker orders, no real fills, no passive queue priority, no broker margin or expiry-settlement model. Use actual saved original depth only. Missing observations remain unavailable.</span></div>
    <div className="ao-header"><div><span className="ao-eyebrow">QUANTLAB · ORIGINAL-DEPTH EXECUTION RESEARCH</span><h3>Paper Trading &amp; Replay</h3><p>Virtual accounts are separate from the manual fill journal and the original market library.</p></div>
      <div className="ao-actions"><button onClick={onOpenChain}>Find option contracts</button><button onClick={onOpenDepth}>Inspect recorded depth</button><button onClick={()=>setRevision(x=>x+1)}><RefreshCw size={14}/>Refresh</button></div></div>
    <nav className="ao-tabs" role="tablist" aria-label="Paper trading views">
      {([['account','Paper Account & Orders'],['replay','Historical Depth / Spreads'],['rules','Rule-Based Replay']] as const).map(([k,v])=><button type="button" role="tab" aria-selected={mode===k} key={k} onClick={()=>{setMode(k);setError('');setNotice('')}}>{v}</button>)}</nav>
    {error&&<div className="ao-warning" role="alert">{error}</div>}{notice&&<p role="status" className="ao-muted">{notice}</p>}
    {mode==='account'&&<>
      <section className="ao-panel"><h4><Wallet size={15}/> Virtual accounts</h4>
        <label>Select preserved account<select value={aid} onChange={e=>setAid(e.target.value)}><option value="">Choose an account</option>{accounts.map(a=><option key={a.id} value={a.id}>{a.label} · {money(a.initial_cash)}</option>)}</select></label>
        <details className="ao-assumptions" open={!accounts.length||undefined}><summary>Create research account</summary>
          <form className="pt-form" onSubmit={e=>{e.preventDefault();void run<Account>('accounts',{label,initial_cash:Number(cash),risk_pct:Number(risk),loss_limit_pct:Number(loss),max_positions:Number(maxPositions),broker_profile:broker},v=>{setAid(v.id);setRevision(x=>x+1);setNotice('Virtual account created. No funds moved.')})}}>
            <label>Account label<input required value={label} maxLength={80} onChange={e=>setLabel(e.target.value)}/></label>
            <Num label="Starting virtual cash ₹" value={cash} set={setCash} min={1000} max={10000000}/>
            <Num label="Maximum premium exposure %" value={risk} set={setRisk} min={1} max={100}/>
            <Num label="Cumulative realized loss limit %" value={loss} set={setLoss} min={1} max={100}/>
            <Num label="Maximum concurrent positions" value={maxPositions} set={setMaxPositions} min={1} max={20}/>
            <Broker value={broker} set={setBroker}/><button disabled={busy}>Create virtual account</button>
          </form><p className="ao-muted">Exposure and loss thresholds are adjustable research assumptions, not recommendations. Existing accounts and records are preserved.</p>
        </details>
      </section>
      {current&&<>
        <div className="ao-grid ao-summary"><Metric label="Virtual cash" value={money(current.account.cash)}/><Metric label="Reserved buy funds" value={money(current.reserved_cash)}/>
          <Metric label="Available virtual cash" value={money(current.available_cash)}/><Metric label="Realized simulated P&L" value={money(current.account.realized)}/>
          <Metric label="Observed liquidation equity" value={money(current.equity)} detail={current.marked_count+'/'+current.positions.length+' positions with complete fresh bid marks'}/>
          <Metric label="Estimated charges paid" value={money(current.account.fees_paid)}/></div>
        <section className="ao-panel"><h4>Submit a simulated order</h4><p>Orders are eligible only after the entered latency. Protected market attempts the first valid later book once; limits can fill across later marketable books. No naked short positions. A SELL can only close held long units.</p>
          <form className="pt-form" onSubmit={e=>{e.preventDefault();void run<Order>('accounts/'+aid+'/orders',{identity,action,kind,lots:Number(lots),protection_price:Number(price),latency_ms:Number(latency),ttl_seconds:Number(ttl),participation_pct:Number(participation),slippage_bps:Number(slippage)},v=>{setNotice('Simulated order '+v.id+' accepted locally. Waiting for later original depth.');setRevision(x=>x+1)})}}>
            <label>Exact verified Dhan option identity<input required pattern="NSE_FNO:[0-9]{1,12}" value={identity} onChange={e=>setIdentity(e.target.value.toUpperCase())} placeholder="NSE_FNO:12345"/></label>
            <label>Action<select value={action} onChange={e=>setAction(e.target.value)}><option>BUY</option><option>SELL</option></select></label>
            <label>Order type<select value={kind} onChange={e=>setKind(e.target.value)}><option value="PROTECTED_MARKET">Protected market · IOC proxy</option><option value="LIMIT">Resting limit · marketable only</option></select></label>
            <Num label={action==='BUY'?'Maximum buy premium ₹':'Minimum sell premium ₹'} value={price} set={setPrice} min={.01} max={1000000} step=".01"/>
            {controls}<button className="ao-primary" disabled={busy||!aid}>Submit paper order</button>
          </form><p className="ao-muted">Worker: {human(current.worker.state)}{current.worker.last_error?' · '+current.worker.last_error:''}. Snapshot {time(current.generated_utc)}.</p>
        </section>
        <section className="ao-panel"><h4>Orders and reserved quantities</h4><div className="ao-table-wrap"><table className="ao-table"><thead><tr><th>Contract</th><th>Side / type</th><th>State</th><th>Filled / requested</th><th>Price protection</th><th>Fees / reserved cash</th><th>Eligible / deadline</th><th>Source books</th><th>Action</th></tr></thead><tbody>
          {current.orders.map(o=><tr key={o.id}><td>{o.symbol}<br/>{o.identity}</td><td>{o.action} · {human(o.kind)}</td><td title={o.terminal_reason||''}>{human(o.state)}{o.cancel_requested_utc?' · cancel requested':''}</td><td>{o.filled}/{o.quantity}</td><td>{money(o.protection_price)}</td><td>{money(o.fees)} / {money(o.reserved_cash)}</td><td>{time(o.ready_utc)}<br/>{time(o.deadline_utc)}</td><td>{o.valid_books} valid · {o.invalid_books} rejected</td><td><button disabled={busy||!['working','partially_filled'].includes(o.state)||!!o.cancel_requested_utc} onClick={()=>void run<Order>('orders/'+o.id+'/cancel',{},()=>{setRevision(x=>x+1);setNotice('Cancellation requested; earlier eligible receipts remain in scope.')})}>Cancel remaining</button></td></tr>)}
          {!current.orders.length&&<tr><td colSpan={9}>No paper orders yet.</td></tr>}</tbody></table></div></section>
        <section className="ao-panel"><h4>Paper positions</h4><div className="ao-table-wrap"><table className="ao-table"><thead><tr><th>Contract</th><th>Units</th><th>Cost basis including fees</th><th>Observed bid mark</th><th>Net unrealized</th><th>State</th><th>Action</th></tr></thead><tbody>
          {current.positions.map(p=><tr key={p.identity}><td>{p.symbol}<br/>{p.expiry} · {p.identity}</td><td>{p.quantity}</td><td>{money(p.cost_basis)}</td><td>{money(p.mark)}<br/>{time(p.mark_utc)}</td><td className={sign(p.unrealized_net)}>{money(p.unrealized_net)}</td><td>{human(p.state)}</td><td><button onClick={()=>{setIdentity(p.identity);setAction('SELL');setLots(String(p.quantity/p.lot_size));if(p.mark)setPrice(String(p.mark));window.scrollTo({top:0,behavior:'smooth'})}}>Prepare SELL</button></td></tr>)}
          {!current.positions.length&&<tr><td colSpan={7}>No open simulated positions.</td></tr>}</tbody></table></div></section>
        <section className="ao-panel"><h4>Simulated fill ledger</h4><div className="ao-table-wrap"><table className="ao-table"><thead><tr><th>Book receipt</th><th>Order / identity</th><th>Units</th><th>VWAP</th><th>Turnover</th><th>Incremental charges</th><th>Realized delta</th></tr></thead><tbody>
          {current.fills.map(f=><tr key={f.id}><td>{time(f.book_received_utc)}</td><td>{f.order_id}<br/>{f.identity}</td><td>{f.units}</td><td>{money(f.vwap)}</td><td>{money(f.turnover)}</td><td>{money(f.incremental_fees)}</td><td className={sign(f.realized_delta)}>{money(f.realized_delta)}</td></tr>)}
          {!current.fills.length&&<tr><td colSpan={7}>No hypothetical fills recorded yet.</td></tr>}</tbody></table></div><Equity rows={current.equity_samples}/><p className="ao-muted">{current.warning}</p></section>
      </>}
    </>}
    {mode==='replay'&&<><section className="ao-panel"><h4>Historical original-depth trade / spread replay</h4><p>Enter exact saved contract IDs in the shown structure order. First eligible receipts in fixed windows only; multi-leg results are synchronized conditional baskets, not sequential execution or verified margin.</p>
      <form className="pt-form" onSubmit={e=>{e.preventDefault();setReplay(null);void run<Replay>('depth-replay',{...modelAssumptions,strategy,identities:ids.split(/[ ,]+/).filter(Boolean),decision_utc:day+'T'+decision+(decision.length===5?':00':'')+'+05:30',max_skew_seconds:Number(skew)},setReplay)}}>
        <label>Structure<select value={strategy} onChange={e=>setStrategy(e.target.value)}>{Object.entries(strategyOptions).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>
        <label>Ordered original identities<input required value={ids} onChange={e=>setIds(e.target.value.toUpperCase())} placeholder="NSE_FNO:12345 NSE_FNO:12346"/></label>
        <label>Trading date (IST)<input required type="date" value={day} onChange={e=>setDay(e.target.value)}/></label>
        <label>Decision time (IST)<input required type="time" step="1" value={decision} onChange={e=>setDecision(e.target.value)}/></label>
        <Num label="Research capital ₹" value={cash} set={setCash} min={1000} max={10000000}/>
        <Num label="Hold minutes" value={hold} set={setHold} min={1} max={1440}/>
        <Num label="Maximum leg skew (s)" value={skew} set={setSkew} min={0} max={30} step=".1"/>
        {controls}<Broker value={broker} set={setBroker}/><button disabled={busy}>Run original-depth replay</button>
      </form></section>{replay&&<ReplayDetail result={replay}/>}</>}
    {mode==='rules'&&<><section className="ao-panel"><h4><Activity size={15}/> Rule-based historical replay</h4><p>Use completed saved BANKNIFTY index minute bars and fixed, preselected historical CE/PE identities. No optimization against future results. Missing execution evidence is censored; potentially committed capital is not reused.</p>
      <form className="pt-form" onSubmit={e=>{e.preventDefault();setRules(null);void run<RuleReplay>('rule-replay',{...modelAssumptions,day,call_identity:ce,put_identity:pe,rule,fast:Number(fast),slow:Number(slow),lookback:Number(lookback),threshold:Number(threshold),hold_rule:holdRule},setRules)}}>
        <label>Trading date (IST)<input required type="date" value={day} onChange={e=>setDay(e.target.value)}/></label>
        <label>Historical CE identity<input required pattern="NSE_FNO:[0-9]{1,12}" value={ce} onChange={e=>setCe(e.target.value.toUpperCase())}/></label>
        <label>Historical PE identity<input required pattern="NSE_FNO:[0-9]{1,12}" value={pe} onChange={e=>setPe(e.target.value.toUpperCase())}/></label>
        <label>Rule<select value={rule} onChange={e=>setRule(e.target.value)}><option value="EMA_CROSSOVER">EMA crossover</option><option value="MOMENTUM">Momentum</option><option value="MEAN_REVERSION">Mean reversion</option></select></label>
        {rule==='EMA_CROSSOVER'?<><Num label="Fast EMA" value={fast} set={setFast} min={2} max={149}/><Num label="Slow EMA" value={slow} set={setSlow} min={3} max={150}/></>:<><Num label="Lookback bars" value={lookback} set={setLookback} min={2} max={150}/><Num label={rule==='MOMENTUM'?'Return threshold %':'Z-score threshold'} value={threshold} set={setThreshold} min={.001} max={100} step=".001"/></>}
        <label>Exit rule<select value={holdRule} onChange={e=>setHoldRule(e.target.value)}><option value="FIXED">Fixed holding time</option><option value="FLIP">Hold until opposite signal, close then flip</option></select></label>
        <Num label="Hold minutes (fixed mode)" value={hold} set={setHold} min={1} max={1440}/>
        <Num label="Research capital ₹" value={cash} set={setCash} min={1000} max={10000000}/>
        {controls}<Broker value={broker} set={setBroker}/><button disabled={busy}>Run rule replay</button>
      </form></section>{rules&&<section className="ao-panel"><h4>{human(rules.state)}</h4><div className="ao-grid ao-summary"><Metric label="Observed minute bars" value={String(rules.bars)}/><Metric label="Signals" value={String(rules.signals)}/><Metric label="Completed observed replays" value={String(rules.completed)}/><Metric label="Complete net P&L" value={money(rules.net_pnl_inr)}/><Metric label="Completed subset net" value={money(rules.completed_subset_net_pnl_inr)} detail="Excludes unresolved execution"/><Metric label="Positive / negative" value={(rules.positive??0)+' / '+(rules.negative??0)}/></div>
        {rules.trades.map((r,i)=><details className="ao-assumptions" key={i}><summary>{time(r.decision_utc)} · {r.signal} · {human(r.state)} · {money(r.net_pnl_inr)}</summary><ReplayDetail result={r}/></details>)}<p>{rules.warning}</p></section>}</>}
  </section>
}
