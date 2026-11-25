// Pure alignment contract: never interpolate or project an indicator onto
// a different source, expiry, bar, OHLC value or newer timestamp.
export function alignIndicator(overlay,source,expiry,rows,plotX){
  if(!overlay||overlay.alignment?.source!==source||!rows.length||!plotX.length)return null
  if(source==='chain_spot_receipts'&&overlay.alignment.expiry!==expiry)return null
  const inputs=overlay.alignment.rows, xs=overlay.plot?.x, traces=overlay.plot?.traces
  if(!Array.isArray(inputs)||!inputs.length||!Array.isArray(xs)||xs.length!==inputs.length||!Array.isArray(traces)||!traces.length)return null
  if(inputs.some((r,i)=>!Array.isArray(r)||r[0]!==xs[i]))return null
  // Exact timestamp strings and exact source values are deliberately strict.
  const map=new Map(inputs.map((r,i)=>[r[0],{row:r,i}]))
  if(map.size!==inputs.length||new Set(rows.map(r=>r[0])).size!==rows.length)return null
  if(inputs[inputs.length-1][0]!==rows[rows.length-1][0]||overlay.last_utc!==rows[rows.length-1][0])return null
  let count=0
  for(const r of rows){
    const old=map.get(r[0])
    if(!old)continue
    if(old.row.length!==r.length||r.some((v,j)=>v!==old.row[j]))return null
    count++
  }
  if(!count||plotX.some(x=>!rows.some(r=>r[0]===x)))return null
  if(traces.some(t=>!Array.isArray(t.y)||t.y.length!==inputs.length||t.y.some(v=>v!==null&&(typeof v!=='number'||!Number.isFinite(v)))))return null
  return traces.map(t=>({name:overlay.name+' v'+overlay.revision+' · '+t.name,y:plotX.map(x=>{const v=map.get(x);return v?t.y[v.i]:null})}))
}
