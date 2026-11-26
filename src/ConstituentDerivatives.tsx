import {useEffect,useState} from 'react'
import ResearchPlot from './ResearchPlots'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'

type Contract={identity:string;underlying:string;instrument:'FUTSTK'|'OPTSTK';expiry:string;strike:number|null;option_type:'CE'|'PE'|null;lot_size:number}
type Status={enabled:boolean;connected:boolean;state:string;requested:Contract[];option_ids:string[];saved:number;dropped:number;stale:number;note:string;storage:{last_error:string|null}}
type Catalog={membership:{symbols:string[]};nearest_futures:Contract[];unresolved_futures:string[];options:Contract[];option_count:number;has_more:boolean;offset:number;selected_option_ids:string[];note:string}
type Row=Contract&{quote:{price:number;volume:number;received_utc:string}|null;oi:{open_interest:number;received_utc:string}|null;return_pct:number|null;volume_delta:number|null;oi_delta:number|null}
type Analysis={rows:Row[];horizon_minutes:number;as_of_utc:string;note:string}
const API='/api/trading-cockpit/constituents/derivatives/'
const fmt=(v:number|null|undefined)=>v==null?'—':v.toLocaleString('en-IN',{maximumFractionDigits:3})
const stamp=(v:string|null|undefined)=>v?new Date(v).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hourCycle:'h23'}):'—'
const label=(c:Contract)=>c.underlying+' '+c.expiry+(c.instrument==='OPTSTK'?' '+c.strike+' '+c.option_type:' FUT')
export default function ConstituentDerivatives(){
 const [status,setStatus]=useState<Status|null>(null)
 const [catalog,setCatalog]=useState<Catalog|null>(null)
 const [analysis,setAnalysis]=useState<Analysis|null>(null)
 const [symbol,setSymbol]=useState('')
 const [selected,setSelected]=useState<string[]>([])
 const [horizon,setHorizon]=useState(5)
 const [historical,setHistorical]=useState('')
 const [reviewed,setReviewed]=useState(false)
 const [busy,setBusy]=useState(false)
 const [error,setError]=useState('')
 const refresh=async()=>{
  setBusy(true);setError('')
  try{
   const r=await marketApi<Status>(API+'status')
   setStatus(r);setSelected(r.option_ids)
  }catch(e){setError(readableError(e))}finally{setBusy(false)}
 }
 useEffect(()=>{let active=true;void marketApi<Status>(API+'status').then(r=>{if(active){setStatus(r);setSelected(r.option_ids)}}).catch(e=>{if(active)setError(readableError(e))});return()=>{active=false}},[])
 const inspect=async(next=symbol,offset=0)=>{
  setBusy(true);setError('')
  try{setCatalog(await marketApi<Catalog>(API+'catalog?'+new URLSearchParams({symbol:next,offset:String(offset),limit:'50'})))}
  catch(e){setError(readableError(e));setCatalog(null)}finally{setBusy(false)}
 }
 const configure=async(enable:boolean)=>{
  setBusy(true);setError('')
  try{const r=await marketPost<Status>(API+'configure',{enabled:enable,option_ids:selected,confirm_shared_feed:reviewed});setStatus(r);setSelected(r.option_ids);setReviewed(false)}
  catch(e){setError(readableError(e))}finally{setBusy(false)}
 }
 const run=async()=>{
  setBusy(true);setError('');setAnalysis(null)
  try{const p=new URLSearchParams({horizon:String(horizon)});if(historical)p.set('as_of',historical+':00+05:30');setAnalysis(await marketApi<Analysis>(API+'analysis?'+p));setStatus(await marketApi<Status>(API+'status'))}
  catch(e){setError(readableError(e))}finally{setBusy(false)}
 }
 const futures=analysis?.rows.filter(r=>r.instrument==='FUTSTK'&&r.return_pct!==null)||[]
 const options=analysis?.rows.filter(r=>r.instrument==='OPTSTK'&&r.return_pct!==null)||[]
 return <section className="bci-panel" aria-label="Constituent futures and stock options">
 <header><div><h3>Constituent derivatives</h3><p>Optional original NSE_FNO futures and selected stock-option receipts. Uses exact dated cash-equity mappings and explicit master underlying fields; no symbol guesses, new socket or displacement of BANKNIFTY options. Nearest unique futures are selected automatically.</p></div><button className="ws-button" disabled={busy} onClick={()=>void refresh()}>Refresh derivative status</button></header>
 <div className="bci-grid"><div className="bci-stat"><span>Capture state</span><strong>{status?.state.replaceAll('_',' ')||'Unavailable'}</strong><small>{status?.enabled?'Consent enabled':'Consent disabled'}</small></div><div className="bci-stat"><span>Subscribed identities</span><strong>{status?.requested.length??'—'}</strong><small>Last shared socket subscription</small></div><div className="bci-stat"><span>Saved / dropped</span><strong>{status?status.saved+' / '+status.dropped:'—'}</strong><small>Process counters, not complete trade tape</small></div></div>
 {error&&<p className="bci-error" role="alert">{error}</p>}{status?.storage.last_error&&<p className="bci-warning">Storage: {status.storage.last_error}</p>}
 <details><summary>Choose exact stock derivatives and configure collection</summary>
  <div className="bci-actions"><button className="ws-button" disabled={busy} onClick={()=>void inspect()}>Inspect exact local derivative master</button>{catalog&&<label>Stock-option underlying<select aria-label="Stock derivative underlying" value={symbol} disabled={busy} onChange={e=>{setSymbol(e.target.value);void inspect(e.target.value)}}><option value="">All dated members</option>{catalog.membership.symbols.map(s=><option key={s} value={s}>{s}</option>)}</select></label>}</div>
  {catalog&&<><p className="bci-note">{catalog.nearest_futures.length} unique nearest futures · {catalog.unresolved_futures.length} missing or ambiguous. {catalog.unresolved_futures.join(', ')}. {catalog.option_count} exact stock options for this filter.</p><div className="bci-scroll"><table aria-label="Exact constituent futures"><thead><tr><th>Future</th><th>Identity</th><th>Lot size</th></tr></thead><tbody>{catalog.nearest_futures.map(c=><tr key={c.identity}><td>{label(c)}</td><td>{c.identity}</td><td>{c.lot_size}</td></tr>)}</tbody></table></div>
   <div className="bci-scroll"><table aria-label="Exact stock option choices"><thead><tr><th>Record</th><th>Contract</th><th>Identity</th><th>Lot size</th></tr></thead><tbody>{catalog.options.map(c=><tr key={c.identity}><td><input type="checkbox" aria-label={'Select '+label(c)} checked={selected.includes(c.identity)} disabled={busy||(!selected.includes(c.identity)&&selected.length>=50)} onChange={e=>{setSelected(v=>e.target.checked?[...v,c.identity]:v.filter(x=>x!==c.identity));setReviewed(false)}}/></td><td>{label(c)}</td><td>{c.identity}</td><td>{c.lot_size}</td></tr>)}</tbody></table></div>
   <div className="bci-actions"><button className="ws-button" disabled={busy||catalog.offset===0} onClick={()=>void inspect(symbol,Math.max(0,catalog.offset-50))}>Previous contracts</button><button className="ws-button" disabled={busy||!catalog.has_more} onClick={()=>void inspect(symbol,catalog.offset+50)}>Next contracts</button><button className="ws-button" disabled={busy||!selected.length} onClick={()=>{setSelected([]);setReviewed(false)}}>Clear stock-option selection</button><span>{selected.length}/50 selected across pages</span></div>
   <p className="bci-note">{catalog.note}</p></>}
  <label className="bci-check"><input type="checkbox" checked={reviewed} disabled={busy} onChange={e=>setReviewed(e.target.checked)}/> I authorize these optional read-only original derivative subscriptions on spare shared feed capacity.</label>
  <div className="bci-actions"><button className="ws-button primary" disabled={busy||!reviewed||!catalog} onClick={()=>void configure(true)}>{status?.enabled?'Save derivative capture choices':'Enable derivative capture'}</button><button className="ws-button" disabled={busy||!status?.enabled} onClick={()=>void configure(false)}>Disable derivative capture</button></div>
  <p className="bci-note">Changes take effect at the next natural connection; the existing recording socket is never forcibly restarted.</p>
 </details>
 <div className="bci-actions"><label>Lookback<select aria-label="Derivative lookback" value={horizon} disabled={busy} onChange={e=>{setHorizon(Number(e.target.value));setAnalysis(null)}}>{[1,5,10,30,60].map(n=><option key={n} value={n}>{n} min</option>)}</select></label><label>Historical end (IST, blank = now)<input type="datetime-local" value={historical} disabled={busy} onChange={e=>{setHistorical(e.target.value);setAnalysis(null)}}/></label><button className="ws-button" disabled={busy} onClick={()=>void run()}>Inspect stored derivative movement</button></div>
 {analysis&&<><p className="bci-note">Observed cutoff {stamp(analysis.as_of_utc)} IST · {analysis.horizon_minutes} min. {analysis.note}</p>
  <div className="bci-scroll"><table aria-label="Stored derivative movement"><thead><tr><th>Contract</th><th>Price</th><th>Return %</th><th>Volume change</th><th>Reported OI</th><th>OI change</th><th>Quote receipt (IST)</th><th>OI receipt (IST)</th></tr></thead><tbody>{analysis.rows.map(r=><tr key={r.identity}><td>{label(r)}</td><td>{fmt(r.quote?.price)}</td><td>{fmt(r.return_pct)}</td><td>{fmt(r.volume_delta)}</td><td>{fmt(r.oi?.open_interest)}</td><td>{fmt(r.oi_delta)}</td><td>{stamp(r.quote?.received_utc)}</td><td>{stamp(r.oi?.received_utc)}</td></tr>)}{!analysis.rows.length&&<tr><td colSpan={8}>No saved derivative receipts for this cutoff.</td></tr>}</tbody></table></div>
  {futures.length>0&&<ResearchPlot provenance="Original sampled constituent futures" plot={{kind:'bar2d',title:'Observed nearest futures movement',x_label:'Recorded contract',y_label:'Return (%)',x:futures.map(label),traces:[{name:'Futures return',y:futures.map(r=>r.return_pct)}]}}/>}
  {options.length>0&&<ResearchPlot provenance="Original sampled selected stock options" plot={{kind:'bar2d',title:'Observed selected stock option movement',x_label:'Recorded contract',y_label:'Premium return (%)',x:options.map(label),traces:[{name:'Premium return',y:options.map(r=>r.return_pct)}]}}/>}
 </>}
 </section>
}
