import {useMemo,useState} from 'react'
import type {ResearchPlotData} from './ResearchPlots'
import IndicatorChart from './IndicatorChart'
import './quantlab-v2.css'
type ObservedClose={timestamp_utc:string;close:number;open?:number;high?:number;low?:number}
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
export default function ObservedIndexChartV2({rows,sourceWarning='',instrument='BANKNIFTY',compact=false,repaired=false}:{
  rows:ObservedClose[];sourceWarning?:string;instrument?:string;compact?:boolean;repaired?:boolean
}){
  const [length,setLength]=useState<30|60|150>(60)
  const [mode,setMode]=useState<'close'|'candle'>('close')
  const hasOhlc=rows.some(r=>typeof r.open==='number'&&typeof r.high==='number'&&typeof r.low==='number'&&[r.open,r.high,r.low,r.close].every(Number.isFinite)&&r.high>=Math.max(r.open,r.close)&&r.low<=Math.min(r.open,r.close))
  const candleMode=mode==='candle'&&hasOhlc
  const plot=useMemo<ResearchPlotData>(()=>{
    const points=rows.filter(r=>Number.isFinite(r.close)&&Number.isFinite(Date.parse(r.timestamp_utc))).map((r,i)=>({...r,time:Date.parse(r.timestamp_utc),index:i})).sort((a,b)=>a.time-b.time)
    const fast=ema(points,9),slow=ema(points,21),data=points.slice(-length)
    return {kind:'line2d',title:instrument+(repaired?' · original session candles (display only)':candleMode?' · observed tick-derived minute OHLC':' · observed completed minute closes'),x_label:'Trading time (IST)',y_label:'Index level (points)',x:data.map(p=>p.timestamp_utc),candles:candleMode?data.map(p=>typeof p.open==='number'&&typeof p.high==='number'&&typeof p.low==='number'&&[p.open,p.high,p.low,p.close].every(Number.isFinite)&&p.high>=Math.max(p.open,p.close)&&p.low<=Math.min(p.open,p.close)?{open:p.open,high:p.high,low:p.low,close:p.close}:null):undefined,break_before:data.map((p,i)=>i>0&&(p.time-data[i-1].time>90000||p.time-data[i-1].time<30000)),traces:[
      ...(!candleMode?[{name:'Observed close',color:'#f5c542',y:data.map(p=>p.close)}]:[]),
      {name:'EMA 9',color:'#ff8192',y:fast.slice(-length)},
      {name:'EMA 21',color:'#70e1ad',y:slow.slice(-length)}
    ]}
  },[rows,length,instrument,candleMode,repaired])
  return <section className={'v2-observed-chart'+(compact?' v2-observed-compact':'')} aria-label="Original observed BANKNIFTY close chart">
    <header className="v2-observed-head"><div><strong>Observed {instrument} closes</strong><p>{repaired?'Original historical + recorded minute candles · display only':'Dhan · completed 1-minute closes'} · index points · IST</p></div>
      <div className="ws-actions"><label>Chart type <select aria-label="Index chart type" value={candleMode?'candle':'close'} onChange={e=>setMode(e.target.value as typeof mode)}><option value="close">Observed close</option><option value="candle" disabled={!hasOhlc}>Observed OHLC candles</option></select></label><label>Visible observations <select value={length} onChange={e=>setLength(Number(e.target.value) as typeof length)}><option value={30}>Latest 30</option><option value={60}>Latest 60</option><option value={150}>Latest 150</option></select></label></div>
    </header>
    {(plot.x?.length||0)<2?<div className="v2-chart-empty">No complete observed one-minute index series is currently available. QuantLab will not draw a synthetic live chart.</div>:<IndicatorChart compact={compact} source="index_minutes" enabled={instrument==='BANKNIFTY'&&!repaired} rows={rows.filter(r=>Number.isFinite(r.close)&&Number.isFinite(Date.parse(r.timestamp_utc))).slice().sort((a,b)=>Date.parse(a.timestamp_utc)-Date.parse(b.timestamp_utc)).map(r=>[r.timestamp_utc,r.open,r.high,r.low,r.close])} plot={plot} provenance={repaired?"repaired-index-display":candleMode?"observed-index-ohlc":"observed-index"}/>}
    {sourceWarning&&<p className="v2-chart-warning">{sourceWarning}</p>}
    <details className="v2-chart-source"><summary>Chart methodology &amp; source</summary><p>EMA warmup uses all available received minute closes before slicing the visible range. Source gaps break lines and reset the EMA. Candles use only genuine source OHLC fields when present. No synthetic open/high/low, authenticated traded volume or option execution evidence.</p></details>
  </section>
}
