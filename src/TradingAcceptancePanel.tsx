import {useState} from 'react'
import {AlertTriangle,ArrowRight,CheckCircle2,ClipboardCheck,Database,Download,RefreshCw,ShieldCheck} from 'lucide-react'
import {marketApi} from './tradingCockpitApi'
import './trading-acceptance.css'

type CheckState='pass'|'action_needed'|'not_verified'|'waiting'|'partial'|'not_recorded'|
  'requires_backtest'|'research_pending'
type Check={
  code:string;title:string;status:CheckState
  detail:string;next_action:string;screen:'connections'|'backtest'|'live'|'replay'
}
type DepthProof={
  status:string;total_automatic_books:number;latest_book_utc:string|null
  sample_checked:number;valid_sample_books:number;invalid_sample_books:number
  valid_ce_books:number;valid_pe_books:number
  observed_trading_dates_in_sample:number;note:string
}
type Report={
  checked_utc:string;version:string;safe_to_share:boolean;read_only:boolean
  external_api_requests:number;orders_placed:number
  market_regular_hours_ist:boolean;recorder_armed:boolean
  recorder_state:string;saved_books:DepthProof;checks:Check[]
}
type DhanCheck={
  ok:boolean;token_valid:boolean|null;data_plan_active:boolean|null
  client_id_configured?:boolean;client_id_auto_available?:boolean
}
type Props={
  onOpenLive:()=>void;onOpenBacktest:()=>void;onOpenReplay:()=>void
}
const DAY=(iso:string|null|undefined)=>iso
  ?new Date(iso).toLocaleString('en-IN',{timeZone:'Asia/Kolkata',
    day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}):'Not recorded'
const STATE_NAMES:Record<CheckState,string>={
  pass:'Verified',action_needed:'Action needed',not_verified:'Not verified',
  waiting:'Awaiting live data',partial:'Partial source',
  not_recorded:'No recorded depth yet',requires_backtest:'Run backtest',
  research_pending:'Research not trained',
}
const toJSON=(input:Report,credentials:DhanCheck|null)=>({
  report_version:input.version,checked_utc:input.checked_utc,
  source:'local_QuantLab_original_evidence',
  read_only:true,orders_placed:0,credential_secrets_included:false,
  dhan_profile:{
    verified:credentials?.ok===true&&credentials.token_valid===true,
    historical_data_plan:credentials?.data_plan_active===true,
    client_id_configured:credentials?.client_id_configured===true,
    client_id_auto_available:credentials?.client_id_auto_available===true,
    // This does NOT establish Dhan's separate 20-level entitlement.
    twenty_level_entitlement:'not_verifiable_from_profile_response',
  },
  market_regular_hours_ist:input.market_regular_hours_ist,
  recorder_armed:input.recorder_armed,
  recorder_state:input.recorder_state,
  saved_books:input.saved_books,
  checks:input.checks,
  backtest_result:'Run Options Backtest separately; download its diagnostic report',
})
export default function TradingAcceptancePanel({onOpenLive,onOpenBacktest,onOpenReplay}:Props){
  const [report,setReport]=useState<Report|null>(null)
  const [credentials,setCredentials]=useState<DhanCheck|null>(null)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [credentialNote,setCredentialNote]=useState('')
  const run=async()=>{
    if(busy)return
    setBusy(true);setError('');setCredentialNote('')
    try{
      const [local,profile]=await Promise.allSettled([
        marketApi<Report>('/api/trading-cockpit/acceptance'),
        marketApi<DhanCheck>('/api/dhan/credentials/check'),
      ])
      if(local.status==='fulfilled')setReport(local.value)
      else {
        setReport(null)
        setError('The local acceptance endpoint could not complete. Make sure the updated QuantLab backend is running and use Data Manager > Activity & recovery.')
      }
      if(profile.status==='fulfilled')setCredentials(profile.value)
      else {
        setCredentials(null)
        setCredentialNote('Dhan profile could not be verified. Open the connection form below to check or renew your local token.')
      }
    }finally{setBusy(false)}
  }
  const download=()=>{
    if(!report)return
    const output=toJSON(report,credentials)
    const blob=new Blob([JSON.stringify(output,null,2)+'\n'],
      {type:'application/json'})
    const url=URL.createObjectURL(blob)
    const link=document.createElement('a')
    link.href=url;link.download='quantlab-trading-acceptance-safe.json'
    document.body.appendChild(link);link.click();link.remove()
    window.setTimeout(()=>URL.revokeObjectURL(url),1000)
  }
  const go=(screen:Check['screen'])=>{
    if(screen==='live')onOpenLive()
    else if(screen==='replay')onOpenReplay()
    else if(screen==='backtest')onOpenBacktest()
    else document.getElementById('tc-connection-check')?.scrollIntoView({behavior:'smooth'})
  }
  const verified=report?.checks.filter(x=>x.status==='pass').length??0
  return <section className="tac-root" aria-label="Trading system local acceptance checklist">
    <header className="tac-header">
      <div><span className="tc-page-kicker">LOCAL ACCEPTANCE · NO TRADING ORDERS</span>
        <h3><ClipboardCheck size={19}/> Check my trading system</h3>
        <p>One click checks genuine locally saved BANKNIFTY history,
          verified option contract IDs, the 20-level recorder, and original
          stored depth. It also checks your Dhan profile separately. No
          backtest or model is rerun and no historical prices are fabricated.</p>
      </div>
      <div className="tac-buttons">
        <button type="button" onClick={()=>void run()} disabled={busy}
          className="tac-check">{busy?<RefreshCw size={15}/>:<ShieldCheck size={15}/>}
          {busy?'Checking local sources…':'Run local checks'}</button>
        {report&&<button type="button" onClick={download}>
          <Download size={15}/> Download safe report</button>}
      </div>
    </header>
    {error&&<p className="tac-error" role="alert"><AlertTriangle size={16}/>{error}</p>}
    {credentialNote&&<p className="tac-note" role="status">{credentialNote}</p>}
    {report&&<div className="tac-results">
      <div className="tac-summary" role="status">
        <strong>{verified} / {report.checks.length} source/research checks verified</strong>
        <span>Checked {DAY(report.checked_utc)} IST · read-only · no orders</span>
        <span>20-level data entitlement is proven only by actual received packets, not by the historical Data API plan.</span>
      </div>
      <article className="tac-card tac-dhan">
        <div><strong>Dhan account &amp; historical Data API</strong>
          <span className={'tac-pill '+(credentials?.ok&&credentials.token_valid?'pass':'action_needed')}>
            {credentials?.ok&&credentials.token_valid?'Profile verified':'Profile not verified'}</span></div>
        <p>Token: {credentials?.token_valid===true?'valid':credentials?.token_valid===false?'not valid':'not verified'}
          {' '}· Data API: {credentials?.data_plan_active===true?'active':'not confirmed'}
          {' '}· WebSocket client ID: {credentials?.client_id_configured?'saved':credentials?.client_id_auto_available?'auto-detected from profile':'not yet verified'}</p>
        <small>The 20-level entitlement requires an actual successful Dhan packet reception.</small>
      </article>
      <div className="tac-grid">
        {report.checks.map(check=><article className="tac-card" key={check.code}>
          <div className="tac-card-head">
            <strong>{check.title}</strong>
            <span className={'tac-pill '+check.status}>{check.status==='pass'
              ?<CheckCircle2 size={13}/>:<AlertTriangle size={13}/>}
              {STATE_NAMES[check.status]}</span>
          </div>
          <p>{check.detail}</p>
          <small>{check.next_action}</small>
          <button type="button" onClick={()=>go(check.screen)}>
            {check.screen==='live'?'Open Live Trading':
              check.screen==='backtest'?'Open Options Backtest':
                check.screen==='replay'?'Review saved depth':
                  'Open connection settings'}
            <ArrowRight size={13}/>
          </button>
        </article>)}
      </div>
      <div className="tac-evidence" role="status">
        <Database size={17}/>
        <div><strong>Original automatic depth evidence</strong>
          <p>{report.saved_books.total_automatic_books.toLocaleString('en-IN')}
            {' '}saved books · {report.saved_books.valid_sample_books} verified in the latest
            {' '}{report.saved_books.sample_checked} inspected receipts ·
            {' '}{report.saved_books.valid_ce_books} CE / {report.saved_books.valid_pe_books} PE
            {' '}in the inspected sample · latest {DAY(report.saved_books.latest_book_utc)} IST.</p>
          <small>{report.saved_books.note}</small>
        </div>
      </div>
    </div>}
    <div className="tac-how" aria-label="How to verify my BANKNIFTY data">
      <strong>Next tests on your Ubuntu workstation</strong>
      <ol>
        <li>Run <b>Run local checks</b> above. Verify your Dhan token, master,
          and original BANKNIFTY minute history.</li>
        <li>Open <b>Live Trading</b>, authorize <b>Arm automatic 20-level recording</b>
          and keep the local server open during regular NSE hours. Inspect
          fresh original <b>20 bid + 20 ask</b> packets for a CE and PE.</li>
        <li>Open <b>Recorded 20-level books</b>. Return here and rerun the
          check to verify nonzero stored books and source SHA receipts.</li>
        <li>Open <b>Options Backtest</b> and run the historical window.
          Inspect <b>opposite exits / re-entry attempts / completed flips</b>
          and download its diagnostic summary.</li>
        <li>Download this safe report and the backtest summary and share
          them here. They contain counts and policy outcomes, not Dhan tokens,
          client IDs or raw market books.</li>
      </ol>
    </div>
    <div className="tac-shortcuts">
      <button type="button" onClick={onOpenLive}>Arm / inspect live depth <ArrowRight size={13}/></button>
      <button type="button" onClick={onOpenReplay}>Replay recorded books <ArrowRight size={13}/></button>
      <button type="button" onClick={onOpenBacktest}>Run options backtest <ArrowRight size={13}/></button>
    </div>
  </section>
}
