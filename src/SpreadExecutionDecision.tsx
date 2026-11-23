import {ShieldAlert} from 'lucide-react'
import './spread-execution-gate.css'

export type ExecutionDecision={
  live_action:'NO_TRADE'
  research_status:'PAPER_TEST_CANDIDATES'|'NO_QUALIFIED_CANDIDATES'
  paper_research_candidates:number
  screened_candidates:number
  rejection_reason_counts:Record<string,number>
  expected_net_profit_inr:null
  calibrated_fill_probability:null
  explanation:string
  policy_version?:string
}
const nice=(x:string)=>x.replaceAll('_',' ').toLowerCase().replace(/\b\w/g,c=>c.toUpperCase())

export default function SpreadExecutionDecision({decision,scope}:{
  decision?:ExecutionDecision|null;scope:string
}){
  const candidates=decision?.paper_research_candidates||0
  const total=decision?.screened_candidates||0
  const sorted=Object.entries(decision?.rejection_reason_counts||{})
    .sort((a,b)=>b[1]-a[1])
  return <section className="sg-decision" aria-label={scope+' execution feasibility decision'}>
    <div className="sg-decision-top">
      <div className="sg-action"><ShieldAlert size={19}/>
        <strong>NO TRADE</strong><small>Live execution not approved</small></div>
      <div><strong>{candidates>0?'Paper-test candidates found':
        'No source-qualified candidates'}</strong>
        <p>{candidates} of {total} evaluated structures cleared the conservative
          <b> research-only</b> source and risk screen. This is not a validated
          probability of profit or an authorization to place orders.</p></div>
    </div>
    <p className="sg-note">{decision?.explanation||
      'No execution recommendation: original bid/ask snapshots contain no verified fills, order queue or calibrated probability of net profit.'}</p>
    {sorted.length>0&&<details className="sg-reasons">
      <summary>Why opportunities were rejected ({sorted.length} reasons)</summary>
      <div className="sg-reason-list">
        {sorted.slice(0,10).map(([name,count])=><span key={name}>
          <strong>{count}</strong>{nice(name)}</span>)}
      </div>
      <small>Counts may overlap: a contract can fail multiple conditions.</small>
    </details>}
  </section>
}
