/** Independent route screenshot/DOM audit, even when a feature smoke test fails. */
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import {chromium} from 'playwright'

const routes={"overview":"Home","trading":"Live Market","tradingchain":"Option Chain","tradingdepth":"20-Level Order Book","tradingspreads":"Liquidity & Spreads","tradingreplay":"Market Replay","tradingjournal":"Trade Journal","tradingpaper":"Paper Trading","tradinganalytics":"Options Analytics","tradingdirectional":"Directional Trading","tradingpatterns":"Market Intelligence","tradingpositions":"Positions & Risk","strategies":"Strategy Library","strategyema":"EMA Explorer","strategypython":"Python Editor","strategybacktest":"BANKNIFTY Backtests","pythonmonitors":"Running Python","custommodels":"Custom Models","customscanners":"Custom Scanners","pythonenvironment":"Python Environment","mathematics":"Model Catalog","models":"Advanced Research Tools","research":"Index Builder","factors":"Factor Research","construction":"Portfolio Construction","risk":"Risk Attribution","rolling":"Rolling Validation","robustness":"Robustness & Sensitivity","modelgrids":"Guided Model Grids","indexstudio":"Index Research Studio","data":"Market Library","dhan":"Get Market Data","dataexplorer":"Data Explorer","dataquality":"Quality & Coverage","datadownloads":"Downloads","nse":"NSE Source Evidence","evidence":"Evidence & Machine Learning","history":"All Research Results","workspace":"Compare Runs","chartstudio":"Chart Studio","comparisons":"Index Comparison","visual":"Historical Charts","workspacejobs":"Research Job History","projects":"My Projects & Notebooks","notebooks":"Research Notebooks","reports":"Research Reports","resourcebrowser":"Saved Resource Library","connections":"Connections","recordingsettings":"Automatic Recording","storage":"Storage & Data Management","preferences":"Preferences","diagnostics":"System Diagnostics","settings":"Backend & Privacy","guide":"Help & How It Works","journey":"New Guided Study"}
const base=process.env.QUANTLAB_SMOKE_URL||'http://127.0.0.1:5173'
const dir=path.resolve(process.env.QUANTLAB_SMOKE_ARTIFACT_DIR||'artifacts/browser-smoke','route-audit')
await fs.mkdir(dir,{recursive:true})
const browser=await chromium.launch({headless:true,args:['--no-sandbox','--disable-dev-shm-usage']})
const results=[]
try{
  for(const [mode,viewport] of [['desktop',{width:1440,height:900}],['mobile',{width:390,height:844}]]){
    const context=await browser.newContext({viewport,deviceScaleFactor:1,colorScheme:'dark'})
    const page=await context.newPage()
    page.setDefaultTimeout(12000)
    for(const [route,title] of Object.entries(routes)){
      const errors=[],badApi=[]
      const error=e=>errors.push(String(e))
      const response=r=>{if(new URL(r.url()).pathname.startsWith('/api/')&&r.status()>=500)badApi.push(r.status()+' '+new URL(r.url()).pathname)}
      page.on('pageerror',error);page.on('response',response)
      const file=mode+'-'+route+'.png'
      try{
        await page.goto(base+'#/'+route,{waitUntil:'domcontentloaded'})
        await page.getByRole('heading',{level:1,name:title,exact:true}).waitFor()
        await page.getByText('Loading '+title+'…',{exact:true}).waitFor({state:'hidden'})
        await page.evaluate(async()=>{window.scrollTo(0,0);await document.fonts.ready;await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))})
        const metrics=await page.evaluate(()=>{
          const main=document.querySelector('main.ws-content')
          const title=document.querySelector('.ws-titlebar h1')
          const r=main?.getBoundingClientRect(),h=title?.getBoundingClientRect()
          return {viewport:window.innerWidth,documentWidth:document.documentElement.scrollWidth,
            mainWidth:r?.width??0,mainLeft:r?.left??-1,titleWidth:h?.width??0,
            visibleCharts:main?.querySelectorAll('.ql-chart-card').length??0,
            pendingPlaceholders:main?.querySelectorAll('.ws-empty[aria-live]').length??0}
        })
        assert.equal(new URL(page.url()).hash,'#/'+route)
        assert.ok(metrics.mainWidth>100&&metrics.titleWidth>0,'Page content is not visible')
        assert.ok(metrics.documentWidth<=metrics.viewport+2,`Horizontal page overflow: ${metrics.documentWidth}px at ${metrics.viewport}px`)
        await page.screenshot({path:path.join(dir,file),fullPage:false})
        assert.deepEqual(errors,[],'Unhandled page exceptions')
        assert.deepEqual(badApi,[],'Backend 5xx')
        results.push({route,title,mode,status:'PASS',file,metrics})
        console.log('[route-audit] PASS '+mode+' '+route)
      }catch(e){
        results.push({route,title,mode,status:'FAIL',file,error:String(e),errors,badApi})
        try{await page.screenshot({path:path.join(dir,file),fullPage:false})}catch{}
        console.error('[route-audit] FAIL '+mode+' '+route+' '+String(e))
      }finally{page.off('pageerror',error);page.off('response',response)}
    }
    // Populated operational views: safe local reads only, no provider calls.
    await page.goto(base+'#/overview',{waitUntil:'domcontentloaded'})
    const home=page.getByRole('region',{name:'Workstation operations overview'})
    await home.waitFor()
    await home.getByRole('button',{name:'Inspect saved coverage'}).click()
    await home.getByRole('table',{name:'Home stored source coverage'}).waitFor({timeout:30000})
    await page.goto(base+'#/storage',{waitUntil:'domcontentloaded'})
    const storage=page.getByRole('region',{name:'Local storage inventory'})
    await storage.getByRole('button',{name:'Inspect storage health'}).click()
    await storage.getByRole('table',{name:'Managed database integrity'}).waitFor({timeout:30000})
    const backup=page.getByRole('region',{name:'Research metadata backups'})
    await backup.getByRole('button',{name:'Inspect metadata backups'}).click()
    await backup.getByRole('table',{name:'Metadata backup source inventory'}).waitFor()
    assert.equal(await backup.getByRole('button',{name:'Create metadata snapshot'}).isDisabled(),true,'Backup requires explicit consent')
    await page.goto(base+'#/nse',{waitUntil:'domcontentloaded'})
    const receipts=page.getByRole('region',{name:'Saved NSE evidence receipts'})
    await receipts.getByRole('searchbox',{name:'Search NSE receipts'}).waitFor()
    await receipts.getByRole('searchbox',{name:'Search NSE receipts'}).fill('ci-no-such-receipt')
    await receipts.getByText('No matching saved intake receipts.').waitFor()
    await page.goto(base+'#/reports',{waitUntil:'domcontentloaded'})
    const reports=page.getByRole('region',{name:'Research report workspace'})
    await reports.getByRole('searchbox',{name:'Search saved reports'}).waitFor()
    await page.goto(base+'#/settings',{waitUntil:'domcontentloaded'})
    const privacy=page.getByRole('region',{name:'Backend safety checks'})
    await privacy.getByText('Read-only',{exact:true}).waitFor()
    await privacy.getByText('Disabled',{exact:true}).waitFor()
    await page.goto(base+'#/connections',{waitUntil:'domcontentloaded'})
    await page.getByText('Zerodha secondary data connection',{exact:true}).click()
    await page.getByText('Zerodha secondary data connection',{exact:true}).waitFor()
    console.log('[route-audit] PASS '+mode+' operational interaction checks')
    await context.close()
  }
}finally{
  await fs.writeFile(path.join(dir,'route-audit.json'),JSON.stringify({scope:'Synthetic CI fixture; not live Dhan or human visual approval',expectedRoutes:Object.keys(routes).length,results},null,2))
  await browser.close()
}
assert.equal(results.length,Object.keys(routes).length*2)
assert.ok(results.every(r=>r.status==='PASS'),'One or more desktop/mobile routes failed; inspect route-audit.json')
