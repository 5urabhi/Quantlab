import ResearchPlot from './ResearchPlots'
import './trading-cockpit.css'
export type Candle = {timestamp_utc:string;session_ist:string;open:number;high:number;low:number;close:number;volume:number;ema9:number|null;ema21:number|null}
export default function CandleChart({rows}:{rows:Candle[]}){
  const data=rows.slice(-150)
  if(!data.length)return <p className="tc-muted">No original one-minute data available.</p>
  return <div className="tc-chart"><ResearchPlot plot={{kind:'line2d',title:'Observed one-minute OHLC candles with 9 and 21-period EMA',x_label:'Bar start time (IST)',y_label:'Index level (points)',x:data.map(r=>r.timestamp_utc),candles:data.map(r=>[r.open,r.high,r.low,r.close].every(Number.isFinite)&&r.low<=Math.min(r.open,r.close)&&r.high>=Math.max(r.open,r.close)?{open:r.open,high:r.high,low:r.low,close:r.close}:null),traces:[{name:'EMA 9',color:'#f5c542',y:data.map(r=>r.ema9)},{name:'EMA 21',color:'#78a8ff',y:data.map(r=>r.ema21)}],break_before:data.map((r,i)=>i>0&&Date.parse(r.timestamp_utc)-Date.parse(data[i-1].timestamp_utc)!==60000)}} provenance="historical" formatX={x=>new Date(x).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',hour12:false})}/><p className="tc-muted">Original candle fields only; missing intervals are not filled. No volume inference.</p></div>
}
