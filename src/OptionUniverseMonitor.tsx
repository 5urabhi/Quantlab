import {useCallback,useEffect,useState} from 'react'
import {Activity,AlertTriangle,ChevronLeft,ChevronRight,Database,Radio} from 'lucide-react'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
import './option-universe-monitor.css'

type FeedState={
  state:string;armed:boolean;depth_armed:boolean
  full_universe_consent:boolean;connected:boolean;market_regular_hours:boolean
  requested_contracts:number;source_contracts:number
  unsubscribed_due_to_capacity:number;observed_contracts:number
  recent_price_contracts:number;quote_packets:number;oi_packets:number
  stored_events:number;dropped_events:number;rejected_frames:number
  ignored_stale_trades:number;unchanged_quote_packets:number
  unchanged_oi_packets:number;queue_depth:number
  opportunity_count:number;depth_candidate_count:number
  observed_oi_contracts:number;requested_not_yet_quoted:number
  coverage_by_expiry:ExpiryCoverage[]
  last_quote_received_utc:string|null
  last_error:string|null
}
type ExpiryCoverage={
  expiry:string;subscribed:number;with_any_quote:number
  fresh_quote_60s:number;with_any_oi:number;oi_only:number
  never_quoted:number;activity_screen_passed_45s:number
}
type SourceOption={
  identity:string;expiry:string;strike:number;option_type:'CE'|'PE'
  lot_size:number;price:number|null;volume:number|null;open_interest:number|null
  score:number|null;move_60s_pct:number|null;move_5m_pct:number|null
  observed_change_pct:number|null;observed_span_seconds:number|null
  eligible_for_depth?:boolean;screen_reason?:string
  volume_increase:number|null;quote_received_utc:string|null
}
type FeedPage={total:number;offset:number;limit:number;contracts:SourceOption[]}
type Alerts={candidates:SourceOption[];basis:string}
type Row={
  received_utc:string;exchange_trade_utc:string|null
  price:number|null;volume:number|null;open_interest:number|null
  kind:'quote'|'oi'
}
type History={identity:string;events:Row[];source:string}
const nf=(v:number|null|undefined,d=0)=>v==null||!Number.isFinite(v)
  ?'—':v.toLocaleString('en-IN',{maximumFractionDigits:d})
const time=(v:string|null|undefined)=>v
  ?new Date(v).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',
    hour:'2-digit',minute:'2-digit',second:'2-digit'}):'—'
const change=(v:number|null|undefined)=>v==null||!Number.isFinite(v)
  ?'—':(v>0?'+':'')+nf(v,1)+'%'
function PriceTimeline({events}:{events:Row[]}){
  const points=events.filter(x=>x.kind==='quote'&&x.price!=null&&x.price>0).slice(-120)
  if(points.length<2)return <p className="ofu-help">
    Not enough original price observations to draw a historical trajectory.</p>
  const width=760,height=190,pad=17
  const values=points.map(x=>x.price as number)
  const floor=Math.min(...values),ceil=Math.max(...values)
  const span=Math.max(.01,ceil-floor)
  const cx=(i:number)=>pad+(width-2*pad)*i/(points.length-1)
  const cy=(v:number)=>height-pad-(height-2*pad)*(v-floor)/span
  const line=points.map((p,i)=>String(cx(i))+','+String(cy(p.price as number))).join(' ')
  return <div className="ofu-chart" aria-label="Saved original Dhan option price observations">
    <div className="ofu-chart-captions"><span>₹{nf(ceil,2)}</span>
      <span>Only received saved Quote packets; no interpolated trades.</span>
      <span>₹{nf(floor,2)}</span></div>
    <svg viewBox="0 0 760 190" role="img"
      aria-label={String(points.length)+' received Dhan option quotes, from ₹'+nf(values[0],2)+' to ₹'+nf(values[values.length-1],2)}>
      <polyline fill="none" stroke="#70e5c7" strokeWidth="2.4"
        strokeLinejoin="round" strokeLinecap="round" points={line}/>
      {points.map((p,i)=><circle key={p.received_utc+'-'+String(i)}
        cx={cx(i)} cy={cy(p.price as number)} r="2.7" fill="#cefdf0">
        <title>{time(p.received_utc)+' IST · ₹'+nf(p.price,2)+
          (p.volume!=null?' · Cumulative volume '+nf(p.volume):'')}
        </title>
      </circle>)}
    </svg>
    <div className="ofu-axis"><span>{time(points[0].received_utc)} IST</span>
      <span>{time(points[points.length-1].received_utc)} IST</span></div>
  </div>
}
export default function OptionUniverseMonitor(){
  const [state,setState]=useState<FeedState|null>(null)
  const [alerts,setAlerts]=useState<SourceOption[]>([])
  const [page,setPage]=useState<FeedPage|null>(null)
  const [offset,setOffset]=useState(0)
  const [chosen,setChosen]=useState<string|null>(null)
  const [history,setHistory]=useState<History|null>(null)
  const [showUniverse,setShowUniverse]=useState(false)
  const [warning,setWarning]=useState('')
  const [confirmed,setConfirmed]=useState(false)
  const [busy,setBusy]=useState(false)
  const refresh=useCallback(async()=>{
    const [a,b]=await Promise.allSettled([
      marketApi<FeedState>('/api/trading-cockpit/option-feed/status'),
      marketApi<Alerts>('/api/trading-cockpit/option-feed/opportunities?limit=15')])
    if(a.status==='fulfilled')setState(a.value)
    else setWarning(readableError(a.reason))
    if(b.status==='fulfilled')setAlerts(b.value.candidates)
  },[])
  const loadPage=useCallback(async(value:number)=>{
    try{
      const result=await marketApi<FeedPage>(
        '/api/trading-cockpit/option-feed/contracts?'+new URLSearchParams({
          offset:String(value),limit:'100'}))
      setPage(result);setOffset(value)
    }catch(e){setWarning(readableError(e))}
  },[])
  const select=useCallback(async(identity:string)=>{
    setChosen(identity);setHistory(null)
    try{
      const result=await marketApi<History>('/api/trading-cockpit/option-feed/history?'+
        new URLSearchParams({identity,limit:'500'}))
      setHistory(result)
    }catch(e){setWarning(readableError(e))}
  },[])
  useEffect(()=>{
    void refresh()
    const interval=window.setInterval(()=>{void refresh()},7000)
    return()=>window.clearInterval(interval)
  },[refresh])
  useEffect(()=>{if(showUniverse)void loadPage(offset)},[showUniverse,offset,loadPage])
  const changeConsent=async(enabled:boolean)=>{
    if(busy)return
    setBusy(true);setWarning('')
    try{
      const result=await marketPost<FeedState>(
        '/api/trading-cockpit/option-feed/'+(enabled?'enable':'disable'),
        enabled?{confirm_live_quote_stream:true}:{})
      setState(result);setConfirmed(false)
      await refresh()
    }catch(e){setWarning(readableError(e))}
    finally{setBusy(false)}
  }
  const metrics=[
    ['Original listed contracts',state?.source_contracts],
    ['Requested live subscriptions',state?.requested_contracts],
    ['Contracts with any observed trade price',state?.observed_contracts],
    ['Live price IDs seen in last 60s',state?.recent_price_contracts],
    ['Subscribed IDs without a trade price yet',state?.requested_not_yet_quoted],
    ['Contracts with observed OI',state?.observed_oi_contracts],
    ['Original Quote / OI packets',state?nf(state.quote_packets)+' / '+nf(state.oi_packets):null],
    ['Saved source events',state?.stored_events],
    ['Dropped / rejected frames',state?nf(state.dropped_events)+' / '+nf(state.rejected_frames):null],
    ['All observed movers',state?.opportunity_count],
    ['Source-activity-screened depth candidates',state?.depth_candidate_count],
  ] as const
  return <section className="ofu-root" aria-label="Full BANKNIFTY option universe monitor">
    <header className="ofu-head"><div><span className="tc-page-kicker">
      ALL ORIGINAL BANKNIFTY OPTIONS · DHAN ONLY</span>
      <h3><Activity size={19}/> Full-universe option price monitor</h3>
      <p>One Dhan Quote/OI socket attempts every current master-verified CE/PE
        contract across source-listed expiries. Received updates are recorded
        in the shared market library. Four other sockets record selected
        original 20-level depth. No broker orders.</p></div>
      <span className={'ofu-state '+(state?.connected?'connected':'pending')}>
        <Radio size={14}/>{state?.state||'Checking source'}</span>
    </header>
    <div className="ofu-consent">
      {!state?.full_universe_consent?<label><input type="checkbox"
        checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/>
        I authorize Dhan-only, read-only Quote/OI subscriptions for all
        currently listed BANKNIFTY CE/PE contracts while local QuantLab
        is running. Up to 5,000 instruments use one additional feed socket.
        Original event storage may grow substantially.</label>:<span>
        Full-universe streaming has separate saved permission.
        Disabling it leaves the four 20-level recording sockets untouched.</span>}
      <button type="button" disabled={busy||(state?.full_universe_consent?
        false:!confirmed||!state?.depth_armed)}
        onClick={()=>void changeConsent(!state?.full_universe_consent)}>
        {busy?'Applying…':state?.full_universe_consent?
          'Stop full-universe price stream':'Start all-contract price stream'}
      </button>
    </div>
    <div className="ofu-summary">
      {metrics.map(([label,value])=><div key={label}>
        <strong>{typeof value==='number'?nf(value):value||'—'}</strong>
        <span>{label}</span>
      </div>)}
    </div>
    {Boolean(state?.coverage_by_expiry?.length)&&<section className="ofu-expiries"
      aria-label="Original option quote and open interest coverage by expiry">
      <strong>Original price and OI coverage by expiry</strong>
      <p className="ofu-help">These counts distinguish subscription requests from
        market packets actually received. Options without new trades may be
        silent or illiquid; missing quotes are not filled from snapshots.</p>
      <div className="ofu-scroll"><table className="ofu-table">
        <thead><tr><th>Expiry</th><th>Subscribed</th>
          <th>Any price observed</th><th>Price seen in 60s</th>
          <th>OI observed</th><th>No price yet</th>
          <th>Pass source activity screen</th></tr></thead>
        <tbody>{state?.coverage_by_expiry?.map(e=><tr key={e.expiry}>
          <td>{e.expiry}</td><td>{nf(e.subscribed)}</td>
          <td>{nf(e.with_any_quote)}</td><td>{nf(e.fresh_quote_60s)}</td>
          <td>{nf(e.with_any_oi)}</td><td>{nf(e.never_quoted)}</td>
          <td>{nf(e.activity_screen_passed_45s)}</td></tr>)}</tbody>
      </table></div>
    </section>}
    {!!state?.unsubscribed_due_to_capacity&&<p className="ofu-warning" role="alert">
      <AlertTriangle size={15}/>{nf(state.unsubscribed_due_to_capacity)} contracts
      exceed Dhan's 5,000-per-connection limit and are NOT streamed.
      Subscribed does not mean delivered.</p>}
    {(state?.dropped_events||0)>0&&<p className="ofu-warning" role="alert">
      <AlertTriangle size={15}/>{nf(state?.dropped_events)} received original
      packets were not saved. Do not treat saved series as complete price history.</p>}
    {warning&&<p className="ofu-warning" role="status">{warning}</p>}
    {state?.last_error&&<p className="ofu-warning" role="status">{state.last_error}</p>}
    <p className="ofu-help"><Database size={14}/> Latest observed Dhan Quote:
      {' '}{time(state?.last_quote_received_utc)} IST.
      {state?.armed?' Automatic recording consent is active.':
        ' Recording is disarmed; enable it using the controls above.'}
      {' '}Daily storage cap: two million received source events. Disconnections,
      silent contracts, delayed last trades, and dropped packets are never filled.</p>
    <div className="ofu-section-head"><div><strong>Unusual observed premium moves</strong>
      <small>Source-activity-screened contracts appear first; all price
        observations remain recorded. The observed-span column shows actual
        elapsed Dhan trade time. A 60s/5m return stays blank until a
        genuine source observation establishes that horizon.
        Screening is not proof of liquidity, a guaranteed fill, or advice.</small></div>
      <button type="button" onClick={()=>void refresh()}>Refresh feed</button></div>
    <div className="ofu-scroll">
      <table className="ofu-table">
        <thead><tr><th>Expiry / Contract</th><th>Strike</th><th>Last price</th>
          <th>Observed move</th><th>Trade span</th>
          <th>60s return</th><th>5m return</th><th>Volume gain</th>
          <th>Depth research screen</th><th>Last quote IST</th><th></th></tr></thead>
        <tbody>{alerts.map(row=><tr key={row.identity}>
          <td>{row.expiry} · {row.option_type}<small>{row.identity}</small></td>
          <td>{nf(row.strike)}</td><td>₹{nf(row.price,2)}</td>
          <td>{change(row.observed_change_pct)}</td>
          <td>{row.observed_span_seconds==null?'—':
            nf(row.observed_span_seconds)+'s'}</td>
          <td>{change(row.move_60s_pct)}</td><td>{change(row.move_5m_pct)}</td>
          <td>{nf(row.volume_increase)}</td>
          <td><span className={'ofu-screen '+(row.eligible_for_depth?'ok':'excluded')}
            title={row.screen_reason||'Awaiting original activity evidence'}>
            {row.eligible_for_depth?'Source screen passed':'Observation only'}
          </span></td>
          <td>{time(row.quote_received_utc)}</td>
          <td><button type="button" onClick={()=>void select(row.identity)}>
            View observations</button></td>
        </tr>)}
        {!alerts.length&&<tr><td colSpan={11}>
          No source-confirmed rapid moves observed. This does not mean all
          options were active or unchanged.</td></tr>}</tbody>
      </table>
    </div>
    <div className="ofu-section-head">
      <div><strong>Every Dhan-listed option contract</strong>
        <small>Paginated verified identities. A silent contract stays listed
          but never receives an invented price.</small></div>
      <button type="button" aria-expanded={showUniverse}
        onClick={()=>setShowUniverse(v=>!v)}>
        {showUniverse?'Hide contract catalog':'Browse all contracts'}
      </button>
    </div>
    {showUniverse&&<div className="ofu-scroll">
      <table className="ofu-table"><thead><tr><th>Contract</th><th>Strike</th>
        <th>Last observed price</th><th>Volume</th><th>Open interest</th>
        <th>Last quote</th><th></th></tr></thead>
        <tbody>{page?.contracts.map(row=><tr key={row.identity}>
          <td>{row.expiry} · {row.option_type}<small>{row.identity}</small></td>
          <td>{nf(row.strike)}</td><td>{row.price!=null?'₹'+nf(row.price,2):'Not observed'}</td>
          <td>{nf(row.volume)}</td><td>{nf(row.open_interest)}</td>
          <td>{time(row.quote_received_utc)} IST</td>
          <td><button type="button" onClick={()=>void select(row.identity)}>
            Price history</button></td></tr>)}
          {!page?.contracts.length&&<tr><td colSpan={7}>
            No verified source catalog has been loaded by the monitor.</td></tr>}
        </tbody></table>
      <div className="ofu-pagination">
        <button type="button" disabled={offset===0}
          onClick={()=>void loadPage(Math.max(0,offset-100))}>
          <ChevronLeft size={15}/> Previous</button>
        <span>{nf(Math.min(offset+1,page?.total||0))}–{nf(Math.min(offset+100,page?.total||0))}
          {' '}of {nf(page?.total)}</span>
        <button type="button" disabled={!page||offset+100>=page.total}
          onClick={()=>void loadPage(offset+100)}>
          Next <ChevronRight size={15}/></button>
      </div>
    </div>}
    {chosen&&<section className="ofu-history" aria-label="Original price observations">
      <div className="ofu-section-head"><div><strong>Recorded price history</strong>
        <small>{chosen} · Up to 500 recent original Quote/OI receipts</small>
      </div><button type="button" onClick={()=>void select(chosen)}>Refresh</button></div>
      {history&&<PriceTimeline events={history.events}/>}
      {!history&&<p className="ofu-help">Loading original saved receipts…</p>}
      <p className="ofu-help">OI packets carry local receive timestamps, not trade time.
        Price events include Dhan last-trade time and local receive time;
        missing intervals are never interpolated.</p>
    </section>}
  </section>
}
