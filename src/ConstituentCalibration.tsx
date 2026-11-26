import {useState} from 'react'
import {marketApi,readableError} from './tradingCockpitApi'
type Group={training_calls:number;holdout_calls:number;training_sessions:number;holdout_sessions:number;candidate_up_probability:number|null;holdout_up_frequency:number|null;absolute_error:number|null}
type Method={state:string;groups:Record<'UP'|'DOWN',Group>;brier:number|null;base_brier:number|null;brier_skill:number|null;expected_calibration_error:number|null;probability_by_call:Record<'UP'|'DOWN',number>|null}
type Result={state:string;observed_sessions:number;required_training_sessions:number;required_holdout_sessions:number;training_dates:string[];holdout_dates:string[];horizon_minutes:number;version:string;methods:Record<string,Method>;note:string}
const percent=(v:number|null)=>v==null?'—':(100*v).toFixed(2)+'%'
const number=(v:number|null)=>v==null?'—':v.toFixed(4)
const names:Record<string,string>={pressure:'Constituent pressure',volume_pressure:'Volume-confirmed pressure',ema_rsi:'EMA-RSI baseline'}
export default function ConstituentCalibration({horizon}:{horizon:number}){
 const [result,setResult]=useState<Result|null>(null)
 const [busy,setBusy]=useState(false)
 const [error,setError]=useState('')
 const load=async()=>{
  setBusy(true);setError('');setResult(null)
  try{setResult(await marketApi<Result>('/api/trading-cockpit/constituents/prospective/calibration?horizon='+horizon))}
  catch(e){setError(readableError(e))}finally{setBusy(false)}
 }
 return <section className="bci-panel" aria-label="Frozen probability validation">
  <header><div><h3>Chronological probability validation</h3><p>Predeclared training and untouched holdout cohorts, evaluated only after enough prospective recorded dates and supported directional calls exist. No probability is invented for missing data.</p></div><button className="ws-button" disabled={busy} onClick={()=>void load()}>{busy?'Checking…':'Inspect probability evidence'}</button></header>
  {error&&<p role="alert" className="bci-error">{error}</p>}
  {result&&result.horizon_minutes===horizon&&<>
   <p className="bci-note">{result.observed_sessions} / {result.required_training_sessions+result.required_holdout_sessions} ended recorded dates · {result.state.replaceAll('_',' ')} · {result.version}.</p>
   {Object.entries(result.methods).map(([m,v])=><div key={m} className="bci-panel"><h4>{names[m]||m}</h4><p className="bci-note">{v.state.replaceAll('_',' ')} · Brier {number(v.brier)} · frozen base Brier {number(v.base_brier)} · skill {percent(v.brier_skill)} · weighted error {percent(v.expected_calibration_error)}</p><div className="bci-scroll"><table aria-label={names[m]+' held-out probability evidence'}><thead><tr><th>Rule call</th><th>Training calls / dates</th><th>Holdout calls / dates</th><th>Development candidate P(up)</th><th>Holdout up frequency</th><th>Abs. error</th><th>Accepted conditional estimate</th></tr></thead><tbody>{(['UP','DOWN'] as const).map(d=><tr key={d}><td>{d}</td><td>{v.groups[d].training_calls} / {v.groups[d].training_sessions}</td><td>{v.groups[d].holdout_calls} / {v.groups[d].holdout_sessions}</td><td>{percent(v.groups[d].candidate_up_probability)}</td><td>{percent(v.groups[d].holdout_up_frequency)}</td><td>{percent(v.groups[d].absolute_error)}</td><td>{v.probability_by_call?percent(v.probability_by_call[d]):'Unavailable'}</td></tr>)}</tbody></table></div></div>)}
   <p className="bci-note">{result.note}</p>
  </>}
 </section>
}
