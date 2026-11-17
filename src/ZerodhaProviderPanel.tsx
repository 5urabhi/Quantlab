import {useCallback,useEffect,useState} from 'react'
import {AlertTriangle,CheckCircle2,ExternalLink,KeyRound,RefreshCw,ShieldCheck} from 'lucide-react'

type KiteStatus={
  provider:string;api_key_configured:boolean;api_secret_configured:boolean;
  token_present:boolean;login_required:boolean;master_available:boolean;master_current:boolean;
  master_instruments:number;master_generated_utc?:string|null;
  callback_url:string;historical_entitlement_verified:boolean;note:string
}
type Job={id:string;status:string;stage?:string;percent?:number;error?:string;
  result?:{authenticated?:boolean;ready?:boolean;instruments?:number;note?:string}}
const request=async<T,>(suffix:string,init?:RequestInit):Promise<T>=>{
  const r=await fetch('/api/data-manager/zerodha'+suffix,init)
  if(!r.ok){let msg='Zerodha source not available'
    try{const a=await r.json() as {detail?:string};if(a.detail)msg=a.detail}catch{/* no payload */}
    throw new Error(msg)}
  return r.json() as Promise<T>
}
export default function ZerodhaProviderPanel({onSourceChange}:{onSourceChange?:()=>void}){
  const [status,setStatus]=useState<KiteStatus|null>(null)
  const [apiKey,setApiKey]=useState('')
  const [apiSecret,setApiSecret]=useState('')
  const [job,setJob]=useState<Job|null>(null)
  const [error,setError]=useState('')
  const [message,setMessage]=useState('')
  const [revision,setRevision]=useState(0)
  const [busy,setBusy]=useState(false)
  const reload=useCallback(async()=>{
    const x=await request<KiteStatus>('/status');setStatus(x)
  },[])
  useEffect(()=>{
    let alive=true
    void reload().catch(e=>{if(alive)setError(String(e))})
    return()=>{alive=false}
  },[reload,revision])
  useEffect(()=>{
    if(!job||!['queued','running'].includes(job.status))return
    let mounted=true
    const interval=window.setTimeout(()=>{
      void fetch('/api/jobs/'+encodeURIComponent(job.id))
        .then(async r=>{if(!r.ok)throw new Error('Job status unavailable');return r.json() as Promise<Job>})
        .then(x=>{
          if(!mounted)return
          setJob(x)
          if(x.status==='complete'){
            setMessage(x.result?.authenticated?'Read-only Kite profile verified.':
              x.result?.ready?'Kite security-token master refreshed.':
              'Zerodha validation completed.')
            setRevision(n=>n+1)
            onSourceChange?.()
          }else if(x.status==='error'||x.status==='cancelled'){
            setError(x.error||'Kite read-only operation did not complete.')
          }
        }).catch(e=>{if(mounted)setError(String(e))})
    },1500)
    return()=>{mounted=false;window.clearTimeout(interval)}
  },[job,onSourceChange])
  const begin=async(suffix:'/verify'|'/refresh-master')=>{
    if(busy)return
    setBusy(true);setError('');setMessage('')
    try{
      const x=await request<{job_id:string;status:string}>(suffix,{method:'POST'})
      setJob({id:x.job_id,status:x.status})
    }catch(e){setError(e instanceof Error?e.message:String(e))}
    finally{setBusy(false)}
  }
  const configure=async()=>{
    if(busy||!apiKey||!apiSecret)return
    setBusy(true);setError('');setMessage('')
    try{
      await request('/configure',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({api_key:apiKey.trim(),api_secret:apiSecret.trim(),
          confirm_local_storage:true})
      })
      setApiKey('');setApiSecret('')
      setMessage('Kite app settings saved privately on this machine. Complete official login next.')
      setRevision(n=>n+1)
    }catch(e){setError(e instanceof Error?e.message:String(e))}
    finally{setBusy(false)}
  }
  const login=async()=>{
    if(busy)return
    // Open synchronously on click; async popups are blocked by some browsers.
    const popup=window.open('about:blank','_blank')
    setBusy(true);setError('');setMessage('')
    try{
      const response=await request<{login_url:string;callback_url:string}>('/auth/start',{method:'POST'})
      const url=new URL(response.login_url)
      if(url.protocol!=='https:'||url.hostname!=='kite.zerodha.com')
        throw new Error('Unexpected Kite sign-in destination')
      if(popup){popup.opener=null;popup.location.assign(response.login_url)}
      else window.location.assign(response.login_url)
      setMessage('Complete official Zerodha login. Return here and refresh connection status.')
    }catch(e){popup?.close();setError(e instanceof Error?e.message:String(e))}
    finally{setBusy(false)}
  }
  const running=busy||Boolean(job&&['queued','running'].includes(job.status))
  return <section className="qm-panel qm-kite" aria-label="Zerodha second market data provider">
    <div className="qm-panel-title"><h3><KeyRound size={18}/> Zerodha — second historical provider</h3>
      <span>Primary: Dhan · fallback: Zerodha Kite Connect (read-only)</span></div>
    <p className="qm-caption">When Dhan cannot supply an approved original daily-close
      window, QuantLab can try Zerodha after you opt in. It requires a current
      paid market-data-enabled Kite subscription, exact exchange security-token
      and trading-symbol matching, and agreeing Dhan close prices. It cannot
      replace official TRI, historical index membership or an expired credential.</p>
    {error&&<div role="alert" className="qm-alert"><AlertTriangle size={16}/>{error}</div>}
    {message&&<div role="status" className="qm-notice"><CheckCircle2 size={16}/>{message}</div>}
    <div className="qm-acquire-metrics">
      <div><small>Kite app credentials</small><strong className="qm-small-stat">
        {status?.api_key_configured&&status.api_secret_configured?'Configured':'Needs setup'}</strong></div>
      <div><small>Current session</small><strong className="qm-small-stat">
        {status?.token_present?'Present — verify':'Login required'}</strong></div>
      <div><small>Exchange master</small><strong className="qm-small-stat">
        {status?.master_current?'Current':status?.master_available?'Stale':'Missing'}</strong></div>
      <div><small>Mapped equity candidates</small><strong>{status?.master_instruments??0}</strong></div>
    </div>
    <p className="qm-caption">One-time setup: place <code>KITE_API_KEY</code> and <code>KITE_API_SECRET</code>
      in the local ignored <code>.env</code>, and register <code>{status?.callback_url||
      'http://127.0.0.1:8765/api/data-manager/zerodha/auth/callback'}</code>
      as the Kite app redirect URL. Do not paste your access token or secret into
      QuantLab's browser forms. Official login/2FA is required each trading day.</p>
    <div className="qm-readiness-action-row">
      <button type="button" className="ws-button primary" disabled={running||
        !status?.api_key_configured||!status?.api_secret_configured} onClick={()=>void login()}>
        <ExternalLink size={15}/> Sign in with Zerodha</button>
      <button type="button" className="ws-button secondary" disabled={running||!status?.token_present}
        onClick={()=>void begin('/verify')}><ShieldCheck size={15}/> Verify session</button>
      <button type="button" className="ws-button secondary" disabled={running||!status?.token_present}
        onClick={()=>void begin('/refresh-master')}><RefreshCw size={15}/> Refresh instrument master</button>
      <button type="button" className="ws-button secondary" disabled={running}
        onClick={()=>setRevision(n=>n+1)}><RefreshCw size={15}/> Recheck status</button>
    </div>
    {job&&['queued','running'].includes(job.status)&&<div className="qm-acquire-status" role="status">
      <RefreshCw size={15}/><div><strong>{job.stage||'Checking read-only Kite source'}</strong>
        <small>{Math.round(job.percent??0)}% · {job.id}</small></div></div>}
    <p className="qm-caption">{status?.note} The instrument list is refreshed on demand,
      not scraped by the browser. Original prices are never overwritten by a secondary provider.</p>
  </section>
}
