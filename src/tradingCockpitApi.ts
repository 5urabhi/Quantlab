/**
 * Single safe, informative error surface for the local Trading Copilot.
 * FastAPI returns strings, {message}, {error}, or Pydantic [{loc,msg,type}].
 * Never let an object become the opaque "[object Object]" shown in the UI.
 */
function textDetail(value:unknown,depth=0):string {
  if(depth>5||value===null||value===undefined)return ''
  if(typeof value==='string')return value.trim()
  if(typeof value==='number'||typeof value==='boolean')return String(value)
  if(Array.isArray(value))return value.map(v=>textDetail(v,depth+1)).filter(Boolean).slice(0,5).join('; ')
  if(typeof value==='object'){
    const obj=value as Record<string,unknown>
    const loc=Array.isArray(obj.loc)?obj.loc.map(String).filter(x=>x!=='body'&&x!=='query').join(' → '):''
    const details=['detail','message','msg','error','errors','reason','description']
      .map(key=>textDetail(obj[key],depth+1)).find(Boolean)||''
    if(loc&&details)return loc+': '+details
    if(details)return details
    const typed=typeof obj.code==='string'?obj.code:''
    if(typed)return typed.replaceAll('_',' ')
    // Unknown response formats are still readable and cannot expose [object Object].
    try{return JSON.stringify(value).slice(0,550)}catch{return 'Unrecognized server response'}
  }
  return ''
}
export class MarketApiError extends Error {
  readonly status:number
  readonly path:string
  readonly hint:string
  constructor(path:string,status:number,detail:unknown){
    const reason=textDetail(detail)||('Request failed (HTTP '+status+')')
    super(reason.slice(0,700))
    this.name='MarketApiError'
    this.status=status
    this.path=path.split('?')[0]
    this.hint=status===422?'Check the selected instrument, dates and other inputs.':
      status===401||status===403?'Verify your Dhan connection and permissions under Connections & Data.':
      status===404?'The selected historical source is unavailable. Check the shared Market Library.':
      status>=500?'Local analysis failed. Retry; if it persists, inspect the API server log.':
      'Review the selected source and retry. Existing market observations are preserved.'
  }
}
export function readableError(error:unknown):string{
  if(error instanceof Error)return error.message
  return textDetail(error)||'An unknown local research error occurred.'
}
export async function marketApi<T>(path:string,init?:RequestInit):Promise<T>{
  let response:Response
  try{response=await fetch(path,init)}
  catch(e){throw new MarketApiError(path,0,
    'Cannot reach the local QuantLab API. Make sure bash run.sh is running. '+readableError(e))}
  if(!response.ok){
    let detail:unknown
    try{const payload=await response.json() as unknown
      detail=(typeof payload==='object'&&payload!==null&&'detail' in payload)
        ?(payload as {detail:unknown}).detail:payload
    }catch{
      try{detail=(await response.text()).slice(0,300)}catch{/* empty body */}
    }
    throw new MarketApiError(path,response.status,detail)
  }
  try{return await response.json() as T}
  catch{throw new MarketApiError(path,response.status,'The local API returned an invalid JSON response.')}
}
export async function marketPost<T>(path:string,body:unknown):Promise<T>{
  return marketApi<T>(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
}
