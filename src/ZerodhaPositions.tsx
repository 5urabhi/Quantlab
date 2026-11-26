import {useEffect,useState} from 'react'
import {marketApi,readableError} from './tradingCockpitApi'
import './market-intelligence-dashboard.css'
type Position={tradingsymbol:string;quantity:number;product:string;average_price:number|null;last_price:number|null;pnl:number|null;realised:number|null;unrealised:number|null}
type Result={rows:Position[];received_utc:string;warning:string}
const fmt=(v:number|null)=>v==null?'—':v.toLocaleString('en-IN',{maximumFractionDigits:2})
export default function ZerodhaPositions(){
 const [enabled,setEnabled]=useState(false),[data,setData]=useState<Result|null>(null),[error,setError]=useState('')
 useEffect(()=>{
  if(!enabled){setData(null);setError('');return}
  let active=true,busy=false
  const controller=new AbortController()
  const poll=async()=>{if(busy||document.hidden)return;busy=true
   try{const r=await marketApi<Result>('/api/trading-cockpit/options/zerodha/net-positions',{signal:controller.signal});if(active){setData(r);setError('')}}
   catch(e){if(active){setData(null);setError(readableError(e))}}
   finally{busy=false}
  }
  void poll();const timer=window.setInterval(()=>void poll(),60000)
  return()=>{active=false;controller.abort();window.clearInterval(timer)}
 },[enabled])
 return <section className="mi-card mi-risk" aria-label="Zerodha broker positions">
  <header className="mi-heading"><div><span className="mi-kicker">KITE · READ ONLY</span><h4>Actual Zerodha BANKNIFTY positions</h4></div><button type="button" className="ws-button" onClick={()=>setEnabled(x=>!x)}>{enabled?'Stop position sync':'Enable read-only position sync'}</button></header>
  <p className="mi-muted">Uses existing Kite login; refreshes every 60 seconds while this page is open and visible. Never creates a journal entry or places an order. Connect or renew Kite under Connections first.</p>
  {error&&<p role="alert" className="tc-error">{error}</p>}
  {enabled&&!data&&!error&&<p role="status">Reading broker positions…</p>}
  {enabled&&data&&<><p className="mi-muted">Broker receipt {new Date(data.received_utc).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'})} IST. {data.warning}</p>{data.rows.length?<div className="tc-table-scroll"><table><thead><tr><th>Exact symbol</th><th>Net units</th><th>Product</th><th>Average price</th><th>Last price</th><th>Broker P&L</th></tr></thead><tbody>{data.rows.map((r,i)=><tr key={r.tradingsymbol+r.product+i}><td>{r.tradingsymbol}</td><td>{r.quantity}</td><td>{r.product}</td><td>{fmt(r.average_price)}</td><td>{fmt(r.last_price)}</td><td>{fmt(r.pnl)}</td></tr>)}</tbody></table></div>:<p>No open BANKNIFTY options in the returned net positions.</p>}</>}
 </section>
}
