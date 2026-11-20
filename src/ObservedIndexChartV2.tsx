import {useMemo,useState} from 'react'
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
const n=(value:number,digits=1)=>value.toLocaleString('en-IN',
  {maximumFractionDigits:digits})
export default function ObservedIndexChartV2({rows,sourceWarning=''}:{
  rows:ObservedClose[];sourceWarning?:string
}){
  const [hover,setHover]=useState<number|null>(null)
  const [length,setLength]=useState<30|60|150>(60)
  const data=useMemo(()=>rows.filter(x=>Number.isFinite(x.close)&&
    Number.isFinite(Date.parse(x.timestamp_utc))).map((x,i)=>({
      ...x,time:Date.parse(x.timestamp_utc),index:i
    })).sort((a,b)=>a.time-b.time).slice(-length),[rows,length])
  const red=useMemo(()=>ema(data,9),[data])
  const green=useMemo(()=>ema(data,21),[data])
  const width=960,height=340,left=67,right=20,top=28,bottom=40
  const all=data.flatMap((d,i)=>[d.close,...[red[i],green[i]].filter(
    (v):v is number=>v!==null&&Number.isFinite(v))])
  const lo=Math.min(...all),hi=Math.max(...all)
  const pad=Number.isFinite(lo)?Math.max(3,(hi-lo)*.08):5
  const min=Number.isFinite(lo)?lo-pad:0,max=Number.isFinite(hi)?hi+pad:1
  const x=(i:number)=>left+(i/Math.max(1,data.length-1))*(width-left-right)
  const y=(v:number)=>top+(max-v)/(max-min)*(height-top-bottom)
  const path=(values:(number|null)[])=>{
    let started=false
    return values.map((v,i)=>{
      const gap=i>0&&(data[i].time-data[i-1].time>90000)
      if(v===null||gap){started=false}
      if(v===null)return ''
      const c=started?'L':'M';started=true
      return c+x(i).toFixed(2)+' '+y(v).toFixed(2)
    }).join(' ')
  }
  const pointPath=path(data.map(p=>p.close))
  const selected=data[hover??Math.max(0,data.length-1)]
  const time=(date:string)=>new Date(date).toLocaleString('en-IN',{
    timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit',day:'numeric',month:'short'
  })
  return <section className="v2-observed-chart" aria-label="Original observed BANKNIFTY close chart">
    <header className="v2-observed-head"><div><strong>Observed BANKNIFTY closes</strong>
      <p>Original Dhan-received completed 1-minute observations · Index points</p></div>
      <label>Visible observations <select value={length}
        onChange={event=>setLength(Number(event.target.value) as typeof length)}>
        <option value={30}>Latest 30</option><option value={60}>Latest 60</option>
        <option value={150}>Latest 150</option>
      </select></label>
    </header>
    {data.length<2?<div className="v2-chart-empty">
      No complete observed one-minute index series is currently available.
      QuantLab will not draw a synthetic live chart.</div>:
    <><svg role="img" aria-label="Original BANKNIFTY completed minute close, derived EMA 9 red and EMA 21 green"
       viewBox={'0 0 '+width+' '+height} onMouseMove={event=>{
         const box=event.currentTarget.getBoundingClientRect()
         const px=(event.clientX-box.left)/box.width*width
         setHover(Math.max(0,Math.min(data.length-1,Math.round(
           (px-left)/(width-left-right)*(data.length-1)))))
       }} onMouseLeave={()=>setHover(null)}>
      {[0,.25,.5,.75,1].map(z=><g key={z}>
        <line x1={left} x2={width-right} y1={top+z*(height-top-bottom)}
          y2={top+z*(height-top-bottom)} stroke="#28465a" strokeDasharray="4 6"/>
        <text x="4" y={top+z*(height-top-bottom)+4} fill="#a7becc" fontSize="12">
          {n(max-z*(max-min),0)}</text>
      </g>)}
      <path d={pointPath} fill="none" stroke="#7ebfff" strokeWidth="2.4"/>
      <path d={path(red)} fill="none" stroke="#ff8192" strokeWidth="2.2"/>
      <path d={path(green)} fill="none" stroke="#70e1ad" strokeWidth="2.2"/>
      {hover!==null&&<line x1={x(hover)} x2={x(hover)} y1={top}
        y2={height-bottom} stroke="#beddf1" strokeDasharray="3 5"/>}
      {selected&&<circle cx={x(hover??data.length-1)} cy={y(selected.close)}
        r="4.5" fill="#fff" stroke="#3c9fc1" strokeWidth="2"/>}
      <text x={left} y={height-8} fill="#9db8ca" fontSize="12">
        {time(data[0].timestamp_utc)+' IST'}</text>
      <text x={width-180} y={height-8} fill="#9db8ca" fontSize="12">
        {time(data[data.length-1].timestamp_utc)+' IST'}</text>
    </svg>
    <div className="v2-observed-meta">
      <span>Observed close <strong>{selected?n(selected.close,2)+' pts':'—'}</strong></span>
      <span>EMA 9 <strong className="red">{hover!==null&&red[hover]!==null?
        n(red[hover] as number,2):red.at(-1)!==null&&red.length?
        n(red.at(-1) as number,2):'—'}</strong></span>
      <span>EMA 21 <strong className="green">{hover!==null&&green[hover]!==null?
        n(green[hover] as number,2):green.at(-1)!==null&&green.length?
        n(green.at(-1) as number,2):'—'}</strong></span>
      <span>{selected?time(selected.timestamp_utc)+' IST':'—'}</span>
    </div></>}
    {sourceWarning&&<p className="v2-chart-warning">{sourceWarning}</p>}
    <p className="v2-chart-source">EMA curves are calculated only from contiguous received
      minute closes and reset after source gaps. This is not historical OHLC,
      volume, or option execution evidence.</p>
  </section>
}
