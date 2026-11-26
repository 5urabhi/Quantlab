/** Isolated UI fixture; no Dhan subscription or broker action is invoked. */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import {chromium} from 'playwright'
const base=process.env.QUANTLAB_SMOKE_URL||'http://127.0.0.1:5173'
const dir=path.resolve(process.env.QUANTLAB_SMOKE_ARTIFACT_DIR||'artifacts/browser-smoke')
await fs.mkdir(dir,{recursive:true})
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--disable-dev-shm-usage']})
const page=await browser.newPage({viewport:{width:1440,height:900}})
page.setDefaultTimeout(20000)
const errors=[]
page.on('pageerror',e=>errors.push(String(e)))
const cutoff='2026-11-23T04:10:00+00:00'
const anchor='2026-11-23T04:05:00+00:00'
const current={identity:'NSE_EQ:10',price:101,received_utc:cutoff,exchange_trade_utc:cutoff,volume:1200,atp:100,buy_quantity:60,sell_quantity:20}
const rows=[
 {symbol:'BANKA',weight_pct:60,current,anchor:{...current,price:100,volume:1000,received_utc:anchor,exchange_trade_utc:anchor},return_pct:1,volume_delta:200,relative_volume:2,baseline_sessions:5,atp_deviation_pct:1,displayed_quantity_imbalance:.5,contribution_pp:.6,approx_index_points:360},
 {symbol:'BANKB',weight_pct:40,current:null,anchor:null,return_pct:null,volume_delta:null,relative_volume:null,baseline_sessions:0,atp_deviation_pct:null,displayed_quantity_imbalance:null,contribution_pp:null,approx_index_points:null}
]
try{
 await page.route('**/api/trading-cockpit/constituents/status',route=>route.fulfill({json:{enabled:false,connected:false,state:'not_subscribed',requested:{},saved:0,dropped:0,ignored_stale:0,sample_seconds:2,last_saved_utc:null,storage:{state:'not_observed',last_error:null},note:'CI-only fixture'}}))
 await page.route('**/api/trading-cockpit/constituents/analysis?*',route=>{
  const horizon=Number(new URL(route.request().url()).searchParams.get('horizon'))
  if(new URL(page.url()).hash==='#/tradingpatterns'){
    const liveStamp=new Date().toISOString()
    const q={...current,received_utc:liveStamp,exchange_trade_utc:liveStamp}
    return route.fulfill({json:{as_of_utc:liveStamp,anchor_utc:anchor,session_ist:'2026-11-23',horizon_minutes:horizon,
      membership:{symbols:['BANKA','BANKB','BANKC']},weight_snapshot:{snapshot_date:'2026-11-23'},
      rows:[{...rows[0],current:q,session_return_pct:1.5},{...rows[1],symbol:'BANKB',weight_pct:25,current:q,return_pct:-.5,session_return_pct:-1},
            {...rows[1],symbol:'BANKC',weight_pct:15,session_return_pct:null}],
      expected_members:3,observed_members:2,observed_weight_pct:85,weighted_breadth_pct:null,weighted_return_pct:null,
      blockers:['Incomplete synthetic fixture'],note:'CI-only synthetic heatmap fixture'}})
  }
  return route.fulfill({json:{as_of_utc:cutoff,anchor_utc:anchor,session_ist:'2026-11-23',horizon_minutes:horizon,
    membership:{date:'2026-11-23',symbols:['BANKA','BANKB']},weight_snapshot:{snapshot_date:'2026-11-23',source:'Synthetic CI-only weights',source_csv_sha256:'a'.repeat(64),recorded_utc:anchor,reported_weight_sum_pct:100},
    rows,expected_members:2,observed_members:1,observed_weight_pct:60,complete_weighted_coverage:false,weighted_return_pct:null,weighted_breadth_pct:null,partial_contribution_pp:.6,spot_anchor:60000,blockers:['Incomplete aligned constituent quotes. Unobserved moves are not zero-filled.'],note:'Synthetic browser fixture; not market evidence.'}})
 })
 for(const [width,height] of [[1440,900],[390,844]]){
  await page.setViewportSize({width,height})
  await page.goto(base+'#/tradingdirectional',{waitUntil:'domcontentloaded'})
  const pane=page.getByRole('region',{name:'BANKNIFTY constituent intelligence'})
  await pane.getByRole('table',{name:'BANKNIFTY constituent metrics'}).waitFor()
  await pane.getByRole('button',{name:'Signal research',exact:true}).click()
  const prospective=pane.getByRole('region',{name:'Prospective constituent and EMA evaluation'})
  await prospective.getByRole('table',{name:'Prospective rule scores'}).waitFor()
  await prospective.getByRole('table',{name:'Matched constituent versus EMA comparisons'}).waitFor()
  assert.equal(await prospective.getByRole('button',{name:'Enable prospective recording'}).isDisabled(),true)
  await prospective.getByRole('combobox',{name:'Prospective outcome horizon'}).selectOption('30')
  await prospective.getByText('Returned 30m ledger window',{exact:true}).first().waitFor()
  const calibration=prospective.getByRole('region',{name:'Frozen probability validation'})
  await calibration.getByRole('button',{name:'Inspect probability evidence'}).click()
  await calibration.getByText(/0 \/ 50 ended recorded dates/).waitFor()
  await pane.getByRole('button',{name:'Stock derivatives',exact:true}).click()
  const derivatives=pane.getByRole('region',{name:'Constituent futures and stock options'})
  await derivatives.getByRole('button',{name:'Inspect stored derivative movement'}).click()
  await derivatives.getByRole('table',{name:'Stored derivative movement'}).waitFor()
  await pane.getByRole('button',{name:'Data setup',exact:true}).click()
  await pane.getByRole('region',{name:'Archived constituent weights'}).getByRole('button',{name:'Inspect saved weightage receipts'}).click()
  await pane.getByRole('combobox',{name:'Archived weight receipt'}).waitFor()
  await pane.getByRole('button',{name:'Bank movement',exact:true}).click()
  await pane.getByRole('combobox',{name:'Constituent chart'}).selectOption('contribution')
  await pane.getByRole('heading',{name:'Estimated weighted index contributions'}).waitFor()
  assert.match(await pane.innerText(),/1 \/ 2/)
  assert.match(await pane.innerText(),/Missing constituent weight is not treated as flat/)
  await pane.getByRole('combobox',{name:'Constituent chart'}).selectOption('returns')
  await pane.getByRole('combobox',{name:'Constituent pressure horizon'}).selectOption('10')
  await pane.getByRole('heading',{name:'Observed constituent returns · 10 minutes'}).waitFor()
  await pane.getByRole('combobox',{name:'Sort constituents'}).selectOption('relative_volume')
  await pane.getByRole('combobox',{name:'Constituent analysis time'}).selectOption('history')
  await pane.getByLabel('Constituent historical time IST').fill('2026-11-23T09:40')
  const request=page.waitForRequest(r=>r.url().includes('/constituents/analysis?')&&new URL(r.url()).searchParams.get('as_of')==='2026-11-23T09:40:00+05:30')
  await pane.getByRole('button',{name:'Inspect saved timestamp'}).click()
  await request
  await pane.getByRole('table',{name:'BANKNIFTY constituent metrics'}).waitFor()
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2),false,'Constituent page overflow at '+width)
  await page.screenshot({path:path.join(dir,'constituent-intelligence-'+width+'.png'),fullPage:false})
  await page.goto(base+'#/tradingpatterns',{waitUntil:'domcontentloaded'})
  const heat=page.getByRole('region',{name:'Bank Nifty constituent heatmap'})
  await heat.getByRole('button',{name:/BANKA/}).waitFor()
  assert.match(await heat.getByRole('button',{name:/BANKA/}).getAttribute('class'),/\bup[123]\b/)
  assert.match(await heat.getByRole('button',{name:/BANKB/}).getAttribute('class'),/\bdown[123]\b/)
  assert.match(await heat.getByRole('button',{name:/BANKC/}).getAttribute('class'),/\bmissing\b/)
  await heat.getByRole('button',{name:/BANKA/}).click()
  await heat.getByRole('region',{name:'Bank details BANKA'}).waitFor()
  await heat.getByRole('combobox',{name:'Bank heatmap return period'}).selectOption('session')
  await heat.getByRole('button',{name:/BANKA \+1.5%/}).waitFor()
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2),false,'Heatmap page overflow at '+width)
  await page.screenshot({path:path.join(dir,'bank-heatmap-'+width+'.png'),fullPage:false})
 }
 assert.deepEqual(errors,[])
 console.log('Constituent intelligence desktop/mobile fixture passed')
}finally{await browser.close()}
