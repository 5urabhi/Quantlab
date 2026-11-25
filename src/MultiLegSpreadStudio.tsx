import {useCallback,useEffect,useMemo,useState} from 'react'
import {Download,RefreshCw,Save,ShieldAlert,Trash2} from 'lucide-react'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
import type {BrokerProfile} from './SpreadOpportunityScanner'
import SpreadExecutionDecision,{type ExecutionDecision} from './SpreadExecutionDecision'
import './multi-leg-spreads.css'
import ResearchPlot from './ResearchPlots'
import {openSnapshotInPython,type PythonSnapshot} from './pythonBridge'
import SavedScriptRunner from './SavedScriptRunner'

type StrategyKey='bull_call_debit'|'bear_put_debit'|'bull_put_credit'|'bear_call_credit'|'iron_condor'|'iron_butterfly'
type Strategy={key:StrategyKey;label:string;group:string;roles:string[];actions:('BUY'|'SELL')[];sides:('CE'|'PE')[];qualified_candidates:number}
type Contract={identity:string;expiry:string;strike:number;option_type:'CE'|'PE';lot_size:number;received_utc:string;bid:number;ask:number;spread_bps:number}
type Leg={role:string;identity:string;action:'BUY'|'SELL';expiry:string;option_type:'CE'|'PE';strike:number;lots:number;units:number;lot_size:number;saved_utc:string;best_bid:number;best_ask:number;spread_bps:number;entry_vwap:number;exit_vwap:number;entry_premium_turnover_inr:number;entry_depth_levels_used:number;original_depth_verified:boolean}
type Point={underlying:number;net_payoff_inr:number}
type Candidate={candidate_id:string;strategy:StrategyKey;label:string;group:string;expiry:string;lots:number;units:number;legs:Leg[];quote_skew_seconds:number;entry_premium_cashflow_inr:number;entry_fees_inr:number;exit_fees_if_immediate_inr:number;estimated_same_book_immediate_roundtrip_net_inr:number;max_profit_inr:number;max_loss_inr:number;risk_capital_proxy_inr:number;risk_reward_ratio_proxy:number;break_even_underlying:number[];payoff_points:Point[];source_age_seconds?:number;fresh_reference?:boolean;research_priority_score?:number;broker_margin_verified:false;status:string;payoff_model:string;read_only:true
  paper_research_qualified?:boolean;feasibility?:{
    paper_research_qualified:boolean;reasons:string[];research_priority_score:number|null
    status:string;broker_margin_verified:boolean;required_broker_margin_inr:null}}
type Scan={day_ist:string;valid_unique_contracts:number;original_depth_id_count:number;discovered_candidates:number;returned_candidates:number;strategies:Strategy[];available_contracts:Contract[];ranked_candidates:Candidate[];rejected_reason_counts:Record<string,number>;warning:string
  execution_decision?:ExecutionDecision;execution_policy?:Record<string,number>}
type Page='discover'|'builder'|'analysis'|'notebook'
type Sort='priority'|'maximum_profit'|'reward_risk'|'minimum_loss'|'exit_cost'|'quote_skew'
type Saved={id:string;title:string;date:string;expiry:string;lots:number;gain:number;loss:number;legs:string[]}
const STORE='quantlab:spread-research:notebook:v1'
const money=(v:number|null|undefined)=>typeof v==='number'&&Number.isFinite(v)?'₹'+v.toLocaleString('en-IN',{minimumFractionDigits:2,maximumFractionDigits:2}):'—'
const n=(v:number|null|undefined,p=0)=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('en-IN',{maximumFractionDigits:p}):'—'
const time=(v:string|null|undefined)=>v?new Date(v).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}):'—'
function loadSaved():Saved[]{try{const v:unknown=JSON.parse(localStorage.getItem(STORE)||'[]');return Array.isArray(v)?(v as Saved[]).slice(0,40):[]}catch{return []}}
function Metric({name,value,detail}:{name:string;value:string;detail:string}){return <div className="ml-metric"><small>{name}</small><strong>{value}</strong><span>{detail}</span></div>}
function PayoffChart({points,breakEven=[]}:{points:Point[];breakEven?:number[]}){
  if(!points.length)return <p>Payoff points unavailable.</p>
  return <div className="ml-chart"><ResearchPlot plot={{kind:'line2d',title:'Theoretical expiration payoff curve, excluding exercise and settlement costs',x_label:'BANKNIFTY expiry level (points)',y_label:'Terminal net payoff (₹)',x:points.map(p=>p.underlying),traces:[{name:'Theoretical net payoff',y:points.map(p=>p.net_payoff_inr)}],reference_lines:[{value:0,label:'Break-even payoff'}],point_markers:breakEven.filter(b=>points.some(p=>p.underlying===b)).map(b=>({x:b,y:0,label:'Break-even',color:'#f5c542'}))}} provenance="theoretical" formatY={money}/><p>Hypothetical terminal payoffs, not current prices, actual fills or verified broker margin.</p></div>
}
export default function MultiLegSpreadStudio({day,expiry,brokerProfile,onBrokerProfileChange}:{day:string;expiry:string;brokerProfile:BrokerProfile;onBrokerProfileChange:(v:BrokerProfile)=>void}){
  const [page,setPage]=useState<Page>('discover')
  const [capital,setCapital]=useState(50000)
  const [lots,setLots]=useState(5)
  const [skew,setSkew]=useState(10)
  const [age,setAge]=useState(60)
  const [data,setData]=useState<Scan|null>(null)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [refresh,setRefresh]=useState(0)
  const [filter,setFilter]=useState<StrategyKey|'all'>('all')
  const [sort,setSort]=useState<Sort>('priority')
  const [freshOnly,setFreshOnly]=useState(false)
  const [qualifiedOnly,setQualifiedOnly]=useState(false)
  const [selectedId,setSelectedId]=useState('')
  const [manual,setManual]=useState<Candidate|null>(null)
  const [detail,setDetail]=useState<'payoff'|'legs'|'risk'>('payoff')
  const [buildStrategy,setBuildStrategy]=useState<StrategyKey>('bull_call_debit')
  const [buildIds,setBuildIds]=useState<string[]>([])
  const [buildLots,setBuildLots]=useState(1)
  const [evaluating,setEvaluating]=useState(false)
  const [saved,setSaved]=useState<Saved[]>(loadSaved)
  const scan=useCallback(async()=>{
    setBusy(true);setError('')
    try{
      const params=new URLSearchParams({day,capital_inr:String(capital),max_lots:String(lots),broker_profile:brokerProfile,max_quote_skew_seconds:String(skew),max_source_age_seconds:String(age),limit:'200'})
      const result=await marketApi<Scan>('/api/trading-cockpit/spreads/multileg/scan?'+params)
      setData(result)
      setSelectedId(current=>result.ranked_candidates.some(x=>x.candidate_id===current)?current:result.ranked_candidates[0]?.candidate_id||'')
    }catch(e){setError(readableError(e))}
    finally{setBusy(false)}
  },[day,capital,lots,brokerProfile,skew,age])
  useEffect(()=>{const t=window.setTimeout(()=>{if(!document.hidden)void scan()},300);return()=>window.clearTimeout(t)},[scan,refresh])
  useEffect(()=>{const t=window.setInterval(()=>{if(!document.hidden)setRefresh(v=>v+1)},90000);return()=>window.clearInterval(t)},[])
  const candidates=useMemo(()=>{
    const output=(data?.ranked_candidates||[]).filter(x=>(filter==='all'||x.strategy===filter)&&
      (!expiry||x.expiry===expiry)&&(!freshOnly||x.fresh_reference)&&
      (!qualifiedOnly||x.paper_research_qualified))
    const val=(x:Candidate)=>{
      if(sort==='maximum_profit')return x.max_profit_inr
      if(sort==='reward_risk')return x.risk_reward_ratio_proxy
      if(sort==='minimum_loss')return x.max_loss_inr
      if(sort==='exit_cost')return x.estimated_same_book_immediate_roundtrip_net_inr
      if(sort==='quote_skew')return x.quote_skew_seconds
      return x.research_priority_score||0
    }
    return output.sort((a,b)=>Number(!!b.paper_research_qualified)-
      Number(!!a.paper_research_qualified)||
      Number(!!b.fresh_reference)-Number(!!a.fresh_reference)||(sort==='minimum_loss'||sort==='quote_skew'?val(a)-val(b):val(b)-val(a))||a.candidate_id.localeCompare(b.candidate_id))
  },[data,filter,expiry,freshOnly,qualifiedOnly,sort])
  const candidateSnapshot=useMemo<PythonSnapshot|null>(()=>candidates.length?{title:'Defined-risk spread candidates · '+day,provenance:'Original saved-book calculations, broker '+brokerProfile+'; research only, margin unverified',columns:['Candidate ID','Strategy','Lots','Maximum profit (₹)','Maximum loss (₹)','Risk capital proxy (₹)','Risk reward proxy','Immediate roundtrip net (₹)','Quote skew (s)','Paper gate qualified','Source legs and receipt times'],rows:candidates.map(c=>[c.candidate_id,c.label,c.lots,c.max_profit_inr,c.max_loss_inr,c.risk_capital_proxy_inr,c.risk_reward_ratio_proxy,c.estimated_same_book_immediate_roundtrip_net_inr,c.quote_skew_seconds,!!c.paper_research_qualified,c.legs.map(l=>l.identity+' '+l.saved_utc).join('; ')])}:null,[candidates,day,brokerProfile])
  const selected=manual||data?.ranked_candidates.find(x=>x.candidate_id===selectedId)||candidates[0]||null
  const spec=data?.strategies.find(x=>x.key===buildStrategy)
  const persist=(items:Saved[])=>{setSaved(items);try{localStorage.setItem(STORE,JSON.stringify(items))}catch{/* storage unavailable */}}
  const selectCandidate=(item:Candidate)=>{setManual(null);setSelectedId(item.candidate_id);setPage('analysis');setDetail('payoff')}
  const openBuilder=()=>{if(selected){setBuildStrategy(selected.strategy);setBuildIds(selected.legs.map(l=>l.identity));setBuildLots(selected.lots)}setPage('builder')}
  const evaluate=async()=>{
    if(!spec||buildIds.length!==spec.roles.length||buildIds.some(id=>!id)){setError('Choose each exact verified option leg.');return}
    setEvaluating(true);setError('')
    try{
      const item=await marketPost<Candidate>('/api/trading-cockpit/spreads/multileg/evaluate',{day,strategy:buildStrategy,identities:buildIds,lots:buildLots,broker_profile:brokerProfile,max_quote_skew_seconds:skew,capital_inr:capital})
      setManual(item);setPage('analysis');setDetail('legs')
    }catch(e){setError(readableError(e))}
    finally{setEvaluating(false)}
  }
  const save=()=>{if(!selected)return;const obs:Saved={id:selected.candidate_id,title:selected.label,date:new Date().toISOString(),expiry:selected.expiry,lots:selected.lots,gain:selected.max_profit_inr,loss:selected.max_loss_inr,legs:selected.legs.map(l=>l.action+' '+l.strike+' '+l.option_type+' '+l.identity)};persist([obs,...saved.filter(x=>x.id!==obs.id)].slice(0,40))}
  const download=()=>{const blob=new Blob([JSON.stringify({note:'Research snapshots only; no orders or fills',items:saved},null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='quantlab-spread-research.json';a.click();window.setTimeout(()=>URL.revokeObjectURL(url),1000)}
  return <section className="ml-studio" aria-label="BANKNIFTY multi-leg option spreads">
    <header className="ml-head"><div><div className="ml-overline">BANKNIFTY · AUTOMATIC STRATEGY ENGINE</div>
      <h3>Multi-Leg Option Spreads</h3><p>Automatically discover vertical debit/credit spreads, iron condors and butterflies. Manual contract selection is optional. <b>Structural payoffs are not profit predictions.</b></p></div>
      <button className="ml-btn" type="button" onClick={()=>setRefresh(v=>v+1)} disabled={busy}><RefreshCw size={15}/>{busy?'Scanning…':'Rescan'}</button></header>
    <div className="ml-warning"><ShieldAlert size={18}/><span><b>No live orders or inferred fills.</b> Zerodha required/final basket margin is not available from saved Dhan depth; maximum strategy loss is only a capital-at-risk proxy. The model excludes settlement/exercise effects. All legs must use original source books.</span></div>
    <nav className="ml-tabs" aria-label="Multi-leg modules">
      {([['discover','Auto Discover'],['builder','Build & Modify'],['analysis','Payoff & Execution'],['notebook','Research Notebook']] as const).map(([id,label])=><button key={id} type="button" className={page===id?'active':''} aria-current={page===id?'page':undefined} onClick={()=>setPage(id)}>{label}</button>)}
    </nav>
    <div className="ml-controls">
      <label>Maximum loss proxy budget (₹)<input type="number" min="1000" max="10000000" step="1000" value={capital} onChange={e=>setCapital(Math.min(10000000,Math.max(1000,Number(e.target.value)||1000)))}/></label>
      <label>Auto-test up to lots<select value={lots} onChange={e=>setLots(Number(e.target.value))}>{[1,2,3,4,5,6,7,8,9,10].map(x=><option key={x} value={x}>{x}</option>)}</select></label>
      <label>Quote skew display limit (s)<input type="number" min="0" max="120" value={skew} onChange={e=>setSkew(Math.max(0,Math.min(120,Number(e.target.value)||0)))}/></label>
      <label>Freshness display limit (s)<input type="number" min="1" max="3600" value={age} onChange={e=>setAge(Math.max(1,Math.min(3600,Number(e.target.value)||1)))}/></label>
      <label>Broker fee schedule<select value={brokerProfile} onChange={e=>onBrokerProfileChange(e.target.value as BrokerProfile)}><option value="zerodha">Zerodha standard</option><option value="zerodha_debit_balance">Zerodha special</option><option value="dhan">Dhan</option></select></label>
    </div>
    {error&&<p className="ml-error" role="alert">{error}</p>}
    {busy&&<p className="ml-muted" role="status">Checking all synchronized saved source combinations…</p>}
    <div className="ml-summary">
      <Metric name="Original-depth contracts" value={n(data?.valid_unique_contracts)} detail="Validated source IDs"/>
      <Metric name="Structurally modeled spreads" value={n(data?.discovered_candidates)} detail="Some are rejected by evidence gate"/>
      <Metric name="Paper-study qualified" value={n(data?.execution_decision?.paper_research_candidates)} detail="NOT a profitability guarantee"/>
      <Metric name="Broker margin / fills" value="Not verified" detail="No live trade authorization"/></div>
    <SpreadExecutionDecision decision={data?.execution_decision}
      scope="Multi-leg options"/>
    <p className="ml-muted">Hard execution-quality gate: each leg ≤8s old,
      quote skew ≤2s, ≥3 saved packets over ≥15s, ≥2 source trade
      times with ≥1 lot of volume growth per leg, sufficient top-level
      depth, narrow relative spreads, and maximum theoretical
      loss ≤25% of the entered capital. Changing the display windows above
      does not override these safety screens.</p>
    {page==='discover'&&<>
      <div className="ml-section"><h4>Automatic research short-list</h4><p>The system chooses a defined-risk structure and lot size without asking you to pick strikes.</p></div>
      <div className="ml-top">
        {candidates.filter(x=>x.paper_research_qualified).slice(0,3).map((item,i)=>
          <button type="button" key={item.candidate_id} onClick={()=>selectCandidate(item)}>
          <small>RESEARCH RANK #{i+1} · {item.fresh_reference?'RECENT SOURCE':'ARCHIVED SOURCE'}</small>
          <strong>{item.label}</strong><span>{item.expiry} · {item.lots} lot(s)</span>
          <span>Max terminal gain {money(item.max_profit_inr)}</span>
          <span>Max terminal loss {money(item.max_loss_inr)} · score {n(item.research_priority_score,1)}</span>
        </button>)}
        {!candidates.some(x=>x.paper_research_qualified)&&
          <p className="ml-empty"><b>NO TRADE:</b> no spread passes the
            strict execution-quality screen. Review rejected reasons in
            the table below. A theoretical maximum profit is not evidence
            of executable earnings.</p>}
      </div>
      <div className="ml-filters">
        <label>Strategy<select value={filter} onChange={e=>setFilter(e.target.value as StrategyKey|'all')}><option value="all">All six strategies</option>{data?.strategies.map(x=><option key={x.key} value={x.key}>{x.label} ({x.qualified_candidates})</option>)}</select></label>
        <label>Sort by<select value={sort} onChange={e=>setSort(e.target.value as Sort)}><option value="priority">Research priority</option><option value="maximum_profit">Max theoretical gain</option><option value="reward_risk">Terminal reward / loss</option><option value="minimum_loss">Smallest terminal loss</option><option value="exit_cost">Least immediate exit drag</option><option value="quote_skew">Smallest quote skew</option></select></label>
        <label className="ml-check"><input type="checkbox" checked={freshOnly}
          onChange={e=>setFreshOnly(e.target.checked)}/>Only fresh saved quotes</label>
        <label className="ml-check"><input type="checkbox" checked={qualifiedOnly}
          onChange={e=>setQualifiedOnly(e.target.checked)}/>Only paper-study qualified</label>
      </div>
      <div className="ml-actions"><button type="button" className="ml-btn" disabled={!candidateSnapshot} onClick={()=>candidateSnapshot&&openSnapshotInPython(candidateSnapshot)}>Analyze / score spreads in Python</button></div>
      <details className="ql-saved-runner-wrap"><summary>Custom saved spread scanner</summary><SavedScriptRunner kind="scanner" snapshot={candidateSnapshot} automatic onInspect={id=>{const candidate=candidates.find(c=>c.candidate_id===id);if(candidate)selectCandidate(candidate)}}/></details>
      <div className="ml-scroll"><table className="ml-table"><thead><tr>
        <th>Rank / strategy</th><th>Legs</th><th>Lots</th><th>Premium entry ±</th><th>Entry costs</th><th>Max terminal gain</th><th>Max terminal loss</th><th>Reward / loss</th><th>Immediate round trip</th><th>Source</th><th>Feasibility</th><th></th>
      </tr></thead><tbody>{candidates.map((x,i)=><tr key={x.candidate_id}>
        <td><b>#{i+1} {x.label}</b><small>{x.expiry}</small></td>
        <td>{x.legs.map(l=><small key={l.identity}>{l.action} {n(l.strike)} {l.option_type}</small>)}</td>
        <td>{x.lots}</td><td>{money(x.entry_premium_cashflow_inr)}</td><td>{money(x.entry_fees_inr)}</td>
        <td className="ml-amber">{money(x.max_profit_inr)}<small>Terminal bound only</small></td>
        <td className="ml-negative">{money(x.max_loss_inr)}</td><td>{n(x.risk_reward_ratio_proxy,2)}×</td>
        <td className="ml-negative">{money(x.estimated_same_book_immediate_roundtrip_net_inr)}</td>
        <td>{x.fresh_reference?'Recent reference':'Archive only'}<small>{n(x.quote_skew_seconds,2)}s skew</small></td>
        <td className={x.paper_research_qualified?'ml-amber':'ml-negative'}>
          {x.paper_research_qualified?'PAPER ONLY':'NO TRADE'}
          <small className="ml-gate-reasons">{x.feasibility?.reasons.slice(0,3)
            .map(v=>v.replaceAll('_',' ')).join(' · ')||
            'No calibrated execution or margin'}</small></td>
        <td><button type="button" className="ml-small" onClick={()=>selectCandidate(x)}>Analyze</button></td></tr>)}
        {!candidates.length&&<tr><td colSpan={12}>No synchronized, verified candidates. Adjust date, filters, or collect source depth.</td></tr>}
      </tbody></table></div>
      <p className="ml-muted">{data?.warning}</p>
    </>}
    {page==='builder'&&<>
      <div className="ml-section"><h4>Optional source-verified leg builder</h4><p>Auto Discover is the default. Edit the contracts only when you want to test another defined-risk shape.</p></div>
      <div className="ml-controls"><label>Structure<select value={buildStrategy} onChange={e=>{setBuildStrategy(e.target.value as StrategyKey);setBuildIds([])}}>{data?.strategies.map(x=><option key={x.key} value={x.key}>{x.label}</option>)}</select></label>
        <label>Lots<select value={buildLots} onChange={e=>setBuildLots(Number(e.target.value))}>{[1,2,3,4,5,6,7,8,9,10].map(x=><option key={x} value={x}>{x}</option>)}</select></label></div>
      <div className="ml-builder">{spec?.roles.map((role,i)=><label key={i}>{i+1}. {role}
        <select value={buildIds[i]||''} onChange={e=>setBuildIds(prev=>{const next=Array.from({length:spec.roles.length},(_,k)=>prev[k]||'');next[i]=e.target.value;return next})}>
          <option value="">Select exact {spec.sides[i]} source contract</option>
          {data?.available_contracts.filter(x=>x.option_type===spec.sides[i]&&(!expiry||x.expiry===expiry)).sort((a,b)=>a.strike-b.strike).map(c=><option key={c.identity} value={c.identity}>{c.expiry} · {c.strike} {c.option_type} · {c.identity} · {n(c.bid,2)} / {n(c.ask,2)}</option>)}
        </select></label>)}</div>
      <div className="ml-actions"><button type="button" className="ml-btn primary" disabled={evaluating} onClick={()=>void evaluate()}>{evaluating?'Evaluating…':'Evaluate source-defined legs'}</button><button type="button" className="ml-btn" onClick={()=>setPage('discover')}>Back to automatic shortlist</button></div>
      <p className="ml-muted">The backend rejects wrong strike order, mixed expiry or lot sizes, insufficient depth and unsynchronized quotes. No simulated fills are recorded as trades.</p>
    </>}
    {page==='analysis'&&<>{selected?<>
      <div className="ml-section"><h4>{selected.label}</h4><p>{selected.expiry} · {selected.lots} lot(s) · {selected.legs.length} legs · quote skew {n(selected.quote_skew_seconds,2)}s</p>
        <div className="ml-actions"><button type="button" className="ml-btn" onClick={openBuilder}>Modify legs</button><button type="button" className="ml-btn" onClick={save}><Save size={14}/>Save research snapshot</button></div></div>
      <div className="ml-warning"><ShieldAlert size={16}/>
        <span><b>NO TRADE.</b> This structure is {
          selected.paper_research_qualified?'paper-research qualified only':
          'blocked by execution-quality evidence'}. {
          selected.feasibility?.reasons.join(' · ').replaceAll('_',' ')||
          'No verified fills or broker basket margin'}.
          The theoretical payoff must not be used as a live profitability forecast.</span>
      </div>
      <div className="ml-detail-tabs">{([['payoff','Payoff'],['legs','Legs & Charges'],['risk','Execution Safety']] as const).map(([id,label])=><button type="button" key={id} className={detail===id?'active':''} onClick={()=>setDetail(id)}>{label}</button>)}</div>
      <div className="ml-summary">
        <Metric name="Max theoretical gain" value={money(selected.max_profit_inr)} detail="Not expected profit"/>
        <Metric name="Max theoretical loss" value={money(selected.max_loss_inr)} detail="Before exercise/settlement"/>
        <Metric name="Loss budget proxy" value={money(selected.risk_capital_proxy_inr)} detail="Not broker margin"/>
        <Metric name="Cross and immediately exit" value={money(selected.estimated_same_book_immediate_roundtrip_net_inr)} detail="Both legs assumed against one saved book"/>
      </div>
      {detail==='payoff'&&<><PayoffChart key={selected.candidate_id} points={selected.payoff_points} breakEven={selected.break_even_underlying}/><p className="ml-muted">Break-even underlying: {selected.break_even_underlying.length?selected.break_even_underlying.map(v=>n(v,2)).join(' / '):'Unavailable'}. {selected.payoff_model}</p></>}
      {detail==='legs'&&<><div className="ml-scroll"><table className="ml-table"><thead><tr><th>Role</th><th>Contract</th><th>Saved bid / ask</th><th>Entry VWAP</th><th>Close VWAP</th><th>Turnover</th><th>Levels</th></tr></thead><tbody>{selected.legs.map(l=><tr key={l.identity}>
        <td>{l.role}<small>{l.action} {l.units} units</small></td>
        <td>{n(l.strike)} {l.option_type}<small>{l.identity} · {time(l.saved_utc)} IST</small></td>
        <td>{money(l.best_bid)} / {money(l.best_ask)}</td><td>{money(l.entry_vwap)}</td>
        <td>{money(l.exit_vwap)}</td><td>{money(l.entry_premium_turnover_inr)}</td>
        <td>{l.entry_depth_levels_used}</td></tr>)}</tbody></table></div>
        <div className="ml-summary">
          <Metric name="Entry credit (+) / debit (−)" value={money(selected.entry_premium_cashflow_inr)} detail="Marketable quotes, not filled"/>
          <Metric name="Entry charges" value={money(selected.entry_fees_inr)} detail="Estimated multi-leg Zerodha/Dhan fees"/>
          <Metric name="Immediate exit charges" value={money(selected.exit_fees_if_immediate_inr)} detail="No future quote assumed"/>
          <Metric name="Quote skew" value={n(selected.quote_skew_seconds,2)+'s'} detail="Source receive times differ"/>
        </div></>}
      {detail==='risk'&&<div className="ml-risk">
        <p><b>Shared execution gate:</b> {selected.feasibility?.reasons.length?
            selected.feasibility.reasons.map(x=>x.replaceAll('_',' ')).join(' · '):
            'Source screen passed for paper research only'}.
          This is not a measure of win probability or expected P&amp;L.</p>
        <p><b>Broker required and final margin:</b> NOT VERIFIED. A defined maximum payoff loss is not an approved Zerodha margin quote.</p>
        <p><b>Partial fills:</b> Individual basket orders can partially fill, reject, or leave temporary unhedged positions. No fill/queue probability is calibrated.</p>
        <p><b>Expiry and taxes:</b> Terminal payoff excludes expiry exercise and settlement charges. Do not treat expiry payoff as exact net cash realization.</p>
        <p><b>Execution sequence:</b> Check broker basket margin with protective long option hedges placed before selling short options when supported by the broker.</p>
        <p><b>Verification:</b> All candidate legs use validated original 20-level depth, but no order has been sent.</p></div>}
      </>:<p className="ml-empty">No qualified strategy. Open Auto Discover to review source coverage.</p>}</>}
    {page==='notebook'&&<>
      <div className="ml-section"><h4>Research notebook</h4><p>Browser-local observations; no paper or real fills are claimed.</p>
        <button type="button" className="ml-btn" disabled={!saved.length} onClick={download}><Download size={14}/>Export JSON</button></div>
      <div className="ml-scroll"><table className="ml-table"><thead><tr><th>Saved</th><th>Structure</th><th>Expiry</th><th>Lots</th><th>Max gain</th><th>Max loss</th><th>Legs</th><th/></tr></thead><tbody>{saved.map(item=><tr key={item.id}>
        <td>{time(item.date)}</td><td>{item.title}</td><td>{item.expiry}</td><td>{item.lots}</td><td>{money(item.gain)}</td><td>{money(item.loss)}</td><td>{item.legs.map(l=><small key={l}>{l}</small>)}</td>
        <td><button type="button" className="ml-small" onClick={()=>persist(saved.filter(v=>v.id!==item.id))}><Trash2 size={13}/>Remove</button></td></tr>)}
        {!saved.length&&<tr><td colSpan={8}>No saved research observations. Analyze a candidate and choose Save.</td></tr>}</tbody></table></div>
    </>}
  </section>
}
