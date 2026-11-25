import {useEffect,useState} from 'react'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
import ResearchPlot,{type ResearchPlotData} from './ResearchPlots'
type Source='index_minutes'|'option_chain'|'chain_spot_receipts'
type Profile='stdlib'|'scientific'
type Item={id:string;name:string;kind:string;revision:number}
type Output={signal?:string;plot?:ResearchPlotData;ranking?:{rank:number;key:string;score:number;row:(string|number|null)[]}[];ranking_columns?:string[];ranking_note?:string;warning?:string}
type Monitor={id:string;name:string;kind:string;revision:number;source:Source;profile:Profile;enabled:boolean;state:string;last_utc:string|null;message:string|null;output:Output|null}
const names:Record<Source,string>={index_minutes:'Recorded completed index minutes',option_chain:'Nearest saved option chain',chain_spot_receipts:'Recorded chain spot receipts'}
export default function PythonMonitors({onEdit,initialKind}:{onEdit:(id?:string)=>void;initialKind?:string}){
  const [scripts,setScripts]=useState<Item[]>([])
  const [monitors,setMonitors]=useState<Monitor[]>([])
  const [selected,setSelected]=useState('')
  const [source,setSource]=useState<Source>('index_minutes')
  const [profile,setProfile]=useState<Profile>('stdlib')
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [expanded,setExpanded]=useState('')
  const [consent,setConsent]=useState(false)
  const refresh=async()=>{try{const [s,m]=await Promise.all([marketApi<{scripts:Item[]}>('/api/user-scripts'),marketApi<{monitors:Monitor[]}>('/api/script-monitors')]);setScripts(s.scripts);setMonitors(m.monitors);setError('')}catch(e){setError(readableError(e))}}
  useEffect(()=>{void refresh();const timer=window.setInterval(()=>{if(!document.hidden)void refresh()},5000);return()=>window.clearInterval(timer)},[])
  const item=scripts.find(s=>s.id===selected)
  const options:Source[]=item?.kind==='strategy'?['index_minutes']:item?.kind==='scanner'?['option_chain']:['index_minutes','option_chain','chain_spot_receipts']
  useEffect(()=>{if(!options.includes(source))setSource(options[0])},[selected,source])
  const action=async(fn:()=>Promise<unknown>)=>{setBusy(true);setError('');try{await fn();await refresh()}catch(e){setError(readableError(e))}finally{setBusy(false)}}
  const register=()=>{if(!item||!consent)return;void action(()=>marketPost('/api/script-monitors',{script_id:item.id,revision:item.revision,source,profile,confirm_readonly:true}))}
  const list=initialKind?scripts.filter(s=>s.kind===initialKind):scripts
  return <section className="ws-card" aria-label={initialKind?'Custom '+initialKind+' library':'Running Python monitors'}>
    <h2>{initialKind==='model'?'Custom mathematical models':initialKind==='scanner'?'Custom option scanners':'Running Python monitors'}</h2>
    <p className="ws-caption">Saved scripts are editable without restarting QuantLab. Pin one revision to a new recorded source. A single bounded worker updates results on new observations only; no extra Dhan connection or broker order.</p>
    <button type="button" className="ws-button primary" onClick={()=>onEdit()}>Open My Scripts</button>
    {initialKind&&<div className="ws-dataset-manage-list">{list.map(s=><div className="ws-dataset-manage-row" key={s.id}><div><strong>{s.name}</strong><small>Revision {s.revision} · custom research, not a built-in validated model</small></div><button className="ws-button" type="button" onClick={()=>onEdit(s.id)}>Edit or run</button></div>)}{!list.length&&<p>No saved {initialKind} scripts. Create one in My Scripts and choose its category.</p>}</div>}
    <div className="ql-monitor-form"><label>Saved revision<select aria-label="Monitor saved script" value={selected} onChange={e=>setSelected(e.target.value)}><option value="">Choose a saved script</option>{list.map(s=><option key={s.id} value={s.id}>{s.name} · v{s.revision} · {s.kind}</option>)}</select></label><label>Source<select value={source} onChange={e=>setSource(e.target.value as Source)}>{options.map(s=><option value={s} key={s}>{names[s]}</option>)}</select></label><label>Python profile<select value={profile} onChange={e=>setProfile(e.target.value as Profile)}><option value="stdlib">Standard library</option><option value="scientific">Scientific packages</option></select></label><label className="ql-monitor-consent"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/> Run this saved revision repeatedly in the read-only sandbox</label><button type="button" className="ws-button primary" disabled={busy||!item||!consent} onClick={register}>Start research monitor</button></div>
    {error&&<p role="alert">{error}</p>}
    <p className="ws-caption">Only fresh regular-session saved observations are accepted. REST spot receipts are irregular samples, not live OHLC. Monitors pause on server restart and never automatically enter trades.</p>
    {monitors.filter(m=>!initialKind||m.kind===initialKind).map(m=><article className="ql-monitor-row" key={m.id}>
      <div className="ql-monitor-head"><div><strong>{m.name} · v{m.revision}</strong><small>{names[m.source]} · {m.profile} · {m.state.replaceAll('_',' ')}</small></div><div className="ws-actions">
        <button type="button" className="ws-button" disabled={busy||(!m.enabled&&!consent)} onClick={()=>void action(()=>marketPost('/api/script-monitors/'+m.id,{enabled:!m.enabled,confirm_readonly:consent}))}>{m.enabled?'Pause':'Resume'}</button>
        <button type="button" className="ws-button" onClick={()=>setExpanded(expanded===m.id?'':m.id)}>{expanded===m.id?'Hide result':'Inspect result'}</button>
        <button type="button" className="ws-button" disabled={m.enabled||busy} onClick={()=>{if(window.confirm('Remove this paused monitor and its latest output? Saved script revisions are retained.'))void action(()=>marketApi('/api/script-monitors/'+m.id,{method:'DELETE'}))}}>Remove</button>
      </div></div><p className="ws-caption">Source observation: {m.last_utc||'None yet'} · {m.message||'Read-only research'}</p>
      {m.output?.signal&&<p><strong>Last custom signal: {m.output.signal}</strong> · {m.state==='complete'?'Last completed calculation':'Not current'} · not a trade instruction</p>}
      {expanded===m.id&&m.output&&<>{m.output.warning&&<p>{m.output.warning}</p>}{m.output.ranking&&<div className="ws-table-scroll"><p>{m.output.ranking_note}</p><table><thead><tr><th>Rank</th><th>Score</th>{m.output.ranking_columns?.map(c=><th key={c}>{c}</th>)}</tr></thead><tbody>{m.output.ranking.map(r=><tr key={r.rank}><td>{r.rank}</td><td>{r.score.toPrecision(5)}</td>{r.row.map((v,i)=><td key={i}>{v??'Missing'}</td>)}</tr>)}</tbody></table></div>}{m.output.plot&&<ResearchPlot plot={m.output.plot} provenance="custom-python-snapshot" allowApply={false}/>}</>}
    </article>)}
    {!monitors.length&&<p>No configured research monitors.</p>}
  </section>
}
