import {useCallback,useEffect,useMemo,useState} from 'react'
import {Activity,ArrowRight,BarChart3,BookOpen,Database,Info,
  Layers3,RefreshCw,ShieldCheck,SlidersHorizontal,TrendingUp} from 'lucide-react'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
import SpreadOpportunityScanner,{type BrokerProfile} from './SpreadOpportunityScanner'
import './liquidity-spreads.css'

type PageTab='live'|'execution'|'history'|'lab'
type Row={
  identity:string;expiry:string;strike:number;option_type:'CE'|'PE'
  lot_size:number;coverage_role:string;best_bid:number|null
  best_ask:number|null;spread_inr:number|null;spread_bps:number|null
  imbalance_20:number|null;bid_quantity_20:number|null
  ask_quantity_20:number|null;top_bid_quantity:number|null
  top_ask_quantity:number|null;saved_book_received_utc:string|null
  source_book_age_seconds:number|null;recent_original_pair_age_seconds:number|null
  feed_fresh:boolean;receipt_status:string
}
type Overview={rows:Row[];filtered_selected:number
  configured_depth_contracts:number;fresh_spread_sample_size:number
  mean_fresh_spread_bps:number|null;expiry_options:string[]
  connected:boolean;market_regular_hours:boolean;source_status:string
  source:string;read_only:boolean;warning:string}
type Level={price:number;quantity:number;orders:number}
type Book={
  identity:string;received_utc:string;expiry:string;strike:number
  option_type:'CE'|'PE';lot_size:number;packet_pair_sha256:string
  bid:number;ask:number;mid:number;spread_bps:number;spread_inr:number
  imbalance_20:number;bid_quantity_20:number;ask_quantity_20:number
  top_bid_quantity:number;top_ask_quantity:number
  bid_levels?:Level[];ask_levels?:Level[]
}
type Books={identity:string;day_ist:string;count:number;books:Book[]
  more_source_records_possible:boolean;scanned_records:number
  sampled_books_not_continuous:boolean;notice:string}
type SideFill={fillable:boolean;missing_units:number;observed_units:number
  vwap:number|null;premium_turnover:number|null;levels_used:number}
type FeeLeg={brokerage:number;exchange_indicative:number;sebi:number;gst:number
  stt_sell:number;stamp_buy:number;premium_turnover:number;fees_total:number
  cash_debit?:number;cash_credit?:number}
type Fees={brokerage:number;exchange_indicative:number;sebi:number;gst:number
  stt_sell:number;stamp_buy:number;total_estimated:number
  buy_leg:FeeLeg;sell_leg:FeeLeg;broker_profile:BrokerProfile
  broker_profile_name:string
  additional_charges_excluded:boolean;assumptions:string;version:string}
type Marketable={gross_inr:number|null;fees:Fees|null
  estimated_net_inr:number|null;status:string;fills_observed:boolean}
type Passive={hypothetical_buy_at_bid:number;hypothetical_sell_at_ask:number
  gross_inr:number;fees:Fees;upper_bound_net_inr_before_unmodelled_costs:number
  after_adverse_move_stress_inr:number;adverse_move_bps_assumption:number
  top_of_book_quantity_sufficient_both_sides:boolean
  fills_observed:boolean;fill_probability:null;classification:string;caveat:string}
type ExecutionRisk={
  status:string;no_buy_fill_net_inr:number
  both_passive_fills_net_inr:number
  buy_fills_sell_misses_forced_exit_net_inr:number|null
  forced_exit_turnover_inr:number|null;premium_at_risk_inr:number
  break_even_sell_fill_probability_given_buy:number|null
  scenario_weighted_net_inr:number|null
  buy_fill_probability_assumed:number|null
  sell_fill_probability_given_buy_assumed:number|null
  probability_no_buy_fill:number|null;probability_both_fill:number|null
  probability_buy_fill_exit_fails:number|null
  adverse_move_bps_assumption:number;forced_exit_slippage_bps_assumption:number
  recorded_bid_depth_sufficient_for_liquidation:boolean
  top_book_quantity_sufficient:boolean
  fill_probabilities_calibrated:boolean
  realized_pnl_inr:null;explanation:string
}
type QuoteMarkout={horizon_seconds:number;status:string
  received_utc:string|null;elapsed_seconds:number|null
  observed_exit_bid_vwap:number|null
  quote_markout_net_if_entry_filled_inr:number|null}
type SimResult={status:string;identity:string;selected_book_received_utc:string
  future_saved_quote_markouts?:QuoteMarkout[];markout_disclaimer?:string
  assumptions?:{units:number;lots:number;lot_size:number;observed_bid:number
    observed_ask:number;spread_bps:number;marketable_buy:SideFill
    marketable_sell:SideFill;marketable_roundtrip:Marketable
    passive_capture_upper_bound:Passive;execution_risk:ExecutionRisk;read_only:boolean}
  note?:string}
type Research={identity:string;day_ist:string;lots:number
  status:string;observed_saved_books:number;observed_spread_bps_mean:number|null
  positive_optimistic_upper_bound_snapshots:number
  net_profitable_executed_trades:null;executed_trades:0;fill_rate:null
  warning:string;samples:{received_utc:string;spread_bps:number
    spread_inr:number;source_bid:number;source_ask:number
    optimistic_net_if_two_passive_fills_inr:number
    stress_net_inr:number;marketable_same_book_net_inr:number|null}[]}

const money=(n:number|null|undefined)=>typeof n==='number'&&Number.isFinite(n)
  ?'₹'+n.toLocaleString('en-IN',{maximumFractionDigits:2,minimumFractionDigits:2}):'—'
const num=(n:number|null|undefined,d=0)=>typeof n==='number'&&Number.isFinite(n)
  ?n.toLocaleString('en-IN',{maximumFractionDigits:d}):'—'
const bps=(n:number|null|undefined)=>typeof n==='number'&&Number.isFinite(n)
  ?num(n,1)+' bps':'—'
const localTime=(s:string|null|undefined)=>s?new Date(s).toLocaleString('en-IN',{
  timeZone:'Asia/Kolkata',day:'2-digit',month:'short',hour:'2-digit',
  minute:'2-digit',second:'2-digit'}):'Not received'
const todayIST=()=>new Intl.DateTimeFormat('sv-SE',{
  timeZone:'Asia/Kolkata',year:'numeric',month:'2-digit',day:'2-digit'
}).format(new Date())
const tabs:{id:PageTab;name:string;caption:string;icon:typeof Activity}[]=[
  {id:'live',name:'Live Spread Monitor',caption:'Source books & comparisons',icon:Activity},
  {id:'execution',name:'Execution Simulator',caption:'Depth-weighted cost estimates',icon:SlidersHorizontal},
  {id:'history',name:'Historical Spread Analysis',caption:'Original saved book timeline',icon:BarChart3},
  {id:'lab',name:'Spread Strategy Lab',caption:'Unexecuted research bounds',icon:TrendingUp},
]
function Metric({name,value,caption}:{name:string;value:string;caption:string}){
  return <div className="lq-metric"><span>{name}</span><strong>{value}</strong><small>{caption}</small></div>
}
function BookView({book,lots}:{book:Book;lots:number}){
  const bids=book.bid_levels||[],asks=book.ask_levels||[]
  const units=lots*book.lot_size
  return <section className="lq-book" aria-label="Original Dhan twenty level order book">
    <header className="lq-section-title"><div><strong>Original 20-level order book</strong>
      <small>{book.identity} · {localTime(book.received_utc)} IST · recorded, not a live execution quote</small>
    </div><span className="lq-chip">Source receipt</span></header>
    <div className="lq-book-header">
      <span>Best bid <b>{money(book.bid)}</b></span>
      <span>Spread <b>{money(book.spread_inr)} · {bps(book.spread_bps)}</b></span>
      <span>Best ask <b>{money(book.ask)}</b></span>
      <span>20-level imbalance <b>{num(100*book.imbalance_20,1)}%</b></span>
    </div>
    <div className="lq-scroll"><table className="lq-table lq-book-table">
      <thead><tr><th>Level</th><th>Bid ₹</th><th>Bid quantity</th>
        <th>Bid orders</th><th>Ask ₹</th><th>Ask quantity</th><th>Ask orders</th></tr></thead>
      <tbody>{Array.from({length:20},(_,i)=><tr key={i}>
        <td>{i+1}</td><td className="bid">{money(bids[i]?.price)}</td>
        <td>{num(bids[i]?.quantity)}</td><td>{num(bids[i]?.orders)}</td>
        <td className="ask">{money(asks[i]?.price)}</td>
        <td>{num(asks[i]?.quantity)}</td><td>{num(asks[i]?.orders)}</td>
      </tr>)}</tbody></table></div>
    <p className="lq-hint">Selected order size: {num(units)} units. Original book quantities are
      visible liquidity at one local receive timestamp; queue position, cancellations,
      and fills are not observed.</p>
  </section>
}
type Series={name:string;books:Book[]}
function SpreadChart({series}:{series:Series[]}){
  const combined=series.flatMap(s=>s.books)
  const [hover,setHover]=useState<{name:string;time:string;spread:number}|null>(null)
  if(combined.length<2)return <p className="lq-empty">
    At least two saved original book samples are required for a spread history chart.
  </p>
  const width=920,height=270,padL=58,padR=20,padTop=20,padBottom=36
  const times=combined.map(x=>new Date(x.received_utc).getTime())
  const first=Math.min(...times),last=Math.max(...times)
  const spreads=combined.map(x=>x.spread_bps)
  const min=Math.min(...spreads,0),max=Math.max(...spreads,1)
  const low=Math.max(0,min-(max-min)*.07),high=max+(max-min)*.09
  const x=(s:string)=>padL+(new Date(s).getTime()-first)/Math.max(1,last-first)*
    (width-padL-padR)
  const y=(v:number)=>padTop+(high-v)/Math.max(.01,high-low)*
    (height-padTop-padBottom)
  const colors=['#67e2bd','#e6af70','#82baff']
  return <div className="lq-chart"><div className="lq-chart-head">
    <span>Observed bid–ask spread (bps)</span>
    <span>{hover?hover.name+' · '+localTime(hover.time)+' · '+bps(hover.spread):
      'Hover an actual saved observation'}</span>
  </div><svg viewBox="0 0 920 270" role="img"
    aria-label="Source-received option spread chart with actual observed timestamps">
    {[0,.25,.5,.75,1].map(i=><g key={i}>
      <line x1={padL} x2={width-padR} y1={y(low+(high-low)*i)}
        y2={y(low+(high-low)*i)} stroke="#30556b" strokeDasharray="3 5"/>
      <text x="6" y={y(low+(high-low)*i)+4} fill="#9bc5d2" fontSize="12">
        {num(low+(high-low)*i,0)}
      </text></g>)}
    {series.map((s,index)=>{
      const points=s.books.filter(v=>Number.isFinite(v.spread_bps))
      return <g key={s.name}>
        {points.length>1&&<polyline fill="none" stroke={colors[index%colors.length]}
          strokeWidth="2.3" strokeLinejoin="round"
          points={points.map(p=>x(p.received_utc)+','+y(p.spread_bps)).join(' ')}/>}
        {points.map((p,j)=><circle key={p.received_utc+String(j)}
          cx={x(p.received_utc)} cy={y(p.spread_bps)} r="3.5"
          fill={colors[index%colors.length]} tabIndex={0}
          onMouseEnter={()=>setHover({name:s.name,time:p.received_utc,spread:p.spread_bps})}
          onFocus={()=>setHover({name:s.name,time:p.received_utc,spread:p.spread_bps})}>
          <title>{s.name+' · '+localTime(p.received_utc)+' · '+bps(p.spread_bps)}</title>
        </circle>)}
      </g>})}
    <text x={padL} y="260" fill="#9bc5d2" fontSize="12">
      {localTime(new Date(first).toISOString())}</text>
    <text x={width-210} y="260" fill="#9bc5d2" fontSize="12">
      {localTime(new Date(last).toISOString())}</text>
  </svg><div className="lq-legend">{series.map((s,i)=><span key={s.name}>
    <i style={{backgroundColor:colors[i%colors.length]}}/>
    {s.name} · {num(s.books.length)} saved samples</span>)}</div></div>
}
export default function LiquiditySpreadsWorkspace({onOpenRecording,onOpenReplay}:{
  onOpenRecording:()=>void;onOpenReplay:()=>void
}){
  const [tab,setTab]=useState<PageTab>('live')
  const [overview,setOverview]=useState<Overview|null>(null)
  const [error,setError]=useState('')
  const [loading,setLoading]=useState(true)
  const [expiry,setExpiry]=useState('')
  const [side,setSide]=useState<'ALL'|'CE'|'PE'>('ALL')
  const [search,setSearch]=useState('')
  const [selected,setSelected]=useState('')
  const [compare,setCompare]=useState('')
  const [day,setDay]=useState(todayIST)
  const [bookList,setBookList]=useState<Books|null>(null)
  const [compareList,setCompareList]=useState<Books|null>(null)
  const [bookBusy,setBookBusy]=useState(false)
  const [bookIndex,setBookIndex]=useState(-1)
  const [lots,setLots]=useState(3)
  const [orders,setOrders]=useState(1)
  const [brokerage,setBrokerage]=useState(20)
  const [brokerProfile,setBrokerProfile]=useState<BrokerProfile>('zerodha')
  const changeBroker=useCallback((profile:BrokerProfile)=>{
    setBrokerProfile(profile)
    setBrokerage(profile==='zerodha_debit_balance'?40:20)
    setSim(null);setResearch(null)
  },[])
  const [adverseBps,setAdverseBps]=useState(25)
  const [exitSlippage,setExitSlippage]=useState(10)
  const [assumeFills,setAssumeFills]=useState(false)
  const [buyProbability,setBuyProbability]=useState(50)
  const [sellProbability,setSellProbability]=useState(50)
  const [sim,setSim]=useState<SimResult|null>(null)
  const [research,setResearch]=useState<Research|null>(null)
  const [running,setRunning]=useState(false)
  const refresh=useCallback(async()=>{
    try{
      const res=await marketApi<Overview>('/api/trading-cockpit/liquidity/overview?limit=200')
      setOverview(res);setError('')
      if(!selected&&res.rows.length)setSelected(res.rows.find(x=>x.best_bid!=null)?.identity||res.rows[0].identity)
    }catch(e){setError(readableError(e))}
    finally{setLoading(false)}
  },[selected])
  useEffect(()=>{
    void refresh()
    const timer=window.setInterval(()=>{if(!document.hidden)void refresh()},8500)
    return()=>window.clearInterval(timer)
  },[refresh])
  useEffect(()=>{
    if(!selected){setBookList(null);return}
    let cancelled=false
    setBookBusy(true);setSim(null);setResearch(null)
    void marketApi<Books>('/api/trading-cockpit/liquidity/history?'+
      new URLSearchParams({identity:selected,day,limit:'300',levels:'true'}))
      .then(value=>{if(!cancelled){setBookList(value);setBookIndex(-1)}})
      .catch(e=>{if(!cancelled){setBookList(null);setError(readableError(e))}})
      .finally(()=>{if(!cancelled)setBookBusy(false)})
    return()=>{cancelled=true}
  },[selected,day])
  useEffect(()=>{
    if(!compare){setCompareList(null);return}
    let cancelled=false
    void marketApi<Books>('/api/trading-cockpit/liquidity/history?'+
      new URLSearchParams({identity:compare,day,limit:'300',levels:'false'}))
      .then(data=>{if(!cancelled)setCompareList(data)})
      .catch(()=>{if(!cancelled)setCompareList(null)})
    return()=>{cancelled=true}
  },[compare,day])
  const filtered=useMemo(()=>overview?.rows.filter(r=>
    (!expiry||r.expiry===expiry)&&
    (side==='ALL'||r.option_type===side)&&
    (!search||[r.identity,r.expiry,String(r.strike),r.option_type].join(' ')
      .toLowerCase().includes(search.toLowerCase()))
  )||[],[overview,expiry,side,search])
  const activeBooks=bookList?.books||[]
  const current=bookIndex<0?activeBooks[activeBooks.length-1]:activeBooks[bookIndex]
  const selectedRow=overview?.rows.find(r=>r.identity===selected)
  const choose=(identity:string)=>{setSelected(identity);setTab('live')}
  const runSimulation=async()=>{
    if(!selected)return
    setRunning(true);setError('');setSim(null)
    try{
      setSim(await marketPost<SimResult>(
        '/api/trading-cockpit/liquidity/simulate',{
          identity:selected,lots,day,
          ...(current?{received_utc:current.received_utc}:{}),
          executed_orders_per_side:orders,
          brokerage_inr:brokerage,adverse_move_bps:adverseBps,
          broker_profile:brokerProfile,exit_slippage_bps:exitSlippage,
          ...(assumeFills?{
            buy_fill_probability:buyProbability/100,
            sell_fill_probability_given_buy:sellProbability/100,
          }:{}),
        }))
    }catch(e){setError(readableError(e))}
    finally{setRunning(false)}
  }
  const runResearch=async()=>{
    if(!selected)return
    setRunning(true);setError('');setResearch(null)
    try{
      setResearch(await marketApi<Research>(
        '/api/trading-cockpit/liquidity/research?'+
        new URLSearchParams({identity:selected,day,
          lots:String(lots),adverse_move_bps:String(adverseBps),limit:'300',
          broker_profile:brokerProfile})))
    }catch(e){setError(readableError(e))}
    finally{setRunning(false)}
  }
  return <section className="lq-workspace" aria-label="Liquidity and Spreads research workstation">
    <div className="lq-intro">
      <div><span className="lq-eyebrow">DHAN ONLY · BANKNIFTY MARKET MICROSTRUCTURE</span>
        <h2>Liquidity &amp; Spreads</h2>
        <p>One research home for actual option spreads, original 20-level books,
          execution costs and unexecuted passive spread scenarios.</p></div>
      <div className="lq-actions">
        <span className={'lq-status '+(overview?.connected?'online':'offline')}>
          <Activity size={15}/>{overview?.connected?'Dhan depth connected':'Saved-data mode'}
        </span>
        <button type="button" onClick={()=>void refresh()}><RefreshCw size={15}/> Refresh</button>
      </div>
    </div>
    <div className="lq-disclaimer"><ShieldCheck size={16}/>
      <span><strong>Research only — no orders sent.</strong> Bid/ask books are saved original Dhan
        observations, not executable commitments. Passive order fills, queue priority
        and realized P&amp;L are unknown. The source clock is local receive time.</span>
    </div>
    <nav className="lq-tabs" role="tablist" aria-label="Liquidity & Spreads modules">
      {tabs.map(t=><button type="button" key={t.id} role="tab"
        aria-selected={tab===t.id} className={tab===t.id?'active':''}
        onClick={()=>setTab(t.id)}><t.icon size={18}/>
        <span><strong>{t.name}</strong><small>{t.caption}</small></span></button>)}
    </nav>
    {error&&<div className="lq-alert" role="alert">{error}</div>}
    {loading&&<p className="lq-muted" role="status">Reading local original Dhan market evidence…</p>}
    <div className="lq-metrics">
      <Metric name="Selected depth subscriptions"
        value={num(overview?.configured_depth_contracts)}
        caption="Dhan IDs, not all-option universe"/>
      <Metric name="Source-fresh saved prices"
        value={num(overview?.fresh_spread_sample_size)}
        caption="Recent pairs; older bid/ask may be sampled"/>
      <Metric name="Mean fresh quoted spread"
        value={bps(overview?.mean_fresh_spread_bps)}
        caption="Only source-fresh selected contracts"/>
      <Metric name="Live source"
        value={overview?.market_regular_hours?'NSE session':'Market closed'}
        caption={overview?.source_status||'Local archive only'}/>
    </div>
    <div className="lq-controls">
      <label>Expiry<select value={expiry} onChange={e=>setExpiry(e.target.value)}>
        <option value="">All selected expiries</option>
        {overview?.expiry_options.map(x=><option key={x} value={x}>{x}</option>)}
      </select></label>
      <label>Option side<select value={side} onChange={e=>setSide(e.target.value as typeof side)}>
        <option value="ALL">CE + PE</option><option value="CE">CE</option>
        <option value="PE">PE</option></select></label>
      <label>Search strike / source ID<input value={search}
        onChange={e=>setSearch(e.target.value)} placeholder="e.g. 63400 or 62539"/></label>
      <label>Original trading date (IST)<input type="date" value={day}
        onChange={e=>setDay(e.target.value)}/></label>
    </div>
    {tab==='live'&&<div className="lq-section" role="tabpanel" aria-label="Live Spread Monitor">
      <SpreadOpportunityScanner day={day} expiry={expiry} side={side}
        search={search} brokerProfile={brokerProfile}
        onBrokerProfileChange={changeBroker}
        onInspect={(identity,chosenLots,profile)=>{
          setSelected(identity)
          setLots(chosenLots)
          changeBroker(profile)
          setBookList(null);setBookIndex(-1);setTab('execution')
        }}/>
      <div className="lq-section-title"><div><strong>Source-backed bid / ask watchlist</strong>
        <small>{num(filtered.length)} selected contracts. Latest *saved* depth may lag
          current source packets; stale rows are always identified.</small></div>
        <button type="button" onClick={onOpenRecording}>
          Recording settings <ArrowRight size={14}/></button></div>
      <div className="lq-scroll">
        <table className="lq-table lq-watchlist"><thead><tr>
          <th>Contract</th><th>Strike</th><th>Best bid</th><th>Best ask</th>
          <th>Spread ₹</th><th>Spread bps</th><th>Top bid / ask qty</th>
          <th>20-level imbalance</th><th>Freshness</th><th>Depth role</th><th/>
        </tr></thead><tbody>
        {filtered.map(r=><tr key={r.identity}
          className={selected===r.identity?'selected':''}
          onClick={()=>setSelected(r.identity)}>
          <td><span className={'lq-side '+r.option_type}>{r.option_type}</span>
            {' '}{r.expiry}<small>{r.identity}</small></td>
          <td>{num(r.strike)}</td><td className="bid">{money(r.best_bid)}</td>
          <td className="ask">{money(r.best_ask)}</td>
          <td>{money(r.spread_inr)}</td>
          <td><b>{bps(r.spread_bps)}</b></td>
          <td>{num(r.top_bid_quantity)} / {num(r.top_ask_quantity)}</td>
          <td>{r.imbalance_20==null?'—':num(r.imbalance_20*100,1)+'%'}</td>
          <td><span className={'lq-indicator '+(r.feed_fresh?'fresh':'stale')}>
            {r.feed_fresh?'Recent Dhan pair':'Stale / no pair'}</span>
            <small>{r.source_book_age_seconds==null?'No saved book':
              num(r.source_book_age_seconds,0)+'s saved-book age'}</small></td>
          <td>{r.coverage_role}</td>
          <td><button type="button" onClick={event=>{
            event.stopPropagation();choose(r.identity)}}>Inspect</button></td>
        </tr>)}
        {!filtered.length&&<tr><td colSpan={11}>No qualifying selected Dhan
          depth contracts. Use Automatic Recording to collect original books;
          no data is simulated.</td></tr>}
        </tbody></table>
      </div>
      <div className="lq-split">
        <div className="lq-panel">
          <div className="lq-section-title"><div><strong>Inspect selected source contract</strong>
            <small>{selected||'Select a CE/PE above'}</small></div>
          </div>
          <p className="lq-hint">Expiry {selectedRow?.expiry||'—'} ·
            {' '}{selectedRow?.option_type||'—'} {num(selectedRow?.strike)} ·
            {' '}{num(selectedRow?.lot_size)} units per lot</p>
          <div className="lq-fieldrow">
            <button type="button" onClick={()=>setTab('execution')}>
              Execution costs <ArrowRight size={14}/></button>
            <button type="button" onClick={()=>setTab('history')}>
              Source history <ArrowRight size={14}/></button>
          </div>
          {bookBusy&&<p className="lq-muted">Loading saved original books…</p>}
          {!bookBusy&&!current&&<p className="lq-empty">No saved 20-level book
            for this contract on {day}. A Quote/OI subscription cannot substitute
            for an original bid/ask book.</p>}
          {current&&<div className="lq-quick">
            <Metric name="Latest saved bid" value={money(current.bid)}
              caption={localTime(current.received_utc)}/>
            <Metric name="Latest saved ask" value={money(current.ask)}
              caption={bps(current.spread_bps)}/>
          </div>}
        </div>
        <div className="lq-panel">
          <div className="lq-section-title"><div><strong>Compare two contracts</strong>
            <small>Different source timestamps are not synchronized executions.</small>
          </div></div>
          <label className="lq-label">Compare against another original depth ID
            <select value={compare} onChange={e=>setCompare(e.target.value)}>
              <option value="">Choose comparison</option>
              {filtered.filter(r=>r.identity!==selected&&r.best_bid!=null)
                .map(r=><option key={r.identity} value={r.identity}>
                  {r.option_type} {num(r.strike)} · {r.expiry} · {r.identity}
                </option>)}
            </select></label>
          <div className="lq-compare">
            <div><span>Selected</span><strong>{bps(current?.spread_bps)}</strong>
              <small>{current?localTime(current.received_utc):'No source book'}</small></div>
            <div><span>Compared</span><strong>{bps(compareList?.books.at(-1)?.spread_bps)}</strong>
              <small>{compareList?.books.length?
                localTime(compareList.books.at(-1)?.received_utc):
                'Choose another contract'}</small></div>
          </div>
          <p className="lq-hint">Comparisons are observational; different strikes
            can have very different liquidity and execution risk.</p>
        </div>
      </div>
      {current&&<BookView book={current} lots={lots}/>}
    </div>}
    {tab==='execution'&&<section className="lq-section" role="tabpanel"
      aria-label="Execution Simulator">
      <div className="lq-section-title"><div><strong>Execution cost workbench</strong>
        <small>Walk actual saved 20-level asks for an illustrative buy and
          bids for an illustrative sell; model both legs at one source time.</small>
      </div></div>
      <div className="lq-form">
        <label>Selected source contract<select value={selected}
          onChange={e=>setSelected(e.target.value)}>
          {selected&&!overview?.rows.some(r=>r.identity===selected)&&
            <option value={selected}>Saved depth {selected}</option>}
          {overview?.rows.map(r=><option key={r.identity} value={r.identity}>
            {r.option_type} {num(r.strike)} · {r.expiry} · {r.identity}
          </option>)}</select></label>
        <label>Lots (1–10)<input type="number" min="1" max="10" value={lots}
          onChange={e=>setLots(Math.max(1,Math.min(10,Number(e.target.value)||1)))}/></label>
        <label>Executed orders per side<input type="number" min="1" max="20"
          value={orders} onChange={e=>setOrders(Math.max(1,
            Math.min(20,Number(e.target.value)||1)))}/></label>
        <label>Broker charges<select value={brokerProfile}
          onChange={e=>changeBroker(e.target.value as BrokerProfile)}>
          <option value="zerodha">Zerodha regular retail</option>
          <option value="zerodha_debit_balance">Zerodha special ₹40/order</option>
          <option value="dhan">Dhan retail</option>
        </select></label>
        <label>Brokerage ₹/executed order<input type="number" min="0" max="1000"
          value={brokerage} onChange={e=>setBrokerage(Math.max(0,
            Math.min(1000,Number(e.target.value)||0)))}/></label>
        <label>Adverse selection stress (bps)<input type="number" min="0" max="1000"
          value={adverseBps} onChange={e=>setAdverseBps(Math.max(0,
            Math.min(1000,Number(e.target.value)||0)))}/></label>
        <label>Forced-exit slippage (bps)<input type="number" min="0" max="1000"
          value={exitSlippage} onChange={e=>setExitSlippage(Math.max(0,
            Math.min(1000,Number(e.target.value)||0)))}/></label>
        <label>Assume fill probabilities?
          <select value={assumeFills?'yes':'no'}
            onChange={e=>setAssumeFills(e.target.value==='yes')}>
            <option value="no">No — unknown (recommended)</option>
            <option value="yes">Yes — hypothetical sensitivity only</option>
          </select>
        </label>
        {assumeFills&&<>
          <label>Assumed buy-fill chance (%)<input type="number" min="0" max="100"
            value={buyProbability} onChange={e=>setBuyProbability(Math.max(0,
              Math.min(100,Number(e.target.value)||0)))}/></label>
          <label>Assumed sell-fill given buy (%)<input type="number" min="0" max="100"
            value={sellProbability} onChange={e=>setSellProbability(Math.max(0,
              Math.min(100,Number(e.target.value)||0)))}/></label>
        </>}
        <label>Original saved book<select value={current?.received_utc||''}
          onChange={e=>setBookIndex(activeBooks.findIndex(
            b=>b.received_utc===e.target.value))}>
          {activeBooks.length===0?<option value="">No source book</option>:
            activeBooks.slice(-150).map(b=><option key={b.received_utc}
              value={b.received_utc}>{localTime(b.received_utc)} · {bps(b.spread_bps)}</option>)}
        </select></label>
      </div>
      <div className="lq-fieldrow">
        <button type="button" disabled={!selected||!current||running}
          onClick={()=>void runSimulation()}>
          <SlidersHorizontal size={16}/> {running?'Calculating…':'Estimate from original book'}
        </button>
        <span className="lq-hint">Calculation only. No orders, fills or historical trades created.</span>
      </div>
      {sim?.assumptions&&<div className="lq-sim">
        <div className="lq-results">
          <Metric name="Buy marketably at asks"
            value={money(sim.assumptions.marketable_buy.vwap)}
            caption={sim.assumptions.marketable_buy.fillable?
              num(sim.assumptions.marketable_buy.levels_used)+' original levels':
              'Insufficient source ask quantity'}/>
          <Metric name="Sell marketably at bids"
            value={money(sim.assumptions.marketable_sell.vwap)}
            caption={sim.assumptions.marketable_sell.fillable?
              num(sim.assumptions.marketable_sell.levels_used)+' original levels':
              'Insufficient source bid quantity'}/>
          <Metric name="Marketable same-book net"
            value={money(sim.assumptions.marketable_roundtrip.estimated_net_inr)}
            caption="Counterfactual, never an actual roundtrip"/>
          <Metric name="Passive upper-bound net"
            value={money(sim.assumptions.passive_capture_upper_bound.upper_bound_net_inr_before_unmodelled_costs)}
            caption="Assumes both limit orders fill, unverified"/>
          <Metric name={'Upper bound after '+num(adverseBps)+' bps stress'}
            value={money(sim.assumptions.passive_capture_upper_bound.after_adverse_move_stress_inr)}
            caption="Assumed adverse movement; not observed P&L"/>
          <Metric name="Order size" value={num(sim.assumptions.units)+' units'}
            caption={num(sim.assumptions.lot_size)+' / lot · '+num(lots)+' lot(s)'}/>
        </div>
        <section className="lq-risk-panel" aria-label="Execution and missed-exit risk">
          <div><strong>Execution outcome paths</strong><small>
            No probabilities inferred from a static order book.
            Conditional estimates include estimated {brokerProfile} charges.</small></div>
          <div className="lq-results">
            <Metric name="Buy never fills" value={money(sim.assumptions.execution_risk.no_buy_fill_net_inr)}
              caption="₹0 assumes unfilled orders are canceled without fees"/>
            <Metric name="Buy and sell both fill" value={money(
              sim.assumptions.execution_risk.both_passive_fills_net_inr)}
              caption="Best-quote conditional estimate, not expected profit"/>
            <Metric name="Buy fills, sell misses" value={money(
              sim.assumptions.execution_risk.buy_fills_sell_misses_forced_exit_net_inr)}
              caption="Forced bid exit with adverse move and slippage; same-book stress"/>
            <Metric name="Long-option premium at risk" value={money(
              sim.assumptions.execution_risk.premium_at_risk_inr)}
              caption="Entry cash debit, not a stop-loss or maximum total exposure"/>
            <Metric name="Break-even conditional sell fill" value={
              sim.assumptions.execution_risk.break_even_sell_fill_probability_given_buy===null
                ?'Unavailable':num(
                  sim.assumptions.execution_risk.break_even_sell_fill_probability_given_buy*100,1)+'%'}
              caption="Required given buy filled, for this two-outcome model"/>
            <Metric name="Scenario-weighted net (user assumptions)" value={
              money(sim.assumptions.execution_risk.scenario_weighted_net_inr)}
              caption={assumeFills?'Not calibrated — not a profit forecast':
                'Fill rates unknown; no expected P&L calculated'}/>
          </div>
          {sim.assumptions.execution_risk.status!=='USER_ASSUMPTIONS_ONLY_NOT_CALIBRATED'&&
            <p className="lq-alert" role="status">
              {sim.assumptions.execution_risk.status.replaceAll('_',' ')}.
              We cannot classify this contract as profitable without verified fills
              and a calibrated execution model.</p>}
          <p className="lq-hint">{sim.assumptions.execution_risk.explanation}</p>
          <div className="lq-section-title"><strong>Saved-quote future markouts</strong></div>
          <div className="lq-results">
            {(sim.future_saved_quote_markouts||[]).map(mark=>
              <Metric key={mark.horizon_seconds}
                name={num(mark.horizon_seconds)+'s later bid exit quote'}
                value={money(mark.quote_markout_net_if_entry_filled_inr)}
                caption={mark.status==='FUTURE_SAVED_QUOTE_ONLY'?
                  'Quote only · '+localTime(mark.received_utc):
                  mark.status.replaceAll('_',' ')}/>)}
          </div>
          <p className="lq-hint">{sim.markout_disclaimer}</p>
        </section>
        {!sim.assumptions.passive_capture_upper_bound.top_of_book_quantity_sufficient_both_sides&&
          <p className="lq-alert" role="status">Top-of-book displayed quantity is insufficient
            for this lot count on at least one side. Passive spread capture
            at the best quoted prices is especially optimistic.</p>}
        <div className="lq-fees">
          <div><strong>Illustrative round-trip cost components</strong>
            <small>At hypothetical passive best-quote prices · broker charges may differ</small></div>
          {Object.entries(sim.assumptions.passive_capture_upper_bound.fees)
            .filter(([k])=>['brokerage','exchange_indicative','sebi','gst',
              'stt_sell','stamp_buy','total_estimated'].includes(k))
            .map(([k,v])=><div key={k}><span>{k.replaceAll('_',' ')}</span>
              <strong>{money(Number(v))}</strong></div>)}
        </div>
        <details className="lq-transaction-ledger">
          <summary>Estimated transaction-by-transaction cash movements · {brokerProfile}</summary>
          <div className="lq-transaction-grid">
            <div><strong>1 · Hypothetical buy at bid</strong>
              <span>Premium paid: {money(sim.assumptions.passive_capture_upper_bound.fees.buy_leg.premium_turnover)}</span>
              <span>Brokerage: {money(sim.assumptions.passive_capture_upper_bound.fees.buy_leg.brokerage)}</span>
              <span>Exchange + SEBI: {money(
                sim.assumptions.passive_capture_upper_bound.fees.buy_leg.exchange_indicative+
                sim.assumptions.passive_capture_upper_bound.fees.buy_leg.sebi)}</span>
              <span>GST: {money(sim.assumptions.passive_capture_upper_bound.fees.buy_leg.gst)}</span>
              <span>Stamp duty: {money(sim.assumptions.passive_capture_upper_bound.fees.buy_leg.stamp_buy)}</span>
              <strong>Total cash debit: {money(
                sim.assumptions.passive_capture_upper_bound.fees.buy_leg.cash_debit)}</strong>
            </div>
            <div><strong>2 · Hypothetical sell at ask</strong>
              <span>Premium proceeds: {money(sim.assumptions.passive_capture_upper_bound.fees.sell_leg.premium_turnover)}</span>
              <span>Brokerage: {money(sim.assumptions.passive_capture_upper_bound.fees.sell_leg.brokerage)}</span>
              <span>Exchange + SEBI: {money(
                sim.assumptions.passive_capture_upper_bound.fees.sell_leg.exchange_indicative+
                sim.assumptions.passive_capture_upper_bound.fees.sell_leg.sebi)}</span>
              <span>GST: {money(sim.assumptions.passive_capture_upper_bound.fees.sell_leg.gst)}</span>
              <span>STT: {money(sim.assumptions.passive_capture_upper_bound.fees.sell_leg.stt_sell)}</span>
              <strong>Net cash credit: {money(
                sim.assumptions.passive_capture_upper_bound.fees.sell_leg.cash_credit)}</strong>
            </div>
          </div>
          <p>Net after both *hypothetical* fills: {
            money(sim.assumptions.passive_capture_upper_bound.upper_bound_net_inr_before_unmodelled_costs)
          }. Marketable orders instead pay the ask and receive the bid; see
            the marketable net above. Neither scenario is a real Zerodha
            contract note or confirmed execution.</p>
        </details>
        <p className="lq-disclaimer">{sim.assumptions.passive_capture_upper_bound.caveat}
          {' '}{sim.assumptions.passive_capture_upper_bound.fees.assumptions}</p>
      </div>}
      {sim&&!sim.assumptions&&<p className="lq-empty">{sim.note||sim.status}</p>}
      {current&&<BookView book={current} lots={lots}/>}
    </section>}
    {tab==='history'&&<section className="lq-section" role="tabpanel"
      aria-label="Historical Spread Analysis">
      <div className="lq-section-title"><div><strong>Original market-depth spread timeline</strong>
        <small>Saved snapshots on {day}; not a tick-complete historical tape.
          You can inspect individual original receive times.</small></div>
        <button type="button" onClick={onOpenReplay}>Open Market Replay <ArrowRight size={14}/></button>
      </div>
      <div className="lq-history-metrics">
        <Metric name="Saved original books" value={num(activeBooks.length)}
          caption={bookList?.more_source_records_possible?'Limited 300-book window':
            'Within requested scan window'}/>
        <Metric name="Latest saved spread" value={bps(activeBooks.at(-1)?.spread_bps)}
          caption={localTime(activeBooks.at(-1)?.received_utc)}/>
        <Metric name="Original data cadence" value="Sampled"
          caption="Recorder does not preserve every book update"/>
      </div>
      <SpreadChart series={[
        {name:selected||'Selected option',books:activeBooks},
        ...(compareList?.books.length?[{name:compare,books:compareList.books}]:[]),
      ]}/>
      <div className="lq-fieldrow"><label>Overlay saved spread from another CE/PE
        <select value={compare} onChange={e=>setCompare(e.target.value)}>
          <option value="">No comparison</option>
          {overview?.rows.filter(r=>r.identity!==selected).map(r=>
            <option key={r.identity} value={r.identity}>
              {r.option_type} {num(r.strike)} · {r.expiry}
            </option>)}
        </select></label></div>
      <div className="lq-scroll"><table className="lq-table">
        <thead><tr><th>Original saved time (IST)</th><th>Bid</th><th>Ask</th>
          <th>Spread ₹</th><th>Spread bps</th><th>20-level imbalance</th><th></th></tr></thead>
        <tbody>{activeBooks.slice().reverse().slice(0,45).map(b=>
          <tr key={b.received_utc}><td>{localTime(b.received_utc)}</td>
            <td className="bid">{money(b.bid)}</td>
            <td className="ask">{money(b.ask)}</td>
            <td>{money(b.spread_inr)}</td><td>{bps(b.spread_bps)}</td>
            <td>{num(b.imbalance_20*100,1)}%</td>
            <td><button type="button" onClick={()=>{setBookIndex(activeBooks.indexOf(b));
              setTab('live')}}>View book</button></td>
          </tr>)}
          {!activeBooks.length&&<tr><td colSpan={7}>No original 20-level
            history for this date and ID. Missing periods are not interpolated.</td></tr>}
        </tbody></table></div>
      <p className="lq-hint">{bookList?.notice||'Choose a contract to inspect original saved depth.'}</p>
    </section>}
    {tab==='lab'&&<section className="lq-section" role="tabpanel"
      aria-label="Spread Strategy Lab">
      <div className="lq-section-title"><div><strong>Spread strategy research · upper-bound explorer</strong>
        <small>Compare passive best-quote optimism with marketable
          cost and adverse-selection stress at source-observed snapshots.</small>
      </div></div>
      <div className="lq-disclaimer"><Info size={17}/>
        <span><strong>Not a filled-order backtest.</strong> Without original order
          acknowledgments or queue position, we cannot estimate actual fill
          probability, Sharpe, realized P&amp;L, or a winning strategy.
          The lab deliberately reports those metrics as unavailable.</span>
      </div>
      <div className="lq-form">
        <label>Broker fees<select value={brokerProfile}
          onChange={e=>changeBroker(e.target.value as BrokerProfile)}>
          <option value="zerodha">Zerodha standard</option>
          <option value="zerodha_debit_balance">Zerodha special ₹40/order</option>
          <option value="dhan">Dhan</option>
        </select></label>
        <label>Lots<input type="number" min="1" max="10" value={lots}
          onChange={e=>setLots(Math.max(1,Math.min(10,Number(e.target.value)||1)))}/></label>
        <label>Adverse price move stress (bps)<input type="number" min="0" max="1000"
          value={adverseBps} onChange={e=>setAdverseBps(Math.max(0,
            Math.min(1000,Number(e.target.value)||0)))}/></label>
        <div className="lq-run"><button type="button" disabled={!selected||running}
          onClick={()=>void runResearch()}><Layers3 size={16}/>
          {running?'Analyzing…':'Analyze original saved books'}</button></div>
      </div>
      {research&&<>
        <div className="lq-results">
          <Metric name="Observed original samples"
            value={num(research.observed_saved_books)}
            caption="Independent book receipts, not independent trades"/>
          <Metric name="Average quoted spread"
            value={bps(research.observed_spread_bps_mean)}
            caption="Source-observed, not captured profit"/>
          <Metric name="Positive optimistic upper bounds"
            value={num(research.positive_optimistic_upper_bound_snapshots)}
            caption="Only with two hypothetical passive fills"/>
          <Metric name="Verified realized P&L" value="Not available"
            caption="No actual execution evidence exists"/>
        </div>
        <div className="lq-alert" role="status">{research.warning}</div>
        <div className="lq-scroll"><table className="lq-table">
          <thead><tr><th>Source book time</th><th>Observed spread</th>
            <th>Marketable net estimate</th>
            <th>Best-quote passive upper net</th>
            <th>After adverse stress</th><th>Real fills?</th></tr></thead>
          <tbody>{research.samples.slice().reverse().slice(0,70).map((r,i)=>
            <tr key={r.received_utc+String(i)}>
              <td>{localTime(r.received_utc)}</td>
              <td>{bps(r.spread_bps)}</td>
              <td>{money(r.marketable_same_book_net_inr)}</td>
              <td>{money(r.optimistic_net_if_two_passive_fills_inr)}</td>
              <td>{money(r.stress_net_inr)}</td><td>Not observed</td>
            </tr>)}</tbody></table></div>
      </>}
      {!research&&<div className="lq-step">
        <BookOpen size={22}/><div><strong>Research workflow</strong>
          <p>Select a source contract and date, choose size and stress, then
            examine fee-adjusted snapshot bounds. Queue-aware fill modeling,
            holdings/inventory risk and true out-of-sample P&amp;L require
            further independent validation—none are silently assumed.</p></div>
      </div>}
    </section>}
    <footer className="lq-footer">
      <span><Database size={14}/> Existing Dhan shared market library · no separate datasets</span>
      <span><ShieldCheck size={14}/> Research-only · original source receipts · no broker execution</span>
    </footer>
  </section>
}
