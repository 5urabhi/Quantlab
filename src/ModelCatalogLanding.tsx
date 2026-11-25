import {Activity, ArrowRight, BarChart3, CheckCircle2, Clock3, Database,
  Layers, Search, Sigma, SlidersHorizontal} from 'lucide-react'
import {useEffect,useMemo, useState} from 'react'
import {marketApi,readableError} from './tradingCockpitApi'
import type {SavedScriptMeta} from './SavedScriptRunner'

export type CatalogEntry={
  id:string;group:string;title:string;mode:'synthetic'|'theoretical'|'historical'|'market';
  description:string;chart:string
}
type SavedModel={id:string;model_id:string;title:string;mode:string;generated_utc:string}
type Readiness={id:string;source_ready:boolean}
type Props={
  models:CatalogEntry[];readiness:Readiness[];recent:SavedModel[];sourceLabel:string;
  onOpen:(id:string)=>void;onReopen:(id:string)=>void;onOpenResults?:()=>void;onOpenCustom?:(id?:string)=>void
}

const FAMILIES=[
  'All models','Stochastic Processes','Volatility & Econometrics',
  'Derivatives & Options','Portfolio Optimization','Tail Risk & Inference'
]
export function catalogFamily(model:Pick<CatalogEntry,'group'|'id'>):string{
  if(model.group!=='3D Visual Laboratory')return model.group
  if(model.id==='risk_surface')return 'Portfolio Optimization'
  return 'Derivatives & Options'
}
const MODE_TEXT:Record<CatalogEntry['mode'],string>={
  synthetic:'Simulation',theoretical:'Mathematical',historical:'Historical data',
  market:'Option quotes'
}
const DETAILS:Record<string,string>={
  gbm:'Explore possible price paths',gbm_fit:'Estimate drift and volatility from prices',
  ou:'Study mean reversion',ou_fit:'Measure reversion in observed volatility',
  heston:'Explore changing volatility',heston_proxy:'Fit a historical variance proxy',
  merton:'Explore price jumps',merton_fit:'Estimate historical jump frequency',
  risk_surface:'Stress correlation and portfolio weights',
  option_surface:'Explore theoretical option prices',
  option_surface_quote:'Compare quoted option scenarios',
}
function simpleDescription(model:CatalogEntry):string{
  const custom=DETAILS[model.id]
  if(custom)return custom
  const words=model.description.split(/[.;]/)[0].trim()
  return words.length>94?words.slice(0,92).trimEnd()+'…':words
}
export default function ModelCatalogLanding({models,readiness,recent,sourceLabel,
  onOpen,onReopen,onOpenResults,onOpenCustom}:Props){
  const [custom,setCustom]=useState<SavedScriptMeta[]>([])
  const [customError,setCustomError]=useState('')
  const reloadCustom=()=>{void marketApi<{scripts:SavedScriptMeta[]}>('/api/user-scripts').then(d=>{setCustom(d.scripts.filter(s=>s.kind==='model'));setCustomError('')}).catch(e=>setCustomError(readableError(e)))}
  useEffect(()=>{if(onOpenCustom)reloadCustom()},[Boolean(onOpenCustom)])
  const [family,setFamily]=useState('All models')
  const [search,setSearch]=useState('')
  const [filter,setFilter]=useState<'all'|'data'|'math'>('all')
  const available=new Map(readiness.map(item=>[item.id,item.source_ready]))
  const visible=useMemo(()=>models.filter(model=>(
    (family==='All models'||catalogFamily(model)===family)&&
    (filter==='all'||(filter==='data'?['historical','market'].includes(model.mode):
      ['theoretical','synthetic'].includes(model.mode)))&&
    (model.title+' '+model.description+' '+model.id+' '+catalogFamily(model))
      .toLowerCase().includes(search.trim().toLowerCase())
  )),[models,family,filter,search])
  const ready=visible.filter(m=>['synthetic','theoretical'].includes(m.mode)||
    available.get(m.id)).length
  return <div className="ql-new-catalog">
    <header className="ql-catalog-hero">
      <div><div className="ql-catalog-eyebrow"><Layers size={15}/> QUANTLAB / MODELS</div>
        <h2>What would you like to explore?</h2>
        <p>Choose a model. Adjust the inputs. Run it. The details stay out of your way until you need them.</p>
      </div>
      <div className="ql-catalog-hero-metrics" role="status">
        <strong>{models.length}</strong><span>model calculations</span>
        <small>{sourceLabel||'Current research library'}</small>
      </div>
    </header>

    <div className="ql-catalog-toolbar">
      <label className="ql-catalog-search"><Search size={18}/>
        <span className="ql-sr-only">Search mathematical models</span>
        <input type="search" value={search} placeholder="Search models, e.g. Heston, VaR, options…"
          onChange={event=>setSearch(event.target.value)}/></label>
      <div className="ql-catalog-type-toggle" role="group" aria-label="Filter model inputs">
        {([['all','All'],['data','Market data'],['math','Simulation / theory']] as const).map(
          ([id,label])=><button key={id} type="button" className={filter===id?'active':''}
            aria-pressed={filter===id} onClick={()=>setFilter(id)}>{label}</button>)}
      </div>
    </div>

    <nav className="ql-catalog-categories" aria-label="Model research areas">
      {FAMILIES.map((name,index)=><button type="button" key={name}
        className={family===name?'active':''} aria-pressed={family===name}
        onClick={()=>setFamily(name)}>
        {index===0?<Sigma size={17}/>:index===1?<Activity size={17}/>:
          index===2?<BarChart3 size={17}/>:index===3?<Layers size={17}/>:
          index===4?<SlidersHorizontal size={17}/>:<Database size={17}/>}
        <span>{name}</span>
        <small>{name==='All models'?models.length:models.filter(m=>catalogFamily(m)===name).length}</small>
      </button>)}
    </nav>

    <div className="ql-catalog-list-heading">
      <div><h3>{family==='All models'?'All research models':family}</h3>
        <p>{visible.length} shown · {ready} can start with available inputs</p></div>
      <span className="ql-catalog-chart-home"><BarChart3 size={15}/>
        Charts and 3D views are in <strong>Results &amp; Charts</strong></span>
    </div>
    <div className="ql-catalog-card-grid">
      {visible.map(model=>{
        const needsData=['historical','market'].includes(model.mode)
        const sourceReady=Boolean(available.get(model.id))
        return <button type="button" key={model.id} className="ql-catalog-model-card"
          onClick={()=>onOpen(model.id)}
          aria-label={'Open '+model.title}>
          <div className="ql-catalog-model-meta">
            <span className="ql-catalog-family-name">{catalogFamily(model)}</span>
            <span className={'ql-catalog-readiness '+(needsData&&!sourceReady?'needs-source':'ready')}>
              {needsData&&!sourceReady?'Needs data':needsData?'Source available':'Ready'}</span>
          </div>
          <h4>{model.title.replace(/^3D /,'')}</h4>
          <p>{simpleDescription(model)}</p>
          <footer><span>{MODE_TEXT[model.mode]}</span><span className="ql-catalog-open">
            Open model <ArrowRight size={16}/></span></footer>
        </button>
      })}
      {!visible.length&&<div className="ql-catalog-empty">
        <Search size={24}/><strong>No matching models</strong>
        <p>Try a different model name or reset your filters.</p>
        <button type="button" onClick={()=>{setFamily('All models');setFilter('all');setSearch('')}}>
          Show all models</button>
      </div>}
    </div>
    {onOpenCustom&&<section className="ql-catalog-recent" aria-label="Registered custom Python models"><div className="ql-saved-runner-head"><div><h3>My Python models</h3><p className="ws-caption">Custom, versioned research models are separate from the built-in validated registry.</p></div><div className="ws-actions"><button type="button" className="ws-button" onClick={reloadCustom}>Refresh custom models</button><button type="button" className="ws-button primary" onClick={()=>onOpenCustom()}>Custom model laboratory</button></div></div>
      {customError&&<p role="alert">{customError}</p>}
      <div className="ql-catalog-card-grid">{custom.filter(c=>c.name.toLowerCase().includes(search.toLowerCase())).map(c=><button type="button" key={c.id} className="ql-catalog-model-card" onClick={()=>onOpenCustom(c.id)} aria-label={'Open custom model '+c.name}><span className="ql-catalog-family-name">Python · revision {c.revision}</span><h4>{c.name}</h4><p>Requires user-selected model inputs and isolated execution.</p><footer>Custom / not validated <ArrowRight size={16}/></footer></button>)}</div>
      {!custom.length&&<p className="ws-caption">Save a script with the model category to register it here.</p>}</section>}
    {recent.length>0&&<section className="ql-catalog-recent">
      <div><Clock3 size={17}/><strong>Continue recent work</strong></div>
      <div className="ql-catalog-recent-items">
        {recent.slice(0,3).map(item=><button key={item.id} type="button"
          onClick={()=>onReopen(item.id)}>
          <CheckCircle2 size={15}/><span>{item.title}</span><ArrowRight size={15}/></button>)}
      </div>
      {onOpenResults&&<button className="ql-catalog-all-results" type="button"
        onClick={onOpenResults}>All results <ArrowRight size={14}/></button>}
    </section>}
  </div>
}
