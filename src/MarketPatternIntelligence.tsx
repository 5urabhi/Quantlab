import {useEffect,useState} from 'react'
import ResearchPlot from './ResearchPlots'
import ScalpingEconomics from './ScalpingEconomics'
import ScalpingValidation from './ScalpingValidation'
import YearScalpingResearch from './YearScalpingResearch'
import {marketApi,marketPost,readableError} from './tradingCockpitApi'
import './market-pattern-intelligence.css'

type Stats={n:number;mean:number|null;median:number|null;p10:number|null;p25:number|null;p75:number|null;p90:number|null;p95:number|null;max:number|null}
type Session={date:string;open:number|null;high:number;low:number;close:number;range:number;range_pct:number|null;up:number|null;down:number|null;net:number|null;bars:number}
type Regime={state:string;efficiency:number|null;low:number|null;high:number|null;range_pct:number|null;location_pct:number|null}
type RangeStudy={state:string;development_sessions:number;evaluation_sessions:number;evaluation_from?:string;rows:{cohort:string;hold_minutes:number;sessions:number;signals:number;mean_signals_per_session:number;positive_pct:number|null;mean_signed_points:number|null;median_mfe:number|null;median_mae:number|null}[]}
type Current=Session&{regime?:Regime;as_of_ist:string;age_seconds:number;state:string;missing_prefix_bars:number;historical_bars:number;live_observed_bars:number;gap:number|null;full_day_range_percentile:number|null;same_time_percentile:number|null;same_time_range:Stats;historical_remaining_excursion:Stats}
type Sync={enabled:boolean;state:string;last_attempt_utc:string|null;message:string}
type Conditional={state:string;development_sessions:number;evaluation_sessions:number;evaluation_from?:string;development_first_hour_p90_pct?:number;rows:{cohort:string;pattern:string;horizon:number;n:number;continuation_pct:number|null;reversal_pct:number|null;continuation_interval_pct:number[]|null;mean_signed_points:number|null;median_mfe:number|null;median_mae:number|null}[]}
type Report={identity:string;date_ist:string;requested_start:string;generated_utc:string;source:string;warning:string;current:Current|null;sync:Sync;coverage:{observed_prior_sessions:number;excluded_partial_sessions:number;verified_receipts:number;rejected_receipts:number;omitted_receipts:number;overlap_revisions:number;live_read_error:string|null};baseline:{sessions:number;first:string|null;last:string|null;daily:Session[];range:Stats;range_pct:Stats;up:Stats;down:Stats;abs_open_close:Stats;bullish_pct:number|null;bearish_pct:number|null;windows:{window:number;sessions:number;range:Stats;range_pct:Stats;abs_open_close:Stats}[];thresholds:{points:number;n:number;range_pct:number|null;either_pct:number|null;up_pct:number|null;down_pct:number|null;both_pct:number|null}[];percent_thresholds:{threshold_pct:number;n:number;range_pct:number|null;either_pct:number|null}[];gap_fill:{points:number;side:string;n:number;fill_pct:number|null}[];horizons:{minutes:number;n:number;absolute_move:Stats;up_pct:number|null;down_pct:number|null;move_50_pct:number|null;move_100_pct:number|null;move_200_pct:number|null}[];time_buckets:{time_ist:string;range:Stats}[];opening_patterns:{opening_minutes:number;hold_minutes:number;signals:number;n:number;positive_pct:number|null;signed_points:Stats}[];conditional?:Conditional;range_reversion?:RangeStudy}}
const fmt=(n:number|null|undefined,d=1)=>n==null?'—':n.toLocaleString('en-IN',{maximumFractionDigits:d})
const pct=(n:number|null|undefined)=>n==null?'—':fmt(n)+'%'
const ftime=(v:string)=>new Date(v).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',dateStyle:'short',timeStyle:'short'})
function Card({label,value,detail}:{label:string;value:string;detail?:string}){
  return <div className="mpi-card"><span>{label}</span><strong>{value}</strong>{detail&&<small>{detail}</small>}</div>
}
function Table({headers,rows}:{headers:string[];rows:(string|number)[][]}){
  return <div className="tc-table-scroll"><table><thead><tr>{headers.map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{rows.map((r,i)=><tr key={i}>{r.map((v,j)=><td key={j}>{v}</td>)}</tr>)}</tbody></table></div>
}
export default function MarketPatternIntelligence({identity='INDEX:BANKNIFTY',compact=false,coverageOnly=false}:{identity?:string;compact?:boolean;coverageOnly?:boolean}){
  const [data,setData]=useState<Report|null>(null)
  const [error,setError]=useState('')
  const [refresh,setRefresh]=useState(0)
  const [saving,setSaving]=useState(false)
  useEffect(()=>{
    let alive=true,loading=false
    setData(null);setError('')
    const poll=async()=>{if(loading)return;loading=true
      try{const r=await marketApi<Report>('/api/trading-cockpit/market-patterns?identity='+encodeURIComponent(identity));if(alive){setData(r);setError('')}}
      catch(e){if(alive)setError(readableError(e))}
      finally{loading=false}
    }
    void poll();const timer=window.setInterval(()=>void poll(),30000)
    return()=>{alive=false;window.clearInterval(timer)}
  },[identity,refresh])
  async function toggleSync(){
    if(!data)return
    setSaving(true)
    try{await marketPost<Sync>('/api/trading-cockpit/market-patterns/sync',{enabled:!data.sync.enabled});setRefresh(x=>x+1)}
    catch(e){setError(readableError(e))}
    finally{setSaving(false)}
  }
  const b=data?.baseline,c=data?.current
  if(coverageOnly)return <section className="mi-card" aria-label="Bank Nifty pattern history coverage">
    <div className="mi-heading"><div><span className="mi-kicker">SHARED MARKET LIBRARY</span><h3>Bank Nifty minute-history coverage</h3></div><a href="#/tradingpatterns">Open market intelligence →</a></div>
    {error&&<p role="alert" className="mi-muted">{error}</p>}
    {data&&!error&&b?<><div className="mpi-compact-grid">
      <Card label="Complete observed sessions" value={String(b.sessions)} detail={String(b.first||'—')+' to '+String(b.last||'—')}/>
      <Card label="Excluded partial sessions" value={String(data.coverage.excluded_partial_sessions)} detail={data.coverage.verified_receipts+' verified original receipts'}/>
      <Card label="Requested date window" value={data.requested_start} detail="Rolling 365 calendar days; not an exchange-calendar count"/>
      <Card label="Receipt integrity" value={data.coverage.rejected_receipts+' rejected'} detail={data.coverage.omitted_receipts+' omitted · '+data.coverage.overlap_revisions+' overlap revisions'}/>
    </div><p className="mi-muted">Automatic history sync: {data.sync.enabled?data.sync.state:'disabled'} · {data.sync.message}</p><button className="ws-button" type="button" disabled={saving} onClick={()=>void toggleSync()}>{data.sync.enabled?'Disable read-only sync':'Enable read-only history sync'}</button><p className="mi-muted">Checks missing requested date windows while the local server runs. A requested window does not establish complete minute or holiday coverage.</p></>:!error?<p className="mi-muted">Checking saved original receipts…</p>:null}
  </section>
  if(compact)return <section className="mi-card mpi-compact" aria-label="Current market movement context">
    <div className="mi-heading"><div><span className="mi-kicker">MOVEMENT CONTEXT</span><h3>Today's range</h3></div><a href="#/tradingpatterns">All statistics →</a></div>
    {error&&<p role="status" className="mi-muted">{error} · current context unavailable.</p>}
    {c&&!error?<><p className="mpi-source">{c.state==='recent_completed_bar'?'Recent completed bar':'Saved / stale'} · {ftime(c.as_of_ist)} IST · {c.missing_prefix_bars} missing prefix minutes</p>
      <div className="mpi-compact-grid">
        <Card label="30m market regime" value={c.state==='recent_completed_bar'?(c.regime?.state.replaceAll('_',' ')||'Unavailable'):'Saved / stale'} detail={'Close efficiency '+fmt(c.regime?.efficiency,2)+' · heuristic'}/>
        <Card label="Observed high–low" value={fmt(c.range)+' pts'} detail={pct(c.range_pct)+' of open'}/>
        <Card label="Same-clock percentile" value={pct(c.same_time_percentile)} detail={'Median by now '+fmt(c.same_time_range.median)+' pts'}/>
        <Card label="From session open" value={fmt(c.net)+' pts'} detail={'High '+fmt(c.high)+' · low '+fmt(c.low)}/>
        <Card label="Typical remaining excursion" value={fmt(c.historical_remaining_excursion.median)+' pts'} detail="Historical, not predicted"/>
      </div>
      {c.same_time_percentile!=null&&<p className="mpi-callout">{c.same_time_percentile>=90?'Unusually wide by this time.':c.same_time_percentile<=10?'Unusually narrow by this time.':'Compare with historical ranges, not direction.'}</p>}
    </>:<p className="mi-muted">No current original completed-minute context. Historical data may still be available.</p>}
    <p className="mi-muted">{b?b.sessions+' complete historical sessions · median full-day range '+fmt(b.range.median)+' points.':'Checking historical coverage…'} {data&&!data.sync.enabled?'History auto-sync is off.':''}</p>
  </section>
  return <section className="tc-panel mpi" aria-label="Market pattern intelligence">
    <div className="mpi-head"><div><span className="tc-page-kicker">MARKET INTELLIGENCE · ROLLING 365 DAYS</span><h3>{identity.replace('INDEX:','')} movement &amp; scalping context</h3><p>Observed index behaviour, not a CE/PE trade recommendation. Refreshes every 30 seconds from the shared library.</p></div><button type="button" onClick={()=>setRefresh(x=>x+1)}>Refresh</button></div>
    {error&&<p role="alert" className="tc-error">{error}{data?' · displayed report may be stale.':''}</p>}
    {!data&&!error&&<p role="status">Checking source-verified historical minutes and current observed session…</p>}
    {data&&b&&<>
      <div className="mpi-coverage">
        <strong>{b.sessions} complete sessions · {b.first||'No complete history'} {b.last?'to '+b.last:''}</strong>
        <span>Requested since {data.requested_start} · {data.coverage.verified_receipts} verified receipts · {data.coverage.excluded_partial_sessions} partial sessions excluded · {data.coverage.rejected_receipts} rejected · {data.coverage.omitted_receipts} omitted · {data.coverage.overlap_revisions} overlap revisions</span>
        <span>Calculated {ftime(data.generated_utc)} IST. Complete-session count is not a guarantee of exchange-calendar coverage.</span>
        {data.coverage.live_read_error&&<span role="status">Live minute read unavailable: {data.coverage.live_read_error}</span>}
        <div className="mpi-sync"><span>Bank Nifty daily original history sync: <b>{data.sync.enabled?data.sync.state:'Off'}</b> · {data.sync.message}</span><button type="button" disabled={saving} onClick={()=>void toggleSync()}>{data.sync.enabled?'Disable sync':'Enable read-only history sync'}</button></div>
        <small>One-time opt-in: fetch missing date windows using your existing Dhan token, then check closed sessions automatically while QuantLab is running. No new socket or trade access; BANKNIFTY only.</small>
      </div>
      <h4>Today · {data.date_ist} IST</h4>
      {c?<><p className="mpi-source">{c.state==='recent_completed_bar'?'Recent completed minute':'Saved / stale observations'} · through {ftime(c.as_of_ist)} IST · {c.bars} observed bars ({c.historical_bars} original, {c.live_observed_bars} tick-derived) · {c.missing_prefix_bars} missing minutes before last observation. Partial range is a lower bound.</p>
        <div className="mpi-grid">
          <Card label="Open / latest" value={fmt(c.open)+' / '+fmt(c.close)} detail={'Net from open: '+fmt(c.net)+' pts'}/>
          <Card label="Observed high / low" value={fmt(c.high)+' / '+fmt(c.low)}/>
          <Card label="Today's range" value={fmt(c.range)+' pts'} detail={pct(c.range_pct)+' of open'}/>
          <Card label="Up / down from open" value={fmt(c.up)+' / '+fmt(c.down)+' pts'}/>
          <Card label="Opening gap" value={fmt(c.gap)+' pts'} detail="Versus previous observed complete close"/>
          <Card label="Full-day range percentile" value={pct(c.full_day_range_percentile)} detail={'Compared with '+b.sessions+' completed sessions'}/>
          <Card label="Same-time range percentile" value={pct(c.same_time_percentile)} detail={'Typical by now: '+fmt(c.same_time_range.median)+' pts · '+c.same_time_range.n+' sessions'}/>
          <Card label="Typical remaining excursion" value={fmt(c.historical_remaining_excursion.median)+' pts'} detail={'Historical median max move from this clock time · '+c.historical_remaining_excursion.n+' sessions; not a forecast'}/>
        </div>
        {c.same_time_percentile!=null&&<p className="mpi-callout">Observed range has already equalled or exceeded {pct(c.same_time_percentile)} of historical sessions at the same clock time.{c.same_time_percentile>=90?' Unusually wide session so far.':c.same_time_percentile<=10?' Unusually narrow session so far.':''} This does not predict direction.</p>}
      </>:<p className="tc-warning">No original completed minute observed for today's regular session. Historical data remains separate; no live movement inferred.</p>}
      <h4>Sideways market research</h4>
      <div className="mpi-grid"><Card label="30m regime (observed)" value={c?.regime?.state.replaceAll('_',' ')||'Unavailable'} detail={c?.state==='recent_completed_bar'?'Recent completed minute':'Saved / stale or unavailable'}/><Card label="Close-range boundaries" value={fmt(c?.regime?.low)+' / '+fmt(c?.regime?.high)} detail="Prior 30 close changes; not guaranteed support/resistance"/><Card label="Directional efficiency" value={fmt(c?.regime?.efficiency,3)} detail="≤0.30 range-bound; ≥0.65 trend; heuristic"/><Card label="Close range width" value={pct(c?.regime?.range_pct)} detail="Below 0.10% classified as compressed"/></div>
      <ScalpingEconomics/>
      {identity==='INDEX:BANKNIFTY'&&<><YearScalpingResearch/><details className="mpi-detail"><summary>Original-depth matched replay (separate execution evidence)</summary><ScalpingValidation/></details></>}
      <details className="mpi-detail"><summary>Range-gated mean reversion · chronological research</summary>
        {b.range_reversion?.state==='descriptive'?<><p className="tc-muted">Development {b.range_reversion.development_sessions} sessions · evaluation {b.range_reversion.evaluation_sessions} from {b.range_reversion.evaluation_from}. Fixed prior range, 20% edge band, inward movement; next-minute open entry and nonoverlapping index proxy holds. No fees, premium or fill inference.</p><Table headers={['Sample','Hold min','Sessions','Triggers','Triggers/day','Positive index proxy','Mean signed pts','Median MFE','Median MAE']} rows={b.range_reversion.rows.map(r=>[r.cohort,r.hold_minutes,r.sessions,r.signals,fmt(r.mean_signals_per_session),pct(r.positive_pct),fmt(r.mean_signed_points),fmt(r.median_mfe),fmt(r.median_mae)])}/></>:<p className="tc-muted">Insufficient complete sessions for chronological evaluation.</p>}
        <p><a className="mi-link" href="#/tradingpaper">Test actual saved CE/PE depth using Range-gated reversal in Rule-Based Replay →</a></p>
      </details>
      <h4>Historical range and volatility</h4>
      {b.sessions===0?<p className="tc-warning">No complete regular-session original minute data in this window. Enable history sync or use the existing data centre. No statistics have been fabricated.</p>:<>
        <div className="mpi-grid">
          <Card label="Daily average / median range" value={fmt(b.range.mean)+' / '+fmt(b.range.median)+' pts'}/>
          <Card label="Daily range percentile bands" value={fmt(b.range.p25)+' / '+fmt(b.range.p75)+' pts'} detail={'90th: '+fmt(b.range.p90)+' · max: '+fmt(b.range.max)}/>
          <Card label="Mean up / down from open" value={fmt(b.up.mean)+' / '+fmt(b.down.mean)+' pts'}/>
          <Card label="Mean absolute open-close" value={fmt(b.abs_open_close.mean)+' pts'} detail={'Up sessions '+pct(b.bullish_pct)+' · down '+pct(b.bearish_pct)}/>
        </div>
        <Table headers={['Last sessions','Sample','Mean range (pts)','Median range (pts)','Mean range (%)','Mean |open-close|']} rows={b.windows.map(w=>[w.window,w.sessions,fmt(w.range.mean),fmt(w.range.median),pct(w.range_pct.mean),fmt(w.abs_open_close.mean)])}/>
        <ResearchPlot plot={{kind:'line2d',title:'Daily observed range vs rolling baseline',x:b.daily.map(x=>x.date),x_label:'NSE session',y_label:'Points',traces:[{name:'High-low range',y:b.daily.map(x=>x.range)}],reference_lines:b.range.median==null?[]:[{value:b.range.median,label:'Median'}]}} provenance="Verified original Dhan IDX_I minute receipts"/>
        <details className="mpi-detail" open><summary>Movement thresholds · full session</summary>
          <Table headers={['Points','Range ≥','Either from open','Up from open','Down from open','Both','Sessions']} rows={b.thresholds.map(t=>[t.points,pct(t.range_pct),pct(t.either_pct),pct(t.up_pct),pct(t.down_pct),pct(t.both_pct),t.n])}/>
          <Table headers={['Threshold (% of open)','Daily range frequency','Either-direction excursion','Sessions']} rows={b.percent_thresholds.map(t=>[pct(t.threshold_pct),pct(t.range_pct),pct(t.either_pct),t.n])}/>
        </details>
        <details className="mpi-detail" open><summary>Scalping horizons · observed close-to-close movement</summary>
          <Table headers={['Minutes','Windows','Median |move|','90th |move|','Up','Down','≥50 pts','≥100 pts','≥200 pts']} rows={b.horizons.map(h=>[h.minutes,h.n,fmt(h.absolute_move.median),fmt(h.absolute_move.p90),pct(h.up_pct),pct(h.down_pct),pct(h.move_50_pct),pct(h.move_100_pct),pct(h.move_200_pct)])}/>
          <p className="tc-muted">Overlapping within-session windows are descriptive; not independent wins or option P&amp;L.</p>
        </details>
        <details className="mpi-detail"><summary>Time of day · 15-minute movement profile</summary>
          <ResearchPlot plot={{kind:'bar2d',title:'Median 15-minute high-low range by clock time',x:b.time_buckets.map(t=>t.time_ist),x_label:'IST',y_label:'Points',traces:[{name:'Median range',y:b.time_buckets.map(t=>t.range.median)}]}} provenance="Verified complete regular sessions"/>
          <Table headers={['IST start','Sessions','Median range','90th percentile']} rows={b.time_buckets.map(t=>[t.time_ist,t.range.n,fmt(t.range.median),fmt(t.range.p90)])}/>
        </details>
        <details className="mpi-detail"><summary>Opening gaps · observed fill frequency</summary>
          <Table headers={['Gap ≥ points','Side','Sample','Fill rate']} rows={b.gap_fill.map(g=>[g.points,g.side,g.n,pct(g.fill_pct)])}/>
          <p className="tc-muted">Prior observed complete close; entire missing sessions are not inferred from a calendar.</p>
        </details>
        <details className="mpi-detail"><summary>Opening range breakout · next-open index proxy</summary>
          <Table headers={['Opening range (min)','Hold (min)','Signals','Scored','Positive proxy','Mean signed points']} rows={b.opening_patterns.map(p=>[p.opening_minutes,p.hold_minutes,p.signals,p.n,pct(p.positive_pct),fmt(p.signed_points.mean)])}/>
          <p className="tc-muted">First close beyond opening range; next observed minute open to horizon close. In-sample only, no fees, option spread, volatility, or fill assumption. Not a strategy ranking.</p>
        </details>
        <details className="mpi-detail"><summary>Conditional continuation / reversal and favorable / adverse excursion</summary>
          {b.conditional?.state==='descriptive'?<><p className="tc-muted">Fixed rules · {b.conditional.development_sessions} development sessions, {b.conditional.evaluation_sessions} chronological evaluation sessions from {b.conditional.evaluation_from}. First qualifying event per session; enter at next observed open. Index proxy only, not option P&amp;L. Wilson intervals are descriptive and do not account for serial dependence or multiple comparisons.</p><Table headers={['Pattern','Sample','Hold min','Events','Continuation','Reversal','Wilson 95% range','Mean signed pts','Median MFE','Median MAE']} rows={b.conditional.rows.map(r=>[r.pattern.replaceAll('_',' '),r.cohort,r.horizon,r.n,pct(r.continuation_pct),pct(r.reversal_pct),r.continuation_interval_pct?r.continuation_interval_pct.map(x=>pct(x)).join(' – '):'—',fmt(r.mean_signed_points),fmt(r.median_mfe),fmt(r.median_mae)])}/></>:<p className="tc-muted">At least 20 development and 5 evaluation sessions required; no pattern probabilities inferred yet.</p>}
        </details>
        <details className="mpi-detail"><summary>Historical sessions · exact observed OHLC</summary><Table headers={['Session','Open','High','Low','Close','Range','Up','Down','Net']} rows={[...b.daily].reverse().map(s=>[s.date,fmt(s.open),fmt(s.high),fmt(s.low),fmt(s.close),fmt(s.range),fmt(s.up),fmt(s.down),fmt(s.net)])}/></details>
      </>}
      <p className="tc-muted">{data.warning}</p>
    </>}
  </section>
}
