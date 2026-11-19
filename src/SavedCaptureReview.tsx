import {useCallback,useEffect,useState} from 'react'
import {Archive,RefreshCw} from 'lucide-react'

type Source={identity:string;observations:number;first_utc:string;last_utc:string}
type CaptureCatalog={
  shared_library:string;minute_sources:Source[];depth_sources:Source[];
  source:string;warning:string
}
type Summary={scored:number;correct:number;incorrect:number;unverifiable:number;
  no_trade:number;directional_accuracy:number|null}
type Replay={
  identity:string;horizon_minutes:number;observed_source_bars:number;
  overall:Summary;source_warning:string;disclaimer:string;
  days:{session_ist:string;scored:number;correct:number;incorrect:number;
    unverifiable:number;directional_accuracy:number|null}[];
}
type Book={
  identity:string;received_utc:string;best_bid:number;best_ask:number;
  spread_bps:number;imbalance:number;full_depth:boolean;bid_levels:number;
  ask_levels:number;bid:{price:number;quantity:number;orders:number}[];
  ask:{price:number;quantity:number;orders:number}[]
}
type SavedBooks={
  identity:string;sampling:string;snapshots:Book[];historical_download_supported:boolean
}
const fmt=(value:number|null|undefined,decimals=2)=>
  value===null||value===undefined?'—':value.toLocaleString('en-IN',{maximumFractionDigits:decimals})
const time=(value:string)=>new Date(value).toLocaleString('en-IN',{
  timeZone:'Asia/Kolkata',year:'numeric',month:'short',day:'numeric',
  hour:'2-digit',minute:'2-digit',hourCycle:'h23',
})
async function read<T>(url:string):Promise<T>{
  const response=await fetch(url)
  if(!response.ok){
    let detail='Recorded-data request failed'
    try{const body=await response.json() as {detail?:string};detail=body.detail||detail}
    catch{/* no body */}
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export default function SavedCaptureReview(){
  const [catalog,setCatalog]=useState<CaptureCatalog|null>(null)
  const [identity,setIdentity]=useState('INDEX:BANKNIFTY')
  const [depthIdentity,setDepthIdentity]=useState('')
  const [horizon,setHorizon]=useState<'3'|'6'>('6')
  const [replay,setReplay]=useState<Replay|null>(null)
  const [books,setBooks]=useState<SavedBooks|null>(null)
  const [selectedBook,setSelectedBook]=useState<number|null>(null)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const refresh=useCallback(async()=>{
    try{
      const next=await read<CaptureCatalog>('/api/trading-cockpit/live/capture-catalog')
      setCatalog(next)
      setIdentity(current=>next.minute_sources.some(x=>x.identity===current)?current:
        next.minute_sources[0]?.identity||'INDEX:BANKNIFTY')
      setDepthIdentity(current=>next.depth_sources.some(x=>x.identity===current)?current:
        next.depth_sources[0]?.identity||'')
    }catch(e){setError(e instanceof Error?e.message:String(e))}
  },[])
  useEffect(()=>{void refresh()},[refresh])
  const replayMinutes=async()=>{
    setBusy(true);setError('')
    try{
      const result=await read<Replay>('/api/trading-cockpit/live/replay?'+
        new URLSearchParams({identity,horizon_minutes:horizon,limit:'5000'}))
      setReplay(result)
    }catch(e){setError(e instanceof Error?e.message:String(e))}
    finally{setBusy(false)}
  }
  const inspectBooks=async()=>{
    if(!depthIdentity)return
    setBusy(true);setError('')
    try{
      const result=await read<SavedBooks>('/api/trading-cockpit/live/depth-history?'+
        new URLSearchParams({identity:depthIdentity,limit:'150'}))
      setBooks(result);setSelectedBook(null)
    }catch(e){setError(e instanceof Error?e.message:String(e))}
    finally{setBusy(false)}
  }
  const chosenBook=selectedBook===null?null:books?.snapshots[selectedBook]
  return <section className="tc-panel tc-archive" aria-label="Captured live history">
    <div className="tc-panel-title"><div><strong><Archive size={17}/> Saved live-data recordings</strong>
      <p className="tc-muted">Live observations become historical evidence in dhan_shared. Original minute prices and recorded 20-level order books are separate, source-labelled series.</p></div>
      <button type="button" onClick={()=>void refresh()}><RefreshCw size={15}/> Rescan saved observations</button>
    </div>
    {error&&<p className="tc-error" role="alert">{error}</p>}
    <div className="tc-archive-grid">
      <div className="tc-archive-card">
        <strong>Previously captured index minute bars</strong>
        <span className="tc-muted">3/6-minute directional replay · never infers option fills</span>
        {catalog?.minute_sources.length?<><label>Recorded index source
          <select aria-label="Recorded index source" value={identity} onChange={e=>{setIdentity(e.target.value);setReplay(null)}}>
            {catalog.minute_sources.filter(x=>x.identity.startsWith('INDEX:')).map(x=>
              <option key={x.identity} value={x.identity}>{x.identity.replace('INDEX:','')} · {x.observations} bars</option>)}
          </select>
        </label><label>Forecast horizon
          <select value={horizon} onChange={e=>setHorizon(e.target.value as '3'|'6')}>
            <option value="3">3 minutes</option><option value="6">6 minutes</option>
          </select></label>
          <button type="button" disabled={busy} onClick={()=>void replayMinutes()}>Replay captured minute bars</button>
        </>:<p className="tc-muted">No saved live index minutes yet. Historical Dhan candle research above still works without recording a stream.</p>}
        {replay&&<div className="tc-archive-stats">
          <span>Observed bars <b>{fmt(replay.observed_source_bars,0)}</b></span>
          <span>Scored calls <b>{fmt(replay.overall.scored,0)}</b></span>
          <span>Directional accuracy <b>{replay.overall.directional_accuracy===null?'Insufficient':fmt(replay.overall.directional_accuracy*100,1)+'%'}</b></span>
          <span>Unverifiable <b>{fmt(replay.overall.unverifiable,0)}</b></span>
        </div>}
      </div>
      <div className="tc-archive-card">
        <strong>Recorded 20-level order books</strong>
        <span className="tc-muted">Actual bid / ask snapshots · only from your previous live captures</span>
        {catalog?.depth_sources.length?<><label>Saved stock or option
          <select aria-label="Saved depth instrument" value={depthIdentity}
            onChange={e=>{setDepthIdentity(e.target.value);setBooks(null)}}>
            {catalog.depth_sources.map(x=>
              <option key={x.identity} value={x.identity}>{x.identity} · {x.observations} snapshots</option>)}
          </select>
        </label>
          <button type="button" disabled={busy} onClick={()=>void inspectBooks()}>Inspect recorded depth</button>
        </>:<p className="tc-muted">No archived depth yet. Historical OHLC alone cannot recreate a 20-level order book.</p>}
        {books&&<p className="tc-confirm">{books.snapshots.length} original snapshots in the selected recorded window.</p>}
      </div>
    </div>
    {replay&&<div className="tc-table-scroll"><table>
      <thead><tr><th>IST session</th><th>Scored</th><th>Correct</th><th>Incorrect</th><th>Gaps</th><th>Directional accuracy</th></tr></thead>
      <tbody>{replay.days.map(d=><tr key={d.session_ist}><td>{d.session_ist}</td><td>{d.scored}</td>
        <td>{d.correct}</td><td>{d.incorrect}</td><td>{d.unverifiable}</td>
        <td>{d.directional_accuracy===null?'—':fmt(d.directional_accuracy*100,1)+'%'}</td></tr>)}</tbody>
    </table></div>}
    {books&&books.snapshots.length>0&&<div className="tc-table-scroll tc-archive-table">
      <table><thead><tr><th>Observed IST</th><th>Bid (₹)</th><th>Ask (₹)</th>
        <th>Spread (bps)</th><th>Bid depth share</th><th>Original levels</th><th></th></tr></thead>
        <tbody>{books.snapshots.map((b,i)=><tr key={b.received_utc+i}>
          <td>{time(b.received_utc)}</td><td>{fmt(b.best_bid)}</td><td>{fmt(b.best_ask)}</td>
          <td>{fmt(b.spread_bps)}</td><td>{fmt(50*(b.imbalance+1),1)}%</td>
          <td>{b.bid_levels} / {b.ask_levels}</td>
          <td><button type="button" onClick={()=>setSelectedBook(selectedBook===i?null:i)}>Levels</button></td>
        </tr>)}</tbody></table></div>}
    {chosenBook&&<details className="tc-archive-levels" open><summary>Snapshot levels · {time(chosenBook.received_utc)}</summary>
      <div className="tc-table-scroll"><table><thead><tr><th>Level</th><th>Bid (₹)</th><th>Bid qty</th><th>Ask (₹)</th><th>Ask qty</th></tr></thead>
      <tbody>{Array.from({length:Math.max(chosenBook.bid.length,chosenBook.ask.length)},(_,i)=><tr key={i}>
        <td>{i+1}</td><td>{fmt(chosenBook.bid[i]?.price)}</td><td>{fmt(chosenBook.bid[i]?.quantity,0)}</td>
        <td>{fmt(chosenBook.ask[i]?.price)}</td><td>{fmt(chosenBook.ask[i]?.quantity,0)}</td>
      </tr>)}</tbody></table></div></details>}
    <p className="tc-muted">A historical directional replay is not an executable option backtest. Depth recordings only cover periods you actually captured. No historical depth, missed ticks or broker fills are invented.</p>
  </section>
}
