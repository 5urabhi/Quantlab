import {useMemo,useState} from 'react'
import ResearchPlot from './ResearchPlots'

export type GammaRow={strike:number;option_type:'CE'|'PE';oi:number|null;lot_size:number|null;contract_master_verified:boolean;model_greeks:{gamma:number}|null}
type Unit='unknown'|'contracts'|'underlying_units'
const fmt=(v:number)=>v.toLocaleString('en-IN',{maximumFractionDigits:0})
export function conditionalGamma(rows:GammaRow[],spot:number,unit:Unit,ce:number,pe:number){
 const strikes=new Map<number,{ce:number;pe:number;covered:number;expected:number;ceCovered:number;peCovered:number}>()
 let covered=0
 if(unit==='unknown'||!Number.isFinite(spot)||spot<=0||!Number.isFinite(ce)||!Number.isFinite(pe)||Math.abs(ce)>1||Math.abs(pe)>1)return {strikes:[],covered,expected:rows.length}
 for(const r of rows){
  if(!Number.isFinite(r.strike)||r.strike<=0)continue
  const cell=strikes.get(r.strike)||{ce:0,pe:0,covered:0,expected:0,ceCovered:0,peCovered:0}
  cell.expected++
  strikes.set(r.strike,cell)
  const gamma=r.model_greeks?.gamma,oi=r.oi
  if(oi===null||!Number.isFinite(oi)||oi<0||gamma==null||!Number.isFinite(gamma)||gamma<0)continue
  if(unit==='contracts'&&(!r.contract_master_verified||r.lot_size===null||!Number.isInteger(r.lot_size)||r.lot_size<=0))continue
  const units=oi*(unit==='contracts'?r.lot_size!:1)
  const magnitude=gamma*units*spot*spot*.01
  if(!Number.isFinite(magnitude))continue
  if(r.option_type==='CE'){cell.ce+=ce*magnitude;cell.ceCovered++}
  else{cell.pe+=pe*magnitude;cell.peCovered++}
  cell.covered++;covered++
 }
 return {strikes:[...strikes.entries()].sort((a,b)=>a[0]-b[0]).map(([strike,v])=>({strike,...v,net:v.ce+v.pe})),covered,expected:rows.length}
}
export default function ConditionalGamma({rows,spot,expiry}:{rows:GammaRow[];spot:number;expiry:string}){
 const [unit,setUnit]=useState<Unit>('unknown')
 const [ce,setCe]=useState(-1)
 const [pe,setPe]=useState(-1)
 const [reviewed,setReviewed]=useState(false)
 const result=useMemo(()=>conditionalGamma(rows,spot,reviewed?unit:'unknown',ce,pe),[rows,spot,unit,ce,pe,reviewed])
 const valid=result.strikes.filter(s=>s.covered>0)
 const sum=valid.reduce((n,r)=>n+r.net,0)
 const complete=result.covered===result.expected&&result.expected>0
 return <section className="ao-panel" aria-label="Conditional gamma exposure scenarios">
  <h4>Hypothetical signed gamma exposure · {expiry}</h4>
  <p className="ao-muted">Public OI cannot identify dealers' signed positions. Choose an explicit OI unit assumption and hypothetical net fractions of open interest (−1 = all short, +1 = all long). This is a sensitivity scenario, not measured dealer exposure or a price forecast.</p>
  <div className="bci-actions"><label>Assumed OI unit<select aria-label="Conditional gamma OI unit" value={unit} onChange={e=>{setUnit(e.target.value as Unit);setReviewed(false)}}><option value="unknown">Unknown / unavailable</option><option value="underlying_units">Assume underlying units</option><option value="contracts">Assume contracts × verified lot size</option></select></label>
   <label>Hypothetical call net fraction<input type="number" min={-1} max={1} step={.1} aria-label="Hypothetical call net fraction" value={ce} onChange={e=>setCe(Number(e.target.value))}/></label>
   <label>Hypothetical put net fraction<input type="number" min={-1} max={1} step={.1} aria-label="Hypothetical put net fraction" value={pe} onChange={e=>setPe(Number(e.target.value))}/></label></div>
  <label className="bci-check"><input type="checkbox" checked={reviewed} disabled={unit==='unknown'} onChange={e=>setReviewed(e.target.checked)}/> I understand these are hypothetical signed inventory and OI-unit assumptions.</label>
  {!reviewed||unit==='unknown'?<p className="ao-muted">No signed scenario is shown until the assumptions are explicitly acknowledged.</p>:<><p className="ao-muted">Coverage: {result.covered} / {result.expected} returned rows with finite gamma, OI and required unit conversion. {complete?'Complete for returned rows only, not the exchange-wide universe.':'Partial observed subset; missing contracts are not treated as zero.'}</p>
   {valid.length>0&&<><p>{complete?'Returned-chain scenario':'Covered-subset scenario'}: ₹{fmt(sum)} signed gamma notional change per +1% underlying move (approximate).</p><ResearchPlot provenance="Hypothetical net OI fractions and same-receipt model gamma" plot={{kind:'bar2d',title:'Conditional signed gamma notional by strike',x_label:'Strike (index points)',y_label:'Hypothetical INR delta-notional change per +1% spot',x:result.strikes.map(r=>r.strike),traces:[{name:'Call scenario',y:result.strikes.map(r=>r.ceCovered?r.ce:null)},{name:'Put scenario',y:result.strikes.map(r=>r.peCovered?r.pe:null)},{name:'Net observed subset',y:result.strikes.map(r=>r.covered?r.net:null)}],reference_lines:[{label:'Zero',value:0}]}}/></>}
   <p className="ao-muted">Formula: assumed signed position units × model gamma × spot² × 0.01. Linearized local sensitivity only; unknown positioning, expiry effects, delta changes and incomplete source coverage prevent inference of actual hedging flows.</p></>}
 </section>
}
