import {useEffect,useMemo,useState} from 'react'
import ResearchPlot from './ResearchPlots'
import ConstituentProspective from './ConstituentProspective'
import ArchivedWeights from './ArchivedWeights'
import ConstituentDerivatives from './ConstituentDerivatives'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
import './constituent-intelligence.css'

type Capture={enabled:boolean;connected:boolean;state:string;requested:Record<string,string>;saved:number;dropped:number;ignored_stale:number;sample_seconds:number;last_saved_utc:string|null;note:string;storage:{state:string;last_error:string|null}}
type Quote={identity:string;price:number;received_utc:string;exchange_trade_utc:string;volume:number;atp:number|null;buy_quantity:number;sell_quantity:number}
type Row={symbol:string;weight_pct:number|null;current:Quote|null;anchor:Quote|null;return_pct:number|null;volume_delta:number|null;relative_volume:number|null;baseline_sessions:number;atp_deviation_pct:number|null;displayed_quantity_imbalance:number|null;contribution_pp:number|null;approx_index_points:number|null}
type Analysis={as_of_utc:string;anchor_utc:string;session_ist:string;horizon_minutes:number;weight_snapshot:{snapshot_date:string;source:string;source_csv_sha256:string;recorded_utc:string;reported_weight_sum_pct:number}|null;membership:{date:string;symbols:string[];covered_through?:string;source_sha256?:string};rows:Row[];expected_members:number;observed_members:number;observed_weight_pct:number|null;complete_weighted_coverage:boolean;weighted_return_pct:number|null;weighted_breadth_pct:number|null;partial_contribution_pp:number|null;spot_anchor:number|null;blockers:string[];note:string}
const API='/api/trading-cockpit/constituents/'
const fmt=(v:number|null|undefined,digits=2)=>v===null||v===undefined?'—':v.toLocaleString('en-IN',{maximumFractionDigits:digits})
const time=(v:string|null|undefined)=>v?new Date(v).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hourCycle:'h23',year:'numeric',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'}):'—'
const today=()=>new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Kolkata'})
const color=(v:number|null|undefined)=>v==null?'':v>0?'bci-up':v<0?'bci-down':''
const pct=(v:number|null|undefined)=>v==null?'—':fmt(v)+'%'
type Sort='weight_pct'|'return_pct'|'relative_volume'|'contribution_pp'|'volume_delta'
function Metric({name,value,detail,tone}:{name:string;value:string;detail:string;tone?:string}){
 return <div className="bci-stat"><span>{name}</span><strong className={tone}>{value}</strong><small>{detail}</small></div>
}
export default function ConstituentIntelligence({onOpenRecording,onOpenSources,onOpenData,onOpenOptions}:{onOpenRecording:()=>void;onOpenSources:()=>void;onOpenData:()=>void;onOpenOptions:()=>void}){
 const [section,setSection]=useState<'movement'|'derivatives'|'research'|'setup'>('movement')
 const [graph,setGraph]=useState<'returns'|'contribution'|'volume'>('returns')
 const [membershipBusy,setMembershipBusy]=useState(false)
 const [membershipMessage,setMembershipMessage]=useState('')
 const [capture,setCapture]=useState<Capture|null>(null)
 const [report,setReport]=useState<Analysis|null>(null)
 const [busy,setBusy]=useState(true)
 const [captureBusy,setCaptureBusy]=useState(false)
 const [error,setError]=useState('')
 const [captureError,setCaptureError]=useState('')
 const [horizon,setHorizon]=useState(5)
 const [mode,setMode]=useState<'live'|'history'>('live')
 const [historyTime,setHistoryTime]=useState('')
 const [appliedTime,setAppliedTime]=useState('')
 const [revision,setRevision]=useState(0)
 const [sort,setSort]=useState<Sort>('weight_pct')
 const [auto,setAuto]=useState(true)
 const [date,setDate]=useState(today)
 const [source,setSource]=useState('')
 const [csv,setCsv]=useState('')
 const [reviewed,setReviewed]=useState(false)
 const [weightBusy,setWeightBusy]=useState(false)
 const [weightMessage,setWeightMessage]=useState('')
 useEffect(()=>{
   let alive=true
   let timer:number|undefined
   let controller:AbortController|null=null
   const refresh=async()=>{
     controller=new AbortController()
     const params=new URLSearchParams({horizon:String(horizon)})
     if(mode==='history'&&appliedTime)params.set('as_of',appliedTime+':00+05:30')
     const requests=[marketApi<Capture>(API+'status',{signal:controller.signal}),mode==='history'&&!appliedTime?Promise.resolve(null):marketApi<Analysis>(API+'analysis?'+params,{signal:controller.signal})] as const
     const [c,r]=await Promise.allSettled(requests)
     if(!alive)return
     if(c.status==='fulfilled'){setCapture(c.value);setCaptureError('')}else{setCapture(null);setCaptureError(readableError(c.reason))}
     if(r.status==='fulfilled'){setReport(r.value);setError('')}else{setReport(null);setError(readableError(r.reason))}
     setBusy(false)
     if(auto&&mode==='live')timer=window.setTimeout(()=>{if(document.hidden){timer=window.setTimeout(()=>void refresh(),30000)}else void refresh()},30000)
   }
   setBusy(true);setReport(null);setError('')
   void refresh()
   return()=>{alive=false;controller?.abort();if(timer!==undefined)window.clearTimeout(timer)}
 },[horizon,mode,appliedTime,revision,auto])
 const toggle=async()=>{
   if(!capture||captureBusy)return
   setCaptureBusy(true);setCaptureError('')
   try{setCapture(await marketPost<Capture>(API+'capture',{enabled:!capture.enabled}));setRevision(n=>n+1)}
   catch(e){setCaptureError(readableError(e))}finally{setCaptureBusy(false)}
 }
 const prepare=async()=>{
   if(membershipBusy)return
   setMembershipBusy(true);setMembershipMessage('')
   try{const r=await marketPost<{symbols:string[];date:string;capture_state:string}>(API+'membership/refresh',{confirm_current_source:true});setMembershipMessage('Saved '+r.symbols.length+' official current members for '+r.date+'. '+r.capture_state);setRevision(n=>n+1)}catch(e){setMembershipMessage(readableError(e))}finally{setMembershipBusy(false)}
 }
 const save=async()=>{
   if(!reviewed||!date||!csv||!source.trim()||weightBusy)return
   setWeightBusy(true);setWeightMessage('')
   try{
     const r=await marketPost<{snapshot_date:string;source_csv_sha256:string}>(API+'weights',{snapshot_date:date,csv_text:csv,source:source.trim(),confirm_reviewed:reviewed})
     setWeightMessage('Stored reviewed local weight snapshot '+r.snapshot_date+' · '+r.source_csv_sha256.slice(0,12)+'. Not independently verified.')
     setReviewed(false);setCsv('');setRevision(n=>n+1)
   }catch(e){setWeightMessage(readableError(e))}finally{setWeightBusy(false)}
 }
 const rows=useMemo(()=>[...(report?.rows||[])].sort((a,b)=>{
   const x=a[sort],y=b[sort]
   return x===null&&y===null?a.symbol.localeCompare(b.symbol):x===null?1:y===null?-1:y-x||a.symbol.localeCompare(b.symbol)
 }),[report,sort])
 const prices=rows.filter(r=>r.return_pct!==null)
 const contrib=rows.filter(r=>r.contribution_pp!==null)
 const relative=rows.filter(r=>r.relative_volume!==null)
 const weight=report?.weight_snapshot
 return <section className="bci-shell" aria-label="BANKNIFTY constituent intelligence">
  <header className="bci-head"><div><small>BANKNIFTY · UNDERLYING CONSTITUENT INTELLIGENCE</small><h2>Which banks are moving the index?</h2><p>Separate observed stock pressure from the option contract decision. Aligned constituent returns, traded-volume changes and estimated weighted contributions are descriptive evidence, not a probability of the next market move.</p></div><button className="ws-button" type="button" onClick={onOpenOptions}>Open Greeks &amp; option scenarios</button></header>
  <nav className="bci-tabs" aria-label="Directional trading sections">{([["movement","Bank movement"],["derivatives","Stock derivatives"],["research","Signal research"],["setup","Data setup"]] as const).map(([key,label])=><button type="button" className="ws-button" key={key} aria-pressed={section===key} onClick={()=>setSection(key)}>{label}</button>)}</nav>
  {section==="movement"&&<div className="bci-ready-strip"><span><b>Bank quotes:</b> {capture?.connected?"Subscribed":capture?.enabled?"Enabled · waiting for shared feed":"Disabled"}</span><span><b>Membership:</b> {report?.expected_members?report.expected_members+" members":"Missing"}</span><span><b>Weights:</b> {weight?weight.snapshot_date:"Not loaded"}</span>{report?.expected_members===0&&<button className="ws-button primary" disabled={membershipBusy} onClick={()=>void prepare()}>{membershipBusy?"Loading official list…":"Load today’s official bank list"}</button>}<button className="ws-button" onClick={()=>setSection("setup")}>Manage sources &amp; recording</button>{membershipMessage&&<small role="status">{membershipMessage}</small>}</div>}
  {section==="setup"&&<div className="bci-panel">
   <header><div><h3>Constituent feed &amp; evidence</h3><p>Uses spare slots on the same Dhan full-option feed, not a sixth connection. All option and index subscriptions retain priority. Enablement takes effect at a natural feed connection; it never forces a restart. Disable stops accepting constituent packets immediately.</p></div><button type="button" className="ws-button primary" disabled={!capture||captureBusy} onClick={()=>void toggle()}>{captureBusy?'Saving…':capture?.enabled?'Disable constituent recording':'Enable constituent recording'}</button></header>
   <div className="bci-grid">
    <Metric name="Capture state" value={capture?.state.replaceAll('_',' ')||'Unavailable'} detail={capture?.connected?'Subscription sent; saved quotes required':'Not receiving via shared socket'}/>
    <Metric name="Requested cash equities" value={capture?String(Object.keys(capture.requested).length):'—'} detail="Exact dated membership and instrument master"/>
    <Metric name="Saved sampled quotes" value={fmt(capture?.saved,0)} detail={'Process counter · one sample per '+(capture?.sample_seconds??2)+'s per instrument maximum'}/>
    <Metric name="Dropped / stale packets" value={capture?fmt(capture.dropped,0)+' / '+fmt(capture.ignored_stale,0):'—'} detail={'Last saved '+time(capture?.last_saved_utc)+' IST'}/>
   </div>
   {captureError&&<p className="bci-error" role="alert">{captureError}</p>}{capture?.storage.last_error&&<p className="bci-error">Storage: {capture.storage.last_error}</p>}
   <div className="bci-actions"><button className="ws-button primary" disabled={membershipBusy} onClick={()=>void prepare()}>{membershipBusy?"Loading…":"Load today’s official bank list"}</button><button className="ws-button" onClick={onOpenRecording}>Automatic recording settings</button><button className="ws-button" onClick={onOpenSources}>Dated membership &amp; NSE evidence</button><button className="ws-button" onClick={onOpenData}>Saved Market Library</button></div>{membershipMessage&&<p role="status" className="bci-note">{membershipMessage}</p>}
  </div>}
  {section==="movement"&&<div className="bci-panel">
   <header><div><h3>Aligned constituent movement</h3><p>Only original quotes received at or before each endpoint are eligible. Trade and receipt ages must be within 30 seconds. Missing data remains unavailable.</p></div><button className="ws-button" type="button" disabled={busy} onClick={()=>setRevision(n=>n+1)}>{busy?'Inspecting…':'Refresh constituent analysis'}</button></header>
   <div className="bci-actions">
    <label>Analysis time<select aria-label="Constituent analysis time" value={mode} onChange={e=>setMode(e.target.value as typeof mode)}><option value="live">Current time</option><option value="history">Historical saved timestamp</option></select></label>
    {mode==='history'&&<><label>End time (IST)<input type="datetime-local" aria-label="Constituent historical time IST" value={historyTime} onChange={e=>setHistoryTime(e.target.value)}/></label><button className="ws-button" disabled={!historyTime} onClick={()=>{setAppliedTime(historyTime);setRevision(n=>n+1)}}>Inspect saved timestamp</button></>}
    <label>Horizon<select aria-label="Constituent pressure horizon" value={horizon} onChange={e=>setHorizon(Number(e.target.value))}>{[1,5,10,30,60].map(n=><option key={n} value={n}>{n} min</option>)}</select></label>
    {mode==='live'&&<label className="bci-check"><input type="checkbox" checked={auto} onChange={e=>setAuto(e.target.checked)}/> Refresh every 30s (local data only)</label>}
   </div>
   {error&&<p className="bci-error" role="alert">{error}</p>}
   {report?<><p className="bci-note">Receipt cutoff {time(report.as_of_utc)} IST · Anchor {time(report.anchor_utc)} IST · {report.session_ist}</p>
    <div className="bci-grid">
     <Metric name="Aligned members" value={report.observed_members+' / '+report.expected_members} detail="Actual same-session paired observations"/>
     <Metric name="Observed weight coverage" value={pct(report.observed_weight_pct)} detail={weight?'Weight snapshot '+weight.snapshot_date:'No eligible complete weight snapshot'}/>
     <Metric name="Weighted return" value={pct(report.weighted_return_pct)} tone={color(report.weighted_return_pct)} detail="Full basket only; approximate weighted return"/>
     <Metric name="Weighted breadth" value={pct(report.weighted_breadth_pct)} tone={color(report.weighted_breadth_pct)} detail="Up weight minus down weight, not a probability"/>
    </div>
    {report.partial_contribution_pp!==null&&!report.complete_weighted_coverage&&<p className="bci-note">Observed subset contribution only: {fmt(report.partial_contribution_pp,4)} percentage points. Missing constituent weight is not treated as flat.</p>}
    {weight&&<p className="bci-note">User-reviewed weights: {weight.source} · dated {weight.snapshot_date} · sum {fmt(weight.reported_weight_sum_pct,4)}% · SHA-256 {weight.source_csv_sha256.slice(0,16)}… · not independently verified.</p>}
    {!!report.blockers.length&&<details className="bci-note bci-warning"><summary>{report.blockers.length} data coverage limitations · view details</summary>{report.blockers.map((b,i)=><p key={i}>{b}</p>)}</details>}
    <label>Sort constituents<select aria-label="Sort constituents" value={sort} onChange={e=>setSort(e.target.value as Sort)}><option value="weight_pct">Dated weight</option><option value="return_pct">Return</option><option value="relative_volume">Relative volume</option><option value="contribution_pp">Estimated contribution</option><option value="volume_delta">Interval volume</option></select></label>
    <div className="bci-scroll"><table aria-label="BANKNIFTY constituent metrics"><thead><tr><th>Bank</th><th>Dated weight</th><th>Last observed price (₹)</th><th>Return</th><th>Volume change (shares)</th><th>RVOL / baseline sessions</th><th>ATP deviation</th><th>Displayed quantity imbalance</th><th>Contribution (pp)</th><th>Approx. index points</th><th>Receipt (IST)</th></tr></thead><tbody>{rows.map(r=><tr key={r.symbol}><td><strong>{r.symbol}</strong><small>{r.current?.identity||'No aligned source'}</small></td><td>{pct(r.weight_pct)}</td><td>{fmt(r.current?.price)}</td><td className={color(r.return_pct)}>{pct(r.return_pct)}</td><td>{fmt(r.volume_delta,0)}</td><td>{r.relative_volume===null?'—':fmt(r.relative_volume)+'×'} / {r.baseline_sessions}</td><td className={color(r.atp_deviation_pct)}>{pct(r.atp_deviation_pct)}</td><td>{fmt(r.displayed_quantity_imbalance,3)}</td><td className={color(r.contribution_pp)}>{fmt(r.contribution_pp,4)}</td><td className={color(r.approx_index_points)}>{fmt(r.approx_index_points)}</td><td>{time(r.current?.received_utc)}</td></tr>)}{!rows.length&&<tr><td colSpan={11}>Dated membership is unavailable. No constituents are invented.</td></tr>}</tbody></table></div>
    {!!rows.length&&<div className="bci-actions"><label>Chart<select aria-label="Constituent chart" value={graph} onChange={e=>setGraph(e.target.value as typeof graph)}><option value="returns">Observed returns</option><option value="contribution">Weighted contributions</option><option value="volume">Relative volume</option></select></label></div>}
    {graph==="returns"&&prices.length>0&&<ResearchPlot compact provenance="Sampled original NSE_EQ quotes" plot={{kind:'bar2d',title:'Observed constituent returns · '+report.horizon_minutes+' minutes',x_label:'Constituent',y_label:'Return (%)',x:prices.map(r=>r.symbol),traces:[{name:'Return',y:prices.map(r=>r.return_pct)}],reference_lines:[{value:0,label:'Flat'}]}}/>}
    {graph==="contribution"&&contrib.length>0&&<ResearchPlot compact provenance="User-reviewed dated weights × observed constituent returns" plot={{kind:'bar2d',title:'Estimated weighted index contributions',x_label:'Constituent',y_label:'Percentage points',x:contrib.map(r=>r.symbol),traces:[{name:'Observed weighted contribution',y:contrib.map(r=>r.contribution_pp)}],reference_lines:[{value:0,label:'Flat'}]}}/>}
    {graph==="volume"&&relative.length>0&&<ResearchPlot compact provenance="Same-time prior recorded equity quote intervals" plot={{kind:'bar2d',title:'Relative interval volume',x_label:'Constituent',y_label:'Current / mean prior interval volume (×)',x:relative.map(r=>r.symbol),traces:[{name:'Relative volume',y:relative.map(r=>r.relative_volume)}],reference_lines:[{value:1,label:'Prior mean'}]}}/>}
    {graph==="contribution"&&!contrib.length&&<p className="bci-note">A dated weight snapshot and aligned quotes are needed.</p>}{graph==="volume"&&!relative.length&&<p className="bci-note">At least five prior same-time quote intervals are needed.</p>}
    <details className="bci-note"><summary>Calculation methodology</summary><p>{report.note}</p></details>
   </>:<p className="bci-note">{busy?'Reading saved constituent observations…':mode==='history'?'Choose an exact historical IST timestamp and inspect it.':'No analysis response available.'}</p>}
  </div>}
  {section==="research"&&<ConstituentProspective/>}
  {section==="derivatives"&&<ConstituentDerivatives/>}
  {section==="setup"&&<><ArchivedWeights onSaved={()=>setRevision(n=>n+1)}/>
  <details className="bci-panel"><summary>Import dated BANKNIFTY weights from a reviewed source</summary>
   <p className="bci-note">Use an authorized dated NSE index weight report. CSV must contain exactly symbol,weight_pct, every dated member once, and a sum within 0.1 percentage point of 100%. No equal-weight fallback. Snapshot must be no more than 35 days old and actually saved before the analysis cutoff.</p>
   <div className="bci-actions"><label>Snapshot date<input aria-label="Constituent weight snapshot date" type="date" max={today()} value={date} onChange={e=>{setDate(e.target.value);setReviewed(false)}}/></label><label>Source reference<input aria-label="Constituent weight source" maxLength={300} placeholder="Authorized source report name/date" value={source} onChange={e=>{setSource(e.target.value);setReviewed(false)}}/></label><label>Read CSV file<input type="file" accept=".csv,text/csv" aria-label="Select constituent weight CSV" onChange={async e=>{const f=e.target.files?.[0];setReviewed(false);if(f&&f.size<=16000)setCsv(await f.text());else if(f)setWeightMessage('Weight CSV exceeds 16 KB')}}/></label></div>
   <label>Reviewed percentage weights<textarea aria-label="Constituent weight CSV" rows={5} maxLength={16000} placeholder={'symbol,weight_pct\n[exact dated constituent rows]'} value={csv} onChange={e=>{setCsv(e.target.value);setReviewed(false)}}/></label>
   <label className="bci-check"><input type="checkbox" checked={reviewed} onChange={e=>setReviewed(e.target.checked)}/> I reviewed the authorized source, snapshot date, constituent list and percentage units.</label>
   <button className="ws-button primary" type="button" disabled={!reviewed||!csv||!date||!source.trim()||weightBusy} onClick={()=>void save()}>{weightBusy?'Saving…':'Save reviewed weight snapshot'}</button>{weightMessage&&<p role="status" className="bci-note">{weightMessage}</p>}
  </details></>}
 </section>
}
