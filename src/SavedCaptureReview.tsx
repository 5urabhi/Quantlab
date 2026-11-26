import {useCallback,useEffect,useState} from 'react'
import {Archive,RefreshCw} from 'lucide-react'
import {marketApi,readableError} from './tradingCockpitApi'
import ResearchPlot from './ResearchPlots'
import './constituent-intelligence.css'

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
  ask:{price:number;quantity:number;orders:number}[];
  collection_mode?:string
  computed_features?:{
    side:'CE'|'PE';strike:number;expiry:string
    lots:number;units:number;lot_size_verified:number
    buy_vwap_for_units:number|null;sell_vwap_for_units:number|null
    bid_quantity_20:number;ask_quantity_20:number
    chain_received_utc:string;clock_basis:string
  }|null
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
const read = marketApi

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
      const indexSources=next.minute_sources.filter(x=>x.identity.startsWith('INDEX:'))
      setIdentity(current=>indexSources.some(x=>x.identity===current)?current:
        indexSources[0]?.identity||'INDEX:BANKNIFTY')
      setDepthIdentity(current=>next.depth_sources.some(x=>x.identity===current)?current:
        next.depth_sources[0]?.identity||'')
    }catch(e){setError(readableError(e))}
  },[])
  useEffect(()=>{void refresh()},[refresh])
  const replayMinutes=async()=>{
    setBusy(true);setError('')
    try{
      const result=await read<Replay>('/api/trading-cockpit/live/replay?'+
        new URLSearchParams({identity,horizon_minutes:horizon,limit:'5000'}))
      setReplay(result)
    }catch(e){setError(readableError(e))}
    finally{setBusy(false)}
  }
  const inspectBooks=async()=>{
    if(!depthIdentity)return
    setBusy(true);setError('')
    try{
      const result=await read<SavedBooks>('/api/trading-cockpit/live/depth-history?'+
        new URLSearchParams({identity:depthIdentity,limit:'150'}))
      setBooks(result);setSelectedBook(null)
    }catch(e){setError(readableError(e))}
    finally{setBusy(false)}
  }
  const chosenBook=selectedBook===null?null:books?.snapshots[selectedBook]
  const orderedBooks=[...(books?.snapshots||[])].sort((a,b)=>a.received_utc.localeCompare(b.received_utc))
  const bookX=orderedBooks.map(b=>b.received_utc)
  const gap=bookX.map((t,i)=>i>0&&Date.parse(t)-Date.parse(bookX[i-1])>120000)
  const orderedReplay=[...(replay?.days||[])].sort((a,b)=>a.session_ist.localeCompare(b.session_ist))
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
        {catalog?.minute_sources.some(x=>x.identity.startsWith('INDEX:'))?<><label>Recorded index source
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
    {orderedReplay.length>0&&<div className="bci-panel" aria-label="Captured directional replay charts">
      <ResearchPlot provenance="Retrospective replay of captured index minutes" plot={{kind:'bar2d',title:'Captured replay scored and unverifiable outcomes',x_label:'Session (IST)',y_label:'Signal count',x:orderedReplay.map(d=>d.session_ist),traces:[{name:'Correct',y:orderedReplay.map(d=>d.correct),color:'#70e1ad'},{name:'Incorrect',y:orderedReplay.map(d=>d.incorrect),color:'#ff8192'},{name:'Unverifiable',y:orderedReplay.map(d=>d.unverifiable)}]}}/>
      <ResearchPlot provenance="Retrospective replay of captured index minutes" plot={{kind:'line2d',title:'Captured directional accuracy by session',x_label:'Session (IST)',y_label:'Directional accuracy (%)',x:orderedReplay.map(d=>d.session_ist),traces:[{name:'Accuracy',y:orderedReplay.map(d=>d.directional_accuracy===null?null:100*d.directional_accuracy)}]}}/>
      <p className="tc-muted">Retrospective directional outcomes are not realized option P&amp;L.</p>
    </div>}
    {replay&&<div className="tc-table-scroll"><table>
      <thead><tr><th>IST session</th><th>Scored</th><th>Correct</th><th>Incorrect</th><th>Gaps</th><th>Directional accuracy</th></tr></thead>
      <tbody>{replay.days.map(d=><tr key={d.session_ist}><td>{d.session_ist}</td><td>{d.scored}</td>
        <td>{d.correct}</td><td>{d.incorrect}</td><td>{d.unverifiable}</td>
        <td>{d.directional_accuracy===null?'—':fmt(d.directional_accuracy*100,1)+'%'}</td></tr>)}</tbody>
    </table></div>}
    {books?.snapshots.some(b=>b.collection_mode==='auto_banknifty_20_level')&&
      <p className="tc-confirm">
        Automatic BANKNIFTY CE/PE books are included below. Derived 3-lot
        liquidity prices use the contract's master-verified lot size and
        original 20-level quantities, not confirmed broker fills.
      </p>}
    {orderedBooks.length>0&&<div className="bci-panel" aria-label="Recorded book charts">
      <ResearchPlot provenance="Original recorded depth snapshots" plot={{kind:'line2d',title:'Recorded best bid and ask',x_label:'Source receipt time (UTC)',y_label:'Price (INR)',x:bookX,traces:[{name:'Best bid',y:orderedBooks.map(b=>b.best_bid),color:'#70e1ad'},{name:'Best ask',y:orderedBooks.map(b=>b.best_ask),color:'#ff8192'}],break_before:gap}}/>
      <ResearchPlot provenance="Original recorded depth snapshots" plot={{kind:'line2d',title:'Recorded bid–ask spread',x_label:'Source receipt time (UTC)',y_label:'Spread (bps)',x:bookX,traces:[{name:'Spread',y:orderedBooks.map(b=>b.spread_bps)}],break_before:gap}}/>
      <ResearchPlot provenance="Original recorded depth snapshots" plot={{kind:'line2d',title:'Recorded displayed bid depth share',x_label:'Source receipt time (UTC)',y_label:'Bid share of recorded quantity (%)',x:bookX,traces:[{name:'Bid share',y:orderedBooks.map(b=>50*(b.imbalance+1))}],reference_lines:[{value:50,label:'Balanced displayed quantities'}],break_before:gap}}/>
      <p className="tc-muted">Latest returned saved snapshots only. Lines break at receipt gaps greater than two minutes. Displayed quantities are not aggressive trade flow or guaranteed fills.</p>
    </div>}
    {books&&books.snapshots.length>0&&<div className="tc-table-scroll tc-archive-table">
      <table><thead><tr><th>Observed IST</th><th>Bid (₹)</th><th>Ask (₹)</th>
        <th>Spread (bps)</th><th>Bid depth share</th><th>Original levels</th>
        <th>Source / option</th><th>Buy lots VWAP (₹)</th><th>Sell lots VWAP (₹)</th><th></th></tr></thead>
        <tbody>{books.snapshots.map((b,i)=><tr key={b.received_utc+i}>
          <td>{time(b.received_utc)}</td><td>{fmt(b.best_bid)}</td><td>{fmt(b.best_ask)}</td>
          <td>{fmt(b.spread_bps)}</td><td>{fmt(50*(b.imbalance+1),1)}%</td>
          <td>{b.bid_levels} / {b.ask_levels}</td>
          <td>{b.computed_features
            ?b.computed_features.side+' '+fmt(b.computed_features.strike,0)
            :'Manual book'}</td>
          <td>{fmt(b.computed_features?.buy_vwap_for_units)}</td>
          <td>{fmt(b.computed_features?.sell_vwap_for_units)}</td>
          <td><button type="button" onClick={()=>setSelectedBook(selectedBook===i?null:i)}>Levels</button></td>
        </tr>)}</tbody></table></div>}
    {chosenBook&&<details className="tc-archive-levels" open><summary>Snapshot levels · {time(chosenBook.received_utc)}</summary>
      {chosenBook.computed_features&&<p className="tc-muted">
        Original automatic contract: {chosenBook.identity} · {chosenBook.computed_features.side}
        {' '}{fmt(chosenBook.computed_features.strike,0)}
        {' '}· {chosenBook.computed_features.lots} lots × verified
        {' '}{chosenBook.computed_features.lot_size_verified} =
        {' '}{chosenBook.computed_features.units} units.
        Indicated buy VWAP ₹{fmt(chosenBook.computed_features.buy_vwap_for_units)},
        sell VWAP ₹{fmt(chosenBook.computed_features.sell_vwap_for_units)}.
        Only levels present in Dhan's received packet are included.
      </p>}
      <div className="bci-panel"><ResearchPlot provenance="Selected original recorded book" plot={{kind:'bar2d',title:'Selected snapshot displayed quantity by level',x_label:'Depth level (best to farther)',y_label:'Displayed quantity',x:Array.from({length:Math.max(chosenBook.bid.length,chosenBook.ask.length)},(_,i)=>i+1),traces:[{name:'Bid quantity',color:'#70e1ad',y:Array.from({length:Math.max(chosenBook.bid.length,chosenBook.ask.length)},(_,i)=>chosenBook.bid[i]?.quantity??null)},{name:'Ask quantity',color:'#ff8192',y:Array.from({length:Math.max(chosenBook.bid.length,chosenBook.ask.length)},(_,i)=>chosenBook.ask[i]?.quantity??null)}]}}/></div>
      <div className="tc-table-scroll"><table><thead><tr><th>Level</th><th>Bid (₹)</th><th>Bid qty</th><th>Ask (₹)</th><th>Ask qty</th></tr></thead>
      <tbody>{Array.from({length:Math.max(chosenBook.bid.length,chosenBook.ask.length)},(_,i)=><tr key={i}>
        <td>{i+1}</td><td>{fmt(chosenBook.bid[i]?.price)}</td><td>{fmt(chosenBook.bid[i]?.quantity,0)}</td>
        <td>{fmt(chosenBook.ask[i]?.price)}</td><td>{fmt(chosenBook.ask[i]?.quantity,0)}</td>
      </tr>)}</tbody></table></div></details>}
    <p className="tc-muted">A historical directional replay is not an executable option backtest. Depth recordings only cover periods you actually captured. No historical depth, missed ticks or broker fills are invented.</p>
  </section>
}
