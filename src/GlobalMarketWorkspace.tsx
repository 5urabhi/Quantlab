import {useEffect,useState} from 'react'
import MarketContextPanel from './MarketContextPanel'
import ParticipantInbox from './ParticipantInbox'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'

type Mapping={factor:string;symbol:string;exchange:string}
type Config={enabled:boolean;fred:boolean;news:boolean;mappings:Mapping[]}
type Status={config:Config;configuration_error:string|null;worker_running:boolean;sync_running:boolean;last_sync_utc:string|null;fred_key_configured:boolean;twelve_key_configured:boolean;fred_catalog:Record<string,string>;max_mappings:number;sources:Record<string,{state:string;detail:string;attempt_utc:string;new_rows?:number}>;note:string}
const base='/api/market-intelligence/feeds'
const factors=['SP500_CLOSE','NASDAQ_CLOSE','US_BANKS_CLOSE','NIKKEI_CLOSE','HANGSENG_CLOSE','SHANGHAI_CLOSE','EUROPE_BANKS_CLOSE','US_VIX_CLOSE','USDINR_CLOSE','BRENT_CLOSE','GIFT_NIFTY','NIKKEI','HANGSENG','SHANGHAI','EUROPE_BANKS','SP500_FUT','NASDAQ_FUT','USDINR','BRENT','INDIA_VIX']
export default function GlobalMarketWorkspace({onOpenAlpha,onOpenEvents}:{onOpenAlpha:()=>void;onOpenEvents:()=>void}){
 const [mode,setMode]=useState<'receipt'|'archive'>('receipt')
 const [status,setStatus]=useState<Status|null>(null),[config,setConfig]=useState<Config|null>(null)
 const [reviewed,setReviewed]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('')
 useEffect(()=>{let active=true,running=false
 const poll=async()=>{if(running)return;running=true;try{const next=await marketApi<Status>(base);if(active){setStatus(next);setConfig(prev=>prev||next.config)}}catch(e){if(active)setError(readableError(e))}finally{running=false}}
 void poll();const timer=window.setInterval(()=>void poll(),5000);return()=>{active=false;window.clearInterval(timer)}
 },[])
 const patch=(value:Partial<Config>)=>{setConfig(c=>c?{...c,...value}:c);setReviewed(false)}
 const update=(i:number,key:keyof Mapping,value:string)=>{if(config)patch({mappings:config.mappings.map((r,n)=>n===i?{...r,[key]:value}:r)})}
 const changed=!!config&&!!status&&JSON.stringify(config)!==JSON.stringify(status.config)
 const save=async()=>{if(!config||!reviewed||busy)return;setBusy(true);setError('');setNotice('')
 try{const next=await marketPost<Status>(base,{...config,confirm_reviewed:true});setStatus(next);setConfig(next.config);setNotice('Collection settings saved locally.');setReviewed(false)}catch(e){setError(readableError(e))}finally{setBusy(false)}}
 const sync=async()=>{if(busy||!reviewed||changed)return;setBusy(true);setError('');setNotice('')
 try{await marketPost(base+'/sync',{confirm_reviewed:true});setNotice('Read-only synchronization requested. Source states refresh below.');setReviewed(false)}catch(e){setError(readableError(e))}finally{setBusy(false)}}
 return <section className="bci-panel" aria-label="Global markets and positioning"><header><div><small>CROSS-MARKET · RECEIPT-TIMED EVIDENCE</small><h3>Global markets & positioning</h3><p>International factors, FX, yields, domestic strength, options and participant reports. Research and collection remain independent of execution.</p></div><div className="bci-actions"><button className="ws-button" onClick={onOpenEvents}>Economic Events →</button><button className="ws-button primary" onClick={onOpenAlpha}>Alpha Research →</button></div></header>
 <div className="bci-grid"><div className="bci-stat"><span>FRED credential</span><strong>{status?.fred_key_configured?'Configured':status?'Not configured':'—'}</strong><small>Daily macro / equity data</small></div><div className="bci-stat"><span>Twelve Data credential</span><strong>{status?.twelve_key_configured?'Configured':status?'Not configured':'—'}</strong><small>Reviewed symbol mappings only</small></div><div className="bci-stat"><span>Automatic collection</span><strong>{status?.sync_running?'Synchronizing':status?.config.enabled?'Enabled':'Disabled'}</strong><small>{status?.last_sync_utc||'No sync receipt yet'}</small></div></div>
 <MarketContextPanel mode={mode} onMode={setMode}/>
 <ParticipantInbox/>
 <details className="bci-note"><summary><strong>Configure automatic source collection</strong></summary><p>Set FRED_API_KEY and TWELVE_DATA_API_KEY in the existing local .env file, then restart QuantLab when recording can safely stop. No key is exposed in this page. FRED uses fixed series IDs; Twelve Data requires exact provider symbol and exchange and suitable permissions. Current data is saved with its actual local receipt, never backdated.</p>
 {status?.configuration_error&&<p role="alert">{status.configuration_error}</p>}
 {config&&<><div className="bci-actions"><label><input type="checkbox" checked={config.enabled} disabled={busy} onChange={e=>patch({enabled:e.target.checked})}/> Collect automatically while QuantLab runs</label><label><input type="checkbox" checked={config.fred} disabled={busy} onChange={e=>patch({fred:e.target.checked})}/> FRED daily factors and release calendar</label><label><input type="checkbox" checked={config.news} disabled={busy} onChange={e=>patch({news:e.target.checked})}/> Official RBI and Federal Reserve announcements</label></div>
 <p>FRED fixed series: {Object.entries(status?.fred_catalog||{}).map(([k,v])=>k+' = '+v).join(' · ')}</p>
 <div className="bci-scroll"><table aria-label="International instrument mappings"><thead><tr><th>Factor</th><th>Provider symbol</th><th>Exact exchange</th><th></th></tr></thead><tbody>{config.mappings.map((r,i)=><tr key={i}><td><select aria-label={'Factor '+(i+1)} value={r.factor} disabled={busy} onChange={e=>update(i,'factor',e.target.value)}><option value="">Choose factor</option>{factors.filter(f=>!config.fred||!(f in (status?.fred_catalog||{}))||f===r.factor).map(f=><option key={f} value={f}>{f}</option>)}</select></td><td><input aria-label={'Provider symbol '+(i+1)} value={r.symbol} disabled={busy} onChange={e=>update(i,'symbol',e.target.value)}/></td><td><input aria-label={'Provider exchange '+(i+1)} value={r.exchange} disabled={busy} onChange={e=>update(i,'exchange',e.target.value)}/></td><td><button className="ws-button" disabled={busy} onClick={()=>patch({mappings:config.mappings.filter((_,n)=>n!==i)})}>Remove</button></td></tr>)}</tbody></table></div>
 <button className="ws-button" disabled={busy||config.mappings.length>=(status?.max_mappings||8)} onClick={()=>patch({mappings:[...config.mappings,{factor:'',symbol:'',exchange:''}]})}>Add reviewed instrument</button>
 <p>Intraday bars: bounded polling during India's pre-open and session. Daily factors and official news are polled less frequently. Provider delays and unavailable instruments are shown explicitly.</p>
 <label><input type="checkbox" checked={reviewed} disabled={busy} onChange={e=>setReviewed(e.target.checked)}/> I authorize these read-only requests and have reviewed provider access, data terms and instrument identities.</label>
 <div className="bci-actions"><button className="ws-button primary" disabled={busy||!reviewed} onClick={()=>void save()}>Save collection settings</button><button className="ws-button" disabled={busy||!reviewed||changed||status?.sync_running} onClick={()=>void sync()}>Synchronize configured sources now</button></div></>}
 </details>
 {notice&&<p role="status">{notice}</p>}{error&&<p role="alert" className="bci-error">{error}</p>}
 <details className="bci-note"><summary>Automatic source status & diagnostics</summary><p>{status?.note}</p><div className="bci-scroll"><table aria-label="Automatic market source state"><thead><tr><th>Source</th><th>State</th><th>Last attempt UTC</th><th>Rows</th><th>Detail</th></tr></thead><tbody>{Object.entries(status?.sources||{}).map(([k,r])=><tr key={k}><td>{k}</td><td>{r.state}</td><td>{r.attempt_utc}</td><td>{r.new_rows??'—'}</td><td>{r.detail}</td></tr>)}</tbody></table></div></details></section>
}
