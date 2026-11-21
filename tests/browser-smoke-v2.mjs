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
   await sub('20-Level Order Book')
   await page.getByText('20-level market depth',{exact:false}).first().waitFor()
   await shot('02-trading-depth')
   await sub('Market Replay')
   await page.locator('#tc-view-replay').waitFor()
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
   await page.getByText('Experiment configuration',{exact:true}).waitFor()
   await page.getByRole('button',{name:/Run Python backtest/}).waitFor()
   await shot('04-index-builder')
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
   await page.getByText('Research projects',{exact:false}).first().waitFor()
   await shot('07-projects')
 })
 await step('Settings providers, live recorder, storage, preferences and diagnostics',async()=>{
   await top('Settings')
   await page.getByRole('heading',{name:'Connections',exact:true}).waitFor()
   await page.getByRole('region',{name:'Dhan data API connection'}).waitFor()
   await shot('08-connections')
   await sub('Automatic Recording')
   await page.getByRole('region',{name:'Automatic BANKNIFTY 20-level order-book recorder'}).waitFor()
   await shot('08-recording')
   await sub('Storage & Data Management')
   await page.getByRole('heading',{name:'Database Manager',exact:true}).waitFor()
   await sub('Preferences')
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
