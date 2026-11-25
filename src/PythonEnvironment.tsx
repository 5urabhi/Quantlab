import {useEffect,useState} from 'react'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
type Profile='stdlib'|'scientific'
type Package={distribution:string;files_present:boolean}
type Environment={available:boolean;engine:string;profiles:Profile[];scientific_packages:Record<string,Package>;scientific_note:string}
type Probe={status:string;error?:string;result?:{packages:Record<string,{available:boolean;version?:string;reason?:string}>}}
export default function PythonEnvironment(){
  const [info,setInfo]=useState<Environment|null>(null)
  const [error,setError]=useState('')
  const [job,setJob]=useState('')
  const [probe,setProbe]=useState<Probe|null>(null)
  const [copied,setCopied]=useState(false)
  const command='bash run.sh python-packages install'
  const refresh=()=>{setError('');void marketApi<Environment>('/api/python-environment').then(setInfo).catch(e=>setError(readableError(e)))}
  useEffect(refresh,[])
  useEffect(()=>{
    if(!job)return
    let active=true,running=false
    const poll=async()=>{if(running)return;running=true;try{const v=await marketApi<Probe>('/api/jobs/'+job);if(active){setProbe(v);if(['complete','error','cancelled','interrupted'].includes(v.status))setJob('')}}catch(e){if(active){setError(readableError(e));setJob('')}}finally{running=false}}
    void poll();const t=window.setInterval(()=>void poll(),1000);return()=>{active=false;window.clearInterval(t)}
  },[job])
  const start=async()=>{setError('');setProbe(null);try{const v=await marketPost<{job_id:string}>('/api/python-environment/probe',{});setJob(v.job_id)}catch(e){setError(readableError(e))}}
  return <section className="ws-card" aria-label="Python environment manager">
    <h2>Python environment</h2><p className="ws-caption">Two read-only research profiles share an isolated Linux subprocess. Package updates affect only new runs. The Dhan recorder is not restarted.</p>
    <div className="ws-actions"><button type="button" className="ws-button" onClick={refresh}>Refresh package status</button><button type="button" className="ws-button primary" disabled={!info?.available||!!job} onClick={()=>void start()}>{job?'Probing imports…':'Test scientific imports'}</button></div>
    {error&&<p role="alert">{error}</p>}{probe?.error&&<p role="alert">{probe.error}</p>}
    <p>Isolation: {info?.available?'Utilities installed; kernel permission checked by execution':info?'Unavailable':'Checking'}</p>
    <p><strong>Standard library</strong> — default, smaller memory limit. <strong>Scientific</strong> — optional system-distribution libraries, read-only inside sandbox.</p>
    {info&&<div className="ws-table-scroll"><table><thead><tr><th>Python import</th><th>Ubuntu package</th><th>Files</th><th>Isolated import test</th></tr></thead><tbody>{Object.entries(info.scientific_packages||{}).map(([name,p])=><tr key={name}><td>{name}</td><td>{p.distribution}</td><td>{p.files_present?'Present':'Not detected'}</td><td>{probe?.result?.packages[name]?.available?'Pass · '+probe.result.packages[name].version:probe?.result?.packages[name]?.reason||'Not tested'}</td></tr>)}</tbody></table></div>}
    <details><summary>Install missing libraries on Ubuntu</summary><p>From your QuantLab project directory, run this helper. It detects missing approved packages and asks for local approval before installing them. The application does not execute privileged commands. Then test scientific imports; no QuantLab restart is needed.</p><pre style={{whiteSpace:'pre-wrap'}}>{command}</pre><div className="ws-actions"><button type="button" className="ws-button" onClick={()=>{void navigator.clipboard.writeText(command).then(()=>setCopied(true)).catch(()=>setError('Clipboard unavailable; copy the command manually.'))}}>{copied?'Copied':'Copy installer command'}</button><button type="button" className="ws-button" onClick={refresh}>Recheck installed packages</button></div><p>Read-only inventory: <code>bash run.sh python-packages check</code></p><p>Availability depends on your Ubuntu release and configured package repositories.</p></details>
    <p className="ws-caption">System package presence is not a successful import. The sandbox has no broker tokens, order API or network access.</p>
  </section>
}
