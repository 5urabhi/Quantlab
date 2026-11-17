import {useCallback, useEffect, useMemo, useState} from 'react'
import {AlertTriangle, ArrowRight, CheckCircle2, Database, Download, LoaderCircle,
  RefreshCw, ShieldCheck} from 'lucide-react'

type Dataset = {id:string;label:string;kind:string}
type Model = {id:string;title:string;group:string;mode:string;min_observations:number}
type Coverage = {
  status:string;runnable:boolean;message?:string;
  min_returns?:number;target_returns?:number;common_returns?:number|null;
  missing_minimum?:number|null;missing_to_target?:number|null;
  missing_uncovered_windows?:number;download_explanation?:string;
  selected_ticker?:string;estimated_vendor_daily_requests?:number
}
type Source = {id:string;label:string;state:string;detail:string}
type Plan = {
  model_id:string;model_title:string;dataset_id:string|null;mode:string;phase:string;
  params:Record<string,number|string>;requirements:Coverage;
  candidate_datasets:{dataset_id:string;label:string;daily_prices:boolean;files_ready:boolean}[];
  source_chain:Source[];next_action:{kind:string;label:string;detail:string};can_acquire:boolean;confirmation_required:boolean;
  estimated_new_dhan_requests:number;preview_token:string;evidence_note:string;
  zerodha_fallback_eligible:boolean;zerodha_fallback_note:string
}
type Job = {id:string;status:string;stage?:string;percent?:number;error?:string;
  result?:{status:string;message:string;dataset_id?:string;selected_ticker?:string;
    warning?:string;missing_to_target?:number}}
type Candidate = {ticker:string;display_name?:string;returns:number;extendable?:boolean}
type ModelInputs = {candidates:Candidate[]}
const api=async<T,>(path:string,init?:RequestInit):Promise<T>=>{
  const res=await fetch(path,init)
  if(!res.ok){
    let message='Request failed ('+res.status+')'
    try{const data=await res.json() as {detail?:string};if(data.detail)message=data.detail}catch{/* intentionally ignore */}
    throw new Error(message)
  }
  return res.json() as Promise<T>
}
export default function DataAcquisitionPanel({datasets,onCompleted,onOpenDhan,onOpenModels}:{
  datasets:Dataset[];onCompleted:(datasetId:string,ticker?:string)=>void;
  onOpenDhan?:()=>void;onOpenModels?:()=>void
}){
  const [models,setModels]=useState<Model[]>([])
  const [modelId,setModelId]=useState('min_variance')
  const [datasetId,setDatasetId]=useState('')
  const [assets,setAssets]=useState(8)
  const [ticker,setTicker]=useState('')
  const [target,setTarget]=useState<'stock'|'benchmark_tri'>('stock')
  const [plan,setPlan]=useState<Plan|null>(null)
  const [candidates,setCandidates]=useState<Candidate[]>([])
  const [busy,setBusy]=useState(false)
  const [working,setWorking]=useState<Job|null>(null)
  const [error,setError]=useState('')
  const [revision,setRevision]=useState(0)
  const [allowZerodha,setAllowZerodha]=useState(false)
  const [runAfter,setRunAfter]=useState(true)
  const selected=useMemo(()=>models.find(m=>m.id===modelId),[models,modelId])
  const isSingle=['gbm_fit','ou_fit','merton_fit','heston_proxy'].includes(modelId)
  const isMarket=selected?.mode==='market'
  useEffect(()=>{
    let live=true
    void api<{models:Model[]}>('/api/data-manager/model-catalog').then(r=>{
      if(live){
        const available=r.models.filter(m=>m.mode==='historical')
        setModels(available)
        if(!available.some(m=>m.id===modelId))setModelId(available[0]?.id||'')
      }
    }).catch(e=>{if(live)setError(e instanceof Error?e.message:String(e))})
    return()=>{live=false}
  },[])
  useEffect(()=>{
    if(!modelId)return
    let live=true
    setPlan(null)
    setError('')
    const qs=new URLSearchParams({model_id:modelId,dataset_id:datasetId,
      assets:String(assets),train_window:'60'})
    if(isSingle){qs.set('target',target);qs.set('ticker',ticker)}
    void api<Plan>('/api/data-manager/acquisition-plan?'+qs.toString()).then(p=>{
      if(live)setPlan(p)
    }).catch(e=>{if(live)setError(e instanceof Error?e.message:String(e))})
    return()=>{live=false}
  },[modelId,datasetId,assets,ticker,target,isSingle,revision])
  useEffect(()=>{
    setCandidates([])
    if(!isSingle||!datasetId||isMarket)return
    let live=true
    void api<ModelInputs>('/api/lab/model-inputs?'+new URLSearchParams({
      dataset_id:datasetId,model_id:modelId}).toString()).then(r=>{
      if(live)setCandidates(r.candidates.slice(0,120))
    }).catch(()=>{/* readiness plan still explains source limitations */})
    return()=>{live=false}
  },[datasetId,modelId,isSingle,isMarket,revision])
  const poll=useCallback((jobId:string)=>{
    let closed=false
    let timer:number|undefined
    const tick=async()=>{
      if(closed)return
      try{
        const next=await api<Job>('/api/jobs/'+encodeURIComponent(jobId))
        if(closed)return
        setWorking(next)
        if(next.status==='complete'){
          setRevision(v=>v+1)
          const output=next.result
          if(output?.dataset_id)onCompleted(output.dataset_id,output.selected_ticker)
          return
        }
        if(next.status==='error'||next.status==='cancelled'){
          setError(next.error||'Data acquisition did not complete; original records remain safe.')
          return
        }
      }catch(e){if(!closed)setError(e instanceof Error?e.message:String(e))}
      timer=window.setTimeout(tick,1600)
    }
    void tick()
    return()=>{closed=true;if(timer!==undefined)window.clearTimeout(timer)}
  },[onCompleted])
  useEffect(()=>{
    if(!working||!['queued','running'].includes(working.status))return
    return poll(working.id)
  },[working?.id,working?.status,poll])
  const start=async()=>{
    if(!plan||(!plan.can_acquire&&!plan.requirements.runnable)||!plan.dataset_id||busy)return
    setError('');setBusy(true);setWorking(null)
    try{
      // This button is the user's explicit authorization. The backend
      // rechecks the source-locked preview before requesting a vendor.
      const data=await api<{job_id:string;status:string}>(
        (runAfter||!plan.can_acquire)?'/api/data-manager/research/resolve-run':
        '/api/data-manager/acquisition/start',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({model_id:plan.model_id,dataset_id:plan.dataset_id,
          params:plan.params,preview_token:plan.preview_token,confirm_download:true,
          confirm_zerodha_fallback:allowZerodha&&plan.zerodha_fallback_eligible,
          prepare_buffer:true})
      })
      setWorking({id:data.job_id,status:data.status})
    }catch(e){setError(e instanceof Error?e.message:String(e))}
    finally{setBusy(false)}
  }
  const loading=!plan&&!error
  const canStart=Boolean(plan?.can_acquire||plan?.requirements.runnable)&&
    !busy&&!(working&&['queued','running'].includes(working.status))
  const showData=plan?.requirements
  return <section className="qm-panel qm-acquire" aria-label="Automatic model data acquisition">
    <div className="qm-panel-title"><h3><Download size={18}/> Get data for a model</h3>
      <span>Inspect → Reuse → Download → Validate</span></div>
    <p className="qm-caption">Choose the research model and source. QuantLab checks the exact input requirements and
      preferred +20% sample automatically; nothing is downloaded until you approve the request.</p>
    <div className="qm-acquire-controls">
      <label>Research model
        <select aria-label="Data acquisition model" value={modelId}
          onChange={e=>{setModelId(e.target.value);setTicker('');setWorking(null);setAllowZerodha(false)}}>
          {models.map(m=><option key={m.id} value={m.id}>{m.title}</option>)}
        </select></label>
      <label>Original dataset
        <select aria-label="Data acquisition dataset" value={datasetId}
          onChange={e=>{setDatasetId(e.target.value);setTicker('');setWorking(null);setAllowZerodha(false)}}>
          <option value="">Choose observed dataset</option>
          {datasets.filter(d=>d.kind!=='synthetic').map(d=><option key={d.id} value={d.id}>{d.label}</option>)}
        </select></label>
      {!isSingle&&<label>Assets to analyze
        <select aria-label="Assets needed" value={assets} onChange={e=>setAssets(Number(e.target.value))}>
          {[2,3,4,5,6,8,10,12,14,16,18].map(n=><option key={n} value={n}>{n} assets</option>)}
        </select></label>}
      {isSingle&&<label>Series type
        <select aria-label="Series type" value={target} onChange={e=>{setTarget(e.target.value as 'stock'|'benchmark_tri');setTicker('')}}>
          <option value="stock">Named stock</option>
          <option value="benchmark_tri">Original total-return index</option>
        </select></label>}
      {isSingle&&target==='stock'&&<label>Stock (never selected silently)
        <select aria-label="Acquisition stock" value={ticker} onChange={e=>setTicker(e.target.value)}>
          <option value="">Choose a stock</option>
          {candidates.map(c=><option key={c.ticker} value={c.ticker}>
            {c.display_name||c.ticker} · {c.returns} valid returns
          </option>)}
        </select></label>}
    </div>
    {loading&&<p className="qm-caption"><LoaderCircle size={14}/> Checking actual model requirements...</p>}
    {error&&<div className="qm-alert" role="alert"><AlertTriangle size={16}/>{error}</div>}
    {showData&&<div className="qm-acquire-result">
      <div className="qm-acquire-metrics">
        <div><small>Valid observed returns</small><strong>{showData.common_returns??'—'}</strong></div>
        <div><small>Minimum required</small><strong>{showData.min_returns??'—'}</strong></div>
        <div><small>Preferred +20%</small><strong>{showData.target_returns??'—'}</strong></div>
        <div><small>Remaining to target</small><strong>{showData.missing_to_target??'—'}</strong></div>
      </div>
      <p className={showData.runnable?'qm-notice':'qm-caption'}>{showData.runnable?<CheckCircle2 size={15}/>:<AlertTriangle size={15}/>}
        {showData.message||'Select a source to calculate exact observed coverage.'}</p>
      {plan&&<div className="qm-source-chain">
        {plan.source_chain.map(source=><div key={source.id}>
          <span className="qm-source-mark"><Database size={14}/></span>
          <span><strong>{source.label}</strong><small>{source.detail}</small></span>
          <span className={'qm-badge '+(source.state==='eligible'||source.state==='available'?'ok':'warn')}>
            {source.state.replaceAll('_',' ')}</span>
        </div>)}
      </div>}
      {(plan?.can_acquire||showData.runnable)&&<div className="qm-acquire-cta">
        <p><ShieldCheck size={15}/> SHA-verified cached Dhan observations are reused first.
          Estimated new provider requests: <strong>{plan.estimated_new_dhan_requests}</strong>.
          No TRI, corporate action or historical index evidence is fabricated.</p>
        {plan.zerodha_fallback_eligible?
          <label className="qm-acquire-provider-consent"><input type="checkbox"
            aria-label="Allow Zerodha fallback" checked={allowZerodha}
            onChange={e=>setAllowZerodha(e.target.checked)}/>
            If Dhan fails, use my locally configured Zerodha Kite Connect market-data entitlement
            (read-only; exact exchange-token/symbol match and Dhan price-overlap checks still required).</label>:
          <p className="qm-caption">{plan.zerodha_fallback_note}</p>}
        <label className="qm-acquire-provider-consent"><input type="checkbox"
          aria-label="Run and save model after data completion" checked={runAfter}
          onChange={e=>setRunAfter(e.target.checked)}/>
          Automatically run the selected model and save source-bound research
          when genuine input requirements are met.</label>
        <button type="button" className="ws-button primary" disabled={!canStart} onClick={()=>void start()}>
          {canStart?<Download size={16}/>:<LoaderCircle size={16}/>}
          {!canStart?'Research operation in progress':
            runAfter?(plan.can_acquire?'Resolve inputs → Run model → Save':
              'Run model and save verified inputs'):
            plan.confirmation_required?'Confirm & get missing Dhan data (+20%)':
            'Reuse saved history and recheck model'}
        </button>
      </div>}
      {!plan?.can_acquire&&!showData.runnable&&<div className="qm-acquire-cta">
        <p>{showData.download_explanation||plan?.next_action.detail||'Use an eligible observed dataset.'}</p>
        {onOpenDhan&&<button type="button" className="ws-button secondary" onClick={onOpenDhan}>
          Open market data downloads <ArrowRight size={15}/></button>}
        {showData.runnable&&onOpenModels&&<button type="button" className="ws-button primary" onClick={onOpenModels}>
          Open Model Laboratory <ArrowRight size={15}/></button>}
      </div>}
    </div>}
    {working&&<div className="qm-acquire-status" role="status"><RefreshCw size={16}/>
      <div><strong>{working.status==='complete'?
          (runAfter?'Model research workflow finished':'Acquisition completed'):
          working.stage||'Preparing and validating observations...'}</strong>
        <small>{Math.round(working.percent??0)}% · {working.id}</small>
        {working.result?.message&&<p>{working.result.message}</p>}
        {working.result?.warning&&<p className="qm-caption">{working.result.warning}</p>}
      </div></div>}
  </section>
}
