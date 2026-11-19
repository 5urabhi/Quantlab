import {useCallback, useEffect, useRef, useState} from 'react'
import {Clock3, RefreshCw, ShieldCheck, Radio, History, ClipboardList, Settings2, ArrowRight, BarChart3} from 'lucide-react'
import {nseMarketWindow} from './tradingMarketSession'
import SavedCaptureReview from './SavedCaptureReview'
import MarketReplayPanel from './MarketReplayPanel'
import StrategyWorkbench from './StrategyWorkbench'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
import './trading-cockpit.css'
import LiveFeedPanel from './LiveFeedPanel'
import type {OptionContract} from './OptionChainLive'

type Entry = {id:string;created_utc:string;identity:string;bar_utc:string;direction:string;reference_close:number;horizon_minutes:number;quote_mode:string;evaluation:string;observed_close:number|null;actual_direction:string|null}
type SourceInstrument = {identity:string;display_name?:string;asset_class?:string;ready:boolean;state:string;needs_preparation?:boolean;needs_download?:boolean}
type Catalog = {instruments:SourceInstrument[];prepared_equities:number;downloaded_equities_pending_preparation:number}
type SourceJob = {id:string;status:string;stage?:string;percent?:number;error?:string;result?:{status?:string;prepared_count?:number;blocked_count?:number;checked?:number;rows?:number;remaining_unselected?:number}}
type History = {predictions:Entry[];summary:{evaluated_directions:number;correct_directions:number;direction_accuracy:number|null;qualification:string}}
type DaySummary = {session_ist:string;total:number;scored:number;correct:number;incorrect:number;pending:number;no_trade:number;flat:number;unverifiable:number;directional_accuracy:number|null}
type Report = {days:DaySummary[];overall:Omit<DaySummary,'session_ist'>;source:string;disclaimer:string;truncated:boolean}
type DhanCheck = {ok:boolean;code:string;message:string;token_present:boolean;token_valid:boolean|null;data_plan_active:boolean|null;client_id_configured?:boolean;expires_at_utc?:string|null;seconds_remaining?:number|null}
type DhanConnect = {connected:boolean;message:string}
type CockpitView = 'live'|'replay'|'strategy'|'journal'|'setup'
type ReplayView = 'session'|'recordings'
type JournalView = 'trades'|'accuracy'
type LiveHeaderState = {
  active?:boolean;index_identity?:string;ticker_connection?:string;
  quotes?:Record<string,{received_utc:string;fresh:boolean;price:number}>;
}
type ManualTrade = {id:string;symbol:string;direction:'CALL'|'PUT';quantity:number;entry_price:number;entry_recorded_utc:string;exit_price:number|null;exit_recorded_utc:string|null;holding_seconds:number;holding_rule_exceeded:boolean;gross_notional_inr:number;net_pnl_inr:number|null;status:'OPEN'|'CLOSED';data_quality:string}
type TradeJournal = {trades:ManualTrade[];summary:{open:number;closed:number;closed_net_pnl_inr:number;holding_violations:number;days:{exit_session_ist:string;closed:number;net_pnl_inr:number;over_6_min:number}[]};disclaimer:string}

const api = marketApi
const fmt=(v:number|null|undefined,digits=2)=>v===null||v===undefined?'—':v.toLocaleString('en-IN',{maximumFractionDigits:digits})
const post=(path:string,body:unknown)=>marketPost<unknown>(path,body)
const indiaDate=(offsetDays=0)=>{const d=new Date();d.setUTCDate(d.getUTCDate()+offsetDays);return d.toLocaleDateString('sv-SE',{timeZone:'Asia/Kolkata'})}

export default function TradingCockpit(){
  const [activeTab,setActiveTab]=useState<CockpitView>(()=>
    nseMarketWindow(Date.now()).regularWindow?'live':'replay')
  const [replayView,setReplayView]=useState<ReplayView>('session')
  const [journalView,setJournalView]=useState<JournalView>('trades')
  const selectedTab=useRef(false)
  const [liveHeader,setLiveHeader]=useState<LiveHeaderState|null>(null)
  const selectTab=(view:CockpitView)=>{selectedTab.current=true;setActiveTab(view)}
  useEffect(()=>{
    let mounted=true
    const check=()=>{
      void api<LiveHeaderState>('/api/trading-cockpit/live/status')
        .then(status=>{if(mounted)setLiveHeader(status)})
        .catch(()=>{if(mounted)setLiveHeader(null)})
    }
    check()
    const timer=window.setInterval(check,10000)
    return()=>{mounted=false;window.clearInterval(timer)}
  },[])
  const [instruments,setInstruments]=useState<Catalog['instruments']>([])
  const [catalog,setCatalog]=useState<Catalog|null>(null)
  const [sourceJob,setSourceJob]=useState<SourceJob|null>(null)
  const [sourceBusy,setSourceBusy]=useState(false)
  const [sourceNotice,setSourceNotice]=useState('')
  const [sourceError,setSourceError]=useState('')
  const [spotIdentity,setSpotIdentity]=useState<'INDEX:BANKNIFTY'|'INDEX:NIFTY50'>('INDEX:BANKNIFTY')
  const [spotFrom,setSpotFrom]=useState(()=>indiaDate(-45))
  const [spotTo,setSpotTo]=useState(()=>indiaDate(1))
  const [journalHistory,setJournalHistory]=useState<History|null>(null)
  const [journalReport,setJournalReport]=useState<Report|null>(null)
  const [journalIdentity,setJournalIdentity]=useState<'INDEX:BANKNIFTY'|'INDEX:NIFTY50'>('INDEX:BANKNIFTY')
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [recordMessage,setRecordMessage]=useState('')
  const [now,setNow]=useState(()=>Date.now())
  const [startTime,setStartTime]=useState<number|null>(()=>{
    try{const stored=window.localStorage.getItem('quantlab:manual-six-minute-timer')
      const value=stored?Number(stored):null
      return value!==null&&Number.isFinite(value)&&value>0&&value<=Date.now()?value:null
    }catch{return null}
  })
  const [journal,setJournal]=useState<TradeJournal|null>(null)
  const [optionSymbol,setOptionSymbol]=useState('')
  const [optionSide,setOptionSide]=useState<'CALL'|'PUT'>('PUT')
  const [optionQty,setOptionQty]=useState('1')
  const [optionLotSize,setOptionLotSize]=useState<number|null>(null)
  const [optionDraftNote,setOptionDraftNote]=useState('')
  const [optionEntry,setOptionEntry]=useState('')
  const [tradeNote,setTradeNote]=useState('')
  const [dhanCheck,setDhanCheck]=useState<DhanCheck|null>(null)
  const [dhanToken,setDhanToken]=useState('')
  const [dhanClientId,setDhanClientId]=useState('')
  const [tokenForm,setTokenForm]=useState(false)
  const [tokenConsent,setTokenConsent]=useState(false)
  const [tokenBusy,setTokenBusy]=useState(false)
  const [tokenError,setTokenError]=useState('')
  const [tokenMessage,setTokenMessage]=useState('')
  const [journalBusy,setJournalBusy]=useState(false)
  const [closingId,setClosingId]=useState('')
  const [exitPremium,setExitPremium]=useState('')
  const [fees,setFees]=useState('0')

  const checkDhan=useCallback(async()=>{
    try{
      const state=await api<DhanCheck>('/api/dhan/credentials/check')
      setDhanCheck(state);setTokenError('')
    }catch(e){setTokenError(readableError(e))}
  },[])
  useEffect(()=>{
    void checkDhan()
    const poll=window.setInterval(()=>{void checkDhan()},60000)
    return()=>window.clearInterval(poll)
  },[checkDhan])
  const connectDhan=async(event:React.FormEvent<HTMLFormElement>)=>{
    event.preventDefault()
    if(tokenBusy||!tokenConsent||!dhanToken.trim())return
    setTokenBusy(true);setTokenError('');setTokenMessage('')
    try{
      const connected=await api<DhanConnect>('/api/market-data/providers/dhan/connect',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({access_token:dhanToken,
          ...(dhanClientId.trim()?{client_id:dhanClientId.trim()}:{}),
          confirm_local_storage:true}),
      })
      setDhanToken('');setDhanClientId('');setTokenForm(false);setTokenConsent(false)
      setTokenMessage(connected.message)
      await checkDhan()
    }catch(e){setTokenError(readableError(e))}
    finally{setTokenBusy(false)}
  }
  const loadJournal=useCallback(async()=>{
    try{setJournal(await api<TradeJournal>('/api/trading-cockpit/trades?limit=80'))}
    catch(e){setError(readableError(e))}
  },[])
  useEffect(()=>{void loadJournal()},[loadJournal])
  const recordEntry=async(event:React.FormEvent<HTMLFormElement>)=>{
    event.preventDefault()
    if(journalBusy)return
    setJournalBusy(true);setError('')
    try{
      if(optionLotSize!==null&&
          (Number(optionQty)<optionLotSize||Number(optionQty)%optionLotSize!==0)){
        throw new Error('Selected option quantity must be a whole number of '+optionLotSize+'-unit lots')
      }
      await post('/api/trading-cockpit/trades',{
        symbol:optionSymbol.trim().toUpperCase(),direction:optionSide,
        quantity:Number(optionQty),entry_price:Number(optionEntry),note:tradeNote})
      setOptionEntry('');setTradeNote('');setOptionDraftNote('');setStartTime(Date.now())
      setRecordMessage('Manual position opened. Six-minute timer started. No broker order submitted.')
      await loadJournal()
    }catch(e){setError(readableError(e))}
    finally{setJournalBusy(false)}
  }
  const recordExit=async(event:React.FormEvent<HTMLFormElement>)=>{
    event.preventDefault()
    if(journalBusy||!closingId)return
    setJournalBusy(true);setError('')
    try{
      await post('/api/trading-cockpit/trades/'+encodeURIComponent(closingId)+'/exit',{
        exit_price:Number(exitPremium),fees_inr:Number(fees)})
      setClosingId('');setExitPremium('');setFees('0')
      setRecordMessage('Manual exit recorded. Net P&L computed from entered prices, not verified broker fills.')
      await loadJournal()
    }catch(e){setError(readableError(e))}
    finally{setJournalBusy(false)}
  }
  useEffect(()=>{
    try{
      if(startTime===null)window.localStorage.removeItem('quantlab:manual-six-minute-timer')
      else window.localStorage.setItem('quantlab:manual-six-minute-timer',String(startTime))
    }catch{/* private browsing or disabled storage */}
  },[startTime])
  const refreshCatalog=useCallback(async()=>{
    const data=await api<Catalog>('/api/trading-cockpit/instruments')
    setCatalog(data);setInstruments(data.instruments)
    setSpotIdentity(previous=>{
      const remaining=data.instruments.filter(x=>x.asset_class==='spot_index'&&!x.ready)
      return remaining.some(x=>x.identity===previous)?previous:
        remaining[0]?.identity==='INDEX:NIFTY50'?'INDEX:NIFTY50':'INDEX:BANKNIFTY'
    })

  },[])
  useEffect(()=>{void refreshCatalog().catch(e=>setSourceError(readableError(e)))},[refreshCatalog])
  useEffect(()=>{
    if(!sourceJob||!['queued','running'].includes(sourceJob.status))return
    let active=true
    const timer=window.setTimeout(()=>{
      void api<SourceJob>('/api/jobs/'+encodeURIComponent(sourceJob.id))
        .then(next=>{
          if(!active)return
          setSourceJob(next)
          if(next.status==='complete'){
            setSourceNotice(next.result?.prepared_count!==undefined
              ?'Prepared '+next.result.prepared_count+' existing one-minute chart sources (no new download).'
              :next.result?.rows!==undefined
                ?'Original index spot history saved: '+next.result.rows+' observed candles.'
                :'Market data preparation finished.')
            void refreshCatalog().catch(e=>setSourceError(readableError(e)))
          }else if(next.status==='error'||next.status==='cancelled'){
            setSourceError(next.error||'The local source task needs attention.')
          }
        }).catch(e=>{if(active)setSourceError(readableError(e))})
    },1500)
    return()=>{active=false;window.clearTimeout(timer)}
  },[sourceJob,refreshCatalog])
  const prepareCached=async()=>{
    if(sourceBusy||['queued','running'].includes(sourceJob?.status||''))return
    setSourceBusy(true);setSourceError('');setSourceNotice('')
    try{
      const result=await api<{job_id:string|null;status:string;message?:string}>(
        '/api/trading-cockpit/sources/prepare',{method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({confirm_reuse_originals:true})})
      if(result.job_id)setSourceJob({id:result.job_id,status:result.status})
      else setSourceNotice(result.message||'All available minute chart caches are prepared.')
    }catch(e){setSourceError(readableError(e))}
    finally{setSourceBusy(false)}
  }
  const acquireSpot=async(event:React.FormEvent<HTMLFormElement>)=>{
    event.preventDefault()
    if(sourceBusy||['queued','running'].includes(sourceJob?.status||''))return
    if(!window.confirm('Download original '+(spotIdentity==='INDEX:BANKNIFTY'?'BANKNIFTY':'NIFTY 50')+' spot index history from Dhan? Existing equities remain in the same shared library, and no order will be placed.'))return
    setSourceBusy(true);setSourceError('');setSourceNotice('')
    try{
      const result=await api<{job_id:string;status:string}>(
        '/api/trading-cockpit/sources/index-spot',{method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({identity:spotIdentity,from_date:spotFrom,
            to_date:spotTo,confirm_readonly:true})})
      setSourceJob({id:result.job_id,status:result.status})
    }catch(e){setSourceError(readableError(e))}
    finally{setSourceBusy(false)}
  }
  useEffect(()=>{
    const timer=window.setInterval(()=>setNow(Date.now()),1000)
    return()=>window.clearInterval(timer)
  },[])
  const loadPredictionLedger=useCallback(async()=>{
    const [ledger,daily]=await Promise.all([
      api<History>('/api/trading-cockpit/predictions?'+new URLSearchParams({
        identity:journalIdentity,limit:'100'})),
      api<Report>('/api/trading-cockpit/report?'+new URLSearchParams({identity:journalIdentity})),
    ])
    setJournalHistory(ledger);setJournalReport(daily)
  },[journalIdentity])
  useEffect(()=>{
    if(activeTab!=='journal'||journalView!=='accuracy')return
    void loadPredictionLedger().catch(e=>setError(readableError(e)))
    const interval=window.setInterval(()=>{
      void loadPredictionLedger().catch(e=>setError(readableError(e)))
    },20000)
    return()=>window.clearInterval(interval)
  },[activeTab,journalView,loadPredictionLedger])
  const evaluateJournal=async()=>{
    if(busy)return
    setBusy(true);setRecordMessage('');setError('')
    try{
      const data=await post('/api/trading-cockpit/live/evaluate',{
        identity:journalIdentity,horizon_minutes:6}) as {updated:number}
      setRecordMessage('Evaluated '+data.updated+' recorded calls using observed live index minutes. Historical gaps are not invented.')
      await loadPredictionLedger()
    }catch(e){setError(readableError(e))}
    finally{setBusy(false)}
  }
  const elapsed=startTime===null?0:Math.floor((now-startTime)/1000)
  const remaining=Math.max(0,6*60-elapsed)
  const countdown=`${String(Math.floor(remaining/60)).padStart(2,'0')}:${String(remaining%60).padStart(2,'0')}`
  const tokenRemaining=dhanCheck?.expires_at_utc
    ?Math.max(0,Math.floor((Date.parse(dhanCheck.expires_at_utc)-now)/1000)):null
  const tokenHours=tokenRemaining===null?null:Math.floor(tokenRemaining/3600)
  const tokenMinutes=tokenRemaining===null?null:Math.floor((tokenRemaining%3600)/60)
  const tokenState=!dhanCheck?'CHECKING':dhanCheck.token_valid===false?'EXPIRED / REJECTED'
    :dhanCheck.token_valid===null?'UNVERIFIED':tokenRemaining!==null&&tokenRemaining<=3600?'EXPIRING SOON'
    :dhanCheck.ok?'CONNECTED':'NEEDS ATTENTION'
  const missingBankNifty=!instruments.some(x=>x.identity==='INDEX:BANKNIFTY'&&x.ready)
  const missingIndexSources=instruments.filter(x=>x.asset_class==='spot_index'&&!x.ready)
  const pendingMinutes=catalog?.downloaded_equities_pending_preparation??0
  const sourceWorking=sourceBusy||['queued','running'].includes(sourceJob?.status||'')
  const summary=journalHistory?.summary
  const marketWindow=nseMarketWindow(now)
  const activeQuote=liveHeader?.index_identity?liveHeader.quotes?.[liveHeader.index_identity]:undefined
  const liveFeedFresh=Boolean(liveHeader?.active&&liveHeader.ticker_connection==='connected'
    &&activeQuote?.fresh&&Date.now()-Date.parse(activeQuote.received_utc)<=8000)
  useEffect(()=>{
    if(!selectedTab.current){
      setActiveTab(liveHeader?.active||marketWindow.regularWindow?'live':'replay')
    }
  },[liveHeader?.active,marketWindow.regularWindow])
  return <div className="tc-shell tc-cockpit-v4">
    <div className="tc-cockpit-intro">
      <span className="tc-page-kicker">TRADING COPILOT · BANKNIFTY / NIFTY 50</span>
      <span className="tc-workspace-readonly"><ShieldCheck size={15}/> Read-only · no orders</span>
    </div>
    <div className="tc-v4-status" role="status" aria-label="Exchange schedule and real feed status">
      <span className={marketWindow.regularWindow?'regular':'idle'}>
        <span className="tc-status-dot"/>{marketWindow.regularWindow?'Regular NSE index hours':'Outside regular NSE index hours'}</span>
      <span className={liveFeedFresh?'live':'idle'}>
        <span className="tc-status-dot"/>{liveFeedFresh?'Broker feed LIVE · fresh':liveHeader?.active?'Feed connecting / stale':'Live feed stopped'}</span>
      <span className={tokenState==='CONNECTED'?'live':tokenState==='EXPIRING SOON'?'regular':'idle'}>
        <ShieldCheck size={14}/> Dhan: {tokenState==='CONNECTED'?'Verified':tokenState==='EXPIRING SOON'?'Expiring soon':tokenState==='CHECKING'?'Checking':tokenState}
        {tokenRemaining!==null&&tokenRemaining>0?' · '+tokenHours+'h '+tokenMinutes+'m remaining':''}
      </span>
      <span className="tc-v4-time"><Clock3 size={14}/>{marketWindow.istClock}</span>
    </div>
    <nav className="tc-v4-tabs" role="tablist" aria-label="Trading cockpit workspaces">
      <button type="button" role="tab" id="tc-tab-live" aria-controls="tc-view-live" aria-selected={activeTab==='live'}
        onClick={()=>selectTab('live')}><Radio size={17}/><span>Live Trading</span></button>
      <button type="button" role="tab" id="tc-tab-replay" aria-controls="tc-view-replay" aria-selected={activeTab==='replay'}
        onClick={()=>selectTab('replay')}><History size={17}/><span>Market Replay</span></button>
      <button type="button" role="tab" id="tc-tab-strategy" aria-controls="tc-view-strategy" aria-selected={activeTab==='strategy'}
        onClick={()=>selectTab('strategy')}><BarChart3 size={17}/><span>Signal Backtest</span></button>
      <button type="button" role="tab" id="tc-tab-journal" aria-controls="tc-view-journal" aria-selected={activeTab==='journal'}
        onClick={()=>selectTab('journal')}><ClipboardList size={17}/><span>Trade Journal</span></button>
      <button type="button" role="tab" id="tc-tab-setup" aria-controls="tc-view-setup" aria-selected={activeTab==='setup'}
        onClick={()=>selectTab('setup')}><Settings2 size={17}/><span>Connections</span></button>
    </nav>

    {activeTab==='live'&&<section role="tabpanel" id="tc-view-live" aria-labelledby="tc-tab-live" className="tc-tab-page">
      <div className="tc-v4-intro"><div><span className="tc-page-kicker">LIVE TRADING RESEARCH</span>
        <h3>BANKNIFTY live monitor</h3><p>Real index ticks, selected option premium, and a source-backed 20-level book. No automatic broker orders.</p></div>
        {!liveFeedFresh&&<button className="tc-link-button" type="button" onClick={()=>selectTab('setup')}>
          Check connection <ArrowRight size={15}/></button>}</div>
      {!marketWindow.regularWindow&&!liveFeedFresh&&<div className="tc-market-note"><Clock3 size={17}/>
        <span>The regular NSE index session is outside its trading window. Feed freshness is determined only by actual Dhan packets; holidays and special sessions are not inferred.</span>
        <button type="button" onClick={()=>{selectTab('replay');setReplayView('session')}}>Open recorded market</button></div>}
      <LiveFeedPanel onOpenSetup={()=>selectTab('setup')}
        onDraftJournal={(contract:OptionContract,lots:number)=>{
          if(!contract.lot_size||!contract.identity)return
          setOptionSymbol(contract.symbol)
          setOptionSide(contract.option_type==='CE'?'CALL':'PUT')
          setOptionQty(String(contract.lot_size*lots))
          setOptionLotSize(contract.lot_size)
          setOptionEntry('')
          setOptionDraftNote('Dhan '+contract.expiry+' '+contract.option_type+' '+contract.strike+
            ' · '+lots+' lot(s) × '+contract.lot_size+' units. The displayed bid/ask is NOT an executed fill.')
          setRecordMessage('')
          setJournalView('trades')
          selectTab('journal')
        }}/>
      <div className="tc-live-footer">
      <section className="tc-panel tc-timer">
        <div className="tc-panel-title"><strong>Six-minute trade discipline</strong><Clock3 size={16}/></div>
        <div className={'tc-clock '+(elapsed>=360?'tc-overdue':'')}>{countdown}</div>
        <p className="tc-muted">Local manual reminder. No order placement, automatic stop or guaranteed exit.</p>
        <div className="tc-actions"><button onClick={()=>setStartTime(Date.now())}>Start on fill</button><button onClick={()=>setStartTime(null)}>Reset</button></div>
        {startTime!==null&&<p className={elapsed>=360?'tc-warning':'tc-muted'}>{elapsed>=360?'Planned holding period exceeded — reassess or exit manually.':elapsed>=300?'Final minute — check exit plan.':'Timer running from your manual start.'}</p>}
      </section>
        <section className="tc-panel tc-live-next"><div><span className="tc-page-kicker">OPTIONS TRADE LOG</span>
          <h3>Manual fills &amp; outcomes</h3>
          <p>Use actual option fill prices; entering a trade here will not place a broker order.</p></div>
          <button type="button" onClick={()=>{selectTab('journal');setJournalView('trades')}}>Open journal <ArrowRight size={16}/></button>
        </section>
      </div>
    </section>}

    {activeTab==='replay'&&<section role="tabpanel" id="tc-view-replay" aria-labelledby="tc-tab-replay" className="tc-tab-page">
      <nav className="tc-subnav" role="tablist" aria-label="Market replay views">
        <button type="button" role="tab" aria-selected={replayView==='session'} onClick={()=>setReplayView('session')}>Session playback</button>
        <button type="button" role="tab" aria-selected={replayView==='recordings'} onClick={()=>setReplayView('recordings')}>Recorded 20-level books</button>
      </nav>
      {replayView==='session'&&<MarketReplayPanel instruments={instruments} onOpenData={()=>selectTab('setup')}/>}
      {replayView==='recordings'&&<SavedCaptureReview/>}
    </section>}

    {activeTab==='strategy'&&<section role="tabpanel" id="tc-view-strategy" aria-labelledby="tc-tab-strategy" className="tc-tab-page">
      <StrategyWorkbench instruments={instruments} onOpenData={()=>selectTab('setup')}
        onOpenReplay={()=>{selectTab('replay');setReplayView('session')}}
        onOpenOptions={()=>selectTab('live')}/>
    </section>}

    {activeTab==='journal'&&<section role="tabpanel" id="tc-view-journal" aria-labelledby="tc-tab-journal" className="tc-tab-page">
      <div className="tc-v4-intro"><div><span className="tc-page-kicker">TRADE JOURNAL</span>
        <h3>Real trades, recorded predictions</h3>
        <p>Your manually entered options trades and the prospective index prediction ledger have different scorecards.</p></div></div>
      <nav className="tc-subnav" role="tablist" aria-label="Trading journal views">
        <button role="tab" type="button" aria-selected={journalView==='trades'} onClick={()=>setJournalView('trades')}>Manual options trades</button>
        <button role="tab" type="button" aria-selected={journalView==='accuracy'} onClick={()=>setJournalView('accuracy')}>Prediction accuracy</button>
      </nav>
      {error&&<div role="alert" className="tc-error">{error}</div>}
      {journalView==='trades'&&<>    <section className="tc-panel tc-ledger" aria-label="Manual options trade journal">
      <div className="tc-panel-title"><strong>Manual options journal · six-minute discipline</strong><span>Read-only research · you type actual prices</span></div>
      <p className="tc-muted">Enter a new trade at the time you actually fill it. QuantLab stores server receipt times and computes P&amp;L only after you report an exit. The app cannot verify your broker fills, enforce a stop, or place orders.</p>
      <p className="tc-confirm">The underlying signal comes from BANKNIFTY spot candles. Contract selection, lot size and current Dhan option bid/ask can be previewed under Live Trading → Option Chain; they are not verified broker fills.</p>
      {optionDraftNote&&<p role="status" className="tc-warning">{optionDraftNote} Enter your actual broker fill premium before recording anything.</p>}
      {optionLotSize!==null&&<p className="tc-muted">Selected contract lot size: <strong>{optionLotSize} units</strong>.
        Quantity is entered in units (lots × lot size). Current entry quantity:
        {' '}{Number(optionQty)/optionLotSize} lot(s). Only whole lots are accepted for this draft.</p>}
      <form className="tc-trade-form" onSubmit={event=>void recordEntry(event)}>
        <label>Exact contract symbol<input required maxLength={48} value={optionSymbol} placeholder="BANKNIFTY23NOV61900PE" onChange={event=>setOptionSymbol(event.target.value.toUpperCase())}/></label>
        <label>Type<select value={optionSide} onChange={event=>setOptionSide(event.target.value as 'CALL'|'PUT')}><option value="PUT">Long put</option><option value="CALL">Long call</option></select></label>
        <label>Quantity (units = lots × lot size)<input aria-label="Trade quantity" required type="number" min="1" max="1000000" step="1" value={optionQty} onChange={event=>setOptionQty(event.target.value)}/></label>
        <label>Entry premium (₹)<input aria-label="Trade entry premium" required type="number" min="0.01" step="0.01" value={optionEntry} onChange={event=>setOptionEntry(event.target.value)}/></label>
        <label>Note (optional)<input maxLength={250} value={tradeNote} onChange={event=>setTradeNote(event.target.value)}/></label>
        <button className="tc-primary" disabled={journalBusy||
          (optionLotSize!==null&&(Number(optionQty)<optionLotSize||
            Number(optionQty)%optionLotSize!==0))} type="submit">
          Record actual broker fill manually + start six-minute timer
        </button>
      </form>
      <div className="tc-ledger-summary"><span>Open positions <strong>{journal?.summary.open??0}</strong></span><span>Closed trades <strong>{journal?.summary.closed??0}</strong></span><span>Net realized from entered fills <strong>₹{fmt(journal?.summary.closed_net_pnl_inr)}</strong></span><span>Over six minutes <strong>{journal?.summary.holding_violations??0}</strong></span></div>
      {journal?.trades.some(trade=>trade.status==='OPEN')&&<div className="tc-trade-active"><strong>Currently open (manual records)</strong>
        {journal.trades.filter(trade=>trade.status==='OPEN').map(trade=><div className="tc-open-trade" key={trade.id}>
          <span>{trade.symbol} · {trade.direction} · {trade.quantity} × ₹{fmt(trade.entry_price)}</span>
          <span className={now-Date.parse(trade.entry_recorded_utc)>360000?'tc-overdue':'tc-muted'}>Elapsed {Math.floor(Math.max(0,now-Date.parse(trade.entry_recorded_utc))/60000)}m</span>
          <button onClick={()=>{setClosingId(trade.id);setExitPremium('')}} disabled={journalBusy}>Record exit</button></div>)}
      </div>}
      {closingId&&<form className="tc-trade-form tc-exit" onSubmit={event=>void recordExit(event)}>
        <strong>Record exit for {journal?.trades.find(trade=>trade.id===closingId)?.symbol}</strong>
        <label>Exit premium (₹)<input required aria-label="Exit premium" type="number" min="0" step="0.01" value={exitPremium} onChange={event=>setExitPremium(event.target.value)}/></label>
        <label>Total charges (₹)<input aria-label="Total charges" required type="number" min="0" step="0.01" value={fees} onChange={event=>setFees(event.target.value)}/></label>
        <button type="submit" className="tc-primary" disabled={journalBusy}>Close manual record</button>
        <button type="button" onClick={()=>setClosingId('')}>Cancel</button>
      </form>}
      <div className="tc-table-scroll"><table><thead><tr><th>Symbol</th><th>Status</th><th>Side</th><th>Qty</th><th>Entry</th><th>Exit</th><th>Holding</th><th>Over 6m?</th><th>Net P&amp;L</th></tr></thead><tbody>{journal?.trades.map(trade=><tr key={trade.id}><td>{trade.symbol}</td><td>{trade.status}</td><td>{trade.direction}</td><td>{trade.quantity}</td><td>₹{fmt(trade.entry_price)}</td><td>{fmt(trade.exit_price)}</td><td>{Math.floor(trade.holding_seconds/60)}m</td><td>{trade.holding_rule_exceeded?'YES':'No'}</td><td>{trade.net_pnl_inr===null?'—':'₹'+fmt(trade.net_pnl_inr)}</td></tr>)}{!journal?.trades.length&&<tr><td colSpan={9}>No manual positions recorded.</td></tr>}</tbody></table></div>
      <p className="tc-warning">Unverified manual entries: the time starts when this local server receives your request, not the broker execution timestamp. This is a discipline journal, not an account reconciliation or evidence of actual fills.</p>
    </section></>}
      {journalView==='accuracy'&&<>
        <div className="tc-toolbar tc-journal-source"><label>Prediction ledger index
          <select aria-label="Prediction ledger index" value={journalIdentity} onChange={event=>{
            setJournalIdentity(event.target.value as 'INDEX:BANKNIFTY'|'INDEX:NIFTY50');
            setJournalHistory(null);setJournalReport(null)}}>
            <option value="INDEX:BANKNIFTY">BANKNIFTY</option>
            <option value="INDEX:NIFTY50">NIFTY 50</option>
          </select></label>
          <button type="button" onClick={()=>void loadPredictionLedger()}><RefreshCw size={15}/> Refresh</button>
          <span className="tc-muted">Existing prospective records; independent of historical chart selection.</span>
        </div>
            <section className="tc-panel tc-ledger"><div className="tc-panel-title"><strong>Permanent prediction ledger</strong><button onClick={()=>void evaluateJournal()} disabled={busy}>Evaluate saved live outcomes</button></div>
      <div className="tc-ledger-summary"><span>Scored directions <strong>{summary?.evaluated_directions??0}</strong></span><span>Correct directions <strong>{summary?.correct_directions??0}</strong></span><span>Directional accuracy <strong>{summary?.direction_accuracy===null||summary?.direction_accuracy===undefined?'Not enough observations':(summary.direction_accuracy*100).toFixed(1)+'%'}</strong></span></div>
      {recordMessage&&<p role="status" className="tc-confirm">{recordMessage}</p>}
      <p className="tc-muted">Directional accuracy excludes no-trade decisions, flat moves and unverifiable source gaps. No historical option P&L is inferred from spot candles.</p>
      <div className="tc-report-title"><h3>End-of-day accuracy · prospective ledger only</h3><span className="tc-muted">No option trade P&amp;L or validated alpha</span></div>
      <div className="tc-ledger-summary"><span>Logged decisions <strong>{journalReport?.overall.total??0}</strong></span><span>Direction score <strong>{journalReport?.overall.directional_accuracy===null||journalReport?.overall.directional_accuracy===undefined?'—':(journalReport.overall.directional_accuracy*100).toFixed(1)+'%'}</strong></span><span>Pending <strong>{journalReport?.overall.pending??0}</strong></span><span>Source gaps <strong>{journalReport?.overall.unverifiable??0}</strong></span></div>
      <div className="tc-table-scroll"><table><thead><tr><th>Session IST</th><th>Calls</th><th>Scored</th><th>Correct</th><th>Incorrect</th><th>No trade</th><th>Pending</th><th>Gaps</th><th>Accuracy</th></tr></thead><tbody>{journalReport?.days.map(day=><tr key={day.session_ist}><td>{day.session_ist}</td><td>{day.total}</td><td>{day.scored}</td><td>{day.correct}</td><td>{day.incorrect}</td><td>{day.no_trade}</td><td>{day.pending}</td><td>{day.unverifiable}</td><td>{day.directional_accuracy===null?'—':(day.directional_accuracy*100).toFixed(1)+'%'}</td></tr>)}{!journalReport?.days.length&&<tr><td colSpan={9}>No prospective logged decisions yet.</td></tr>}</tbody></table></div>
      <div className="tc-table-scroll"><table><thead><tr><th>Recorded UTC</th><th>Source bar UTC</th><th>Signal</th><th>Horizon</th><th>Reference</th><th>Observed</th><th>Outcome</th></tr></thead><tbody>{journalHistory?.predictions.map(x=><tr key={x.id}><td>{x.created_utc.slice(0,19)}</td><td>{x.bar_utc.slice(0,19)}</td><td>{x.direction}</td><td>{x.horizon_minutes}m</td><td>{fmt(x.reference_close)}</td><td>{fmt(x.observed_close)}</td><td>{x.evaluation.replaceAll('_',' ')}</td></tr>)}{!journalHistory?.predictions.length&&<tr><td colSpan={7}>No prospective predictions logged for this instrument yet.</td></tr>}</tbody></table></div>
    </section>
      </>}
    </section>}

    {activeTab==='setup'&&<section role="tabpanel" id="tc-view-setup" aria-labelledby="tc-tab-setup" className="tc-tab-page">
      <div className="tc-v4-intro"><div><span className="tc-page-kicker">CONNECTIONS &amp; SOURCE MANAGEMENT</span>
        <h3>One library. Automatic reuse.</h3>
        <p>Verify the Dhan connection, inspect source coverage and prepare missing genuine observations without making duplicate datasets.</p>
      </div><button type="button" className="tc-link-button" onClick={()=>selectTab('live')}>Return to Live Trading <ArrowRight size={15}/></button></div>
          <section className="tc-panel tc-token-panel" aria-label="Dhan data API connection">
      <div className="tc-panel-title"><strong>Dhan market data connection</strong><span>Local-only token · read-only verification</span></div>
      <div className="tc-token-status">
        <span className={'tc-token-state '+(tokenState==='CONNECTED'?'good':tokenState==='EXPIRING SOON'?'soon':'attention')}>{tokenState}</span>
        <span>{tokenRemaining!==null?(tokenRemaining>0?
          `Expires in ${tokenHours}h ${tokenMinutes}m`:'Token expired'):
          'Expiry time unavailable until broker verification succeeds'}</span>
        <button type="button" onClick={()=>void checkDhan()} disabled={tokenBusy}>Check now</button>
        <button type="button" onClick={()=>{setTokenForm(v=>!v);setTokenError('');setTokenMessage('')}}>
          {tokenForm?'Cancel':'Add / replace Dhan token'}</button>
      </div>
      {dhanCheck?.expires_at_utc&&<p className="tc-muted">Dhan-reported token expiry: {new Date(dhanCheck.expires_at_utc).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'})} IST · historical Data API {dhanCheck.data_plan_active?'active':'not confirmed active'}.</p>}
      {dhanCheck&&!dhanCheck.ok&&<p className="tc-warning">{dhanCheck.message}</p>}
      {tokenError&&<div className="tc-error" role="alert">{tokenError}</div>}
      {tokenMessage&&<p className="tc-confirm" role="status">{tokenMessage}</p>}
      {tokenForm&&<form className="tc-token-form" onSubmit={event=>void connectDhan(event)}>
        <label>New token from Dhan Web<input type="password" autoComplete="off" value={dhanToken} onChange={event=>setDhanToken(event.target.value)} placeholder="Paste Dhan access token"/></label>
        <label>Dhan client ID for live streaming (numeric; verified against your broker profile)
          <input type="password" autoComplete="off" value={dhanClientId}
            onChange={event=>setDhanClientId(event.target.value)}
            placeholder="Your Dhan client ID · leave blank to keep existing"/>
        </label>
        <label className="tc-token-consent"><input type="checkbox" checked={tokenConsent} onChange={event=>setTokenConsent(event.target.checked)}/> Store this verified token in the local, gitignored .env file. Do not send it to GitHub or the browser's storage.</label>
        <button type="submit" disabled={tokenBusy||!tokenConsent||!dhanToken.trim()}>{tokenBusy?'Verifying…':'Verify and save token'}</button>
      </form>}
      <p className="tc-muted">This verifies your Dhan session and Data API entitlement. Live WebSockets also need your Dhan client ID {dhanCheck?.client_id_configured?'(configured)':'(not configured or not yet checked)'}. This connection alone does not start market streaming.</p>
    </section>
          <section className="tc-panel tc-source-panel" aria-label="Shared market data library status">
      <div className="tc-panel-title"><strong>One shared market-data library · dhan_shared</strong><span>Original downloads are reusable source receipts, not separate datasets</span></div>
      <div className="tc-source-summary"><span>Ready one-minute charts <strong>{catalog?.prepared_equities??0}</strong></span><span>Existing minute sources awaiting chart preparation <strong>{pendingMinutes}</strong></span><span>BANKNIFTY spot index <strong>{missingBankNifty?'Original index not yet available':'Source available'}</strong></span></div>
      {sourceError&&<p className="tc-error" role="alert">{sourceError}</p>}
      {sourceNotice&&<p className="tc-confirm" role="status">{sourceNotice}</p>}
      {sourceJob&&sourceWorking&&<p className="tc-muted" role="status">{sourceJob.stage||'Preparing market data'} {sourceJob.percent!==undefined?'· '+Math.round(sourceJob.percent)+'%':''}</p>}
      {pendingMinutes>0&&<div className="tc-source-action"><p>Existing Dhan one-minute stock candles have been downloaded, but their analytical chart index has not been built. Reuse those files without downloading anything again.</p><button type="button" disabled={sourceWorking} onClick={()=>void prepareCached()}>Prepare {Math.min(40,pendingMinutes)} cached minute instruments</button></div>}
      {missingIndexSources.length>0&&<form className="tc-source-action" onSubmit={event=>void acquireSpot(event)}>
        <div><strong>The real index series needs its own original observations.</strong>
        <p>The downloaded constituent stocks are preserved, but they cannot substitute for BANKNIFTY or NIFTY 50 spot candles. Fetch missing IDX_I observations into the same shared library.</p></div>
        <label>Spot index <select aria-label="Missing index spot series" value={spotIdentity} onChange={e=>setSpotIdentity(e.target.value as 'INDEX:BANKNIFTY'|'INDEX:NIFTY50')}>{missingIndexSources.map(x=><option value={x.identity} key={x.identity}>{x.display_name}</option>)}</select></label>
        <label>From (IST) <input type="date" required value={spotFrom} onChange={e=>setSpotFrom(e.target.value)}/></label>
        <label>Through (exclusive) <input type="date" required value={spotTo} onChange={e=>setSpotTo(e.target.value)}/></label>
        <button type="submit" disabled={sourceWorking}>Get missing index spot candles</button>
      </form>}
      {!pendingMinutes&&!missingIndexSources.length&&<p className="tc-confirm">Existing local sources are prepared. These are historical observations, not a live broker stream.</p>}
      <p className="tc-muted">All sources remain internally partitioned by instrument, interval and observation time for accuracy; you manage one library. Missing source dates are never invented or backfilled from today's membership.</p>
    </section>
    </section>}
  </div>
}