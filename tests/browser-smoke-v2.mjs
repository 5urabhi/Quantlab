/**
 * QuantLab V2 browser acceptance. Existing Classic feature suite still runs
 * unchanged with ?ui=classic; this tests the ACTUAL new default navigation,
 * connected feature components, browser deep-links and mobile support.
 *
 * CI source records are synthetic fixtures — never broker-feed certification.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import {chromium} from 'playwright'

const base=process.env.QUANTLAB_SMOKE_URL||'http://127.0.0.1:5173'
const dir=path.resolve(process.env.QUANTLAB_SMOKE_ARTIFACT_DIR||'artifacts/browser-smoke')
await fs.mkdir(dir,{recursive:true})
const errors=[],badApi=[],results=[]
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--disable-dev-shm-usage']})
const context=await browser.newContext({viewport:{width:1440,height:900},
  deviceScaleFactor:1,acceptDownloads:true,colorScheme:'dark'})
const page=await context.newPage()
page.setDefaultTimeout(20000)
page.on('pageerror',error=>errors.push(String(error)))
page.on('response',response=>{
  try{if(new URL(response.url()).pathname.startsWith('/api/')&&response.status()>=500)
    badApi.push(response.status()+' '+new URL(response.url()).pathname)}
  catch{}
})
async function step(name,action){
  try{
    await action()
    results.push({name,status:'PASS'})
    console.log('[V2] PASS '+name)
  }catch(error){
    results.push({name,status:'FAIL',reason:String(error)})
    console.error('[V2] FAIL '+name+': '+String(error))
    try{await page.screenshot({path:path.join(dir,'v2-failed-'+
      name.toLowerCase().replace(/[^a-z0-9]+/g,'-').slice(0,55)+'.png'),
      fullPage:true})}catch{}
    throw error
  }
}
async function top(name){
  const button=page.locator('.ws-sidebar nav').getByRole('button',{name,exact:true})
  await button.click()
  await page.locator('.ws-titlebar h1').waitFor()
}
async function sub(name){
  await page.getByRole('navigation',{name:'Modules within selected research destination'})
    .getByRole('button',{name,exact:true}).click()
  await page.locator('.ws-titlebar h1',{hasText:name}).waitFor()
}
async function shot(name){
  await page.screenshot({path:path.join(dir,'v2-'+name+'.png'),fullPage:true})
}
try{
 await step('eight-page V2 default and usable global header',async()=>{
   await page.goto(base,{waitUntil:'domcontentloaded'})
   await page.locator('.ws-v2 .ws-nav-item').first().waitFor({timeout:35000})
   assert.equal(await page.locator('.ws-sidebar .ws-nav-item').count(),8)
   assert.deepEqual(await page.locator('.ws-sidebar .ws-nav-item').allTextContents(),
     ['Home','Trading','Strategies','Models','Data Center',
      'Results & Charts','Projects','Settings'])
   await page.getByRole('button',{name:/Recorder status/}).waitFor()
   await page.getByRole('button',{name:'Open Jobs and downloads'}).waitFor()
   await page.getByRole('button',{name:'New Study'}).waitFor()
   await page.getByRole('heading',{name:'Home',exact:true}).waitFor()
   await page.getByRole('button',{name:/Test BANKNIFTY signals/}).waitFor()
   await shot('01-home')
 })
 await step('V3 compact navigation and durable reusable Python scripts',async()=>{
   await page.getByRole('button',{name:'Collapse sidebar'}).click()
   assert.ok(await page.locator('.ws-shell').evaluate(el=>el.classList.contains('ql-nav-compact')))
   await page.getByRole('button',{name:'Expand sidebar'}).click()
   await page.getByRole('button',{name:'Python',exact:true}).click()
   const python=page.getByRole('region',{name:'Python research workspace'})
   await python.waitFor()
   await python.getByRole('textbox',{name:'Reusable Python code'}).fill('def analyze(data):\n    return {"title":"Example", "x_label":"Time", "y_label":"Value", "traces":[{"name":"Value", "y":[1]}]}')
   await python.getByRole('textbox',{name:'Name',exact:true}).fill('V3 CI script '+Date.now())
   await python.getByRole('button',{name:'Save as new',exact:true}).click()
   await python.getByText('Saved to local backend · revision 1',{exact:true}).waitFor()
   await python.getByRole('button',{name:'Minimize'}).click()
   await page.getByRole('button',{name:'Python',exact:true}).click()
   await python.getByRole('textbox',{name:'Reusable Python code'}).waitFor()
   assert.match(await python.getByRole('textbox',{name:'Reusable Python code'}).inputValue(),/def analyze/)
   await python.getByRole('button',{name:'Minimize'}).click()
 })
 await step('global Jobs drawer stays independent of recorder',async()=>{
   await page.getByRole('button',{name:'Open Jobs and downloads'}).click()
   await page.getByRole('dialog',{name:'QuantLab research jobs'}).waitFor()
   await page.getByRole('button',{name:'Close jobs'}).click()
   assert.equal(await page.getByRole('dialog',{name:'QuantLab research jobs'}).count(),0)
 })
 await step('Trading live chart, chain, depth, replay and journal navigation',async()=>{
   await top('Trading')
   await page.getByRole('heading',{name:'Live Market',exact:true}).waitFor()
   await page.getByRole('region',{name:'Live BANKNIFTY and 20-level market feed'}).waitFor()
   await page.getByRole('region',{name:'Original observed BANKNIFTY close chart'}).waitFor()
   await shot('02-trading-live')
   await sub('Option Chain')
   await page.getByRole('region',{name:'BANKNIFTY option chain and lot calculator'}).waitFor()
   await shot('02-trading-option-chain')
   // Original-shape *synthetic* fixtures for the new advanced workspace.
   const fixtureExpiry='2026-12-29'
   const optionIdentity='NSE_FNO:62539'
   const modelGreeks={price:179.5,delta:.48,gamma:.0008,theta_day:-12,
     vega_iv_point:5.6,rho_rate_point:1.1}
   const optionFixture={identity:optionIdentity,symbol:'FIXTURE BANKNIFTY CE',
     strike:63000,expiry:fixtureExpiry,option_type:'CE',lot_size:30,
     contract_master_verified:true,bid:179,ask:180,ltp:179.5,
     top_bid_quantity:300,top_ask_quantity:300,oi:3000,volume:6000,iv:18,
     delta:.48,theta:-12,gamma:.0008,vega:5.6,quote_valid:true,
     one_lot_ask_inr:5400,one_lot_bid_inr:5370,spread_inr_per_lot:30}
   const advancedChain=()=>({underlying:'BANKNIFTY',underlying_spot:63000,
     expiry:fixtureExpiry,received_utc:new Date().toISOString(),
     source:'synthetic_browser_fixture',source_clock:'local_received_utc_not_exchange_quote_time',
     not_live_stream:true,market_master_fresh:true,master_message:'',
     master_age_hours:1,contracts:[optionFixture],quote_count:1,read_only:true,
     warning:'Synthetic fixture',cache_hit:false})
   await page.route('**/api/trading-cockpit/options/expiries',route=>route.fulfill({
     json:{underlying:'BANKNIFTY',expiries:[fixtureExpiry],nearest_expiry:fixtureExpiry,
       received_utc:new Date().toISOString(),source:'synthetic_browser_fixture'}
   }))
   await page.route('**/api/trading-cockpit/options/chain?*',route=>route.fulfill({json:advancedChain()}))
   await page.route('**/api/trading-cockpit/options/analytics?*',route=>{
     const q=new URL(route.request().url()).searchParams
     const assumptions=Object.fromEntries([...q.entries()].filter(([k])=>!['expiry','selected'].includes(k))
       .map(([k,v])=>[k,['direction','broker_profile'].includes(k)?v:Number(v)]))
     const chain=advancedChain()
     const scenarios=Object.fromEntries([
       ['favorable',100,225,3800],['flat',0,178,-220],['adverse',-100,136,-4100],
       ['iv_crush',100,210,2500],['iv_expansion',100,240,5100],
       ['double_favorable',200,280,8800],['double_adverse',-200,101,-7300]
     ].map(([k,move,premium,pnl])=>[k,{move_points:move,iv_change_points:0,minutes:5,
       model_mid:premium+.5,assumed_exit_bid:premium,charges_inr:65,net_pnl_inr:pnl}]))
     const row={...optionFixture,mid:179.5,intrinsic:0,extrinsic:179.5,moneyness:'ATM vicinity',
       spread_bps:55.7,iv_mid_pct:18,iv_bid_pct:17.9,iv_ask_pct:18.1,model_greeks:modelGreeks,
       iv_change_pct_points:null,oi_change:null,volume_change:null,trade_activity:null,
       trade_activity_state:'missing_trade_evidence',top_level_lots:10,affordable_lots:3,
       scenario_lots:3,units:90,entry_debit_inr:16230,max_premium_loss_inr:16230,
       break_even_exit_premium:180.8,roundtrip_fees:{total_estimated:65,
         buy_leg:{cash_debit:16230,fees_total:30},sell_leg:{fees_total:35},
         brokerage:40,stt_sell:10,gst:8,exchange_indicative:5,stamp_buy:1,sebi:1},
       same_quote_roundtrip_net_inr:-155,scenarios,score:71,rank:1,
       rank_quality:'indicative_snapshot_only',reasons:[],depth:null,depth_state:'no_recent_original_book',
       unsigned_gamma_oi_proxy:10000}
     return route.fulfill({json:{chain,rows:[row],ranked_count:1,confirmed_depth_count:0,
       recent_trade_count:0,as_of_utc:chain.received_utc,generated_utc:chain.received_utc,
       snapshot_age_seconds:0,recent_receipt:true,assumed_expiry_utc:fixtureExpiry+'T10:00:00Z',
       years_to_expiry:.1,assumptions,
       volatility:{atm_provider_iv_pct:18,realized_intraday_pct:null,realized_returns:0,
         realized_last_utc:null,expected_move_points_model:100,iv_rank:null,iv_percentile:null,
         iv_prior_sessions:0,iv_min_prior_sessions:20,iv_history:[],term_structure:[],india_vix:null},
       oi:{call_oi:3000,put_oi:null,known_counts:{CE:1,PE:0},contract_counts:{CE:1,PE:0},
         complete:false,pcr:null,max_pain_strike:null,previous_snapshot_utc:null,dealer_gamma_exposure:null},
       selected_history_identity:q.get('selected')||null,selected_history:[],historical_error:null,
       warnings:['Synthetic browser fixture, no trades or profits.'],orders_enabled:false}})
   })
   const chainRegion=page.getByRole('region',{name:'BANKNIFTY option chain and lot calculator'})
   await chainRegion.getByRole('button',{name:'Refresh expiry list',exact:true}).click()
   await chainRegion.getByLabel('Dhan BANKNIFTY expiry').locator('option',{hasText:fixtureExpiry}).waitFor({state:'attached'})
   const paired=chainRegion.getByRole('table',{name:'Calls and puts by strike'})
   await paired.getByRole('button',{name:'Select 63000 CE',exact:true}).click()
   const drawer=chainRegion.getByRole('complementary',{name:'Selected option contract details'})
   await drawer.waitFor()
   await drawer.getByRole('button',{name:'Fit lots to premium budget'}).click()
   assert(Number(await drawer.getByLabel('BANKNIFTY option lots').inputValue())>=1)
   await drawer.getByRole('button',{name:'Close contract details'}).click()
   await drawer.waitFor({state:'hidden'})
   await chainRegion.getByLabel('Option chain layout').selectOption('list')
   await chainRegion.getByLabel('Option chain layout').selectOption('paired')
   await chainRegion.getByRole('button',{name:'Advanced Analytics',exact:true}).click()
   const advanced=page.getByRole('region',{name:'Advanced Options Analytics'})
   await advanced.getByRole('heading',{name:'Best fit for the selected scenario'}).waitFor()
   await advanced.locator('.ao-pick').first().waitFor()
   await advanced.getByText('Indicative · activity unverified',{exact:false}).first().waitFor()
   await advanced.getByRole('tab',{name:'Greeks',exact:true}).click()
   await advanced.getByRole('heading',{name:'Independent model sensitivities'}).waitFor()
   await advanced.getByText('Gamma across strikes',{exact:true}).waitFor()
   await advanced.getByRole('tab',{name:'Volatility',exact:true}).click()
   await advanced.getByText('Same-expiry IV percentile',{exact:true}).waitFor()
   await advanced.getByRole('tab',{name:'OI & Volume',exact:true}).click()
   await advanced.getByText('Put / call OI ratio',{exact:true}).waitFor()
   await advanced.getByRole('tab',{name:'Liquidity',exact:true}).click()
   await advanced.getByRole('heading',{name:'Quote and original-depth evidence'}).waitFor()
   await advanced.getByRole('button',{name:'Trade calculator',exact:true}).click()
   await advanced.getByRole('heading',{name:/Net P&L scenarios/}).waitFor()
   await advanced.getByText('Adverse move',{exact:true}).waitFor()
   await advanced.getByRole('button',{name:'Watch',exact:true}).click()
   await advanced.getByRole('tab',{name:/Watchlist \(1\)/}).click()
   await advanced.getByText('1 of 1 returned contracts',{exact:true}).waitFor()
   await shot('02-trading-advanced-options')
   // Synthetic UI verification of the persistent manual-trading workflow.
   // Real backend tests separately verify causal storage and no actual orders.
   let tracking=false
   let alertEnabled=false
   let alertConditions={}
   const workflowUrl='**/api/trading-cockpit/options/workflow'
   await page.route(workflowUrl,route=>route.fulfill({json:{
      tracking_enabled:tracking,rules:alertEnabled?[{id:'alert_fixture',identity:optionIdentity,
        expiry:fixtureExpiry,strike:63000,side:'CE',conditions:alertConditions,enabled:true,
        state:'waiting_for_receipt',last_receipt_utc:null}]:[],events:[],samples:[],
      sample_counts:{},observed_count:0,positive_count:0,negative_count:0,
      mean_markout_inr:null,sum_markout_inr:null,paired_count:0,paired_mean_return_difference_pp:null,
      control_observed_count:0,worker:{alive:true,state:'running',last_cycle_utc:new Date().toISOString(),last_error:null},
      warning:'Synthetic workflow fixture, no trade evidence'
   }}))
   await page.route('**/api/trading-cockpit/options/workflow/tracking',route=>{
      tracking=route.request().postDataJSON().enabled
      return route.fulfill({json:{tracking_enabled:tracking}})
   })
   await page.route('**/api/trading-cockpit/options/workflow/alerts',route=>{
      alertEnabled=true;alertConditions=route.request().postDataJSON().conditions
      return route.fulfill({json:{id:'alert_fixture',enabled:true}})
   })
   await page.route('**/api/trading-cockpit/options/compare',route=>{
      const now=new Date().toISOString()
      return route.fulfill({json:{rows:[],ranked_count:0,coverage:[
        {expiry:fixtureExpiry,state:'recent',age_seconds:0,received_utc:now,ranked_count:0},
        {expiry:'2027-01-25',state:'delayed_or_closed',age_seconds:80,ranked_count:0}],
        settings:route.request().postDataJSON(),generated_utc:now,truncated:false,
        warning:'Saved snapshots only',orders_enabled:false}})
   })
   await page.route('**/api/trading-cockpit/options/positions?*',route=>route.fulfill({json:{
      positions:[],total_open:0,marked_count:0,marked_net_pnl_inr:null,all_positions_marked:true,
      coverage_limited:false,aggregate_greeks:null,fresh_greeks_count:0,
      generated_utc:new Date().toISOString(),warning:'User-entered journal only',orders_enabled:false
   }}))
   await advanced.getByRole('button',{name:'Manual trading workflow',exact:true}).click()
   const manual=page.getByRole('region',{name:'Manual options workflow'})
   await manual.getByRole('heading',{name:'Compare recorded expiries under the same assumptions'}).waitFor()
   await manual.getByText('2027-01-25',{exact:true}).waitFor()
   await manual.getByRole('tab',{name:'Positions & Exits',exact:true}).click()
   await manual.getByText('No open user-entered trades.',{exact:false}).waitFor()
   await manual.getByRole('tab',{name:'Contract Alerts',exact:true}).click()
   await manual.getByLabel('Verified contract identity',{exact:true}).fill(optionIdentity)
   await manual.getByLabel('Maximum ask ₹',{exact:true}).fill('200')
   await manual.getByRole('button',{name:'Create alert',exact:true}).click()
   await manual.getByText('Alert saved. Waiting for a new verified receipt.',{exact:true}).waitFor()
   await manual.getByRole('tab',{name:'Ranking Review',exact:true}).click()
   await manual.getByRole('button',{name:'Enable automatic shortlist recording',exact:true}).click()
   await manual.getByRole('button',{name:'Disable automatic shortlist recording',exact:true}).waitFor()
   await shot('02-trading-manual-options-workflow')
   await page.unroute(workflowUrl)
   await page.unroute('**/api/trading-cockpit/options/workflow/tracking')
   await page.unroute('**/api/trading-cockpit/options/workflow/alerts')
   await page.unroute('**/api/trading-cockpit/options/compare')
   await page.unroute('**/api/trading-cockpit/options/positions?*')
   await chainRegion.getByRole('button',{name:'Overview',exact:true}).click()
   await page.unroute('**/api/trading-cockpit/options/analytics?*')
   await page.unroute('**/api/trading-cockpit/options/chain?*')
   await page.unroute('**/api/trading-cockpit/options/expiries')
   await sub('20-Level Order Book')
   await page.getByText('20-level market depth',{exact:false}).first().waitFor()
   await shot('02-trading-depth')
   // Dedicated local research page never mounts broker order entry or a
   // second automatic recorder. All below are synthetic UI fixtures.
   await page.route('**/api/trading-cockpit/liquidity/overview?*',route=>route.fulfill({
     status:200,contentType:'application/json',body:JSON.stringify({
       rows:[{
         identity:'NSE_FNO:62539',expiry:'2026-11-23',strike:63400,
         option_type:'CE',lot_size:30,coverage_role:'core',best_bid:249,
         best_ask:250,spread_inr:1,spread_bps:40.08,imbalance_20:.25,
         bid_quantity_20:3000,ask_quantity_20:3000,
         top_bid_quantity:150,top_ask_quantity:150,
         saved_book_received_utc:'2026-11-23T04:05:00+00:00',
         source_book_age_seconds:31,recent_original_pair_age_seconds:2,
         feed_fresh:true,receipt_status:'valid_book_saved',
       }],
       filtered_selected:1,configured_depth_contracts:200,
       fresh_spread_sample_size:1,mean_fresh_spread_bps:40.08,
       expiry_options:['2026-11-23'],connected:true,
       market_regular_hours:true,source_status:'recording_original_depth',
       source:'original_Dhan_20_level_fixture',read_only:true,warning:'Research only',
     }),
   }))
   await page.route('**/api/trading-cockpit/liquidity/scan?*',route=>{
     // UI-only fixture. Does not assert that any real Zerodha orders filled.
     const q=new URL(route.request().url()).searchParams
     const profile=q.get('broker_profile')||'zerodha'
     const lot={lots:3,units:90,capital_required_inr:22500,
       within_budget:true,marketable_full_depth:true,
       top_of_book_both_sides_sufficient:true,
       hypothetical_buy_cash_debit_inr:22500,
       hypothetical_sell_cash_credit_inr:22560,
       buy_fees_inr:22,sell_fees_inr:30,total_fees_inr:52,
       passive_gross_inr:112,passive_upper_net_inr:60,
       passive_stressed_upper_net_inr:4,marketable_net_inr:-150,
       marketable_buy_cash_debit_inr:22580,
       marketable_sell_cash_credit_inr:22430,
       marketable_buy_fees_inr:22,marketable_sell_fees_inr:30}
     const row={identity:'NSE_FNO:62539',expiry:'2026-11-23',strike:63400,
       option_type:'CE',lot_size:30,received_utc:'2026-11-23T04:05:00+00:00',
       saved_book_age_seconds:9,fresh_original_saved_book:true,
       best_bid:249,best_ask:250,spread_inr:1,spread_bps:40.08,
       top_bid_quantity:150,top_ask_quantity:150,
       bid_quantity_20:3000,ask_quantity_20:3000,
       best_hypothetical_lots:3,required_capital_inr:22500,
       passive_upper_net_inr:60,passive_stressed_upper_net_inr:4,
       marketable_net_inr:-150,estimated_buy_fees_inr:22,
       estimated_sell_fees_inr:30,estimated_total_fees_inr:52,
       lot_scenarios:[lot],classification:'POSITIVE_HYPOTHETICAL_STRESS_BOUND',
       two_passive_fills_observed:false,actual_executed_orders:0,
       actual_profit_inr:null}
     return route.fulfill({status:200,contentType:'application/json',
       body:JSON.stringify({
         day_ist:'2026-11-23',broker_profile:profile,
         broker_profile_name:'Zerodha regular retail',
         capital_inr:50000,max_lots:10,executed_orders_per_side:1,
         adverse_move_bps:25,original_depth_contracts_found:1,
         source_scan_truncated:false,invalid_or_nonoriginal_books:0,
         evaluated_source_books:1,rankable_with_budget_and_depth:1,
         positive_stressed_upper_bounds:1,negative_stressed_upper_bounds:0,
         positive_even_without_stress:1,negative_even_optimistic:0,
         no_feasible_lots:0,recent_saved_books_60s:1,
         total_rows:1,scan_completed_utc:'2026-11-23T04:05:00+00:00',
         read_only:true,fills_observed:false,net_realized_profit_inr:null,
         source:'Dhan synthetic 20-level fixture',
         warning:'not actual fill evidence',rows:[row],
       })})
   })
   await page.route('**/api/trading-cockpit/liquidity/history?*',route=>{
     const book={identity:'NSE_FNO:62539',
       received_utc:'2026-11-23T04:05:00+00:00',expiry:'2026-11-23',
       strike:63400,option_type:'CE',lot_size:30,
       packet_pair_sha256:'c'.repeat(64),bid:249,ask:250,
       mid:249.5,spread_inr:1,spread_bps:40.08,imbalance_20:.25,
       bid_quantity_20:3000,ask_quantity_20:3000,
       top_bid_quantity:150,top_ask_quantity:150,
       bid_levels:Array.from({length:20},(_,i)=>({
         price:249-.05*i,quantity:150,orders:3})),
       ask_levels:Array.from({length:20},(_,i)=>({
         price:250+.05*i,quantity:150,orders:3})),
     }
     return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
       identity:'NSE_FNO:62539',day_ist:'2026-11-23',
       count:2,books:[book,{...book,
         received_utc:'2026-11-23T04:06:00+00:00',bid:248.5,
         ask:250.2,spread_bps:68.18}],
       more_source_records_possible:false,scanned_records:2,
       sampled_books_not_continuous:true,
       notice:'Only original saved Dhan book samples; no invented trades',
     })})
   })
   await page.route('**/api/trading-cockpit/liquidity/simulate',route=>route.fulfill({
     status:200,contentType:'application/json',body:JSON.stringify({
       status:'ORIGINAL_BOOK_SCENARIO_ONLY',identity:'NSE_FNO:62539',
       selected_book_received_utc:'2026-11-23T04:05:00+00:00',
       future_saved_quote_markouts:[
         {horizon_seconds:60,status:'NO_TIMELY_FUTURE_RECEIPT',
          received_utc:null,elapsed_seconds:null,observed_exit_bid_vwap:null,
          quote_markout_net_if_entry_filled_inr:null},
         {horizon_seconds:300,status:'NO_TIMELY_FUTURE_RECEIPT',
          received_utc:null,elapsed_seconds:null,observed_exit_bid_vwap:null,
          quote_markout_net_if_entry_filled_inr:null},
       ],
       markout_disclaimer:'Synthetic quote paths; no observed fills.',
       assumptions:{units:90,lots:3,lot_size:30,observed_bid:249,
         observed_ask:250,spread_bps:40.08,broker_orders_sent:0,read_only:true,
         marketable_buy:{fillable:true,vwap:250,levels_used:1,
           observed_units:90,missing_units:0},
         marketable_sell:{fillable:true,vwap:249,levels_used:1,
           observed_units:90,missing_units:0},
         marketable_roundtrip:{gross_inr:-90,estimated_net_inr:-171,
           status:'COUNTERFACTUAL_IMMEDIATE_CROSS_THE_SPREAD',fills_observed:false},
         execution_risk:{
           status:'FILL_PROBABILITIES_UNKNOWN',no_buy_fill_net_inr:0,
           both_passive_fills_net_inr:9,
           buy_fills_sell_misses_forced_exit_net_inr:-150,
           forced_exit_turnover_inr:22300,premium_at_risk_inr:22437.31,
           break_even_sell_fill_probability_given_buy:.944,
           scenario_weighted_net_inr:null,buy_fill_probability_assumed:null,
           sell_fill_probability_given_buy_assumed:null,
           probability_no_buy_fill:null,probability_both_fill:null,
           probability_buy_fill_exit_fails:null,
           adverse_move_bps_assumption:25,
           forced_exit_slippage_bps_assumption:10,
           recorded_bid_depth_sufficient_for_liquidation:true,
           top_book_quantity_sufficient:true,
           fill_probabilities_calibrated:false,realized_pnl_inr:null,
           explanation:'Synthetic read-only fixture; no live fills.',
         },
         passive_capture_upper_bound:{
           hypothetical_buy_at_bid:249,hypothetical_sell_at_ask:250,
           gross_inr:90,upper_bound_net_inr_before_unmodelled_costs:9,
           after_adverse_move_stress_inr:-47,
           adverse_move_bps_assumption:25,
           top_of_book_quantity_sufficient_both_sides:true,
           fills_observed:false,fill_probability:null,
           classification:'UNEXECUTABLE_OPTIMISTIC_UPPER_BOUND',
           caveat:'No passive order fills observed.',
           fees:{brokerage:40,exchange_indicative:4.5,sebi:.1,gst:8,
             stt_sell:34,stamp_buy:1,total_estimated:87.6,
             broker_profile:'zerodha',broker_profile_name:'Zerodha regular retail',
             buy_leg:{brokerage:20,exchange_indicative:2.25,sebi:.05,
               gst:4.01,stt_sell:0,stamp_buy:1,premium_turnover:22410,
               fees_total:27.31,cash_debit:22437.31},
             sell_leg:{brokerage:20,exchange_indicative:2.25,sebi:.05,
               gst:3.99,stt_sell:34,stamp_buy:0,premium_turnover:22500,
               fees_total:60.29,cash_credit:22439.71},
             assumptions:'Illustrative source-only fixture',version:'fixture'},
         },
       },
     }),
   }))
   await page.route('**/api/trading-cockpit/liquidity/research?*',route=>route.fulfill({
     status:200,contentType:'application/json',body:JSON.stringify({
       identity:'NSE_FNO:62539',day_ist:'2026-11-23',lots:3,
       status:'SOURCE_SNAPSHOT_UPPER_BOUND_ONLY',observed_saved_books:2,
       observed_spread_bps_mean:54.13,
       positive_optimistic_upper_bound_snapshots:1,
       net_profitable_executed_trades:null,executed_trades:0,
       fill_rate:null,warning:'NOT a backtest of filled orders',
       samples:[{received_utc:'2026-11-23T04:05:00+00:00',
         spread_bps:40.08,spread_inr:1,source_bid:249,source_ask:250,
         optimistic_net_if_two_passive_fills_inr:9,
         stress_net_inr:-47,marketable_same_book_net_inr:-171}],
     }),
   }))
   await sub('Liquidity & Spreads')
   await page.getByRole('tablist',{name:'Liquidity & Spreads modules'}).waitFor()
   const scanner=page.getByRole('region',{
     name:'Automatic spread profit and loss scanner'})
   await scanner.getByText('Spread P&L Opportunity Scanner').waitFor()
   await scanner.getByText('Risk-screened fresh research').waitFor()
   await scanner.getByText('NO TRADE',{exact:true}).first().waitFor()
   await scanner.getByText('To zero:').first().waitFor()
   await scanner.getByRole('button',{name:'All lots'}).click()
   await scanner.getByRole('region',{name:'Per-lot transaction cashflow ledger'}).waitFor()
   await scanner.getByText('Cash left after buy').waitFor()
   await scanner.getByText('Cash after hypothetical sell').waitFor()
   await scanner.getByLabel('Sort by').selectOption('marketable')
   await scanner.getByLabel('Show outcomes').selectOption('positive')
   await scanner.getByLabel('Charge profile').selectOption('dhan')
   await scanner.getByText('Not a profit prediction').waitFor()
   await shot('02-spread-auto-scanner')

   await page.getByRole('tabpanel',{name:'Live Spread Monitor'}).waitFor()
   await page.getByRole('button',{name:'Inspect'}).first().waitFor()
   await page.getByText('Original 20-level order book').waitFor()
   await shot('02-trading-liquidity')
   await page.getByRole('tab',{name:/Execution Simulator/}).click()
   await page.getByRole('button',{name:/Estimate from original book/}).click()
   await page.getByText('Passive upper-bound net').waitFor()
   await page.getByText('Execution outcome paths').waitFor()
   await page.getByText('Buy fills, sell misses').waitFor()
   await page.getByText('No passive order fills observed.').waitFor()
   await page.getByRole('tab',{name:/Historical Spread Analysis/}).click()
   await page.getByRole('img',{name:/Source-received option spread chart/}).waitFor()
   await page.getByRole('tab',{name:/Spread Strategy Lab/}).click()
   await page.getByRole('button',{name:/Analyze original saved books/}).click()
   await page.getByText('NOT a backtest of filled orders').waitFor()
   assert.equal(await page.getByText('Verified realized P&L').count(),1)
   assert.equal(await page.getByRole('button',{name:/Place live order/}).count(),0)

   // End-to-end browser fixture for new read-only multi-leg workflow.
   await page.route('**/api/trading-cockpit/spreads/multileg/scan?*',route=>{
     const legs=[
       {role:'Buy lower CE',identity:'NSE_FNO:1001',action:'BUY',
        expiry:'2026-11-23',option_type:'CE',strike:100,lots:1,
        units:30,lot_size:30,saved_utc:'2026-11-23T04:05:00+00:00',
        best_bid:29,best_ask:29.1,spread_bps:34,entry_vwap:29.1,
        exit_vwap:29,entry_premium_turnover_inr:873,
        entry_depth_levels_used:1,original_depth_verified:true},
       {role:'Sell higher CE',identity:'NSE_FNO:1002',action:'SELL',
        expiry:'2026-11-23',option_type:'CE',strike:110,lots:1,
        units:30,lot_size:30,saved_utc:'2026-11-23T04:05:00+00:00',
        best_bid:23,best_ask:23.1,spread_bps:43,entry_vwap:23,
        exit_vwap:23.1,entry_premium_turnover_inr:690,
        entry_depth_levels_used:1,original_depth_verified:true},
     ]
     const candidate={candidate_id:'bull_call_debit:NSE_FNO:1001:NSE_FNO:1002',
       strategy:'bull_call_debit',label:'Bull call debit vertical',
       group:'Directional',expiry:'2026-11-23',lots:1,units:30,legs,
       quote_skew_seconds:0,entry_premium_cashflow_inr:-183,
       entry_fees_inr:48,exit_fees_if_immediate_inr:48,
       estimated_same_book_immediate_roundtrip_net_inr:-102,
       max_profit_inr:69,max_loss_inr:231,risk_capital_proxy_inr:231,
       risk_reward_ratio_proxy:.3,break_even_underlying:[107.7],
       payoff_points:Array.from({length:61},(_,i)=>({
         underlying:80+i,net_payoff_inr:
           -231+30*Math.max(0,Math.min(i-20,10))})),
       source_age_seconds:9,fresh_reference:true,research_priority_score:47,
       broker_margin_verified:false,status:'PAPER_RESEARCH_ONLY_MARGIN_UNVERIFIED',
       paper_research_qualified:true,
       feasibility:{paper_research_qualified:true,reasons:[],
         research_priority_score:47,status:'PAPER_RESEARCH_ONLY',
         broker_margin_verified:false,required_broker_margin_inr:null},
       payoff_model:'Terminal intrinsic less entry charges, synthetic browser fixture.',
       read_only:true}
     return route.fulfill({status:200,contentType:'application/json',
       body:JSON.stringify({
         day_ist:'2026-11-23',capital_inr:50000,max_lots:5,
         valid_unique_contracts:2,original_depth_id_count:2,
         discovered_candidates:1,returned_candidates:1,
         execution_decision:{
           live_action:'NO_TRADE',research_status:'PAPER_TEST_CANDIDATES',
           paper_research_candidates:1,screened_candidates:1,
           rejection_reason_counts:{},expected_net_profit_inr:null,
           calibrated_fill_probability:null,
           explanation:'No real fills in synthetic fixture; paper-study only.'},
         ranked_candidates:[candidate],
         available_contracts:legs.map(l=>({
           identity:l.identity,expiry:l.expiry,strike:l.strike,
           option_type:l.option_type,lot_size:l.lot_size,
           received_utc:l.saved_utc,bid:l.best_bid,ask:l.best_ask,
           spread_bps:l.spread_bps})),
         rejected_reason_counts:{},
         strategies:[{key:'bull_call_debit',label:'Bull call debit vertical',
           group:'Directional',roles:['Buy lower CE','Sell higher CE'],
           actions:['BUY','SELL'],sides:['CE','CE'],
           qualified_candidates:1}],
         warning:'Research-only fixture; no fill, no broker margin.',
       })})
   })
   await page.getByRole('tab',{name:/Multi-Leg Option Spreads/}).click()
   const multi=page.getByRole('region',{
     name:'BANKNIFTY multi-leg option spreads'})
   await multi.getByText('Automatic research short-list').waitFor()
   await multi.getByText('NO TRADE',{exact:true}).first().waitFor()
   await multi.getByText('Paper-test candidates found').waitFor()
   await multi.getByRole('button',{name:'Analyze'}).click()
   await multi.getByText('Explore hypothetical expiry BANKNIFTY level').waitFor()
   await multi.getByRole('button',{name:/Save research snapshot/}).click()
   await multi.getByRole('button',{name:'Research Notebook'}).click()
   await multi.getByText('Browser-local observations').waitFor()
   await multi.getByRole('button',{name:'Build & Modify'}).click()
   await multi.getByText('Optional source-verified leg builder').waitFor()
   await shot('02-multileg-spread-studio')
   await page.unroute('**/api/trading-cockpit/spreads/multileg/scan?*')
   await page.unroute('**/api/trading-cockpit/liquidity/scan?*')
   await page.unroute('**/api/trading-cockpit/liquidity/overview?*')
   await page.unroute('**/api/trading-cockpit/liquidity/history?*')
   await page.unroute('**/api/trading-cockpit/liquidity/simulate')
   await page.unroute('**/api/trading-cockpit/liquidity/research?*')

   await sub('Market Replay')
   await page.locator('#tc-view-replay').waitFor()
   await sub('Paper Trading')
   const paper=page.getByRole('region',{name:'Paper Trading and Depth Replay'})
   await paper.getByRole('heading',{name:'Paper Trading & Replay'}).waitFor()
   await paper.getByRole('tab',{name:'Historical Depth / Spreads'}).click()
   await paper.getByRole('heading',{name:'Historical original-depth trade / spread replay'}).waitFor()
   await paper.getByRole('tab',{name:'Rule-Based Replay'}).click()
   await paper.getByRole('heading',{name:'Rule-based historical replay'}).waitFor()
   await paper.getByRole('tab',{name:'Paper Account & Orders'}).click()
   await shot('02-trading-paper-workspace')
   await sub('Trade Journal')
   await page.getByRole('heading',{name:'Trade Journal',exact:true}).waitFor()
   await shot('02-trading-journal')
 })
 await step('Strategies library, EMA all-mode, direct Python editor, options backtest',async()=>{
   await top('Strategies')
   await page.getByRole('heading',{name:'Strategy Library',exact:true}).first().waitFor()
   await page.getByRole('button',{name:/EMA Crossover/}).waitFor()
   await shot('03-strategy-library')
   await sub('EMA Explorer')
   await page.getByRole('radio',{name:/Test all supported pairs/}).check()
   await page.getByRole('button',{name:/Test all 11,026 EMA combinations/}).waitFor()
   await shot('03-ema-explorer')
   await sub('Python Editor')
   await page.getByRole('textbox',{name:'Paste or type Python backtest code'}).waitFor()
   await shot('03-python-editor')
   await sub('BANKNIFTY Backtests')
   await page.locator('[aria-label="BANKNIFTY signal backtest workspace"]').waitFor()
   await shot('03-options-backtest')
 })
 await step('Models catalog and existing index builder',async()=>{
   await top('Models')
   await page.getByRole('heading',{name:'Model Catalog',exact:true}).waitFor()
   await page.getByRole('navigation',{name:'Model research areas'}).waitFor()
   await page.getByRole('heading',{name:'What would you like to explore?'}).waitFor()
   // The layout has five mathematical families, not a 3D rendering family.
   assert.equal(await page.getByRole('button',{name:/3D Visual Laboratory/}).count(),0)
   await shot('04-model-catalog')
   await page.getByRole('button',{name:'Open Geometric Brownian Motion'}).click()
   await page.locator('.ql-model-focus-head').getByRole('heading',{
     name:'Geometric Brownian Motion'}).waitFor()
   const equationButton=page.getByRole('button',{name:'About & equation'})
   await equationButton.click()
   const explanation=page.getByRole('dialog',{name:'About Geometric Brownian Motion'})
   await explanation.waitFor()
   await explanation.getByText('Mathematical equation').waitFor()
   await page.keyboard.press('Escape')
   await explanation.waitFor({state:'hidden'})
   await page.getByRole('button',{name:/More settings/}).click()
   await page.getByRole('button',{name:'Run model',exact:true}).click()
   // Visualizations live in Results & Charts, not inside the model catalog.
   await page.getByRole('heading',{name:'All Research Results'}).waitFor({timeout:30000})
   await page.getByRole('navigation',{name:'Research results sections'}).waitFor()
   await shot('04-model-results-charts')
   await top('Models')
   await page.getByRole('button',{name:'Open Geometric Brownian Motion'}).waitFor()
   await sub('Index Builder')
   const indexWorkspace=page.getByRole('region',{name:'Index Builder workspace'})
   await indexWorkspace.waitFor()
   await page.getByRole('region',{name:'Index source and provenance'}).waitFor()
   await page.getByRole('region',{name:'Index factor research'}).waitFor()
   await page.getByRole('region',{name:'Index construction rules'}).waitFor()
   await page.getByRole('slider',{name:'Momentum factor contribution'}).waitFor()
   await page.getByRole('button',{name:'Get price history'}).waitFor()
   await page.getByRole('button',{name:'Build & backtest index'}).waitFor()
   await shot('04-index-builder')
   // Hidden research modules are accessible without cluttering the main tab row.
   const modelExtras=page.getByRole('navigation',{
     name:'Modules within selected research destination'}).locator('details.ws-context-more')
   await modelExtras.locator('summary').click()
   await modelExtras.getByRole('button',{name:'Risk Attribution'}).click()
   await page.locator('.ws-titlebar h1').getByText('Risk Attribution',{exact:true}).waitFor()
   await sub('Model Catalog')
   await page.getByRole('heading',{name:'What would you like to explore?'}).waitFor()
 })
 await step('Data Center unified market library acquisition explorer quality and downloads',async()=>{
   await top('Data Center')
   await page.getByRole('heading',{name:'Market Library',exact:true}).waitFor()
   await shot('05-data-library')
   await sub('Get Market Data')
   await page.getByRole('heading',{name:/Get the data/}).waitFor()
   await shot('05-get-data')
   await sub('Data Explorer')
   await page.getByRole('heading',{name:'Database Manager',exact:true}).waitFor()
   const dataTasks=page.getByRole('region',{name:'Choose a data task'})
   await dataTasks.getByRole('button',{name:/Browse market data/}).waitFor()
   await dataTasks.getByRole('button',{name:/Get missing data/}).click()
   await dataTasks.getByRole('button',{name:/Inspect stored records/}).click()
   await page.locator('.qm-panel-title').getByRole('heading',{name:'Data Explorer',exact:true}).waitFor()
   await dataTasks.getByRole('button',{name:/Health & recovery/}).click()
   await page.getByRole('heading',{name:'Whole-workstation health'}).waitFor()
   await dataTasks.getByRole('button',{name:/Inspect stored records/}).click()
   await shot('05-explorer')
   await sub('Quality & Coverage')
   await page.getByText('Market-data evidence audit',{exact:true}).first().waitFor()
   // Validate the dedicated anomaly detector end-to-end on isolated CI prices.
   await page.getByLabel('Observed dataset').selectOption('upload_ci_browser_smoke')
   await page.getByRole('button',{name:'Audit dataset',exact:true}).click()
   await page.locator('.rw-anomaly-findings').waitFor({timeout:30000})
   await page.getByRole('button',{name:'Export anomaly evidence'}).waitFor()
   await shot('05-statistical-source-anomalies')
   const sourceExtras=page.getByRole('navigation',{
     name:'Modules within selected research destination'}).locator('details.ws-context-more')
   await sourceExtras.locator('summary').click()
   await sourceExtras.getByRole('button',{name:'NSE Source Evidence'}).click()
   await page.locator('.ws-titlebar h1').getByText('NSE Source Evidence',{exact:true}).waitFor()
   await sub('Downloads')
   await page.getByRole('heading',{name:/See exactly what's happening/}).waitFor()
   await shot('05-downloads')
 })
 await step('Results run analysis, comparisons, chart builder and Projects',async()=>{
   await top('Results & Charts')
   await page.getByRole('heading',{name:'All Research Results',exact:true}).waitFor()
   const resultFilters=page.getByRole('group',{name:'Filter saved run types'})
   await resultFilters.getByRole('button',{name:'Models'}).click()
   await resultFilters.getByRole('button',{name:'Models'}).getAttribute('aria-pressed')
     .then(value=>assert.equal(value,'true'))
   await resultFilters.getByRole('button',{name:'All'}).click()
   await shot('06-results')
   await sub('Compare Runs')
   await page.getByText('Comparison and Graph Studio',{exact:true}).first().waitFor()
   await shot('06-compare')
   await sub('Chart Studio')
   await page.getByRole('heading',{name:'Chart Studio',exact:true}).waitFor()
   await shot('06-chart-studio')
   await top('Projects')
   await page.getByRole('heading',{name:'Organize your studies'}).waitFor()
   const creation=page.getByRole('group',{name:'Create research artifact'})
   await creation.getByRole('button',{name:'New project'}).waitFor()
   const notebookKind=creation.getByRole('button',{name:'Notebook'})
   if(await notebookKind.isEnabled()){
     await notebookKind.click()
     await page.getByRole('button',{name:'Create notebook'}).waitFor()
   }
   // Project inventory loads asynchronously; do not assert a transient
   // disabled state while the server populates saved project records.
   await creation.getByRole('button',{name:'New project'}).click()
   await page.getByRole('button',{name:'Create project'}).waitFor()
   await shot('07-projects')
 })
 await step('Settings providers, live recorder, storage, preferences and diagnostics',async()=>{
   await top('Settings')
   await page.getByRole('heading',{name:'Your connections',exact:true}).waitFor()
   await page.getByRole('region',{name:'Connections overview'}).waitFor()
   await shot('08-connections')
   await page.getByRole('button',{name:/Manage Dhan connection/}).click()
   await page.getByRole('region',{name:'Dhan data API connection'}).waitFor()
   await page.getByRole('button',{name:/Back to Connections/}).click()
   await page.getByRole('heading',{name:'Your connections',exact:true}).waitFor()
   await sub('Automatic Recording')
   await page.getByRole('region',{name:'Automatic BANKNIFTY 20-level order-book recorder'}).waitFor()
   await shot('08-recording')
   const advancedSettings=page.getByRole('navigation',{
     name:'Modules within selected research destination'}).locator('details.ws-context-more')
   await advancedSettings.locator('summary').click()
   await advancedSettings.getByRole('button',{name:'Storage & Data Management'}).click()
   await page.getByRole('heading',{name:'Database Manager',exact:true}).waitFor()
   await advancedSettings.locator('summary').click()
   await advancedSettings.getByRole('button',{name:'Preferences'}).click()
   await page.getByText('Appearance & units',{exact:true}).waitFor()
   await sub('System Diagnostics')
   await page.getByRole('heading',{name:'Diagnostics',exact:true}).waitFor()
   const recorderDiagnostic=page.locator('.v2-health-list>div').filter({hasText:'Dhan market capture'})
   await recorderDiagnostic.waitFor()
   await recorderDiagnostic.locator('span').getByText(/(Healthy|Waiting|Needs attention)/).waitFor()
   assert.ok(['healthy','waiting','attention'].includes(
     await recorderDiagnostic.getAttribute('data-status')),
     'Recorder health must be classified using packet and connection evidence')
   await page.getByText('HTTP 200', {exact:false}).first().waitFor()
   await shot('08-diagnostics')
 })
 await step('Advanced mathematical grids, index research, evidence and resource library remain accessible',async()=>{
   const archived=[
     ['modelgrids','Guided Model Grids'],
     ['indexstudio','Index Research Studio'],
     ['evidence','Evidence & Machine Learning'],
     ['resourcebrowser','Saved Resource Library'],
   ]
   for(const [route,heading] of archived){
     await page.goto(base+'#/'+route,{waitUntil:'domcontentloaded'})
     await page.getByRole('heading',{name:heading,exact:true}).waitFor()
     await page.locator('.rw-root').waitFor()
   }
   await shot('08-advanced-research-library')
 })
 await step('V3 custom Python libraries and scientific environment routes',async()=>{
   for(const [route,label] of [['pythonmonitors','Running Python monitors'],['custommodels','Custom model library'],['customscanners','Custom scanner library'],['pythonenvironment','Python environment manager']]){
     await page.goto(base+'#/'+route,{waitUntil:'domcontentloaded'})
     await page.getByRole('region',{name:label,exact:true}).waitFor()
   }
 })
 await step('Deep-link, browser back and Help / New Study buttons',async()=>{
   await page.goto(base+'#/strategyema',{waitUntil:'domcontentloaded'})
   await page.getByRole('heading',{name:'EMA Explorer',exact:true}).waitFor()
   await page.getByRole('button',{name:'Open Help'}).click()
   await page.getByRole('heading',{name:'Help & How It Works',exact:true}).waitFor()
   await page.getByRole('button',{name:'New Study'}).click()
   await page.getByRole('heading',{name:'New Guided Study',exact:true}).waitFor()
   await page.goBack()
   await page.getByRole('heading',{name:'Help & How It Works',exact:true}).waitFor()
   await page.goBack()
   await page.getByRole('heading',{name:'EMA Explorer',exact:true}).waitFor()
 })
 await step('390-pixel responsive sidebar drawer and eight navigable pages',async()=>{
   await page.setViewportSize({width:390,height:844})
   await page.getByRole('button',{name:'Open navigation'}).click()
   await page.locator('.ws-sidebar').getByRole('button',{name:'Data Center'}).click()
   await page.getByRole('heading',{name:'Market Library',exact:true}).waitFor()
   assert.equal(await page.locator('.ws-sidebar .ws-nav-item').count(),8)
   await shot('09-mobile-data')
 })
 assert.equal(errors.length,0,'React browser exceptions: '+JSON.stringify(errors))
 // Provider/source 500s are reported explicitly; they are not silently
 // accepted as evidence of working data, and CI source fixture should have none.
 assert.equal(badApi.length,0,'Backend API 500s: '+JSON.stringify(badApi))
}finally{
 await fs.writeFile(path.join(dir,'v2-acceptance.json'),
  JSON.stringify({results,errors,badApi,scope:'Synthetic CI fixtures; not live Dhan'},null,2))
 await browser.close()
}
