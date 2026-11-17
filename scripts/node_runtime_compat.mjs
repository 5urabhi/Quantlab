/** Compatibility guard for the locally installed Node/npm PAIR.
 *
 * npm 12 supports Node ^22.22.2 || ^24.15.0 || >=26.0.0; checking
 * Node alone lets npm 12.2 warn on an otherwise valid Node 22.22.1.
 * Retain Node 20.19+/22.12+/24+/26+ with compatible older npm versions.
 *
 * CLI: node scripts/node_runtime_compat.mjs v22.22.1 12.2.0
 * Exit 0 for supported pairs, 1 otherwise. No logging or network calls.
 */
import {fileURLToPath} from 'node:url'

function version(value) {
  const match=/^v?(\d+)\.(\d+)\.(\d+)$/.exec(String(value||'').trim())
  return match ? match.slice(1).map(Number) : null
}
function atLeast(pair,major,minor=0,patch=0) {
  return pair[0]>major || (pair[0]===major &&
    (pair[1]>minor || (pair[1]===minor&&pair[2]>=patch)))
}
export function compatibleRuntime(nodeVersion,npmVersion) {
  const n=version(nodeVersion), p=version(npmVersion)
  if(!n||!p) return false
  // The app runs Vite 6 and targets maintained even-numbered Node releases.
  const supportedNode=(n[0]===20&&atLeast(n,20,19)) ||
    (n[0]===22&&atLeast(n,22,12)) ||
    n[0]===24 || (n[0]>=26&&n[0]%2===0)
  if(!supportedNode)return false
  if(p[0]===12) return (
    (n[0]===22&&atLeast(n,22,22,2))||
    (n[0]===24&&atLeast(n,24,15))||
    n[0]>=26)
  if(p[0]===11) return n[0]!==20||atLeast(n,20,17)
  return p[0]>=9&&p[0]<=10
}
if(process.argv[1]&&fileURLToPath(import.meta.url)===process.argv[1]) {
  process.exit(compatibleRuntime(process.argv[2],process.argv[3])?0:1)
}
