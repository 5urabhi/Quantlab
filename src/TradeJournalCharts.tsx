import ResearchPlot from './ResearchPlots'

type TradeDay={exit_session_ist:string;closed:number;net_pnl_inr:number;over_6_min:number}
type PredictionDay={session_ist:string;total:number;scored:number;correct:number;incorrect:number;pending:number;no_trade:number;flat:number;unverifiable:number;directional_accuracy:number|null}
const fmt=(n:number)=>n.toLocaleString('en-IN',{maximumFractionDigits:2})

export function ManualTradeCharts({days,limited}:{days:TradeDay[];limited:boolean}){
 const ordered=[...days].sort((a,b)=>a.exit_session_ist.localeCompare(b.exit_session_ist))
 let cumulative=0
 const net=ordered.map(d=>d.net_pnl_inr)
 const x=ordered.map(d=>d.exit_session_ist)
 if(!ordered.length)return <p className="tc-muted">Daily P&L charts appear after you close a manually recorded trade.</p>
 return <section className="ql-journal-charts" aria-label="Manual trade performance charts">
  <h3>Recorded trade performance</h3>
  <p className="tc-muted">Based on user-entered fills and charges for the returned journal entries, grouped by exit date in IST. Not a verified brokerage statement.{limited?' Recent-entry limit applies; this is not lifetime P&L.':''}</p>
  <div className="tc-ledger-summary"><span>Profitable exit dates <strong>{net.filter(v=>v>0).length}</strong></span><span>Loss-making exit dates <strong>{net.filter(v=>v<0).length}</strong></span><span>Best date net P&L <strong>₹{fmt(Math.max(...net))}</strong></span><span>Worst date net P&L <strong>₹{fmt(Math.min(...net))}</strong></span></div>
  <ResearchPlot provenance="User-entered manual fills" plot={{kind:'bar2d',title:'Net recorded P&L by exit date',x_label:'Exit calendar date (IST)',y_label:'Net P&L (INR)',x,traces:[{name:'Net recorded P&L',y:net}],reference_lines:[{label:'Break-even',value:0}]}}/>
  <ResearchPlot provenance="User-entered manual fills" plot={{kind:'line2d',title:'Cumulative net recorded P&L · returned entries',x_label:'Exit calendar date (IST)',y_label:'Cumulative net P&L (INR)',x,traces:[{name:'Net recorded P&L',y:net.map(v=>{cumulative+=v;return cumulative})}],reference_lines:[{label:'Zero',value:0}]}}/>
  <ResearchPlot provenance="User-entered manual fills" plot={{kind:'bar2d',title:'Closed recorded trades by exit date',x_label:'Exit calendar date (IST)',y_label:'Trades',x,traces:[{name:'Closed trades',y:ordered.map(d=>d.closed)}]}}/>
 </section>
}
export function PredictionCharts({days,truncated}:{days:PredictionDay[];truncated:boolean}){
 const ordered=[...days].sort((a,b)=>a.session_ist.localeCompare(b.session_ist))
 const x=ordered.map(d=>d.session_ist)
 if(!ordered.length)return <p className="tc-muted">No evaluated prospective prediction dates are available to chart.</p>
 return <section className="ql-journal-charts" aria-label="Prospective prediction performance charts">
  <h3>Prospective prediction performance</h3><p className="tc-muted">Scored predictions exclude pending, flat, no-trade and unverifiable outcomes. This is directional accuracy, not trading P&L.{truncated?' Report is truncated; do not interpret as lifetime accuracy.':''}</p>
  <ResearchPlot provenance="Saved prospective prediction ledger" plot={{kind:'line2d',title:'Observed directional accuracy by session',x_label:'Session date (IST)',y_label:'Scored directional accuracy (%)',x,traces:[{name:'Accuracy',y:ordered.map(d=>d.directional_accuracy===null?null:d.directional_accuracy*100)}]}}/>
  <ResearchPlot provenance="Saved prospective prediction ledger" plot={{kind:'bar2d',title:'Scored prediction outcomes',x_label:'Session date (IST)',y_label:'Predictions',x,traces:[{name:'Correct',color:'#70e1ad',y:ordered.map(d=>d.correct)},{name:'Incorrect',color:'#ff8192',y:ordered.map(d=>d.incorrect)}]}}/>
  <ResearchPlot provenance="Saved prospective prediction ledger" plot={{kind:'bar2d',title:'Unscored decision outcomes',x_label:'Session date (IST)',y_label:'Predictions',x,traces:[{name:'Pending',y:ordered.map(d=>d.pending)},{name:'Unverifiable',y:ordered.map(d=>d.unverifiable)},{name:'No trade',y:ordered.map(d=>d.no_trade)},{name:'Flat',y:ordered.map(d=>d.flat)}]}}/>
 </section>
}
