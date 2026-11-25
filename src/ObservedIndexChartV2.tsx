import {useMemo,useState} from 'react'
import ResearchPlot,{type ResearchPlotData} from './ResearchPlots'
import './quantlab-v2.css'
type ObservedClose={timestamp_utc:string;close:number}
type Point=ObservedClose&{time:number;index:number}
function ema(points:Point[],period:number):(number|null)[]{
  const result:(number|null)[]=[]
  const alpha=2/(period+1)
  let previous:number|null=null,streak=0,buffer=0
  for(let i=0;i<points.length;i++){
    if(i===0||points[i].time-points[i-1].time>90000||
      points[i].time-points[i-1].time<30000){
      previous=null;streak=0;buffer=0
    }
    buffer+=points[i].close;streak++
    if(streak<period){result.push(null);continue}
    if(previous===null){previous=buffer/period;result.push(previous);continue}
    previous=alpha*points[i].close+(1-alpha)*previous
    result.push(previous)
  }
  return result
}
const time=(value:string|number)=>new Date(value).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',hour12:false})
export default function ObservedIndexChartV2({rows,sourceWarning='',instrument='BANKNIFTY'}:{
  rows:ObservedClose[];sourceWarning?:string;instrument?:string
}){
  const [length,setLength]=useState<30|60|150>(60)
  const plot=useMemo<ResearchPlotData>(()=>{
    const points=rows.filter(r=>Number.isFinite(r.close)&&Number.isFinite(Date.parse(r.timestamp_utc))).map((r,i)=>({...r,time:Date.parse(r.timestamp_utc),index:i})).sort((a,b)=>a.time-b.time)
    const fast=ema(points,9),slow=ema(points,21),data=points.slice(-length)
    return {kind:'line2d',title:instrument+' · observed completed minute closes',x_label:'Trading time (IST)',y_label:'Index level (points)',x:data.map(p=>p.timestamp_utc),break_before:data.map((p,i)=>i>0&&(p.time-data[i-1].time>90000||p.time-data[i-1].time<30000)),traces:[
      {name:'Observed close',color:'#f5c542',y:data.map(p=>p.close)},
      {name:'EMA 9',color:'#ff8192',y:fast.slice(-length)},
      {name:'EMA 21',color:'#70e1ad',y:slow.slice(-length)}
    ]}
  },[rows,length,instrument])
  return <section className="v2-observed-chart" aria-label="Original observed BANKNIFTY close chart">
    <header className="v2-observed-head"><div><strong>Observed {instrument} closes</strong><p>Dhan · completed 1-minute closes · index points · IST</p></div>
      <label>Visible observations <select value={length} onChange={e=>setLength(Number(e.target.value) as typeof length)}><option value={30}>Latest 30</option><option value={60}>Latest 60</option><option value={150}>Latest 150</option></select></label>
    </header>
    {(plot.x?.length||0)<2?<div className="v2-chart-empty">No complete observed one-minute index series is currently available. QuantLab will not draw a synthetic live chart.</div>:<ResearchPlot plot={plot} provenance="observed-index" formatX={time} formatY={v=>v.toLocaleString('en-IN',{maximumFractionDigits:2})}/>}
    {sourceWarning&&<p className="v2-chart-warning">{sourceWarning}</p>}
    <p className="v2-chart-source">EMA warmup uses all available received minute closes before slicing the visible range. Source gaps break lines and reset the EMA. This is not observed OHLC, volume or option execution evidence.</p>
  </section>
}
