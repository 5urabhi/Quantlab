import {useEffect,useMemo,useState} from 'react'
import {marketApi,readableError} from './tradingCockpitApi'
import './market-intelligence-dashboard.css'

type Quote={price:number;received_utc:string;identity:string}
type Bank={symbol:string;weight_pct:number|null;return_pct:number|null;session_return_pct?:number|null;relative_volume:number|null;baseline_sessions:number;volume_delta:number|null;approx_index_points:number|null;contribution_pp:number|null;atp_deviation_pct:number|null;displayed_quantity_imbalance:number|null;current:Quote|null;session_anchor_utc?:string|null}
type Report={rows:Bank[];expected_members:number;observed_members:number;observed_weight_pct:number|null;weighted_breadth_pct:number|null;weighted_return_pct:number|null;as_of_utc:string;blockers:string[];weight_snapshot:{snapshot_date:string}|null}
const number=(v:number|null|undefined,d=2)=>v==null||!Number.isFinite(v)?'—':v.toLocaleString('en-IN',{maximumFractionDigits:d})
const signed=(v:number|null|undefined)=>v==null||!Number.isFinite(v)?'—':(v>0?'+':'')+number(v)+'%'
const stamp=(v:string|undefined|null)=>v?new Date(v).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata',hourCycle:'h23'}):'—'
export default function BankHeatmap(){
 const [mode,setMode]=useState<'session'|'1'|'5'|'10'|'30'|'60'>('5')
 const [report,setReport]=useState<Report|null>(null)
 const [error,setError]=useState('')
 const [selected,setSelected]=useState('')
 const [now,setNow]=useState(Date.now())
 useEffect(()=>{
   let active=true,busy=false
   const controller=new AbortController()
   setReport(null);setError('')
   const poll=async()=>{
     if(busy||document.hidden)return
     busy=true
     try{const r=await marketApi<Report>('/api/trading-cockpit/constituents/analysis?horizon='+(mode==='session'?'5':mode),{signal:controller.signal});if(active){setReport(r);setError('');setNow(Date.now())}}
     catch(e){if(active)setError(readableError(e))}
     finally{busy=false}
   }
   void poll()
   const timer=window.setInterval(()=>void poll(),15000)
   const clock=window.setInterval(()=>setNow(Date.now()),1000)
   const visible=()=>{if(!document.hidden)void poll()}
   document.addEventListener('visibilitychange',visible)
   return()=>{active=false;controller.abort();window.clearInterval(timer);window.clearInterval(clock);document.removeEventListener('visibilitychange',visible)}
 },[mode])
 const stale=!!report&&(!!error||now-Date.parse(report.as_of_utc)>45000)
 const rows=useMemo(()=>[...(report?.rows||[])].sort((a,b)=>(b.weight_pct??-1)-(a.weight_pct??-1)||a.symbol.localeCompare(b.symbol)),[report])
 const value=(r:Bank)=>stale?null:mode==='session'?r.session_return_pct??null:r.return_pct
 const counts=rows.reduce((a,r)=>{const v=value(r);a[v==null?'missing':v>0?'up':v<0?'down':'flat']++;return a},{up:0,down:0,flat:0,missing:0})
 const detail=rows.find(r=>r.symbol===selected)
 return <section className="mi-card mi-heatmap" aria-label="Bank Nifty constituent heatmap">
  <header className="mi-heading"><div><span className="mi-kicker">UNDERLYING STOCKS</span><h3>Bank heatmap</h3></div><a href="#/tradingdirectional">Full bank analysis →</a></header>
  <div className="mi-heat-controls"><label>Return period <select aria-label="Bank heatmap return period" value={mode} onChange={e=>setMode(e.target.value as typeof mode)}><option value="session">Since opening sample</option>{['1','5','10','30','60'].map(n=><option key={n} value={n}>{n} min</option>)}</select></label><span>{report?stamp(report.as_of_utc)+' IST · '+(stale?'STALE':'observed cutoff'):'Awaiting data'}</span></div>
  <div className="mi-breadth" aria-label="Constituent breadth"><span className="mi-positive">▲ {counts.up} up</span><span className="mi-negative">▼ {counts.down} down</span><span>{counts.flat} flat</span><span>{counts.missing} unavailable</span></div>
  {report&&mode!=='session'&&!stale&&<div className="mi-weighted"><span>Weight coverage <b>{number(report.observed_weight_pct,1)}{report.observed_weight_pct!=null?'%':''}</b></span><span>Weighted breadth <b>{signed(report.weighted_breadth_pct)}</b></span></div>}
  {rows.length>0?<div className="mi-heat-grid">{rows.map(r=>{
    const v=value(r),strength=v==null?0:Math.min(3,Math.floor(Math.abs(v)/(mode==='session'?.5:.15))+1)
    const cls=v==null?'missing':v===0?'flat':(v>0?'up':'down')+strength
    return <button key={r.symbol} type="button" className={'mi-tile '+cls+(selected===r.symbol?' selected':'')} aria-pressed={selected===r.symbol} aria-label={r.symbol+' '+signed(v)+'; weight '+number(r.weight_pct)+' percent'} onClick={()=>setSelected(selected===r.symbol?'':r.symbol)}>
      <strong>{r.symbol}</strong><span>{v==null?'—':(v>0?'▲ ':v<0?'▼ ':'')+signed(v)}</span><small>{r.weight_pct==null?'Weight —':number(r.weight_pct,1)+'% wt'}</small>
    </button>
  })}</div>:<p className="mi-muted">{error?'Constituent data unavailable.':report?'No dated constituent membership is available. Sync reviewed membership in Full bank analysis.':'Reading saved constituent quotes…'}</p>}
  {detail&&<div className="mi-bank-detail" role="region" aria-label={'Bank details '+detail.symbol}><header><strong>{detail.symbol}</strong><button type="button" onClick={()=>setSelected('')}>Close</button></header><div><span>Observed price <b>{stale?'—':number(detail.current?.price)}</b></span><span>Return <b>{signed(value(detail))}</b></span><span>Relative interval volume <b>{stale?'—':number(detail.relative_volume)}{!stale&&detail.relative_volume!=null?'×':''}</b></span><span>Volume shares <b>{stale?'—':number(detail.volume_delta,0)}</b></span><span>ATP deviation <b>{stale?'—':signed(detail.atp_deviation_pct)}</b></span><span>Interval index points <b>{stale?'—':number(detail.approx_index_points)}</b></span><span>Quote time <b>{stamp(detail.current?.received_utc)} IST</b></span><span>Opening sample <b>{stamp(detail.session_anchor_utc)} IST</b></span></div><small>Volume and estimated contributions use the selected interval (5m in opening-sample mode). Displayed quantity and ATP are not aggressor flow.</small></div>}
  {error&&<p className="mi-muted" role="status">{error} · no current colors inferred.</p>}
  {report&&report.blockers.length>0&&<details className="mi-evidence"><summary>Data coverage &amp; evidence</summary>{report.blockers.map((b,i)=><p key={i}>{b}</p>)}<p>Dated weights: {report.weight_snapshot?.snapshot_date||'unavailable'}. {report.expected_members} expected constituents.</p></details>}
  <p className="mi-muted">All dated members, ordered by weight where available. Green/red = observed return, gray = flat or unavailable (see label). Opening sample is not the official exchange open. Not a directional forecast.</p>
 </section>
}
