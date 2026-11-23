import {useCallback,useEffect,useMemo,useState} from 'react'
import {AlertTriangle,ArrowRight,Clock3,Database,RefreshCw,ShieldCheck,TrendingUp} from 'lucide-react'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
import './option-chain-live.css'

type Expiries={
  underlying:string;expiries:string[];nearest_expiry:string;
  received_utc:string;source:string;expiry_sources?:Record<string,string[]>;
  providers_used?:string[];provider_errors?:Record<string,string>
}
type ProviderConnection={id:string;label:string;configured:boolean;session_verified:boolean;
  mode:string;note:string}
type CoverageConnections={read_only:boolean;providers:ProviderConnection[];underlyings:string[];warning:string}
export type OptionContract={
  identity:string|null;symbol:string;strike:number;expiry:string;option_type:'CE'|'PE'
  lot_size:number|null;contract_master_verified:boolean
  bid:number|null;ask:number|null;ltp:number|null
  top_bid_quantity:number|null;top_ask_quantity:number|null
  oi:number|null;volume:number|null;iv:number|null
  delta:number|null;theta:number|null;gamma:number|null;vega:number|null
  quote_valid:boolean;one_lot_ask_inr:number|null
  one_lot_bid_inr:number|null;spread_inr_per_lot:number|null
  quote_provider?:string;available_sources?:string[];source_received_utc?:string
  provider_lot_size?:number|null;provider_instrument_key?:string
  source_identity_conflict?:boolean
}
type Chain={
  underlying:string;underlying_spot:number;expiry:string;received_utc:string
  source:string;source_clock:string;not_live_stream:boolean
  market_master_fresh:boolean;master_message:string;master_age_hours:number|null
  contracts:OptionContract[];quote_count:number;read_only:boolean
  warning:string;cache_hit:boolean
  providers_used?:string[];provider_errors?:Record<string,string>
  provider_contract_counts?:Record<string,number>
  source_identity_conflicts?:number
  secondary_verified_quote_replacements?:number
}
const money=(value:number|null|undefined)=>value===null||value===undefined?'—':
  new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',
    maximumFractionDigits:2,minimumFractionDigits:2}).format(value)
const num=(value:number|null|undefined,n=2)=>value===null||value===undefined?'—':
  value.toLocaleString('en-IN',{maximumFractionDigits:n})
const timeIST=(value:string)=>new Date(value).toLocaleString('en-IN',{
  timeZone:'Asia/Kolkata',month:'short',day:'2-digit',
  hour:'2-digit',minute:'2-digit',second:'2-digit',
})
type Props={
  feedActive:boolean;depthIdentity:string;onSelectDepth:(identity:string)=>void
  onDraftJournal:(contract:OptionContract,lots:number)=>void
  openConnections:()=>void
  currentIndexDirection:'UP'|'DOWN'|'NO_TRADE'|null
}
export default function OptionChainLive({feedActive,depthIdentity,
  onSelectDepth,onDraftJournal,openConnections,currentIndexDirection}:Props){
  const [underlying,setUnderlying]=useState<'BANKNIFTY'|'NIFTY50'>('BANKNIFTY')
  const [providerChoice,setProviderChoice]=useState<'all'|'dhan'|'upstox'>('all')
  const [connections,setConnections]=useState<CoverageConnections|null>(null)
  const [upstoxToken,setUpstoxToken]=useState('')
  const [upstoxConsent,setUpstoxConsent]=useState(false)
  const [upstoxOpen,setUpstoxOpen]=useState(false)
  const [upstoxBusy,setUpstoxBusy]=useState(false)
  const [connectionNotice,setConnectionNotice]=useState('')
  const [dates,setDates]=useState<Expiries|null>(null)
  const [expiry,setExpiry]=useState('')
  const [chain,setChain]=useState<Chain|null>(null)
  const [selected,setSelected]=useState<string>('')
  const [side,setSide]=useState<'ALL'|'CE'|'PE'>('ALL')
  const [lots,setLots]=useState(3)
  const [targetPremium,setTargetPremium]=useState(300)
  const [premiumTolerance,setPremiumTolerance]=useState(50)
  const [nearTargetOnly,setNearTargetOnly]=useState(false)
  const [capital,setCapital]=useState(50_000)
  const [busy,setBusy]=useState(false)
  const [expiryBusy,setExpiryBusy]=useState(false)
  const [error,setError]=useState('')
  const [expiryError,setExpiryError]=useState('')
  const [masterJobId,setMasterJobId]=useState('')
  const [masterNotice,setMasterNotice]=useState('')
  const [now,setNow]=useState(Date.now())
  const refreshConnections=useCallback(async()=>{
    const data=await marketApi<CoverageConnections>(
      '/api/trading-cockpit/options/providers')
    setConnections(data)
  },[])
  useEffect(()=>{void refreshConnections().catch(e=>setConnectionNotice(readableError(e)))},
    [refreshConnections])
  const connectUpstox=async(event:React.FormEvent<HTMLFormElement>)=>{
    event.preventDefault()
    if(upstoxBusy||!upstoxConsent||!upstoxToken.trim())return
    setUpstoxBusy(true);setConnectionNotice('')
    try{
      await marketPost('/api/trading-cockpit/options/upstox/connect',{
        access_token:upstoxToken,confirm_local_storage:true})
      setUpstoxToken('');setUpstoxConsent(false);setUpstoxOpen(false)
      setConnectionNotice('Upstox access token saved privately on this local machine. Refresh the expiry list to verify entitlement.')
      await refreshConnections()
      await getExpiries()
    }catch(e){setConnectionNotice(readableError(e))}
    finally{setUpstoxBusy(false)}
  }
  const disconnectUpstox=async()=>{
    if(upstoxBusy)return
    if(!window.confirm('Disconnect the private locally saved Upstox token? This does not affect Dhan, Zerodha or original saved observations.'))return
    setUpstoxBusy(true);setConnectionNotice('')
    try{
      const response=await marketPost<{environment_token_still_configured:boolean}>(
        '/api/trading-cockpit/options/upstox/disconnect',{confirm_disconnect:true})
      setConnectionNotice(response.environment_token_still_configured
        ?'Local Upstox token removed. A separately configured environment token is still active.'
        :'Local Upstox token removed. Dhan and Zerodha were not changed.')
      await refreshConnections()
      await getExpiries()
    }catch(e){setConnectionNotice(readableError(e))}
    finally{setUpstoxBusy(false)}
  }
  const getExpiries=useCallback(async()=>{
    setExpiryBusy(true);setExpiryError('')
    try{
      const data=await marketApi<Expiries>(
        '/api/trading-cockpit/options/coverage/expiries?'+
        new URLSearchParams({underlying,provider:providerChoice}))
      setDates(data)
      setExpiry(last=>data.expiries.includes(last)?last:data.nearest_expiry)
    }catch(e){setExpiryError(readableError(e))}
    finally{setExpiryBusy(false)}
  },[underlying,providerChoice])
  useEffect(()=>{void getExpiries()},[getExpiries])
  const getChain=useCallback(async(forceRefresh=false)=>{
    if(!expiry)return
    setBusy(true);setError('')
    try{
      const data=await marketApi<Chain>(
        '/api/trading-cockpit/options/coverage/chain?'+new URLSearchParams({
          expiry,underlying,provider:providerChoice,
          ...(forceRefresh?{force_refresh:'true'}:{}),
        }))
      setChain(data)
      setSelected(previous=>data.contracts.some(c=>c.identity===previous&&c.contract_master_verified)
        ?previous:'')
    }catch(e){setError(readableError(e))}
    finally{setBusy(false)}
  },[expiry,underlying,providerChoice])
  useEffect(()=>{
    if(!expiry)return
    void getChain()
    const poll=window.setInterval(()=>{
      if(document.visibilityState==='visible')void getChain()
    },20_000)
    return()=>window.clearInterval(poll)
  },[expiry,getChain])
  const refreshMaster=async()=>{
    if(masterJobId)return
    setMasterNotice('')
    try{
      const response=await marketPost<{job_id:string}>('/api/dhan/instruments/refresh',{})
      setMasterJobId(response.job_id)
      setMasterNotice('Refreshing original Dhan instrument master in the local Data Library…')
    }catch(e){setMasterNotice('Dhan master refresh failed to start: '+readableError(e))}
  }
  useEffect(()=>{
    if(!masterJobId)return
    let mounted=true
    let running=false
    const poll=async()=>{
      if(running)return
      running=true
      try{
        const job=await marketApi<{status:string;error?:string}>(
          '/api/jobs/'+encodeURIComponent(masterJobId))
        if(!mounted)return
        if(job.status==='complete'){
          setMasterNotice('Original Dhan instrument master refreshed. Rechecking contract lot sizes and security IDs.')
          setMasterJobId('')
          await getChain(true)
        }else if(['error','cancelled','interrupted'].includes(job.status)){
          setMasterNotice('Instrument master update failed: '+(job.error||job.status))
          setMasterJobId('')
        }
      }catch(e){if(mounted){setMasterNotice('Could not check instrument master refresh: '+readableError(e));setMasterJobId('')}}
      finally{running=false}
    }
    void poll()
    const poller=window.setInterval(()=>{void poll()},2000)
    return()=>{mounted=false;window.clearInterval(poller)}
  },[masterJobId,getChain])
  useEffect(()=>{
    const clock=window.setInterval(()=>setNow(Date.now()),1000)
    return()=>window.clearInterval(clock)
  },[])
  const filtered=useMemo(()=>{
    const rows=(chain?.expiry===expiry&&chain.underlying===underlying?chain.contracts:[]).filter(c=>
      (side==='ALL'||c.option_type===side)&&
      (!nearTargetOnly||(c.ltp!==null&&Math.abs(c.ltp-targetPremium)<=premiumTolerance)))
    return [...rows].sort((a,b)=>{
      // Closest to preferred premium first; ties resolved by strike and type.
      const aPrice=a.ltp===null?Number.POSITIVE_INFINITY:Math.abs(a.ltp-targetPremium)
      const bPrice=b.ltp===null?Number.POSITIVE_INFINITY:Math.abs(b.ltp-targetPremium)
      return aPrice-bPrice||a.strike-b.strike||a.option_type.localeCompare(b.option_type)
    })
  },[chain,expiry,underlying,side,nearTargetOnly,targetPremium,premiumTolerance])
  const picked=chain?.expiry===expiry&&chain.underlying===underlying
    ?chain.contracts.find(c=>c.identity&&c.identity===selected):null
  const valid=Boolean(picked?.contract_master_verified&&picked?.quote_valid&&
    picked.ask!==null&&picked.lot_size!==null)
  const units=valid?lots*picked!.lot_size!:0
  const totalAsk=valid?units*picked!.ask!:null
  const totalBid=valid&&picked!.bid!==null?units*picked!.bid!:null
  const spread=totalAsk!==null&&totalBid!==null?totalAsk-totalBid:null
  const maxLots=(picked&&valid&&picked.ask&&picked.lot_size)
    ?Math.floor(capital/(picked.ask*picked.lot_size)):0
  const matchingPremiumCount=(chain?.expiry===expiry&&chain.underlying===underlying?chain.contracts:[]).filter(c=>
    (side==='ALL'||c.option_type===side)&&c.ltp!==null&&
    Math.abs(c.ltp-targetPremium)<=premiumTolerance).length
  const age=chain?.received_utc?Math.max(0,Math.round((now-Date.parse(chain.received_utc))/1000)):null
  const bookCurrent=Boolean(picked?.identity&&picked.identity===depthIdentity)
  const mapSignal=underlying==='BANKNIFTY'&&currentIndexDirection==='UP'?'CE':
    underlying==='BANKNIFTY'&&currentIndexDirection==='DOWN'?'PE':null
  return <section className="oc-root" aria-label="Index option chain and lot calculator">
    <header className="oc-head"><div><span className="tc-page-kicker">READ-ONLY ORIGINAL OPTIONS / MULTIPLE SOURCES</span>
      <h3>{underlying==='BANKNIFTY'?'BANKNIFTY':'NIFTY 50'} CE / PE option chain</h3>
      <p>Browse every source-reported active expiry and all returned strikes.
        Dhan remains the reference for original 20-level depth and tradeable exchange IDs;
        providers' snapshot prices are never mixed into a synthetic best bid/ask.</p>
    </div><span className="oc-source"><ShieldCheck size={15}/> Read-only · no orders</span></header>
    <section className="oc-provider-panel" aria-label="Multiple market data connections">
      <div className="oc-provider-heading">
        <div><strong>Market-data connections</strong>
          <small>Connect multiple providers. Each contributes only capabilities it actually supports.</small></div>
        <button type="button" className="oc-connection-button" onClick={openConnections}>
          Manage Dhan / Zerodha <ArrowRight size={14}/></button>
        <button type="button" className="oc-connection-button"
          aria-expanded={upstoxOpen} onClick={()=>setUpstoxOpen(v=>!v)}>
          {upstoxOpen?'Hide Upstox setup':'Connect Upstox'}</button>
      </div>
      <div className="oc-provider-cards">
        {connections?.providers.map(item=><div className="oc-provider-card" key={item.id}>
          <strong>{item.label}</strong><span className={item.configured?'connected':'missing'}>
            {item.configured?'Configured · live session not assumed':'Not configured'}</span>
          <small>{item.note}</small>
        </div>)}
        {!connections&&<p>Checking configured source connections…</p>}
      </div>
      {connectionNotice&&<div className="oc-timestamp" role="status">{connectionNotice}</div>}
      {upstoxOpen&&<form className="oc-provider-form" onSubmit={e=>void connectUpstox(e)}>
        <label>Authorized Upstox access token
          <input aria-label="Upstox access token" type="password" autoComplete="off"
            value={upstoxToken} minLength={16} maxLength={4096}
            onChange={e=>setUpstoxToken(e.target.value)}
            placeholder="Manually generated token from your Upstox developer app"/>
        </label>
        <label className="oc-provider-confirm">
          <input type="checkbox" checked={upstoxConsent}
            onChange={e=>setUpstoxConsent(e.target.checked)}/>
          Store privately on this workstation (0600 permissions). Use for read-only
          current-option contracts and chain requests, never orders.
        </label>
        <div className="oc-controls-actions">
          <button type="submit" disabled={!upstoxConsent||!upstoxToken||upstoxBusy}>
            Save Upstox token locally</button>
          {connections?.providers.some(p=>p.id==='upstox'&&p.configured)&&
            <button type="button" disabled={upstoxBusy} onClick={()=>void disconnectUpstox()}>
              Disconnect locally saved Upstox token</button>}
        </div>
        <small>Upstox authentication is issued by Upstox. Connection presence
          does not guarantee entitlement or a valid current session.
          Never enter your brokerage login password.</small>
      </form>}
    </section>
    <div className="oc-controls">
      <label>Index underlying
        <select aria-label="Option underlying index" value={underlying}
          onChange={e=>{setUnderlying(e.target.value as 'BANKNIFTY'|'NIFTY50')
            setExpiry('');setDates(null);setChain(null);setSelected('')}}>
          <option value="BANKNIFTY">BANKNIFTY</option>
          <option value="NIFTY50">NIFTY 50</option>
        </select>
      </label>
      <label>Quote source
        <select aria-label="Option chain provider" value={providerChoice}
          onChange={e=>{setProviderChoice(e.target.value as 'all'|'dhan'|'upstox')
            setExpiry('');setDates(null);setChain(null);setSelected('')}}>
          <option value="all">All connected · Dhan preferred</option>
          <option value="dhan">Dhan only</option>
          <option value="upstox">Upstox only</option>
        </select>
      </label>
      <label>Source-listed expiry
        <select aria-label="Option chain expiry" value={expiry}
          onChange={e=>{setExpiry(e.target.value);setChain(null);setSelected('')}}>
          {!dates&&<option value="">Connect a source for current expiries</option>}
          {dates?.expiries.map(x=><option key={x} value={x}>
            {x} · {(dates.expiry_sources?.[x]||[]).join(' + ')}</option>)}
        </select>
      </label>
      <div className="oc-controls-actions">
        <button type="button" onClick={()=>void getExpiries()} disabled={expiryBusy}>
          <Database size={15}/>{expiryBusy?'Checking expiries…':'Refresh expiry list'}</button>
        <button type="button" onClick={()=>void getChain()} disabled={!expiry||busy}>
          <RefreshCw size={15}/>{busy?'Refreshing…':'Refresh option chain'}</button>
        <button type="button" onClick={()=>void refreshMaster()} disabled={Boolean(masterJobId)}>
          <Database size={15}/>{masterJobId?'Updating master…':'Update contract lot sizes'}</button>
      </div>
      <div className="oc-observed">
        <span>Underlying spot <b>{chain?num(chain.underlying_spot)+' pts':'—'}</b></span>
        <span>Snapshot age <b>{age===null?'—':age+'s'}</b></span>
      </div>
    </div>
    {masterNotice&&<p className="oc-timestamp" role="status">{masterNotice}</p>}
    {expiryError&&<div className="oc-alert" role="alert"><AlertTriangle size={18}/>
      <div><strong>No connected provider returned current option expiries.</strong>
        <p>{expiryError}</p></div>
      <button type="button" onClick={openConnections}>Connections <ArrowRight size={14}/></button>
    </div>}
    {error&&<div className="oc-alert" role="alert"><AlertTriangle size={18}/>
      <div><strong>Current option-chain snapshot unavailable</strong>
        <p>{error}</p></div>
    </div>}
    {chain&&<div className="oc-timestamp"><Clock3 size={14}/>
      <strong>Independent REST market-data snapshots, not executable books</strong> ·
      Received {timeIST(chain.received_utc)} IST ·
      {chain.cache_hit?' Cached responses reused':' Read original vendor responses'} ·
      Quote sources: {(chain.providers_used||[]).join(' + ')} ·
      Contract counts: {Object.entries(chain.provider_contract_counts||{}).map(([key,value])=>
        key+' '+value).join(', ')} · Union {chain.quote_count}.
      Dhan master {chain.market_master_fresh?'recent':'missing / outdated'}.
      Provider quotes may have different capture times.</div>}
    {chain&&Object.keys(chain.provider_errors||{}).length>0&&
      <div className="oc-alert" role="status"><AlertTriangle size={16}/>
        Some providers could not respond: {Object.entries(chain.provider_errors||{}).map(
          ([key,value])=>key+': '+value).join('; ')}.
        The displayed rows are from providers that did respond.</div>}
    {dates&&Object.keys(dates.provider_errors||{}).length>0&&
      <div className="oc-alert" role="status"><AlertTriangle size={16}/>
        Expiry discovery unavailable for: {Object.entries(dates.provider_errors||{}).map(
          ([key,value])=>key+': '+value).join('; ')}</div>}
    {chain&&(chain.source_identity_conflicts||0)>0&&
      <div className="oc-alert" role="alert"><AlertTriangle size={16}/>
        {chain.source_identity_conflicts} contract identities disagreed between providers.
        Their quotes were kept separate; refresh official masters before selecting.</div>}
    {chain&&!chain.market_master_fresh&&<p className="oc-alert" role="status">
      <AlertTriangle size={16}/>
      {chain.master_message} Refresh the official Dhan instrument master from Data Library
      before relying on contract quantity or lot-based premium calculations.</p>}
    <div className="oc-filter">
      <strong>All {chain?.quote_count??0} source-reported current CE / PE contracts · {filtered.length} displayed</strong>
      <div role="group" aria-label="Option-chain contract type">
        {(['ALL','CE','PE'] as const).map(kind=><button key={kind}
          type="button" aria-pressed={side===kind} onClick={()=>setSide(kind)}>
          {kind==='ALL'?'All contracts':kind}</button>)}
      </div>
      <span>Signal: <b>{underlying==='BANKNIFTY'?(currentIndexDirection||'Not ready'):'Not tracked for this index'}</b>
        {mapSignal?' · '+mapSignal+' contracts are one possible long-options expression':' · no contract suggestion'}</span>
    </div>
    <div className="oc-preferences">
      <strong>Preferred scalp setup · adjustable, never a guaranteed fill</strong>
      <label>Target option LTP (₹)
        <input aria-label="Preferred option LTP" type="number" min={1} max={100000}
          value={targetPremium} onChange={e=>setTargetPremium(Math.max(1,Number(e.target.value)||1))}/>
      </label>
      <label>Premium range ± ₹
        <input aria-label="Preferred premium tolerance" type="number" min={0} max={10000}
          value={premiumTolerance} onChange={e=>setPremiumTolerance(Math.max(0,Number(e.target.value)||0))}/>
      </label>
      <label className="oc-preference-checkbox">
        <input type="checkbox" checked={nearTargetOnly}
          onChange={e=>setNearTargetOnly(e.target.checked)}/>
        Only show premiums near target
      </label>
      <span>{matchingPremiumCount} matching contract(s). Sorted closest to ₹{num(targetPremium)} LTP. Bid/ask, spread and liquidity still matter.</span>
    </div>
    <div className="tc-table-scroll oc-table">
      <table><thead><tr><th>Choose</th><th>Strike</th><th>Type</th>
        <th>LTP ₹</th><th>Bid ₹</th><th>Ask ₹</th><th>OI</th><th>Volume</th>
        <th>IV %</th><th>Delta</th><th>Lot size</th><th>Verified ID</th>
        <th>Price source</th></tr></thead>
        <tbody>{filtered.map(c=>{
          const atm=chain&&Math.abs(c.strike-chain.underlying_spot)<100
          return <tr key={c.option_type+':'+c.strike}
            className={(selected&&c.identity===selected?'oc-chosen ':'')+(atm?'oc-near-atm':'')}>
            <td><input type="radio" name="oc-selected" aria-label={'Select '+c.strike+' '+c.option_type}
              checked={Boolean(c.identity&&selected===c.identity)}
              disabled={!c.contract_master_verified||!c.identity}
              onChange={()=>{setSelected(c.identity||'');setLots(3)}}/></td>
            <td>{num(c.strike,0)} {atm&&<small>ATM vicinity</small>}</td>
            <td><span className={'tc-direction '+(c.option_type==='CE'?'up':'down')}>{c.option_type}</span></td>
            <td>{num(c.ltp)}</td><td>{num(c.bid)}</td><td>{num(c.ask)}</td>
            <td>{num(c.oi,0)}</td><td>{num(c.volume,0)}</td><td>{num(c.iv,2)}</td>
            <td>{num(c.delta,3)}</td><td>{c.lot_size??'Unverified'}</td>
            <td>{c.identity||'—'}</td>
            <td title={c.source_received_utc?
              'Received '+timeIST(c.source_received_utc)+' IST':''}>
              {c.quote_provider||'dhan'}{(c.available_sources?.length||0)>1?
                <small>also {(c.available_sources||[]).filter(p=>p!==c.quote_provider).join(', ')}</small>:null}
            </td>
          </tr>
        })}
        {!filtered.length&&<tr><td colSpan={13}>
          {busy?'Loading original connected option chains…':nearTargetOnly?'No contracts in the preferred premium range. Widen the range or turn off the filter.':'No original contract quotes for the selected expiry. Check provider connection and source coverage.'}
        </td></tr>}</tbody></table>
    </div>
    <div className="oc-preview">
      <div className="oc-preview-title">
        <div><span className="tc-page-kicker">SELECT A REAL CONTRACT</span>
          <h4>{picked?picked.symbol+' · '+picked.expiry:
            'Select an available CE or PE to calculate lots'}</h4>
          <p>{picked?picked.identity+' · '+picked.option_type+' '+num(picked.strike,0)+
            ' · Quote source '+(picked.quote_provider||'dhan'):'The index cannot be bought or sold as a direct position.'}</p>
          <p>Default 3 lots · currently around {picked?.lot_size===30?'90':'3 × verified lot size'} units · preferred LTP ₹{num(targetPremium)}. Exact premium is based on the ask, not LTP.</p>
        </div>
        <span className="oc-source">{bookCurrent?'Selected for order book':'No order-book subscription selected'}</span>
      </div>
      <div className="oc-lot-inputs">
        <label>Lots <input type="number" aria-label="BANKNIFTY option lots"
          min={1} max={50} step={1} value={lots}
          onChange={e=>setLots(Math.max(1,Math.min(50,Math.trunc(Number(e.target.value)||1))))}/></label>
        <label>Paper capital (₹) <input type="number" aria-label="Option paper capital"
          min={1000} max={100000000} step={1000} value={capital}
          onChange={e=>setCapital(Math.max(1000,Math.min(100000000,Number(e.target.value)||1000)))}/></label>
        <div><span>Units</span><b>{valid?num(units,0):'—'}</b></div>
        <div><span>Premium required at ask</span><b>{money(totalAsk)}</b></div>
        <div><span>Immediate bid / ask spread cost</span><b>{money(spread)}</b></div>
        <div><span>Affordable lots at current ask</span><b>{valid?num(maxLots,0):'—'}</b></div>
      </div>
      {picked&&valid&&totalAsk!==null&&totalAsk>capital&&<p className="oc-alert" role="status">
        This paper position requires {money(totalAsk)}, more than the selected
        {money(capital)} budget, before fees. Reduce lots or change contract.
      </p>}
      <div className="oc-preview-actions">
        <button type="button" disabled={!picked?.identity||!picked.contract_master_verified||
          (feedActive&&!bookCurrent)} onClick={()=>{if(picked?.identity)onSelectDepth(picked.identity)}}>
          <TrendingUp size={16}/>{bookCurrent?'Current 20-level target':
            feedActive?'Stop current stream to change instrument':'Use for live 20-level depth'}
        </button>
        <button type="button" className="oc-secondary" disabled={!valid||totalAsk===null||
          totalAsk>capital||!picked} onClick={()=>{if(picked)onDraftJournal(picked,lots)}}>
          Prepare manual journal entry <ArrowRight size={15}/>
        </button>
      </div>
      <p className="tc-muted">Paper premium = observed best ask × selected lots × official lot size; the bid/ask spread
        is an immediate crossing-cost illustration, not an executed fill. Confirm the actual
        price and quantity with your broker. Selecting a contract does not send an order.</p>
    </div>
  </section>
}
