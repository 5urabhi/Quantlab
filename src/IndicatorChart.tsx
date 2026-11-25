import {useEffect,useMemo,useState} from 'react'
import {marketApi,readableError} from './tradingCockpitApi'
import ResearchPlot,{type ResearchPlotData} from './ResearchPlots'
import {alignIndicator,type AlignedMonitor,type Source,type SourceRow} from './indicatorAlignment.mjs'

const formatTime=(x:string|number)=>new Date(x).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false})
export default function IndicatorChart({source,expiry=null,rows,plot,provenance,enabled=true}:{source:Source;expiry?:string|null;rows:SourceRow[];plot:ResearchPlotData;provenance:string;enabled?:boolean}){
  const [overlays,setOverlays]=useState<AlignedMonitor[]>([])
  const [selected,setSelected]=useState<string[]>([])
  const [error,setError]=useState('')
  const [now,setNow]=useState(Date.now)
  useEffect(()=>{
    if(!enabled){setOverlays([]);return}
    let alive=true,reading=false
    const refresh=async()=>{if(reading||document.hidden)return;reading=true
      try{const v=await marketApi<{overlays:AlignedMonitor[]}>('/api/script-monitor-overlays?source='+source)
        if(alive){setOverlays(v.overlays);setNow(Date.now());setError('')}}
      catch(e){if(alive){setOverlays([]);setError(readableError(e))}}finally{reading=false}}
    void refresh();const timer=window.setInterval(()=>{setNow(Date.now());void refresh()},5000)
    return()=>{alive=false;window.clearInterval(timer)}
  },[source,enabled])
  const available=useMemo(()=>overlays.flatMap(o=>{
    const age=(now-Date.parse(o.last_utc))/1000
    if(!Number.isFinite(age)||age<(source==='index_minutes'?60:0)||age>(source==='index_minutes'?150:120))return []
    const traces=alignIndicator(o,source,expiry,rows,plot.x||[])
    return traces?[{...o,traces,sameUnits:o.plot.y_label===plot.y_label}]:[]
  }),[overlays,source,expiry,rows,plot.x,plot.y_label,now])
  const applied=available.filter(o=>selected.includes(o.id))
  const merged={...plot,traces:[...(plot.traces||[]),...applied.filter(o=>o.sameUnits).flatMap(o=>o.traces)]}
  const group='custom-indicators:'+source
  return <div className="ql-indicator-chart">
    {enabled&&<details className="ql-indicator-controls"><summary>Python indicators {applied.length>0?'· '+applied.length+' applied':''}</summary>
      <p className="ws-caption">Select a running indicator from Strategies → Running Python. Matching units overlay this chart; different units receive their own aligned panel. Only identical source values and the latest matching observation are allowed.</p>
      {error&&<p role="status">Indicator status unavailable: {error}</p>}
      {!available.length&&<p className="ws-caption">No fresh, exactly aligned indicator calculation is available. Older results are not drawn as current data.</p>}
      {available.map(o=><label key={o.id}><input type="checkbox" checked={selected.includes(o.id)} onChange={e=>setSelected(v=>e.target.checked?[...v,o.id]:v.filter(x=>x!==o.id))}/>{o.name} · v{o.revision} · {o.sameUnits?'Overlay':'Companion panel'} · {o.plot.y_label}</label>)}
      {selected.some(id=>!available.some(o=>o.id===id))&&<p className="ws-caption">A selected indicator is paused, stale or awaiting a matching source update.</p>}
    </details>}
    <ResearchPlot plot={merged} provenance={provenance} formatX={formatTime} syncGroup={group}/>
    {applied.filter(o=>!o.sameUnits).map(o=><ResearchPlot key={o.id} plot={{...o.plot,x:plot.x,traces:o.traces,break_before:plot.break_before}} provenance="custom-python-snapshot" allowApply={false} formatX={formatTime} syncGroup={group}/>)}
    {!!applied.length&&<p className="ws-caption">Custom traces are research calculations, not verified predictive signals or orders. No missing values are filled.</p>}
  </div>
}
