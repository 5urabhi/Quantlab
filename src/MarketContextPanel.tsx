import {useEffect,useState} from 'react'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'

type Mode='receipt'|'archive'
type Factor={factor:string;kind:string;group:string;description:string}
type FactorState={state:string;level?:number;change_feature?:number;event_utc?:string;known_utc?:string;age_hours?:number;source?:string;receipt_sha256?:string}
type OptionContext={expiry:string;received_utc:string;prior_received_utc:string|null;spot:number;paired_strikes:number;matched_prior_strikes:number;put_call_oi_ratio:number;put_call_volume_ratio:number|null;largest_call_oi_strike:number;largest_put_oi_strike:number;features:Record<string,number>}
type Snapshot={as_of_utc:string;mode:Mode;catalog:Factor[];factors:Record<string,FactorState>;global_group_coverage:boolean;options:OptionContext|null;domestic:{return_30m_bps:number}|null;imported_rows:number;ambiguous_factors:string[];warning:string}
type Receipt={receipt_sha256:string;rows:number;inserted:boolean;mode:Mode;note:string}
const base='/api/trading-cockpit/constituents/alpha/context'
const fmt=(v:number|null|undefined,d=2)=>v==null?'—':v.toLocaleString('en-IN',{maximumFractionDigits:d})
const pretty=(v:string)=>v.replaceAll('_',' ')

export default function MarketContextPanel({mode,onMode,disabled=false}:{mode:Mode;onMode:(m:Mode)=>void;disabled?:boolean}){
 const [snapshot,setSnapshot]=useState<Snapshot|null>(null),[cutoff,setCutoff]=useState(''),[revision,setRevision]=useState(0)
 const [kind,setKind]=useState<'factors'|'oi'|'volume'>('factors'),[csv,setCsv]=useState(''),[source,setSource]=useState('')
 const [day,setDay]=useState(''),[available,setAvailable]=useState(''),[reviewed,setReviewed]=useState(false)
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[receipt,setReceipt]=useState<Receipt|null>(null)
 const [loading,setLoading]=useState(true)
 useEffect(()=>{let active=true;setLoading(true);setSnapshot(null)
 const query=new URLSearchParams({mode});if(cutoff.trim())query.set('as_of',cutoff.trim())
 marketApi<Snapshot>(base+'?'+query.toString()).then(x=>{if(active)setSnapshot(x)}).catch(e=>{if(active)setError(readableError(e))}).finally(()=>{if(active)setLoading(false)})
 return()=>{active=false}
 },[mode,revision]) // explicit refresh applies the selected historical cutoff
 const importData=async()=>{if(busy||disabled||!reviewed||!csv.trim())return
 setBusy(true);setError('');setReceipt(null)
 try{
 const r=kind==='factors'?await marketPost<Receipt>(base+'/import',{csv_text:csv,source:source.trim(),mode,confirm_reviewed:true}):
 await marketPost<Receipt>(base+'/participants',{csv_text:csv,report_day:day,available_utc:available.trim(),report_type:kind,mode,confirm_reviewed:true})
 setReceipt(r);setCsv('');setReviewed(false);setRevision(v=>v+1)
 }catch(e){setError(readableError(e))}finally{setBusy(false)}}
 const option=snapshot?.options
 const counts=(g:string)=>snapshot?.catalog.filter(x=>x.group===g&&snapshot.factors[x.factor]?.state==='available').length||0
 return <details className="bci-note" open><summary><strong>Market context · evidence and source setup</strong></summary>
 <p>Global markets, domestic breadth, BANKNIFTY option positioning and participant reports. No extra provider requests or order placement; missing data is not fabricated.</p>
 <div className="bci-actions">
 <label>Source timing<select aria-label="Context availability mode" value={mode} disabled={busy||disabled} onChange={e=>{setReviewed(false);onMode(e.target.value as Mode)}}><option value="receipt">Receipt mode · actual import time</option><option value="archive">Archive research · reviewed availability</option></select></label>
 <label>As-of timestamp (optional ISO + offset)<input aria-label="Context as of timestamp" value={cutoff} placeholder="2026-11-26T10:00:00+05:30" onChange={e=>setCutoff(e.target.value)}/></label>
 <button className="ws-button" disabled={loading} onClick={()=>{setError('');setRevision(v=>v+1)}}>Refresh market context</button></div>
 {mode==='archive'&&<p className="bci-note bci-warning">Historical availability in archive mode is user-reviewed, not independently verified. Results are retrospective, not genuine prospective evidence.</p>}
 {loading&&<p role="status">Reading saved market evidence…</p>}
 {snapshot&&<><p>As of {snapshot.as_of_utc} · {snapshot.imported_rows.toLocaleString('en-IN')} external observations in the bounded source window.</p>
 <div className="bci-grid">{[['Global equities',counts('global_equity')],['Asian markets',counts('asia')],['Macro / FX / rates',counts('macro')],['Participant series',counts('participants')]].map(([k,v])=><div className="bci-stat" key={k}><span>{k}</span><strong>{v}</strong><small>Available level + change series</small></div>)}
 <div className="bci-stat"><span>NIFTY 50 return · 30m</span><strong>{fmt(snapshot.domestic?.return_30m_bps)} bps</strong></div>
 <div className="bci-stat"><span>BANKNIFTY paired option strikes</span><strong>{option?option.paired_strikes:'Unavailable'}</strong><small>{option?option.expiry:'Fresh verified saved chain required'}</small></div></div>
 {option&&<div className="bci-grid"><div className="bci-stat"><span>Put / call open interest</span><strong>{fmt(option.put_call_oi_ratio)}</strong><small>Near-spot paired contracts only</small></div><div className="bci-stat"><span>Put / call cumulative volume</span><strong>{fmt(option.put_call_volume_ratio)}</strong></div><div className="bci-stat"><span>ATM IV</span><strong>{fmt(option.features.atm_iv_pct)}%</strong></div><div className="bci-stat"><span>15m same-ATM IV change</span><strong>{option.features.atm_iv_change_missing?'—':fmt(option.features.same_atm_iv_change_pct_points)+' pp'}</strong></div><div className="bci-stat"><span>Largest call / put OI strikes</span><strong>{fmt(option.largest_call_oi_strike,0)} / {fmt(option.largest_put_oi_strike,0)}</strong></div><div className="bci-stat"><span>Matched prior strikes</span><strong>{option.matched_prior_strikes}</strong><small>Same expiry, identity and lot size</small></div></div>}
 <p className="bci-note">{snapshot.warning}</p>
 {snapshot.ambiguous_factors.length>0&&<p className="bci-warning">Conflicting source identities: {snapshot.ambiguous_factors.join(', ')}</p>}
 <details><summary>Factor catalog and observed timestamps</summary><div className="bci-scroll"><table aria-label="Market context factor coverage"><thead><tr><th>Factor / group</th><th>State</th><th>Level</th><th>Change feature</th><th>Known UTC</th><th>Source</th></tr></thead><tbody>{snapshot.catalog.map(f=>{const v=snapshot.factors[f.factor];return <tr key={f.factor}><td><strong>{f.factor}</strong><small style={{display:'block'}}>{f.description} · {pretty(f.group)}</small></td><td>{pretty(v?.state||'unavailable')}</td><td>{fmt(v?.level)}</td><td>{fmt(v?.change_feature)}</td><td>{v?.known_utc||'—'}</td><td>{v?.source||'—'}</td></tr>})}</tbody></table></div></details></>}
 <details><summary>Import authorized source data</summary>
 <div className="bci-actions"><label>Import type<select aria-label="Market context import type" value={kind} disabled={busy||disabled} onChange={e=>{setKind(e.target.value as typeof kind);setCsv('');setReviewed(false)}}><option value="factors">Normalized factor CSV</option><option value="oi">Original NSE participant OI CSV</option><option value="volume">Original NSE participant volume CSV</option></select></label>
 {kind==='factors'?<label>Source / instrument identity<input aria-label="Context source identity" value={source} onChange={e=>{setSource(e.target.value);setReviewed(false)}} placeholder="Vendor, instrument, consistent methodology" disabled={busy||disabled}/></label>:<><label>Report session<input type="date" aria-label="Participant report session" value={day} onChange={e=>{setDay(e.target.value);setReviewed(false)}} disabled={busy||disabled}/></label><label>Actual publication timestamp<input aria-label="Participant report availability" placeholder="YYYY-MM-DDTHH:mm:ss+05:30" value={available} onChange={e=>{setAvailable(e.target.value);setReviewed(false)}} disabled={busy||disabled}/></label></>}
 <label>CSV file<input aria-label="Market context CSV file" type="file" accept=".csv,text/csv" disabled={busy||disabled} onChange={async e=>{const file=e.target.files?.[0];if(!file)return;setReviewed(false);if(file.size>(kind==='factors'?5000000:64000)){setError('CSV exceeds the bounded import size');return}try{setCsv(await file.text());setError('')}catch(err){setError(readableError(err))}}}/></label></div>
 <p>{kind==='factors'?'Exact header: factor,event_utc,available_utc,value. Use timezone-aware event and publication timestamps; use consistent units and instruments.':'Use the original NSE participant report with Client, DII, FII, Pro and TOTAL rows. The publication timestamp must be after market close.'}</p>
 <textarea aria-label="Market context CSV contents" rows={5} style={{width:'100%',boxSizing:'border-box'}} value={csv} onChange={e=>{setCsv(e.target.value);setReviewed(false)}} disabled={busy||disabled}/>
 <label><input type="checkbox" checked={reviewed} disabled={busy||disabled} onChange={e=>setReviewed(e.target.checked)}/> I reviewed the authorized source, instrument definitions, units, and actual availability timestamps.</label>
 <div className="bci-actions"><button className="ws-button primary" disabled={busy||disabled||!reviewed||!csv.trim()||(kind==='factors'?source.trim().length<3:!day||!available.trim())} onClick={()=>void importData()}>{busy?'Saving…':'Save reviewed context evidence'}</button></div>
 {receipt&&<p role="status">{receipt.inserted?'Imported':'Already stored'} {receipt.rows} rows · receipt {receipt.receipt_sha256.slice(0,16)}. {receipt.note}</p>}
 </details>
 {error&&<p className="bci-error" role="alert">{error}</p>}
 </details>
}
