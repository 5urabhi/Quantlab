import {useCallback, useEffect, useMemo, useRef, useState} from 'react'
import {Clock3, Database, RefreshCw, ShieldCheck} from 'lucide-react'
import './trading-cockpit.css'

type Candle = {timestamp_utc:string;session_ist:string;open:number;high:number;low:number;close:number;volume:number;ema9:number|null;ema21:number|null}
type Entry = {id:string;created_utc:string;identity:string;bar_utc:string;direction:string;reference_close:number;horizon_minutes:number;quote_mode:string;evaluation:string;observed_close:number|null;actual_direction:string|null}
type Snapshot = {identity:string;model_version:string;horizon_minutes:number;quote_mode:string;last_observed_utc:string;source_age_seconds:number;direction:'UP'|'DOWN'|'NO_TRADE';confidence:null;validation:string;latest_close:number;rsi14:number|null;atr14:number|null;ema9:number|null;ema21:number|null;rows:Candle[];note:string;source_warning:string;has_more:boolean}
type SourceInstrument = {identity:string;display_name?:string;asset_class?:string;ready:boolean;state:string;needs_preparation?:boolean;needs_download?:boolean}
type Catalog = {instruments:SourceInstrument[];prepared_equities:number;downloaded_equities_pending_preparation:number}
type SourceJob = {id:string;status:string;stage?:string;percent?:number;error?:string;result?:{status?:string;prepared_count?:number;blocked_count?:number;checked?:number;rows?:number;remaining_unselected?:number}}
type History = {predictions:Entry[];summary:{evaluated_directions:number;correct_directions:number;direction_accuracy:number|null;qualification:string}}
type DaySummary = {session_ist:string;total:number;scored:number;correct:number;incorrect:number;pending:number;no_trade:number;flat:number;unverifiable:number;directional_accuracy:number|null}
type Report = {days:DaySummary[];overall:Omit<DaySummary,'session_ist'>;source:string;disclaimer:string;truncated:boolean}
type Replay = {mode:string;identity:string;model_version:string;horizon_minutes:number;observed_source_bars:number;overall:Omit<DaySummary,'session_ist'>;days:DaySummary[];has_more_history:boolean;source_warning:string;disclaimer:string}
type DhanCheck = {ok:boolean;code:string;message:string;token_present:boolean;token_valid:boolean|null;data_plan_active:boolean|null;expires_at_utc?:string|null;seconds_remaining?:number|null}
type DhanConnect = {connected:boolean;message:string}
type ManualTrade = {id:string;symbol:string;direction:'CALL'|'PUT';quantity:number;entry_price:number;entry_recorded_utc:string;exit_price:number|null;exit_recorded_utc:string|null;holding_seconds:number;holding_rule_exceeded:boolean;gross_notional_inr:number;net_pnl_inr:number|null;status:'OPEN'|'CLOSED';data_quality:string}
type TradeJournal = {trades:ManualTrade[];summary:{open:number;closed:number;closed_net_pnl_inr:number;holding_violations:number;days:{exit_session_ist:string;closed:number;net_pnl_inr:number;over_6_min:number}[]};disclaimer:string}

async function api<T>(path:string,init?:RequestInit):Promise<T>{
  const response=await fetch(path,init)
  if(!response.ok){
    let detail='Local analysis unavailable'
    try{const result=await response.json() as {detail?:string};detail=result.detail||detail}catch{/* no body */}
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}
const fmt=(v:number|null|undefined,digits=2)=>v===null||v===undefined?'—':v.toLocaleString('en-IN',{maximumFractionDigits:digits})
const post=(path:string,body:unknown)=>api<unknown>(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
const indiaDate=(offsetDays=0)=>{const d=new Date();d.setUTCDate(d.getUTCDate()+offsetDays);return d.toLocaleDateString('sv-SE',{timeZone:'Asia/Kolkata'})}

function CandleChart({rows}:{rows:Candle[]}){
  const [hover,setHover]=useState<number|null>(null)
  const data=rows.slice(-150)
  if(!data.length)return <p className="tc-muted">No original one-minute data available.</p>
  const values=data.flatMap(c=>[c.low,c.high,c.ema9??c.close,c.ema21??c.close])
  const min=Math.min(...values),max=Math.max(...values),range=Math.max(0.001,max-min)
  const height=310, width=970, left=54,right=16,top=18,bottom=27,chartW=width-left-right,chartH=height-top-bottom
  const x=(i:number)=>left+(i+.5)*chartW/data.length
  const y=(p:number)=>top+(max-p)/range*chartH
  const line=(key:'ema9'|'ema21')=>{
    let started=false
    return data.map((row,i)=>{
      const value=row[key]
      if(value===null){started=false;return ''}
      const command=started?'L':'M'
      started=true
      return `${command}${x(i).toFixed(1)},${y(value).toFixed(1)}`
    }).join(' ')
  }
  const step=chartW/data.length
  const selected=hover===null?data[data.length-1]:data[hover]
  return <div className="tc-chart">
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Observed one-minute OHLC candles with 9 and 21-period EMA" onMouseMove={event=>{
      const rect=event.currentTarget.getBoundingClientRect()
      const px=(event.clientX-rect.left)/rect.width*width
      setHover(Math.max(0,Math.min(data.length-1,Math.floor((px-left)/chartW*data.length))))
    }} onMouseLeave={()=>setHover(null)}>
      {[0,.25,.5,.75,1].map(f=><g key={f}><line x1={left} y1={top+f*chartH} x2={width-right} y2={top+f*chartH} stroke="#28364c" strokeDasharray="3 5"/><text x="4" y={top+f*chartH+4} fontSize="12" fill="#9eafc4">{fmt(max-f*range,0)}</text></g>)}
      {data.map((r,i)=><g key={r.timestamp_utc} stroke={r.close>=r.open?'#2ed3a2':'#f37b86'} fill={r.close>=r.open?'#2ed3a2':'#f37b86'}>
        <line x1={x(i)} x2={x(i)} y1={y(r.high)} y2={y(r.low)}/>
        <rect x={x(i)-Math.max(.7,step*.32)} y={Math.min(y(r.open),y(r.close))} width={Math.max(1.4,step*.64)} height={Math.max(1,Math.abs(y(r.open)-y(r.close)))}/>
      </g>)}
      <path d={line('ema9')} fill="none" stroke="#e9ae57" strokeWidth="1.8"/>
      <path d={line('ema21')} fill="none" stroke="#72b3fa" strokeWidth="1.8"/>
      {hover!==null&&<line x1={x(hover)} x2={x(hover)} y1={top} y2={top+chartH} stroke="#dce9f8" opacity=".65" strokeDasharray="3 5"/>}
      <text x={left} y={height-5} fill="#99aabd" fontSize="12">{data[0].session_ist}</text>
      <text x={width-110} y={height-5} fill="#99aabd" fontSize="12">{new Date(data[data.length-1].timestamp_utc).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit'})} IST</text>
    </svg>
    <div className="tc-chart-caption">{new Date(selected.timestamp_utc).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'})} · O {fmt(selected.open)} · H {fmt(selected.high)} · L {fmt(selected.low)} · C {fmt(selected.close)} · Vol {fmt(selected.volume,0)}</div>
  </div>
}

export default function TradingCockpit(){
  const [instruments,setInstruments]=useState<Catalog['instruments']>([])
  const [catalog,setCatalog]=useState<Catalog|null>(null)
  const [sourceJob,setSourceJob]=useState<SourceJob|null>(null)
  const [sourceBusy,setSourceBusy]=useState(false)
  const [sourceNotice,setSourceNotice]=useState('')
  const [sourceError,setSourceError]=useState('')
  const [spotFrom,setSpotFrom]=useState(()=>indiaDate(-45))
  const [spotTo,setSpotTo]=useState(()=>indiaDate(1))
  const [identity,setIdentity]=useState('')
  const [snapshot,setSnapshot]=useState<Snapshot|null>(null)
  const [history,setHistory]=useState<History|null>(null)
  const [report,setReport]=useState<Report|null>(null)
  const [replay,setReplay]=useState<Replay|null>(null)
  const [replayBusy,setReplayBusy]=useState(false)
  const [monitor,setMonitor]=useState(false)
  const monitorRef=useRef(false)
  const [horizon,setHorizon]=useState<3|6>(6)
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
  const [paused,setPaused]=useState(false)
  const [journal,setJournal]=useState<TradeJournal|null>(null)
  const [optionSymbol,setOptionSymbol]=useState('')
  const [optionSide,setOptionSide]=useState<'CALL'|'PUT'>('PUT')
  const [optionQty,setOptionQty]=useState('1')
  const [optionEntry,setOptionEntry]=useState('')
  const [tradeNote,setTradeNote]=useState('')
  const [dhanCheck,setDhanCheck]=useState<DhanCheck|null>(null)
  const [dhanToken,setDhanToken]=useState('')
  const [tokenForm,setTokenForm]=useState(false)
  const [tokenConsent,setTokenConsent]=useState(false)
  const [tokenBusy,setTokenBusy]=useState(false)
  const [tokenError,setTokenError]=useState('')
  const [tokenMessage,setTokenMessage]=useState('')
  const [replayLimit,setReplayLimit]=useState('1500')
  const [journalBusy,setJournalBusy]=useState(false)
  const [closingId,setClosingId]=useState('')
  const [exitPremium,setExitPremium]=useState('')
  const [fees,setFees]=useState('0')

  const checkDhan=useCallback(async()=>{
    try{
      const state=await api<DhanCheck>('/api/dhan/credentials/check')
      setDhanCheck(state);setTokenError('')
    }catch(e){setTokenError(e instanceof Error?e.message:String(e))}
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
        body:JSON.stringify({access_token:dhanToken,confirm_local_storage:true}),
      })
      setDhanToken('');setTokenForm(false);setTokenConsent(false)
      setTokenMessage(connected.message)
      await checkDhan()
    }catch(e){setTokenError(e instanceof Error?e.message:String(e))}
    finally{setTokenBusy(false)}
  }
  const loadJournal=useCallback(async()=>{
    try{setJournal(await api<TradeJournal>('/api/trading-cockpit/trades?limit=80'))}
    catch(e){setError(e instanceof Error?e.message:String(e))}
  },[])
  useEffect(()=>{void loadJournal()},[loadJournal])
  const recordEntry=async(event:React.FormEvent<HTMLFormElement>)=>{
    event.preventDefault()
    if(journalBusy)return
    setJournalBusy(true);setError('')
    try{
      await post('/api/trading-cockpit/trades',{
        symbol:optionSymbol.trim().toUpperCase(),direction:optionSide,
        quantity:Number(optionQty),entry_price:Number(optionEntry),note:tradeNote})
      setOptionEntry('');setTradeNote('');setStartTime(Date.now())
      setRecordMessage('Manual position opened. Six-minute timer started. No broker order submitted.')
      await loadJournal()
    }catch(e){setError(e instanceof Error?e.message:String(e))}
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
    }catch(e){setError(e instanceof Error?e.message:String(e))}
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
    setIdentity(previous=>{
      if(data.instruments.some(x=>x.ready&&x.identity===previous))return previous
      return data.instruments.find(x=>x.ready&&x.identity==='INDEX:BANKNIFTY')?.identity
        ||data.instruments.find(x=>x.ready)?.identity||''
    })
  },[])
  useEffect(()=>{void refreshCatalog().catch(e=>setSourceError(String(e)))},[refreshCatalog])
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
            void refreshCatalog().catch(e=>setSourceError(String(e)))
          }else if(next.status==='error'||next.status==='cancelled'){
            setSourceError(next.error||'The local source task needs attention.')
          }
        }).catch(e=>{if(active)setSourceError(String(e))})
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
    }catch(e){setSourceError(e instanceof Error?e.message:String(e))}
    finally{setSourceBusy(false)}
  }
  const acquireSpot=async(event:React.FormEvent<HTMLFormElement>)=>{
    event.preventDefault()
    if(sourceBusy||['queued','running'].includes(sourceJob?.status||''))return
    if(!window.confirm('Download original BANKNIFTY spot index history from Dhan? Existing equities remain in the same shared library, and no order will be placed.'))return
    setSourceBusy(true);setSourceError('');setSourceNotice('')
    try{
      const result=await api<{job_id:string;status:string}>(
        '/api/trading-cockpit/sources/index-spot',{method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({identity:'INDEX:BANKNIFTY',from_date:spotFrom,
            to_date:spotTo,confirm_readonly:true})})
      setSourceJob({id:result.job_id,status:result.status})
    }catch(e){setSourceError(e instanceof Error?e.message:String(e))}
    finally{setSourceBusy(false)}
  }
  const refresh=useCallback(async()=>{
    if(!identity)return
    setError('')
    try{
      if(monitorRef.current){
        await post('/api/trading-cockpit/monitor/tick',{identity,horizon_minutes:6})
      }
      const [observed,ledger,daily]=await Promise.all([
        api<Snapshot>('/api/trading-cockpit/snapshot?'+new URLSearchParams({identity,limit:'500'})),
        api<History>('/api/trading-cockpit/predictions?'+new URLSearchParams({identity,limit:'60'})),
        api<Report>('/api/trading-cockpit/report?'+new URLSearchParams({identity})),
      ])
      setSnapshot(observed);setHistory(ledger);setReport(daily)
    }catch(e){setError(e instanceof Error?e.message:String(e))}
  },[identity])
  useEffect(()=>{setSnapshot(null);setHistory(null);setReplay(null);setReport(null);void refresh()},[refresh])
  useEffect(()=>{
    const timer=window.setInterval(()=>setNow(Date.now()),1000)
    return()=>window.clearInterval(timer)
  },[])
  useEffect(()=>{
    if(!identity||paused)return
    const timer=window.setInterval(()=>{void refresh()},15000)
    return()=>window.clearInterval(timer)
  },[identity,refresh,paused])
  const action=async(kind:'record'|'evaluate')=>{
    if(!identity||busy)return
    setBusy(true);setRecordMessage('');setError('')
    try{
      if(kind==='record'){
        const recorded=await post('/api/trading-cockpit/predictions',{identity,horizon_minutes:horizon}) as Entry
        setRecordMessage('Saved unchanged: '+recorded.direction+' at '+recorded.bar_utc)
      }else{
        const data=await post('/api/trading-cockpit/evaluate',{identity,horizon_minutes:horizon}) as History & {updated:number}
        setRecordMessage('Evaluated '+data.updated+' predictions against available source bars.')
      }
      await refresh()
    }catch(e){setError(e instanceof Error?e.message:String(e))}
    finally{setBusy(false)}
  }
  const runReplay=async()=>{
    if(!identity||replayBusy)return
    setReplayBusy(true);setError('')
    try{
      const result=await api<Replay>('/api/trading-cockpit/replay?'+
        new URLSearchParams({identity,horizon_minutes:String(horizon),limit:replayLimit}))
      setReplay(result)
    }catch(e){setError(e instanceof Error?e.message:String(e))}
    finally{setReplayBusy(false)}
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
  const preparedInstruments=instruments.filter(x=>x.ready)
  const missingBankNifty=!instruments.some(x=>x.identity==='INDEX:BANKNIFTY'&&x.ready)
  const pendingMinutes=catalog?.downloaded_equities_pending_preparation??0
  const sourceWorking=sourceBusy||['queued','running'].includes(sourceJob?.status||'')
  const forecast=snapshot?.direction??'NO_TRADE'
  const sourceRecent=snapshot?.quote_mode==='RECENT_LOCAL_CANDLE_NOT_VERIFIED_LIVE'
  const summary=history?.summary
  const dataStatus=useMemo(()=>{
    if(!snapshot)return 'NO ORIGINAL DATA'
    return sourceRecent?'RECENT CANDLE · NOT LIVE QUOTE':'HISTORICAL · NOT LIVE'
  },[snapshot,sourceRecent])
  return <div className="tc-shell">
    <header className="tc-header"><div><div className="tc-eyebrow">QUANTLAB / READ-ONLY MARKET RESEARCH</div><h2>Intraday trading cockpit</h2><p>One-minute observed candles · 3/6-minute forecasts · permanent outcome audit</p></div><span className={'tc-data-badge '+(sourceRecent?'tc-recent':'')}>{dataStatus}</span></header>
    {error&&<div className="tc-error" role="alert">{error}</div>}
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
        <label className="tc-token-consent"><input type="checkbox" checked={tokenConsent} onChange={event=>setTokenConsent(event.target.checked)}/> Store this verified token in the local, gitignored .env file. Do not send it to GitHub or the browser's storage.</label>
        <button type="submit" disabled={tokenBusy||!tokenConsent||!dhanToken.trim()}>{tokenBusy?'Verifying…':'Verify and save token'}</button>
      </form>}
      <p className="tc-muted">This verifies your Dhan session and data entitlement. A valid token alone does not start live market streaming; cockpit candles currently come from prepared historical files.</p>
    </section>
    <section className="tc-panel tc-source-panel" aria-label="Shared market data library status">
      <div className="tc-panel-title"><strong>One shared market-data library · dhan_shared</strong><span>Original downloads are reusable source receipts, not separate datasets</span></div>
      <div className="tc-source-summary"><span>Ready one-minute charts <strong>{catalog?.prepared_equities??0}</strong></span><span>Existing minute sources awaiting chart preparation <strong>{pendingMinutes}</strong></span><span>BANKNIFTY spot index <strong>{missingBankNifty?'Original index not yet available':'Source available'}</strong></span></div>
      {sourceError&&<p className="tc-error" role="alert">{sourceError}</p>}
      {sourceNotice&&<p className="tc-confirm" role="status">{sourceNotice}</p>}
      {sourceJob&&sourceWorking&&<p className="tc-muted" role="status">{sourceJob.stage||'Preparing market data'} {sourceJob.percent!==undefined?'· '+Math.round(sourceJob.percent)+'%':''}</p>}
      {pendingMinutes>0&&<div className="tc-source-action"><p>Existing Dhan one-minute stock candles have been downloaded, but their analytical chart index has not been built. Reuse those files without downloading anything again.</p><button type="button" disabled={sourceWorking} onClick={()=>void prepareCached()}>Prepare {Math.min(40,pendingMinutes)} cached minute instruments</button></div>}
      {missingBankNifty&&<form className="tc-source-action" onSubmit={event=>void acquireSpot(event)}>
        <div><strong>For BANKNIFTY signals, the actual index series is missing.</strong>
        <p>The 14 constituent stocks are saved, but their prices are not interchangeable with the index. Fetch the original Dhan IDX_I index spot candles into the same shared library.</p></div>
        <label>From (IST) <input type="date" required value={spotFrom} onChange={e=>setSpotFrom(e.target.value)}/></label>
        <label>Through (exclusive) <input type="date" required value={spotTo} onChange={e=>setSpotTo(e.target.value)}/></label>
        <button type="submit" disabled={sourceWorking}>Get missing BANKNIFTY spot candles</button>
      </form>}
      {!pendingMinutes&&!missingBankNifty&&<p className="tc-confirm">Existing local sources are prepared. These are historical observations, not a live broker stream.</p>}
      <p className="tc-muted">All sources remain internally partitioned by instrument, interval and observation time for accuracy; you manage one library. Missing source dates are never invented or backfilled from today's membership.</p>
    </section>
    <div className="tc-toolbar"><label>Prepared chart source <select aria-label="Trading cockpit instrument" value={identity} onChange={event=>setIdentity(event.target.value)}><option value="">Choose a ready observed source</option>{preparedInstruments.map(s=><option key={s.identity} value={s.identity}>{s.display_name||s.identity} ({s.identity})</option>)}</select></label><label className="tc-monitor-toggle"><input type="checkbox" checked={monitor} onChange={event=>{
  const enabled=event.target.checked;setMonitor(enabled);monitorRef.current=enabled
  if(enabled)void refresh()
}}/> Auto-audit while this page is open</label><button onClick={()=>void refresh()} disabled={!identity}><RefreshCw size={16}/> Refresh</button><button onClick={()=>setPaused(v=>!v)}>{paused?'Resume observations':'Pause updates'}</button><span className="tc-muted"><ShieldCheck size={14}/> No broker execution</span></div>
    {!preparedInstruments.length&&<p className="tc-missing"><Database size={17}/> The library has no ready one-minute chart source yet. Use the actions above to prepare already-downloaded stocks or fetch the actual BANKNIFTY spot series. The existing daily market library remains intact.</p>}
    <div className="tc-layout">
      <section className="tc-panel tc-main">
        <div className="tc-panel-title"><strong>Price action</strong><span>1-minute original OHLC · EMA 9 / EMA 21</span></div>
        {snapshot?<><div className="tc-price">{fmt(snapshot.latest_close)} <small>at {new Date(snapshot.last_observed_utc).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'})} IST</small></div><CandleChart rows={snapshot.rows}/><div className="tc-metrics"><div>EMA 9 <strong>{fmt(snapshot.ema9)}</strong></div><div>EMA 21 <strong>{fmt(snapshot.ema21)}</strong></div><div>RSI 14 <strong>{fmt(snapshot.rsi14)}</strong></div><div>ATR 14 <strong>{fmt(snapshot.atr14)}</strong></div></div></>:<p className="tc-missing">Select an instrument with verified local one-minute candles.</p>}
      </section>
      <section className="tc-panel tc-signal">
        <div className="tc-panel-title"><strong>Next {horizon} minutes</strong><span>Rule baseline v1</span></div>
        <div className="tc-horizon"><button className={horizon===3?'active':''} onClick={()=>setHorizon(3)}>3 MIN</button><button className={horizon===6?'active':''} onClick={()=>setHorizon(6)}>6 MIN</button></div>
        <div className={'tc-direction '+forecast.toLowerCase()}>{forecast==='UP'?'UPWARD BIAS':forecast==='DOWN'?'DOWNWARD BIAS':'NO TRADE'}</div>
        <p className="tc-muted">Unvalidated technical rule. Not a measured win probability or options recommendation.</p>
        <div className="tc-audit-info"><div>Source age <strong>{snapshot?fmt(snapshot.source_age_seconds,0)+' sec':'—'}</strong></div><div>Confidence <strong>Not calibrated</strong></div><div>Option price <strong>Not connected</strong></div><div>Model status <strong>Research only</strong></div></div>
        <button className="tc-primary" disabled={!snapshot||busy||!sourceRecent} onClick={()=>void action('record')}>Record prospective prediction</button>
        {!sourceRecent&&<p className="tc-warning">Prediction recording is disabled for historical or stale candles. This prevents retroactively claiming a past observation as a live prediction.</p>}
      </section>
      <section className="tc-panel tc-timer">
        <div className="tc-panel-title"><strong>Six-minute trade discipline</strong><Clock3 size={16}/></div>
        <div className={'tc-clock '+(elapsed>=360?'tc-overdue':'')}>{countdown}</div>
        <p className="tc-muted">Local manual reminder. No order placement, automatic stop or guaranteed exit.</p>
        <div className="tc-actions"><button onClick={()=>setStartTime(Date.now())}>Start on fill</button><button onClick={()=>setStartTime(null)}>Reset</button></div>
        {startTime!==null&&<p className={elapsed>=360?'tc-warning':'tc-muted'}>{elapsed>=360?'Planned holding period exceeded — reassess or exit manually.':elapsed>=300?'Final minute — check exit plan.':'Timer running from your manual start.'}</p>}
      </section>
    </div>
    <section className="tc-panel tc-ledger"><div className="tc-panel-title"><strong>Permanent prediction ledger</strong><button onClick={()=>void action('evaluate')} disabled={!identity||busy}>Evaluate recorded outcomes</button></div>
      <div className="tc-ledger-summary"><span>Scored directions <strong>{summary?.evaluated_directions??0}</strong></span><span>Correct directions <strong>{summary?.correct_directions??0}</strong></span><span>Directional accuracy <strong>{summary?.direction_accuracy===null||summary?.direction_accuracy===undefined?'Not enough observations':(summary.direction_accuracy*100).toFixed(1)+'%'}</strong></span></div>
      {recordMessage&&<p role="status" className="tc-confirm">{recordMessage}</p>}
      <p className="tc-muted">Directional accuracy excludes no-trade decisions, flat moves and unverifiable source gaps. No historical option P&L is inferred from spot candles.</p>
      {monitor&&<p className="tc-confirm">Auto-audit enabled in this browser tab. Every 15 seconds QuantLab records both 3/6-minute calls only from freshly completed original source bars and scores due outcomes. Closing the page stops monitoring. A current local candle alone is not evidence of a streaming broker connection.</p>}
      <div className="tc-report-title"><h3>End-of-day accuracy · prospective ledger only</h3><span className="tc-muted">No option trade P&amp;L or validated alpha</span></div>
      <div className="tc-ledger-summary"><span>Logged decisions <strong>{report?.overall.total??0}</strong></span><span>Direction score <strong>{report?.overall.directional_accuracy===null||report?.overall.directional_accuracy===undefined?'—':(report.overall.directional_accuracy*100).toFixed(1)+'%'}</strong></span><span>Pending <strong>{report?.overall.pending??0}</strong></span><span>Source gaps <strong>{report?.overall.unverifiable??0}</strong></span></div>
      <div className="tc-table-scroll"><table><thead><tr><th>Session IST</th><th>Calls</th><th>Scored</th><th>Correct</th><th>Incorrect</th><th>No trade</th><th>Pending</th><th>Gaps</th><th>Accuracy</th></tr></thead><tbody>{report?.days.map(day=><tr key={day.session_ist}><td>{day.session_ist}</td><td>{day.total}</td><td>{day.scored}</td><td>{day.correct}</td><td>{day.incorrect}</td><td>{day.no_trade}</td><td>{day.pending}</td><td>{day.unverifiable}</td><td>{day.directional_accuracy===null?'—':(day.directional_accuracy*100).toFixed(1)+'%'}</td></tr>)}{!report?.days.length&&<tr><td colSpan={9}>No prospective logged decisions yet.</td></tr>}</tbody></table></div>
      <div className="tc-table-scroll"><table><thead><tr><th>Recorded UTC</th><th>Source bar UTC</th><th>Signal</th><th>Horizon</th><th>Reference</th><th>Observed</th><th>Outcome</th></tr></thead><tbody>{history?.predictions.map(x=><tr key={x.id}><td>{x.created_utc.slice(0,19)}</td><td>{x.bar_utc.slice(0,19)}</td><td>{x.direction}</td><td>{x.horizon_minutes}m</td><td>{fmt(x.reference_close)}</td><td>{fmt(x.observed_close)}</td><td>{x.evaluation.replaceAll('_',' ')}</td></tr>)}{!history?.predictions.length&&<tr><td colSpan={7}>No prospective predictions logged for this instrument yet.</td></tr>}</tbody></table></div>
    </section>
    <section className="tc-panel tc-ledger">
      <div className="tc-panel-title"><strong>Historical BANKNIFTY directional backtest · no option P&amp;L</strong><div className="tc-backtest-controls"><label>History window <select value={replayLimit} onChange={event=>setReplayLimit(event.target.value)}><option value="500">Last 500 minutes</option><option value="1500">Last 1,500 minutes</option><option value="3000">Last 3,000 minutes</option><option value="5000">Last 5,000 minutes</option></select></label><button disabled={!identity||replayBusy} onClick={()=>void runReplay()}>{replayBusy?'Evaluating source history…':'Run directional backtest'}</button></div></div>
      <p className="tc-muted">Runs the fixed untrained rule separately at each historical minute using only information available up to that minute. Checks actual 3/6-minute direction where observed; does not claim executable option fills, costs or out-of-sample trading skill.</p>
      {replay&&<><div className="tc-ledger-summary"><span>Horizon <strong>{replay.horizon_minutes} min</strong></span><span>Source bars <strong>{replay.observed_source_bars}</strong></span><span>Scored signals <strong>{replay.overall.scored}</strong></span><span>Correct <strong>{replay.overall.correct}</strong></span><span>Baseline accuracy <strong>{replay.overall.directional_accuracy===null?'—':(replay.overall.directional_accuracy*100).toFixed(1)+'%'}</strong></span><span>Gaps <strong>{replay.overall.unverifiable}</strong></span></div>
      <div className="tc-table-scroll"><table><thead><tr><th>IST session</th><th>Scored</th><th>Correct</th><th>Incorrect</th><th>No trade</th><th>Gaps</th><th>Directional accuracy</th></tr></thead><tbody>{replay.days.map(d=><tr key={d.session_ist}><td>{d.session_ist}</td><td>{d.scored}</td><td>{d.correct}</td><td>{d.incorrect}</td><td>{d.no_trade}</td><td>{d.unverifiable}</td><td>{d.directional_accuracy===null?'—':(d.directional_accuracy*100).toFixed(1)+'%'}</td></tr>)}</tbody></table></div>
      <p className="tc-warning">{replay.disclaimer}{replay.has_more_history?' Additional older source data was not evaluated.':''}</p></>}
    </section>
    <section className="tc-panel tc-ledger" aria-label="Manual options trade journal">
      <div className="tc-panel-title"><strong>Manual options journal · six-minute discipline</strong><span>Read-only research · you type actual prices</span></div>
      <p className="tc-muted">Enter a new trade at the time you actually fill it. QuantLab stores server receipt times and computes P&amp;L only after you report an exit. The app cannot verify your broker fills, enforce a stop, or place orders.</p>
      <p className="tc-confirm">Signal input: BANKNIFTY spot candles only. You choose the exact CE/PE contract, expiry, strike and actual filled premium in your broker. The signal does not forecast the option premium.</p>
      <form className="tc-trade-form" onSubmit={event=>void recordEntry(event)}>
        <label>Exact contract symbol<input required maxLength={48} value={optionSymbol} placeholder="BANKNIFTY23NOV61900PE" onChange={event=>setOptionSymbol(event.target.value.toUpperCase())}/></label>
        <label>Type<select value={optionSide} onChange={event=>setOptionSide(event.target.value as 'CALL'|'PUT')}><option value="PUT">Long put</option><option value="CALL">Long call</option></select></label>
        <label>Quantity<input aria-label="Trade quantity" required type="number" min="1" max="1000000" step="1" value={optionQty} onChange={event=>setOptionQty(event.target.value)}/></label>
        <label>Entry premium (₹)<input aria-label="Trade entry premium" required type="number" min="0.01" step="0.01" value={optionEntry} onChange={event=>setOptionEntry(event.target.value)}/></label>
        <label>Note (optional)<input maxLength={250} value={tradeNote} onChange={event=>setTradeNote(event.target.value)}/></label>
        <button className="tc-primary" disabled={journalBusy} type="submit">Record manual entry + start six-minute timer</button>
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
    </section>
  </div>
}
