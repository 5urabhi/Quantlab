import {useState} from 'react'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
type Receipt={id:string;ingested_utc:string;files:{name:string;original_sha256:string;bytes:number}[]}
export default function ArchivedWeights({onSaved}:{onSaved:()=>void}){
 const [receipts,setReceipts]=useState<Receipt[]|null>(null)
 const [receipt,setReceipt]=useState('')
 const [filename,setFilename]=useState('')
 const [date,setDate]=useState('')
 const [reviewed,setReviewed]=useState(false)
 const [busy,setBusy]=useState(false)
 const [message,setMessage]=useState('')
 const current=receipts?.find(r=>r.id===receipt)
 const files=current?.files.filter(f=>f.name.toLowerCase().endsWith('.csv'))||[]
 const refresh=async()=>{
  setBusy(true);setMessage('')
  try{
   const result=await marketApi<{receipts:Receipt[];partial:boolean}>('/api/workspace/nse-sources/receipts?limit=100')
   setReceipts(result.receipts.filter(r=>r.files.some(f=>f.name.toLowerCase().endsWith('.csv'))))
   if(result.partial)setMessage('Partial intake archive listing; only returned original CSV files can be selected.')
  }catch(e){setMessage(readableError(e));setReceipts(null)}finally{setBusy(false)}
 }
 const save=async()=>{
  setBusy(true);setMessage('')
  try{
   const r=await marketPost<{snapshot_date:string;source_csv_sha256:string}>('/api/trading-cockpit/constituents/weights/import-receipt',{receipt_id:receipt,filename,snapshot_date:date,confirm_reviewed:reviewed})
   setMessage('Imported dated local weights '+r.snapshot_date+' · normalized SHA-256 '+r.source_csv_sha256.slice(0,16)+'. Original intake bytes verified; source authenticity remains user-reviewed.')
   setReviewed(false);onSaved()
  }catch(e){setMessage(readableError(e))}finally{setBusy(false)}
 }
 return <section className="bci-panel" aria-label="Archived constituent weights">
  <header><div><h3>Reuse authorized weightage intake</h3><p>Automatically normalize a selected original CSV already stored in NSE Source Evidence. The backend checks the original SHA-256 and requires exact dated membership. No website scraping or inferred publication date.</p></div><button className="ws-button" type="button" disabled={busy} onClick={()=>void refresh()}>Inspect saved weightage receipts</button></header>
  {receipts&&<><div className="bci-actions">
   <label>Intake receipt<select aria-label="Archived weight receipt" disabled={busy} value={receipt} onChange={e=>{setReceipt(e.target.value);setFilename('');setReviewed(false)}}><option value="">Select saved intake</option>{receipts.map(r=><option key={r.id} value={r.id}>{r.id} · {r.ingested_utc.slice(0,10)}</option>)}</select></label>
   <label>Original CSV<select aria-label="Archived weight CSV" disabled={busy||!receipt} value={filename} onChange={e=>{setFilename(e.target.value);setReviewed(false)}}><option value="">Select original CSV</option>{files.map(f=><option key={f.name} value={f.name}>{f.name}</option>)}</select></label>
   <label>Reviewed weight date<input type="date" aria-label="Archived weight date" value={date} disabled={busy} onChange={e=>{setDate(e.target.value);setReviewed(false)}}/></label>
   </div>
   {!receipts.length&&<p className="bci-note">No authorized original CSV receipts returned. Import the source in NSE Source Evidence first.</p>}
   <label className="bci-check"><input type="checkbox" checked={reviewed} disabled={busy} onChange={e=>setReviewed(e.target.checked)}/> I reviewed this BANKNIFTY-only report, date, permission and percentage-weight units.</label>
   <button className="ws-button primary" type="button" disabled={busy||!receipt||!filename||!date||!reviewed} onClick={()=>void save()}>Import verified archived bytes</button></>}
  {message&&<p className="bci-note" role="status">{message}</p>}
 </section>
}
