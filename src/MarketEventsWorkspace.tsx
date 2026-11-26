import {useEffect,useState} from 'react'
import {marketApi,readableError} from './tradingCockpitApi'

type Source={received_utc:string;sha256:string}|null
type Headline={source:string;title:string;topic:string;published_utc:string;first_received_utc:string;link:string}
type Release={release_id:number;title:string;date:string}
type Events={as_of_utc:string;sources:Record<string,Source>;headlines:Headline[];calendar:Release[];features:{features:Record<string,number>;full_source_coverage:boolean}|null;warning:string}
const sourceLabels:Record<string,string>={rbi_press:'RBI press releases',fed_monetary:'Federal Reserve monetary policy',fed_banking:'Federal Reserve banking regulation',fred_calendar:'FRED macro release dates'}
const pretty=(s:string)=>s.replaceAll('_',' ')
const time=(s?:string)=>s?new Date(s).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',dateStyle:'medium',timeStyle:'short'})+' IST':'Unavailable'
export default function MarketEventsWorkspace({onOpenSources}:{onOpenSources:()=>void}){
 const [value,setValue]=useState<Events|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[revision,setRevision]=useState(0)
 useEffect(()=>{let active=true,running=false
 const refresh=async()=>{if(running)return;running=true;if(active)setBusy(true);try{const next=await marketApi<Events>('/api/market-intelligence/events');if(active){setValue(next);setError('')}}catch(e){if(active)setError(readableError(e))}finally{running=false;if(active)setBusy(false)}}
 void refresh();const timer=window.setInterval(()=>void refresh(),30000);return()=>{active=false;window.clearInterval(timer)}
 },[revision])
 return <section className="bci-panel" aria-label="Economic events and official announcements"><header><div><small>MACRO CATALYSTS · POINT-IN-TIME EVIDENCE</small><h3>Economic events & official announcements</h3><p>Track observed central-bank releases, liquidity and banking topics, and scheduled macro release dates without guessing their market direction.</p></div><div className="bci-actions"><button className="ws-button" disabled={busy} onClick={()=>setRevision(v=>v+1)}>Refresh stored evidence</button><button className="ws-button primary" onClick={onOpenSources}>Configure source collection →</button></div></header>
 {error&&<p role="alert" className="bci-error">{error}</p>}
 <div className="bci-grid">{Object.entries(sourceLabels).map(([k,label])=><div key={k} className="bci-stat"><span>{label}</span><strong>{value?.sources[k]?'Received':'Unavailable'}</strong><small>{time(value?.sources[k]?.received_utc)}</small></div>)}</div>
 <p className="bci-note">{value?.warning||'Waiting for stored official-source evidence.'} {value?.features?.full_source_coverage?'All required event source families have recent receipts.':'Full event-model source coverage is not established.'}</p>
 <h4>Upcoming and current macro release dates</h4><p>Dates are supplied by the source; no exact release time, forecast, actual value or surprise is inferred. The FRED calendar is not a complete global or Indian economic calendar.</p>
 <div className="bci-scroll"><table aria-label="Macro release dates"><thead><tr><th>Date (source calendar)</th><th>Release</th><th>Release ID</th></tr></thead><tbody>{(value?.calendar||[]).map(r=><tr key={r.release_id+'-'+r.date}><td>{r.date}</td><td>{r.title}</td><td>{r.release_id}</td></tr>)}{!value?.calendar.length&&<tr><td colSpan={3}>No stored matching release dates; this is not evidence that no events are scheduled.</td></tr>}</tbody></table></div>
 <h4>Official announcements</h4><div className="bci-scroll"><table aria-label="Official announcement receipts"><thead><tr><th>Headline</th><th>Source</th><th>Topic</th><th>Published (IST)</th><th>First received (IST)</th></tr></thead><tbody>{(value?.headlines||[]).map((r,i)=><tr key={r.source+'-'+r.published_utc+'-'+i}><td>{r.link?<a href={r.link} target="_blank" rel="noopener noreferrer">{r.title}</a>:r.title}</td><td>{sourceLabels[r.source]||r.source}</td><td>{pretty(r.topic)}</td><td>{time(r.published_utc)}</td><td>{time(r.first_received_utc)}</td></tr>)}{!value?.headlines.length&&<tr><td colSpan={5}>No timestamp-qualified announcements saved.</td></tr>}</tbody></table></div>
 {value?.features&&<details className="bci-note"><summary>Event-model feature values</summary><p>Counts are descriptive, not sentiment scores or trade recommendations.</p><div className="bci-grid">{Object.entries(value.features.features).map(([k,v])=><div key={k} className="bci-stat"><span>{pretty(k)}</span><strong>{v}</strong></div>)}</div></details>}
 </section>
}
