import {useState} from 'react'
import './trading-cockpit.css'
export type Candle = {timestamp_utc:string;session_ist:string;open:number;high:number;low:number;close:number;volume:number;ema9:number|null;ema21:number|null}
const fmt=(v:number|null|undefined,digits=2)=>v===null||v===undefined?'—':v.toLocaleString('en-IN',{maximumFractionDigits:digits})
export default function CandleChart({rows}:{rows:Candle[]}){
  const [hover,setHover]=useState<number|null>(null)
  const data=rows.slice(-150)
  if(!data.length)return <p className="tc-muted">No original one-minute data available.</p>
  const values=data.flatMap(c=>[c.low,c.high,c.ema9??c.close,c.ema21??c.close])
  const min=Math.min(...values),max=Math.max(...values),range=Math.max(0.001,max-min)
  const height=310, width=970, left=54,right=16,top=18,bottom=27,chartW=width-left-right,chartH=height-top-bottom
  const x=(i:number)=>left+(i+.5)*chartW/data.length
  const y=(p:number)=>top+(max-p)/range*chartH
  const line=(key:'ema9'|'ema21')=>{
    let started=false
    return data.map((row,i)=>{
      const value=row[key]
      if(value===null){started=false;return ''}
      const command=started?'L':'M'
      started=true
      return `${command}${x(i).toFixed(1)},${y(value).toFixed(1)}`
    }).join(' ')
  }
  const step=chartW/data.length
  const selected=hover===null?data[data.length-1]:data[hover]
  return <div className="tc-chart">
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Observed one-minute OHLC candles with 9 and 21-period EMA" onMouseMove={event=>{
      const rect=event.currentTarget.getBoundingClientRect()
      const px=(event.clientX-rect.left)/rect.width*width
      setHover(Math.max(0,Math.min(data.length-1,Math.floor((px-left)/chartW*data.length))))
    }} onMouseLeave={()=>setHover(null)}>
      {[0,.25,.5,.75,1].map(f=><g key={f}><line x1={left} y1={top+f*chartH} x2={width-right} y2={top+f*chartH} stroke="#28364c" strokeDasharray="3 5"/><text x="4" y={top+f*chartH+4} fontSize="12" fill="#9eafc4">{fmt(max-f*range,0)}</text></g>)}
      {data.map((r,i)=><g key={r.timestamp_utc} stroke={r.close>=r.open?'#2ed3a2':'#f37b86'} fill={r.close>=r.open?'#2ed3a2':'#f37b86'}>
        <line x1={x(i)} x2={x(i)} y1={y(r.high)} y2={y(r.low)}/>
        <rect x={x(i)-Math.max(.7,step*.32)} y={Math.min(y(r.open),y(r.close))} width={Math.max(1.4,step*.64)} height={Math.max(1,Math.abs(y(r.open)-y(r.close)))}/>
      </g>)}
      <path d={line('ema9')} fill="none" stroke="#e9ae57" strokeWidth="1.8"/>
      <path d={line('ema21')} fill="none" stroke="#72b3fa" strokeWidth="1.8"/>
      {hover!==null&&<line x1={x(hover)} x2={x(hover)} y1={top} y2={top+chartH} stroke="#dce9f8" opacity=".65" strokeDasharray="3 5"/>}
      <text x={left} y={height-5} fill="#99aabd" fontSize="12">{data[0].session_ist}</text>
      <text x={width-110} y={height-5} fill="#99aabd" fontSize="12">{new Date(data[data.length-1].timestamp_utc).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit'})} IST</text>
    </svg>
    <div className="tc-chart-caption">{new Date(selected.timestamp_utc).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'})} · O {fmt(selected.open)} · H {fmt(selected.high)} · L {fmt(selected.low)} · C {fmt(selected.close)} · Vol {fmt(selected.volume,0)}</div>
  </div>
}

