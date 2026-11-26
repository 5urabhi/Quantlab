import {useMemo,useState} from 'react'
import ResearchPlot,{type ResearchPlotData} from './ResearchPlots'
import './saved-index-analytics.css'

type Row=Record<string,unknown>
export type AnalyticsRoute='factors'|'construction'|'risk'|'rolling'|'robustness'|'comparisons'|'visual'
type Detail={id:string;source:Row;returns:Row[];latest_weights:{name:string;weight:number}[];rank_ic:Row[];factor_exposures:Row[];concentration:Row[];rolling:Row[];cost_sensitivity:Row[];robustness:Row[];methodologies:Row[];sector_exposure?:Row[];methodology_returns?:Row[];artifacts:string[]}
type Metric={key:string;label:string;unit:string;scale?:number}
const num=(v:unknown):number|null=>typeof v==='number'&&Number.isFinite(v)?v:null
const pretty=(v:unknown)=>typeof v==='number'?v.toLocaleString('en-IN',{maximumFractionDigits:6}):v==null?'—':String(v)
const human=(s:string)=>s.replaceAll('_',' ').replace(/^./,c=>c.toUpperCase())
const pct=(key:string,label:string):Metric=>({key,label,unit:'%',scale:100})
const scalar=(key:string,label:string,unit='Ratio'):Metric=>({key,label,unit})
const rollingMetrics=[pct('rolling_volatility','Annualized volatility'),pct('rolling_tracking_error','Annualized tracking error'),pct('rolling_active_return','Annualized arithmetic active return'),scalar('rolling_information_ratio','Information ratio'),scalar('cumulative_relative_wealth','Relative wealth','× benchmark wealth'),pct('drawdown','Drawdown')]
const concentrationMetrics=[pct('largest_weight','Largest weight'),pct('top_five_weight','Top-five weight'),scalar('hhi','Herfindahl index','HHI (0–1)'),scalar('effective_names','Effective holdings','Count'),scalar('nonzero_holdings','Actual holdings','Count')]
const performanceMetrics=[pct('strategy_cagr','Strategy CAGR'),pct('benchmark_cagr','Benchmark CAGR'),pct('volatility','Annualized volatility'),pct('strategy_volatility','Annualized strategy volatility'),pct('tracking_error','Annualized tracking error'),pct('max_drawdown','Maximum drawdown'),scalar('information_ratio','Information ratio'),pct('annualized_turnover','Annualized turnover'),pct('geometric_relative_cagr','Relative CAGR')]
const dateAxis={key:'date',label:'Saved observation date'}
const sourceNames:Record<AnalyticsRoute,string>={factors:'Factor diagnostics',construction:'Portfolio composition',risk:'Risk and concentration',rolling:'Rolling validation',robustness:'Parameter stability',comparisons:'Methodology comparison',visual:'Historical validation'}
function value(r:Row,m:Metric){const n=num(r[m.key]);return n===null?null:n*(m.scale??1)}
function metricOptions(rows:Row[],metrics:Metric[]){return metrics.filter(m=>rows.some(r=>num(r[m.key])!==null))}
function observedMetrics(rows:Row[],exclude:string[],unit:string,scale?:number):Metric[]{return [...new Set(rows.flatMap(Object.keys))].filter(k=>!exclude.includes(k)&&rows.some(r=>num(r[k])!==null)).map(key=>({key,label:human(key),unit,scale}))}
function download(name:string,data:unknown){const u=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000)}
function DataTable({rows,title,artifact,runId}:{rows:Row[];title:string;artifact?:string;runId:string}){
 const [page,setPage]=useState(0)
 const keys=[...new Set(rows.flatMap(Object.keys))]
 const safePage=Math.min(page,Math.max(0,Math.ceil(rows.length/25)-1))
 return <details className="sia-table"><summary>{title} · {rows.length.toLocaleString()} loaded rows</summary>
   {!rows.length?<p className="sia-note">No saved rows for this output.</p>:<><div className="sia-scroll"><table aria-label={title}><thead><tr>{keys.map(k=><th key={k}>{human(k)}</th>)}</tr></thead><tbody>{rows.slice(safePage*25,(safePage+1)*25).map((row,i)=><tr key={i}>{keys.map(k=><td key={k}>{pretty(row[k])}</td>)}</tr>)}</tbody></table></div>
   <div className="sia-actions"><button className="ws-button" disabled={!safePage} onClick={()=>setPage(safePage-1)}>Previous</button><span>Page {safePage+1} of {Math.ceil(rows.length/25)}</span><button className="ws-button" disabled={(safePage+1)*25>=rows.length} onClick={()=>setPage(safePage+1)}>Next</button><button className="ws-button" onClick={()=>download('quantlab-'+runId+'-loaded.json',rows)}>Export loaded rows</button>{artifact&&<a className="ws-button" href={'/api/runs/'+encodeURIComponent(runId)+'/files/'+encodeURIComponent(artifact)} download>Download original CSV</a>}</div></>}
 </details>
}
function MetricPanel({title,help,rows,metrics,axis=dateAxis,kind='line2d',runId,provenance,artifact}:{title:string;help:string;rows:Row[];metrics:Metric[];axis?:{key:string;label:string};kind?:string;runId:string;provenance:string;artifact?:string}){
 const options=metricOptions(rows,metrics)
 const [chosen,setChosen]=useState('')
 const metric=options.find(m=>m.key===chosen)||options[0]
 const validRows=rows.filter(r=>typeof r[axis.key]==='string'||num(r[axis.key])!==null)
 const plot:ResearchPlotData|null=metric&&validRows.length?{kind,title:title+' · '+metric.label,x_label:axis.label,y_label:metric.label+' ('+metric.unit+')',x:validRows.map(r=>typeof r[axis.key]==='number'?r[axis.key] as number:String(r[axis.key])),traces:[{name:metric.label,y:validRows.map(r=>value(r,metric))}]}:null
 return <article className="sia-panel"><header><div><h3>{title}</h3><p>{help}</p></div>{options.length>0&&<label>Metric<select aria-label={title+' metric'} value={metric?.key||''} onChange={e=>setChosen(e.target.value)}>{options.map(m=><option key={m.key} value={m.key}>{m.label}</option>)}</select></label>}</header>
 {plot?<ResearchPlot plot={plot} provenance={provenance} syncGroup={axis.key==='date'?'index-'+runId:undefined}/>:<p className="sia-empty">No finite saved values for this metric. Run an index experiment with the required inputs.</p>}
 <DataTable rows={rows} title={title+' evidence'} runId={runId} artifact={artifact}/></article>
}
function Stability({rows,runId,provenance,artifact}:{rows:Row[];runId:string;provenance:string;artifact?:string}){
 const options=metricOptions(rows,performanceMetrics)
 const [key,setKey]=useState('strategy_cagr')
 const lags=[...new Set(rows.map(r=>num(r.execution_lag_months)).filter((n):n is number=>n!==null))].sort((a,b)=>a-b)
 const [lag,setLag]=useState(0)
 const selectedLag=lags.includes(lag)?lag:lags[0]
 const metric=options.find(m=>m.key===key)||options[0]
 const slice=rows.filter(r=>r.execution_lag_months===selectedLag)
 const costs=[...new Set(slice.map(r=>num(r.transaction_cost_bps)).filter((n):n is number=>n!==null))].sort((a,b)=>a-b)
 const months=[...new Set(slice.map(r=>num(r.reconstitution_months)).filter((n):n is number=>n!==null))].sort((a,b)=>a-b)
 const matrix=months.map(m=>costs.map(c=>{const matches=slice.filter(r=>r.reconstitution_months===m&&r.transaction_cost_bps===c);return metric&&matches.length===1?value(matches[0],metric):null}))
 const has=matrix.some(r=>r.some(v=>v!==null))
 const complete=has&&matrix.every(r=>r.every(v=>v!==null))
 return <article className="sia-panel"><header><div><h3>Executed parameter grid</h3><p>Compare saved configurations at a fixed execution lag. Missing or duplicate cells are unavailable, not interpolated. Exploratory selection is not frozen holdout evidence.</p></div><div className="sia-actions"><label>Metric<select aria-label="Robustness metric" value={metric?.key||''} onChange={e=>setKey(e.target.value)}>{options.map(m=><option key={m.key} value={m.key}>{m.label}</option>)}</select></label><label>Execution lag (months)<select aria-label="Robustness execution lag" value={selectedLag??''} onChange={e=>setLag(Number(e.target.value))}>{lags.map(n=><option key={n}>{n}</option>)}</select></label></div></header>
 {metric&&has?<><ResearchPlot provenance={provenance} plot={{kind:'line2d',title:'Sensitivity by transaction cost · '+metric.label,x_label:'Cost (bps)',y_label:metric.label+' ('+metric.unit+')',x:costs,traces:months.map((m,i)=>({name:m+' month rebalance',y:matrix[i]}))}}/>
 {complete&&months.length>=2&&costs.length>=2?<ResearchPlot provenance={provenance} plot={{kind:'heatmap2d',title:'Executed parameter heatmap · '+metric.label+' ('+metric.unit+')',x_label:'Cost (bps)',y_label:'Reconstitution (months)',labels:costs.map(String),row_labels:months.map(String),values:matrix.map(r=>r.map(v=>v!)),scale:'sequential'}}/>:<p className="sia-note">A complete two-dimensional grid is needed for the heatmap; available points remain visible above.</p>}</>:<p className="sia-empty">No executed sensitivity grid has been saved.</p>}
 <DataTable rows={rows} title="Parameter grid evidence" runId={runId} artifact={artifact}/></article>
}
function rollingDerived(rows:Row[]):Row[]{
 return rows.map((r,i)=>{
  const out:Row={date:r.date,sharpe:null,beta:null}
  if(i<11)return out
  const window=rows.slice(i-11,i+1)
  const dates=window.map(v=>String(v.date??'').match(/^(\d{4})-(\d{2})/))
  if(dates.some(d=>!d))return out
  const months=dates.map(d=>Number(d![1])*12+Number(d![2]))
  if(months.some((m,j)=>j>0&&m!==months[j-1]+1))return out
  const a=window.map(v=>num(v.strategy_net)),b=window.map(v=>num(v.benchmark))
  if(a.some(v=>v===null||v<=-1)||b.some(v=>v===null||v<=-1))return out
  const s=a as number[],t=b as number[],mean=(x:number[])=>x.reduce((n,v)=>n+v,0)/x.length
  const ms=mean(s),mt=mean(t),ss=s.reduce((n,v)=>n+(v-ms)**2,0),tt=t.reduce((n,v)=>n+(v-mt)**2,0)
  if(ss>0)out.sharpe=ms/Math.sqrt(ss/11)*Math.sqrt(12)
  if(tt>0)out.beta=s.reduce((n,v,j)=>n+(v-ms)*(t[j]-mt),0)/tt
  return out
 })
}
export default function SavedIndexAnalytics({route,detail}:{route:AnalyticsRoute;detail:Detail}){
 const provenance=detail.source.dataset_kind==='synthetic'?'synthetic':'historical'
 const p={runId:detail.id,provenance}
 const artifact=(name:string)=>detail.artifacts.includes(name)?name:undefined
 const derived=useMemo(()=>rollingDerived(detail.returns),[detail.returns])
 const panel=(title:string,help:string,rows:Row[],metrics:Metric[],file?:string,axis?:{key:string;label:string},kind?:string)=><MetricPanel key={title} {...p} title={title} help={help} rows={rows} metrics={metrics} artifact={file?artifact(file):undefined} axis={axis} kind={kind}/>
 const rolling=()=>panel('Rolling relative metrics','Saved trailing 12-month metrics. Warm-up values are not zero-filled.',detail.rolling,rollingMetrics,'rolling_metrics.csv')
 const concentration=()=>panel('Portfolio concentration','Observed saved post-rebalance weights; HHI is dimensionless, effective holdings are counts.',detail.concentration,concentrationMetrics,'concentration.csv')
 const factors=()=>panel('Factor rank information coefficient','Rank correlation with forward returns; descriptive, not proof of predictive power.',detail.rank_ic,observedMetrics(detail.rank_ic,['date','index'],'Rank correlation'),'factor_rank_ic.csv')
 return <section className="sia-shell" aria-label={sourceNames[route]+' analytics'}><div className="sia-heading"><div><small>SAVED INDEX RESEARCH</small><h2>{sourceNames[route]}</h2><p>Run {detail.id} · {provenance==='synthetic'?'Synthetic demonstration, not observed markets':'User-source backtest, not independently audited'}. API views are bounded; original CSV downloads preserve the saved artifacts.</p></div></div>
 {(route==='factors'||route==='visual')&&factors()}
 {route==='factors'&&panel('Portfolio factor exposures','Weight-averaged source factor scores; not return or risk attribution.',detail.factor_exposures,observedMetrics(detail.factor_exposures,['date','index'],'Saved factor score'),'portfolio_factor_exposures.csv')}
 {route==='construction'&&<>{panel('Latest constituent allocation','Largest positive saved positions (API returns at most 40). Unshown weight is not cash.',detail.latest_weights,[pct('weight','Portfolio weight')],'post_rebalance_weights.csv',{key:'name',label:'Constituent'},'bar2d')}{concentration()}{panel('Sector allocation history','Only available when dated sector classifications were used.',detail.sector_exposure||[],observedMetrics(detail.sector_exposure||[],['date','index'],'%',100),'sector_exposure.csv')}{panel('Turnover and costs','Saved monthly traded weight and cost fraction.',detail.returns,[pct('turnover','Turnover'),pct('transaction_cost_fraction','Transaction cost')],'monthly_results.csv')}</>}
 {(route==='risk'||route==='rolling')&&<>{rolling()}{panel('Rolling Sharpe and beta','Derived from 12 consecutive saved monthly paired returns. Sharpe uses zero risk-free rate; beta uses the saved benchmark. Invalid or missing months are not filled.',derived,[scalar('sharpe','Sharpe (zero risk-free rate)'),scalar('beta','Benchmark beta')])}{route==='risk'&&<>{concentration()}<p className="sia-note">Security-level covariance risk contributions require aligned individual asset return and weight matrices; these are not supplied by this saved-run endpoint. Concentration is not covariance attribution.</p></>}</>}
 {route==='robustness'&&<><Stability {...p} rows={detail.robustness} artifact={artifact('robustness_grid.csv')}/>{panel('Cost sensitivity','Repricing the fixed trade path; not reoptimization.',detail.cost_sensitivity,[pct('annualized_return','Annualized return'),pct('total_turnover','Total turnover')],'cost_sensitivity.csv',{key:'cost_bps',label:'Transaction cost (bps)'})}</>}
 {route==='comparisons'&&<>{panel('Comparable methodology metrics','Same-date backtest methodology results. Compare one unit at a time.',detail.methodologies,performanceMetrics,'methodology_summary.csv',{key:'methodology',label:'Methodology'},'bar2d')}{panel('Methodology monthly return history','Saved net returns, not independently verified performance.',detail.methodology_returns||[],observedMetrics(detail.methodology_returns||[],['date','index'],'%',100),'methodology_returns.csv')}{panel('Cost sensitivity','Fixed-trade-path cost approximation.',detail.cost_sensitivity,[pct('annualized_return','Annualized return')],'cost_sensitivity.csv',{key:'cost_bps',label:'Transaction cost (bps)'})}</>}
 </section>
}
