/**
 * Guard the real Vite output against regressing to one oversized JS bundle.
 *
 * Run after vite build. This checks bytes on disk, not an increased Vite
 * warning threshold. Every lazy route must stay below 500 kB minified.
 * Read-only: it never changes dist, sources, or user data.
 */
import {readdirSync,readFileSync,statSync} from 'node:fs'
import {join} from 'node:path'
import {fileURLToPath} from 'node:url'
import {gzipSync} from 'node:zlib'

const root=fileURLToPath(new URL('../',import.meta.url))
const assets=join(root,'dist','assets')
const files=readdirSync(assets).filter(x=>/\.js$/.test(x)).map(name=>{
  const buffer=readFileSync(join(assets,name))
  return {name,bytes:buffer.length,gzip:gzipSync(buffer).length}
}).sort((a,b)=>b.bytes-a.bytes)
const maxChunk=500_000 // Match Vite's default 500 kB warning threshold.
const oversize=files.filter(x=>x.bytes>maxChunk)
console.log('QuantLab production JS chunks (minified / gzip):')
for(const file of files.slice(0,12)){
  console.log('  '+file.name+': '+(file.bytes/1000).toFixed(1)+' kB / '+
              (file.gzip/1000).toFixed(1)+' kB')
}
const total=files.reduce((acc,x)=>acc+x.bytes,0)
const totalGzip=files.reduce((acc,x)=>acc+x.gzip,0)
console.log('  '+files.length+' lazy/shared JS chunks, '+(total/1000).toFixed(1)+
            ' kB total (across ALL pages), '+(totalGzip/1000).toFixed(1)+' kB gzip.')
const html=readFileSync(join(root,'dist','index.html'),'utf8')
const initial=html.match(/src="\/assets\/(index-[^"]+\.js)"/)
if(!initial){
  console.error('FAIL: Could not identify the Vite entry script.')
  process.exitCode=1
}else{
  const entry=files.find(x=>x.name===initial[1])
  if(!entry){console.error('FAIL: Vite entry script is missing.');process.exitCode=1}
  else console.log('  Entry module: '+(entry.bytes/1000).toFixed(1)+' kB minified.')
}
if(files.length<8){
  console.error('FAIL: QuantLab routes were not split into independent JS chunks.')
  process.exitCode=1
}
if(oversize.length){
  console.error('FAIL: oversized production chunk(s): '+oversize.map(x=>x.name).join(', '))
  process.exitCode=1
}
if(!process.exitCode){
  console.log('PASS: route-level chunks are real and all are below 500 kB.')
}
