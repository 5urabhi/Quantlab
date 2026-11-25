import LivePythonResults from './LivePythonResults'
import {useCallback,useEffect,useMemo,useState} from 'react'
import {Activity,Database,Radio,RefreshCw,ShieldCheck,Square,Search} from 'lucide-react'
import './live-feed.css'
import OptionChainLive,{type OptionContract} from './OptionChainLive'
import AutoDepthRecorder from './AutoDepthRecorder'
import ObservedIndexChartV2 from './ObservedIndexChartV2'
import RecordedChainSpot from './RecordedChainSpot'
import ResearchPlot from './ResearchPlots'
import {openSnapshotInPython} from './pythonBridge'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'

type DepthLevel={price:number;quantity:number;orders:number}
type Book={identity:string;received_utc:string;bid:DepthLevel[];ask:DepthLevel[];
  best_bid:number;best_ask:number;spread_bps:number;imbalance:number;bid_levels:number;
  ask_levels:number;full_depth:boolean;age_seconds:number;fresh:boolean;source_clock:string}
type AutoRecorder={armed:boolean;state:string;connected:boolean;chain_spot?:number;last_chain_utc?:string;contracts?:{identity:string;side:string;strike:number;expiry:string}[];snapshots_saved?:number;last_packet_utc?:string;last_error?:string}
type Quote={price:number;exchange_utc:string;received_utc:string;age_seconds:number;fresh:boolean;source:string}
type Feed={active:boolean;session_id?:string;index_identity?:string;depth_identity?:string|null;
  ticker_connection?:string;depth_connection?:string;auto_audit?:boolean;
  ticks?:number;depth_snapshots?:number;saved_books?:number;revision?:number;
  last_error?:string|null;ticker_note?:string;depth_note?:string;index_packet_note?:string;
  unsupported_index_packets?:number;started_utc?:string;
  quotes?:Record<string,Quote>;latest_book?:Book|null;client_id_configured:boolean;
  depth_recording?:string;audit_state?:string;read_only:boolean}
type Contract={identity:string;symbol:string;display_name:string;instrument:string;
  expiry?:string|null;strike?:string|null;option_type?:string|null}
type Signal={ready:boolean;reason?:string;identity:string;direction?:'UP'|'DOWN'|'NO_TRADE';
  quote_mode:string;latest_close?:number;last_observed_utc?:string;source_age_seconds?:number;
  rsi14?:number|null;ema9?:number|null;ema21?:number|null;
  contiguous_session_bars?:number;rows?:{timestamp_utc:string;close:number;open?:number;high?:number;low?:number}[];
  source_warning?:string}
const request = <T,>(path:string,body?:unknown):Promise<T>=>{
  const url='/api/trading-cockpit/live/'+path
  return body===undefined?marketApi<T>(url):marketPost<T>(url,body)
}
const fmt=(value:number|null|undefined,decimals=2)=>value===undefined||value===null?'—':
  value.toLocaleString('en-IN',{maximumFractionDigits:decimals})
const timeIST=(value?:string)=>value?new Date(value).toLocaleTimeString('en-IN',
  {timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit',second:'2-digit'}):'—'
const isExactDepth=(value:string)=>/^NSE_(?:EQ|FNO):[0-9]{1,12}$/.test(value)

export default function LiveFeedPanel({
  onOpenSetup,onDraftJournal,onOpenSaved,focusedView,hideNavigation=false,onViewChange,initialOptionMode
}:{
  onOpenSetup?:()=>void
  onOpenSaved?:()=>void
  onDraftJournal?:(contract:OptionContract,lots:number)=>void
  focusedView?:'signals'|'options'|'depth'
  hideNavigation?:boolean
  onViewChange?:(view:'signals'|'options'|'depth')=>void
  initialOptionMode?:'overview'|'analytics'|'directional'
}){
  const [view,setView]=useState<'signals'|'options'|'depth'>(focusedView||'options')
  useEffect(()=>{if(focusedView)setView(focusedView)},[focusedView])
  const changeView=(next:'signals'|'options'|'depth')=>{
    setView(next);onViewChange?.(next)
  }
  const [feed,setFeed]=useState<Feed|null>(null)
  const [automatic,setAutomatic]=useState<AutoRecorder|null>(null)
  const [savedBook,setSavedBook]=useState<Book|null>(null)
  const [savedBookError,setSavedBookError]=useState('')
  useEffect(()=>{let active=true;let busy=false;const poll=async()=>{if(busy)return;busy=true;try{const v=await marketApi<AutoRecorder>('/api/trading-cockpit/auto-depth/status');if(active)setAutomatic(v)}catch{if(active)setAutomatic(null)}finally{busy=false}};void poll();const timer=window.setInterval(()=>void poll(),8000);return()=>{active=false;window.clearInterval(timer)}},[])
  const [connectedToLocal,setConnectedToLocal]=useState(false)
  const [index,setIndex]=useState<'INDEX:BANKNIFTY'|'INDEX:NIFTY50'>('INDEX:BANKNIFTY')
  const [contractSearch,setContractSearch]=useState('BANKNIFTY')
  const [contracts,setContracts]=useState<Contract[]>([])
  const [contractInfo,setContractInfo]=useState('')
  const [depthIdentity,setDepthIdentity]=useState('')
  const [autoAudit,setAutoAudit]=useState(true)
  const [consent,setConsent]=useState(false)
  const [busy,setBusy]=useState(false)
  const [queryBusy,setQueryBusy]=useState(false)
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')
  const [signal,setSignal]=useState<Signal|null>(null)
  const [replayHorizon,setReplayHorizon]=useState<'3'|'6'>('6')
  const [configOpen,setConfigOpen]=useState(false)
  const [now,setNow]=useState(()=>Date.now())

  const refresh=useCallback(async()=>{
    try{setFeed(await request<Feed>('status'))}
    catch(e){setError(readableError(e))}
  },[])
  useEffect(()=>{
    void refresh()
    const stream=new EventSource('/api/trading-cockpit/live/events')
    stream.onmessage=(event:MessageEvent<string>)=>{
      try{setFeed(JSON.parse(event.data) as Feed);setConnectedToLocal(true)}
      catch{setConnectedToLocal(false)}
    }
    stream.onerror=()=>setConnectedToLocal(false)
    const clock=window.setInterval(()=>setNow(Date.now()),1000)
    return()=>{stream.close();window.clearInterval(clock)}
  },[refresh])
  useEffect(()=>{
    if(!automatic?.armed||view!=='depth'||!isExactDepth(depthIdentity)){setSavedBook(null);return}
    let active=true,running=false;setSavedBook(null);setSavedBookError('')
    const poll=async()=>{if(running)return;running=true;try{
      const data=await marketApi<{snapshots:Book[]}>('/api/trading-cockpit/live/depth-history?'+new URLSearchParams({identity:depthIdentity,limit:'1'}))
      if(active){setSavedBook(data.snapshots.at(-1)||null);setSavedBookError('')}
    }catch(e){if(active){setSavedBook(null);setSavedBookError(readableError(e))}}finally{running=false}}
    void poll();const timer=window.setInterval(()=>void poll(),5000)
    return()=>{active=false;window.clearInterval(timer)}
  },[automatic?.armed,view,depthIdentity])
  const watchedIndex=feed?.active?(feed.index_identity||index):index
  useEffect(()=>{
    const poll=async()=>{
      try{setSignal(await request<Signal>('signal?'+new URLSearchParams({identity:watchedIndex})))}
      catch(e){setError(readableError(e))}
    }
    void poll()
    const interval=window.setInterval(()=>{void poll()},4000)
    return()=>window.clearInterval(interval)
  },[watchedIndex,feed?.active])
  const findContracts=async()=>{
    if(queryBusy)return
    setQueryBusy(true);setError('');setContractInfo('')
    try{
      const found=await request<{contracts:Contract[];catalog_available:boolean;message:string}>(
        'contracts?'+new URLSearchParams({query:contractSearch.trim(),limit:'35'}))
      setContracts(found.contracts);setContractInfo(found.message)
    }catch(e){setError(readableError(e))}
    finally{setQueryBusy(false)}
  }
  const start=async()=>{
    if(busy||!consent)return
    setBusy(true);setError('');setNotice('')
    try{
      const state=await request<Feed>('start',{
        index_identity:index,depth_identity:depthIdentity.trim().toUpperCase(),
        auto_audit:autoAudit,confirm_live_data:true})
      setFeed(state);setNotice('Broker WebSockets starting. Wait for actual observed packets before interpreting a signal.')
      setConsent(false)
    }catch(e){setError(readableError(e))}
    finally{setBusy(false)}
  }
  const stop=async()=>{
    if(busy)return
    setBusy(true);setError('');setNotice('')
    try{setFeed(await request<Feed>('stop',{}));setNotice('Live session stopped. Saved observations remain available for research.')}
    catch(e){setError(readableError(e))}
    finally{setBusy(false)}
  }
  const record=async()=>{
    if(busy)return
    setBusy(true);setError('')
    try{
      const r=await fetch('/api/trading-cockpit/live/predictions',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({identity:watchedIndex,horizon_minutes:Number(replayHorizon)})})
      if(!r.ok){const b=await r.json() as {detail?:string};throw new Error(b.detail||'Live prediction unavailable')}
      setNotice('Prospective '+replayHorizon+'-minute prediction permanently recorded.')
    }catch(e){setError(readableError(e))}
    finally{setBusy(false)}
  }
  const quote=feed?.quotes?.[watchedIndex]
  const optionQuote=feed?.depth_identity?feed.quotes?.[feed.depth_identity]:undefined
  const usingSaved=Boolean(automatic?.armed&&!feed?.active)
  const liveBook=usingSaved?(savedBook?.identity===depthIdentity?savedBook:null):feed?.latest_book
  const quoteAge=quote?Math.max(0,(now-Date.parse(quote.received_utc))/1000):null
  const livePrice=Boolean(feed?.active&&feed.ticker_connection==='connected'
    &&quoteAge!==null&&quoteAge<=8&&quote?.fresh)
  const bookAge=liveBook?Math.max(0,(now-Date.parse(liveBook.received_utc))/1000):null
  const bookFresh=Boolean(feed?.active&&feed.depth_connection==='connected'
    &&bookAge!==null&&bookAge<=8&&liveBook?.fresh)
  const hasSignal=Boolean(livePrice&&signal?.ready&&signal.quote_mode==='LIVE_OBSERVED')
  const bookRows=useMemo(()=>liveBook?Array.from({length:Math.min(20,
    Math.max(liveBook.bid.length,liveBook.ask.length))},(_,i)=>({
      bid:liveBook.bid[i],ask:liveBook.ask[i],position:i+1,
    })):[],[liveBook])
  const configuredDepth=feed?.active?feed.depth_identity:depthIdentity
  const autoContracts=automatic?.contracts||[]
  return <section className="tc-panel lf-root" aria-label="Live BANKNIFTY and 20-level market feed">
    <div className="tc-panel-title lf-title"><div><strong><Radio size={17}/>{hideNavigation?
      view==='signals'?'BANKNIFTY index & signal monitor':
      view==='depth'?'Original 20-level CE/PE order book':
      'BANKNIFTY CE/PE option chain':
      'Manual live index + single-contract depth'}</strong>
      <p className="tc-muted">{hideNavigation?
      'Live index/contract observations come from genuine Dhan packets. The automatic 190-contract CE/PE recorder is configured separately in Settings; navigation never stops it.':
      'This manual feed is independent from automatic BANKNIFTY CE/PE 20-level recording below. Both use read-only Dhan data; neither places broker orders.'}</p></div>
      <span className={'lf-badge '+(livePrice?'live':feed?.active?'connecting':'offline')}>
        {livePrice?'LIVE INDEX · FRESH':feed?.active?'INDEX FEED STARTING / STALE':automatic?.armed?'AUTOMATIC RECORDER ARMED':'NOT STREAMING'}</span>
    </div>
    <div className="lf-meta"><span>Local UI stream <b>{connectedToLocal?'Connected':'Reconnecting'}</b></span>
      <span>Index ticker <b>{feed?.ticker_connection||'Not started'}</b></span>
      <span>20-level feed <b>{feed?.depth_connection||'Not started'}</b></span>
      <span>Stored in <b>dhan_shared</b></span><span>Automatic recorder <b>{automatic?automatic.armed?automatic.state.replaceAll('_',' '):'Off':'Checking'}</b></span></div>
    {error&&<p role="alert" className="tc-error">{error}</p>}
    {notice&&<p role="status" className="tc-confirm">{notice}</p>}
    {!hideNavigation&&<nav className="lf-view-tabs" role="tablist" aria-label="Live trading views">
      <button type="button" role="tab" aria-selected={view==='signals'}
        onClick={()=>changeView('signals')}><Activity size={16}/> Index signal monitor</button>
      <button type="button" role="tab" aria-selected={view==='options'}
        onClick={()=>changeView('options')}><Database size={16}/> BANKNIFTY option chain &amp; 20-level depth</button>
      <button type="button" role="tab" aria-selected={view==='depth'}
        onClick={()=>changeView('depth')}><Database size={16}/> 20-level order book</button>
    </nav>}
    {view==='options'&&!hideNavigation&&<AutoDepthRecorder onOpenSaved={onOpenSaved}/>}
    {view==='options'&&<OptionChainLive initialMode={initialOptionMode} automaticRecording={Boolean(automatic?.armed)}
      feedActive={Boolean(feed?.active)} depthIdentity={feed?.active?feed.depth_identity||'':depthIdentity}
      currentIndexDirection={hasSignal?signal?.direction||null:null}
      openConnections={()=>onOpenSetup?.()}
      onSelectDepth={identity=>{
        setDepthIdentity(identity);setIndex('INDEX:BANKNIFTY');setConfigOpen(!automatic?.armed)
        setNotice(automatic?.armed?'Contract selected. Inspect the latest locally saved original book; no extra socket is opened.':'Contract selected. Confirm read-only Dhan 20-level streaming below to start its original order book.')
        if(hideNavigation)changeView('depth')
      }}
      onDraftJournal={(contract,lots)=>onDraftJournal?.(contract,lots)}
    />}
    {view==='options'&&<LivePythonResults mode="options"/>}
    {feed?.index_packet_note&&!livePrice&&<p className="tc-warning" role="status">
      Broker index packet not supported by the published binary layout · {feed.unsupported_index_packets} observed.
      {' '}{feed.index_packet_note}</p>}
    {view==='signals'&&<>
      <ObservedIndexChartV2 rows={signal?.rows||[]} instrument={watchedIndex==='INDEX:NIFTY50'?'NIFTY 50':'BANKNIFTY'}
        sourceWarning={signal?.source_warning||''}/>
      {automatic?.armed&&!feed?.active&&<RecordedChainSpot/>}
      {watchedIndex!=='INDEX:NIFTY50'&&<LivePythonResults mode="index"/>}
      <div className="lf-cards">
      <div className="lf-stat"><span>Live index level</span><strong>{livePrice?fmt(quote?.price)+' pts':'—'}</strong>
        <small>{livePrice?'Last observed '+timeIST(quote?.exchange_utc)+' IST':
          'Waiting for fresh Dhan ticker data'}</small></div>
      <div className="lf-stat"><span>Source age</span><strong>{quoteAge===null?'—':fmt(quoteAge,1)+' s'}</strong>
        <small>{livePrice?'Received from authenticated Dhan feed':'Stale or unverified'}</small></div>
      <div className="lf-stat"><span>Next {replayHorizon} min index direction</span><strong className={hasSignal?'lf-good':'lf-neutral'}>
        {hasSignal?(signal?.direction==='UP'?'UP':signal?.direction==='DOWN'?'DOWN':'NO TRADE'):'NOT READY'}</strong>
        <small>{signal?.contiguous_session_bars??0} consecutive completed observed one-minute bars · minimum 30</small></div>
      <div className="lf-stat"><span>Depth best bid / ask</span><strong>{bookFresh?
        '₹'+fmt(liveBook?.best_bid)+' / ₹'+fmt(liveBook?.best_ask):'—'}</strong>
        <small>{bookFresh?'Original paired 20-level book':'No fresh NSE depth snapshot'}</small></div>
    </div></>}

    {!feed?.active&&!automatic?.armed&&<div className="lf-connect-block">
      <div><strong>Real-time feed is stopped</strong><p>Index signals and 20-level depth require original broker packets. Historical analysis remains separate and available at any time.</p></div>
      <button type="button" onClick={()=>setConfigOpen(v=>!v)}>{configOpen?'Close manual controls':'Manual feed controls'}</button>
    </div>}
    {!feed?.active&&!automatic?.armed&&feed&&!feed.client_id_configured&&<div className="lf-connect-warning" role="status">
      <span>{hideNavigation?
        'Dhan access needs verification. QuantLab can resolve the client ID from the authenticated profile when a valid local token is available.':
        'Add your Dhan client ID and token in Connections before starting a stream.'}</span>
      {onOpenSetup&&<button type="button" onClick={onOpenSetup}>Open Connections</button>}
    </div>}
    {!feed?.active&&!automatic?.armed&&configOpen&&<div className="lf-start-form">
      <label>Analyze index<select aria-label="Live underlying index" value={index}
        onChange={e=>setIndex(e.target.value as typeof index)}>
        <option value="INDEX:BANKNIFTY">BANKNIFTY · spot index</option>
        <option value="INDEX:NIFTY50">NIFTY 50 · spot index</option>
      </select></label>
      {view==='signals'&&<div className="lf-contract-search">
        <label>Find a BANKNIFTY option for 20-level depth
          <span className="lf-search-row"><input value={contractSearch}
            onChange={e=>setContractSearch(e.target.value.toUpperCase())}
            placeholder="BANKNIFTY"/><button type="button" onClick={()=>void findContracts()} disabled={queryBusy}>
            <Search size={15}/>{queryBusy?'Searching':'Find contracts'}</button></span></label>
        {!!contractInfo&&<small className="tc-muted">{contractInfo}</small>}
        {!!contracts.length&&<select aria-label="Choose Dhan option contract" defaultValue=""
          onChange={e=>{if(e.target.value)setDepthIdentity(e.target.value)}}>
          <option value="">Choose a real Dhan option contract…</option>
          {contracts.map(c=><option key={c.identity} value={c.identity}>
            {c.display_name||c.symbol} · {c.identity} {c.expiry||''}</option>)}</select>}
      </div>}
      <label>20-level depth instrument (optional)
        <input aria-label="Exact depth instrument" placeholder="NSE_FNO:12345 or NSE_EQ:1333"
          value={depthIdentity} onChange={e=>setDepthIdentity(e.target.value.toUpperCase())}/>
        <small>Choose a real listed option or bank stock. Indices have no order book; leave blank for index price-only streaming.</small>
      </label>
      <label className="lf-consent"><input type="checkbox" checked={autoAudit}
        onChange={e=>setAutoAudit(e.target.checked)}/> Automatically record and evaluate genuine 3/6-minute decisions while the local server runs</label>
      <label className="lf-consent"><input type="checkbox" checked={consent}
        onChange={e=>setConsent(e.target.checked)}/> Start authorized read-only Dhan streaming and locally record real observations</label>
      <button className="lf-primary" type="button" onClick={()=>void start()}
        disabled={busy||!consent||Boolean(depthIdentity.trim()&&!isExactDepth(depthIdentity.trim()))}>
        <Activity size={16}/>{busy?'Connecting':'Start live feed'}
      </button>
    </div>}
    {feed?.active&&<div className="lf-live-actions"><div><strong>Running: {watchedIndex.replace('INDEX:','')}</strong>
      <small>20-level target: {configuredDepth||'None selected · index prices only'}</small>
      <small>Index packets {fmt(feed.ticks,0)} · depth snapshots {fmt(feed.depth_snapshots,0)} · saved samples {fmt(feed.saved_books,0)}</small></div>
      <button type="button" onClick={()=>void stop()} disabled={busy}><Square size={15}/> Stop streams</button>
      <button type="button" onClick={()=>void refresh()}><RefreshCw size={15}/> Check connection</button>
    </div>}
    {automatic?.armed&&!feed?.active&&<div className="lf-connect-block"><div><strong>Automatic BANKNIFTY recording is armed</strong><p>Original CE/PE capture runs independently using the reserved Dhan sockets. {automatic.last_chain_utc?'Last recorded chain spot: '+fmt(automatic.chain_spot)+' points · '+timeIST(automatic.last_chain_utc)+' IST. ':''}The manual index ticker is separate and cannot run concurrently; a chain snapshot is not a live directional signal.</p></div>{onOpenSaved&&<button type="button" onClick={onOpenSaved}>View recorded market</button>}</div>}
    {(view==='depth'||(view==='options'&&!hideNavigation))&&
      <div className="lf-depth-summary">
      <div className="tc-panel-title"><strong>20-level market depth · {configuredDepth||'select a stock / option'}</strong>
        <span>Original NSE equity/derivative packet pairs · available levels only</span></div>
      {usingSaved&&<div className="lf-start-form"><label>Automatically captured contract<select aria-label="Automatically captured depth contract" value={depthIdentity} onChange={e=>setDepthIdentity(e.target.value)}><option value="">Select recorded contract</option>{depthIdentity&&!autoContracts.some(c=>c.identity===depthIdentity)&&<option value={depthIdentity}>{depthIdentity} · selected / not currently subscribed</option>}{autoContracts.map(c=><option key={c.identity} value={c.identity}>{c.strike} {c.side} · {c.expiry} · {c.identity}</option>)}</select></label><small>Reads the latest saved original book. No new broker subscription; a saved sample is not a live quote.</small></div>}
      {savedBookError&&usingSaved&&<p role="alert" className="tc-error">{savedBookError}</p>}
      {optionQuote&&<div className="lf-meta">
        <span>Selected option/stock last observed premium <b>₹{fmt(optionQuote.price)}</b></span>
        <span>Received <b>{timeIST(optionQuote.received_utc)} IST</b></span>
        <span>Ticker freshness <b>{optionQuote.fresh?'Fresh':'STALE'}</b></span>
      </div>}
      {liveBook&&<div className="lf-meta"><span>Bid–ask spread <b>{fmt(liveBook.spread_bps)} bps</b></span>
        <span>Order-book imbalance <b>{fmt((liveBook.imbalance+1)*50,1)}% bid-side share</b></span>
        <span>Book update <b>{timeIST(liveBook.received_utc)} IST</b></span>
        <span>Status <b>{usingSaved?'Saved sample · '+Math.max(0,Math.round((now-Date.parse(liveBook.received_utc))/1000))+'s old':bookFresh?'Fresh':'STALE'}</b></span></div>}
      {liveBook?<div className="tc-table-scroll"><table><thead><tr><th>Level</th><th>Bid qty</th><th>Bid orders</th><th>Bid price (₹)</th><th>Ask price (₹)</th><th>Ask orders</th><th>Ask qty</th></tr></thead>
        <tbody>{bookRows.map(row=><tr key={row.position}><td>{row.position}</td><td>{fmt(row.bid?.quantity,0)}</td>
          <td>{fmt(row.bid?.orders,0)}</td><td>{fmt(row.bid?.price)}</td><td>{fmt(row.ask?.price)}</td>
          <td>{fmt(row.ask?.orders,0)}</td><td>{fmt(row.ask?.quantity,0)}</td></tr>)}</tbody></table></div>:
        <p className="tc-missing"><Database size={17}/> No paired 20-level Dhan packets yet.
          You may need full-market-depth entitlement and an active NSE_EQ or NSE_FNO contract.</p>}
      {liveBook&&<><ResearchPlot plot={{kind:'step2d',title:'Displayed cumulative depth by price',x_label:'Option / stock price (₹ per unit)',y_label:'Cumulative displayed quantity (units)',x:[...liveBook.bid,...liveBook.ask].map(v=>v.price).filter((v,i,all)=>all.indexOf(v)===i).sort((a,b)=>a-b),traces:(()=>{const levels=[...liveBook.bid,...liveBook.ask].map(v=>v.price).filter((v,i,all)=>all.indexOf(v)===i).sort((a,b)=>a-b);return [{name:'Bids at or above price',color:'#70e1ad',y:levels.map(p=>p<=liveBook.best_bid?liveBook.bid.filter(v=>v.price>=p).reduce((sum,v)=>sum+v.quantity,0):null)},{name:'Asks at or below price',color:'#ff8192',y:levels.map(p=>p>=liveBook.best_ask?liveBook.ask.filter(v=>v.price<=p).reduce((sum,v)=>sum+v.quantity,0):null)}]})()}} provenance="original-depth-snapshot"/><button type="button" className="ws-button secondary" onClick={()=>openSnapshotInPython({title:'Original order book '+liveBook.identity,provenance:'Saved or streaming original book · '+liveBook.received_utc,columns:['Level','Bid price (₹)','Bid qty','Ask price (₹)','Ask qty'],rows:bookRows.map(r=>[r.position,r.bid?.price??null,r.bid?.quantity??null,r.ask?.price??null,r.ask?.quantity??null])})}>Analyze depth in Python</button></>}
      <p className="tc-muted">20-level depth is NOT available on IDX_I itself. Depth is sampled for storage at up to one observed pair per second, while the live screen uses the newest observed packet. No historical book is inferred from candles.</p>
    </div>}
    {view==='signals'&&<div className="lf-signal-actions">
      <div><strong>Record prospective index call</strong><p>Only available after genuine fresh Dhan index packets and at least 30 consecutive completed one-minute candles. Results are evaluated against observed future candles.</p></div>
      <label>Horizon <select value={replayHorizon} onChange={e=>setReplayHorizon(e.target.value as '3'|'6')}>
        <option value="3">3 minutes</option><option value="6">6 minutes</option></select></label>
      <button type="button" onClick={()=>void record()} disabled={!hasSignal||busy}>Record {replayHorizon}m prediction</button>
    </div>}
    <div className="tc-warning"><ShieldCheck size={14}/> Read-only research. Real-time data requires valid Dhan Data API plus live market/depth permissions. A connected socket is not proof of fresh trades. Any stale feed, absent market data or missing completed candles disables live directional claims. Closing this tab does not stop the local streaming session; clicking Stop or shutting down QuantLab does.</div>
  </section>
}
