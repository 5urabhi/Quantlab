import {useEffect, useId, useMemo, useRef, useState} from 'react'
import {openSnapshotInPython,PYTHON_APPLY_EVENT,type PythonApplied,type SnapshotCell} from './pythonBridge'
import './research-plots-v3.css'

export type ResearchTrace={name:string;y:(number|null)[];color?:string}
export type ResearchPlotData={
  kind:string;title:string;x?:(string|number)[];y?:number[];
  traces?:ResearchTrace[];x_label?:string;y_label?:string;
  z_label?:string;z?:number[][];band?:{lower:number[];upper:number[]};
  band_label?:string;break_before?:boolean[];
  candles?:({open:number;high:number;low:number;close:number}|null)[];
  labels?:string[];row_labels?:string[];scale?:string;values?:number[][];threshold?:number;
  annotations?:{x:string|number;label:string}[];
  regions?:{start:string|number;end:string|number;label:string}[]
  units?:{numeric?:string;price_currency?:string;price_currency_declared_by_user?:boolean;
    currency_verified_by_source?:boolean;stored_values_unscaled?:boolean}
}
const COLORS=['#f5c542','#78a8ff','#c19dff','#f09366','#f38eac','#d0e0ef','#79d5c2','#e4b06a']
const finite=(n:unknown):n is number=>typeof n==='number'&&Number.isFinite(n)
const fmt=(v:number)=>Math.abs(v)<.001&&v!==0?v.toExponential(1):Math.abs(v)>1000?v.toLocaleString('en-US',{maximumFractionDigits:0}):v.toLocaleString('en-US',{maximumFractionDigits:3})
const clamp=(v:number,l:number,h:number)=>Math.min(h,Math.max(l,v))
const exactDateKey=(value:string|number):string|null=>{
  if(typeof value!=='string')return null
  // Date-only and midnight UTC are the same daily observation, but do NOT
  // infer nearest dates, align intraday times or combine unrelated x units.
  return /^\d{4}-\d{2}-\d{2}(?:T00:00:00(?:\.000)?Z)?$/.test(value)?
    value.slice(0,10):null
}
const GRID_LEFT=70,GRID_RIGHT=830,GRID_TOP=22,GRID_BOTTOM=280
function yBounds(plot:ResearchPlotData){
  const ys=(plot.traces||[]).flatMap(t=>t.y).filter(finite)
  if(plot.kind==='scatter2d'&&plot.y)ys.push(...plot.y.filter(finite))
  if(plot.band){ys.push(...plot.band.lower.filter(finite),...plot.band.upper.filter(finite))}
  if(plot.candles)for(const c of plot.candles){if(c)ys.push(c.low,c.high)}
  if(plot.kind==='bar2d'||plot.kind==='histogram2d')ys.push(0)
  if(!ys.length)return [0,1] as const
  let lo=Math.min(...ys),hi=Math.max(...ys)
  if(lo===hi){lo-=Math.max(.01,Math.abs(lo)*.07);hi+=Math.max(.01,Math.abs(hi)*.07)}
  const pad=(hi-lo)*.07
  return [lo-pad,hi+pad] as const
}
function Canvas2D({plot,syncHover=true,formatX,formatY}:{plot:ResearchPlotData;syncHover?:boolean;formatX:(x:string|number)=>string;formatY:(y:number)=>string}){
  const x=plot.x||[]
  const [activeIndex,setActiveIndex]=useState<number|null>(null)
  const [pinned,setPinned]=useState(false)
  useEffect(()=>{setActiveIndex(null);setPinned(false)},[plot.title,x.length])
  useEffect(()=>{
    if(!syncHover)return
    const handler=(event:Event)=>{
      const target=(event as CustomEvent<{x:string|null}>).detail?.x
      if(pinned)return
      if(target===null){setActiveIndex(null);return}
      if(typeof target==='string'){
        const match=x.findIndex(v=>(exactDateKey(v)||String(v))===target)
        if(match>=0)setActiveIndex(match)
      }
    }
    window.addEventListener('quantlab:chart-cursor',handler)
    return()=>window.removeEventListener('quantlab:chart-cursor',handler)
  },[syncHover,pinned,plot.x])
  const emitCursor=(index:number|null)=>{
    if(!syncHover)return
    window.dispatchEvent(new CustomEvent('quantlab:chart-cursor',{
      detail:{x:index===null?null:(exactDateKey(x[index])||String(x[index]))}}))
  }
  const width=GRID_RIGHT-GRID_LEFT,height=GRID_BOTTOM-GRID_TOP
  const [lo,hi]=useMemo(()=>yBounds(plot),[plot])
  const xp=(i:number)=>GRID_LEFT+(x.length<2?.5:i/(x.length-1))*width
  const yp=(value:number)=>GRID_BOTTOM-(value-lo)/(hi-lo)*height
  const traces=plot.traces||[]
  const numerical=x.length>0&&x.every(finite)
  const temporal=x.length>0&&x.every(v=>typeof v==='string'&&/^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(v)&&Number.isFinite(Date.parse(v)))
  const coords=numerical?x as number[]:temporal?x.map(v=>Date.parse(String(v))):[]
  const [minX,maxX]=coords.length>1?[Math.min(...coords),Math.max(...coords)]:[0,1]
  const xcoord=(i:number)=>coords.length===x.length&&coords.length>1&&maxX>minX
    ?GRID_LEFT+(coords[i]-minX)/(maxX-minX)*width:xp(i)
  const isBar=plot.kind==='bar2d'||plot.kind==='histogram2d'
  const path=(v:(number|null)[])=>v.map((y,i)=>{
    if(!finite(y))return null
    return (i&&finite(v[i-1])&&!plot.break_before?.[i]?'L':'M')+xcoord(i).toFixed(2)+','+yp(y).toFixed(2)
  }).filter(Boolean).join(' ')
  const ticks=[0,.25,.5,.75,1]
  return <div className="ql-plot">
    <svg viewBox="0 0 880 350" className="ql-svg-chart" role="img" tabIndex={0}
      aria-label={plot.title+'; '+(plot.x_label||'x axis')+' versus '+(plot.y_label||'y axis')+
        '. Hover for values or use keyboard arrows.'}
      onPointerMove={event=>{
        if(!x.length||pinned)return
        const rect=event.currentTarget.getBoundingClientRect()
        const mouse=(event.clientX-rect.left)/rect.width*880
        let nearest=0,best=Number.POSITIVE_INFINITY
        for(let i=0;i<x.length;i++){
          const diff=Math.abs(xcoord(i)-mouse)
          if(diff<best){best=diff;nearest=i}
        }
        if(nearest!==activeIndex){
          setActiveIndex(nearest);emitCursor(nearest)
        }
      }}
      onPointerLeave={()=>{if(!pinned){setActiveIndex(null);emitCursor(null)}}}
      onClick={()=>setPinned(old=>!old)}
      onFocus={()=>setActiveIndex(x.length?x.length-1:null)}
      onBlur={()=>setActiveIndex(null)}
      onKeyDown={event=>{
        if(event.key==='ArrowLeft'||event.key==='ArrowRight'){
          event.preventDefault()
          const next=Math.max(0,Math.min(x.length-1,
            (activeIndex??x.length-1)+(event.key==='ArrowRight'?1:-1)))
          setActiveIndex(next);emitCursor(next)
        }
        if(event.key==='Enter'||event.key===' '){
          event.preventDefault();setPinned(old=>!old)
        }
        if(event.key==='Escape'){event.preventDefault();setPinned(false);setActiveIndex(null)}
        if(event.key==='Home'){event.preventDefault();setActiveIndex(0)}
        if(event.key==='End'){event.preventDefault();setActiveIndex(x.length-1)}
      }}>
      {ticks.map(t=><g key={t}>
        <line x1={GRID_LEFT} x2={GRID_RIGHT} y1={GRID_TOP+t*height} y2={GRID_TOP+t*height}
          stroke="#304353" strokeDasharray="3 7" opacity=".8"/>
        <text x="60" y={GRID_TOP+t*height+4} fill="#c0c0c8" fontSize="11" textAnchor="end">{formatY(hi-t*(hi-lo))}</text>
      </g>)}
      {(plot.regions||[]).slice(0,3).map((region,i)=>{
        const start=x.findIndex(v=>String(v)===String(region.start))
        const end=x.findIndex(v=>String(v)===String(region.end))
        if(start<0||end<start)return null
        const x1=xcoord(start),x2=xcoord(end)
        return <g key={i}>
          <rect x={x1} y={GRID_TOP} width={Math.max(1,x2-x1)} height={height}
            fill="#7dc4f5" opacity=".12"/>
          <text x={Math.min(GRID_RIGHT-110,x1+4)} y={GRID_TOP+12+i*13}
            fill="#a9deff" fontSize="9">{region.label.slice(0,25)}</text>
        </g>
      })}
      {plot.band?.lower&&plot.band.upper&&plot.band.lower.length===x.length&&
        <polygon points={[
          ...plot.band.upper.map((v,i)=>xcoord(i)+','+yp(v)),
          ...plot.band.lower.map((v,i)=>xcoord(i)+','+yp(v)).reverse(),
        ].join(' ')} fill="#58dfbf" opacity=".13"/>}
      {plot.candles?.map((c,i)=>{
        if(!c||![c.open,c.high,c.low,c.close].every(finite)||c.high<Math.max(c.open,c.close)||c.low>Math.min(c.open,c.close))return null
        const step=x.length>1?width/(x.length-1):width/3
        const w=Math.max(1,Math.min(12,step*.62)),at=xcoord(i),color=c.close>=c.open?'#70e1ad':'#ff8192'
        return <g key={'candle-'+i}><line x1={at} x2={at} y1={yp(c.high)} y2={yp(c.low)} stroke={color} vectorEffect="non-scaling-stroke"/>
          <rect x={at-w/2} width={w} y={Math.min(yp(c.open),yp(c.close))} height={Math.max(1,Math.abs(yp(c.open)-yp(c.close)))} fill={color}>
            <title>{formatX(x[i])+' · Open '+formatY(c.open)+' · High '+formatY(c.high)+' · Low '+formatY(c.low)+' · Close '+formatY(c.close)}</title>
          </rect></g>
      })}
      {plot.kind==='scatter2d'&&plot.y?.length===x.length?
        plot.y.map((y,i)=>finite(y)?<circle key={i} cx={xcoord(i)} cy={yp(y)} r="3.3" fill={COLORS[0]} opacity=".7">
          <title>{formatX(x[i])+' : '+formatY(y)}</title>
        </circle>:null)
      :isBar?traces.flatMap((trace,t)=>trace.y.map((v,i)=>{
        if(!finite(v))return null
        const center=xcoord(i)
        const bw=Math.min(28,width/Math.max(4,x.length)*(0.78/Math.max(1,traces.length)))
        const start=center+(t-(traces.length-1)/2)*bw
        const base=yp(Math.max(lo,Math.min(hi,0)))
        return <rect key={t+'-'+i} x={start-bw*.46} y={Math.min(base,yp(v))}
          width={bw*.92} height={Math.max(1,Math.abs(base-yp(v)))}
          fill={trace.color||COLORS[t%COLORS.length]} opacity=".8">
          <title>{trace.name+' · '+String(x[i])+' · '+fmt(v)}</title>
        </rect>
      })):
      traces.map((trace,t)=><g key={trace.name}>
        <path d={path(trace.y)} fill="none" stroke={trace.color||COLORS[t%COLORS.length]}
          strokeWidth="2.5" strokeLinejoin="round" vectorEffect="non-scaling-stroke"/>
        {trace.y.length<=24&&trace.y.map((v,i)=>finite(v)?<circle key={i}
          cx={xcoord(i)} cy={yp(v)} r="3" fill={trace.color||COLORS[t%COLORS.length]}>
          <title>{trace.name+' · '+String(x[i])+' · '+fmt(v)}</title>
        </circle>:null)}
      </g>)}
      {plot.threshold!==undefined&&finite(plot.threshold)&&numerical&&maxX>minX&&
         plot.threshold>=minX&&plot.threshold<=maxX&&<>
        <line x1={GRID_LEFT+(plot.threshold-minX)/(maxX-minX)*width}
              x2={GRID_LEFT+(plot.threshold-minX)/(maxX-minX)*width}
              y1={GRID_TOP} y2={GRID_BOTTOM}
              stroke="#ffa466" strokeDasharray="7 5" strokeWidth="1.5"/>
        <text x={GRID_LEFT+(plot.threshold-minX)/(maxX-minX)*width+5} y={GRID_TOP+12}
              fill="#ffc890" fontSize="10">Loss quantile</text>
      </>}
      {(plot.annotations||[]).slice(0,8).map((note,index)=>{
        const idx=x.findIndex(v=>String(v)===String(note.x))
        if(idx<0)return null
        const at=xcoord(idx)
        return <g key={index}>
          <line x1={at} x2={at} y1={GRID_TOP} y2={GRID_BOTTOM}
            stroke="#f6c16a" strokeDasharray="4 5" strokeWidth="1.4"/>
          <rect x={Math.min(at+5,GRID_RIGHT-160)} y={GRID_TOP+index*17}
            width="155" height="15" rx="3" fill="#153849" opacity=".9"/>
          <text x={Math.min(at+9,GRID_RIGHT-156)} y={GRID_TOP+11+index*17}
            fill="#ffe0a3" fontSize="9">{note.label.slice(0,24)}</text>
        </g>
      })}
      {activeIndex!==null&&x[activeIndex]!==undefined&&<g className="ql-active-observation">
        <line x1={xcoord(activeIndex)} x2={xcoord(activeIndex)}
          y1={GRID_TOP} y2={GRID_BOTTOM} stroke="#d3f8e9"
          strokeDasharray="4 5" strokeWidth="1.1"/>
        {plot.kind==='scatter2d'&&plot.y&&finite(plot.y[activeIndex])&&
          <circle cx={xcoord(activeIndex)} cy={yp(plot.y[activeIndex])}
            r="5" stroke="#d5fff0" strokeWidth="2" fill="#70dcca"/>}
        {!isBar&&plot.kind!=='scatter2d'&&traces.map((t,i)=>
          finite(t.y[activeIndex])?<circle key={t.name}
            cx={xcoord(activeIndex)} cy={yp(t.y[activeIndex] as number)}
            r="4.2" stroke="#06232e" strokeWidth="2"
            fill={t.color||COLORS[i%COLORS.length]}/>:null)}
        <rect x={GRID_RIGHT-250} y={GRID_TOP+4} rx="8" width="247"
          height={28+19*Math.min(4,plot.kind==='scatter2d'?1:traces.length)}
          fill="#092332" stroke="#6e9f9d" opacity=".96"/>
        <text x={GRID_RIGHT-240} y={GRID_TOP+22} fontSize="12" fill="#e0fffb">
          {formatX(x[activeIndex]).slice(0,36)}
        </text>
        {(plot.kind==='scatter2d'?[
          {name:plot.y_label||'Value',value:plot.y?.[activeIndex]},
        ]:traces.slice(0,4).map(t=>({name:t.name,value:t.y[activeIndex]})))
          .map((r,i)=><text key={r.name} x={GRID_RIGHT-240} y={GRID_TOP+41+i*19}
            fontSize="11" fill={COLORS[i%COLORS.length]}>
            {r.name.slice(0,18)+': '+(finite(r.value)?formatY(r.value):'missing')}
          </text>)}
      </g>}
      {Array.from(new Set([0,.25,.5,.75,1].map(t=>Math.round(t*(x.length-1))))).filter(i=>i>=0&&i<x.length).map((idx,i,indices)=><text key={idx} x={xcoord(idx)} y="300" textAnchor={i===0?'start':i===indices.length-1?'end':'middle'}
          fill="#b9b9c1" fontSize="11">{formatX(x[idx]).slice(0,24)}</text>)}
      <text x="450" y="336" textAnchor="middle" fill="#b1c1d0" fontSize="12">{plot.x_label}</text>
      <text x="18" y="152" fill="#b1c1d0" fontSize="11" textAnchor="middle"
        transform="rotate(-90,18,152)">{plot.y_label}</text>
    </svg>
    <p className="ql-plot-hover-help">Hover or touch to inspect · click (or press Enter) to
      {pinned?' unlock the cursor':' lock the cursor'} · arrow keys move between observations.
      {pinned?' Cursor pinned.':''}</p>
    <div className="ql-legend">{plot.candles&&<span><i style={{background:'#70e1ad'}}/>Close ≥ open <i style={{background:'#ff8192'}}/>Close &lt; open</span>}{traces.map((t,i)=><span key={t.name}>
      <i style={{background:t.color||COLORS[i%COLORS.length]}}/>{t.name}
    </span>)}{plot.kind==='scatter2d'&&<span><i style={{background:COLORS[0]}}/>{plot.y_label||'Observations'}</span>}{plot.band&&<span><i style={{background:'#79d5c2'}}/>{plot.band_label||'Model lower/upper band'}</span>}</div>
    {activeIndex!==null&&x[activeIndex]!==undefined&&<div className="ql-inspection" aria-live="off"><strong>{plot.x_label||'X'}: {formatX(x[activeIndex])}</strong>{plot.candles?.[activeIndex]&&Object.entries(plot.candles[activeIndex]!).map(([key,v])=><span key={key}>{key}: {formatY(v)}</span>)}{(plot.kind==='scatter2d'?[{name:plot.y_label||'Value',value:plot.y?.[activeIndex]}]:traces.map(t=>({name:t.name,value:t.y[activeIndex]}))).map(t=><span key={t.name}>{t.name}: {finite(t.value)?formatY(t.value):'Missing'}</span>)}</div>}
  </div>
}
function Heatmap({plot}:{plot:ResearchPlotData}){
  const labels=plot.labels||[]
  const values=plot.values||[]
  const rowLabels=plot.row_labels||labels
  const cols=labels.length,rows=rowLabels.length
  if(!cols||!rows||cols>25||rows>25||values.length!==rows||
    values.some(row=>row.length!==cols||row.some(v=>!finite(v))))
    return <p className="ql-muted">No valid bounded heatmap matrix to render.</p>
  const cell=Math.max(18,Math.min(48,Math.floor(590/Math.max(cols,rows))))
  const all=values.flat(),low=Math.min(...all),high=Math.max(...all),span=Math.max(1e-12,high-low)
  const correlation=plot.scale!=='sequential'
  const scale=(value:number)=>{
    const z=clamp(correlation?(value+1)/2:(value-low)/span,0,1)
    return 'rgb('+Math.round(37+(1-z)*60)+','+Math.round(110+z*94)+','+
      Math.round(151+z*29)+')'
  }
  return <div className="ql-heat-scroll"><svg width={90+cell*cols} height={82+cell*rows}
    role="img" aria-label={plot.title+' heatmap with '+rows+' rows and '+cols+' columns'}>
    {labels.map((label,i)=><text key={i} x={77+cell*i+cell/2} y="58"
      fill="#9bb7c8" fontSize="10" textAnchor="start"
      transform={'rotate(-40 '+(77+cell*i+cell/2)+' 58)'}>{label.slice(0,13)}</text>)}
    {rowLabels.map((label,i)=><text key={i} x="70" y={70+cell*i+cell/2}
      fill="#9bb7c8" fontSize="10" textAnchor="end">{label.slice(0,13)}</text>)}
    {values.flatMap((row,i)=>row.map((v,j)=><g key={i+'-'+j}>
      <rect x={77+j*cell} y={65+i*cell} width={cell-2} height={cell-2}
        fill={scale(v)} rx="2"><title>{rowLabels[i]+' × '+labels[j]+': '+fmt(v)}</title></rect>
      {cols<=10&&rows<=10&&<text x={77+j*cell+cell/2} y={65+i*cell+cell/2+4}
        textAnchor="middle" fontSize="10" fill="#071b25">{fmt(v)}</text>}
    </g>))}
  </svg><p className="ql-muted">{correlation?'Color represents correlation from -1 to +1.':
    'Color is scaled between the finite minimum ('+fmt(low)+') and maximum ('+fmt(high)+').'}
    {' '}Hover for exact source-computed values.</p></div>
}
type Point3={x:number;y:number;depth:number}
function Surface3D({plot}:{plot:ResearchPlotData}){
  const [azimuth,setAzimuth]=useState(-42)
  const [elevation,setElevation]=useState(26)
  const [zoom,setZoom]=useState(1)
  const drag=useRef<{x:number;y:number;az:number;el:number}|null>(null)
  const xs=(plot.x||[]).map(Number),ys=(plot.y||[]).map(Number),zs=plot.z||[]
  const good=xs.length>=2&&ys.length>=2&&xs.length<=41&&ys.length<=41&&zs.length===ys.length&&zs.every(r=>r.length===xs.length)
  const mesh=useMemo(()=>{
    if(!good)return {polys:[] as {key:string;points:string;depth:number;color:string;value:number}[],axes:[] as Point3[]}
    const vals=zs.flat(),zmin=Math.min(...vals),zmax=Math.max(...vals),zr=Math.max(1e-9,zmax-zmin)
    const angle=azimuth*Math.PI/180,tilt=elevation*Math.PI/180
    const proj=(i:number,j:number,z:number):Point3=>{
      const a=(i/(xs.length-1)-.5)*2,b=(j/(ys.length-1)-.5)*2,c=((z-zmin)/zr-.5)*1.5
      const rX=Math.cos(angle)*a-Math.sin(angle)*b
      const rY=Math.sin(angle)*a+Math.cos(angle)*b
      return {x:435+zoom*178*rX,y:220-zoom*178*(Math.sin(tilt)*rY+Math.cos(tilt)*c),
              depth:Math.cos(tilt)*rY-Math.sin(tilt)*c}
    }
    const polygons=[]
    for(let j=0;j<ys.length-1;j++)for(let i=0;i<xs.length-1;i++){
      const z=[zs[j][i],zs[j][i+1],zs[j+1][i+1],zs[j+1][i]]
      const v=[proj(i,j,z[0]),proj(i+1,j,z[1]),proj(i+1,j+1,z[2]),proj(i,j+1,z[3])]
      const shade=clamp((z.reduce((a,b)=>a+b,0)/4-zmin)/zr,0,1)
      const hue=185-50*shade
      polygons.push({key:j+'-'+i,points:v.map(p=>p.x.toFixed(2)+','+p.y.toFixed(2)).join(' '),
        depth:v.reduce((a,b)=>a+b.depth,0)/4,color:`hsl(${hue} 58% ${27+38*shade}%)`,
        value:z.reduce((a,b)=>a+b,0)/4})
    }
    polygons.sort((a,b)=>a.depth-b.depth)
    return {polys:polygons,axes:[proj(0,0,zmin),proj(xs.length-1,0,zmin),
        proj(0,ys.length-1,zmin),proj(0,0,zmax)]}
  },[azimuth,elevation,zoom,xs.length,ys.length,JSON.stringify(zs),good])
  if(!good)return <p className="ql-muted">No valid numerical surface was returned.</p>
  const axes=mesh.axes
  return <div className="ql-surface">
    <div className="ql-graph-controls">
      <span>Drag to rotate · 3D mathematical surface</span>
      <button type="button" onClick={()=>setZoom(v=>clamp(v-.15,.55,1.45))}>−</button>
      <button type="button" onClick={()=>setZoom(v=>clamp(v+.15,.55,1.45))}>+</button>
      <button type="button" onClick={()=>{setAzimuth(-42);setElevation(26);setZoom(1)}}>Reset</button>
    </div>
    <svg viewBox="0 0 880 460" role="img" tabIndex={0}
      aria-label={'Interactive 3D surface: '+plot.title+'. Use arrow keys to rotate'}
      onKeyDown={e=>{
        if(e.key==='ArrowLeft'||e.key==='ArrowRight'){setAzimuth(v=>v+(e.key==='ArrowRight'?8:-8));e.preventDefault()}
        if(e.key==='ArrowUp'||e.key==='ArrowDown'){setElevation(v=>clamp(v+(e.key==='ArrowUp'?5:-5),5,75));e.preventDefault()}
      }}
      onPointerDown={e=>{drag.current={x:e.clientX,y:e.clientY,az:azimuth,el:elevation};e.currentTarget.setPointerCapture(e.pointerId)}}
      onPointerMove={e=>{if(!drag.current)return;setAzimuth(drag.current.az+(e.clientX-drag.current.x)*.36);setElevation(clamp(drag.current.el+(e.clientY-drag.current.y)*.28,5,75))}}
      onPointerUp={()=>{drag.current=null}} onPointerCancel={()=>{drag.current=null}}>
      <rect x="0" y="0" width="880" height="460" rx="8" fill="#0c1b2a"/>
      {mesh.polys.map(face=><polygon key={face.key} points={face.points}
        fill={face.color} fillOpacity=".87" stroke="#081d27" strokeOpacity=".6"
        strokeWidth=".65"><title>{plot.z_label+': '+fmt(face.value)}</title></polygon>)}
      {[[1,0],[2,0],[3,0]].map(([i,j])=><line key={i} x1={axes[i].x} y1={axes[i].y}
        x2={axes[j].x} y2={axes[j].y} stroke="#c3def0" strokeOpacity=".65" strokeWidth="1.6"/>)}
      {axes.slice(1).map((p,i)=><text key={i} x={p.x} y={p.y+(i===2?-9:20)}
        fontSize="12" textAnchor="middle" fill="#c6e7ee">{[plot.x_label,plot.y_label,plot.z_label][i]}</text>)}
    </svg>
    <div className="ql-plot-foot"><span>X: {fmt(xs[0])} → {fmt(xs[xs.length-1])}</span>
      <span>Y: {fmt(ys[0])} → {fmt(ys[ys.length-1])}</span>
      <span>Z: {fmt(Math.min(...zs.flat()))} → {fmt(Math.max(...zs.flat()))}</span></div>
  </div>
}
const csvCell=(value:unknown)=>{
  if(typeof value==='number'&&Number.isFinite(value))return String(value)
  const text=String(value??'')
  const safe=/^[=+@\\-]/.test(text)?"'"+text:text
  return '"'+safe.replaceAll('"','""')+'"'
}
function dataTable(plot:ResearchPlotData):{columns:string[];rows:SnapshotCell[][]}{
  if(plot.kind==='surface3d'){
    const xs=plot.x||[],ys=plot.y||[],z=plot.z||[]
    return {columns:[plot.x_label||'x',plot.y_label||'y',plot.z_label||'z'],
      rows:ys.flatMap((y,i)=>xs.map((x,j)=>[x,y,z[i]?.[j]??null]))}
  }
  if(plot.kind==='heatmap2d'){
    const xs=plot.labels||[],ys=plot.row_labels||xs,z=plot.values||[]
    return {columns:['Row','Column','Value'],
      rows:ys.flatMap((y,i)=>xs.map((x,j)=>[y,x,z[i]?.[j]??null]))}
  }
  const axes=plot.x||[]
  const traces=plot.traces||[]
  const columns=[plot.x_label||'X',
    ...(plot.candles?['Open (points)','High (points)','Low (points)','Close (points)']:[]),
    ...(plot.kind==='scatter2d'?[plot.y_label||'Value']:traces.map(t=>t.name)),
    ...(plot.band?['Band lower','Band upper']:[])]
  return {columns,rows:axes.map((x,i)=>[
    x,...(plot.candles?[plot.candles[i]?.open??null,plot.candles[i]?.high??null,plot.candles[i]?.low??null,plot.candles[i]?.close??null]:[]),...(plot.kind==='scatter2d'?[plot.y?.[i]??null]:traces.map(t=>t.y[i]??null)),
    ...(plot.band?[plot.band.lower[i]??null,plot.band.upper[i]??null]:[])
  ])}
}
function downloadFile(name:string,contents:string,mime:string){
  const url=URL.createObjectURL(new Blob([contents],{type:mime}))
  const anchor=document.createElement('a')
  anchor.href=url;anchor.download=name;document.body.appendChild(anchor)
  anchor.click();anchor.remove()
  URL.revokeObjectURL(url)
}
function safeName(name:string){
  return name.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'').slice(0,70)||'plot'
}
export default function ResearchPlot({plot,provenance,formatX,formatY=fmt,allowApply=true}:{plot:ResearchPlotData;provenance?:string;formatX?:(x:string|number)=>string;formatY?:(y:number)=>string;allowApply?:boolean}){
  const displayX=formatX||((x:string|number)=>typeof x==='number'?fmt(x):String(x))
  const targetId=useId()
  const [attached,setAttached]=useState<PythonApplied|null>(null)
  const [hidden,setHidden]=useState<string[]>([])
  useEffect(()=>setHidden([]),[plot.title])
  const chart=useRef<HTMLElement|null>(null)
  const [view,setView]=useState<{start:number;end:number}|null>(null)
  const [syncHover,setSyncHover]=useState(true)
  const [expandError,setExpandError]=useState('')
  const [syncViewport,setSyncViewport]=useState(true)
  const n=plot.x?.length||0
  const zoomable=n>=8&&plot.kind!=='surface3d'&&plot.kind!=='heatmap2d'
  const dateKeys=useMemo(()=>(plot.x||[]).map(exactDateKey),[plot.x])
  const syncable=zoomable&&dateKeys.length===n&&dateKeys.every(v=>v!==null)
  const left=view?.start??0,right=view?.end??n
  useEffect(()=>{setView(null)},[plot.title,n])
  useEffect(()=>{
    if(!syncViewport||!syncable)return
    const handler=(event:Event)=>{
      const detail=(event as CustomEvent<{first:string|null;last:string|null}>).detail
      if(!detail||(!detail.first&&!detail.last)){setView(null);return}
      if(!detail.first||!detail.last)return
      const start=dateKeys.indexOf(detail.first),end=dateKeys.indexOf(detail.last)
      if(start<0||end<start+4)return  // No inference between different calendars.
      setView(start===0&&end===n-1?null:{start,end:end+1})
    }
    window.addEventListener('quantlab:chart-viewport',handler)
    return()=>window.removeEventListener('quantlab:chart-viewport',handler)
  },[dateKeys,n,syncViewport,syncable])
  const broadcast=(next:{start:number;end:number}|null)=>{
    setView(next)
    if(syncViewport&&syncable)window.dispatchEvent(new CustomEvent('quantlab:chart-viewport',{
      detail:{first:next?dateKeys[next.start]:null,last:next?dateKeys[next.end-1]:null}}))
  }
  const clampView=(start:number,span:number)=>{
    const size=Math.max(5,Math.min(n,span))
    const beginning=Math.max(0,Math.min(n-size,start))
    broadcast(size===n?null:{start:beginning,end:beginning+size})
  }
  const zoomIn=()=>clampView(right-Math.max(5,Math.ceil((right-left)/1.6)),
    Math.max(5,Math.ceil((right-left)/1.6)))
  const zoomOut=()=>clampView(right-Math.min(n,Math.ceil((right-left)*1.6)),
    Math.min(n,Math.ceil((right-left)*1.6)))
  const pan=(dir:-1|1)=>{
    const span=right-left,step=Math.max(1,Math.round(span/3))
    clampView(left+dir*step,span)
  }
  const visible=useMemo(()=>{
    if(!view||!zoomable)return plot
    return {...plot,x:plot.x?.slice(view.start,view.end),
      y:plot.y?.slice(view.start,view.end),
      candles:plot.candles?.slice(view.start,view.end),
      traces:plot.traces?.map(t=>({...t,y:t.y.slice(view.start,view.end)})),
      break_before:plot.break_before?.slice(view.start,view.end),
      band:plot.band?{lower:plot.band.lower.slice(view.start,view.end),
        upper:plot.band.upper.slice(view.start,view.end)}:undefined}
  },[plot,view,zoomable])
  const inputSignature=useMemo(()=>JSON.stringify(dataTable(visible)),[visible])
  const attachedMatches=Boolean(attached&&inputSignature===JSON.stringify({columns:attached.snapshot.columns,rows:attached.snapshot.rows}))
  const overlay=attachedMatches&&attached?.mode==='overlay'?attached.plot.traces||[]:[]
  useEffect(()=>{
    if(!allowApply)return
    const apply=(event:Event)=>{
      const detail=(event as CustomEvent<PythonApplied>).detail
      if(!detail||detail.snapshot.targetId!==targetId)return
      if(inputSignature!==JSON.stringify({columns:detail.snapshot.columns,rows:detail.snapshot.rows}))return
      if(detail.mode==='overlay'&&(plot.kind!=='line2d'||detail.plot.y_label!==visible.y_label||JSON.stringify(detail.plot.x)!==JSON.stringify(visible.x)))return
      setAttached(detail);event.preventDefault()
    }
    window.addEventListener(PYTHON_APPLY_EVENT,apply)
    return()=>window.removeEventListener(PYTHON_APPLY_EVENT,apply)
  },[allowApply,targetId,inputSignature,plot.kind,visible.y_label,visible.x])
  const shown=useMemo(()=>({...visible,traces:[...(visible.traces||[]).filter(t=>!hidden.includes(t.name)).map(t=>({...t,color:t.color||COLORS[(plot.traces||[]).findIndex(x=>x.name===t.name)%COLORS.length]})),...overlay.map((t,i)=>({...t,name:'Python: '+t.name,color:COLORS[(i+4)%COLORS.length]}))]}),[visible,hidden,plot.traces,overlay])
  const table=useMemo(()=>dataTable(plot),[plot])
  const saveSvg=()=>{
    const original=chart.current?.querySelector('svg')
    if(!original)return
    const copy=original.cloneNode(true) as SVGSVGElement
    copy.setAttribute('xmlns','http://www.w3.org/2000/svg')
    if(!copy.getAttribute('viewBox')){
      const w=Number(copy.getAttribute('width')||880)
      const h=Number(copy.getAttribute('height')||460)
      copy.setAttribute('viewBox',`0 0 ${w} ${h}`)
    }
    const description=document.createElementNS('http://www.w3.org/2000/svg','desc')
    description.textContent='QuantLab computed figure. Source class: '+String(provenance||'not specified')+
      '. Charts with synthetic paths are not observed market prices.'
    copy.insertBefore(description,copy.firstChild)
    downloadFile('quantlab-'+safeName(plot.title)+'.svg',
      new XMLSerializer().serializeToString(copy),'image/svg+xml;charset=utf-8')
  }
  const saveCsv=()=>{
    const contents=[table.columns.map(csvCell).join(','),
      ...table.rows.map(row=>row.map(csvCell).join(','))].join('\n')
    downloadFile('quantlab-'+safeName(plot.title)+'.csv',contents,'text/csv;charset=utf-8')
  }
  const exportPython=()=>{
    // Explicit download only: never execute arbitrary chart code in the browser.
    const payload=JSON.stringify({title:plot.title,provenance:provenance??null,columns:table.columns,rows:table.rows})
    const code='# QuantLab research snapshot; source and units are preserved.\nimport json\n\ndata = json.loads('+JSON.stringify(payload)+')\ncolumns = data["columns"]\nrows = data["rows"]\n\n# Add your own analysis below. Missing observations are None.\nprint(data["title"], columns, len(rows))\n'
    downloadFile('quantlab-'+safeName(plot.title)+'.py',code,'text/x-python;charset=utf-8')
  }
  const expand=async()=>{
    setExpandError('')
    try{
      if(document.fullscreenElement===chart.current)await document.exitFullscreen()
      else if(chart.current?.requestFullscreen)await chart.current.requestFullscreen()
      else setExpandError('Full screen is not supported by this browser.')
    }catch{setExpandError('Unable to expand this chart in the current browser.')}
  }
  return <section className="ql-chart-card" ref={chart}>
    <div className="ql-chart-title-row"><h4>{plot.title}</h4>
      <div className="ql-chart-export">
        <button type="button" onClick={()=>void expand()}>Full screen / exit</button>
        {zoomable||(!['surface3d','heatmap2d'].includes(plot.kind)&&!!plot.x?.length)?<button type="button" onClick={()=>{
          const input=dataTable(visible)
          openSnapshotInPython({targetId:allowApply?targetId:undefined,title:plot.title,provenance:(provenance||'computed chart')+' · visible viewport snapshot',columns:input.columns,rows:input.rows})
        }} title="Attach visible observations to isolated Python workspace">Python analysis</button>:null}
        <button type="button" onClick={exportPython} title="Download a Python script with the full plotted dataset for offline analysis">Python snapshot</button>
        <button type="button" onClick={saveSvg} aria-label={'Export SVG of '+plot.title}>Export SVG</button>
        <button type="button" onClick={saveCsv} aria-label={'Export CSV of '+plot.title}>Export CSV</button>
      </div>
    </div>
    {expandError&&<p role="alert">{expandError}</p>}
    <p className="ql-muted">X: {plot.x_label||'Not specified by model'} · Y: {plot.y_label||'Not specified by model'}{plot.z_label?' · Z: '+plot.z_label:''}</p>
    {zoomable&&<div className="ql-chart-viewport" role="group"
      aria-label={'Chart zoom and synchronized pointer for '+plot.title}>
      <button type="button" onClick={zoomIn} disabled={right-left<=5}
        aria-label={'Zoom in '+plot.title}>Zoom in +</button>
      <button type="button" onClick={zoomOut} disabled={!view}
        aria-label={'Zoom out '+plot.title}>Zoom out −</button>
      <button type="button" onClick={()=>pan(-1)} disabled={!view||left===0}
        aria-label={'Pan left '+plot.title}>◀ Earlier</button>
      <button type="button" onClick={()=>pan(1)} disabled={!view||right>=n}
        aria-label={'Pan right '+plot.title}>Later ▶</button>
      <button type="button" onClick={()=>broadcast(null)} disabled={!view}
        aria-label={'Reset zoom '+plot.title}>Reset</button>
      <label><input type="checkbox" checked={syncHover} onChange={e=>setSyncHover(e.target.checked)}/>
        Link crosshair by shared dates</label>
      {syncable&&<label><input type="checkbox" checked={syncViewport}
        onChange={e=>setSyncViewport(e.target.checked)}/>
        Link zoom/pan on exact dates</label>}
      <span>{right-left} of {n} observations visible · full-series CSV export</span>
    </div>}
    {!!plot.traces?.length&&plot.kind!=='surface3d'&&plot.kind!=='heatmap2d'&&<div className="ql-series-controls" aria-label="Visible chart series">{plot.traces.map((t,i)=><button type="button" key={t.name} aria-pressed={!hidden.includes(t.name)} disabled={!hidden.includes(t.name)&&plot.traces!.length-hidden.length<=1} onClick={()=>setHidden(h=>h.includes(t.name)?h.filter(x=>x!==t.name):[...h,t.name])}><i style={{background:t.color||COLORS[i%COLORS.length]}}/>{t.name}</button>)}</div>}
    {plot.kind==='surface3d'?<Surface3D plot={plot}/>:
     plot.kind==='heatmap2d'?<Heatmap plot={plot}/>:
     <Canvas2D plot={shown} syncHover={syncHover&&syncable} formatX={displayX} formatY={formatY}/>}
    {attached&&<div className="ql-inspection"><span>{attachedMatches?'Custom result '+attached.runId+' · '+attached.mode:'Custom result is no longer aligned to the displayed observations. Recompute from current snapshot.'}</span><button type="button" onClick={()=>setAttached(null)}>Remove custom result</button></div>}
    {attachedMatches&&attached?.mode==='companion'&&<ResearchPlot plot={attached.plot} provenance="custom-python-snapshot" allowApply={false}/>}
    {attachedMatches&&attached?.mode==='overlay'&&<details><summary>Custom overlay data and export</summary><ResearchPlot plot={attached.plot} provenance="custom-python-snapshot" allowApply={false}/></details>}
    <details className="ql-chart-data">
      <summary>Inspect plotted observations ({table.rows.length.toLocaleString('en-US')} rows)</summary>
      <div className="ql-table-scroll">
        <table><thead><tr>{table.columns.map((key,i)=><th key={i}>{key}</th>)}</tr></thead>
          <tbody>{table.rows.slice(0,40).map((row,i)=><tr key={i}>
            {row.map((cell,j)=><td key={j}>{cell===null?'Missing':String(cell)}</td>)}</tr>)}</tbody>
        </table>
      </div>
      {table.rows.length>40&&<p className="ql-note">Preview shows 40 rows.
        Export CSV contains all {table.rows.length.toLocaleString('en-US')} rows.</p>}
    </details>
    {plot.units?.numeric&&<p className="ql-muted">
      Numeric unit: {plot.units.numeric}.
      {plot.units.price_currency_declared_by_user?
        ' Currency '+plot.units.price_currency+' was declared by the user, not source-verified.':''}
      {' '}CSV and chart values preserve original numeric scale.
    </p>}
    <p className="ql-muted">{provenance==='synthetic'?
      'SEEDED SIMULATION · ARTIFICIAL DATA · Reproducible hypothetical paths, not real market history.':
      provenance==='historical'?
      'HISTORICAL INPUT · Some graphs also contain seeded scenario paths. Check plot titles and methodological limits.':
      provenance==='market'?
      'ORIGINAL QUOTE INPUT · Computed prices, surfaces and payoff paths are MODEL outputs, not historical fills.':
      provenance==='theoretical'?
      'THEORETICAL MODEL · User-assumed inputs, not observed quotes.':
      provenance==='custom-python-snapshot'?'CUSTOM PYTHON · Client-provided snapshot; not independently source-verified. Not a live signal.':
      provenance==='observed-index'?'OBSERVED MINUTE CLOSES · No manufactured OHLC or volume.':
      provenance==='observed-index-ohlc'?'OBSERVED TICK-DERIVED OHLC · Completed minute aggregates; tick delivery can be incomplete; no authenticated volume.':
      provenance==='recorded-chain-spot'?'RECORDED Dhan REST SPOT RECEIPTS · Irregular timestamps; not live index ticks or OHLC.':
      provenance==='options-snapshot'?'OPTIONS SNAPSHOT · Provider observations and model-derived quantities; not executable fills.':
      provenance==='original-depth-snapshot'?'ORIGINAL DISPLAYED DEPTH · Snapshot quantities, not executed volume or fills.':
      'Source: Python research engine · computed values with explicit evidence classification.'}</p>
  </section>
}
