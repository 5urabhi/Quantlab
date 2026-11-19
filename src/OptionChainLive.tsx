import {useCallback,useEffect,useMemo,useState} from 'react'
import {AlertTriangle,ArrowRight,Clock3,Database,RefreshCw,ShieldCheck,TrendingUp} from 'lucide-react'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
import './option-chain-live.css'

type Expiries={
  underlying:string;expiries:string[];nearest_expiry:string;
  received_utc:string;source:string
}
export type OptionContract={
  identity:string|null;symbol:string;strike:number;expiry:string;option_type:'CE'|'PE'
  lot_size:number|null;contract_master_verified:boolean
  bid:number|null;ask:number|null;ltp:number|null
  top_bid_quantity:number|null;top_ask_quantity:number|null
  oi:number|null;volume:number|null;iv:number|null
  delta:number|null;theta:number|null;gamma:number|null;vega:number|null
  quote_valid:boolean;one_lot_ask_inr:number|null
  one_lot_bid_inr:number|null;spread_inr_per_lot:number|null
}
type Chain={
  underlying:string;underlying_spot:number;expiry:string;received_utc:string
  source:string;source_clock:string;not_live_stream:boolean
  market_master_fresh:boolean;master_message:string;master_age_hours:number|null
  contracts:OptionContract[];quote_count:number;read_only:boolean
  warning:string;cache_hit:boolean
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
  const [dates,setDates]=useState<Expiries|null>(null)
  const [expiry,setExpiry]=useState('')
  const [chain,setChain]=useState<Chain|null>(null)
  const [selected,setSelected]=useState<string>('')
  const [side,setSide]=useState<'ALL'|'CE'|'PE'>('ALL')
  const [lots,setLots]=useState(1)
  const [capital,setCapital]=useState(50_000)
  const [busy,setBusy]=useState(false)
  const [expiryBusy,setExpiryBusy]=useState(false)
  const [error,setError]=useState('')
  const [expiryError,setExpiryError]=useState('')
  const [masterJobId,setMasterJobId]=useState('')
  const [masterNotice,setMasterNotice]=useState('')
  const [now,setNow]=useState(Date.now())
  const getExpiries=useCallback(async()=>{
    setExpiryBusy(true);setExpiryError('')
    try{
      const data=await marketApi<Expiries>('/api/trading-cockpit/options/expiries')
      setDates(data)
      setExpiry(last=>data.expiries.includes(last)?last:data.nearest_expiry)
    }catch(e){setExpiryError(readableError(e))}
    finally{setExpiryBusy(false)}
  },[])
  useEffect(()=>{void getExpiries()},[getExpiries])
  const getChain=useCallback(async(forceRefresh=false)=>{
    if(!expiry)return
    setBusy(true);setError('')
    try{
      const data=await marketApi<Chain>(
        '/api/trading-cockpit/options/chain?'+new URLSearchParams({
          expiry,...(forceRefresh?{force_refresh:'true'}:{}),
        }))
      setChain(data)
      setSelected(previous=>data.contracts.some(c=>c.identity===previous&&c.contract_master_verified)
        ?previous:'')
    }catch(e){setError(readableError(e))}
    finally{setBusy(false)}
  },[expiry])
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
    const rows=(chain?.expiry===expiry?chain.contracts:[]).filter(c=>
      side==='ALL'||c.option_type===side)
    return [...rows].sort((a,b)=>a.strike-b.strike||
      a.option_type.localeCompare(b.option_type))
  },[chain,expiry,side])
  const picked=chain?.expiry===expiry
    ?chain.contracts.find(c=>c.identity&&c.identity===selected):null
  const valid=Boolean(picked?.contract_master_verified&&picked?.quote_valid&&
    picked.ask!==null&&picked.lot_size!==null)
  const units=valid?lots*picked!.lot_size!:0
  const totalAsk=valid?units*picked!.ask!:null
  const totalBid=valid&&picked!.bid!==null?units*picked!.bid!:null
  const spread=totalAsk!==null&&totalBid!==null?totalAsk-totalBid:null
  const maxLots=(picked&&valid&&picked.ask&&picked.lot_size)
    ?Math.floor(capital/(picked.ask*picked.lot_size)):0
  const age=chain?.received_utc?Math.max(0,Math.round((now-Date.parse(chain.received_utc))/1000)):null
  const bookCurrent=Boolean(picked?.identity&&picked.identity===depthIdentity)
  const mapSignal=currentIndexDirection==='UP'?'CE':
    currentIndexDirection==='DOWN'?'PE':null
  return <section className="oc-root" aria-label="BANKNIFTY option chain and lot calculator">
    <header className="oc-head"><div><span className="tc-page-kicker">TRADE THE CONTRACT, NOT THE INDEX</span>
      <h3>BANKNIFTY CE / PE option chain</h3>
      <p>Current Dhan option snapshots, real contract IDs and exchange lot sizes.
        Subscribe separately to one selected NSE_FNO contract for live 20-level depth.</p>
    </div><span className="oc-source"><ShieldCheck size={15}/> Read-only · no orders</span></header>
    <div className="oc-controls">
      <label>Expiry from Dhan
        <select aria-label="Dhan BANKNIFTY expiry" value={expiry}
          onChange={e=>{setExpiry(e.target.value);setChain(null);setSelected('')}}>
          {!dates&&<option value="">Connect Dhan for current expiries</option>}
          {dates?.expiries.map(x=><option key={x} value={x}>{x}</option>)}
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
      <div><strong>Option-chain connection requires Dhan credentials.</strong>
        <p>{expiryError}</p></div>
      <button type="button" onClick={openConnections}>Connections <ArrowRight size={14}/></button>
    </div>}
    {error&&<div className="oc-alert" role="alert"><AlertTriangle size={18}/>
      <div><strong>Current option-chain snapshot unavailable</strong>
        <p>{error}</p></div>
    </div>}
    {chain&&<div className="oc-timestamp"><Clock3 size={14}/>
      <strong>Dhan REST snapshot, not a live streaming book</strong> ·
      Received {timeIST(chain.received_utc)} IST ·
      {chain.cache_hit?' Reused cached response':' Original vendor response'} ·
      Instrument master {chain.market_master_fresh?'recent':'missing / outdated'}.
      Market data may have changed since capture.</div>}
    {chain&&!chain.market_master_fresh&&<p className="oc-alert" role="status">
      <AlertTriangle size={16}/>
      {chain.master_message} Refresh the official Dhan instrument master from Data Library
      before relying on contract quantity or lot-based premium calculations.</p>}
    <div className="oc-filter">
      <strong>Listed strikes near the observed spot</strong>
      <div role="group" aria-label="Option-chain contract type">
        {(['ALL','CE','PE'] as const).map(kind=><button key={kind}
          type="button" aria-pressed={side===kind} onClick={()=>setSide(kind)}>
          {kind==='ALL'?'All contracts':kind}</button>)}
      </div>
      <span>Signal: <b>{currentIndexDirection||'Not ready'}</b>
        {mapSignal?' · '+mapSignal+' contracts are one possible long-options expression':' · no contract suggestion'}</span>
    </div>
    <div className="tc-table-scroll oc-table">
      <table><thead><tr><th>Choose</th><th>Strike</th><th>Type</th>
        <th>LTP ₹</th><th>Bid ₹</th><th>Ask ₹</th><th>OI</th><th>Volume</th>
        <th>IV %</th><th>Delta</th><th>Lot size</th><th>Verified ID</th></tr></thead>
        <tbody>{filtered.map(c=>{
          const atm=chain&&Math.abs(c.strike-chain.underlying_spot)<100
          return <tr key={c.option_type+':'+c.strike}
            className={(selected&&c.identity===selected?'oc-chosen ':'')+(atm?'oc-near-atm':'')}>
            <td><input type="radio" name="oc-selected" aria-label={'Select '+c.strike+' '+c.option_type}
              checked={Boolean(c.identity&&selected===c.identity)}
              disabled={!c.contract_master_verified||!c.identity}
              onChange={()=>{setSelected(c.identity||'');setLots(1)}}/></td>
            <td>{num(c.strike,0)} {atm&&<small>ATM vicinity</small>}</td>
            <td><span className={'tc-direction '+(c.option_type==='CE'?'up':'down')}>{c.option_type}</span></td>
            <td>{num(c.ltp)}</td><td>{num(c.bid)}</td><td>{num(c.ask)}</td>
            <td>{num(c.oi,0)}</td><td>{num(c.volume,0)}</td><td>{num(c.iv,2)}</td>
            <td>{num(c.delta,3)}</td><td>{c.lot_size??'Unverified'}</td>
            <td>{c.identity||'—'}</td>
          </tr>
        })}
        {!filtered.length&&<tr><td colSpan={12}>
          {busy?'Loading original Dhan option chain…':'No verified original strikes for the selected expiry. Refresh the chain, token or instrument master.'}
        </td></tr>}</tbody></table>
    </div>
    <div className="oc-preview">
      <div className="oc-preview-title">
        <div><span className="tc-page-kicker">SELECT A REAL CONTRACT</span>
          <h4>{picked?picked.symbol+' · '+picked.expiry:
            'Select an available CE or PE to calculate lots'}</h4>
          <p>{picked?picked.identity+' · '+picked.option_type+' '+num(picked.strike,0):'BANKNIFTY index cannot be bought or sold directly.'}</p>
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
