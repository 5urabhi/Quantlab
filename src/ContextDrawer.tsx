import {useEffect,useRef,type ReactNode} from 'react'
import {X} from 'lucide-react'
import './context-drawer.css'

export default function ContextDrawer({title,subtitle,onClose,children}:{title:string;subtitle?:string;onClose:()=>void;children:ReactNode}){
  const ref=useRef<HTMLDialogElement>(null)
  useEffect(()=>{
    const dialog=ref.current
    const previous=document.activeElement instanceof HTMLElement?document.activeElement:null
    if(dialog&&!dialog.open)dialog.showModal()
    return()=>{if(dialog?.open)dialog.close();if(previous?.isConnected)previous.focus()}
  },[])
  return <dialog ref={ref} className="ql-context-drawer" aria-label={title} onCancel={event=>{event.preventDefault();onClose()}} onClick={event=>{if(event.target===event.currentTarget)onClose()}}>
    <div className="ql-context-drawer-body"><header><div><small>RECORD DETAILS</small><h2>{title}</h2>{subtitle&&<p>{subtitle}</p>}</div><button type="button" aria-label="Close details" onClick={onClose}><X size={18}/></button></header>
    <div className="ql-context-drawer-content">{children}</div></div>
  </dialog>
}
