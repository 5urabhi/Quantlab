import {useCallback,useEffect,useState} from 'react'
import {Activity,AlertTriangle,Database,History,PauseCircle,Radio,ShieldCheck} from 'lucide-react'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
import './auto-depth-recorder.css'

type Settings={
  enabled:boolean;target_premium:number;tolerance:number
  per_side:number;lots:number;sample_seconds:number
}
type Candidate={
  identity:string;side:'CE'|'PE';strike:number;expiry:string
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
  current_expiry?:string;chain_spot?:number
  selection_warning?:string|null;contracts:Candidate[]
  latest:Record<string,Latest>;read_only:boolean
  historical_depth_download_supported:boolean
}
const DEFAULT_SETTINGS:Settings={
  enabled:false,target_premium:300,tolerance:75,per_side:2,lots:3,sample_seconds:3,
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
  no_eligible_option_contracts:'No verified options near target',
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
  const [settings,setSettings]=useState<Settings>(DEFAULT_SETTINGS)
  const [armedConsent,setArmedConsent]=useState(false)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')
  const refresh=useCallback(async()=>{
    try{
      const updated=await marketApi<Recorder>('/api/trading-cockpit/auto-depth/status')
      setState(updated)
      if(!busy)setSettings(updated.settings)
    }catch(e){setError(readableError(e))}
  },[busy])
  useEffect(()=>{
    void refresh()
    const timer=window.setInterval(()=>{void refresh()},7000)
    return()=>window.clearInterval(timer)
  },[refresh])
  const arm=async()=>{
    if(busy||!armedConsent)return
    setBusy(true);setError('');setNotice('')
    try{
      const {enabled:_,...options}=settings
      const result=await marketPost<Recorder>(
        '/api/trading-cockpit/auto-depth/arm',
        {...options,confirm_live_data:true})
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
        <p>Select real Dhan contracts near {inr(settings.target_premium,0)}, follow
          changes during market hours, and store original 20-bid/20-ask snapshots
          for later liquidity and RL research. No orders are sent.</p>
      </div>
      <span className={'ad-status '+(connected?'active':armed?'armed':'stopped')}>
        <Radio size={15}/>{STATE_NAME[state?.state||'disabled']||state?.state||'Stopped'}
      </span>
    </header>

    <div className="ad-controls" aria-label="Automatic order-book recording configuration">
      <label>Preferred premium ₹
        <input aria-label="Auto depth target premium" type="number" min={50} max={10000} step={5}
          disabled={armed} value={settings.target_premium}
          onChange={e=>setSettings(x=>({...x,target_premium:Number(e.target.value)}))}/>
      </label>
      <label>Premium tolerance ±₹
        <input aria-label="Auto depth premium tolerance" type="number" min={5} max={500}
          disabled={armed} value={settings.tolerance}
          onChange={e=>setSettings(x=>({...x,tolerance:Number(e.target.value)}))}/>
      </label>
      <label>Contracts per side
        <select aria-label="Auto depth contracts per side" disabled={armed}
          value={settings.per_side}
          onChange={e=>setSettings(x=>({...x,per_side:Number(e.target.value)}))}>
          <option value={1}>1 CE + 1 PE</option>
          <option value={2}>2 CE + 2 PE</option>
          <option value={3}>3 CE + 3 PE</option>
        </select>
      </label>
      <label>Lots to evaluate
        <input aria-label="Auto depth lots" type="number" min={1} max={20} step={1}
          disabled={armed} value={settings.lots}
          onChange={e=>setSettings(x=>({...x,lots:Number(e.target.value)}))}/>
      </label>
      <label>Sample every
        <select aria-label="Auto depth sample interval" disabled={armed}
          value={settings.sample_seconds}
          onChange={e=>setSettings(x=>({...x,sample_seconds:Number(e.target.value)}))}>
          <option value={1}>1 second / contract</option>
          <option value={2}>2 seconds / contract</option>
          <option value={3}>3 seconds / contract</option>
          <option value={5}>5 seconds / contract</option>
          <option value={10}>10 seconds / contract</option>
        </select>
      </label>
    </div>

    <div className="ad-actions">
      {!armed?<label className="ad-consent">
        <input type="checkbox" checked={armedConsent}
          onChange={e=>setArmedConsent(e.target.checked)}/>
        Allow my local QuantLab server to automatically subscribe to and record original
        Dhan market-depth data during future regular NSE sessions, until I stop it.
      </label>:<p className="ad-armed-note"><ShieldCheck size={16}/>
        Consent is saved locally. Recording resumes automatically while the local server
        is running during regular NSE hours. Stopping disarms future sessions.</p>}
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
      <span><strong>{state?.contracts.length??0}</strong> verified contracts selected</span>
      <span><strong>{state?.current_expiry||'—'}</strong> Dhan-listed expiry</span>
      <span><strong>{clock(state?.last_packet_utc)}</strong> most recent paired packet (IST)</span>
    </div>
    <div className="ad-contracts">
      {state?.contracts.length?state.contracts.map(contract=>{
        const live=state.latest[contract.identity]
        return <article className="ad-contract" key={contract.identity}>
          <div className="ad-contract-title">
            <strong className={contract.side==='CE'?'ce':'pe'}>{contract.side}</strong>
            <strong>{n(contract.strike,0)} strike</strong>
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
      }):<div className="ad-empty-contract">
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
      running, and Dhan full-depth entitlement is required. Captured snapshots
      remain available under Market Replay, even after stopping.
    </p>
  </section>
}
