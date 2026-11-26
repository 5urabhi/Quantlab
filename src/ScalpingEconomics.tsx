import {useState} from 'react'
import './market-intelligence-dashboard.css'

const fmt=(v:number,d=2)=>v.toLocaleString('en-IN',{maximumFractionDigits:d})
const money=(v:number)=>(v<0?'−₹':'₹')+fmt(Math.abs(v))
export default function ScalpingEconomics(){
 const [inputs,setInputs]=useState({quantity:'90',sideCost:'50',spread:'0',slippage:'0',win:'200',loss:'150',winRate:'70',trades:'100',minutes:'5'})
 const a=Object.fromEntries(Object.entries(inputs).map(([k,v])=>[k,v.trim()===''?NaN:Number(v)])) as Record<keyof typeof inputs,number>
 const valid=Object.values(a).every(v=>Number.isFinite(v)&&v>=0)&&a.quantity>0&&Number.isInteger(a.quantity)&&a.winRate<=100&&a.trades>=1&&Number.isInteger(a.trades)&&a.minutes>0&&a.win+a.loss>0
 const cost=2*a.sideCost+a.quantity*(a.spread+a.slippage)
 const p=a.winRate/100
 const net=p*a.win-(1-p)*a.loss-cost
 const threshold=(a.loss+cost)/(a.win+a.loss)
 const max=Math.floor(375/a.minutes)
 const label=(key:keyof typeof inputs,title:string,min=0,step='any',maxValue?:number)=><label key={key}>{title}<input aria-label={title} type="number" min={min} step={step} max={maxValue} value={inputs[key]} onChange={e=>setInputs(s=>({...s,[key]:e.target.value}))}/></label>
 return <section className="mi-card mi-risk" aria-label="Scalping cost and expectancy">
  <header className="mi-heading"><div><span className="mi-kicker">COST FIRST · SCENARIO CALCULATOR</span><h3>Scalping economics</h3><p className="mi-muted">Hypothetical average gross winning/losing rupees before the separately entered costs. These are assumptions, not historical win rates.</p></div><a href="#/tradingpaper">Original-depth paper replay →</a></header>
  <div className="mi-risk-actions" style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(160px,1fr))'}}>
   {label('quantity','Quantity (units)',1,'1')}{label('sideCost','Charges per side (₹)')}{label('spread','Extra round-trip spread (premium pts)')}{label('slippage','Extra round-trip slippage (premium pts)')}
   {label('win','Average gross winner (₹)')}{label('loss','Average gross loser (₹)')}{label('winRate','Assumed win rate (%)',0,'any',100)}{label('trades','Hypothetical round trips/day',1,'1')}{label('minutes','Minutes per round trip',.01)}
  </div>
  {valid?<><div className="mi-risk-grid">
    <div className="mi-risk-stat"><span>Round-trip friction</span><strong>{money(cost)}</strong><small>{fmt(cost/a.quantity,3)} premium points per unit</small></div>
    <div className="mi-risk-stat"><span>Net winning trade</span><strong>{money(a.win-cost)}</strong><small>Net loser {money(-a.loss-cost)}</small></div>
    <div className="mi-risk-stat"><span>Break-even win rate</span><strong>{threshold>=1?'No positive edge possible':fmt(threshold*100)+'%'}</strong><small>Strictly above required for positive expectancy</small></div>
    <div className="mi-risk-stat"><span>Expected net / round trip</span><strong className={net>0?'mi-positive':net<0?'mi-negative':''}>{money(net)}</strong><small>Assumed win rate and payoff</small></div>
    <div className="mi-risk-stat"><span>Hypothetical daily net</span><strong>{money(a.trades*net)}</strong><small>Daily friction {money(a.trades*cost)}; not a profit forecast</small></div>
    <div className="mi-risk-stat"><span>Time-only capacity</span><strong>{max} round trips</strong><small>375 regular minutes; ignores waits and execution</small></div>
  </div>{a.trades>max&&<p className="tc-warning">Requested count exceeds non-overlapping time capacity. Do not shorten a strategy merely to hit a trade quota.</p>}
  {a.win<=cost&&<p className="tc-warning">Even a winning trade cannot overcome entered friction.</p>}
  <p className="mi-muted">Use actual buy-ask and sell-bid fills in gross P&L and set extra spread/slippage to zero if already included, to avoid double counting. Losses can exceed the assumed average; no fixed daily trade target is recommended.</p>
  </>:<p role="status" className="mi-muted">Enter valid nonnegative costs, positive quantity/holding time, and win rate from 0–100%.</p>}
 </section>
}
