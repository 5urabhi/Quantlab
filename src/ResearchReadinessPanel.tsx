import {useCallback,useEffect,useState} from 'react'
import {AlertTriangle,ArrowRight,CheckCircle2,Clock,Database,
  FileCheck,RefreshCw,ShieldCheck} from 'lucide-react'

type Dataset={id:string;label:string;kind:string}
type ModelStatus={
  id:string;title:string;group:string;mode:string;status:string;
  source_ready:boolean;mathematics_ready:boolean;implementation_ready:boolean;
  implementation_status:string;evidence_type:string;
  setup_steps:{title:string;state:string;detail:string;action_kind:string}[];
  detail:string;next_action:string;
  requirement:{minimum_observed_returns:number;preferred_with_20_percent:number;frequency:string};
  action:{kind:string;label:string;automatable:boolean}
}
type Evidence={id:string;label:string;verified_by_exchange:boolean;available:boolean;action:string}
type Readiness={
  dataset_id:string|null;dataset_label:string;total_models:number;
  implemented_models:number;math_ready:number;historical_source_ready:number;option_source_ready:number;
  blocked:number;synthetic_fixture:boolean;models:ModelStatus[];
  sources:{historical_membership:{available:boolean;covered_through?:string;
    limitations?:string[];source?:string};requirements:Evidence[];
    membership_status:string;benchmark_and_actions:Record<string,unknown>};
  warning:string
}
type EvidenceAudit={dataset_id:string;status:string;structural_run_ready:boolean;
  independent_source_certified:boolean;publication_certified:boolean;
  checks:{name:string;status:string;detail:string;next_action:string}[];
  warning:string}
type Audit={id:string;dataset_id:string|null;attempted_models:number;software_pass:number;
  software_fail:number;source_blocked:number;checked_utc:string}
type Acceptance={id:string;dataset_id:string;created_utc:string;status:string;
  structural_ready?:boolean;independently_certified:boolean;
  current_source_match?:boolean;current_source_status?:string;
  source_checks_passed:number;source_checks_blocked:number;source_checks_review?:number;
  model_software_pass:number;model_software_fail:number;
  blockers?:{component:string;state:string;detail:string;next_action:string}[];
  warning?:string}
type Job={id:string;status:string;percent?:number;stage?:string;error?:string;
  result?:Audit|Record<string,unknown>}
const json=async<T,>(path:string,init?:RequestInit):Promise<T>=>{
  const r=await fetch(path,init)
  if(!r.ok){
    let msg='Readiness service unavailable'
    try{const b=await r.json() as {detail?:string};if(b.detail)msg=b.detail}catch{/* ignore */}
    throw new Error(msg)
  }
  return r.json() as Promise<T>
}
export default function ResearchReadinessPanel({datasets,onAcquire,onModel}:{
  datasets:Dataset[];onAcquire:()=>void;onModel:()=>void
}){
  const [dataset,setDataset]=useState('')
  const [info,setInfo]=useState<Readiness|null>(null)
  const [recent,setRecent]=useState<Audit[]>([])
  const [evidenceAudit,setEvidenceAudit]=useState<EvidenceAudit|null>(null)
  const [validationStart,setValidationStart]=useState('')
  const [finalTestStart,setFinalTestStart]=useState('')
  const [acceptance,setAcceptance]=useState<Acceptance|null>(null)
  const [acceptanceReports,setAcceptanceReports]=useState<Acceptance[]>([])
  const [job,setJob]=useState<Job|null>(null)
  const [error,setError]=useState('')
  const [notice,setNotice]=useState('')
  const [busy,setBusy]=useState(false)
  const [onlyBlocked,setOnlyBlocked]=useState(false)
  const [revision,setRevision]=useState(0)
  const reload=useCallback(async()=>{
    const [summary,audits,evidence,reports]=await Promise.all([
      json<Readiness>('/api/data-manager/research/overview?'+new URLSearchParams({
        dataset_id:dataset}).toString()),
      json<{audits:Audit[]}>('/api/data-manager/research/audits'),
      dataset?json<EvidenceAudit>('/api/data-manager/research/evidence-audit?'+
        new URLSearchParams({dataset_id:dataset})):Promise.resolve(null),
      json<{reports:Acceptance[]}>('/api/data-manager/research/acceptance/reports')
    ])
    setInfo(summary);setRecent(audits.audits);setEvidenceAudit(evidence);setAcceptanceReports(reports.reports)
  },[dataset])
  useEffect(()=>{
    let live=true
    setInfo(null);setError('')
    void reload().catch(e=>{if(live)setError(e instanceof Error?e.message:String(e))})
    return()=>{live=false}
  },[reload,revision])
  useEffect(()=>{
    if(!job||!['queued','running'].includes(job.status))return
    let live=true
    const timeout=window.setTimeout(()=>{
      void json<Job>('/api/jobs/'+encodeURIComponent(job.id)).then(next=>{
        if(!live)return
        setJob(next)
        if(next.status==='complete'){
          if(next.result&&'blockers' in next.result){
            setAcceptance(next.result as Acceptance)
            setNotice('Real-data acceptance saved. Review the original-source blockers below.')
          }else{
            setNotice('Operation completed. Review the updated evidence and model results.')
          }
          setRevision(x=>x+1)
        }else if(next.status==='error'||next.status==='cancelled'){
          setError(next.error||'Check could not complete; source evidence was preserved.')
        }
      }).catch(e=>{if(live)setError(String(e))})
    },1500)
    return()=>{live=false;window.clearTimeout(timeout)}
  },[job])
  const start=async(which:'verify'|'sync')=>{
    if(busy||(job&&['queued','running'].includes(job.status)))return
    setError('');setNotice('');setBusy(true);setJob(null)
    try{
      const r=await json<{job_id:string;status:string}>(
        which==='verify'?'/api/data-manager/research/verify':'/api/indices/sync',
        which==='verify'?{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({dataset_id:dataset||null,
            include_historical:true,confirm_software_check:true})}:
          {method:'POST'})
      setJob({id:r.job_id,status:r.status})
    }catch(e){setError(e instanceof Error?e.message:String(e))}
    finally{setBusy(false)}
  }
  const runAcceptance=async()=>{
    if(!dataset||!validationStart||!finalTestStart||busy||
      (job&&['queued','running'].includes(job.status)))return
    setBusy(true);setError('');setNotice('');setAcceptance(null);setJob(null)
    try{
      const created=await json<{job_id:string;status:string}>(
        '/api/data-manager/research/acceptance/run',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({dataset_id:dataset,
            validation_start:validationStart,final_test_start:finalTestStart,
            run_models:true,confirm_real_data_audit:true})
        })
      setJob({id:created.job_id,status:created.status})
    }catch(e){setError(e instanceof Error?e.message:String(e))}
    finally{setBusy(false)}
  }
  const openAcceptance=async(id:string)=>{
    setError('')
    try{
      const report=await json<Acceptance>(
        '/api/data-manager/research/acceptance/report/'+encodeURIComponent(id))
      setAcceptance(report)
    }catch(e){setError(e instanceof Error?e.message:String(e))}
  }
  const openExactModel=(id:string)=>{
    try{window.localStorage.setItem('ql-target-model',id)}catch{/* no storage */}
    onModel()
  }
  const active=busy||Boolean(job&&['queued','running'].includes(job.status))
  const shown=info?.models.filter(m=>!onlyBlocked||
    !['source_available','math_ready'].includes(m.status))||[]
  return <section className="qm-panel qm-readiness" aria-label="Research models readiness">
    <div className="qm-panel-title"><h3><FileCheck size={19}/> Research Readiness Center</h3>
      <span>Every registered model · source truth · actionable next step</span></div>
    <p className="qm-caption">QuantLab separates mathematics that runs immediately, observed
      historical data that meets minimum requirements, and data that still needs genuine
      provider evidence. A model passing a software test is <strong>not</strong> proof
      that the associated trading research is historically certified.</p>
    <div className="qm-readiness-controls">
      <label>Original research dataset
        <select aria-label="Readiness research dataset" value={dataset}
          onChange={e=>{setDataset(e.target.value);setNotice('')}}>
          <option value="">No dataset selected (inspect mathematics)</option>
          {datasets.map(d=><option key={d.id} value={d.id}>
            {d.label}{d.kind==='synthetic'?' (synthetic only)':''}</option>)}
        </select></label>
      <button type="button" className="ws-button secondary" onClick={()=>setRevision(x=>x+1)}>
        <RefreshCw size={15}/> Recheck sources</button>
    </div>
    {error&&<div role="alert" className="qm-alert"><AlertTriangle size={16}/>{error}</div>}
    {notice&&<div role="status" className="qm-notice"><CheckCircle2 size={16}/>{notice}</div>}
    {info&&<div className="qm-acquire-metrics">
      <div><small>Algorithms implemented</small><strong>{info.implemented_models}/{info.total_models}</strong></div>
      <div><small>Mathematics runnable</small><strong>{info.math_ready}</strong></div>
      <div><small>Observed-history inputs ready</small><strong>{info.historical_source_ready}</strong></div>
      <div><small>Need original inputs</small><strong>{info.blocked}</strong></div>
    </div>}
    <div className="qm-readiness-action-row">
      <button className="ws-button primary" disabled={active} onClick={()=>void start('verify')}>
        <ShieldCheck size={15}/> {active?'Checking…':'Run model software checks'}</button>
      <button className="ws-button secondary" disabled={active} onClick={()=>void start('sync')}>
        <RefreshCw size={15}/> Sync historical memberships</button>
      <button className="ws-button secondary" onClick={onAcquire}>
        <Database size={15}/> Get missing model inputs <ArrowRight size={14}/></button>
    </div>
    {job&&['queued','running'].includes(job.status)&&<div className="qm-acquire-status" role="status">
      <Clock size={16}/><div><strong>{job.stage||'Running controlled verification'}</strong>
        <small>{Math.round(job.percent||0)}% · {job.id}</small></div></div>}
    {recent.length>0&&<details className="qm-details"><summary>Saved software checks ({recent.length})</summary>
      {recent.slice(0,12).map(a=><div className="qm-file" key={a.id}>
        <span>{a.checked_utc?.slice(0,16)} · {a.dataset_id||'Mathematics'}</span>
        <small>{a.software_pass}/{a.attempted_models} passed · {a.software_fail} failed</small>
      </div>)}</details>}
    {info&&<div className="qm-readiness-evidence">
      <div className="qm-panel-title"><h3>Market-data evidence gates</h3><span>Missing original history is never manufactured</span></div>
      {info.sources.requirements.map(item=><div className="qm-readiness-row" key={item.id}>
        <span className={'qm-badge '+(item.available?'ok':'warn')}>
          {item.available?'Evidence present':'Evidence needed'}</span>
        <div><strong>{item.label}</strong><small>{item.action}</small></div>
        <span className="qm-readiness-external">Not exchange-certified</span>
      </div>)}
      <p className="qm-caption">Historical membership source: {info.sources.membership_status.replaceAll('_',' ')}.
        {info.sources.historical_membership.covered_through&&
          ' Documented coverage through '+info.sources.historical_membership.covered_through+'.'}
        Original index notices, delistings and TRI remain separate research evidence.</p>
    </div>}
    {evidenceAudit&&<details className="qm-details qm-evidence-audit">
      <summary>Detailed PIT, TRI, corporate-action and chronology checks ({evidenceAudit.checks.length})</summary>
      <p className="qm-caption">Research source status: {evidenceAudit.status.replaceAll('_',' ')}.
        Structural computation: {evidenceAudit.structural_run_ready?'locally ready':'inputs incomplete'}.
        Original issuer certification: not granted by software.</p>
      {evidenceAudit.checks.map(check=><div className="qm-readiness-row" key={check.name}>
        <span className={'qm-badge '+(check.status==='pass'?'ok':'warn')}>
          {check.status.replaceAll('_',' ')}</span>
        <div><strong>{check.name}</strong><small>{check.detail}</small>
          {check.next_action&&<small><b>Resolve:</b> {check.next_action}</small>}</div>
      </div>)}
      <p className="qm-caption">{evidenceAudit.warning}</p>
    </details>}
    <div className="qm-readiness-evidence qm-real-acceptance" aria-label="Real data acceptance">
      <div className="qm-panel-title"><h3>End-to-end real-data acceptance</h3>
        <span>Original evidence → chronological holdout → numerical models</span></div>
      <p className="qm-caption">Select your actual historical dataset and dates.
        QuantLab checks source hashes, point-in-time constituents, TRI, corporate
        actions, eligible forward returns and an untouched final-test period,
        then runs every eligible model's software check. A local structural pass
        never claims independent exchange or source certification.</p>
      <div className="qm-readiness-controls">
        <label>Validation begins
          <input type="date" aria-label="Acceptance validation start" value={validationStart}
            onChange={e=>setValidationStart(e.target.value)}/></label>
        <label>Untouched final-test begins
          <input type="date" aria-label="Acceptance final test start" value={finalTestStart}
            onChange={e=>setFinalTestStart(e.target.value)}/></label>
        <button type="button" className="ws-button primary"
          disabled={active||!dataset||!validationStart||!finalTestStart||
            !(validationStart<finalTestStart)}
          onClick={()=>void runAcceptance()}>
          <ShieldCheck size={15}/> Run complete original-data acceptance</button>
      </div>
      <p className="qm-caption">The strict research protocol needs at least 44
        observed training months, a separate validation interval and 12
        genuinely untouched final-test months. Failed checks identify the
        exact original files or observations still required.</p>
      {acceptance&&<div role="status" className="qm-acceptance-report">
        {acceptance.current_source_match===false&&<div className="qm-alert" role="alert">
          <AlertTriangle size={16}/>Original inputs have changed or disappeared since
          this report. Run a new audit; this saved historical result is not current.
        </div>}
        <div className="qm-acquire-metrics">
          <div><small>Historical structural checks</small>
            <strong>{acceptance.source_checks_passed} passed</strong></div>
          <div><small>Source checks blocked</small>
            <strong>{acceptance.source_checks_blocked}</strong></div>
          <div><small>Models passed software QA</small>
            <strong>{acceptance.model_software_pass}</strong></div>
          <div><small>Independent certification</small>
            <strong className="qm-small-stat">Not granted</strong></div>
        </div>
        <strong>Status: {acceptance.status.replaceAll('_',' ')}</strong>
        <div className="qm-readiness-evidence">
          {acceptance.blockers?.map((x,i)=><div className="qm-readiness-row"
            key={x.component+'-'+i}>
            <span className="qm-badge warn">{x.state}</span>
            <div><strong>{x.component}</strong><small>{x.detail}</small>
              <small><b>Next:</b> {x.next_action}</small></div></div>)}
        </div>
        <a className="ws-button secondary" download={acceptance.id+'.json'}
          href={'/api/data-manager/research/acceptance/report/'+encodeURIComponent(acceptance.id)}>
          Save acceptance evidence JSON</a>
        <p className="qm-caption">{acceptance.warning}</p>
      </div>}
      {acceptanceReports.length>0&&<details className="qm-details">
        <summary>Previous genuine-source acceptance reports ({acceptanceReports.length})</summary>
        {acceptanceReports.slice(0,15).map(x=><div className="qm-file" key={x.id}>
          <span>{x.dataset_id} · {x.created_utc.slice(0,16)}</span>
          <small>{x.status.replaceAll('_',' ')} · {x.source_checks_blocked} source blockers</small>
          <button className="ws-button secondary" type="button"
            onClick={()=>void openAcceptance(x.id)}>Review original evidence</button>
        </div>)}
      </details>}
    </div>
    <div className="qm-readiness-model-list">
      <div className="qm-panel-title"><h3>Every model and its next step</h3>
        <label className="qm-check"><input type="checkbox" checked={onlyBlocked}
          onChange={e=>setOnlyBlocked(e.target.checked)}/> Only models needing inputs</label></div>
      {shown.map(m=><div className="qm-readiness-row" key={m.id}>
        <div className="qm-readiness-status-pair">
          <span className={'qm-badge '+(m.implementation_ready?'ok':'warn')}>
            {m.implementation_ready?'Implemented':'Needs implementation'}</span>
          <span className={'qm-badge '+(['source_available','math_ready'].includes(m.status)?'ok':'warn')}>
            {m.status==='math_ready'?'No market source required':
             m.status==='source_available'?'Source available · select exact inputs':
             m.status.replaceAll('_',' ')}</span>
        </div>
        <div><strong>{m.title}</strong>
          <small>{m.group} · {m.detail}</small>
          <small>Minimum: {m.requirement.minimum_observed_returns} returns;
            preferred (+20%): {m.requirement.preferred_with_20_percent}.</small>
          <small><strong>Next:</strong> {m.next_action}</small>
          <details className="qm-model-setup-details">
            <summary>See exactly how to run this model ({m.setup_steps.length} steps)</summary>
            <ol>{m.setup_steps.map((step,i)=><li key={i}>
              <strong>{step.title}</strong> — {step.detail}
              <span>{step.state==='ready'?' · ready':' · action required'}</span>
            </li>)}</ol>
          </details>
        </div>
        <button type="button" className="ws-button secondary"
          onClick={()=>openExactModel(m.id)}>
          {m.mode==='historical'||m.mode==='market'?'Set up & run':'Run mathematics'}
          <ArrowRight size={13}/></button>
      </div>)}
      {!info&&<p className="qm-caption">Inspecting source evidence and model requirements…</p>}
    </div>
  </section>
}
