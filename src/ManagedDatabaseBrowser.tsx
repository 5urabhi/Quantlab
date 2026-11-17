import {useCallback, useEffect, useState} from 'react'
import {AlertTriangle, Database, LockKeyhole, RefreshCw, Search} from 'lucide-react'

type Column = {name:string;type:string;primary_key:boolean}
type TableMeta = {name:string;columns:Column[];filterable:string[]}
type DatabaseMeta = {id:string;label:string;available:boolean;read_only:boolean;tables:TableMeta[];warning?:string}
type Catalog = {databases:DatabaseMeta[];privacy:string}
type Page = {database_id:string;table:string;columns:Column[];rows:Array<Record<string,unknown>>;
  page:number;per_page:number;has_more:boolean;read_only:boolean;note:string}
async function load<T,>(path:string):Promise<T>{
  const r=await fetch('/api/data-manager/'+path)
  if(!r.ok){
    let msg='Unable to inspect database'
    try{const x=await r.json() as {detail?:string};msg=x.detail||msg}catch{/* non-json error */}
    throw new Error(msg)
  }
  return r.json() as Promise<T>
}
export default function ManagedDatabaseBrowser(){
  const [catalog,setCatalog]=useState<Catalog|null>(null)
  const [dbId,setDbId]=useState('')
  const [tableName,setTableName]=useState('')
  const [filterColumn,setFilterColumn]=useState('')
  const [filterValue,setFilterValue]=useState('')
  const [appliedFilter,setAppliedFilter]=useState('')
  const [page,setPage]=useState(1)
  const [data,setData]=useState<Page|null>(null)
  const [error,setError]=useState('')
  const [reload,setReload]=useState(0)
  const refresh=useCallback(async()=>{
    try{
      const info=await load<Catalog>('database-catalog')
      setCatalog(info);setError('')
      setDbId(id=>info.databases.find(db=>db.id===id&&db.available)?.id||
        info.databases.find(db=>db.available)?.id||'')
    }catch(e){setError(e instanceof Error?e.message:String(e))}
  },[])
  useEffect(()=>{void refresh()},[refresh,reload])
  const database=catalog?.databases.find(db=>db.id===dbId)
  const selectedTable=database?.tables.find(t=>t.name===tableName)
  useEffect(()=>{
    if(!database?.tables.some(x=>x.name===tableName)){
      setTableName(database?.tables[0]?.name||'')
      setFilterColumn('')
      setFilterValue('')
      setAppliedFilter('')
      setPage(1)
    }
  },[database,tableName])
  useEffect(()=>{
    if(!database||!selectedTable){setData(null);return}
    let active=true
    const query=new URLSearchParams({database_id:database.id,table:selectedTable.name,
      page:String(page),per_page:'40'})
    if(filterColumn&&appliedFilter){query.set('filter_column',filterColumn);query.set('filter_value',appliedFilter)}
    setData(null)
    void load<Page>('database-table?'+query.toString()).then(x=>{if(active){setData(x);setError('')}})
      .catch(e=>{if(active)setError(e instanceof Error?e.message:String(e))})
    return()=>{active=false}
  },[database?.id,selectedTable?.name,page,filterColumn,appliedFilter])
  const changeDb=(id:string)=>{
    setDbId(id);setTableName('');setFilterColumn('');setFilterValue('');setAppliedFilter('');setPage(1)
  }
  return <section className="qm-panel qm-managed-dbs" aria-label="Read-only database tables">
    <div className="qm-panel-title"><h3><Database size={18}/> Database tables</h3>
      <button type="button" className="ws-button secondary" onClick={()=>setReload(v=>v+1)}>
        <RefreshCw size={14}/> Refresh</button></div>
    <p className="qm-caption"><LockKeyhole size={14}/> Managed SQLite databases are always read-only.
      No arbitrary SQL, saved payload fields, filesystem paths or broker credentials can be viewed or changed here.</p>
    {error&&<div className="qm-alert" role="alert"><AlertTriangle size={16}/>{error}</div>}
    <div className="qm-db-toolbar">
      <label>Managed database
        <select aria-label="Managed database" value={dbId} onChange={e=>changeDb(e.target.value)}>
          <option value="">Choose a database</option>
          {catalog?.databases.map(d=><option disabled={!d.available} key={d.id} value={d.id}>
            {d.label}{d.available?'':' (not created yet)'}</option>)}
        </select></label>
      <label>Data table
        <select aria-label="Managed table" value={tableName} onChange={e=>{
          setTableName(e.target.value);setFilterColumn('');setFilterValue('');
          setAppliedFilter('');setPage(1)}}>
          <option value="">Choose a table</option>
          {database?.tables.map(t=><option value={t.name} key={t.name}>{t.name}</option>)}
        </select></label>
    </div>
    <form className="qm-db-filter" onSubmit={e=>{e.preventDefault();setAppliedFilter(filterValue);setPage(1)}}>
      <label>Filter field
        <select aria-label="Filter database field" value={filterColumn} onChange={e=>{
          setFilterColumn(e.target.value);setAppliedFilter('');setFilterValue('');setPage(1)}}>
          <option value="">No filter</option>
          {selectedTable?.filterable.map(c=><option key={c} value={c}>{c}</option>)}
        </select></label>
      <label>Exact field value
        <input aria-label="Exact database field value" disabled={!filterColumn}
          value={filterValue} onChange={e=>setFilterValue(e.target.value)}
          placeholder="e.g. NSE_EQ:1333"/></label>
      <button type="submit" className="ws-button secondary" disabled={!filterColumn}>
        <Search size={14}/> Filter</button>
    </form>
    {!database||!selectedTable?<p className="qm-caption">Choose an available managed database and table.</p>:
      data?<><div className="qm-scroll"><table><thead><tr>{data.columns.map(c=>
        <th key={c.name} title={c.type+(c.primary_key?' · primary key':'')}>{c.name}</th>)}</tr></thead>
        <tbody>{data.rows.map((r,i)=><tr key={i}>{data.columns.map(c=>
          <td key={c.name} title={String(r[c.name]??'')}>{String(r[c.name]??'—')}</td>)}</tr>)}</tbody></table>
        {data.rows.length===0&&<p className="qm-caption">No records match this exact filter.</p>}</div>
        <div className="qm-pager"><span>Showing up to {data.per_page} saved rows · read-only</span>
          <div><button disabled={page===1} onClick={()=>setPage(v=>Math.max(v-1,1))}>Previous</button>
            <span>Page {page}</span><button disabled={!data.has_more} onClick={()=>setPage(v=>v+1)}>Next</button></div></div>
        <p className="qm-caption">{data.note}</p>
      </>:<p className="qm-caption">Loading protected table rows…</p>}
  </section>
}
