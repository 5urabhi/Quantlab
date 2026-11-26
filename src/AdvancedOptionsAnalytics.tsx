import {useEffect,useMemo,useState} from 'react'
import {Activity,AlertTriangle,ArrowDownUp,Calculator,Check,Clock3,RefreshCw,Star} from 'lucide-react'
import {marketApi,readableError} from './tradingCockpitApi'
import type {Chain,OptionContract} from './OptionChainLive'
import './advanced-options.css'
import ResearchPlot from './ResearchPlots'
import ConditionalGamma from './ConditionalGamma'
import './constituent-intelligence.css'
import ManualOptionsWorkflow,{IndiaVixMetric} from './ManualOptionsWorkflow'

type Settings={
  capital:number;max_lots:number;direction:'BOTH'|'UP'|'DOWN';move_points:number
  horizon_minutes:number;iv_change_points:number;rate_pct:number;dividend_pct:number
  max_spread_bps:number;risk_pct:number;target_premium:number;slippage_bps:number
  broker_profile:'zerodha'|'dhan'|'zerodha_debit_balance'
}
type Greeks={price:number;delta:number;gamma:number;theta_day:number;vega_iv_point:number;rho_rate_point:number}
type Scenario={move_points:number;iv_change_points:number;minutes:number;model_mid:number
  assumed_exit_bid:number;charges_inr:number;net_pnl_inr:number}
type Fees={total_estimated:number;buy_leg:{cash_debit:number;fees_total:number};sell_leg:{fees_total:number}
  brokerage:number;stt_sell:number;gst:number;exchange_indicative:number;stamp_buy:number;sebi:number}
type Row=OptionContract&{
  mid:number|null;intrinsic:number;extrinsic:number|null;moneyness:string
  spread_bps:number|null;iv_mid_pct:number|null;iv_bid_pct:number|null;iv_ask_pct:number|null
  model_greeks:Greeks|null;iv_change_pct_points:number|null;oi_change:number|null;volume_change:number|null
  trade_activity:{trade_times:number;volume_delta:number;last_exchange_trade_utc:string}|null
  trade_activity_state:string;top_level_lots:number|null;affordable_lots:number|null
  scenario_lots:number;units:number;entry_debit_inr:number|null;max_premium_loss_inr:number|null
  break_even_exit_premium:number|null;roundtrip_fees:Fees|null;same_quote_roundtrip_net_inr:number|null
  scenarios:Record<string,Scenario|null>;score:number|null;reasons:string[];rank?:number;rank_quality?:string
  depth_state:string;depth:{received_utc:string;age_seconds:number;bid:number;ask:number;spread_bps:number
    imbalance_20:number;bid_quantity_20:number;ask_quantity_20:number;top_bid_quantity:number;top_ask_quantity:number}|null
  unsigned_gamma_oi_proxy:number|null
  premium_change?:number|null;price_oi_state?:string|null
  score_components?:{reward_risk:number;spread:number;premium_fit:number;favorable_return:number
    favorable_return_pct:number;adverse_loss_pct:number;flat_loss_pct:number;iv_contraction_drag_pct:number}|null
}
type IVPoint={day?:string;expiry?:string;captured_utc:string;strike:number;iv_pct:number;spot:number}
type HistoryPoint={captured_utc:string;spot:number;ltp:number|null;iv:number|null;delta:number|null
  gamma:number|null;theta:number|null;vega:number|null;oi:number|null;volume:number|null}
type Analysis={
  chain:Chain;rows:Row[];ranked_count:number;confirmed_depth_count:number;recent_trade_count:number
  as_of_utc:string;generated_utc:string;snapshot_age_seconds:number;recent_receipt:boolean
  assumed_expiry_utc:string;years_to_expiry:number;assumptions:Settings
  volatility:{atm_provider_iv_pct:number|null;realized_intraday_pct:number|null;realized_returns:number
    realized_last_utc:string|null;expected_move_points_model:number|null;iv_rank:number|null;iv_percentile:number|null
    iv_prior_sessions:number;iv_min_prior_sessions:number;iv_history:IVPoint[];term_structure:IVPoint[];india_vix:null}
  oi:{call_oi:number|null;put_oi:number|null;known_counts:Record<string,number>;contract_counts:Record<string,number>
    complete:boolean;pcr:number|null;max_pain_strike:number|null;previous_snapshot_utc:string|null;dealer_gamma_exposure:null}
  selected_history_identity:string|null;selected_history:HistoryPoint[];historical_error:string|null
  warnings:string[];orders_enabled:false
}
type Tab='rank'|'greeks'|'volatility'|'oi'|'liquidity'|'calculator'|'watch'
type Column={key:string;label:string;get:(r:Row)=>number|string|null|undefined;digits?:number;money?:boolean}
const nf=(v:number|null|undefined,d=2)=>v==null||!Number.isFinite(v)?'—':v.toLocaleString('en-IN',{maximumFractionDigits:d})
const rs=(v:number|null|undefined)=>v==null?'—':'₹'+nf(v)
const fmtTime=(v?:string|null)=>v?new Date(v).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',second:'2-digit'})+' IST':'Unavailable'
const status=(v?:string)=>({recent_depth_and_trades:'Recent depth + trades',recent_trades_snapshot_only:'Recent trades · snapshot',indicative_snapshot_only:'Indicative · activity unverified',recent_original_book:'Recent original book',delayed_original_book:'Delayed original book',no_recent_original_book:'No recent original book',not_checked:'Depth not checked',original_book_unavailable:'Depth unavailable',recent_trade_evidence:'Recent trade evidence',insufficient_recent_trades:'Insufficient trade activity',missing_trade_evidence:'Activity evidence missing'} as Record<string,string>)[v||'']||v||'Not ranked'
const signed=(n:number|null|undefined)=>n==null?'':n>0?'ao-positive':n<0?'ao-negative':''
const scenarioNames:Record<string,string>={favorable:'Favorable move',flat:'Flat underlying',adverse:'Adverse move',iv_crush:'Favorable + 2pp IV contraction',iv_expansion:'Favorable + 2pp IV expansion',double_favorable:'Double favorable move',double_adverse:'Double adverse move'}
const baseColumns:Column[]=[
  {key:'strike',label:'Strike',get:r=>r.strike,digits:0},
  {key:'type',label:'Side',get:r=>r.option_type},
  {key:'ltp',label:'LTP ₹',get:r=>r.ltp,money:true},
  {key:'bid',label:'Bid ₹',get:r=>r.bid,money:true},
  {key:'ask',label:'Ask ₹',get:r=>r.ask,money:true},
]
const rankColumns:Column[]=[
  {key:'rank',label:'Rank',get:r=>r.rank,digits:0},...baseColumns,
  {key:'lots',label:'Model lots',get:r=>r.scenario_lots,digits:0},
  {key:'capital',label:'Entry debit',get:r=>r.entry_debit_inr,money:true},
  {key:'delta',label:'Model Δ',get:r=>r.model_greeks?.delta,digits:3},
  {key:'iv',label:'Mid IV %',get:r=>r.iv_mid_pct},
  {key:'spread',label:'Spread bps',get:r=>r.spread_bps},
  {key:'gain',label:'Favorable net',get:r=>r.scenarios.favorable?.net_pnl_inr,money:true},
  {key:'loss',label:'Adverse net',get:r=>r.scenarios.adverse?.net_pnl_inr,money:true},
  {key:'score',label:'Fit score',get:r=>r.score},
  {key:'evidence',label:'Evidence',get:r=>status(r.rank_quality||r.trade_activity_state)},
]
const columns:Record<Exclude<Tab,'calculator'>,Column[]>={
  rank:rankColumns,watch:rankColumns,
  greeks:[...baseColumns,{key:'money',label:'Moneyness',get:r=>r.moneyness},
    {key:'intrinsic',label:'Intrinsic ₹',get:r=>r.intrinsic,money:true},
    {key:'extrinsic',label:'Extrinsic ₹',get:r=>r.extrinsic,money:true},
    {key:'d',label:'Delta',get:r=>r.model_greeks?.delta,digits:4},
    {key:'g',label:'Gamma',get:r=>r.model_greeks?.gamma,digits:7},
    {key:'th',label:'Theta / day',get:r=>r.model_greeks?.theta_day,digits:4},
    {key:'v',label:'Vega / IV pp',get:r=>r.model_greeks?.vega_iv_point,digits:4},
    {key:'rh',label:'Rho / rate pp',get:r=>r.model_greeks?.rho_rate_point,digits:4},
    {key:'dd',label:'Dhan delta',get:r=>r.delta,digits:4},{key:'dg',label:'Dhan gamma',get:r=>r.gamma,digits:7},
    {key:'dt',label:'Dhan theta',get:r=>r.theta,digits:4},{key:'dv',label:'Dhan vega',get:r=>r.vega,digits:4}],
  volatility:[...baseColumns,{key:'vendor',label:'Dhan IV %',get:r=>r.iv},
    {key:'bidiv',label:'Bid IV %',get:r=>r.iv_bid_pct},{key:'midiv',label:'Mid IV %',get:r=>r.iv_mid_pct},
    {key:'askiv',label:'Ask IV %',get:r=>r.iv_ask_pct},{key:'change',label:'Δ IV (pp)',get:r=>r.iv_change_pct_points},
    {key:'theta',label:'Theta/day',get:r=>r.model_greeks?.theta_day,digits:4}],
  oi:[...baseColumns,{key:'oi',label:'OI',get:r=>r.oi,digits:0},{key:'oichg',label:'Δ OI',get:r=>r.oi_change,digits:0},
    {key:'price_oi',label:'Price / OI change',get:r=>r.price_oi_state},
    {key:'premium_change',label:'Δ premium',get:r=>r.premium_change,money:true},
    {key:'volume',label:'Volume',get:r=>r.volume,digits:0},{key:'volchg',label:'Δ volume',get:r=>r.volume_change,digits:0},
    {key:'traded',label:'Recent trade times',get:r=>r.trade_activity?.trade_times,digits:0},
    {key:'gex',label:'Unsigned gamma × OI proxy',get:r=>r.unsigned_gamma_oi_proxy,digits:0}],
  liquidity:[...baseColumns,{key:'spread',label:'Spread bps',get:r=>r.spread_bps},
    {key:'bq',label:'Chain bid qty',get:r=>r.top_bid_quantity,digits:0},{key:'aq',label:'Chain ask qty',get:r=>r.top_ask_quantity,digits:0},
    {key:'depth',label:'Original 20-level',get:r=>status(r.depth_state)},
    {key:'age',label:'Book age (s)',get:r=>r.depth?.age_seconds},{key:'imbalance',label:'Depth imbalance',get:r=>r.depth?.imbalance_20,digits:3},
    {key:'b20',label:'20 bid qty',get:r=>r.depth?.bid_quantity_20,digits:0},{key:'a20',label:'20 ask qty',get:r=>r.depth?.ask_quantity_20,digits:0},
    {key:'vol',label:'120s volume Δ',get:r=>r.trade_activity?.volume_delta,digits:0},
    {key:'fees',label:'Round-trip charges',get:r=>r.roundtrip_fees?.total_estimated,money:true},
    {key:'same',label:'Immediate net',get:r=>r.same_quote_roundtrip_net_inr,money:true}],
}
function Metric({label,value,detail}:{label:string;value:string;detail?:string}){
  return <div className="ao-metric"><span>{label}</span><strong>{value}</strong>{detail&&<small>{detail}</small>}</div>
}
type Point={x:number;y:number|null;label?:string}
type Series={label:string;points:Point[];color:string}
function Plot({title,series,xFormat=nf,yFormat=nf,description,xLabel,yLabel}:{
  title:string;series:Series[];xFormat?:(v:number)=>string;yFormat?:(v:number)=>string;description:string;xLabel?:string;yLabel?:string
}){
  const xs=Array.from(new Set(series.flatMap(s=>s.points.filter(p=>Number.isFinite(p.x)).map(p=>p.x)))).sort((a,b)=>a-b)
  const traces=series.map(s=>{const byX=new Map(s.points.map(p=>[p.x,p.y]));return {name:s.label,color:s.color,y:xs.map(x=>{const y=byX.get(x);return y!==null&&y!==undefined&&Number.isFinite(y)?y:null})}})
  if(!traces.some(s=>s.y.some(v=>v!==null)))return <div className="ao-plot"><strong>{title}</strong><p>No source-backed values available.</p></div>
  return <div className="ao-plot"><ResearchPlot plot={{kind:'line2d',title,x:xs,traces,x_label:xLabel||'Strike (index points)',y_label:yLabel||title}} provenance="options-snapshot" formatX={x=>xFormat(Number(x))} formatY={yFormat}/><small>{description}</small></div>
}
function Table({rows,cols,selected,onSelect,sortKey,onSort,ascending}:{
  rows:Row[];cols:Column[];selected:string;onSelect:(id:string)=>void
  sortKey:string;onSort:(key:string)=>void;ascending:boolean
}){
  return <div className="ao-table-wrap"><table className="ao-table"><thead><tr>
    {cols.map(c=><th key={c.key} aria-sort={sortKey===c.key?(ascending?'ascending':'descending'):'none'}>
      <button type="button" onClick={()=>onSort(c.key)}>{c.label} <ArrowDownUp size={11}/></button></th>)}<th>Inspect</th>
    </tr></thead><tbody>{rows.map(r=><tr key={r.option_type+':'+r.strike}
      className={r.identity&&r.identity===selected?'ao-selected':''}>
      {cols.map(c=>{const v=c.get(r);return <td key={c.key}
        className={['gain','loss','same','oichg','change'].includes(c.key)&&typeof v==='number'?signed(v):''}>
        {typeof v==='number'?(c.money?rs(v):nf(v,c.digits)):v??'—'}</td>})}
      <td><button type="button" disabled={!r.identity} onClick={()=>r.identity&&onSelect(r.identity)}
        title={r.reasons.join(' · ')}>Inspect</button>
        {!!r.reasons.length&&<small className="ao-reason" title={r.reasons.join(' · ')}>{r.reasons[0]}</small>}</td>
    </tr>)}
    {!rows.length&&<tr><td colSpan={cols.length+1}>No contracts match this view. Change filters or check source evidence.</td></tr>}
    </tbody></table></div>
}
type Props={
  initialWorkflow?:boolean;expiry:string;selected:string;onSelect:(id:string)=>void;onSnapshot:(chain:Chain)=>void
  capital:number;lots:number;targetPremium:number;onSettings:(capital:number,lots:number,premium:number)=>void
  onDraftJournal:(contract:OptionContract,lots:number)=>void
  onChooseContract:(expiry:string,identity:string)=>void}
export default function AdvancedOptionsAnalytics({expiry,selected,onSelect,onSnapshot,capital,lots,targetPremium,onSettings,onDraftJournal,onChooseContract,initialWorkflow=false}:Props){
  const defaults:Settings={capital,max_lots:lots,direction:'BOTH',move_points:100,horizon_minutes:5,
    iv_change_points:0,rate_pct:6.5,dividend_pct:0,max_spread_bps:250,risk_pct:100,
    target_premium:targetPremium,slippage_bps:10,broker_profile:'zerodha'}
  const [form,setForm]=useState<Settings>(defaults)
  const [applied,setApplied]=useState<Settings>(defaults)
  const [tab,setTab]=useState<Tab>('rank')
  const [workflowOpen,setWorkflowOpen]=useState(initialWorkflow)
  useEffect(()=>setWorkflowOpen(initialWorkflow),[initialWorkflow])
  const [data,setData]=useState<Analysis|null>(null)
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  const [refresh,setRefresh]=useState(0)
  const [search,setSearch]=useState('')
  const [side,setSide]=useState<'ALL'|'CE'|'PE'>('ALL')
  const [rankedOnly,setRankedOnly]=useState(true)
  const [page,setPage]=useState(0)
  const [sortKey,setSortKey]=useState('rank')
  const [ascending,setAscending]=useState(true)
  const [clock,setClock]=useState(Date.now())
  const [historyMetric,setHistoryMetric]=useState<keyof Pick<HistoryPoint,'ltp'|'iv'|'delta'|'gamma'|'theta'|'vega'|'oi'|'volume'>>('ltp')
  const [watch,setWatch]=useState<string[]>(()=>{try{const v=JSON.parse(localStorage.getItem('quantlab:advanced-options-watchlist')||'[]');return Array.isArray(v)?v.filter(x=>typeof x==='string'&&/^NSE_FNO:[0-9]+$/.test(x)).slice(0,200):[]}catch{return []}})
  useEffect(()=>{try{localStorage.setItem('quantlab:advanced-options-watchlist',JSON.stringify(watch))}catch{/* local preferences unavailable */}},[watch])
  useEffect(()=>{const tick=window.setInterval(()=>setClock(Date.now()),1000);return()=>window.clearInterval(tick)},[])
  useEffect(()=>{
    if(!expiry||workflowOpen)return
    let active=true,running=false
    const controller=new AbortController()
    const poll=async()=>{
      if(running||!active)return
      running=true;setBusy(true);setError('')
      try{
        const params=new URLSearchParams({expiry,selected,...Object.fromEntries(Object.entries(applied).map(([k,v])=>[k,String(v)]))})
        const result=await marketApi<Analysis>('/api/trading-cockpit/options/analytics?'+params,{signal:controller.signal})
        if(active){setData(result);onSnapshot(result.chain)}
      }catch(e){if(active)setError(readableError(e))}
      finally{running=false;if(active)setBusy(false)}
    }
    void poll()
    const timer=window.setInterval(()=>{if(!document.hidden)void poll()},30000)
    return()=>{active=false;controller.abort();window.clearInterval(timer)}
  },[expiry,applied,selected,refresh,onSnapshot,workflowOpen])
  const result=data?.chain.expiry===expiry?data:null
  const inputChanged=JSON.stringify(form)!==JSON.stringify(applied)
  const age=result?Math.max(0,(clock-Date.parse(result.as_of_utc))/1000):null
  const scenarioMatches=Boolean(result&&Object.entries(applied).every(([key,value])=>result.assumptions[key as keyof Settings]===value))
  const usable=Boolean(result?.recent_receipt&&age!==null&&age<=30&&!error&&scenarioMatches&&!inputChanged)
  const effectiveRows=useMemo(()=>result?(usable?result.rows:result.rows.map(r=>({...r,rank:undefined,rank_quality:undefined,score:null}))):[],[result,usable])
  const ranked=useMemo(()=>effectiveRows.filter(r=>r.rank!==undefined).sort((a,b)=>a.rank!-b.rank!),[effectiveRows])
  const picks=applied.direction==='BOTH'?
    [...ranked.filter(r=>r.option_type==='CE').slice(0,2),...ranked.filter(r=>r.option_type==='PE').slice(0,2)]:ranked.slice(0,4)
  const active=effectiveRows.find(r=>r.identity===selected)||ranked[0]||null
  const shownCols=tab==='calculator'?rankColumns:columns[tab]
  const tableRows=useMemo(()=>{
    let rows=effectiveRows.filter(r=>(side==='ALL'||r.option_type===side)&&
      (!search||[r.strike,r.symbol,r.identity,r.option_type].join(' ').toLowerCase().includes(search.toLowerCase()))&&
      (tab!=='rank'||!rankedOnly||!usable||!ranked.length||r.rank!==undefined)&&(tab!=='watch'||Boolean(r.identity&&watch.includes(r.identity))))
    const col=shownCols.find(c=>c.key===sortKey)
    if(col)rows=[...rows].sort((a,b)=>{
      const av=col.get(a),bv=col.get(b)
      if(av==null)return bv==null?0:1
      if(bv==null)return -1
      return (typeof av==='number'&&typeof bv==='number'?av-bv:String(av).localeCompare(String(bv)))*(ascending?1:-1)
    })
    return rows
  },[effectiveRows,side,search,tab,rankedOnly,watch,shownCols,sortKey,ascending,usable,ranked.length])
  useEffect(()=>setPage(0),[tab,side,search,rankedOnly,sortKey,ascending,expiry])
  const switchTab=(next:Tab)=>{setTab(next);setSortKey(next==='rank'||next==='watch'?'rank':'strike');setAscending(true)}
  const toggleWatch=(id:string)=>setWatch(old=>old.includes(id)?old.filter(x=>x!==id):[id,...old].slice(0,200))
  const numberField=(label:string,key:keyof Settings,min:number,max:number,step=1)=><label key={key}>{label}
    <input aria-label={label} type="number" value={String(form[key])} min={min} max={max} step={step}
      onChange={e=>{const x=Number(e.target.value);if(Number.isFinite(x))setForm(v=>({...v,[key]:x}))}}/></label>
  const chainPlot=(key:(r:Row)=>number|null|undefined):Series[]=>['CE','PE'].map((s,i)=>({label:s,color:i?'#f0b786':'#68d7d1',
    points:effectiveRows.filter(r=>r.option_type===s&&result&&Math.abs(r.strike-result.chain.underlying_spot)<=result.chain.underlying_spot*.05)
      .map(r=>({x:r.strike,y:key(r)??null,label:String(r.strike)}))}))
  const historySeries=(name:string,points:IVPoint[]):Series[]=>[{label:name,color:'#81d5e1',
    points:points.map(p=>({x:Date.parse(p.expiry||p.day||p.captured_utc),y:p.iv_pct,label:p.expiry||p.day||p.captured_utc}))}]
  const dateLabel=(x:number)=>new Date(x).toLocaleDateString('en-IN',{day:'numeric',month:'short',timeZone:'Asia/Kolkata'})
  const tabs:[Tab,string][]=[['rank','Best-fit contracts'],['greeks','Greeks'],['volatility','Volatility'],['oi','OI & Volume'],['liquidity','Liquidity'],['calculator','Trade Calculator'],['watch','Watchlist']]
  return <section className="ao-root" aria-label="Advanced Options Analytics">
    <header className="ao-header"><div><span className="ao-eyebrow">SOURCE-BACKED OPTIONS WORKSPACE</span><h3>Advanced Options Analytics</h3>
      <p>Compare long CE / PE contracts using one option-chain receipt, explicit market scenarios and estimated costs. No broker orders.</p></div>
      <button type="button" onClick={()=>setRefresh(x=>x+1)} disabled={busy||!expiry||workflowOpen}><RefreshCw size={15}/>{busy&&!workflowOpen?'Analyzing…':'Refresh analytics'}</button></header>
    <div className="ao-mode" role="group" aria-label="Advanced analytics mode">
      <button type="button" aria-pressed={!workflowOpen} onClick={()=>setWorkflowOpen(false)}>Contract analytics</button>
      <button type="button" aria-pressed={workflowOpen} onClick={()=>setWorkflowOpen(true)}>Manual trading workflow</button>
    </div>
    <form className="ao-settings" onSubmit={e=>{e.preventDefault();setApplied({...form});onSettings(form.capital,form.max_lots,form.target_premium)}}>
      <label>Assumed BANKNIFTY direction<select value={form.direction} onChange={e=>setForm(v=>({...v,direction:e.target.value as Settings['direction']}))}>
        <option value="BOTH">Compare both directions</option><option value="UP">Bullish · CE</option><option value="DOWN">Bearish · PE</option>
      </select></label>
      {numberField('Capital ₹','capital',1000,100000000)}
      {numberField('Maximum lots','max_lots',1,50)}
      {numberField('Assumed move (pts)','move_points',1,10000)}
      {numberField('Holding minutes','horizon_minutes',1,1440)}
      {numberField('IV shock (percentage points)','iv_change_points',-50,50,.5)}
      {numberField('Preferred premium ₹','target_premium',1,100000)}
      {numberField('Max premium exposure %','risk_pct',1,100)}
      <details className="ao-assumptions"><summary>Model & cost assumptions</summary><div className="ao-input-grid">
        {numberField('Risk-free rate % (assumed)','rate_pct',-5,25,.1)}
        {numberField('Dividend yield % (assumed)','dividend_pct',0,25,.1)}
        {numberField('Max spread bps','max_spread_bps',10,5000)}
        {numberField('Extra exit slippage bps','slippage_bps',0,500)}
        <label>Broker charges<select value={form.broker_profile} onChange={e=>setForm(v=>({...v,broker_profile:e.target.value as Settings['broker_profile']}))}>
          <option value="zerodha">Zerodha regular</option><option value="dhan">Dhan regular</option><option value="zerodha_debit_balance">Zerodha debit-balance scenario</option></select></label>
      </div></details>
      <button type="submit" className="ao-primary" disabled={!expiry||(busy&&!workflowOpen)}>Apply scenario &amp; rank</button>
      {inputChanged&&<small className="ao-amber">Inputs changed — displayed values use the last applied scenario.</small>}
    </form>
    <ManualOptionsWorkflow visible={workflowOpen} onOpen={()=>setWorkflowOpen(true)} scenario={applied}
      selected={active} onChooseContract={(nextExpiry,id)=>{onChooseContract(nextExpiry,id);setWorkflowOpen(false);switchTab('calculator')}}/>
    {!workflowOpen&&<>
    {error&&<div className="ao-warning" role="alert"><AlertTriangle size={16}/>{error} · Previous values may be outdated.</div>}
    {!expiry&&<p className="ao-warning">Select a Dhan expiry to calculate analytics.</p>}
    {result&&<>
      <div className={'ao-source '+(usable?'ao-fresh':'ao-delayed')}><Clock3 size={16}/><span>
        {usable?'Recent chain receipt':inputChanged||!scenarioMatches?'Scenario refresh required':'Historical / delayed chain receipt'} · {fmtTime(result.as_of_utc)}
        {' · '}{nf(age,1)}s local receipt age · NOT exchange quote time.
        {result.historical_error?' '+result.historical_error+'.':''}</span></div>
      <div className="ao-grid ao-summary">
        <Metric label="BANKNIFTY spot" value={nf(result.chain.underlying_spot,2)} detail={expiry}/>
        <Metric label="Scenario-ranked contracts" value={String(usable?result.ranked_count:0)} detail={!usable?'No current shortlist':'Not trade signals'}/>
        <Metric label="Recent depth + trade evidence" value={String(usable?result.confirmed_depth_count:0)} detail="At scan · no execution guarantee"/>
        <Metric label="Recent trade activity" value={String(usable?result.recent_trade_count:0)} detail="Among ranked contracts"/>
        <Metric label="ATM Dhan IV" value={result.volatility.atm_provider_iv_pct===null?'Unavailable':nf(result.volatility.atm_provider_iv_pct)+'%'} detail="Nearest paired strike"/>
        <Metric label="Assumed horizon move" value={nf(result.volatility.expected_move_points_model,1)+' pts'} detail="IV-scaled model magnitude, not direction"/>
      </div>
      <nav className="ao-tabs" role="tablist" aria-label="Advanced options views">{tabs.map(([key,label])=><button key={key}
        type="button" role="tab" aria-selected={tab===key} onClick={()=>switchTab(key)}>{label}{key==='watch'?' ('+watch.length+')':''}</button>)}</nav>
      {tab==='rank'&&<section className="ao-panel">
        <h4>Best fit for the selected scenario</h4>
        <p>Sorted by source-evidence tier, then a heuristic comparing favorable net gain, adverse loss, time decay, IV-contraction drag, spread and preferred premium. In both-directions mode, the top two calls and top two puts are shown separately. Not a predicted win rate. Each contract is sized to budget, exposure cap and displayed top quantity.</p>
        {!usable||!ranked.length?<div className="ao-warning"><AlertTriangle size={17}/>
          No current qualified shortlist. Inspect rejected rows below to distinguish unavailable evidence, liquidity and scenario economics.</div>:
          <div className="ao-grid ao-picks">{picks.map(r=><button type="button" className="ao-pick" key={r.identity} onClick={()=>{if(r.identity)onSelect(r.identity);switchTab('calculator')}}>
            <span className="ao-eyebrow">#{r.rank} · {r.option_type} · {status(r.rank_quality)}</span>
            <strong>{nf(r.strike,0)} {r.option_type}</strong>
            <small>Ask {rs(r.ask)} · {r.scenario_lots} lots · {rs(r.entry_debit_inr)} cash debit</small>
            <div><span className={signed(r.scenarios.favorable?.net_pnl_inr)}>Favorable {rs(r.scenarios.favorable?.net_pnl_inr)}</span>
            <span className={signed(r.scenarios.adverse?.net_pnl_inr)}>Adverse {rs(r.scenarios.adverse?.net_pnl_inr)}</span></div>
            <small>Full premium loss: {rs(r.max_premium_loss_inr)} · Fit {nf(r.score,1)}/100</small>
          </button>)}</div>}
        <p className="ao-muted">Snapshot-only rows are indicative. Do not interpret a displayed positive scenario as expected profit. Default maximum exposure is 100% of entered capital, not a suggested risk allocation.</p>
      </section>}
      {tab==='greeks'&&<section className="ao-panel"><h4>Independent model sensitivities</h4>
        <p>BSM Greeks per option unit, calibrated to this contract's quoted midpoint. Theta is per calendar day; Vega and Rho are per percentage point. Dhan values are displayed separately as reported, without assuming their units.</p>
        <div className="ao-charts">
          <Plot title="Delta across strikes" yLabel="Delta (unitless)" series={chainPlot(r=>r.model_greeks?.delta)} description="Within ±5% of observed BANKNIFTY spot"/>
          <Plot title="Gamma across strikes" yLabel="Gamma (per index point)" series={chainPlot(r=>r.model_greeks?.gamma)} yFormat={v=>nf(v,6)} description="Per underlying point · within ±5% of spot"/>
          <Plot title="Theta per calendar day" yLabel="Theta (premium points/day)" series={chainPlot(r=>r.model_greeks?.theta_day)} description="Per option unit · within ±5% of spot"/>
          <Plot title="Vega per IV percentage point" yLabel="Vega (premium points/IV pp)" series={chainPlot(r=>r.model_greeks?.vega_iv_point)} description="Per option unit · within ±5% of spot"/>
        </div></section>}
      {tab==='volatility'&&<section className="ao-panel"><h4>Volatility and historical context</h4>
        <div className="ao-grid ao-summary">
          <Metric label="Realized intraday vol" value={result.volatility.realized_intraday_pct===null?'Unavailable':nf(result.volatility.realized_intraday_pct)+'%'} detail={result.volatility.realized_returns+' contiguous 1-minute returns · minimum 30'}/>
          <Metric label="Same-expiry IV rank" value={result.volatility.iv_rank===null?'Unavailable':nf(result.volatility.iv_rank)+'%'} detail={result.volatility.iv_prior_sessions+' prior observed dates · minimum 20'}/>
          <Metric label="Same-expiry IV percentile" value={result.volatility.iv_percentile===null?'Unavailable':nf(result.volatility.iv_percentile)+'%'} detail="Not constant-maturity IV"/>
          <IndiaVixMetric/>
        </div>
        <div className="ao-charts">
          <Plot title="Implied volatility smile / skew" yLabel="Implied volatility (%)" series={chainPlot(r=>r.iv_mid_pct)} description="Independent midpoint IV %, within ±5% of spot"/>
          <Plot title="ATM IV term structure" xLabel="Expiry date (epoch ms in exported data)" yLabel="Dhan IV (%)" series={historySeries('ATM Dhan IV',result.volatility.term_structure)} xFormat={dateLabel} description="Latest recorded receipt per expiry; times may differ"/>
          <Plot title="Recorded same-expiry ATM IV history" xLabel="Receipt date (epoch ms in exported data)" yLabel="Dhan IV (%)" series={historySeries('ATM Dhan IV',result.volatility.iv_history)} xFormat={dateLabel} description="One observed snapshot per date, current receipt appended"/>
        </div><p className="ao-muted">Realized volatility is based on saved index ticks aggregated into contiguous one-minute closes; no missing bars are filled. The IV horizon move is a calendar-time square-root model magnitude, not a confidence-certified price range.</p>
      </section>}
      {tab==='oi'&&<section className="ao-panel"><h4>Open interest and volume</h4>
        <div className="ao-grid ao-summary">
          <Metric label="Call OI (reported sum)" value={nf(result.oi.call_oi,0)} detail={result.oi.known_counts.CE+'/'+result.oi.contract_counts.CE+' rows with OI'}/>
          <Metric label="Put OI (reported sum)" value={nf(result.oi.put_oi,0)} detail={result.oi.known_counts.PE+'/'+result.oi.contract_counts.PE+' rows with OI'}/>
          <Metric label="Put / call OI ratio" value={nf(result.oi.pcr,3)} detail="Only if returned OI coverage complete"/>
          <Metric label="Max pain strike" value={nf(result.oi.max_pain_strike,0)} detail="Descriptive payout minimum, not a forecast"/>
        </div><p>Changes are relative to prior saved same-expiry receipt: {fmtTime(result.oi.previous_snapshot_utc)}. Missing changes remain unavailable. OI changes do not identify which participant opened or closed a position.</p>
        <div className="ao-charts"><Plot title="Open interest by strike" yLabel="Provider-reported OI (unit convention unverified)" series={chainPlot(r=>r.oi)} description="Provider-reported OI, within ±5% of spot"/>
          <Plot title="OI change by strike" yLabel="Change in reported OI" series={chainPlot(r=>r.oi_change)} description="Difference from previous saved same-session snapshot"/>
          <Plot title="Unsigned gamma × OI proxy" yLabel="Unsigned gamma × OI proxy" series={chainPlot(r=>r.unsigned_gamma_oi_proxy)} description="Gamma × reported OI × spot² × 1%; dealer sign / OI unit convention unknown"/>
        </div><p className="ao-muted">Dealer gamma exposure is unavailable: public OI does not reveal net dealer positioning. The unsigned proxy must not be interpreted as dealer GEX.</p></section>}
      {tab==='oi'&&<ConditionalGamma key={result.chain.expiry} rows={result.rows} spot={result.chain.underlying_spot} expiry={result.chain.expiry}/>}
      {tab==='liquidity'&&<section className="ao-panel"><h4>Quote and original-depth evidence</h4>
        <p>Chain top-level bid/ask and quantities are snapshots. Depth is checked only for up to 60 leading candidates plus the inspected contract. Recent trade observations and original depth do not establish your own fill or queue position.</p>
        <div className="ao-charts"><Plot title="Relative bid–ask spread" yLabel="Bid–ask spread (bps)" series={chainPlot(r=>r.spread_bps)} description="Basis points, within ±5% of spot"/>
          <Plot title="Recent reported volume increase" yLabel="Reported volume change (120 s)" series={chainPlot(r=>r.trade_activity?.volume_delta)} description="Saved Quote/OI feed, preceding 120 seconds"/></div></section>}
      {active&&<section className="ao-panel ao-inspect">
        <header className="ao-header"><div><span className="ao-eyebrow">INSPECT CONTRACT · {active.identity||'Unverified identity'}</span>
          <h4>{nf(active.strike,0)} {active.option_type} · {active.expiry}</h4>
          <p>{status(active.rank_quality||active.trade_activity_state)} · {active.moneyness} · {active.identity===selected?'Selected':'Top comparison candidate'}</p></div>
          <div className="ao-actions"><button type="button" disabled={!active.identity} onClick={()=>{if(active.identity)onSelect(active.identity);switchTab('calculator')}}><Calculator size={15}/> Trade calculator</button>
            <button type="button" disabled={!active.identity} onClick={()=>active.identity&&toggleWatch(active.identity)}><Star size={15} fill={active.identity&&watch.includes(active.identity)?'currentColor':'none'}/>{active.identity&&watch.includes(active.identity)?'Remove watch':'Watch'}</button></div></header>
        <div className="ao-grid ao-summary">
          <Metric label="Ask / bid" value={rs(active.ask)+' / '+rs(active.bid)} detail={'Mid '+rs(active.mid)}/>
          <Metric label="Affordable lots incl. fees" value={nf(active.affordable_lots,0)} detail={'Scenario uses '+active.scenario_lots+' lots / '+active.units+' units'}/>
          <Metric label="Premium debit incl. entry fees" value={rs(active.entry_debit_inr)} detail="Full premium can be lost"/>
          <Metric label="Break-even sell premium" value={rs(active.break_even_exit_premium)} detail="Estimated charges included, before tick rounding"/>
          <Metric label="Same-quote crossing net" value={rs(active.same_quote_roundtrip_net_inr)} detail="Not an executed round trip"/>
          <Metric label="20-level evidence" value={status(active.depth_state)} detail={active.depth?fmtTime(active.depth.received_utc):'No confirmed original book in lookback'}/>
        </div>
        {active.reasons.length>0&&<div className="ao-warning"><AlertTriangle size={15}/><span>Not shortlist-qualified: {active.reasons.join(' · ')}.</span></div>}
        {active.score_components&&usable&&<details className="ao-assumptions"><summary>Why this contract ranks here · {nf(active.score,2)}/100</summary>
          <div className="ao-grid ao-summary">
            <Metric label="Reward / risk" value={nf(active.score_components.reward_risk)+'/50'} detail="Includes adverse, flat and IV-contraction drag"/>
            <Metric label="Spread quality" value={nf(active.score_components.spread)+'/20'}/>
            <Metric label="Preferred premium fit" value={nf(active.score_components.premium_fit)+'/15'}/>
            <Metric label="Favorable return component" value={nf(active.score_components.favorable_return)+'/15'}/>
            <Metric label="Adverse scenario loss / debit" value={nf(active.score_components.adverse_loss_pct)+'%'}/>
            <Metric label="IV-contraction drag / debit" value={nf(active.score_components.iv_contraction_drag_pct)+'%'}/>
          </div></details>}
        {active.model_greeks&&<div className="ao-grid ao-summary">
          <Metric label="Position delta" value={nf(active.model_greeks.delta*active.units,3)} detail="₹ per underlying point"/>
          <Metric label="Position gamma" value={nf(active.model_greeks.gamma*active.units,5)} detail="₹ per point²"/>
          <Metric label="Position theta/day" value={rs(active.model_greeks.theta_day*active.units)}/>
          <Metric label="Position vega / IV pp" value={rs(active.model_greeks.vega_iv_point*active.units)}/>
          <Metric label="Position rho / rate pp" value={rs(active.model_greeks.rho_rate_point*active.units)}/>
        </div>}
        {tab==='calculator'&&<>
          <h4>Net P&amp;L scenarios · long {active.option_type} · {active.scenario_lots} lot(s)</h4>
          <div className="ao-table-wrap"><table className="ao-table"><thead><tr><th>Scenario</th><th>Spot move</th><th>IV shock pp</th><th>Minutes</th><th>Model midpoint</th><th>Assumed sell bid</th><th>Fees</th><th>Net P&amp;L</th></tr></thead><tbody>
            {Object.keys(scenarioNames).map(k=>{const v=active.scenarios[k];return <tr key={k}>
              <td>{scenarioNames[k]}</td><td>{nf(v?.move_points)}</td><td>{nf(v?.iv_change_points)}</td><td>{nf(v?.minutes,0)}</td>
              <td>{rs(v?.model_mid)}</td><td>{rs(v?.assumed_exit_bid)}</td><td>{rs(v?.charges_inr)}</td><td className={signed(v?.net_pnl_inr)}>{rs(v?.net_pnl_inr)}</td></tr>})}</tbody></table></div>
          <Plot title="Conditional net P&L versus BANKNIFTY move" xLabel="Underlying move (index points)" yLabel="Conditional net P&L (₹)" series={[{label:'Applied IV shock + horizon',color:'#75d6c5',points:['double_adverse','adverse','flat','favorable','double_favorable'].map(k=>active.scenarios[k]).filter((s):s is Scenario=>!!s).map(s=>({x:s.move_points,y:s.net_pnl_inr}))}]} yFormat={rs} description="Scenario repricing, not a price or profit forecast"/>
          {active.roundtrip_fees&&<details className="ao-assumptions"><summary>Estimated same-quote charge breakdown</summary><div className="ao-grid ao-summary">
            {Object.entries({Brokerage:active.roundtrip_fees.brokerage,STT:active.roundtrip_fees.stt_sell,GST:active.roundtrip_fees.gst,Exchange:active.roundtrip_fees.exchange_indicative,SEBI:active.roundtrip_fees.sebi,Stamp:active.roundtrip_fees.stamp_buy,Total:active.roundtrip_fees.total_estimated}).map(([name,v])=><Metric key={name} label={name} value={rs(v)}/>)}</div></details>}
          <button type="button" disabled={!active.identity||!active.units||!usable||!active.contract_master_verified} onClick={()=>onDraftJournal(active,active.scenario_lots)}>Prepare manual journal entry (no order)</button>
        </>}
        {active.identity===result.selected_history_identity&&<div className="ao-history">
          <label>Recorded selected-contract history<select value={historyMetric} onChange={e=>setHistoryMetric(e.target.value as typeof historyMetric)}>
            {(['ltp','iv','delta','gamma','theta','vega','oi','volume'] as const).map(k=><option key={k} value={k}>{k.toUpperCase()}</option>)}</select></label>
          <Plot title={'Recorded '+historyMetric.toUpperCase()} xLabel="Receipt time (IST; epoch ms exported)" yLabel={historyMetric==='ltp'?'Premium (₹ per unit)':historyMetric.toUpperCase()+' (provider units)'} series={[{label:'Original provider snapshots',color:'#95c8fd',points:result.selected_history.map(p=>({x:Date.parse(p.captured_utc),y:p[historyMetric],label:fmtTime(p.captured_utc)}))}]} xFormat={x=>new Date(x).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit'})} yFormat={v=>nf(v,historyMetric==='gamma'?7:3)} description="Up to 40 saved prior receipts in the same session; raw provider Greek units"/>
        </div>}
      </section>}
      {tab==='calculator'&&!active&&<div className="ao-warning">No contract selected. Open Greeks or Best-fit contracts and inspect a verified identity.</div>}
      {tab==='watch'&&<p className="ao-muted">{watch.length} saved exact IDs · {effectiveRows.filter(r=>r.identity&&watch.includes(r.identity)).length} present in this expiry. Entries from other expiries remain in your watchlist. Use Best-fit contracts to discover candidates automatically.</p>}
      {tab!=='calculator'&&<>
        <div className="ao-filters">
          <label>Search contracts<input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Strike, symbol or exact ID"/></label>
          <label>Option type<select value={side} onChange={e=>setSide(e.target.value as typeof side)}><option value="ALL">Calls + puts</option><option value="CE">CE</option><option value="PE">PE</option></select></label>
          {tab==='rank'&&<label className="ao-check"><input type="checkbox" checked={rankedOnly&&usable&&ranked.length>0} onChange={e=>setRankedOnly(e.target.checked)} disabled={!usable||!ranked.length}/>Only scenario-ranked rows</label>}
          <small>{tableRows.length} of {effectiveRows.length} returned contracts</small>
        </div>
        <Table rows={tableRows.slice(Math.min(page,Math.max(0,Math.ceil(tableRows.length/50)-1))*50,(Math.min(page,Math.max(0,Math.ceil(tableRows.length/50)-1))+1)*50)}
          cols={shownCols} selected={selected} onSelect={onSelect} sortKey={sortKey} ascending={ascending}
          onSort={k=>{if(k===sortKey)setAscending(v=>!v);else{setSortKey(k);setAscending(true)}}}/>
        <div className="ao-pagination"><button type="button" disabled={page<=0} onClick={()=>setPage(p=>p-1)}>Previous</button>
          <span>Page {Math.min(page+1,Math.max(1,Math.ceil(tableRows.length/50)))} / {Math.max(1,Math.ceil(tableRows.length/50))}</span>
          <button type="button" disabled={(page+1)*50>=tableRows.length} onClick={()=>setPage(p=>p+1)}>Next</button></div>
      </>}
      <details className="ao-assumptions"><summary>Data and model limitations <Activity size={15}/></summary>{result.warnings.map(w=><p key={w}><Check size={13}/> {w}</p>)}</details>
    </>}
    {!result&&expiry&&!error&&<p className="ao-muted">Loading source-backed analytics…</p>}
    </>}
  </section>
}
