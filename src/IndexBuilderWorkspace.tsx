import {useMemo} from 'react'
import {ArrowRight, BarChart3, CheckCircle2, CircleAlert, Database, Play, ShieldCheck, SlidersHorizontal} from 'lucide-react'
import './index-builder.css'

export type IndexBuilderConfig = {
  name:string
  factor_weights:Record<string,number>
  top_n:number
  weighting:string
  max_weight:number
  rebalance_every:number
  cost_bps:number
  execution_lag:number
  momentum_formation:number
  momentum_skip:number
  volatility_lookback:number
  validation_start:string
  final_test_start:string
  sector_cap:number|null
}
export type IndexBuilderSource = {
  id:string
  label:string
  kind:string
  ready:boolean
  missing:string[]
  files:string[]
  has_prices:boolean
  has_daily_prices?:boolean
  monthly_price_observations?:number
  has_fundamentals:boolean
  has_sectors:boolean
  benchmark_kind?:string
  benchmark_is_total_return?:boolean
  independently_verified?:boolean
  basis:string
}
type Props = {
  config:IndexBuilderConfig
  onConfigChange:(value:IndexBuilderConfig)=>void
  datasets:IndexBuilderSource[]
  selectedDataset:string
  onSelectDataset:(id:string)=>void
  busy:boolean
  jobActive:boolean
  onRun:()=>void
  onOpenData:()=>void
  onGetData:()=>void
  onOpenNse:()=>void
  onOpenResults:()=>void
  onOpenStudio:()=>void
}
const FACTORS = [
  {key:'momentum',name:'Momentum',source:'Historical prices',description:'Past relative price strength after a skip window.'},
  {key:'low_volatility',name:'Low volatility',source:'Historical prices',description:'Lower trailing realized return dispersion.'},
  {key:'value',name:'Value',source:'Point-in-time fundamentals',description:'As-published valuation factor observations.'},
  {key:'quality',name:'Quality',source:'Point-in-time fundamentals',description:'As-published profitability/quality observations.'},
  {key:'size',name:'Size',source:'Point-in-time fundamentals',description:'Negative log contemporaneous market capitalization.'},
] as const
const hasFundamentalNeed=(config:IndexBuilderConfig)=>
  ['value','quality','size','yield'].some(key=>(config.factor_weights[key]||0)>0)
const labelMissing=(name:string)=>({
  'prices.csv':'Monthly security prices',
  'membership.csv':'Point-in-time index membership',
  'benchmark.csv':'Compatible benchmark returns',
  'unresolved_historical_index_prices':'Historical constituent prices',
  'missing_eligible_price_observations':'Sufficient eligible member history',
  'unverified_membership_source':'Membership-source provenance',
  'unreadable_membership_provenance':'Readable membership provenance',
  'invalid_benchmark_provenance':'Benchmark-source provenance',
  'unreadable_daily_aggregation_provenance':'Daily-aggregation provenance',
} as Record<string,string>)[name]||name.replaceAll('_',' ')
function Numeric({title,value,onChange,min,max,step=1,help}:{
  title:string;value:number;onChange:(n:number)=>void;min:number;max:number;step?:number;help?:string
}){
  return <label className="idx-field"><span>{title}</span>
    <input type="number" min={min} max={max} step={step} value={value}
      onChange={e=>onChange(Number(e.target.value))}/>
    {help&&<small>{help}</small>}
  </label>
}
export default function IndexBuilderWorkspace({
  config,onConfigChange,datasets,selectedDataset,onSelectDataset,busy,jobActive,
  onRun,onOpenData,onGetData,onOpenNse,onOpenResults,onOpenStudio,
}:Props){
  const source=datasets.find(item=>item.id===selectedDataset)
  const factorTotal=FACTORS.reduce((sum,item)=>sum+(config.factor_weights[item.key]||0),0)
  const selectedFactors=FACTORS.filter(item=>(config.factor_weights[item.key]||0)>0)
  const needsFundamentals=hasFundamentalNeed(config)
  const weightedMethods=['inverse_volatility','minimum_variance','risk_parity']
  const lookback=Math.max(
    (config.factor_weights.momentum||0)>0?config.momentum_formation+config.momentum_skip:0,
    (config.factor_weights.low_volatility||0)>0||weightedMethods.includes(config.weighting)
      ?config.volatility_lookback:0)
  const priceDates=source?.monthly_price_observations||0
  const availableMonths=Math.max(0,priceDates-lookback-config.execution_lag)
  const sourceBlockers=useMemo(()=>{
    const missing=[...(source?.missing||[])]
    if(!source)return ['Select an observed market-data source.']
    if(!source.ready&&!missing.length)missing.push('Required index inputs are incomplete')
    if(needsFundamentals&&!source.has_fundamentals)missing.push('fundamentals.csv')
    if(config.sector_cap!==null&&!source.has_sectors)missing.push('sectors.csv')
    if(config.weighting==='benchmark_relative'&&!source.files.includes('benchmark_weights.csv'))
      missing.push('benchmark_weights.csv')
    return [...new Set(missing)].map(labelMissing)
  },[source,needsFundamentals,config.sector_cap,config.weighting])
  const settingsBlockers=useMemo(()=>{
    const messages:string[]=[]
    if(factorTotal<=0)messages.push('Select at least one factor with a positive contribution.')
    if(config.top_n*config.max_weight<1-1e-10)
      messages.push('Constituents × maximum weight must reach 100%.')
    if(config.momentum_skip>=config.momentum_formation)
      messages.push('Momentum skip must be shorter than formation.')
    if(config.validation_start&&config.final_test_start&&
        config.validation_start>=config.final_test_start)
      messages.push('Validation must begin before the frozen final test.')
    return messages
  },[factorTotal,config])
  const canRun=Boolean(source?.ready&&sourceBlockers.length===0&&
    settingsBlockers.length===0&&!busy&&!jobActive)
  const sourceKind=source?.kind==='synthetic'?'Synthetic demonstration':
    source?.independently_verified?'Source reviewed':'Observed source · not independently reviewed'
  const set=(key:keyof IndexBuilderConfig,value:number|string|null)=>
    onConfigChange({...config,[key]:value})
  const sourceOptions=datasets.filter(item=>
    item.id==='dhan_shared'||item.kind!=='dhan'||item.id===selectedDataset)
  const selectedFactorCount=selectedFactors.length
  const steps=[
    {name:'Choose evidence',ready:!!source?.ready&&sourceBlockers.length===0},
    {name:'Blend factors',ready:factorTotal>0&&(!needsFundamentals||!!source?.has_fundamentals)},
    {name:'Set index rules',ready:settingsBlockers.length===0},
    {name:'Run & analyze',ready:false},
  ]

  return <div className="idx-shell" aria-label="Index Builder workspace">
    <div className="idx-intro">
      <div><span className="idx-eyebrow">EQUITY INDEX CONSTRUCTION / RESEARCH</span>
        <h2>Build a rules-based equity index</h2>
        <p>Choose the historical universe, combine factor signals, set portfolio constraints,
          then backtest against the selected benchmark. Every chart comes from a saved Python run.</p>
      </div>
      <button type="button" className="ws-button secondary" onClick={onOpenStudio}>
        Advanced Index Studio <ArrowRight size={15}/>
      </button>
    </div>
    <nav className="idx-steps" aria-label="Index construction workflow">
      {steps.map((step,i)=><span key={step.name} className={step.ready?'ready':i===3?'last':'pending'}>
        <b>{step.ready?<CheckCircle2 size={16}/>:String(i+1).padStart(2,'0')}</b>{step.name}</span>)}
    </nav>

    <section className="ws-card idx-card" aria-label="Index source and provenance">
      <header className="idx-card-head"><span className="idx-step-number">01</span><div>
        <h3>Choose a market-data source</h3>
        <p>Use one shared library. Historical membership and benchmark evidence are distinct from prices.</p>
      </div></header>
      <div className="idx-source-row">
        <label className="idx-field idx-source-select"><span>Historical index dataset</span>
          <select value={selectedDataset} onChange={e=>onSelectDataset(e.target.value)}
            aria-label="Select research dataset">
            <option value="">Choose a historical source</option>
            {sourceOptions.map(item=><option value={item.id} key={item.id}>
              {item.label}{item.kind==='synthetic'?' (demonstration)':''}</option>)}
          </select>
        </label>
        <div className={'idx-source-state '+(source?.ready?'ready':'blocked')}>
          {source?.ready?<CheckCircle2 size={16}/>:<CircleAlert size={16}/>}
          <div><strong>{source?.ready?'Required source files present':'Source preparation needed'}</strong>
            <span>{sourceKind}</span></div>
        </div>
      </div>
      <div className="idx-source-pills" role="list" aria-label="Source evidence overview">
        <span role="listitem" className={source?.has_prices?'available':''}>
          <b>Prices</b>{source?.has_prices?'Saved':'Missing'}</span>
        <span role="listitem" className={source?.files.includes('membership.csv')?'available':''}>
          <b>Membership</b>{source?.files.includes('membership.csv')?'Saved':'Missing'}</span>
        <span role="listitem" className={source?.files.includes('benchmark.csv')?'available':''}>
          <b>Benchmark</b>{source?.files.includes('benchmark.csv')?'Saved':'Missing'}</span>
        <span role="listitem" className={source?.has_fundamentals?'available':''}>
          <b>Fundamentals</b>{source?.has_fundamentals?'Saved':'Optional / missing'}</span>
      </div>
      <div className="idx-source-actions">
        <button type="button" className="ws-button secondary" onClick={onGetData}>
          <Database size={15}/> Get price history
        </button>
        <button type="button" className="ws-button secondary" onClick={onOpenNse}>
          Historical membership
        </button>
        <button type="button" className="ws-button secondary" onClick={onOpenData}>
          Benchmark & source files
        </button>
      </div>
      {source&&<p className="idx-evidence-note">
        <ShieldCheck size={15}/>{source.basis}
        {!source.benchmark_is_total_return&&
          ' Benchmark total-return status has not been established.'}
      </p>}
      {!!sourceBlockers.length&&<div className="idx-blockers" role="status">
        <strong>What is missing for this configuration?</strong>
        <ul>{sourceBlockers.map((reason,i)=><li key={i}>{reason}</li>)}</ul>
        <p>Price candles can be acquired from authorized providers. Past constituent
          membership, publication-dated fundamentals and official TRI must have their own genuine source evidence.</p>
      </div>}
    </section>

    <section className="ws-card idx-card" aria-label="Index factor research">
      <header className="idx-card-head"><span className="idx-step-number">02</span><div>
        <h3>Choose your factor model</h3>
        <p>Each slider is a relative model contribution, not a forecasted return or portfolio weight.</p>
      </div></header>
      <div className="idx-factor-summary"><strong>{selectedFactorCount} active factor{selectedFactorCount===1?'':'s'}</strong>
        <span>Contributions are normalized to 100% inside the Python score model.</span>
      </div>
      <div className="idx-factor-grid">{FACTORS.map(factor=>{
        const weight=config.factor_weights[factor.key]||0
        const contribution=factorTotal>0?weight/factorTotal*100:0
        const available=!['value','quality','size'].includes(factor.key)||
          Boolean(source?.has_fundamentals)
        return <label className={'idx-factor '+(weight>0?'active ':'')+(available?'':'requires-source')}
          key={factor.key}>
          <span className="idx-factor-name"><strong>{factor.name}</strong>
            <em>{weight>0?contribution.toFixed(0)+'% of blend':'Not included'}</em></span>
          <small>{factor.description}</small>
          <input aria-label={factor.name+' factor contribution'} type="range" min="0" max="1"
            step=".05" value={weight}
            onChange={e=>onConfigChange({...config,
              factor_weights:{...config.factor_weights,[factor.key]:Number(e.target.value)}})}/>
          <span className="idx-factor-footer"><span>Raw contribution: {weight.toFixed(2)}</span>
            <span>{available?factor.source:'Needs publication-dated fundamentals'}</span></span>
        </label>
      })}</div>
      {factorTotal<=0&&<p className="idx-inline-error" role="alert">
        Select at least one positive factor to create a composite score.</p>}
      <p className="idx-evidence-note"><ShieldCheck size={15}/>
        Momentum and volatility use observed price windows. Value, Quality and Size
        require as-of fundamentals; unavailable factors are never silently replaced.</p>
    </section>

    <section className="ws-card idx-card" aria-label="Index construction rules">
      <header className="idx-card-head"><span className="idx-step-number">03</span><div>
        <h3>Define portfolio construction rules</h3>
        <p>Convert factor rankings into holdings with explicit weight caps, rebalancing and costs.</p>
      </div></header>
      <div className="idx-core-form">
        <label className="idx-field"><span>Experiment name</span>
          <input type="text" aria-label="Index experiment name" value={config.name}
            onChange={e=>set('name',e.target.value)}/></label>
        <Numeric title="Constituents (top N)" value={config.top_n} min={2} max={300}
          onChange={v=>set('top_n',v)}/>
        <label className="idx-field"><span>Portfolio weighting</span>
          <select value={config.weighting} onChange={e=>set('weighting',e.target.value)}>
            {[['equal','Equal weight'],['score','Factor score'],
              ['inverse_volatility','Inverse volatility'],['minimum_variance','Minimum variance'],
              ['risk_parity','Risk parity'],['benchmark_relative','Benchmark-relative optimizer']
            ].map(([value,name])=><option value={value} key={value}>{name}</option>)}
          </select></label>
        <Numeric title="Maximum weight per stock" value={config.max_weight}
          min={.01} max={1} step={.01} onChange={v=>set('max_weight',v)}
          help={(config.max_weight*100).toFixed(1)+'% maximum of index capital'}/>
        <Numeric title="Rebalance every (months)" value={config.rebalance_every}
          min={1} max={12} onChange={v=>set('rebalance_every',v)}/>
        <Numeric title="Transaction cost (basis points)" value={config.cost_bps}
          min={0} max={500} step={5} onChange={v=>set('cost_bps',v)}
          help="10 bps = 0.10% per traded notional unit."/>
      </div>
      <div className="idx-execution-box">
        <label className="idx-field"><span>Execution timing</span><select
          value={String(config.execution_lag)}
          onChange={e=>set('execution_lag',Number(e.target.value))}>
          <option value="1">Next-month execution (more conservative)</option>
          <option value="0">Same-close execution (idealized)</option>
        </select></label>
        <p>Weights are recalculated on scheduled rebalance dates and drift between them.
          Monthly data cannot establish actual intraday fills.</p>
      </div>
      {config.top_n*config.max_weight<1-1e-10&&
        <div className="idx-inline-error" role="alert">These weight caps cannot form a 100% invested index.
          <button type="button" onClick={()=>set('max_weight',Math.ceil(100/config.top_n)/100)}>
            Use a feasible cap ({Math.ceil(100/config.top_n)}%)
          </button>
        </div>}
      <details className="idx-advanced">
        <summary><SlidersHorizontal size={15}/> Advanced lookbacks, holdout and sector limits</summary>
        <div className="idx-core-form">
          <Numeric title="Momentum formation (months)" value={config.momentum_formation}
            min={2} max={60} onChange={v=>set('momentum_formation',v)}/>
          <Numeric title="Momentum skip (months)" value={config.momentum_skip}
            min={0} max={12} onChange={v=>set('momentum_skip',v)}/>
          <Numeric title="Volatility lookback (months)" value={config.volatility_lookback}
            min={3} max={60} onChange={v=>set('volatility_lookback',v)}/>
          <label className="idx-field"><span>Validation starts (optional)</span>
            <input type="date" value={config.validation_start}
              onChange={e=>set('validation_start',e.target.value)}/></label>
          <label className="idx-field"><span>Frozen final test starts (optional)</span>
            <input type="date" value={config.final_test_start}
              onChange={e=>set('final_test_start',e.target.value)}/></label>
          <label className="idx-field idx-inline-checkbox"><span>Historical sector cap</span>
            <input type="checkbox" checked={config.sector_cap!==null}
              onChange={e=>set('sector_cap',e.target.checked?.4:null)}/>
            <small>Needs genuine as-of sectors.csv</small></label>
          {config.sector_cap!==null&&<Numeric title="Sector weight cap" value={config.sector_cap}
            min={.1} max={1} step={.05} onChange={v=>set('sector_cap',v)}/>}
        </div>
      </details>
    </section>

    <section className="ws-card idx-card idx-run-card" aria-label="Index backtest readiness and run">
      <header className="idx-card-head"><span className="idx-step-number">04</span><div>
        <h3>Validate inputs and run your index</h3>
        <p>Python checks the actual historical source and saves an auditable result only after calculation.</p>
      </div></header>
      <div className="idx-run-metrics">
        <div><small>Saved monthly price dates</small><strong>{priceDates||'—'}</strong></div>
        <div><small>Warm-up months</small><strong>{lookback}</strong></div>
        <div><small>Possible evaluated months</small><strong>{source?availableMonths:'—'}</strong></div>
        <div><small>Factor blend</small><strong>{factorTotal>0?'Defined':'Missing'}</strong></div>
      </div>
      {availableMonths<12&&!!source&&<p className="idx-warning" role="status">
        <CircleAlert size={16}/> This configuration may have fewer than 12 evaluated months.
        Sharpe, CAGR, tracking error and inference may be insufficient or exploratory.
        Extend source history before treating results as empirical evidence.</p>}
      {settingsBlockers.length>0&&<div className="idx-blockers" role="alert">
        <strong>Fix these rules before running:</strong>
        <ul>{settingsBlockers.map(item=><li key={item}>{item}</li>)}</ul></div>}
      <div className="idx-final-actions">
        <button type="button" className="ws-button primary" onClick={onRun}
          disabled={!canRun}><Play size={16}/> Build & backtest index</button>
        <button type="button" className="ws-button secondary" onClick={onOpenResults}>
          <BarChart3 size={16}/> See saved results</button>
        {!canRun&&<span role="status">{busy?'Working…':jobActive?'A research job is already running.':
          sourceBlockers.length?'Complete source evidence above.':
          settingsBlockers.length?'Correct the indicated model rules.':
          'Choose original data.'}</span>}
      </div>
      <p className="idx-evidence-note"><ShieldCheck size={15}/>
        Backtests use the selected dataset, genuine membership and the recorded benchmark.
        An available source does not prove licensed index methodology, adjusted total returns,
        point-in-time completeness or out-of-sample alpha.</p>
    </section>
  </div>
}
