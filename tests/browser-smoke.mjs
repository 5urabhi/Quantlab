/**
 * Ubuntu Chromium acceptance: real browser -> Vite proxy -> FastAPI -> local
 * deterministic CI fixture -> rendered numerical response.
 *
 * This is not a Dhan live-credential test or investment-data certification.
 * Run via .github/workflows/workstation-browser-smoke.yml.
 */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { chromium } from 'playwright'

const artifactDir = path.resolve(process.env.QUANTLAB_SMOKE_ARTIFACT_DIR || 'artifacts/browser-smoke')
await fs.mkdir(artifactDir, { recursive: true })
const base = process.env.QUANTLAB_SMOKE_URL || 'http://127.0.0.1:5173'
const steps = []
const errors = []
const api500 = []
let browser
let page

function record(name, status, detail = '') {
  steps.push({ name, status, detail, at: new Date().toISOString() })
  console.log('[browser-smoke] ' + status + ': ' + name + (detail ? ' (' + detail + ')' : ''))
}
async function step(name, fn) {
  const started = Date.now()
  try {
    await fn()
    record(name, 'PASS', Date.now() - started + ' ms')
  } catch (e) {
    record(name, 'FAIL', String(e))
    if (page) {
      try {
        await page.screenshot({path: path.join(artifactDir, 'failed-' +
            name.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0,55)+'.png'),fullPage:true})
      } catch {}
    }
    throw e
  }
}
function nav(name) {
  return page.locator('.ws-sidebar nav').getByRole('button', {name, exact:true})
}
function researchTab(name) {
  return page.locator('.rw-navigation').getByRole('tab', {name: new RegExp('^'+name)})
}
async function apiJson(endpoint) {
  const response = await page.request.get(base + endpoint)
  assert.equal(response.status(), 200, endpoint + ': ' + (await response.text()).slice(0,400))
  return response.json()
}
async function waitJobComplete(jobId) {
  for (let attempt=0; attempt<75; attempt++) {
    const data = await apiJson('/api/workspace/jobs')
    const job = data.jobs.find(x => x.id === jobId)
    if (job?.status === 'complete') return job
    if (job?.status === 'error' || job?.status === 'cancelled')
      throw new Error('Report job did not succeed: ' + JSON.stringify(job))
    await new Promise(resolve=>setTimeout(resolve,500))
  }
  throw new Error('Timed out waiting for actual report job ' + jobId)
}
async function screenshot(name) {
  await page.screenshot({path:path.join(artifactDir,name+'.png'),fullPage:true})
}
try {
  browser = await chromium.launch({headless:true,args:['--no-sandbox','--disable-dev-shm-usage']})
  const context = await browser.newContext({
    viewport: {width: 1440, height: 900}, deviceScaleFactor: 1,
    acceptDownloads:true, locale:'en-US', colorScheme:'dark'
  })
  page = await context.newPage()
  page.setDefaultTimeout(18000)
  page.on('pageerror', e => errors.push(String(e)))
  page.on('response', r=>{
    try {
      if (new URL(r.url()).pathname.startsWith('/api/') && r.status() >= 500)
        api500.push(r.status()+' '+r.request().method()+' '+new URL(r.url()).pathname)
    } catch {}
  })
  await step('backend and nine-destination shell', async()=>{
    const health=await apiJson('/api/health')
    assert.equal(health.broker_orders_enabled,false,'Broker execution must be off')
    assert.equal(health.dhan_token_configured,false,'CI fixture must have no broker token')
    await page.goto(base,{waitUntil:'domcontentloaded'})
    await page.getByText('ENGINE ONLINE',{exact:true}).waitFor({timeout:25000})
    const buttons = page.locator('aside .ws-nav-item')
    assert.equal(await buttons.count(),9,'Exactly nine main destinations')
    await screenshot('01-home-desktop')
  })
  await step('all research destination views and nested navigation',async()=>{
    for (const section of ['Guided Research','Home','Data Library','Model Laboratory','Experiment Studio',
      'Compare & Visualize','Results Studio','Research Projects','Help & Settings']) {
      await nav(section).click()
      const header=page.locator('.ws-titlebar h1')
      assert.ok((await header.innerText()).length>2,'Destination must have a visible title: '+section)
    }
    // The source assistant belongs in the Data Library shown in the UI.
    await nav('Data Library').click()
    const dataTabs=page.getByRole('navigation',{name:'Modules within selected research destination'})
    await dataTabs.getByRole('button',{name:'Data manager',exact:true}).waitFor()
    await dataTabs.getByRole('button',{name:'Download market data',exact:true}).waitFor()
    await dataTabs.getByRole('button',{name:'NSE Sources',exact:true}).click()
    await page.locator('.ws-titlebar h1').getByText('NSE Sources',{exact:true}).waitFor()
    const directNse=page.getByRole('region',{name:'NSE Source Assistant'})
    await directNse.waitFor()
    await directNse.getByRole('button',{name:'Check connection'}).waitFor()
    assert.equal(await directNse.getByRole('textbox',{name:'NSE stock symbol'}).inputValue(),'RELIANCE',
      'An editable example should not look like a disabled placeholder')
    assert.equal(await directNse.getByRole('button',{name:'Check NSE source'}).isEnabled(),true)
    await screenshot('01-nse-sources-visible-in-data-library')
    await dataTabs.getByRole('button',{name:'Data manager',exact:true}).click()
    await page.locator('.mdw-root').getByRole('tab',{name:'My Datasets'}).waitFor()
    await dataTabs.getByRole('button',{name:'NSE Sources',exact:true}).click()
    await directNse.waitFor()
    await nav('Compare & Visualize').click()
    await page.locator('.rw-top h2').waitFor()
    assert.equal(await researchTab('Plot Builder').count(),1)
  })
  await step('guided data-to-model-to-evidence-to-save flow',async()=>{
    await nav('Guided Research').click()
    await page.getByRole('region',{name:'Research step 1: Select data'}).waitFor()
    await page.getByRole('button',{name:/Next · Choose a research model/}).click()
    await page.getByRole('region',{name:'Research step 2: Choose model'}).waitFor()
    await page.locator('.rj-model-grid button').filter({hasText:'Geometric Brownian Motion'}).first().click()
    await page.getByRole('button',{name:/Configure and run Geometric Brownian Motion/}).click()
    await page.getByRole('region',{name:'Research step 3: Run model'}).waitFor()
    await page.getByRole('button',{name:'Run selected model'}).click()
    await page.getByRole('region',{name:'Research step 4: Analyze saved run'}).waitFor({timeout:40000})
    await page.locator('.rs-identity h3').waitFor({timeout:20000})
    await page.getByRole('button',{name:/Next · Save and export evidence/}).click()
    const last=page.getByRole('region',{name:'Research step 5: Save evidence'})
    await last.waitFor()
    await last.getByText(/already saved/).waitFor()
    const exportLink=last.getByRole('link',{name:/Export research evidence ZIP/})
    assert.match(await exportLink.getAttribute('href'),/evidence-bundles\/model_run\/.+\.zip$/)
    const response=await page.request.get(new URL(await exportLink.getAttribute('href'),base).href)
    assert.equal(response.status(),200,'Actual saved evidence ZIP should be exportable')
    assert.match(response.headers()['content-type'],/application\/zip/)
    await screenshot('01-guided-research-evidence-export')
  })
  await step('Results Studio source-classified evidence audit and export',async()=>{
    await nav('Results Studio').click()
    await page.locator('.rs-identity h3').waitFor()
    await page.locator('.rs-tabs').getByRole('button',{name:'Evidence audit'}).click()
    await page.getByRole('heading',{name:'Research Evidence Audit'}).waitFor()
    await page.locator('.rs-check-gates .rs-gate').first().waitFor({timeout:20000})
    const saved=await apiJson('/api/lab/runs?limit=30')
    const audit=await apiJson('/api/workspace/results/model_run/'+saved.runs[0].id+'/evidence')
    assert.equal(audit.evidence_class,'synthetic_demo','GBM is synthetic, not historical')
    assert.equal(audit.readiness,'research_diagnostic_only')
    assert.ok(audit.checks.some(check=>check.status==='blocked'))
    assert.ok(await page.getByRole('button',{name:'Evidence JSON'}).isEnabled())
    await screenshot('02-results-evidence-audit')
  })
  await step('Ask QuantLab references exact saved evidence, not fabricated claims',async()=>{
    await nav('Results Studio').click()
    await page.locator('.rs-identity h3').waitFor()
    await page.locator('.rs-tabs').getByRole('button',{name:'Ask QuantLab'}).click()
    const assistant=page.getByRole('region',{name:'Research assistant'})
    await assistant.waitFor()
    await assistant.getByRole('button',{name:'Can I trust this result?'}).click()
    await assistant.getByRole('heading',{name:'Can this result be trusted?'}).waitFor()
    assert.match(await assistant.innerText(),/synthetic|evidence|independent/i)
    await assistant.getByRole('button',{name:/Exact validation checks and statistical evidence/}).click()
    await page.getByRole('heading',{name:'Research Evidence Audit'}).waitFor()
    await page.locator('.rs-tabs').getByRole('button',{name:'Ask QuantLab'}).click()
    await assistant.getByRole('heading',{name:'Can this result be trusted?'}).waitFor()
    await screenshot('02-assistant-saved-evidence-links')
  })
  await step('historical evidence source checks and safe frozen-test gating',async()=>{
    await nav('Experiment Studio').click()
    await page.locator('.hv-root').waitFor()
    await page.getByRole('heading',{name:/Original sources.*independent review.*frozen test/}).waitFor()
    await page.locator('.hv-checks .hv-check').first().waitFor({timeout:25000})
    const text=await page.locator('.hv-root').innerText()
    assert.match(text,/not independently audited/i,
      'Original source review must never be silently approved in synthetic CI')
    assert.match(text,/Historical study incomplete/i)
    assert.equal(await page.getByRole('button',{name:/Create frozen protocol/}).isDisabled(),true,
      'Short CI fixture must not be treated as a valid final-test study')
    await page.getByRole('region',{name:'Original-source missing-data worklist'}).waitFor()
    const gapPanel=page.getByRole('region',{name:'Original-source missing-data worklist'})
    assert.match(await gapPanel.innerText(),/Exact missing history and evidence to collect/)
    assert.match(await gapPanel.innerText(),/Training history.*preferred.*20%/i)
    assert.match(await gapPanel.innerText(),/Original-source|NOT AUTO-CERTIFIED/)
    const officialGuide=gapPanel.locator('.hv-public-guide')
    await officialGuide.getByRole('heading',{name:/Public NSE reports you can collect/}).waitFor()
    assert.equal(await officialGuide.locator('.hv-public-grid').first().locator('a').count(),6,
      'Six public official-source pages must be actionable without an approval workflow')
    const archiveLink=officialGuide.getByRole('link',{name:/Open official archive/}).first()
    assert.equal((await archiveLink.getAttribute('href'))?.startsWith('https://'),true)
    await officialGuide.getByText(/Approval-only NSE research programs/).click()
    await officialGuide.getByText('NSE Data for Analytics / NSE Data Room').waitFor()
    assert.match(await officialGuide.innerText(),/Research committee review/i)
    const gapDownload=page.waitForEvent('download')
    await gapPanel.getByRole('link',{name:'Export missing-source ZIP'}).click()
    const gapFile=await gapDownload
    const gapFilename=path.join(artifactDir,'source-worklist.zip')
    await gapFile.saveAs(gapFilename)
    const gapBytes=await fs.readFile(gapFilename)
    assert.equal(gapBytes.subarray(0,2).toString(),'PK',
      'Worklist must be a real ZIP file, not an inert button or placeholder')
    const gapAudit=await apiJson('/api/workspace/historical-sources/upload_ci_browser_smoke')
    assert.equal(typeof gapAudit.existing_benchmark.state,'string',
      'Existing benchmark must be inspected before suggesting duplicate TRI import')
    assert.equal(gapAudit.existing_benchmark.independently_verified,false)
    const assistant=gapPanel.getByRole('region',{name:'NSE Source Assistant'})
    await assistant.waitFor()
    assert.match(await assistant.innerText(),/Official NSE MCP runs inside/)
    assert.equal(await assistant.getByRole('tab',{name:'Corporate actions'})
      .getAttribute('aria-selected'),'true')
    let providerRequests=0
    await page.route('**/api/workspace/nse-sources/query',async route=>{
      providerRequests++
      const request=route.request().postDataJSON()
      assert.equal(request.task,'corporate_actions')
      assert.equal(request.symbol,'RELIANCE')
      await route.fulfill({status:200,contentType:'application/json',
        body:JSON.stringify(providerRequests===1?{
          status:'provider_unavailable',task:'corporate_actions',provider:'NSE Official MCP',
          message:'Corporate actions for RELIANCE could not be fetched from NSE right now.',
          data:null,warnings:[],research_data_updated:false,no_events_verified:false
        }:{
          status:'available',task:'corporate_actions',provider:'NSE Official MCP',
          data:{events:[{symbol:'RELIANCE',exDate:'2026-10-01'}]},warnings:[],
          research_data_updated:false,no_events_verified:false
        })})
    })
    await assistant.getByRole('textbox',{name:'NSE stock symbol'}).fill('RELIANCE')
    await assistant.getByRole('button',{name:'Check NSE source'}).click()
    await assistant.getByRole('alert').filter({hasText:'NSE could not provide this source'}).waitFor()
    assert.match(await assistant.innerText(),/does not.*mean there are zero corporate actions/s)
    await assistant.getByRole('button',{name:'Retry source check'}).click()
    await assistant.getByText('Informational NSE response received').waitFor()
    assert.equal(providerRequests,2)
    const upload=assistant.getByLabel('Select NSE source files')
    await upload.setInputFiles({name:'test_weights.csv',mimeType:'text/csv',
      buffer:Buffer.from('Symbol,Weightage (%)\nA,50\nB,50\n')})
    await assistant.getByRole('button',{name:'Prepare 1 source file'}).click()
    await assistant.getByText('Original files safely prepared').waitFor({timeout:25000})
    assert.match(await assistant.innerText(),/TRI is preserved/)
    await page.unroute('**/api/workspace/nse-sources/query')
    const capability=await apiJson('/api/workspace/nse-sources/capabilities')
    assert.equal(capability.research_data_write_allowed,false)
    assert.equal(gapAudit.summary.independent_original_source_certified,false)
    assert.equal(gapAudit.summary.publication_certified,false)
    await screenshot('02-historical-source-readiness')
  })
  await step('Unified Market Data wizard: source planning, approval and no broker side-effects',async()=>{
    await nav('Data Library').click()
    await page.locator('.ws-context-tabs').getByRole('button',{name:'Download market data'}).click()
    const workspace=page.locator('.mdw-root')
    await workspace.getByRole('heading',{
      name:'Get the data. QuantLab handles the preparation.'}).waitFor()
    for(const tab of ['Get Data','My Datasets','Downloads & Jobs'])
      await workspace.getByRole('tab',{name:tab}).waitFor()
    await workspace.getByRole('heading',{name:'Choose your research data'}).waitFor()
    assert.equal(await workspace.getByRole('heading',{name:'What history do you need?'}).count(),0,
      'Only the current setup stage should be displayed')
    const nifty=workspace.getByRole('button',{name:/NIFTY 50.*Historical constituents/})
    assert.equal(await nifty.getAttribute('aria-pressed'),'true')
    await workspace.getByRole('button',{name:/Continue to history & source checks/}).click()
    await workspace.getByRole('heading',{name:'What history do you need?'}).waitFor()
    assert.equal(await workspace.getByRole('heading',{name:'Choose your research data'}).count(),0)
    assert.equal(await workspace.getByRole('combobox',{name:'Candle frequency'}).inputValue(),'daily')
    await workspace.getByText(/Connect Dhan historical Data API/).first().waitFor()
    await page.route('**/api/market-data/sources/prepare',route=>route.fulfill({
      status:200,contentType:'application/json',
      body:JSON.stringify({job_id:'ci_source_setup',status:'queued'})
    }))
    await page.route('**/api/jobs/ci_source_setup',route=>route.fulfill({
      status:200,contentType:'application/json',
      body:JSON.stringify({id:'ci_source_setup',status:'complete',
        percent:100,stage:'Source files inspected'})
    }))
    await workspace.getByRole('button',{name:/Prepare missing sources/}).click()
    await workspace.getByText('Source setup completed. Rechecking the requested period.').waitFor()
    await page.unroute('**/api/market-data/sources/prepare')
    await page.unroute('**/api/jobs/ci_source_setup')
    await workspace.getByRole('combobox',{name:'Optional research model'}).selectOption('garch')
    await workspace.getByText('72 returns').waitFor()
    await workspace.getByRole('button',{name:/Continue to provider & download/}).click()
    await workspace.getByRole('heading',{name:'Get data and prepare automatically'}).waitFor()
    assert.equal(await workspace.getByRole('heading',{name:'What history do you need?'}).count(),0)
    await workspace.getByRole('button',{name:'Connect Dhan',exact:true}).click()
    await workspace.getByLabel('Dhan access token').waitFor()
    assert.equal(await workspace.getByRole('button',{name:'Verify & save locally'}).isDisabled(),true,
      'A connection must not save a token without user consent')
    await workspace.getByRole('button',{name:'Connect Dhan',exact:true}).click()
    assert.equal(await workspace.getByRole('button',{name:/Get & prepare data/}).isDisabled(),true,
      'No unapproved broker requests with missing token and index coverage')
    await workspace.getByRole('button',{name:/Back to history & source plan/}).click()
    await workspace.getByLabel('Through date').fill('2026-10-15')
    await workspace.getByRole('button',{name:/Back to data selection/}).click()
    await workspace.getByRole('button',{name:/BANK NIFTY/}).click()
    assert.equal(await workspace.getByRole('button',{name:/BANK NIFTY/})
      .getAttribute('aria-pressed'),'true')
    await workspace.getByRole('button',{name:/My stocks/}).click()
    await workspace.getByLabel('Stock ticker list').fill('RELIANCE\nTCS\n')
    await workspace.getByText('2 unique tickers').waitFor()
    await screenshot('02-unified-market-data-source-plan')
    await workspace.getByRole('tab',{name:'My Datasets'}).click()
    await workspace.getByRole('heading',{name:"Everything you've collected"}).waitFor()
    await workspace.getByRole('tab',{name:'Downloads & Jobs'}).click()
    await workspace.getByRole('heading',{name:"See exactly what's happening"}).waitFor()
  })
  await step('Compare Workspace remains navigable after source review',async()=>{
    await nav('Compare & Visualize').click()
    await page.locator('.rw-top h2').waitFor()
  })
  await step('Data Manager model-aware acquisition and protected SQLite browsing',async()=>{
    await nav('Data Library').click()
    await page.locator('.ws-context-tabs').getByRole('button',{name:'Data manager'}).click()
    const manager=page.locator('.qm-root')
    if(!(await manager.isVisible())) {
      await page.getByRole('button',{name:'Database Manager',exact:true}).click()
      await manager.waitFor()
    }
    await manager.getByRole('button',{name:'Get model data'}).click()
    const acquisition=page.getByRole('region',{name:'Automatic model data acquisition'})
    await acquisition.waitFor()
    await acquisition.getByLabel('Data acquisition model').selectOption('min_variance')
    await acquisition.getByLabel('Data acquisition dataset').selectOption('upload_ci_browser_smoke')
    await acquisition.getByText('Preferred +20%').waitFor()
    await acquisition.getByText('SHA-checked local Dhan candle cache').waitFor()
    const dryPlan=await apiJson('/api/data-manager/acquisition-plan?model_id=min_variance')
    assert.equal(dryPlan.phase,'choose_dataset')
    assert.equal(dryPlan.requirements.target_returns,72)
    await manager.getByRole('button',{name:'Database tables'}).click()
    await page.getByRole('region',{name:'Read-only database tables'}).waitFor()
    const catalog=await apiJson('/api/data-manager/database-catalog')
    assert.equal(catalog.databases.some(db=>db.id==='research_library'),true)
    const safety=await page.getByRole('region',{name:'Read-only database tables'}).innerText()
    assert.match(safety,/No arbitrary SQL/)
    await screenshot('02-data-acquisition-and-safe-database-tables')
  })
  await step('source-safe alternate providers and accelerated Parquet controls',async()=>{
    await nav('Data Library').click()
    await page.locator('.ws-context-tabs').getByRole('button',{name:'Data manager'}).click()
    const manager=page.locator('.qm-root')
    if(!(await manager.isVisible())) {
      await page.getByRole('button',{name:'Database Manager',exact:true}).click()
      await manager.waitFor()
    }
    await manager.getByRole('button',{name:'Fast analytics'}).click()
    const columnar=page.getByRole('region',{name:'Columnar analytical cache'})
    await columnar.waitFor()
    await columnar.getByRole('heading',{name:'Fast historical-data analytics'}).waitFor()
    assert.match(await columnar.innerText(),/original SQLite unchanged/i)
    const status=await apiJson('/api/data-manager/columnar/status')
    assert.equal(typeof status.engine_available,'boolean')
    assert.equal(typeof status.ready,'boolean')
    await manager.getByRole('button',{name:'Sources & provenance'}).click()
    const fallback=page.getByRole('region',{name:'Compatible alternate historical source'})
    await fallback.waitFor()
    await fallback.getByLabel('Fallback provider').waitFor()
    await fallback.getByLabel('Canonical identity').waitFor()
    await fallback.getByLabel('Original fallback CSV').waitFor()
    assert.equal(await fallback.getByRole('button',{name:'Validate & append compatible source'}).isDisabled(),true)
    const providers=await apiJson('/api/data-manager/fallback/registry')
    assert.equal(providers.providers.some(p=>p.id==='nse_mcp'&&p.compatible===false),true)
    await screenshot('02c-quantlab-compatible-sources-and-columnar-cache')
  })
  await step('every-model readiness and genuine minute/depth source states',async()=>{
    await nav('Data Library').click()
    await page.locator('.ws-context-tabs').getByRole('button',{name:'Data manager'}).click()
    const manager=page.locator('.qm-root')
    if(!(await manager.isVisible())) {
      await page.getByRole('button',{name:'Database Manager',exact:true}).click()
      await manager.waitFor()
    }
    await manager.getByRole('button',{name:'Research readiness'}).click()
    const center=page.getByRole('region',{name:'Research models readiness'})
    await center.waitFor()
    await center.getByRole('heading',{name:'Research Readiness Center'}).waitFor()
    await center.getByRole('heading',{name:'Market-data evidence gates'}).waitFor()
    await center.getByRole('button',{name:/Run model software checks/}).waitFor()
    const readiness=await apiJson('/api/data-manager/research/overview')
    assert.ok(readiness.total_models>20,'Registered models must have a readiness entry')
    assert.equal(readiness.models.length,readiness.total_models)
    assert.ok(readiness.sources.requirements.every(row=>row.verified_by_exchange===false),
      'Source references alone must not claim NSE certification')
    await manager.getByRole('button',{name:'Minute & order book'}).click()
    const minute=page.getByRole('region',{name:'One-minute Parquet research'})
    await minute.waitFor()
    await minute.getByRole('heading',{name:'Original 1-minute candle analytics'}).waitFor()
    const micro=page.getByRole('region',{name:'Real market depth research'})
    await micro.waitFor()
    await micro.getByRole('heading',{name:'Historical order-book laboratory'}).waitFor()
    await micro.getByRole('button',{name:'Start genuine live depth recording'}).waitFor()
    assert.equal(await micro.getByRole('button',{name:'Start genuine live depth recording'}).isDisabled(),true,
      'Dhan live capture must require a configured original feed and explicit consent')
    const depth=await apiJson('/api/data-manager/depth/catalog')
    assert.equal(depth.historical_depth_download_supported,false)
    const minuteInventory=await apiJson('/api/data-manager/intraday/catalog')
    assert.equal(minuteInventory.interval_minutes,1)
    await screenshot('02d-research-readiness-and-original-orderbook')
  })
  await step('Zerodha second provider and original-market acceptance',async()=>{
    await nav('Data Library').click()
    await page.locator('.ws-context-tabs').getByRole('button',{name:'Data manager'}).click()
    const manager=page.locator('.qm-root')
    if(!(await manager.isVisible())) {
      await page.getByRole('button',{name:'Database Manager',exact:true}).click()
      await manager.waitFor()
    }
    await manager.getByRole('button',{name:'Sources & provenance'}).click()
    const kite=page.getByRole('region',{name:'Zerodha second market data provider'})
    await kite.waitFor()
    await kite.getByRole('heading',{name:/Zerodha.*second historical provider/}).waitFor()
    await kite.getByRole('button',{name:'Sign in with Zerodha'}).waitFor()
    await kite.getByLabel('Kite app API key').waitFor()
    await kite.getByLabel('Kite app API secret').waitFor()
    assert.equal(await kite.getByRole('button',{name:'Save private local Kite app settings'}).isDisabled(),true,
      'Do not save incomplete Kite app credentials')
    const status=await apiJson('/api/data-manager/zerodha/status')
    assert.equal(status.provider,'zerodha_kite')
    assert.equal(typeof status.token_present,'boolean')
    assert.equal(typeof status.master_current,'boolean')
    assert.ok(!JSON.stringify(status).includes('access_token'))
    const registry=await apiJson('/api/data-manager/fallback/registry')
    assert.ok(registry.providers.some(p=>p.id==='zerodha_kite'&&p.compatible===true))
    assert.equal(registry.providers.some(p=>p.id==='upstox_v3'),false,
      'Only Zerodha is offered as the automated second provider')
    await manager.getByRole('button',{name:'Research readiness'}).click()
    const readiness=page.getByRole('region',{name:'Research models readiness'})
    await readiness.getByRole('heading',{name:'End-to-end real-data acceptance'}).waitFor()
    await readiness.getByLabel('Acceptance validation start').waitFor()
    await readiness.getByLabel('Acceptance final test start').waitFor()
    assert.equal(await readiness.getByRole('button',{name:'Run complete original-data acceptance'}).isDisabled(),true,
      'Do not run a real-data acceptance without a selected dataset and explicit dates')
    const reports=await apiJson('/api/data-manager/research/acceptance/reports')
    assert.ok(Array.isArray(reports.reports))
    await screenshot('02e-zerodha-second-provider-and-original-data-acceptance')
  })
  await step('whole-workstation health and research source reliability',async()=>{
    await nav('Data Library').click()
    await page.locator('.ws-context-tabs').getByRole('button',{name:'Data manager'}).click()
    const manager=page.locator('.qm-root')
    if(!(await manager.isVisible())) {
      await page.getByRole('button',{name:'Database Manager',exact:true}).click()
      await manager.waitFor()
    }
    await manager.getByRole('button',{name:'Activity & recovery'}).click()
    await manager.getByRole('heading',{name:'Whole-workstation health'}).waitFor()
    await manager.getByRole('button',{name:'Run integrity checks'}).waitFor()
    const health=await apiJson('/api/data-manager/system-health')
    assert.equal(health.read_only,true)
    assert.equal(health.market_data_certified,false)
    assert.ok(['operational','needs_attention','needs_repair'].includes(health.overall_state))
    assert.ok(health.databases.every(x=>x.state!=='integrity_error'),
      'Test fixtures must not contain a corrupted operational SQLite database')
    assert.ok(health.storage.total_bytes===null||health.storage.total_bytes>0)
    await manager.getByText('Managed database integrity',{exact:true}).waitFor()
    await manager.getByRole('heading',{name:'Jobs and recovery'}).waitFor()
    await screenshot('02f-operational-source-health')
  })
  await step('Data Manager exposes source completion and recoverable dataset management',async()=>{
    await nav('Data Library').click()
    await page.locator('.ws-context-tabs').getByRole('button',{name:'Data manager'}).click()
    await page.getByRole('heading',{name:"Everything you've collected"}).waitFor()
    const sourceSnapshots=page.locator('.mdw-root details.mdw-options')
      .filter({hasText:'Advanced: original source snapshots'}).first()
    await sourceSnapshots.locator('summary').first().click()
    await sourceSnapshots.locator('.mdw-dataset').first().waitFor()
    const imported=page.locator('.mdw-dataset').getByRole('button',{name:'Delete',exact:true})
    assert.ok(await imported.count()>0,'User-owned datasets need a visible delete action')
    await imported.first().click()
    const deletion=page.getByRole('dialog',{name:/Delete dataset/})
    await deletion.waitFor()
    assert.match(await deletion.innerText(),/linked saved/)
    await deletion.getByRole('button',{name:/Yes, delete dataset/}).waitFor()
    await deletion.getByRole('button',{name:'No, keep everything'}).waitFor()
    await deletion.getByRole('button',{name:'Archive instead'}).waitFor()
    await screenshot('02-dataset-dependencies-preview')
    await deletion.getByRole('button',{name:'No, keep everything'}).click()
    assert.equal(await deletion.count(),0,'Preview must not delete any data when cancelled')
    await page.locator('.mdw-dataset').first().getByRole('button',{
      name:'Extend / complete'
    }).click()
    await page.getByRole('heading',{name:'Complete your existing model dataset'}).waitFor()
    await page.getByRole('region',{name:'Automatic model data acquisition'}).waitFor()
    assert.equal(await page.getByRole('button',{name:/Get & prepare data/}).count(),0,
      'Existing dataset extension must not show an unrelated general-universe batch CTA')
    await page.locator('.mdw-root').getByRole('tab',{name:'My Datasets'}).click()
    await page.locator('details.ws-tri-advanced.ws-data-advanced').first().locator('summary').first().click()
    await page.locator('.ws-dataset-advanced summary').waitFor()
    assert.equal(await page.locator('.ws-dataset-advanced').first().evaluate(el=>el.open),false,
      'Raw metadata must remain behind a disclosure')
    await page.locator('.ws-dataset-archive summary').waitFor()
    assert.match(await page.locator('.ws-dataset-archive summary').innerText(),/Archived datasets/)
    await page.locator('.ws-dataset-trash summary').waitFor()
    await page.locator('.ws-dataset-trash summary').click()
    await page.locator('.ws-dataset-trash').evaluate(el=>el.open===true)
    await nav('Model Laboratory').click()
    // <details> is a semantic group in Chromium; use the stable class when
    // accessible role differs among browser versions.
    const overview=page.locator('.ql-model-matrix')
    await overview.locator('summary').click()
    await overview.getByRole('heading',{name:'What can run with the selected data?'}).waitFor()
    await overview.getByText(/Theoretical \/ simulation inputs ready/).waitFor()
    await overview.locator('summary').click()
    await page.locator('.ql-family-tabs').getByRole('button',{name:/Stochastic Processes/}).click()
    await page.getByText('WORKING SEEDED SIMULATION — NOT OBSERVED MARKET DATA').waitFor()
    const setup=page.getByRole('region',{name:'How to run this model'})
    await setup.waitFor()
    await setup.getByRole('heading',{name:'How to run this model'}).waitFor()
    await setup.getByText('Python solver implemented and covered by software tests.').waitFor()
    await page.locator('.ql-selected-header .ql-impl-badge').getByText('Implemented').waitFor()
    assert.equal(await page.getByText('SEEDED SIMULATION · DEMO',{exact:true}).count(),0,
      'Working simulations must not be mislabeled as unimplemented demos')
    await page.getByRole('button',{name:/Use observed market data/}).waitFor()
    await page.getByRole('button',{name:'Fit to historical data (train / test)'}).click()
    await page.getByRole('heading',{name:'GBM · Fit to Historical Data'}).waitFor()
    await page.getByText(/first 80% calibrates the parameters/).waitFor()
    await page.getByRole('region',{name:'Eligible historical stock inputs'}).waitFor()
    await page.getByRole('heading',{name:'2 · Choose an actual series'}).waitFor()
    await page.getByRole('button',{name:'Explore mathematics (assumed parameters)'}).click()
    await page.getByText('WORKING SEEDED SIMULATION — NOT OBSERVED MARKET DATA').waitFor()
    await page.getByRole('region',{name:'Research workflow'}).getByText(/Run selected model/).waitFor()
    const modelFilters=page.getByRole('group',{name:'Show model types'})
    await modelFilters.getByRole('button',{name:'Math & simulation'}).click()
    assert.equal(await modelFilters.getByRole('button',{name:'Math & simulation'}).getAttribute('aria-pressed'),'true')
    await modelFilters.getByRole('button',{name:'All'}).click()
    await page.getByRole('button',{name:'Run selected model'}).click()
    await page.getByRole('region',{name:'Research interpretation'}).waitFor({timeout:20000})
    await page.getByText('What does this result establish?').waitFor()
    await page.getByText(/synthetic fixture|reproducible|artificial/i).first().waitFor()
    const chart=page.locator('.ql-chart-card').first()
    await chart.getByRole('button',{name:/Export SVG of/}).waitFor()
    const svgFile=page.waitForEvent('download')
    await chart.getByRole('button',{name:/Export SVG of/}).click()
    const svg=await svgFile
    assert.match(svg.suggestedFilename(),/\.svg$/)
    const csvFile=page.waitForEvent('download')
    await chart.getByRole('button',{name:/Export CSV of/}).click()
    const csv=await csvFile
    assert.match(csv.suggestedFilename(),/\.csv$/)
    await chart.locator('.ql-chart-data summary').click()
    assert.ok(await chart.locator('.ql-chart-data tbody tr').count()>0)
    await screenshot('02-model-interpretation-chart-data-and-exports')
    await page.locator('.ql-model-list').getByRole('button',{name:/Ornstein–Uhlenbeck Process/}).click()
    await page.getByRole('button',{name:'Fit from historical daily volatility'}).click()
    await page.getByRole('heading',{name:'OU · Historical Volatility Fit'}).waitFor()
    const ouGate=page.locator('.ql-coverage-panel')
    await ouGate.getByText(/No stock is selected yet|Choose a stock|needs daily stock closes|no prepared stock prices|Choose a saved observed-data source/i).first().waitFor()
    const remediation=ouGate.getByRole('region',{name:'Recommended next action'})
    await remediation.waitFor({timeout:20000})
    assert.ok((await remediation.innerText()).includes('Next action:'),
      'Blocked historical models should provide a source-specific actionable recovery path')
    await page.locator('.ql-family-tabs').getByRole('button',{name:/Derivatives & Options/}).click()
    await page.locator('.ql-model-list').getByRole('button',{name:/Black–Scholes–Merton & Greeks/}).click()
    await page.getByRole('button',{name:'Use observed option bid/ask'}).click()
    await page.getByRole('heading',{name:'Black–Scholes · Observed Market Quote'}).waitFor()
    await page.getByRole('region',{name:'Import original provider option quotes'}).waitFor()
    await page.getByText(/never fabricates a market premium/).waitFor()
    const manual=page.locator('.ql-advanced-import')
    assert.equal(await manual.evaluate(el=>el.open),false)
    await manual.locator('summary').click()
    await manual.getByRole('button',{name:'Download blank CSV template'}).waitFor()
    await manual.locator('summary').click()
    await page.getByRole('button',{name:/Fetch current Dhan quotes \(read-only\)/}).waitFor()
    await page.getByRole('region',{name:'Import original provider option quotes'})
      .getByText(/data plan|data entitlement|entitlements|subscription/i).first().waitFor()
    assert.equal(await page.getByRole('button',{name:'Run selected model'}).isDisabled(),true,
      'A market option cannot be valued without an actual quote')
    await screenshot('02-quote-anchored-option-model-gated')
    await nav('Compare & Visualize').click()
    await page.locator('.rw-top h2').waitFor()
  })
  await step('Download failures show actionable recovery with optional source diagnostics',async()=>{
    const fakeId='batch_baaaaaaaaaaaaaaa'
    const summary={
      id:fakeId,status:'paused',selection:'banknifty_pit',interval:1,
      created_utc:'2026-11-13T00:00:00Z',from_date:'2025-11-13',to_date:'2026-10-12',
      total:14,processed:1,current_symbol:'AUBANK',errors:1,warning:'',
      counts:{pending:13,downloading:0,complete:0,cached:0,no_data:0,failed:1},
      failure_examples:[{
        symbol:'AUBANK',code:'HTTP 401',
        diagnostic:'Dhan HTTP 401 (vendor response body hidden)',
        explanation:'Dhan rejected this historical request. Check authentication and subscription.',
      }],
    }
    const batchRoutes=/\/api\/dhan\/batches(?:\/[^?]*)?(?:\?.*)?$/
    await page.route(batchRoutes,route=>{
      if(route.request().method()!=='GET')return route.continue()
      const url=new URL(route.request().url())
      const body=url.pathname.endsWith('/batches')?{batches:[summary]}:
        url.pathname.endsWith('/'+fakeId)?
          {...summary,items:[],page:1,per_page:40,filtered_total:0}:null
      return body?route.fulfill({status:200,contentType:'application/json',
        body:JSON.stringify(body)}):route.continue()
    })
    await nav('Data Library').click()
    await page.locator('.ws-context-tabs').getByRole('button',{
      name:'Download market data'
    }).click()
    const workspace=page.locator('.mdw-root')
    await workspace.getByRole('tab',{name:'Downloads & Jobs'}).click()
    const detail=workspace.locator('.mdw-batch-detail')
    await detail.getByText('Dhan access needs attention').waitFor()
    await detail.getByText('Last attempted AUBANK').waitFor()
    assert.equal(await detail.locator('.mdw-inline-status .mdw-spin').count(),0,
      'Paused jobs must not display an active-working spinner')
    await detail.getByText(/Verify your token and historical Data API entitlement/).waitFor()
    await detail.getByRole('button',{name:/View technical details/}).click()
    const originalFailure=detail.locator('.mdw-diagnostics')
    await originalFailure.getByText('AUBANK · HTTP 401',{exact:true}).waitFor()
    await originalFailure.getByText(/Dhan HTTP 401/).waitFor()
    assert.ok(!(await detail.innerText()).includes('SECRET_API_TOKEN'))
    assert.equal(await detail.getByRole('button',{name:/Resume/}).isDisabled(),false)
    await screenshot('02b-actionable-market-source-error')
    await page.unroute(batchRoutes)
    await nav('Compare & Visualize').click()
    await page.locator('.rw-top h2').waitFor()
  })
  await step('observed-column plot builder: browser to API to mathematical chart',async()=>{
    await researchTab('Plot Builder').click()
    await page.getByLabel('Observed market dataset').selectOption('upload_ci_browser_smoke')
    await page.getByLabel('Graph type').selectOption('scatter')
    await page.getByRole('button',{name:'Plot selected observations'}).click()
    await page.locator('.ra-result svg').first().waitFor()
    assert.match(await page.locator('.ra-result').innerText(),/SHA-256/i)
    const graph=page.locator('.ra-result .ql-svg-chart').first()
    await graph.hover({position:{x:320,y:140}})
    await page.locator('.ra-result .ql-active-observation').first().waitFor()
    assert.ok((await page.locator('.ra-result .ql-active-observation').textContent()).length>3,
      'Hover must expose actual data values, not a non-interactive line')
    await screenshot('02-plot-scatter')
    const figure=await apiJson('/api/workspace/plot-builder/columns/upload_ci_browser_smoke')
    assert.equal(figure.total_columns,4)
    assert.ok(figure.total_dates>400,'Fixture must expose real aligned rows to the API')
    await page.getByLabel('Price currency (user declared)').selectOption('INR')
    await page.getByLabel('Transformation').selectOption('price')
    await page.getByLabel('Graph type').selectOption('line')
    await page.getByRole('button',{name:'Plot selected observations'}).click()
    await page.locator('.ra-result svg').first().waitFor()
    assert.match(await page.locator('.ra-result').innerText(),/INR/i)
    assert.match(await page.locator('.ra-result').innerText(),/user declared/i)
    const syncedZoom=page.locator('.ra-result').getByLabel('Link zoom/pan on exact dates')
    assert.equal(await syncedZoom.count(),1,'Date-labeled plots must expose exact-date zoom sync')
    await page.locator('.ra-result').getByRole('button',{name:/Zoom in/}).click()
    assert.match(await page.locator('.ra-result').innerText(),/of 460 observations visible/i)
    await page.locator('.ra-result').getByRole('button',{name:/Reset zoom/}).click()
    await screenshot('02-plot-date-sync-and-user-currency')
  })
  await step('chart save, report attachment and standalone HTML export',async()=>{
    await page.getByRole('button',{name:'Save chart',exact:true}).click()
    await page.getByLabel('Add saved chart to report notebook').selectOption({label:'CI smoke notebook'})
    await page.getByRole('button',{name:'Add to report',exact:true}).click()
    await page.getByText('Saved graph added directly to your report notebook.').waitFor()
    const downloadPromise=page.waitForEvent('download')
    await page.getByRole('button',{name:/Interactive HTML/}).click()
    const download=await downloadPromise
    const filename=path.join(artifactDir,'03-exported-plot.html')
    await download.saveAs(filename)
    const html=await fs.readFile(filename,'utf8')
    assert.ok(html.includes('<svg')&&html.includes('pointerdown'),
      '2D exported HTML must contain graph and interactive pan handler')
    await page.getByLabel('Graph type').selectOption('correlation')
    await page.getByRole('button',{name:'Plot selected observations'}).click()
    await page.locator('.ra-result svg').first().waitFor()
    assert.match(await page.locator('.ra-result').innerText(),/source/i)
    await screenshot('04-heatmap')
  })
  await step('statistical tests on backend numeric return observations',async()=>{
    await page.getByRole('button',{name:/Statistics & Diagnostics/}).click()
    await page.getByRole('button',{name:'Calculate actual statistical evidence'}).click()
    await page.getByRole('heading',{name:/Observed diagnostics/}).waitFor()
    assert.ok((await page.locator('.rw-stats').first().innerText()).includes('jarque'))
    await screenshot('05-statistical-diagnostics')
  })
  await step('evidence gate remains unverified and trained ML completes its real holdout',async()=>{
    await researchTab('Evidence & ML').click()
    await page.getByRole('heading',{name:'Research-data evidence register'}).waitFor()
    await page.getByText('Historical investability certified',{exact:true}).waitFor()
    const evidence=await apiJson('/api/workspace/integrity/upload_ci_browser_smoke')
    assert.equal(evidence.historical_investability_certified,false)
    assert.equal(evidence.prospective_trading_certified,false)
    await page.getByRole('button',{name:'Live Dhan Check'}).click()
    await page.getByText(/Choose a prepared DAILY Dhan dataset/).waitFor()
    // No real credential, no vendor API calls, and no data mutation.
    await page.getByRole('button',{name:'ML / RL Holdout'}).click()
    await page.getByText('Preferred (+20%)').waitFor()
    await page.getByText('Minimum training+holdout requirement satisfied').waitFor()
    page.once('dialog',dialog=>dialog.accept())
    const pendingResponse=page.waitForResponse(r=>
      new URL(r.url()).pathname==='/api/workspace/learning/run'&&
      r.request().method()==='POST')
    await page.getByRole('button',{name:/Confirm & run chronological research/}).click()
    const started=await pendingResponse
    assert.equal(started.status(),200,await started.text())
    const submitted=await started.json()
    assert.ok(submitted.job_id)
    const finished=await waitJobComplete(submitted.job_id)
    assert.equal(finished.result.method,'ridge')
    assert.ok(finished.result.last_training_label_date <
      finished.result.first_test_decision_date,'No test future labels in training')
    const csv=await page.request.get(base+'/api/workspace/studies/'+finished.result.study_id+
      '/returns.csv')
    assert.equal(csv.status(),200,'Full chronological holdout CSV downloaded')
    assert.ok((await csv.text()).split('\n').length>40)
    await screenshot('06-learning-evidence')
  })
  await step('researcher index studio passports, data-safe preflight and model explanations',async()=>{
    await researchTab('Index Research Studio').click()
    await page.getByRole('heading',{name:'Research source — one canonical dataset'}).waitFor()
    await page.getByRole('button',{name:'Data Passports'}).click()
    await page.getByRole('heading',{name:/Research Data Passport/}).waitFor()
    const passport=await apiJson('/api/workspace/passports/upload_ci_browser_smoke')
    assert.equal(passport.investability_certified,false)
    assert.ok(passport.available_files.some(x=>x.name==='prices.csv'))
    await screenshot('11-source-data-passport')
    await page.getByRole('button',{name:'Inspect actual missing observations'}).click()
    await page.getByRole('heading',{name:/Observed coverage audit/}).waitFor()
    const sourceGaps=await apiJson('/api/workspace/source-coverage/upload_ci_browser_smoke')
    assert.equal(sourceGaps.historical_investability_certified,false)
    assert.ok(sourceGaps.price_observations>=2)
    assert.ok(Array.isArray(sourceGaps.warnings))
    await screenshot('11b-historical-coverage-gaps')
    await page.getByRole('button',{name:'Index Studio',exact:true}).click()
    await page.getByRole('button',{name:'Check assumptions & data'}).click()
    await page.getByText(/Infeasible observed universe/).waitFor()
    assert.equal(await page.getByRole('button',{name:'Confirm & run methodology'}).isDisabled(),true)
    await page.getByRole('button',{name:'Why This Result?'}).click()
    const saved=await apiJson('/api/lab/runs?limit=30')
    assert.ok(saved.runs.length>=2)
    await page.getByLabel('Saved calculation').selectOption(saved.runs[0].id)
    await page.getByRole('button',{name:'Understand this calculated result'}).click()
    await page.locator('.rs-explanation').waitFor()
    assert.match(await page.locator('.rs-explanation').innerText(),/Mathematical relation/)
    await screenshot('12-archived-research-explainer')
  })
  await step('research hypothesis registration is pinned and inspectable',async()=>{
    await page.getByRole('button',{name:'Publication & Protocol'}).click()
    await page.getByLabel('Research question').fill(
      'Can this preregistered multi-factor experiment beat its earlier-defined benchmark?')
    await page.getByLabel('Rationale').fill(
      'A factor combination may be more diversified than either univariate score.')
    await page.getByLabel('Frozen data, split, methodology and limitations').fill(
      'Use 70/15/15 chronological splits, fixed objective parameters and a wholly untouched final test.')
    await page.getByRole('button',{name:'Register frozen hypothesis'}).click()
    await page.getByText(/Hypothesis recorded with an append-only checksum/).waitFor()
    const h=await apiJson('/api/workspace/hypotheses')
    assert.equal(h.hypotheses[0].content_unchanged,true)
    assert.equal(h.hypotheses[0].dataset_id,'upload_ci_browser_smoke')
    await screenshot('13-registered-research-protocol')
  })
  await step('guided research and two-parameter grid preflight',async()=>{
    await researchTab('Guided & Grids').click()
    await page.getByRole('heading',{name:/Guided Research/}).waitFor()
    await page.getByRole('button',{name:/Multi-parameter grids/}).click()
    await page.getByRole('button',{name:/Validate complete experiment grid/}).click()
    await page.getByText(/3 model executions/).waitFor()
    await screenshot('06-parameter-grid')
  })
  await step('research notebook generates actual PDF HTML and Markdown files',async()=>{
    await researchTab('Projects & Notes').click()
    await page.getByRole('button',{name:/CI smoke notebook/}).first().click()
    const generate=page.getByRole('button',{name:/Generate PDF, HTML & Markdown report/})
    await generate.waitFor()
    assert.equal(await generate.isDisabled(),false,'Clean seeded notebook should allow report')
    const responsePromise=page.waitForResponse(r=>r.url().includes('/api/workspace/reports')&&r.request().method()==='POST')
    await generate.click()
    const response=await responsePromise
    assert.equal(response.status(),200,'Actual report generation must queue successfully')
    const queued=await response.json()
    assert.ok(queued.job_id,'Report must be associated with a real job ID')
    await waitJobComplete(queued.job_id)
    const records=await apiJson('/api/workspace/records?kind=report')
    assert.ok(records.records.length>0,'Report metadata must persist')
    const report=records.records[0]
    for(const [kind,expected] of [['html','<html'],['markdown','#'],['pdf','%PDF']]) {
      const file=await page.request.get(base+'/api/workspace/reports/'+report.id+'/'+kind)
      assert.equal(file.status(),200,'Report export '+kind)
      const raw=await file.body()
      assert.ok(raw.length>100,'Report '+kind+' must contain actual output')
      assert.ok(raw.toString('utf8',0,Math.min(raw.length,1000)).toLowerCase()
        .includes(expected.toLowerCase()),'Invalid '+kind+' report content')
    }
    await screenshot('07-notebook-report')
  })
  await step('model comparison and library resource listings render',async()=>{
    await researchTab('Compare & Graph').click()
    assert.ok(await page.locator('.rw-run-list label').count() >= 2,
      'Two seeded model runs must be visible')
    const toggles=page.locator('.rw-run-list input[type=checkbox]')
    await toggles.nth(0).check()
    await toggles.nth(1).check()
    await screenshot('08-saved-model-comparison')
    await researchTab('Library').click()
    await page.getByText('Datasets & results').first().waitFor()
  })
  await step('global command palette and formula reference',async()=>{
    await page.keyboard.press('Control+k')
    const dialog=page.getByRole('dialog',{name:'Search QuantLab research library'})
    await dialog.waitFor()
    await dialog.getByPlaceholder(/Find datasets/).fill('Heston')
    await dialog.getByText('Heston').first().waitFor()
    await page.keyboard.press('Escape')
    await nav('Help & Settings').click()
    await page.getByRole('button',{name:'Expected Shortfall (ES / CVaR)'}).waitFor()
    await page.getByRole('button',{name:'Value at Risk (VaR)'}).click()
    assert.match(await page.locator('.qg-metric-detail').innerText(),/quantile_alpha/)
    await screenshot('09-metric-reference')
  })
  await step('mobile viewport and navigation remain usable',async()=>{
    await page.setViewportSize({width:390,height:844})
    await page.getByRole('button',{name:'Open navigation'}).click()
    await nav('Compare & Visualize').click()
    await page.locator('.rw-top h2').waitFor()
    await screenshot('10-mobile-workspace')
  })
  await step('no unhandled browser exceptions or HTTP 5xx',async()=>{
    assert.deepEqual(errors,[],'Browser page errors')
    assert.deepEqual(api500,[],'Backend 5xx responses')
  })
} catch(e) {
  console.error('[browser-smoke] FAIL:',e)
  process.exitCode=1
} finally {
  await fs.writeFile(path.join(artifactDir,'summary.json'),JSON.stringify({
    success:process.exitCode!==1,
    steps,jsErrors:errors,api5xx:api500,scope:'isolated synthetic CI fixture; no broker credentials/orders',
  },null,2)+'\n')
  if(browser)await browser.close()
}
