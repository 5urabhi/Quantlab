import test from 'node:test'
import assert from 'node:assert/strict'
import {mkdtempSync, mkdirSync, symlinkSync, writeFileSync, readFileSync, rmSync} from 'node:fs'
import {tmpdir} from 'node:os'
import {join, resolve} from 'node:path'
import {spawnSync} from 'node:child_process'
import {compatibleRuntime} from '../scripts/node_runtime_compat.mjs'

const root=resolve(import.meta.dirname,'..')

test('npm 12.2 rejects Node 22.22.1, accepts a sufficiently patched Node',()=>{
  assert.equal(compatibleRuntime('v22.22.1','12.2.0'),false)
  assert.equal(compatibleRuntime('v22.22.2','12.2.0'),true)
  assert.equal(compatibleRuntime('v22.23.5','12.2.0'),true)
  assert.equal(compatibleRuntime('v24.14.9','12.2.0'),false)
  assert.equal(compatibleRuntime('v24.15.0','12.2.0'),true)
  assert.equal(compatibleRuntime('v26.0.0','12.2.0'),true)
  assert.equal(compatibleRuntime('v20.19.0','12.2.0'),false)
})

test('bundled npm 10 and current supported Node 22 releases work',()=>{
  assert.equal(compatibleRuntime('v22.23.5','10.9.9'),true)
  assert.equal(compatibleRuntime('v22.16.0','10.9.2'),true)
  assert.equal(compatibleRuntime('v22.12.0','11.3.0'),true)
  assert.equal(compatibleRuntime('v24.22.3','11.5.0'),true)
  assert.equal(compatibleRuntime('v22.23.5','13.0.0'),false)
  assert.equal(compatibleRuntime('broken','10.9.9'),false)
  assert.equal(compatibleRuntime('v22.22.1','broken'),false)
})

test('npm 12 only grants esbuild installation script, not every dependency',()=>{
  const pkg=JSON.parse(readFileSync(join(root,'package.json'),'utf8'))
  assert.deepEqual(pkg.allowScripts,{esbuild:true})
  assert.ok(!pkg.scripts.build.includes('dangerously'))
})

test('setup and launcher both source the shared selector (child PATH cannot propagate)',()=>{
  const setup=readFileSync(join(root,'scripts/start.sh'),'utf8')
  const launcher=readFileSync(join(root,'scripts/run_workstation.sh'),'utf8')
  assert.match(setup,/source "\$ROOT\/scripts\/node_runtime\.sh"/)
  assert.match(setup,/quantlab_activate_node_runtime "\$ROOT"/)
  assert.match(launcher,/quantlab_activate_node_runtime "\$ROOT" offline/)
  assert.match(setup,/\$\(npm --version\)/)
  assert.match(setup,/require\('esbuild'\)/)
})

test('offline launcher selects local Node/npm if global pair is incompatible',()=>{
  const temp=mkdtempSync(join(tmpdir(),'quantlab-node-bootstrap-'))
  try{
    symlinkSync(join(root,'scripts'),join(temp,'scripts'),'dir')
    const globalbin=join(temp,'broken-global-bin')
    const arch=process.arch==='arm64'?'arm64':'x64'
    const portable=join(temp,'.local-tools',`node-v22.23.5-linux-${arch}`,'bin')
    for(const dir of [globalbin,portable])mkdirSync(dir,{recursive:true})
    const fakeNode=(value)=>`#!/usr/bin/env bash
if [ "\${1:-}" = "--version" ]; then echo ${value}; else exec "${process.execPath}" "$@"; fi
`
    const fakeNpm=(value)=>`#!/usr/bin/env bash
if [ "\${1:-}" = "--version" ]; then echo ${value}; else exit 2; fi
`
    writeFileSync(join(globalbin,'node'),fakeNode('v22.22.1'),{mode:0o755})
    writeFileSync(join(globalbin,'npm'),fakeNpm('12.2.0'),{mode:0o755})
    writeFileSync(join(portable,'node'),fakeNode('v22.23.5'),{mode:0o755})
    writeFileSync(join(portable,'npm'),fakeNpm('10.9.9'),{mode:0o755})
    const command='source "$1/scripts/node_runtime.sh"; quantlab_activate_node_runtime "$1" offline || exit 7; printf "%s|%s|%s\\n" "$QUANTLAB_NODE_RUNTIME_CHOICE" "$(node --version)" "$(npm --version)"'
    const result=spawnSync('bash',['-c',command,'bash',temp],{
      encoding:'utf8',env:{...process.env,PATH:globalbin+':'+process.env.PATH}
    })
    assert.equal(result.status,0,result.stderr)
    assert.equal(result.stdout.trim(),'portable|v22.23.5|10.9.9')
  }finally{rmSync(temp,{recursive:true,force:true})}
})

test('compatible system pair is left unchanged',()=>{
  const temp=mkdtempSync(join(tmpdir(),'quantlab-node-compatible-'))
  try{
    symlinkSync(join(root,'scripts'),join(temp,'scripts'),'dir')
    const bin=join(temp,'bin')
    mkdirSync(bin,{recursive:true})
    writeFileSync(join(bin,'node'),`#!/usr/bin/env bash
if [ "\${1:-}" = "--version" ]; then echo v22.23.5; else exec "${process.execPath}" "$@"; fi
`,{mode:0o755})
    writeFileSync(join(bin,'npm'),'#!/usr/bin/env bash\necho 10.9.9\n',{mode:0o755})
    const cmd='source "$1/scripts/node_runtime.sh"; quantlab_activate_node_runtime "$1" offline || exit 7; printf "%s\\n" "$QUANTLAB_NODE_RUNTIME_CHOICE"'
    const result=spawnSync('bash',['-c',cmd,'bash',temp],{
      encoding:'utf8',env:{...process.env,PATH:bin+':'+process.env.PATH}
    })
    assert.equal(result.status,0,result.stderr)
    assert.equal(result.stdout.trim(),'system')
  }finally{rmSync(temp,{recursive:true,force:true})}
})


test('workstation launcher waits for heavy saved-market FastAPI startup without 10s false failure',()=>{
  const launcher=readFileSync(join(root,'scripts/run_workstation.sh'),'utf8')
  const syntax=spawnSync('bash',['-n',join(root,'scripts/run_workstation.sh')],{encoding:'utf8'})
  assert.equal(syntax.status,0,syntax.stderr)
  assert.match(launcher,/QUANTLAB_API_READY_TIMEOUT_SECONDS:-120/)
  assert.match(launcher,/API_READY_DEADLINE/)
  assert.match(launcher,/while :; do/)
  assert.match(launcher,/curl --fail --silent --max-time 3/)
  assert.match(launcher,/kill -0 "\$API_PID"/)
  assert.doesNotMatch(launcher,/seq 1 40/)
  assert.match(launcher,/Python API healthy; starting browser UI/)
})


import {alignIndicator} from '../src/indicatorAlignment.mjs'
test('live indicators require exact source, timestamps, values, expiry and latest receipt',()=>{
  const rows=[['a',10],['b',20],['c',30]]
  const item={id:'i',name:'Example',revision:2,last_utc:'c',alignment:{source:'chain_spot_receipts',expiry:'expiry',rows:rows.slice(1)},plot:{x:['b','c'],traces:[{name:'v',y:[1,2]}]}}
  assert.deepEqual(alignIndicator(item,'chain_spot_receipts','expiry',rows,['a','b','c']),[{name:'Example v2 · v',y:[null,1,2]}])
  assert.equal(alignIndicator(item,'chain_spot_receipts','other',rows,['b','c']),null)
  assert.equal(alignIndicator(item,'index_minutes',null,rows,['b','c']),null)
  assert.equal(alignIndicator(item,'chain_spot_receipts','expiry',[['b',21],['c',30]],['b','c']),null)
  assert.equal(alignIndicator(item,'chain_spot_receipts','expiry',[...rows,['d',40]],['b','c','d']),null)
  assert.equal(alignIndicator(item,'chain_spot_receipts','expiry',rows,['unknown']),null)
})
