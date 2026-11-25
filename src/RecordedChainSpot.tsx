import {useEffect,useState} from 'react'
import ResearchPlot from './ResearchPlots'
import {marketApi,readableError} from './tradingCockpitApi'
type Data={rows:{timestamp_utc:string;spot:number}[];expiry:string|null;last_utc:string|null;source:string}
export default function RecordedChainSpot(){
  const [data,setData]=useState<Data|null>(null)
  const [error,setError]=useState('')
  useEffect(()=>{let active=true,busy=false;const load=async()=>{if(busy)return;busy=true;try{const v=await marketApi<Data>('/api/trading-cockpit/recorded-chain-spot');if(active){setData(v);setError('')}}catch(e){if(active)setError(readableError(e))}finally{busy=false}};void load();const timer=window.setInterval(()=>void load(),10000);return()=>{active=false;window.clearInterval(timer)}},[])
  return <section className="v2-observed-chart" aria-label="Recorded option chain underlying spot">
    <h3>BANKNIFTY spot at saved option-chain receipts</h3><p className="ws-caption">Automatic capture mode · no additional socket. Receipt time is local, not an exchange event time. Do not infer candle OHLC or trade signals from these samples.</p>
    {error&&<p role="alert">{error}</p>}
    {data&&data.rows.length>0?<><p>Expiry of latest saved receipt: {data.expiry} · Last receipt UTC: {data.last_utc}</p><ResearchPlot plot={{kind:'line2d',title:'BANKNIFTY underlying spot · saved REST receipts',x_label:'Receipt time (IST)',y_label:'Index spot (points)',x:data.rows.map(r=>r.timestamp_utc),traces:[{name:'Observed spot',y:data.rows.map(r=>r.spot)}],break_before:data.rows.map((r,i)=>i>0&&Date.parse(r.timestamp_utc)-Date.parse(data.rows[i-1].timestamp_utc)>120000)}} provenance="recorded-chain-spot" formatX={x=>new Date(x).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false})}/></>:<p>No saved chain receipts in the latest recorded window. Existing captured index charts remain separate.</p>}
  </section>
}
