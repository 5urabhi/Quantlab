import {useCallback,useEffect,useMemo,useState} from 'react'
import {ArrowDownUp,ArrowRight,RefreshCw,ShieldAlert} from 'lucide-react'
import {marketApi,readableError} from './tradingCockpitApi'
import SpreadExecutionDecision,{type ExecutionDecision} from './SpreadExecutionDecision'
import './spread-opportunity-scanner.css'

export type BrokerProfile='zerodha'|'zerodha_debit_balance'|'dhan'
type LotOutcome={
  lots:number;units:number;capital_required_inr:number
  within_budget:boolean;marketable_full_depth:boolean
  top_of_book_both_sides_sufficient:boolean
  hypothetical_buy_cash_debit_inr:number;hypothetical_sell_cash_credit_inr:number
  buy_fees_inr:number;sell_fees_inr:number;total_fees_inr:number
  passive_gross_inr:number;passive_upper_net_inr:number
  passive_stressed_upper_net_inr:number;marketable_net_inr:number|null
  failed_exit_net_inr?:number|null;break_even_exit_fill_probability?:number|null
  half_premium_exit_net_inr?:number|null
  loss_if_option_worthless_inr?:number|null
  sell_fill_hurdle_if_zero_recovery?:number|null
  marketable_buy_cash_debit_inr:number|null
  marketable_sell_cash_credit_inr:number|null
  marketable_buy_fees_inr:number|null
  marketable_sell_fees_inr:number|null
}
type Candidate={
  identity:string;expiry:string|null;strike:number|null;option_type:string|null
  lot_size:number;received_utc:string;saved_book_age_seconds:number
  fresh_original_saved_book:boolean;best_bid:number;best_ask:number
  spread_inr:number;spread_bps:number
  top_bid_quantity:number;top_ask_quantity:number
  bid_quantity_20:number;ask_quantity_20:number
  best_hypothetical_lots:number|null;tested_lot_count:number
  required_capital_inr:number|null
  passive_upper_net_inr:number|null
  passive_stressed_upper_net_inr:number|null;marketable_net_inr:number|null
  estimated_buy_fees_inr:number|null;estimated_sell_fees_inr:number|null
  estimated_total_fees_inr:number|null
  risk_screen_score?:number|null;source_fresh_risk_screened?:boolean
  break_even_sell_fill_given_buy?:number|null;failed_exit_net_inr?:number|null
  risk_screen_reason?:string
  loss_if_option_worthless_inr?:number|null
  half_premium_exit_net_inr?:number|null
  conservative_sell_fill_hurdle?:number|null
  feasibility?:{paper_research_qualified:boolean;reasons:string[]
    status:string;loss_if_option_worthless_inr:number|null
    conservative_sell_fill_hurdle_if_zero_recovery:number|null
    receipt_evidence?:{packet_receipts_120s:number;distinct_packet_pairs_120s:number
      receipt_span_seconds:number}}
  lot_scenarios:LotOutcome[]
  classification:string;two_passive_fills_observed:false
  actual_executed_orders:0;actual_profit_inr:null
}
type Scan={
  day_ist:string;broker_profile:BrokerProfile;broker_profile_name:string
  capital_inr:number;max_lots:number;executed_orders_per_side:number
  adverse_move_bps:number
  original_depth_contracts_found:number;source_scan_truncated:boolean
  invalid_or_nonoriginal_books:number;evaluated_source_books:number
  rankable_with_budget_and_depth:number
  positive_stressed_upper_bounds:number;negative_stressed_upper_bounds:number
  positive_even_without_stress:number;negative_even_optimistic:number
  no_feasible_lots:number;recent_saved_books_60s:number
  source_fresh_risk_screened?:number
  execution_decision?:ExecutionDecision
  execution_policy?:{max_age_seconds:number;min_bid_inr:number
    max_relative_spread_bps:number;min_receipts:number
    minimum_top_depth_multiple:number;min_receipt_span_seconds:number
    max_loss_to_zero_fraction_of_budget:number}
  scan_completed_utc:string;total_rows:number;read_only:true;fills_observed:false
  net_realized_profit_inr:null;source:string;warning:string;rows:Candidate[]
}
type SortKey='risk'|'hurdle'|'failed_exit'|'stressed'|'optimistic'|'marketable'|'spread'|'capital'|'freshness'|'strike'
type Verdict='all'|'screened'|'positive'|'negative'|'blocked'
const money=(x:number|null|undefined)=>typeof x==='number'&&Number.isFinite(x)
  ?'₹'+x.toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2}):'—'
const n=(x:number|null|undefined,precision=0)=>typeof x==='number'&&Number.isFinite(x)
  ?x.toLocaleString('en-IN',{maximumFractionDigits:precision}):'—'
const time=(s:string)=>new Date(s).toLocaleString('en-IN',{
  timeZone:'Asia/Kolkata',day:'2-digit',month:'short',
  hour:'2-digit',minute:'2-digit',second:'2-digit'})
const sortValue=(row:Candidate,sort:SortKey):number|null=>{
  if(sort==='risk')return row.risk_screen_score??(
    -1000-(row.feasibility?.reasons.length??10)*100-
    Math.min(500,row.spread_bps/10))
  if(sort==='hurdle')return row.break_even_sell_fill_given_buy??null
  if(sort==='failed_exit')return row.failed_exit_net_inr??null
  if(sort==='stressed')return row.passive_stressed_upper_net_inr
  if(sort==='optimistic')return row.passive_upper_net_inr
  if(sort==='marketable')return row.marketable_net_inr
  if(sort==='spread')return row.spread_bps
  if(sort==='capital')return row.required_capital_inr
  if(sort==='freshness')return row.saved_book_age_seconds
  return row.strike
}

export default function SpreadOpportunityScanner({
  day,expiry,side,search,brokerProfile,onBrokerProfileChange,onInspect,
}:{
  day:string;expiry:string;side:'CE'|'PE'|'ALL';search:string
  brokerProfile:BrokerProfile;onBrokerProfileChange:(v:BrokerProfile)=>void
  onInspect:(identity:string,lots:number,profile:BrokerProfile)=>void
}){
  const [budget,setBudget]=useState(17000)
  const [maxLots,setMaxLots]=useState(3)
  const [orders,setOrders]=useState(1)
  const [stress,setStress]=useState(25)
  const [exitSlippage,setExitSlippage]=useState(10)
  const [data,setData]=useState<Scan|null>(null)
  const [busy,setBusy]=useState(true)
  const [error,setError]=useState('')
  const [verdict,setVerdict]=useState<Verdict>('all')
  const [sort,setSort]=useState<SortKey>('risk')
  const [descending,setDescending]=useState(true)
  const [freshOnly,setFreshOnly]=useState(false)
  const [page,setPage]=useState(0)
  const [expanded,setExpanded]=useState('')
  const [refreshToken,setRefreshToken]=useState(0)
  const scan=useCallback(async(signal?:AbortSignal)=>{
    setBusy(true)
    try{
      const qs=new URLSearchParams({
        day,broker_profile:brokerProfile,capital_inr:String(budget),
        max_lots:String(maxLots),executed_orders_per_side:String(orders),
        adverse_move_bps:String(stress),exit_slippage_bps:String(exitSlippage),
      })
      // Data access remains read-only, local; cost profile is only a tariff.
      const value=await marketApi<Scan>('/api/trading-cockpit/liquidity/scan?'+qs)
      if(signal?.aborted)return
      setData(value);setError('')
    }catch(e){if(!signal?.aborted)setError(readableError(e))}
    finally{if(!signal?.aborted)setBusy(false)}
  },[day,brokerProfile,budget,maxLots,orders,stress,exitSlippage])
  useEffect(()=>{
    const controller=new AbortController()
    const timer=window.setTimeout(()=>{if(!document.hidden)void scan(controller.signal)},350)
    return()=>{controller.abort();window.clearTimeout(timer)}
  },[scan,refreshToken])
  useEffect(()=>{
    // Source collection itself is never touched. At most one read-only scan
    // every 60s while this tab is displayed in a visible browser.
    const timer=window.setInterval(()=>{
      if(!document.hidden&&!busy)setRefreshToken(v=>v+1)
    },60000)
    return()=>window.clearInterval(timer)
  },[busy])
  const ordered=useMemo(()=>{
    const rows=(data?.rows||[]).filter(row=>{
      const label=[row.identity,row.expiry,row.strike,row.option_type].join(' ').toLowerCase()
      if(expiry&&row.expiry!==expiry)return false
      if(side!=='ALL'&&row.option_type!==side)return false
      if(search&&!label.includes(search.toLowerCase()))return false
      if(freshOnly&&!row.fresh_original_saved_book)return false
      if(verdict==='blocked')return row.best_hypothetical_lots===null
      if(verdict==='screened')return !!row.source_fresh_risk_screened
      if(verdict==='positive')return row.passive_stressed_upper_net_inr!==null&&
        row.passive_stressed_upper_net_inr>0
      if(verdict==='negative')return row.passive_stressed_upper_net_inr!==null&&
        row.passive_stressed_upper_net_inr<=0
      return true
    })
    rows.sort((a,b)=>{
      const av=sortValue(a,sort),bv=sortValue(b,sort)
      if(av==null||bv==null)return av==null?(bv==null?0:1):-1
      return (descending?-1:1)*(av-bv)||a.identity.localeCompare(b.identity)
    })
    return rows
  },[data,expiry,side,search,freshOnly,verdict,sort,descending])
  const pageSize=40
  const pageCount=Math.max(1,Math.ceil(ordered.length/pageSize))
  const actualPage=Math.min(pageCount-1,page)
  const visible=ordered.slice(actualPage*pageSize,(actualPage+1)*pageSize)
  useEffect(()=>setPage(0),[verdict,sort,descending,expiry,side,search,freshOnly])
  const summary=[
    ['Original depth IDs found',data?.original_depth_contracts_found],
    ['Validated books',data?.evaluated_source_books],
    ['Affordable with verified depth',data?.rankable_with_budget_and_depth],
    ['Risk-screened fresh research',data?.source_fresh_risk_screened],
    ['Negative stressed upper bounds',data?.negative_stressed_upper_bounds],
    ['Insufficient budget / depth',data?.no_feasible_lots],
  ] as const
  return <section className="sos-workspace" aria-label="Automatic spread profit and loss scanner">
    <div className="sos-title">
      <div><span className="sos-overline"><ArrowDownUp size={13}/> AUTO-EVALUATE SAVED DHAN BOOKS</span>
        <h3>Spread P&amp;L Opportunity Scanner</h3>
        <p>Automatic price/fee/depth scan of all saved, validated original
          order books. Each contract and lot size is screened for conditional
          sell-fill hurdle and failed-exit loss. <b>Use Analyze to inspect
          a ranked candidate; no manual contract picking required.</b></p>
      </div>
      <button type="button" onClick={()=>setRefreshToken(v=>v+1)}
        disabled={busy}><RefreshCw size={14}/>{busy?'Scanning…':'Refresh scan'}</button>
    </div>
    <div className="sos-options" aria-label="Automatic spread scanning assumptions">
      <label>Charge profile
        <select value={brokerProfile} onChange={e=>onBrokerProfileChange(
          e.target.value as BrokerProfile)}>
          <option value="zerodha">Zerodha standard · ₹20/order</option>
          <option value="zerodha_debit_balance">Zerodha special · ₹40/order</option>
          <option value="dhan">Dhan standard · ₹20/order</option>
        </select>
      </label>
      <label>Available capital (₹)
        <input type="number" min={1000} max={10000000} step={1000}
          value={budget} onChange={e=>setBudget(Math.min(10000000,
            Math.max(1000,Number(e.target.value)||1000)))}/>
      </label>
      <label>Auto-test lot counts
        <select value={maxLots} onChange={e=>setMaxLots(Number(e.target.value))}>
          {[1,2,3,4,5,6,7,8,9,10].map(x=><option key={x} value={x}>1–{x} lots</option>)}
        </select>
      </label>
      <label>Executed orders per side
        <select value={orders} onChange={e=>setOrders(Number(e.target.value))}>
          {[1,2,3,4,5].map(x=><option key={x} value={x}>{x}</option>)}
        </select>
      </label>
      <label>Adverse selection allowance (bps)
        <input type="number" min={0} max={1000} value={stress}
          onChange={e=>setStress(Math.min(1000,Math.max(0,Number(e.target.value)||0)))}/>
      </label>
      <label>Exit slippage allowance (bps)
        <input type="number" min={0} max={1000} value={exitSlippage}
          onChange={e=>setExitSlippage(Math.min(1000,Math.max(0,Number(e.target.value)||0)))}/>
      </label>
    </div>
    <div className="sos-summary">
      {summary.map(([name,value])=><div key={name}>
        <strong>{n(value)}</strong><small>{name}</small>
      </div>)}
    </div>
    <SpreadExecutionDecision decision={data?.execution_decision}
      scope="Bid-ask spread capture"/>
    <section className="sos-top-choices" aria-label="Automatically screened bid-ask research candidates">
      <div><strong>Automatically screened research shortlist</strong>
        <small>Strict source gate: ≤8-second books, bid ≥₹20, ≤250 bps
          relative spread, ≥3 packet receipts over ≥15s, ≥2 fresh Dhan
          exchange-trade times with ≥1 lot of cumulative volume growth,
          ≥2× top-level depth, and loss-to-zero ≤25% of capital.
          Not a profit forecast.</small></div>
      <div className="sos-top-list">
        {(data?.rows||[]).filter(x=>x.source_fresh_risk_screened).slice(0,3)
          .map((row,i)=><button type="button" key={row.identity}
            onClick={()=>row.best_hypothetical_lots!==null&&
              onInspect(row.identity,row.best_hypothetical_lots,brokerProfile)}>
            <small>RESEARCH #{i+1} · score {n(row.risk_screen_score,1)}</small>
            <strong>{row.option_type} {n(row.strike)} · {n(row.best_hypothetical_lots)} lot(s)</strong>
            <span>Conditional upper net {money(row.passive_stressed_upper_net_inr)}</span>
            <span>Failed exit {money(row.failed_exit_net_inr)}</span>
            <span>Option worthless: {money(row.loss_if_option_worthless_inr)}
              {' · '}zero-recovery hurdle {
                row.conservative_sell_fill_hurdle==null?'—':
                n(row.conservative_sell_fill_hurdle*100,1)+'%'}</span>
            <span>Analyze execution & costs →</span>
          </button>)}
        {!(data?.rows||[]).some(x=>x.source_fresh_risk_screened)&&
          <p><b>NO TRADE.</b> No source-verified candidate passes the
            stricter spread, premium, depth, repeated-book and full-premium-risk
            screen. Blocked quotes remain below so you can see why.</p>}
      </div>
    </section>
    <div className="sos-toolbar">
      <label>Show outcomes
        <select value={verdict} onChange={e=>setVerdict(e.target.value as Verdict)}>
          <option value="all">All evaluated / unavailable</option>
          <option value="screened">Fresh risk-screened research only</option>
          <option value="positive">Positive conditional bounds (not profits)</option>
          <option value="negative">Nonpositive conditional bounds</option>
          <option value="blocked">No affordable verified-depth lot</option>
        </select>
      </label>
      <label>Sort by
        <select value={sort} onChange={e=>setSort(e.target.value as SortKey)}>
          <option value="risk">Risk-screen research priority</option>
          <option value="hurdle">Break-even exit-fill hurdle</option>
          <option value="failed_exit">Failed-exit scenario P&amp;L</option>
          <option value="stressed">Conditional upper net after stress</option>
          <option value="optimistic">Optimistic passive upper net</option>
          <option value="marketable">Marketable round-trip estimate</option>
          <option value="spread">Quoted spread (bps)</option>
          <option value="capital">Capital needed</option>
          <option value="freshness">Source book age</option>
          <option value="strike">Strike</option>
        </select>
      </label>
      <label>Order
        <select value={descending?'desc':'asc'}
          onChange={e=>setDescending(e.target.value==='desc')}>
          <option value="desc">Highest first</option>
          <option value="asc">Lowest first</option>
        </select>
      </label>
      <label className="sos-check">
        <input type="checkbox" checked={freshOnly}
          onChange={e=>setFreshOnly(e.target.checked)}/>
        Only books received in last 60s
      </label>
    </div>
    {error&&<p className="sos-error" role="alert">{error}</p>}
    {busy&&<p className="sos-muted" role="status">Checking saved original bid/ask
      books, affordable lot sizes and estimated broker charges…</p>}
    <p className="sos-muted">{ordered.length} matching rows of
      {' '}{n(data?.total_rows??data?.rows.length)} evaluated original depth IDs.
      {' '}Last scan: {data?time(data.scan_completed_utc):'Not completed'} IST.
      {data?.source_scan_truncated?' Archive scan capped; not all source contracts examined.':''}
      {data?.invalid_or_nonoriginal_books?' Invalid/non-original books excluded: '+
        n(data.invalid_or_nonoriginal_books)+'.':''}
    </p>
    <div className="sos-warning"><ShieldAlert size={16}/>
      <span><strong>NO TRADE is the only live action; amber is paper research only.</strong>
        No fill probability or realized profit is observed. Large quoted spreads
        may be illiquid or stale. Dhan Quote/OI covers more contracts than
        the 20-level depth that is required to evaluate execution.
        Zerodha charges are published <em>estimates</em>, not actual contract-note charges.</span>
    </div>
    <div className="sos-scroll"><table className="sos-table">
      <thead><tr>
        <th>Source contract</th><th>Bid / ask</th><th>Spread</th>
        <th>Best modeled lots</th><th>Capital required</th>
        <th>Buy fees / Sell fees</th>
        <th>Marketable net</th><th>Conditional upper net</th>
        <th>Conditional after stress</th><th>Failed-exit / zero loss</th>
        <th>Fill hurdle (mild / zero)</th><th>Execution evidence gate</th>
        <th>Source age</th><th/>
      </tr></thead>
      <tbody>
        {visible.map(row=>{
          const selectedLot=row.lot_scenarios.find(
            lot=>lot.lots===row.best_hypothetical_lots)
          const positive=(row.passive_stressed_upper_net_inr??0)>0
          return <tr key={row.identity} className={
            (expanded===row.identity?'sos-open ':'')+
            (row.feasibility&&!row.feasibility.paper_research_qualified
              ?'sos-rejected':'')}>
            <td><span className="sos-contract">
              {row.option_type} {n(row.strike)} <small>{row.expiry}
              {' · '}{row.identity}</small></span></td>
            <td>{money(row.best_bid)} / {money(row.best_ask)}</td>
            <td>{money(row.spread_inr)}<small>{n(row.spread_bps,1)} bps</small></td>
            <td>{row.best_hypothetical_lots==null?'—':
              n(row.best_hypothetical_lots)+' lot(s)'}
              <small>tested {n(row.tested_lot_count)} sizes</small></td>
            <td>{money(row.required_capital_inr)}</td>
            <td>{money(row.estimated_buy_fees_inr)} / {money(row.estimated_sell_fees_inr)}</td>
            <td className="sos-negative">{money(row.marketable_net_inr)}</td>
            <td className={row.passive_upper_net_inr!==null&&row.passive_upper_net_inr>0?
              'sos-conditional':'sos-negative'}>{money(row.passive_upper_net_inr)}</td>
            <td><span className={row.best_hypothetical_lots===null?'sos-unknown':
                positive?'sos-conditional':'sos-negative'}>
              {money(row.passive_stressed_upper_net_inr)}</span>
              <small>{row.best_hypothetical_lots==null?'Budget/depth blocked':
                positive?'Not a profit prediction':'Conditional loss/negative'}</small>
            </td>
            <td className="sos-negative">{money(row.failed_exit_net_inr)}
              <small>To zero: {money(row.loss_if_option_worthless_inr)}</small>
              <small>Half-price exit: {money(row.half_premium_exit_net_inr)}</small>
            </td>
            <td>{row.break_even_sell_fill_given_buy==null?'—':
              n(row.break_even_sell_fill_given_buy*100,1)+'%'}
              {' / '}{row.conservative_sell_fill_hurdle==null?'—':
              n(row.conservative_sell_fill_hurdle*100,1)+'%'}
              <small>Both hypothetical, not probabilities</small></td>
            <td><span className={row.source_fresh_risk_screened?
                'sos-conditional':'sos-negative'}>
              {row.source_fresh_risk_screened?
                'Paper study '+n(row.risk_screen_score,1):'NO TRADE'}</span>
              <small title={row.feasibility?.reasons.join(', ')}>
                {row.feasibility?.reasons.slice(0,2).map(
                  x=>x.replaceAll('_',' ')).join(' · ')||
                  'Passes source screen; fill odds unknown'}</small></td>
            <td><span className={row.fresh_original_saved_book?'sos-fresh':'sos-older'}>
              {n(row.saved_book_age_seconds,0)}s</span><small>
              {time(row.received_utc)} IST</small></td>
            <td>
              <button type="button" onClick={()=>setExpanded(
                v=>v===row.identity?'':row.identity)} aria-expanded={expanded===row.identity}>
                {expanded===row.identity?'Hide':'All lots'}
              </button>
              {row.best_hypothetical_lots!==null&&<button type="button"
                onClick={()=>onInspect(row.identity,row.best_hypothetical_lots!,brokerProfile)}>
                Inspect <ArrowRight size={12}/></button>}
              {expanded===row.identity&&selectedLot&&
                <small className="sos-selected-caption">Selected hypothetical
                  lot size: {selectedLot.lots}</small>}
            </td>
          </tr>
        })}
        {visible.length===0&&!busy&&<tr><td colSpan={14}>
          No source-verified saved books match these filters. No prices
          or transactions will be invented.</td></tr>}
      </tbody></table></div>
    {expanded&&data?.rows.some(row=>row.identity===expanded)&&
      <section className="sos-ledger" aria-label="Per-lot transaction cashflow ledger">
        {data.rows.filter(row=>row.identity===expanded).map(row=>
          <div key={row.identity}>
            <div className="sos-ledger-head"><strong>All modeled lot outcomes · {row.identity}</strong>
              <small>Buy then sell at the same saved original quote; not executed.</small></div>
            <div className="sos-scroll"><table className="sos-table">
              <thead><tr>
                <th>Lots / units</th><th>Budget eligible?</th>
                <th>Buy debit incl. charges</th><th>Cash left after buy</th>
                <th>Sell credit after charges</th><th>Cash after hypothetical sell</th>
                <th>Net after costs</th><th>After stress</th><th>Marketable net</th>
                <th>Missed-exit loss</th><th>Exit-fill hurdle</th>
              </tr></thead>
              <tbody>{row.lot_scenarios.map(lot=><tr key={lot.lots}>
                <td>{lot.lots} / {n(lot.units)}</td>
                <td>{lot.within_budget&&lot.marketable_full_depth&&
                  lot.top_of_book_both_sides_sufficient?'Within budget & depth':'Limited'}</td>
                <td>{money(lot.hypothetical_buy_cash_debit_inr)}
                  <small>Buy fees {money(lot.buy_fees_inr)}</small></td>
                <td>{money(budget-lot.hypothetical_buy_cash_debit_inr)}</td>
                <td>{money(lot.hypothetical_sell_cash_credit_inr)}
                  <small>Sell fees {money(lot.sell_fees_inr)}</small></td>
                <td>{money(budget-lot.hypothetical_buy_cash_debit_inr+
                  lot.hypothetical_sell_cash_credit_inr)}</td>
                <td className={lot.passive_upper_net_inr>0?'sos-conditional':'sos-negative'}>
                  {money(lot.passive_upper_net_inr)}</td>
                <td className={lot.passive_stressed_upper_net_inr>0?'sos-conditional':'sos-negative'}>
                  {money(lot.passive_stressed_upper_net_inr)}</td>
                <td>{money(lot.marketable_net_inr)}</td>
                <td className="sos-negative">{money(lot.failed_exit_net_inr)}</td>
                <td>{lot.break_even_exit_fill_probability==null?'—':
                  n(lot.break_even_exit_fill_probability*100,1)+'%'}</td>
              </tr>)}</tbody></table></div>
            <small className="sos-muted">These are independent counterfactuals
              for this one contract. Cash after buy/sell assumes full passive
              fills at unchanged bid/ask, not executable proceeds. No orders
              placed. Capital covers long-option premium only and not margin
              for naked short positions, exercise, or future market moves.</small>
          </div>)}
      </section>}
    <div className="sos-pagination">
      <span>Showing {ordered.length?actualPage*pageSize+1:0}–
        {Math.min((actualPage+1)*pageSize,ordered.length)} of {n(ordered.length)}</span>
      <div><button type="button" disabled={actualPage===0}
        onClick={()=>setPage(v=>Math.max(0,v-1))}>Previous</button>
        <span>Page {actualPage+1} / {pageCount}</span>
        <button type="button" disabled={actualPage>=pageCount-1}
          onClick={()=>setPage(v=>Math.min(pageCount-1,v+1))}>Next</button></div>
    </div>
  </section>
}
