import {useState} from 'react'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
type PaperDecision={id:number;decision_utc:string;lane:string;selected?:{units:number;strategy:string;legs:{action:string;strike:number;side:string;expiry:string}[]}}
type Margin={decision_id:number;decision_utc:string;received_utc:string;product:string;initial_margin_inr:number;final_margin_inr:number;conservative_margin_inr:number;paper_capital_inr:number;within_paper_capital:boolean;modeled_risk_inr:number|null;legs:{tradingsymbol:string;side:string;quantity:number;margin_inr:number;estimated_charges_inr:number|null}[];warning:string}
const money=(n:number|null)=>n==null?'—':'₹'+n.toLocaleString('en-IN',{maximumFractionDigits:2})
export default function ZerodhaBasketMargin(){
 const [decisions,setDecisions]=useState<PaperDecision[]>([]),[decision,setDecision]=useState(''),[product,setProduct]=useState('MIS'),[consent,setConsent]=useState(false)
 const [result,setResult]=useState<Margin|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[loaded,setLoaded]=useState(false)
 async function load(){
  setBusy(true);setError('');setResult(null);setConsent(false)
  try{const response=await marketApi<{recent:PaperDecision[]}>('/api/trading-cockpit/automatic-paper');const rows=response.recent.filter(r=>r.selected);setDecisions(rows);setDecision(rows.length?String(rows[0].id):'');setLoaded(true)}
  catch(e){setError(readableError(e))}finally{setBusy(false)}
 }
 async function calculate(){
  if(!decision||!consent||busy)return
  setBusy(true);setError('');setResult(null)
  try{setResult(await marketPost<Margin>('/api/trading-cockpit/options/zerodha/basket-margin',{decision_id:Number(decision),product,confirm_readonly:true}))}
  catch(e){setError(readableError(e))}finally{setBusy(false);setConsent(false)}
 }
 const current=result&&String(result.decision_id)===decision&&result.product===product
 return <details className="mpi-detail"><summary>Zerodha standalone basket-margin preview</summary>
  <p className="mi-muted">Compare a saved paper candidate with Kite's current calculation. Exact option expiry, strike, side and lot size are mapped from its current derivative master. Requires local Kite login and explicit consent; no order is placed, and account positions are excluded.</p>
  <button type="button" className="ws-button" disabled={busy} onClick={()=>void load()}>Load saved paper baskets</button>
  {loaded&&!decisions.length&&<p className="mi-muted">No selected paper candidates are saved yet.</p>}
  {decisions.length>0&&<div className="mi-risk-actions">
   <label>Saved paper candidate<select disabled={busy} value={decision} onChange={e=>{setDecision(e.target.value);setResult(null);setConsent(false)}}>{decisions.map(r=><option key={r.id} value={r.id}>#{r.id} · {r.decision_utc.slice(0,16)} UTC · {r.selected?.legs.map(l=>l.action+' '+l.strike+' '+l.side+' '+l.expiry).join(' / ')} · {r.selected?.units} units</option>)}</select></label>
   <label>Product<select disabled={busy} value={product} onChange={e=>{setProduct(e.target.value);setResult(null);setConsent(false)}}><option>MIS</option><option>NRML</option></select></label>
   <label><input type="checkbox" checked={consent} disabled={busy} onChange={e=>setConsent(e.target.checked)}/> Authorize one read-only Kite calculation</label>
   <button type="button" className="ws-button" disabled={busy||!consent||!decision} onClick={()=>void calculate()}>{busy?'Checking…':'Calculate standalone margin'}</button>
  </div>}
  {error&&<p role="alert" className="tc-error">{error}</p>}
  {current&&result&&<><div className="mi-risk-grid">{Object.entries({'Initial basket margin':result.initial_margin_inr,'Final basket margin':result.final_margin_inr,'Conservative required margin':result.conservative_margin_inr,'Paper capital':result.paper_capital_inr,'Theoretical modeled risk':result.modeled_risk_inr}).map(([k,v])=><div key={k} className="mi-risk-stat"><span>{k}</span><strong>{money(v)}</strong></div>)}</div>
   <p>{result.within_paper_capital?'Within the configured paper budget':'Exceeds the configured paper budget'} · current broker calculation received {result.received_utc}. Not an available cash or order approval check.</p>
   <div className="tc-table-scroll"><table><thead><tr><th>Leg</th><th>Quantity</th><th>Individual margin</th><th>Estimated charges</th></tr></thead><tbody>{result.legs.map(l=><tr key={l.tradingsymbol}><td>{l.side} {l.tradingsymbol}</td><td>{l.quantity}</td><td>{money(l.margin_inr)}</td><td>{money(l.estimated_charges_inr)}</td></tr>)}</tbody></table></div><p className="mi-muted">{result.warning}</p></>}
 </details>
}
