import {useEffect,useState} from 'react'
import ResearchPlot from './ResearchPlots'
import {marketApi,readableError} from './tradingCockpitApi'

type Source={id:string;label:string;unit:string;state:string;first:string|null;last:string|null;time_basis:string;count:number|null}
type Activity={source:string;label:string;unit:string;time_basis:string;start:string;end:string;checked_utc:string;state:string;detail:string;note:string;rows:{date:string;count:number;instruments:number}[]}
const canonical=new Set(['daily_closes','live_ticks','live_minute_bars','option_quote','option_oi','option_chain','live_depth_books','depth_features','sector_history'])
const isoDay=(s:string|null)=>s&&/^\d{4}-\d{2}-\d{2}/.test(s)?s.slice(0,10):null
const epoch=(s:string|null)=>{const d=isoDay(s);return d===null?NaN:Date.parse(d+'T00:00:00Z')}
const dayString=(n:number)=>new Date(n).toISOString().slice(0,10)
const today=()=>new Date().toISOString().slice(0,10)
const fmt=(n:number)=>n.toLocaleString('en-IN')

export default function MarketInventoryCharts({sources,onChoose}:{sources:Source[];onChoose:(id:string)=>void}){
 const available=sources.filter(s=>canonical.has(s.id))
 const [source,setSource]=useState(()=>available.find(s=>s.id==='option_quote'&&s.count!==null&&s.count>0)?.id||available.find(s=>s.count!==null&&s.count>0)?.id||available[0]?.id||'')
 const selected=available.find(s=>s.id===source)||available[0]
 const [start,setStart]=useState('')
 const [end,setEnd]=useState('')
 const [data,setData]=useState<Activity|null>(null)
 const [busy,setBusy]=useState(false)
 const [error,setError]=useState('')
 useEffect(()=>{
   const last=isoDay(selected?.last||null)||today()
   setEnd(last);setStart(dayString(epoch(last)-29*86400000));setData(null);setError('')
 },[selected?.id,selected?.last])
 useEffect(()=>{setData(null);setError('')},[start,end])
 const valid=sources.filter(s=>Number.isFinite(epoch(s.first))&&Number.isFinite(epoch(s.last))&&epoch(s.first)<=epoch(s.last))
 const earliest=valid.length?Math.min(...valid.map(s=>epoch(s.first))):0
 const latest=valid.length?Math.max(...valid.map(s=>epoch(s.last))):0
 const span=Math.max(86400000,latest-earliest)
 const load=async()=>{
   if(!selected||busy)return
   setBusy(true);setError('');setData(null)
   try{const result=await marketApi<Activity>('/api/data-manager/inventory/activity?'+new URLSearchParams({source:selected.id,start,end}));setData(result)}
   catch(e){setError(readableError(e))}finally{setBusy(false)}
 }
 const shown=data&&data.source===selected?.id&&data.start===start&&data.end===end?data:null
 const populated=shown?.rows.filter(r=>r.count>0).length??0
 const max=shown?Math.max(1,...shown.rows.map(r=>r.count)):1
 return <section className="mi-visuals" aria-label="Market data coverage and activity charts">
   <header><h3>Observed coverage timeline</h3><p className="mi-caption">Endpoints show stored first and last calendar dates across inspected sources. Dashed connections do not certify continuity; different timestamp bases and overlapping receipts are kept separate.</p></header>
   {!valid.length?<p className="mi-caption">No inspected source has valid stored endpoints yet.</p>:<div className="mi-timeline">
     <div className="mi-timeline-axis"><span>{dayString(earliest)}</span><span>{dayString(latest)}</span></div>
     {valid.map(s=>{const left=100*(epoch(s.first)-earliest)/span,right=100*(epoch(s.last)-earliest)/span;return <button key={s.id} type="button" className="mi-timeline-row" onClick={()=>onChoose(s.id)} aria-label={'Inspect timeline '+s.label+' '+isoDay(s.first)+' to '+isoDay(s.last)}>
       <span><strong>{s.label}</strong><small>{s.time_basis} · {s.state==='partial'?'Partial inspection':s.state==='receipt'?'Receipt evidence':'Stored extent'}</small></span>
       <span className="mi-timeline-track"><i style={{left:left+'%',width:Math.max(0,right-left)+'%'}}/><b style={{left:left+'%'}}/><b style={{left:right+'%'}}/></span>
       <span className="mi-timeline-dates">{isoDay(s.first)} → {isoDay(s.last)}</span>
     </button>})}
   </div>}
   <div className="mi-activity"><h3>Daily stored recording activity</h3><p className="mi-caption">Inspect one canonical source at a time for up to 90 calendar days. This performs a bounded local read, not a market download.</p>
     <div className="mi-filter"><label>Activity source<select aria-label="Recording activity source" disabled={busy} value={selected?.id||''} onChange={e=>setSource(e.target.value)}>{available.map(s=><option key={s.id} value={s.id}>{s.label}</option>)}</select></label><label>From date<input type="date" aria-label="Recording activity start" disabled={busy} value={start} onChange={e=>setStart(e.target.value)}/></label><label>Through date<input type="date" aria-label="Recording activity end" disabled={busy} value={end} onChange={e=>setEnd(e.target.value)}/></label><button type="button" className="ws-button primary" disabled={busy||!selected||!start||!end} onClick={()=>void load()}>{busy?'Inspecting…':'Inspect recording activity'}</button></div>
     {error&&<p role="alert" className="mi-error">{error}</p>}
     {shown&&shown.state!=='stored'&&<p role="status" className="mi-caption">{shown.detail} Counts are unavailable.</p>}
     {shown?.state==='stored'&&<><div className="mi-activity-summary"><span><strong>{fmt(shown.rows.reduce((n,r)=>n+r.count,0))}</strong> {shown.unit}</span><span><strong>{populated} / {shown.rows.length}</strong> calendar days with records</span><span>{shown.time_basis}</span></div>
       <ResearchPlot provenance="historical" plot={{kind:'bar2d',title:shown.label+' · daily stored records',x_label:'Stored calendar date',y_label:shown.unit,x:shown.rows.map(r=>r.date),traces:[{name:shown.unit,y:shown.rows.map(r=>r.count)}]}}/>
       <ResearchPlot provenance="historical" plot={{kind:'bar2d',title:shown.label+' · daily instrument coverage',x_label:'Stored calendar date',y_label:'Distinct instruments',x:shown.rows.map(r=>r.date),traces:[{name:'Distinct instruments',y:shown.rows.map(r=>r.instruments)}]}}/>
       <h4>Calendar activity heatmap</h4><div className="mi-calendar" role="group" aria-label="Stored calendar day activity">{shown.rows.map(r=><div key={r.date} title={r.date+': '+fmt(r.count)+' '+shown.unit} aria-label={r.date+': '+fmt(r.count)+' '+shown.unit} className={r.count?'mi-calendar-active':''} style={r.count?{background:'rgba(245,197,66,'+(0.14+0.75*Math.sqrt(r.count/max))+')'}:{}}><span>{r.date.slice(5)}</span><strong>{fmt(r.count)}</strong></div>)}</div>
       <p className="mi-caption">{shown.note} Weekend, holiday, not-yet-tracked and missing market-session distinctions require a verified exchange calendar and expected subscription scope. Checked {shown.checked_utc}.</p></>}
   </div>
 </section>
}
