import {useEffect,useState} from 'react'
import {marketApi,readableError} from './tradingCockpitApi'

type Task={task:string;selected:string;brier:number|null;accuracy:number|null;scored:number|null;predicted:Record<string,number|null>;observed:Record<string,number|null>;matched_brier_difference:number|null}
type Scope={state:string;coverage:Record<string,number|null>;tasks:Task[]}
type Summary={state:string;report_name?:string;training_dates?:string[];validation_dates?:string[];holdout_dates?:string[];horizons?:Record<string,Record<string,Scope>>;bank_target_state?:string}
const fmt=(x:number|null|undefined,d=4)=>x==null?'—':x.toFixed(d)
const pct=(x:number|null|undefined)=>x==null?'—':(100*x).toFixed(1)+'%'
const labels:Record<string,string>={sequence:'Longer candles',global:'Sequences + global',panel:'Sequences + banks',panel_global:'Sequences + banks + global',bank_directions:'Individual bank direction / divergence'}
const taskName=(s:string)=>s.replaceAll('_',' ')

export default function CandleBarrierResults(){
  const [opened,setOpened]=useState(false)
  const [data,setData]=useState<Summary|null>(null)
  const [error,setError]=useState('')
  const [revision,setRevision]=useState(0)
  const [horizon,setHorizon]=useState('15')
  const [scope,setScope]=useState('sequence')
  useEffect(()=>{
    if(!opened)return
    let active=true
    setError('')
    void marketApi<Summary>('/api/trading-cockpit/candle-barriers/latest').then(result=>{if(active)setData(result)}).catch(err=>{if(active)setError(readableError(err))})
    return()=>{active=false}
  },[opened,revision])
  const scopes=data?.horizons?.[horizon]||{}
  const current=scopes[scope]||scopes.sequence
  return <details className="mpi-detail" onToggle={e=>setOpened(e.currentTarget.open)}>
    <summary>Saved candle sequences &amp; first-passage research</summary>
    <div className="mpi-head"><div><h4>Observed movement probability studies</h4><p className="tc-muted">Chronological research only. Upper/lower touches are BANKNIFTY points, not option premium changes. No live signal or profitability approval.</p></div><button className="ws-button" type="button" onClick={()=>setRevision(x=>x+1)}>Refresh saved report</button></div>
    {error&&<p role="alert" className="tc-error">{error}</p>}
    {!data&&!error&&opened&&<p role="status">Checking saved first-passage results…</p>}
    {data?.state!=='available'&&data&&<p className="tc-muted">No valid saved study yet ({data.state.replaceAll('_',' ')}). Run <code>bash run.sh candle-research --first-passage --context-mode archive --fixed-panel</code> outside market priority hours.</p>}
    {data?.state==='available'&&<>
      <p className="tc-muted">Training {data.training_dates?.length??0} sessions · validation {data.validation_dates?.length??0} · evaluation {data.holdout_dates?.length??0} ({data.holdout_dates?.[0]??'—'} to {data.holdout_dates?.[data.holdout_dates.length-1]??'—'}). Previously inspected dates are exploratory.</p>
      <label>Forecast horizon <select value={horizon} onChange={e=>{setHorizon(e.target.value);setScope('sequence')}}>{Object.keys(data.horizons||{}).map(k=><option key={k} value={k}>{k} minutes</option>)}</select></label>{' '}
      <label>Matched comparison <select value={scopes[scope]?scope:'sequence'} onChange={e=>setScope(e.target.value)}>{Object.keys(scopes).map(k=><option key={k} value={k}>{labels[k]||k}</option>)}</select></label>
      {current&&<><p className="tc-muted">{current.state.replaceAll('_',' ')} · train {current.coverage.train??0}, validation {current.coverage.validation??0}, evaluation {current.coverage.holdout??0} matched anchors. Lower Brier is better; negative Δ means improvement over its matched baseline.</p>
      {current.tasks.length===0?<p className="tc-muted">Insufficient matched earlier observations; no prediction estimated.</p>:<div className="tc-table-scroll"><table><thead><tr><th>Target</th><th>Selected on validation</th><th>Evaluation anchors</th><th>Brier ↓</th><th>Δ Brier ↓</th><th>Accuracy</th><th>Mean forecast vs observed</th></tr></thead><tbody>
        {current.tasks.map(t=><tr key={t.task}><td>{taskName(t.task)}</td><td>{taskName(t.selected)}</td><td>{t.scored??'—'}</td><td>{fmt(t.brier)}</td><td>{fmt(t.matched_brier_difference)}</td><td>{pct(t.accuracy)}</td><td>{Object.entries(t.predicted).map(([k,v])=><div key={k}>{taskName(k)}: {pct(v)} / {pct(t.observed[k])}</div>)}</td></tr>)}
      </tbody></table></div>}</>}
      {data.bank_target_state&&data.bank_target_state!=='observed_fixed_panel'&&<p className="tc-muted">Individual bank targets: {data.bank_target_state.replaceAll('_',' ')}.</p>}
      <p className="tc-muted">Ambiguous means both barriers touched within a minute without a known order. These are historical aggregate probabilities, not a prediction for the current candle.</p>
    </>}
  </details>
}
