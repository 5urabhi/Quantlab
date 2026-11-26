import {useEffect,useState} from 'react'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
type Status={config:{enabled:boolean;source:string};folder:string;state:string;last_scan_utc:string|null;scanning:boolean;eligible_files:number;counts?:Record<string,number>;files:{file:string;state:string;rows?:number;detail?:string}[];note:string;error?:string|null}
const base='/api/market-intelligence/participant-inbox'
export default function ParticipantInbox(){
 const [status,setStatus]=useState<Status|null>(null),[enabled,setEnabled]=useState(false),[source,setSource]=useState(''),[ready,setReady]=useState(false),[consent,setConsent]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('')
 useEffect(()=>{let alive=true,pending=false
 const load=async()=>{if(pending)return;pending=true;try{const r=await marketApi<Status>(base);if(alive)setStatus(r)}catch(e){if(alive)setError(readableError(e))}finally{pending=false}}
 void load();const timer=window.setInterval(()=>void load(),5000);return()=>{alive=false;window.clearInterval(timer)}},[])
 useEffect(()=>{if(status&&!ready){setEnabled(status.config.enabled);setSource(status.config.source);setReady(true)}},[status,ready])
 const save=async()=>{if(busy||!ready||(enabled&&(!consent||source.trim().length<3)))return;setBusy(true);setError('')
 try{const r=await marketPost<Status>(base,{enabled,source,confirm_reviewed:consent});setStatus(r);setConsent(false)}catch(e){setError(readableError(e))}finally{setBusy(false)}}
 return <details className="bci-note"><summary><strong>Authorized participant report delivery</strong></summary>
 <p>Automatically consume complete report files delivered by your authorized provider or approved export. This is a local inbox, not an NSE scraper. Files remain untouched. Report dates are not treated as publication times.</p>
 <p>Inbox: <code style={{overflowWrap:'anywhere'}}>{status?.folder||'Loading local path'}</code></p>
 <p>Names: <code>fao_participant_oi_DDMMYYYY.csv</code> or <code>fao_participant_vol_DDMMYYYY.csv</code>. Deliver by atomic rename after writing.</p>
 <div className="bci-actions"><label><input type="checkbox" checked={enabled} disabled={!ready||busy} onChange={e=>{setEnabled(e.target.checked);setConsent(false)}}/> Enable automatic local intake</label><label>Reviewed licensed source<input value={source} disabled={!ready||busy} onChange={e=>{setSource(e.target.value);setConsent(false)}} placeholder="Source identity"/></label></div>
 <label><input type="checkbox" checked={consent} disabled={!ready||busy} onChange={e=>setConsent(e.target.checked)}/> I have permission to store and use these reports for model research.</label>
 <div className="bci-actions"><button className="ws-button primary" disabled={!ready||busy||(enabled&&(!consent||source.trim().length<3))} onClick={()=>void save()}>Save inbox settings</button></div>
 <p>{status?.config.enabled?'Enabled':'Disabled'} · {status?.scanning?'Scanning':status?.state||'—'} · {status?.eligible_files||0} matching files · last scan {status?.last_scan_utc||'—'}. {Object.entries(status?.counts||{}).map(([k,v])=>k+': '+v).join(' · ')}</p>
 {status?.files.length? <div className="bci-scroll"><table aria-label="Participant report intake status"><thead><tr><th>File</th><th>State</th><th>Rows</th><th>Detail</th></tr></thead><tbody>{status.files.map(r=><tr key={r.file}><td>{r.file}</td><td>{r.state}</td><td>{r.rows??'—'}</td><td>{r.detail||'—'}</td></tr>)}</tbody></table></div>:null}
 <p>{status?.note}</p>{(error||status?.error)&&<p role="alert" className="bci-error">{error||status?.error}</p>}
 </details>
}
