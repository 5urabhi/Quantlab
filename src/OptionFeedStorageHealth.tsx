import {useEffect,useState} from 'react'
import {Database,ShieldAlert} from 'lucide-react'
import {marketApi,readableError} from './tradingCockpitApi'
import './option-feed-storage-health.css'

type StorageHealth={
  armed:boolean;connected:boolean;state:string
  storage_state?:string;storage_writer_alive?:boolean
  storage_daily_events?:number|null;storage_daily_limit?:number|null
  storage_last_saved_received_utc?:string|null
  storage_free_gb?:number|null;storage_reserve_gb?:number|null
  storage_gap_detected?:boolean;storage_gap_started_utc?:string|null
  storage_last_drop_utc?:string|null;storage_last_error?:string|null
  dropped_events:number;queue_depth:number
}
function ist(stamp?:string|null){
  if(!stamp)return 'No confirmed saved event'
  const date=new Date(stamp)
  if(!Number.isFinite(date.getTime()))return 'Unknown saved time'
  return date.toLocaleString('en-IN',{timeZone:'Asia/Kolkata',
    day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',second:'2-digit'})+' IST'
}
export default function OptionFeedStorageHealth(){
  const [data,setData]=useState<StorageHealth|null>(null)
  const [error,setError]=useState('')
  useEffect(()=>{
    let active=true
    async function poll(){
      if(document.hidden)return
      try{
        const value=await marketApi<StorageHealth>('/api/trading-cockpit/option-feed/status')
        if(active){setData(value);setError('')}
      }catch(e){
        if(active)setError(readableError(e))
      }
    }
    void poll()
    const timer=window.setInterval(()=>void poll(),45000)
    return()=>{active=false;window.clearInterval(timer)}
  },[])
  if(error&&!data)return <div className="ofs-health unknown" role="status">
    <Database size={17}/>Quote/OI storage health unavailable: {error}.
    Spread research may lack saved trade-activity evidence.</div>
  if(!data)return null
  const state=data.storage_state??'not_reported'
  const risk=data.armed&&(
    data.storage_gap_detected||
    (data.connected&&data.storage_writer_alive===false)||
    ['storage_unavailable','storage_flush_incomplete','sqlite_storage_write_failure',
      'insufficient_free_disk_space','ingest_queue_overflow'].includes(state))
  const healthy=data.armed&&data.connected&&data.storage_writer_alive===true&&
    state==='recording'&&!data.storage_gap_detected
  const level=risk?'problem':healthy?'healthy':'unknown'
  const label=risk?'Quote/OI storage warning':healthy?
    'Quote/OI saving original events':data.armed?
    'Quote/OI storage not yet verified':'Quote/OI feed not armed'
  return <section className={'ofs-health '+level} aria-label="Option quote storage health">
    {risk?<ShieldAlert size={18}/>:<Database size={18}/>}
    <div>
      <strong>{label}</strong>
      <p>Connection: {data.connected?'streaming':'not connected'} ·
        {' '}Writer: {data.storage_writer_alive?'running':'not confirmed'} ·
        {' '}Today's saved events: {data.storage_daily_events==null?
          'not reported':data.storage_daily_events.toLocaleString('en-IN')} ·
        {' '}Last saved: {ist(data.storage_last_saved_received_utc)}.
        {data.storage_daily_limit==null&&' No artificial daily event cap.'}
      </p>
      {risk&&<p className="ofs-caution">
        Source gap possible: {data.dropped_events.toLocaleString('en-IN')}
        {' '}reported drops this session. State: {state.replaceAll('_',' ')}.
        {' '}Lost source packets cannot be reconstructed from the latest quote.
      </p>}
      {data.storage_free_gb!=null&&<small>Free disk: {data.storage_free_gb} GB ·
        Reserved safety space: {data.storage_reserve_gb??'—'} GB ·
        Writer queue: {data.queue_depth.toLocaleString('en-IN')}.</small>}
      {!data.armed&&<small>Depth recording and full-universe Quote/OI event
        recording are separate subscriptions. Missing Quote/OI data blocks
        trade-activity validation.</small>}
      {data.storage_last_error&&<small>
        Last storage issue: {data.storage_last_error}</small>}
      {error&&<small>Latest status refresh failed: {error}</small>}
    </div>
  </section>
}
