import {useState} from 'react'
import {marketPost,readableError} from './tradingCockpitApi'
import ResearchPlot from './ResearchPlots'

type Source={id:string;label:string}
type Audit={source:string;identity:string;qualifier:string;start:string;end:string;source_label:string;calendar_sha256:string;read_complete:boolean;expect_recording:boolean;missing_expected_sessions:number|null;rows:{date:string;calendar_state:string;count:number|null;verdict:string}[];note:string}
const supported=new Set(['daily_closes','live_ticks','live_minute_bars','constituent_quotes','option_quote','option_oi','option_chain','live_depth_books','depth_features'])
const today=()=>new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Kolkata'})
export default function SessionCoverageAudit({sources}:{sources:Source[]}){
 const available=sources.filter(s=>supported.has(s.id))
 const [source,setSource]=useState('live_ticks')
 const [identity,setIdentity]=useState('INDEX:BANKNIFTY')
 const [qualifier,setQualifier]=useState('')
 const [start,setStart]=useState('')
 const [end,setEnd]=useState('')
 const [calendar,setCalendar]=useState('')
 const [label,setLabel]=useState('')
 const [reviewed,setReviewed]=useState(false)
 const [expected,setExpected]=useState(false)
 const [busy,setBusy]=useState(false)
 const [result,setResult]=useState<Audit|null>(null)
 const [error,setError]=useState('')
 const changed=()=>{setResult(null);setReviewed(false);setExpected(false)}
 const run=async()=>{
  setBusy(true);setResult(null);setError('')
  try{setResult(await marketPost<Audit>('/api/data-manager/inventory/session-coverage',{source,identity:identity.trim(),qualifier:source==='option_chain'?qualifier:'',start,end,calendar_csv:calendar,source_label:label.trim(),confirm_reviewed:reviewed,expect_recording:expected}))}
  catch(e){setError(readableError(e))}finally{setBusy(false)}
 }
 return <details className="mi-activity" aria-label="Reviewed exchange session coverage"><summary><strong>Expected exchange session coverage audit</strong></summary>
  <p className="mi-caption">Compare an exact instrument's actual stored records against a reviewed NSE calendar, including holidays and special sessions. Import an authorized CSV with session_date,state (OPEN or CLOSED) for every date. No weekday assumptions or automatic missing-data claims.</p>
  <div className="mi-filter"><label>Canonical source<select value={source} aria-label="Expected session source" disabled={busy} onChange={e=>{setSource(e.target.value);setIdentity('');setQualifier('');changed()}}>{available.map(s=><option key={s.id} value={s.id}>{s.label}</option>)}</select></label><label>Exact instrument identity<input value={identity} aria-label="Expected instrument identity" maxLength={160} disabled={busy} onChange={e=>{setIdentity(e.target.value);changed()}}/></label>
  {source==='option_chain'&&<label>Exact expiry<input type="date" value={qualifier} disabled={busy} onChange={e=>{setQualifier(e.target.value);changed()}}/></label>}
  <label>From date<input type="date" max={today()} value={start} disabled={busy} onChange={e=>{setStart(e.target.value);changed()}}/></label><label>Through date<input type="date" value={end} disabled={busy} onChange={e=>{setEnd(e.target.value);changed()}}/></label></div>
  <div className="mi-filter"><label>Reviewed calendar source<input value={label} maxLength={300} disabled={busy} onChange={e=>{setLabel(e.target.value);changed()}} placeholder="NSE calendar/circular reference"/></label><label>Read calendar CSV<input type="file" accept=".csv,text/csv" disabled={busy} onChange={async e=>{const f=e.target.files?.[0];changed();if(f&&f.size<=20000)setCalendar(await f.text());else if(f)setError('Calendar file exceeds 20 KB')}}/></label></div>
  <label className="qoc-field">Calendar CSV<textarea rows={5} value={calendar} maxLength={20000} disabled={busy} onChange={e=>{setCalendar(e.target.value);changed()}} placeholder={'session_date,state\nYYYY-MM-DD,OPEN\nYYYY-MM-DD,CLOSED'}/></label>
  <label className="bci-check"><input type="checkbox" checked={reviewed} disabled={busy} onChange={e=>{setReviewed(e.target.checked);setResult(null)}}/> I reviewed every date and session state against the authorized source.</label>
  <label className="bci-check"><input type="checkbox" checked={expected} disabled={busy} onChange={e=>{setExpected(e.target.checked);setResult(null)}}/> This exact source and instrument was expected to be recorded during every OPEN date in this interval.</label>
  <button type="button" className="ws-button primary" disabled={busy||!reviewed||!identity.trim()||!calendar||!start||!end||!label.trim()||(source==='option_chain'&&!qualifier)} onClick={()=>void run()}>{busy?'Auditing…':'Audit expected sessions'}</button>
  {error&&<p className="mi-error" role="alert">{error}</p>}
  {result&&<><p className="mi-caption">Calendar source: {result.source_label} · SHA-256 {result.calendar_sha256}. {result.read_complete?'Completed bounded record query.':'Counts not verified.'} Expected sessions without observations: {result.missing_expected_sessions??'Unavailable'}.</p>
  {result.read_complete&&<ResearchPlot provenance="Reviewed calendar + actual stored records" plot={{kind:'bar2d',title:'Stored record counts by reviewed session date',x_label:'Calendar date',y_label:'Stored records',x:result.rows.map(r=>r.date),traces:[{name:'Records',y:result.rows.map(r=>r.count)}]}}/>}
  <div className="qoc-scroll"><table aria-label="Reviewed session coverage results"><thead><tr><th>Session date</th><th>Reviewed state</th><th>Records</th><th>Coverage verdict</th></tr></thead><tbody>{result.rows.map(r=><tr key={r.date}><td>{r.date}</td><td>{r.calendar_state}</td><td>{r.count??'—'}</td><td>{r.verdict.replaceAll('_',' ')}</td></tr>)}</tbody></table></div><p className="mi-caption">{result.note}</p></>}
 </details>
}
