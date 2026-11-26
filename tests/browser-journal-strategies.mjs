/** Explicit UI-only fixture: no actual broker fills, signals or data writes. */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import {chromium} from 'playwright'
const base=process.env.QUANTLAB_SMOKE_URL||'http://127.0.0.1:5173'
const dir=path.resolve(process.env.QUANTLAB_SMOKE_ARTIFACT_DIR||'artifacts/browser-smoke')
await fs.mkdir(dir,{recursive:true})
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--disable-dev-shm-usage']})
const page=await browser.newPage({viewport:{width:1440,height:900}})
const errors=[]
page.on('pageerror',e=>errors.push(String(e)))
page.setDefaultTimeout(20000)
const days=[{exit_session_ist:'2026-11-25',closed:1,net_pnl_inr:-40,over_6_min:0},{exit_session_ist:'2026-11-24',closed:2,net_pnl_inr:150,over_6_min:1}]
const predictions=[{session_ist:'2026-11-24',total:4,scored:2,correct:1,incorrect:1,pending:1,no_trade:0,flat:0,unverifiable:1,directional_accuracy:.5},{session_ist:'2026-11-25',total:2,scored:0,correct:0,incorrect:0,pending:2,no_trade:0,flat:0,unverifiable:0,directional_accuracy:null}]
const script={id:'ci-strategy',name:'CI example strategy',kind:'strategy',revision:2,updated_utc:'2026-11-25T00:00:00Z'}
try{
 await page.route('**/api/trading-cockpit/trades?*',route=>route.fulfill({json:{trades:[],summary:{open:0,closed:3,closed_net_pnl_inr:110,holding_violations:1,limited_to_recent:true,days},disclaimer:'Synthetic UI fixture, not verified fills'}}))
 await page.route('**/api/trading-cockpit/predictions?*',route=>route.fulfill({json:{predictions:[],summary:{evaluated_directions:2,correct_directions:1,direction_accuracy:.5,qualification:'Synthetic UI fixture'}}}))
 await page.route('**/api/trading-cockpit/report?*',route=>route.fulfill({json:{days:predictions,overall:{total:6,scored:2,correct:1,incorrect:1,pending:3,no_trade:0,flat:0,unverifiable:1,directional_accuracy:.5},source:'Synthetic UI fixture',disclaimer:'No verified signals',truncated:true}}))
 await page.route('**/api/user-scripts',route=>route.fulfill({json:{scripts:[script,{id:'ci-model',name:'CI nonstrategy',kind:'model',revision:1}],sandbox:{available:true}}}))
 await page.route('**/api/script-monitors',route=>route.fulfill({json:{monitors:[{id:'m-ci',name:script.name,kind:'strategy',revision:1,state:'paused',enabled:false}]}}))
 await page.route('**/api/user-scripts/ci-strategy',route=>route.fulfill({json:{script_id:script.id,name:script.name,kind:script.kind,revision:2,code:'def signal(data):\n    return "HOLD"',revisions:[{revision:2,created_utc:script.updated_utc,name:script.name,kind:script.kind}]}}))
 for(const [width,height] of [[1440,900],[390,844]]){
   await page.setViewportSize({width,height})
   await page.goto(base+'#/tradingjournal',{waitUntil:'domcontentloaded'})
   await page.getByRole('heading',{level:1,name:'Trade Journal'}).waitFor()
   const trade=page.getByRole('region',{name:'Manual trade performance charts'})
   await trade.getByRole('heading',{name:'Net recorded P&L by exit date'}).waitFor()
   await trade.getByRole('heading',{name:'Cumulative net recorded P&L · returned entries'}).waitFor()
   assert.match(await trade.innerText(),/not lifetime P&L/)
   await page.screenshot({path:path.join(dir,'journal-manual-'+width+'.png'),fullPage:false})
   await page.getByRole('tab',{name:'Prediction accuracy'}).click()
   const prediction=page.getByRole('region',{name:'Prospective prediction performance charts'})
   await prediction.getByRole('heading',{name:'Observed directional accuracy by session'}).waitFor()
   assert.match(await prediction.innerText(),/not trading P&L/)
   await page.screenshot({path:path.join(dir,'journal-accuracy-'+width+'.png'),fullPage:false})
   const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+2)
   assert.equal(overflow,false,'Journal page overflows at '+width)
   await page.goto(base+'#/strategies',{waitUntil:'domcontentloaded'})
   const registry=page.getByRole('region',{name:'Saved strategy registry'})
   await registry.getByText(script.name,{exact:true}).first().waitFor()
   await registry.getByRole('searchbox',{name:'Search saved strategies'}).fill('nonexistent')
   await registry.getByText('No matching saved strategy.').waitFor()
   await registry.getByRole('searchbox',{name:'Search saved strategies'}).fill('CI example')
   assert.equal(await registry.getByRole('button',{name:'Open saved strategy'}).count(),1)
   await registry.getByRole('button',{name:'Open saved strategy'}).click()
   const python=page.getByRole('region',{name:'Python research workspace'})
   await python.getByText(/Loaded revision 2/).waitFor()
   await python.getByRole('button',{name:'Minimize'}).click()
   await page.screenshot({path:path.join(dir,'saved-strategies-'+width+'.png'),fullPage:false})
 }
 assert.deepEqual(errors,[])
 console.log('Journal and strategy registry browser acceptance: synthetic UI fixtures passed')
}finally{await browser.close()}
