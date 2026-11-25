import {useEffect,useState} from 'react'
import {BookOpen,Database,FlaskConical,Search,X} from 'lucide-react'
import './quantlab-v2.css'
type Result={kind:string;id:string;title:string;location:string}
export default function GlobalSearchV2({open,onClose,onOpen,routes=[],onOpenRoute}:{
  open:boolean;onClose:()=>void
  routes?:{id:string;title:string;section:string;description:string}[];onOpenRoute?:(id:string)=>void
  onOpen:(destination:'mathematics'|'projects'|'data'|'workspace'|'history'|'guide')=>void
}){
  const [query,setQuery]=useState('')
  const [results,setResults]=useState<Result[]>([])
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  useEffect(()=>{
    if(!open){setQuery('');setResults([]);setError('');return}
    const escape=(event:KeyboardEvent)=>{if(event.key==='Escape')onClose()}
    window.addEventListener('keydown',escape)
    return()=>window.removeEventListener('keydown',escape)
  },[open,onClose])
  useEffect(()=>{
    if(!open||!query.trim()){setResults([]);setBusy(false);return}
    const controller=new AbortController()
    const timer=window.setTimeout(()=>{
      setBusy(true)
      void fetch('/api/workspace/search?q='+encodeURIComponent(query),{
        signal:controller.signal,
      }).then(async response=>{
        if(!response.ok)throw Error('Search HTTP '+response.status)
        return response.json() as Promise<{results:Result[]}>
      }).then(result=>{if(!controller.signal.aborted){
        setResults(result.results.slice(0,25));setError('')
      }}).catch(e=>{
        if(!controller.signal.aborted)setError(e instanceof Error?e.message:String(e))
      }).finally(()=>{if(!controller.signal.aborted)setBusy(false)})
    },240)
    return()=>{window.clearTimeout(timer);controller.abort()}
  },[open,query])
  if(!open)return null
  const terms=query.trim().toLowerCase().split(/\s+/).filter(Boolean)
  const matches=routes.filter(r=>terms.every(t=>(r.title+' '+r.section+' '+r.id+' '+r.description).toLowerCase().includes(t))).slice(0,terms.length?12:8)
  const openResult=(item:Result)=>{
    onClose()
    if(item.location==='model_catalog'){
      try{localStorage.setItem('ql-target-model',item.id)}catch{}
      onOpen('mathematics');return
    }
    if(item.kind==='project'||item.kind==='notebook'||item.kind==='report'){
      onOpen('projects');return
    }
    if(item.location==='resource_library'||item.kind==='dataset'){
      onOpen('data');return
    }
    if(item.kind==='chart'||item.kind==='comparison'){
      onOpen('workspace');return
    }
    if(item.location==='documentation'){
      onOpen('guide');return
    }
    onOpen('history')
  }
  return <div className="v2-search-backdrop" onMouseDown={e=>{
    if(e.target===e.currentTarget)onClose()
  }}>
    <section className="v2-search-dialog" role="dialog" aria-modal="true"
      aria-label="Search QuantLab resources">
      <header><Search size={21}/><input autoFocus value={query}
        aria-label="Search models, data, saved results and projects"
        placeholder="Find a model, dataset, run, chart, report…"
        onChange={event=>setQuery(event.target.value)}/>
        <button onClick={onClose} aria-label="Close search"><X size={18}/></button></header>
      {busy&&<p role="status" className="v2-search-info">Searching saved local research…</p>}
      {error&&<p role="alert" className="v2-search-error">{error}</p>}
      <div className="v2-search-results">
        {onOpenRoute&&matches.length>0&&<><p className="v2-search-info">Go to page</p>{matches.map(r=><button key={"route:"+r.id} type="button" onClick={()=>{onClose();onOpenRoute(r.id)}}><Search size={18}/><span><strong>{r.title}</strong><small>{r.section} · Page</small></span></button>)}</>}
        {results.length>0&&<p className="v2-search-info">Saved resources</p>}
        {results.map(item=><button key={item.kind+':'+item.id}
          onClick={()=>openResult(item)}>
          {item.kind==='dataset'?<Database size={18}/>:
            item.location==='model_catalog'?<FlaskConical size={18}/>:<BookOpen size={18}/>}
          <span><strong>{item.title}</strong>
            <small>{item.kind.replaceAll('_',' ')} · {item.id}</small></span>
        </button>)}
        {!busy&&query.trim()&&!results.length&&!matches.length&&!error&&
          <p className="v2-search-info">No matching saved resources. Try a model, ticker or project name.</p>}
        {!query.trim()&&<p className="v2-search-info">Searches the actual local research library.
          QuantLab does not fabricate results for missing data.</p>}
      </div>
      <footer>Ctrl/Cmd + K to open · Esc to close · Read-only search</footer>
    </section>
  </div>
}
