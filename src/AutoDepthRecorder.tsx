import {useCallback,useEffect,useRef,useState} from 'react'
import {Activity,AlertTriangle,Database,History,PauseCircle,Radio,ShieldCheck} from 'lucide-react'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
import './auto-depth-recorder.css'

type Settings={
  enabled:boolean;target_premium:number;tolerance:number
  selection_mode?:string
  per_side:number;lots:number;sample_seconds:number;allow_token_renewal:boolean
}
type Candidate={
  identity:string;side:'CE'|'PE';strike:number;expiry:string
  wing?:'above'|'below';atm_strike?:number
  lot_size:number;ltp:number;chain_received_utc:string;volume:number
}
type Latest={
  side:'CE'|'PE';received_utc:string;age_seconds:number;fresh:boolean
  lots:number;units:number;spread_bps:number;book_imbalance_20:number
  bid_quantity_20:number;ask_quantity_20:number
  bid_levels:number;ask_levels:number;full_20_levels:boolean
  best_bid:number;best_ask:number
  buy_vwap_for_units:number|null;sell_vwap_for_units:number|null
}
type Recorder={
  armed:boolean;state:string;connected:boolean
  market_regular_hours:boolean;settings:Settings;session_id:string|null
  snapshots_saved:number;received_pairs:number;invalid_pairs:number
  selection_events:number;last_error:string|null
  last_packet_utc:string|null;last_chain_utc:string|null
  current_expiry?:string;chain_spot?:number;atm_strike?:number
  contracts_above?:number;contracts_below?:number
  sockets_connected?:number;sockets_requested?:number
  dropped_depth_samples?:number
  selection_warning?:string|null;contracts:Candidate[]
  latest:Record<string,Latest>;read_only:boolean
  historical_depth_download_supported:boolean
}
type AutomaticChainCapture={
  armed:boolean;state:string;snapshot_count_session:number
  snapshots_saved_today:number;expiries_found:number
  expiries_captured_session:number;last_expiry:string|null
  last_snapshot_utc:string|null;last_strike_count:number
  last_quote_count:number;last_error:string|null
  token_maintenance:string;token_maintenance_message:string|null
  token_renewal_opted_in:boolean
  capture_schedule_seconds:{nearest_two:number;next_four:number;remaining:number}
}
const DEFAULT_SETTINGS:Settings={
  enabled:false,target_premium:300,tolerance:75,per_side:2,lots:3,sample_seconds:30,
  selection_mode:"atm_contracts_100_each",
  allow_token_renewal:false,
}
const inr=(value:number|null|undefined, digits=2)=>value===null||value===undefined
  ?'—':'₹'+value.toLocaleString('en-IN',{maximumFractionDigits:digits})
const n=(value:number|null|undefined,digits=0)=>value===null||value===undefined
  ?'—':value.toLocaleString('en-IN',{maximumFractionDigits:digits})
const clock=(value?:string|null)=>value
  ?new Date(value).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',
    month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'})
  :'—'
const STATE_NAME:Record<string,string>={
  disabled:'Stopped',
  stopping:'Stopping feed',
  armed_waiting_for_nse_hours:'Armed · waiting for NSE session',
  selecting_verified_ce_pe:'Selecting CE/PE from Dhan',
  no_eligible_option_contracts:'No verified CE/PE ATM-wing contracts',
  connected_waiting_for_packets:'Subscribed · awaiting original depth',
  recording_original_depth:'Recording original 20-level books',
  connected_no_depth_packets:'Connected · no fresh depth packets',
  daily_storage_limit_reached:'Daily storage safety limit reached',
  connection_or_source_error:'Data source needs attention',
  other_local_worker:'Other local QuantLab server is recording',
  local_server_stopping:'Local server stopping',
}

export default function AutoDepthRecorder({onOpenSaved}:{
  onOpenSaved?:()=>void
}){
  const [state,setState]=useState<Recorder|null>(null)
  const [chainCapture,setChainCapture]=useState<AutomaticChainCapture|null>(null)
  const [settings,setSettings]=useState<Settings>(DEFAULT_SETTINGS)
  const settingsInitialized=useRef(false)
  const [armedConsent,setArmedConsent]=useState(false)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')
  const refresh=useCallback(async()=>{
    const [depth,chains]=await Promise.allSettled([
      marketApi<Recorder>('/api/trading-cockpit/auto-depth/status'),
      marketApi<AutomaticChainCapture>('/api/trading-cockpit/auto-chain/status'),
    ])
    if(depth.status==='fulfilled'){
      setState(depth.value)
      if(!settingsInitialized.current){
        setSettings(depth.value.settings)
        settingsInitialized.current=true
      }
    }else setError(readableError(depth.reason))
    if(chains.status==='fulfilled')setChainCapture(chains.value)
  },[])
  useEffect(()=>{
    void refresh()
    const timer=window.setInterval(()=>{void refresh()},7000)
    return()=>window.clearInterval(timer)
  },[refresh])
  const arm=async()=>{
    if(busy||!armedConsent)return
    setBusy(true);setError('');setNotice('')
    try{
      const result=await marketPost<Recorder>(
        '/api/trading-cockpit/auto-depth/arm',
        {
          target_premium:settings.target_premium,tolerance:settings.tolerance,
          selection_mode:"atm_contracts_100_each",
          per_side:settings.per_side,lots:settings.lots,
          sample_seconds:settings.sample_seconds,
          allow_token_renewal:settings.allow_token_renewal,
          confirm_live_data:true,
        })
      setState(result);setSettings(result.settings);setArmedConsent(false)
      setNotice(result.market_regular_hours
        ?'Recorder armed. Waiting for original Dhan CE/PE depth packets.'
        :'Recorder armed for the next regular NSE session while QuantLab is running.')
    }catch(e){setError(readableError(e))}
    finally{setBusy(false)}
  }
  const disarm=async()=>{
    if(busy)return
    setBusy(true);setError('');setNotice('')
    try{
      const result=await marketPost<Recorder>(
        '/api/trading-cockpit/auto-depth/disarm',{})
      setState(result);setSettings(result.settings)
      setNotice('Automatic depth recording disarmed. Original saved books remain available.')
    }catch(e){setError(readableError(e))}
    finally{setBusy(false)}
  }
  const armed=Boolean(state?.armed)
  const connected=Boolean(state?.connected)
  return <section className="ad-root" aria-label="Automatic BANKNIFTY 20-level order-book recorder">
    <header className="ad-head">
      <div>
        <span className="tc-page-kicker">AUTOMATIC LIVE DATA COLLECTION</span>
        <h3><Activity size={19}/> Record BANKNIFTY CE &amp; PE order books</h3>
        <p>Automatically follow 100 verified option contracts above BANKNIFTY's
          nearest listed ATM strike and 100 below it: 50 CE and 50 PE on each
          side. Four Dhan depth sockets capture up to 200 live 20-level books.
          The full CE/PE option chain is archived separately. No orders are sent.</p>
      </div>
      <span className={'ad-status '+(connected?'active':armed?'armed':'stopped')}>
        <Radio size={15}/>{STATE_NAME[state?.state||'disabled']||state?.state||'Stopped'}
      </span>
    </header>

    <div className="ad-controls" aria-label="Automatic order-book recording configuration">
      <div className="ad-armed-note" role="note">
        <strong>Automatic coverage: 100 contracts above + 100 below ATM</strong>
        <div>50 listed strikes per direction × CE and PE = 200 contracts total.
          Missing verified contracts are reported rather than simulated.</div>
      </div>
      <label>Lots to evaluate
        <input aria-label="Auto depth lots" type="number" min={1} max={20} step={1}
          disabled={armed} value={settings.lots}
          onChange={e=>setSettings(x=>({...x,lots:Number(e.target.value)}))}/>
      </label>
      <label>Broad depth save interval
        <select aria-label="Auto depth sample interval" disabled={armed}
          value={settings.sample_seconds}
          onChange={e=>setSettings(x=>({...x,sample_seconds:Number(e.target.value)}))}>
          <option value={30}>30 seconds per contract</option>
          <option value={45}>45 seconds per contract</option>
          <option value={60}>60 seconds per contract</option>
        </select>
      </label>
      <small>Nearest above-ATM and below-ATM CE/PE contracts are sampled every 3 seconds.
        Every other selected contract is sampled at the broad interval. All
        selected contracts stay subscribed while the NSE market is open.</small>
    </div>
    <div className="ad-actions">
      {!armed?<label className="ad-consent">
        <input type="checkbox" checked={settings.allow_token_renewal}
          onChange={e=>setSettings(current=>({...current,allow_token_renewal:e.target.checked}))}/>
        Optional: automatically renew my still-valid Dhan-Web access token before it expires.
        Dhan invalidates the old token on renewal; other apps using it may need to reconnect.
      </label>:null}
      {!armed?<label className="ad-consent">
        <input type="checkbox" checked={armedConsent}
          onChange={e=>setArmedConsent(e.target.checked)}/>
        Allow my local QuantLab server to automatically subscribe to and record original
        Dhan market-depth data for 100 contracts above and 100 below ATM and archive the complete
        returned BANKNIFTY option chains for listed expiries during future regular
        NSE sessions, until I stop it.
      </label>:<p className="ad-armed-note"><ShieldCheck size={16}/>
        Read-only BANKNIFTY CE/PE recording runs automatically during NSE hours
        while the local server is running. Stop and disarm to disable future sessions.</p>}
      <div className="ad-buttons">
        {!armed?<button type="button" className="ad-start"
          onClick={()=>void arm()} disabled={busy||!armedConsent}>
          <Radio size={15}/>{busy?'Arming…':'Arm automatic 20-level recording'}</button>
        :<button type="button" className="ad-stop" onClick={()=>void disarm()} disabled={busy}>
          <PauseCircle size={15}/>{busy?'Stopping…':'Stop and disarm recording'}</button>}
        <button type="button" onClick={()=>void refresh()} disabled={busy}>Refresh status</button>
        {onOpenSaved&&<button type="button" onClick={onOpenSaved}>
          <History size={15}/> Review saved depth</button>}
      </div>
    </div>
    {error&&<p className="ad-error" role="alert"><AlertTriangle size={15}/>{error}</p>}
    {notice&&<p className="ad-notice" role="status">{notice}</p>}
    {state?.last_error&&<p className="ad-error" role="status">
      <AlertTriangle size={15}/>{state.last_error}</p>}
    {state?.selection_warning&&<p className="ad-warning" role="status">
      {state.selection_warning}; historical books are never fabricated.</p>}
    <div className="ad-summary">
      <span><strong>{n(state?.snapshots_saved)}</strong> books stored this session</span>
      <span><strong>{n(state?.received_pairs)}</strong> observed source packet pairs</span>
      <span><strong>{state?.contracts.length??0}/200</strong> verified contracts selected</span>
      <span><strong>{state?.contracts_above??0} / {state?.contracts_below??0}</strong> above / below ATM</span>
      <span><strong>{state?.sockets_connected??0} / {state?.sockets_requested??0}</strong> live Dhan depth sockets</span>
      <span><strong>{state?.current_expiry||'—'}</strong> Dhan-listed expiry</span>
      <span><strong>{clock(state?.last_packet_utc)}</strong> most recent paired packet (IST)</span>
    </div>
    <p className="ad-armed-note" role="status">
      <Database size={16}/> Complete option-chain archive: <strong>{chainCapture?.state||'Checking status'}</strong>
      {' · '}{n(chainCapture?.snapshots_saved_today)} chain snapshots saved today
      {' · '}{n(chainCapture?.expiries_captured_session)} / {n(chainCapture?.expiries_found)} expiries observed this session.
      {chainCapture?.last_snapshot_utc&&<> Latest: {chainCapture.last_expiry}
        {' · '}{n(chainCapture.last_strike_count)} strikes
        {' · '}{n(chainCapture.last_quote_count)} CE/PE quotes
        {' · '}{clock(chainCapture.last_snapshot_utc)} IST.</>}
      {chainCapture?.last_error&&<span className="ad-warning"> {chainCapture.last_error}</span>}
      {chainCapture?.token_renewal_opted_in&&<span> Token maintenance: {chainCapture.token_maintenance_message||"checking"}.</span>}
    </p>
    <div className="ad-contracts">
      {state?.contracts.length?<><p className="ad-armed-note">
        Showing the eight nearest subscribed CE/PE contracts. All {state.contracts.length}
        selected contracts are recorded in the shared Market Library; open
        Market Replay to review their saved 20-level depth.
        {Boolean(state.dropped_depth_samples)&&
          <> {n(state.dropped_depth_samples)} samples were skipped because
          local storage could not keep up.</>}
      </p>{[...state.contracts.filter(x=>x.wing==='above').slice(0,4),
        ...state.contracts.filter(x=>x.wing==='below').slice(0,4)].map(contract=>{
        const live=state.latest[contract.identity]
        return <article className="ad-contract" key={contract.identity}>
          <div className="ad-contract-title">
            <strong className={contract.side==='CE'?'ce':'pe'}>{contract.side}</strong>
            <strong>{n(contract.strike,0)} strike{contract.wing?' · '+contract.wing+' ATM':''}</strong>
            <span>{contract.identity} · {contract.expiry}</span>
            <small>Chain LTP {inr(contract.ltp)}</small>
          </div>
          {live?<div className="ad-book-grid">
            <span>Best bid / ask <strong>{inr(live.best_bid)} / {inr(live.best_ask)}</strong></span>
            <span>Spread <strong>{n(live.spread_bps,1)} bps</strong></span>
            <span>20-level bid share <strong>{n((live.book_imbalance_20+1)*50,1)}%</strong></span>
            <span>Buy {live.units} units <strong>{inr(live.buy_vwap_for_units)}</strong></span>
            <span>Sell {live.units} units <strong>{inr(live.sell_vwap_for_units)}</strong></span>
            <span>Packet age <strong className={live.fresh?'ad-fresh':'ad-stale'}>
              {n(live.age_seconds,0)}s · {live.fresh?'fresh':'stale'}</strong></span>
          </div>:<p className="ad-empty-contract">
            Waiting for an original bid+ask 20-level packet; selection alone does not prove depth access.
          </p>}
          <small className="ad-lot-note">{settings.lots} lots × verified {contract.lot_size}
            {' '}units = {settings.lots*contract.lot_size} units · local receive clock</small>
        </article>
      })}</>:<div className="ad-empty-contract">
        <Database size={16}/> No current verified CE/PE subscriptions.
        {!armed?' Arm the recorder to begin when the NSE market is open.':
          ' QuantLab will select contracts automatically from the official Dhan chain.'}
      </div>}
    </div>
    <p className="ad-disclaimer">
      <ShieldCheck size={15}/> Read-only research. Dhan option-chain prices select
      contracts; the live 20-level WebSocket supplies actual books. Displayed
      quantities and depth-weighted prices are hypothetical liquidity estimates,
      not guaranteed executions or historical downloads. The backend must remain
      running; full-depth entitlement is required only for 20-level books, not
      ordinary option-chain snapshots. Captured snapshots
      remain available under Market Replay, even after stopping.
    </p>
  </section>
}
