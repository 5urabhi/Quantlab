import {useEffect,useState} from 'react'
import {marketApi,readableError} from './tradingCockpitApi'
import ResearchPlot,{type ResearchPlotData} from './ResearchPlots'

type Monitor={id:string;name:string;kind:string;revision:number;source:string;enabled:boolean;state:string;last_utc:string|null;message:string|null;output:{signal?:string;plot?:ResearchPlotData;ranking?:{rank:number;key:string;score:number;row:(string|number|null)[]}[];ranking_columns?:string[];ranking_note?:string;warning?:string}|null}
export default function LivePythonResults({mode}:{mode:'index'|'options'}){
  const [monitors,setMonitors]=useState<Monitor[]>([])
  const [error,setError]=useState('')
  useEffect(()=>{
    let alive=true,reading=false
    const refresh=async()=>{if(reading||document.hidden)return;reading=true
      try{const data=await marketApi<{monitors:Monitor[]}>('/api/script-monitors')
        if(alive){setMonitors(data.monitors);setError('')}}
      catch(e){if(alive)setError(readableError(e))}
      finally{reading=false}}
    void refresh()
    const timer=window.setInterval(()=>void refresh(),5000)
    return()=>{alive=false;window.clearInterval(timer)}
  },[])
  const visible=monitors.filter(m=>mode==='options'?m.source==='option_chain':m.source==='index_minutes'||m.source==='chain_spot_receipts')
  return <section className="ws-card" aria-label="Custom Python research output">
    <h3>Custom Python research</h3>
    <p className="ws-caption">Calculations on locally recorded observations. No extra broker subscription or orders. Source time is shown separately from the latest calculation.</p>
    {error&&<p role="status">Monitor status unavailable: {error}</p>}
    {!visible.length&&<p className="ws-caption">Configure a saved script in Strategies → Running Python to show its research results here.</p>}
    {visible.map(m=><details key={m.id}><summary>{m.name} · revision {m.revision} · {m.enabled?m.state:'paused'}{m.output?.signal?' · last calculated '+m.output.signal:''}</summary>
      <p>Source: {m.source.replaceAll('_',' ')} · {m.last_utc||'No completed calculation'} · {m.message||'Read-only research'}</p>
      <p className="ws-caption">{m.output?.warning||'Custom research; the last result is not a verified current trade signal.'}</p>
      {m.output?.ranking&&<div className="ws-table-scroll"><p>{m.output.ranking_note}</p><table><thead><tr><th>Rank</th><th>Score</th>{m.output.ranking_columns?.map((c,i)=><th key={i}>{c}</th>)}</tr></thead><tbody>{m.output.ranking.map(r=><tr key={r.rank}><td>{r.rank}</td><td>{r.score.toPrecision(5)}</td>{r.row.map((v,i)=><td key={i}>{v??'Missing'}</td>)}</tr>)}</tbody></table></div>}
      {m.output?.plot&&<ResearchPlot plot={m.output.plot} provenance="custom-python-snapshot" allowApply={false}/>}
    </details>)}
  </section>
}
