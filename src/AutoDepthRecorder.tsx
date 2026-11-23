import {useCallback,useEffect,useRef,useState} from 'react'
import {Activity,AlertTriangle,Database,History,PauseCircle,Radio,ShieldCheck} from 'lucide-react'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
import OptionUniverseMonitor from './OptionUniverseMonitor'
import './auto-depth-recorder.css'

type Settings={
  enabled:boolean;target_premium:number;tolerance:number
  selection_mode?:string
  per_side:number;lots:number;sample_seconds:number;allow_token_renewal:boolean
}
type Candidate={
  identity:string;side:'CE'|'PE';strike:number;expiry:string
  wing?:'above'|'below'|'atm';atm_strike?:number;coverage_role?:'core'|'opportunity'|'rotating'
  lot_size:number;ltp:number;chain_received_utc:string;volume:number
}
type Latest={
  side:'CE'|'PE';received_utc:string;age_seconds:number;fresh:boolean
  lots:number;units:number;spread_bps:number;book_imbalance_20:number
  bid_quantity_20:number;ask_quantity_20:number
  bid_levels:number;ask_levels:number;full_20_levels:boolean
  best_bid:number;best_ask:number
  feed_age_seconds?:number|null;feed_fresh?:boolean
  buy_vwap_for_units:number|null;sell_vwap_for_units:number|null
}
type ContractReceipt={
  status:'valid_book_saved'|'valid_pair_not_yet_saved'|'bid_ask_seen_no_valid_pair'|
    'bid_only'|'ask_only'|'previously_saved_feed_quiet'|'no_decoded_depth_yet'
  socket:number;bid_age_seconds:number|null;ask_age_seconds:number|null
  pair_age_seconds:number|null;saved_age_seconds:number|null
  has_ever_saved_book:boolean
}
type SocketHealth={
  socket:number;connected:boolean;subscribed:number
  with_recent_pairs_60s:number;with_recent_bids_60s:number;with_recent_asks_60s:number
}
type Recorder={
  armed:boolean;state:string;connected:boolean
  market_regular_hours:boolean;settings:Settings;session_id:string|null
  snapshots_saved:number;received_pairs:number;invalid_pairs:number
  selection_events:number;last_error:string|null
  last_packet_utc:string|null;last_chain_utc:string|null
  current_expiry?:string;chain_spot?:number;atm_strike?:number
  contracts_above?:number;contracts_below?:number
  source_pairs_above?:number;source_pairs_below?:number;missing_ltp_selected?:number
  contracts_with_saved_books?:number;contracts_with_recent_packets?:number
  sockets_connected?:number;sockets_requested?:number;sockets_with_recent_pairs?:number
  dropped_depth_samples?:number
  contract_receipts?:Record<string,ContractReceipt>
  socket_health?:SocketHealth[];active_contracts_with_no_valid_pairs_60s?:number
  depth_parser_diagnostics?:Record<string,number>
  selection_warning?:string|null;contracts:Candidate[]
  source_contracts_reported?:number;source_verified_depth_contracts?:number
  source_strike_min?:number|null;source_strike_max?:number|null
  subscribed_strike_min?:number|null;subscribed_strike_max?:number|null
  rotating_contracts?:number;opportunity_depth_contracts?:number
  not_currently_depth_subscribed?:number
  rotation_step?:number;chain_refresh_seconds?:number
  boundary_escape_events?:number;last_boundary_escape_utc?:string|null
  coverage_gap_warning?:string|null
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
  capture_schedule_seconds:{nearest:number;second:number;next_four:number;remaining:number}
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
const receiptMessage=(receipt?:ContractReceipt)=>{
  if(!receipt)return 'Receipt diagnostics unavailable until the recorder refreshes.'
  switch(receipt.status){
    case 'valid_pair_not_yet_saved':
      return 'Verified original bid + ask pair received; waiting for its scheduled saved sample.'
    case 'bid_ask_seen_no_valid_pair':
      return 'Original bid and ask halves were decoded, but not validated as one same-ID book within one second.'
    case 'bid_only':
      return 'Original bid half decoded, but no recent matching ask half.'
    case 'ask_only':
      return 'Original ask half decoded, but no recent matching bid half.'
    case 'previously_saved_feed_quiet':
      return 'A real order book was saved earlier; no complete recent source pair is available.'
    case 'valid_book_saved':
      return 'Validated order book is saved.'
    default:
      return 'No original 20-level bid or ask packet has been decoded for this subscribed contract in the last 60 seconds.'
  }
}
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
  const [contractView,setContractView]=useState<'nearby'|'recording'|'rotating'>('nearby')
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
  const displayedContracts=state?.contracts
    ?contractView==='recording'
      ?state.contracts.filter(c=>Boolean(state.latest[c.identity]))
        .sort((a,b)=>Date.parse(state.latest[b.identity].received_utc)-
          Date.parse(state.latest[a.identity].received_utc)).slice(0,8)
      :contractView==='rotating'
        ?state.contracts.filter(c=>c.coverage_role==='rotating').slice(0,8)
        :state.contracts.filter(c=>c.coverage_role==='core').slice(0,8)
    :[]
  return <section className="ad-root" aria-label="Automatic BANKNIFTY 20-level order-book recorder">
    <header className="ad-head">
      <div>
        <span className="tc-page-kicker">AUTOMATIC LIVE DATA COLLECTION</span>
        <h3><Activity size={19}/> Record BANKNIFTY CE &amp; PE order books</h3>
        <p>Dhan-only automatic coverage. Archive every source-returned
          CE/PE chain for all listed expiries. The separately authorized fifth
          WebSocket can record live prices across the full verified universe.
          Four 20-level sockets monitor the 120 nearest contracts, promote
          rapidly moving verified contracts, then rotate spare distant slots.
          No orders.</p>
      </div>
      <span className={'ad-status '+(connected?'active':armed?'armed':'stopped')}>
        <Radio size={15}/>{STATE_NAME[state?.state||'disabled']||state?.state||'Stopped'}
      </span>
    </header>

    <div className="ad-controls" aria-label="Automatic order-book recording configuration">
      <div className="ad-armed-note" role="note">
        <strong>Full Dhan option chains + 200 concurrent depth subscriptions</strong>
        <div>120 nearest CE/PE contracts remain subscribed. Up to 40
          source-confirmed premium movers can take deep-book slots, while
          remaining distant slots rotate every 90 seconds. The separate
          all-contract Quote/OI monitor is optional and independent of depth.</div>
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
      <small>The six closest subscribed contracts may be saved every 3 seconds.
        Others use the broad interval. Recheck original Dhan spot every
        20 seconds; distant contracts rotate every 90 seconds. If the market
        moves outside prior coverage, no missing book is invented.</small>
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
        Dhan depth data for up to 200 verified contracts at a time
        (120 nearest plus 80 rotating distant contracts), and archive complete
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
    {state?.coverage_gap_warning&&<p className="ad-warning" role="status">
      <AlertTriangle size={15}/>{state.coverage_gap_warning}
      {' '}Last detected: {clock(state.last_boundary_escape_utc)} IST.</p>}
    <div className="ad-summary">
      <span><strong>{n(state?.snapshots_saved)}</strong> books stored this session</span>
      <span><strong>{n(state?.received_pairs)}</strong> observed source packet pairs</span>
      <span><strong>{state?.contracts.length??0}/200</strong> simultaneous depth IDs</span>
      <span><strong>{n(state?.source_verified_depth_contracts)}</strong> verified options in source chain</span>
      <span><strong>{n(state?.not_currently_depth_subscribed)}</strong> waiting for a distant depth rotation slot</span>
      <span><strong>{n(state?.rotating_contracts)}</strong> currently rotating depth IDs</span>
      <span><strong>{n(state?.opportunity_depth_contracts)}</strong> original moving options promoted to 20-level</span>
      <span><strong>{state?.contracts_above??0} / {state?.contracts_below??0}</strong> subscribed above / below ATM</span>
      <span><strong>{n(state?.rotation_step)}</strong> distant strike rotation cycle</span>
      <span><strong>{n(state?.boundary_escape_events)}</strong> observed prior-depth-range breakouts</span>
      <span><strong>{n(state?.subscribed_strike_min)} – {n(state?.subscribed_strike_max)}</strong> subscribed strikes</span>
      <span><strong>{n(state?.source_strike_min)} – {n(state?.source_strike_max)}</strong> verified source strikes</span>
      <span><strong>{n(state?.contracts_with_saved_books)}</strong> contracts with saved source books</span>
      <span><strong>{n(state?.contracts_with_recent_packets)}</strong> contracts with paired packets in last 10s</span>
      <span><strong>{n(state?.active_contracts_with_no_valid_pairs_60s)}</strong> selected IDs without a valid pair in last 60s</span>
      <span><strong>{n(state?.depth_parser_diagnostics?.rejected_frame_count)}</strong> non-book / invalid Dhan depth frames (see reasons)</span>
      <span><strong>{n(state?.depth_parser_diagnostics?.disconnect_or_control_frames)}</strong> Dhan depth control/disconnect frames</span>
      <span><strong>{n(state?.depth_parser_diagnostics?.unsupported_response_code_frames)}</strong> unsupported depth response-code frames</span>
      <span><strong>{n(state?.depth_parser_diagnostics?.oversized_depth_stack_frames)}</strong> oversized depth messages (over 100 half-packets)</span>
      <span><strong>{n(state?.depth_parser_diagnostics?.truncated_or_wrong_size_frames)}</strong> malformed / truncated depth frames</span>
      <span><strong>{n(state?.depth_parser_diagnostics?.invalid_header_or_level_frames)}</strong> invalid depth headers or level values</span>
      <span><strong>{n(state?.depth_parser_diagnostics?.unpaired_time_window_count)}</strong> source bid/ask halves outside 1s pairing window</span>
      <span><strong>{n(state?.depth_parser_diagnostics?.rejected_book_pair_count)}</strong> decoded pairs rejected by original-book validation</span>
      <span><strong>{state?.sockets_connected??0} / {state?.sockets_requested??0}</strong> connected depth sockets</span>
      <span><strong>{n(state?.sockets_with_recent_pairs)} / {state?.sockets_requested??0}</strong> sockets with original depth in last 60s</span>
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
    <OptionUniverseMonitor/>
    {Boolean(state?.socket_health?.length)&&<section className="ad-socket-health"
      aria-label="Original Dhan depth receipt health by socket">
      <strong>Original 20-level delivery by socket</strong>
      <p>A connected socket can still have instruments with no complete bid + ask pairs.
        Counts reflect distinct subscribed contracts observed in the past 60 seconds.</p>
      <div>{state?.socket_health?.map(socket=><span key={socket.socket}>
        <b>Socket {socket.socket} · {socket.connected?'Connected':'Disconnected'}</b>
        <strong>{socket.with_recent_pairs_60s}/{socket.subscribed} valid books</strong>
        <small>{socket.with_recent_bids_60s} bid IDs · {socket.with_recent_asks_60s} ask IDs</small>
      </span>)}</div>
    </section>}
    <div className="ad-view-tabs" role="group" aria-label="Inspect Dhan 20-level contract coverage">
      <button type="button" className={contractView==='nearby'?'selected':''}
        aria-pressed={contractView==='nearby'} onClick={()=>setContractView('nearby')}>
        Nearest contracts</button>
      <button type="button" className={contractView==='recording'?'selected':''}
        aria-pressed={contractView==='recording'} onClick={()=>setContractView('recording')}>
        Actually saved ({n(state?.contracts_with_saved_books)})</button>
      <button type="button" className={contractView==='rotating'?'selected':''}
        aria-pressed={contractView==='rotating'} onClick={()=>setContractView('rotating')}>
        Rotating depth</button>
    </div>
    <div className="ad-contracts">
      {state?.contracts.length?<><p className="ad-armed-note">
        {contractView==='nearby'?'Nearest eight subscribed contracts':
         contractView==='recording'?'Eight most recently saved source books':
         'Eight currently subscribed far-strike contracts'}.
        {' '}{state.contracts.length} original Dhan IDs are subscribed;
        {' '}{n(state.contracts_with_saved_books)} have produced saved original
        20-level books this session. These are not reconstructed historical packets.
        {Boolean(state.missing_ltp_selected)&&<>
        {' '}{n(state.missing_ltp_selected)} verified contracts have no last traded
        premium in the source chain.</>}
        {Boolean(state.dropped_depth_samples)&&
          <> {n(state.dropped_depth_samples)} samples were skipped because
          local storage could not keep up.</>}
      </p>{displayedContracts.map(contract=>{
        const live=state.latest[contract.identity]
        const receipt=state.contract_receipts?.[contract.identity]
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
            <span>Latest source packet <strong className={live.feed_fresh?'ad-fresh':'ad-stale'}>
              {live.feed_age_seconds==null?'—':n(live.feed_age_seconds,0)+'s'} · {live.feed_fresh?'active':'quiet / unavailable'}</strong></span>
            <span>Saved book age <strong>{n(live.age_seconds,0)}s</strong></span>
          </div>:<p className="ad-empty-contract">{receiptMessage(receipt)}</p>}
          {receipt&&<small className="ad-receipt-meta">
            Socket {receipt.socket} · decoded bid {receipt.bid_age_seconds==null?'not seen':
              n(receipt.bid_age_seconds,0)+'s ago'} · ask {receipt.ask_age_seconds==null?'not seen':
              n(receipt.ask_age_seconds,0)+'s ago'} · last valid pair {receipt.pair_age_seconds==null?
              'not seen':n(receipt.pair_age_seconds,0)+'s ago'}
          </small>}
          <small className="ad-lot-note">{settings.lots} lots × verified {contract.lot_size}
            {' '}units = {settings.lots*contract.lot_size} units · local receive clock</small>
        </article>
      })}
        {displayedContracts.length===0&&<p className="ad-empty-contract">
          No subscribed contracts have saved a validated original book in this view.
          Check the per-socket bid/ask receipt counts above.
        </p>}</>:<div className="ad-empty-contract">
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
