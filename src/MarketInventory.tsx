import {useEffect,useState} from 'react'
import {Database,RefreshCw,Search,ArrowRight,Download,HardDrive,Clock3} from 'lucide-react'
import {marketApi,readableError} from './tradingCockpitApi'
import ContextDrawer from './ContextDrawer'
import MarketInventoryCharts from './MarketInventoryCharts'
import TradingDataRepair from './TradingDataRepair'
import MarketMaintenance from './MarketMaintenance'
import {openSnapshotInPython} from './pythonBridge'
import './market-inventory.css'

type Source={id:string;label:string;unit:string;time_basis:string;storage:string;provenance:string;state:string;detail:string;groups:number;instruments:number;count:number|null;first:string|null;last:string|null;inspected_count:number;sample_present?:boolean|null}
type Entry={source:string;identity:string;name:string;resolution:string;count:number;first:string|null;last:string|null;evidence:string;qualifier:string}
type Report={library_id:string;checked_utc:string;sources:Source[];items:Entry[];total:number;page:number;has_more:boolean;cache_age_seconds:number;note:string}
type Records={columns:string[];rows:(string|number|null)[][];has_more:boolean;before:string|null;note:string}
const fmt=(n:number|null|undefined)=>n==null?'Not verified':n.toLocaleString('en-IN')
const stamp=(s:string|null|undefined)=>!s?'—':s.length===10?s:s.replace('T',' ').replace('+00:00',' UTC').replace(/\.\d{1,6} UTC$/,' UTC')
const stateText=(s:string)=>(({stored:'Stored rows',receipt:'Saved receipts',empty:'Empty',not_recorded:'Not recorded',partial:'Partial inventory',not_verified:'Needs inspection'} as Record<string,string>)[s]||s)
const evidenceText=(s:string)=>(({stored_rows:'Stored database rows',receipt_count_csv_edges:'Receipt count + actual file endpoints',receipt_timestamps:'Saved response timestamps',archive_manifest:'Archive manifest'} as Record<string,string>)[s]||s)
const sqlSources=new Set(['daily_closes','constituent_quotes','constituent_derivative_quote','constituent_derivative_oi','live_ticks','live_minute_bars','option_quote','option_oi','option_chain','live_depth_books','depth_features','sector_history','prospective_signals','market_context','market_event_receipts','market_news'])
const categories=[
 {title:'Historical prices',ids:['daily_closes','raw_daily','raw_intraday','index_history','active_option_history','expired_options']},
 {title:'Recorded market activity',ids:['constituent_quotes','constituent_derivative_quote','constituent_derivative_oi','live_ticks','live_minute_bars','option_quote','option_oi','option_chain','live_depth_books','depth_features']},
 {title:'Global markets & economic events',ids:['market_context','market_event_receipts','market_news']},
 {title:'Derived research evidence',ids:['prospective_signals']},
 {title:'Reference & backups',ids:['sector_history','archives']},
]
function exportJSON(name:string,value:unknown){
 const u=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)
}
export default function MarketInventory({compact=false,onAcquire,onReplay,onModels}:{compact?:boolean;onAcquire?:()=>void;onReplay?:()=>void;onModels?:()=>void}){
 const [repair,setRepair]=useState(false)
 const [source,setSource]=useState('all')
 const [search,setSearch]=useState('')
 const [query,setQuery]=useState('')
 const [page,setPage]=useState(1)
 const [refresh,setRefresh]=useState(0)
 const [report,setReport]=useState<Report|null>(null)
 const [busy,setBusy]=useState(true)
 const [error,setError]=useState('')
 const [entry,setEntry]=useState<Entry|null>(null)
 const [records,setRecords]=useState<Records|null>(null)
 const [recordBusy,setRecordBusy]=useState(false)
 const [recordError,setRecordError]=useState('')
 const [before,setBefore]=useState('')
 useEffect(()=>{const t=window.setTimeout(()=>{setQuery(search.trim());setPage(1)},250);return()=>window.clearTimeout(t)},[search])
 useEffect(()=>{
   let alive=true;const c=new AbortController()
   setBusy(true);setError('')
   const params=new URLSearchParams({source,query,page:String(page),per_page:'50',refresh:refresh?'true':'false'})
   void marketApi<Report>('/api/data-manager/inventory?'+params,{signal:c.signal}).then(r=>{if(alive)setReport(r)}).catch(e=>{if(alive)setError(readableError(e))}).finally(()=>{if(alive)setBusy(false)})
   return()=>{alive=false;c.abort()}
 },[source,query,page,refresh])
 useEffect(()=>{
   if(!entry||!sqlSources.has(entry.source)){setRecords(null);return}
   let alive=true;const c=new AbortController();setRecordBusy(true);setRecordError('');setRecords(null)
   const params=new URLSearchParams({source:entry.source,identity:entry.identity,qualifier:entry.qualifier,before,limit:'50'})
   void marketApi<Records>('/api/data-manager/inventory/records?'+params,{signal:c.signal}).then(r=>{if(alive)setRecords(r)}).catch(e=>{if(alive)setRecordError(readableError(e))}).finally(()=>{if(alive)setRecordBusy(false)})
   return()=>{alive=false;c.abort()}
 },[entry,before])
 const choose=(id:string)=>{setSource(id);setPage(1)}
 const current=report?.sources.find(s=>s.id===source)
 const rowsMatch=report&&(!busy&&!error)
 const active=report?.sources.filter(s=>s.count!==null&&s.count>0).length||0
 const unresolved=report?.sources.filter(s=>['partial','not_verified'].includes(s.state)).length||0
 return <section className="mi-shell" aria-label="Unified saved market data inventory">
   <header className="mi-head"><div><small><Database size={15}/> UNIFIED DATA INVENTORY</small><h2>{compact?'Stored observation coverage':'Your complete market data library'}</h2><p>See what is actually stored across historical downloads and the automatic recorder. No new download or duplicate dataset is created by this view.</p></div><div className="mi-head-actions"><button className="ws-button" type="button" disabled={busy} onClick={()=>setRefresh(v=>v+1)}><RefreshCw size={15}/>{busy?'Inspecting…':'Refresh inventory'}</button><button type="button" className="ws-button primary" aria-expanded={repair} onClick={()=>setRepair(v=>!v)}>{repair?'Close manual repair':'Manual repair & inspection'} <ArrowRight size={15}/></button></div></header>
   {!compact&&<MarketMaintenance onDone={()=>setRefresh(v=>v+1)}/>}
   {repair&&<TradingDataRepair sources={report?.sources||[]} onOpenStocks={onAcquire} onInspect={id=>{choose(id);setRepair(false)}} onDone={()=>setRefresh(v=>v+1)}/>}
   <div className="mi-kpis">
     <div><span><HardDrive size={15}/> Logical library</span><strong>dhan_shared</strong><small>Original records + source receipts</small></div>
     <div><span>Data types with saved rows</span><strong>{report?active+' / '+report.sources.length:'—'}</strong><small>Not a sum of overlapping records</small></div>
     <div><span>Needs further inspection</span><strong>{report?unresolved:'—'}</strong><small>Bounded or unavailable reads</small></div>
     <div><span><Clock3 size={15}/> Inventory checked</span><strong className="mi-time">{stamp(report?.checked_utc)}</strong><small>{report?'Cached '+report.cache_age_seconds+' seconds at response':'Reading local storage'}</small></div>
   </div>
   {error&&<p role="alert" className="mi-error">{error} {report?'Previously inspected inventory remains visible; refresh before relying on it.':''}</p>}
   {busy&&<p role="status" className="mi-caption">Inspecting saved storage. Large tables have bounded reads to protect the recorder.</p>}
   {report&&<>{!compact&&<MarketInventoryCharts sources={report.sources} onChoose={choose}/>}<div className="mi-section-title"><div><h3>Coverage by data type</h3><p>First and last observed values use the stated timestamp basis. Gaps may exist between them.</p></div><button type="button" className="ws-button" onClick={()=>exportJSON('quantlab-market-coverage.json',{checked_utc:report.checked_utc,sources:report.sources,note:report.note})}><Download size={14}/> Export coverage</button></div>
     {categories.map(group=><div key={group.title} className="mi-category"><h4>{group.title}</h4><div className="mi-coverage-grid">
       {group.ids.map(id=>report.sources.find(s=>s.id===id)).filter((s):s is Source=>!!s).map(s=><button type="button" key={s.id} className={'mi-coverage-card '+(source===s.id?'selected':'')} aria-pressed={source===s.id} aria-label={'View '+s.label+' coverage'} onClick={()=>choose(s.id)}>
         <div className="mi-card-top"><strong>{s.label}</strong><span className={'mi-state '+s.state}>{stateText(s.state)}</span></div><div className="mi-count">{s.sample_present&&s.count==null?"Records found":fmt(s.count)} <small>{s.sample_present&&s.count==null?"count unverified":s.unit}</small></div>
         <div className="mi-range"><span>First</span><b>{stamp(s.first)}</b><span>Last</span><b>{stamp(s.last)}</b></div><footer>{s.groups} groups · {s.storage}<ArrowRight size={14}/></footer>
       </button>)}</div></div>)}
     {!compact&&<div className="mi-section-title mi-inspection"><div><h3>Inspect saved instruments and receipts</h3><p>Filter by data type, symbol, security ID, resolution or expiry. Select a row to inspect its saved evidence.</p></div></div>}
     <div className="mi-filter"><label>Data type<select aria-label="Inventory data type" value={source} onChange={e=>choose(e.target.value)}><option value="all">All stored data types</option>{report.sources.map(s=><option key={s.id} value={s.id}>{s.label}</option>)}</select></label><label>Search saved instruments<div className="mi-search"><Search size={16}/><input aria-label="Search saved instruments" value={search} maxLength={120} onChange={e=>setSearch(e.target.value)} placeholder="BANKNIFTY, NSE_FNO:…, 1 min, expiry"/></div></label>{onModels&&<button className="ws-button" type="button" onClick={onModels}>Choose model <ArrowRight size={15}/></button>}</div>
     {current&&<div className="mi-source-info"><strong>{current.label} · {current.time_basis}</strong><p>{current.provenance}. {current.detail}</p>{current.count===null&&current.inspected_count>0&&<p>Inspected so far: {fmt(current.inspected_count)} {current.unit}; full count unavailable.</p>}</div>}
     <div className="mi-table-scroll"><table aria-label="Saved market coverage by instrument"><thead><tr><th>Instrument / receipt</th><th>Data type</th><th>Resolution / expiry</th><th>Saved rows</th><th>First observed</th><th>Last observed</th><th>Evidence</th><th>Inspect</th></tr></thead><tbody>{rowsMatch&&report.items.map((r,i)=><tr key={r.source+':'+r.identity+':'+r.qualifier+':'+r.resolution+':'+i}><td><strong>{r.name}</strong><small>{r.identity}</small></td><td>{report.sources.find(s=>s.id===r.source)?.label||r.source}</td><td>{r.resolution}{r.qualifier&&r.qualifier!==r.resolution&&<small>{r.qualifier}</small>}</td><td>{fmt(r.count)}</td><td>{stamp(r.first)}</td><td>{stamp(r.last)}</td><td>{evidenceText(r.evidence)}</td><td><button type="button" className="ws-button" aria-label={'Inspect coverage '+r.identity+' '+r.source+(r.qualifier?' '+r.qualifier:'')} onClick={()=>{setBefore('');setEntry(r)}}>Inspect</button></td></tr>)}
     {rowsMatch&&!report.items.length&&<tr><td colSpan={8}>No matching stored records in the inspected inventory. Select another type or refresh.</td></tr>}{!rowsMatch&&<tr><td colSpan={8}>{busy?'Reading local storage…':'Inventory unavailable for this filter.'}</td></tr>}</tbody></table></div>
     <div className="mi-pager"><span>{rowsMatch?fmt(report.total)+' matching groups / receipts':'Loading'} · Page {page}</span><div><button type="button" className="ws-button" disabled={page<=1||busy} onClick={()=>setPage(v=>v-1)}>Previous</button><button type="button" className="ws-button" disabled={!report.has_more||busy} onClick={()=>setPage(v=>v+1)}>Next</button></div></div>
     <p className="mi-caption">{report.note} Receipt-based counts and file endpoints are not a fresh full-file integrity audit. Prepared research views and imported datasets remain in the original source browser below.</p>
   </>}
   {entry&&<ContextDrawer title={entry.name} subtitle={'Saved coverage · '+entry.identity} onClose={()=>setEntry(null)}>
     <dl>{[['Data type',report?.sources.find(s=>s.id===entry.source)?.label||entry.source],['Resolution / expiry',entry.resolution+' '+entry.qualifier],['Stored rows',fmt(entry.count)],['First observed',stamp(entry.first)],['Last observed',stamp(entry.last)],['Evidence',evidenceText(entry.evidence)]].map(([k,v])=><div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
     {sqlSources.has(entry.source)&&<><h3>Actual saved records</h3>{recordBusy&&<p role="status">Reading newest records…</p>}{recordError&&<p role="alert">{recordError}</p>}{records&&<><p className="mi-caption">{records.note}</p><div className="mi-table-scroll"><table aria-label="Actual stored records"><thead><tr>{records.columns.map(c=><th key={c}>{c}</th>)}</tr></thead><tbody>{records.rows.map((r,i)=><tr key={i}>{r.map((v,j)=><td key={j}>{v===null?'—':String(v)}</td>)}</tr>)}</tbody></table></div><div className="ws-actions"><button type="button" className="ws-button" disabled={!records.before} onClick={()=>setBefore(records.before||'')}>Older records</button><button type="button" className="ws-button" disabled={!before} onClick={()=>setBefore('')}>Newest records</button><button className="ws-button" type="button" disabled={!records.rows.length} onClick={()=>{openSnapshotInPython({title:entry.name+' · '+entry.source,provenance:'Actual local scalar record preview; not a complete source export',columns:records.columns,rows:records.rows});setEntry(null)}}>Analyze preview in Python</button><button className="ws-button" type="button" onClick={()=>exportJSON('quantlab-saved-record-preview.json',records)}>Export preview</button></div></>}</>}
     {!sqlSources.has(entry.source)&&<p className="mi-caption">This entry describes an original receipt or archive. Its full underlying source is not duplicated into SQLite by the inventory. Use existing dataset tools or historical backtests to analyze source files.</p>}
     {onReplay&&['live_ticks','live_minute_bars','option_quote','option_oi','option_chain','live_depth_books','depth_features','index_history'].includes(entry.source)&&<button type="button" className="ws-button primary" onClick={()=>{setEntry(null);onReplay()}}>Open market replay <ArrowRight size={15}/></button>}
     <button type="button" className="ws-button" onClick={()=>exportJSON('quantlab-instrument-coverage.json',entry)}>Export coverage evidence</button>
   </ContextDrawer>}
 </section>
}
