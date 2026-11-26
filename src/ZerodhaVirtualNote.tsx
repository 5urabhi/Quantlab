import {useEffect,useState} from 'react'
import {marketPost,readableError} from './tradingCockpitApi'
type Props={buy:number;sell:number;quantity:number;enabled:boolean}
type Result={broker_estimated_total:number;local_estimated_total:number;difference_inr:number;net_pnl_inr:number;received_utc:string;tradingsymbol:string;quantity:number;buy_premium:number;sell_premium:number;sides:{side:string;brokerage:number;transaction_tax:number;exchange_turnover_charge:number;sebi_turnover_charge:number;stamp_duty:number;gst:number;total:number}[]}
const money=(v:number)=>'₹'+v.toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2})
export default function ZerodhaVirtualNote({buy,sell,quantity,enabled}:Props){
 const [symbol,setSymbol]=useState(''),[product,setProduct]=useState('MIS')
 const [result,setResult]=useState<Result|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false)
 useEffect(()=>{setResult(null);setError('')},[buy,sell,quantity,symbol,product,enabled])
 async function check(){
  setBusy(true);setResult(null);setError('')
  try{setResult(await marketPost<Result>('/api/trading-cockpit/options/zerodha/virtual-note',{tradingsymbol:symbol.trim().toUpperCase(),quantity,buy_premium:buy,sell_premium:sell,product}))}
  catch(e){setError(readableError(e))}
  finally{setBusy(false)}
 }
 const current=result&&enabled&&result.buy_premium===buy&&result.sell_premium===sell&&result.quantity===quantity&&result.tradingsymbol===symbol.trim().toUpperCase()
 return <details className="mpi-detail"><summary>Compare with Zerodha's virtual contract note</summary>
  <p className="mi-muted">Optional broker-side calculation for one hypothetical buy and one sell with regular tariff. Uses your existing local Kite login only when clicked. No order is placed. Connect or renew Kite in Connections first.</p>
  <form className="mi-risk-actions" onSubmit={e=>{e.preventDefault();void check()}}><label>Exact Kite BANKNIFTY symbol<input aria-label="Exact Kite BANKNIFTY symbol" required value={symbol} onChange={e=>setSymbol(e.target.value)} placeholder="Copy exact tradingsymbol"/></label><label>Product<select value={product} onChange={e=>setProduct(e.target.value)}><option>MIS</option><option>NRML</option></select></label><button type="submit" disabled={!enabled||busy} className="ws-button">{busy?'Checking Kite…':'Calculate with Zerodha'}</button></form>
  {error&&<p role="alert" className="tc-error">{error}</p>}
  {current&&result&&<><div className="mi-risk-grid">{Object.entries({'Kite estimated fees':result.broker_estimated_total,'Difference vs local estimate':result.difference_inr,'Net P&L using Kite estimate':result.net_pnl_inr}).map(([k,v])=><div className="mi-risk-stat" key={k}><span>{k}</span><strong>{money(v)}</strong></div>)}</div><div className="tc-table-scroll"><table><thead><tr><th>Side</th><th>Brokerage</th><th>STT</th><th>Exchange</th><th>SEBI</th><th>Stamp</th><th>GST</th><th>Total</th></tr></thead><tbody>{result.sides.map(r=><tr key={r.side}><td>{r.side}</td>{[r.brokerage,r.transaction_tax,r.exchange_turnover_charge,r.sebi_turnover_charge,r.stamp_duty,r.gst,r.total].map((v,i)=><td key={i}>{money(v)}</td>)}</tr>)}</tbody></table></div><p className="mi-muted">Hypothetical broker calculation · not the final contract note. Extra spread/slippage assumptions not included here.</p></>}
 </details>
}
