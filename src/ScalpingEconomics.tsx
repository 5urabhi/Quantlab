import {useEffect,useState} from 'react'
import {marketPost,readableError} from './tradingCockpitApi'
import ZerodhaVirtualNote from './ZerodhaVirtualNote'
import ZerodhaBasketMargin from './ZerodhaBasketMargin'
import './market-intelligence-dashboard.css'

const fmt=(v:number,d=2)=>v.toLocaleString('en-IN',{maximumFractionDigits:d})
const money=(v:number|null|undefined)=>v==null?'—':(v<0?'−₹':'₹')+fmt(Math.abs(v))
type Fee={brokerage:number;exchange_indicative:number;sebi:number;gst:number;stt_sell:number;stamp_buy:number;total_estimated:number;buy_leg:{fees_total:number};sell_leg:{fees_total:number};version:string}
type Estimate={fees:Fee;gross_pnl_inr:number;net_pnl_inr:number;extra_execution_cost_inr:number;break_even_sell_premium:number|null;target_sell_premium:number|null;expectancy:{net_winner:number;net_loser:number;break_even_win_pct:number|null;expected_net_inr:number}|null}
export default function ScalpingEconomics(){
 const [inputs,setInputs]=useState({quantity:'90',buy:'180',sell:'182',buyOrders:'1',sellOrders:'1',spread:'0',slippage:'0',target:'100',win:'200',loss:'150',winRate:'70',trades:'100',minutes:'5'})
 const [profile,setProfile]=useState('zerodha')
 const [data,setData]=useState<Estimate|null>(null),[error,setError]=useState('')
 const a=Object.fromEntries(Object.entries(inputs).map(([k,v])=>[k,v.trim()===''?NaN:Number(v)])) as Record<keyof typeof inputs,number>
 const valid=Object.values(a).every(v=>Number.isFinite(v)&&v>=0)&&a.quantity>=1&&a.quantity<=100000&&Number.isInteger(a.quantity)&&a.buy>=.05&&a.sell>=.05&&a.buy<=20000&&a.sell<=20000&&[a.buyOrders,a.sellOrders].every(n=>Number.isInteger(n)&&n>=1&&n<=20)&&a.winRate<=100&&a.trades>=1&&Number.isInteger(a.trades)&&a.minutes>0
 useEffect(()=>{
   let active=true
   setData(null);setError('')
   if(!valid)return
   const timer=window.setTimeout(()=>{marketPost<Estimate>('/api/trading-cockpit/options/zerodha/cost-estimate',{buy_premium:a.buy,sell_premium:a.sell,quantity:a.quantity,buy_orders:a.buyOrders,sell_orders:a.sellOrders,broker_profile:profile,target_net_inr:a.target,extra_spread_points:a.spread,extra_slippage_points:a.slippage,gross_winner_inr:a.win,gross_loser_inr:a.loss,win_rate_pct:a.winRate}).then(r=>{if(active)setData(r)}).catch(e=>{if(active)setError(readableError(e))})},250)
   return()=>{active=false;window.clearTimeout(timer)}
 },[inputs,profile,valid])
 const label=(key:keyof typeof inputs,title:string,min=0,step='any',maxValue?:number)=><label key={key}>{title}<input aria-label={title} type="number" min={min} step={step} max={maxValue} value={inputs[key]} onChange={e=>setInputs(s=>({...s,[key]:e.target.value}))}/></label>
 const max=Math.floor(375/a.minutes),ex=data?.expectancy,fee=data?.fees
 return <section className="mi-card mi-risk" aria-label="Scalping cost and expectancy">
  <header className="mi-heading"><div><span className="mi-kicker">ZERODHA · CURRENT NSE OPTIONS TARIFF</span><h3>Scalping economics &amp; execution costs</h3><p className="mi-muted">Premium-dependent local estimates, updated automatically. No Kite request or order is sent.</p></div><a href="#/tradingpaper">Original-depth paper replay →</a></header>
  <div className="mi-risk-actions" style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(160px,1fr))'}}>
   {label('quantity','Quantity (units)',1,'1',100000)}{label('buy','Entry premium (₹)',.05,'any',20000)}{label('sell','Exit premium (₹)',.05,'any',20000)}{label('target','Target net profit (₹)')}
   <label>Broker tariff<select value={profile} onChange={e=>setProfile(e.target.value)}><option value="zerodha">Zerodha regular</option><option value="zerodha_debit_balance">Zerodha debit balance</option></select></label>
   {label('buyOrders','Executed buy orders',1,'1',20)}{label('sellOrders','Executed sell orders',1,'1',20)}
  </div>
  <details className="mpi-detail"><summary>Execution assumptions and hypothetical expectancy</summary><div className="mi-risk-actions" style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(160px,1fr))'}}>
   {label('spread','Extra round-trip spread (premium pts)')}{label('slippage','Extra round-trip slippage (premium pts)')}
   {label('win','Average gross winner (₹)')}{label('loss','Average gross loser (₹)')}{label('winRate','Assumed win rate (%)',0,'any',100)}{label('trades','Hypothetical round trips/day',1,'1')}{label('minutes','Minutes per round trip',.01)}
  </div></details>
  {error&&<p role="alert" className="tc-error">{error}</p>}
  {data&&fee?<><div className="mi-risk-grid">
    <div className="mi-risk-stat"><span>Estimated round-trip fees</span><strong>{money(fee.total_estimated)}</strong><small>Buy {money(fee.buy_leg.fees_total)} · Sell {money(fee.sell_leg.fees_total)}</small></div>
    <div className="mi-risk-stat"><span>Net P&L</span><strong>{money(data.net_pnl_inr)}</strong><small>Gross {money(data.gross_pnl_inr)} · extra execution {money(data.extra_execution_cost_inr)}</small></div>
    <div className="mi-risk-stat"><span>Break-even exit premium</span><strong>{money(data.break_even_sell_premium)}</strong><small>₹0.05 tick assumption; not a fill</small></div>
    <div className="mi-risk-stat"><span>Exit for net target</span><strong>{money(data.target_sell_premium)}</strong><small>Target {money(a.target)}</small></div>
    <div className="mi-risk-stat"><span>Break-even win rate</span><strong>{ex?.break_even_win_pct==null?'—':ex.break_even_win_pct>=100?'No positive edge possible':fmt(ex.break_even_win_pct)+'%'}</strong><small>Hypothetical payoffs</small></div>
    <div className="mi-risk-stat"><span>Expected net / round trip</span><strong>{money(ex?.expected_net_inr)}</strong><small>Hypothetical daily net {money(ex?ex.expected_net_inr*a.trades:null)}</small></div>
  </div><details className="mpi-detail"><summary>Complete charge breakdown</summary><div className="mi-risk-grid">{Object.entries({Brokerage:fee.brokerage,'NSE transaction':fee.exchange_indicative,SEBI:fee.sebi,GST:fee.gst,'Sell STT':fee.stt_sell,'Buy stamp duty':fee.stamp_buy}).map(([k,v])=><div className="mi-risk-stat" key={k}><span>{k}</span><strong>{money(v)}</strong></div>)}</div><p className="mi-muted">{fee.version} · ₹20/40 per executed order depending on tariff. STT 0.15% of sell premium since 1 April 2026. NSE 0.03553%, SEBI 0.0001%, stamp 0.003% buy, GST 18% on brokerage/exchange/SEBI. IPFT included in the NSE transaction rate. Daily rounding and final contract notes can differ.</p></details>
  {a.trades>max&&<p className="tc-warning">Requested count exceeds {max} non-overlapping time-only round trips; no trade quota is recommended.</p>}
  {ex&&ex.net_winner<=0&&<p className="tc-warning">Even the assumed gross winning trade does not clear its costs.</p>}
  </>:!error?<p className="mi-muted">{valid?'Calculating current tariff…':'Enter valid premiums, quantity and cost assumptions.'}</p>:null}
  <ZerodhaVirtualNote buy={a.buy} sell={a.sell} quantity={a.quantity} enabled={valid&&a.buyOrders===1&&a.sellOrders===1&&profile==="zerodha"}/>
  <ZerodhaBasketMargin/>
  <p className="mi-muted">Use actual buy-ask and sell-bid fill prices where possible. Set extra spread/slippage to zero if already included. API subscriptions, exceptional square-off/dealer fees, expiry exercise, interest and account-specific costs are excluded. No guaranteed profitable trade.</p>
 </section>
}
