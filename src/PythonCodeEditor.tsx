import {forwardRef,useMemo,useRef,type KeyboardEvent,type UIEvent} from 'react'
import './python-code-editor.css'

const keywords=new Set('and as assert async await break class continue def del elif else except False finally for from global if import in is lambda None nonlocal not or pass raise return True try while with yield match case'.split(' '))
const builtins=new Set('abs all any bool dict enumerate float int len list map max min print range reversed round set sorted str sum tuple type zip'.split(' '))
type Token={text:string;kind:string}
function tokenize(code:string):Token[]{
  // Display-only lexical highlighting: never evaluate user code or inject HTML.
  const pattern=/"""[\s\S]*?(?:"""|$)|'''[\s\S]*?(?:'''|$)|"(?:\\.|[^"\\\n])*(?:"|$)|'(?:\\.|[^'\\\n])*(?:'|$)|#[^\n]*|\b(?:0[xX][0-9a-fA-F_]+|0[bB][01_]+|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?)\b|[a-zA-Z_]\w*|[+\-*\/%=<>!&|^~:]+/g
  const output:Token[]=[]
  let end=0
  for(const match of code.matchAll(pattern)){
    const start=match.index??0,text=match[0]
    if(start>end)output.push({text:code.slice(end,start),kind:'plain'})
    const kind=text.startsWith('#')?'comment':text[0]==='"'||text[0]==="'"?'string':keywords.has(text)?'keyword':builtins.has(text)?'builtin':/^\d/.test(text)?'number':/^[+\-*\/%=<>!&|^~:]/.test(text)?'operator':'plain'
    output.push({text,kind});end=start+text.length
  }
  if(end<code.length)output.push({text:code.slice(end),kind:'plain'})
  return output
}
type Props={value:string;onChange:(value:string)=>void;label:string;onRun?:()=>void;maxLength?:number;disabled?:boolean}
const PythonCodeEditor=forwardRef<HTMLTextAreaElement,Props>(function PythonCodeEditor({value,onChange,label,onRun,maxLength=20000,disabled=false},ref){
  const highlight=useRef<HTMLPreElement>(null),numbers=useRef<HTMLPreElement>(null)
  const tokens=useMemo(()=>tokenize(value),[value])
  const scroll=(event:UIEvent<HTMLTextAreaElement>)=>{
    const el=event.currentTarget
    if(highlight.current){highlight.current.scrollTop=el.scrollTop;highlight.current.scrollLeft=el.scrollLeft}
    if(numbers.current)numbers.current.scrollTop=el.scrollTop
  }
  const key=(event:KeyboardEvent<HTMLTextAreaElement>)=>{
    if(event.key==='Tab'&&!event.shiftKey){
      event.preventDefault();const el=event.currentTarget
      const start=el.selectionStart,end=el.selectionEnd
      if(value.length-(end-start)+4<=maxLength){onChange(value.slice(0,start)+'    '+value.slice(end));requestAnimationFrame(()=>el.setSelectionRange(start+4,start+4))}
    }
    if((event.ctrlKey||event.metaKey)&&event.key==='Enter'&&onRun){event.preventDefault();onRun()}
  }
  return <div className="ql-python-editor">
    <pre className="ql-python-gutter" ref={numbers} aria-hidden="true">{value.split('\n').map((_,i)=>i+1).join('\n')+'\n'}</pre>
    <div className="ql-python-code">
      <pre className="ql-python-highlight" ref={highlight} aria-hidden="true">{tokens.map((token,i)=><span key={i} className={'ql-token-'+token.kind}>{token.text}</span>)}{'\n'}</pre>
      <textarea ref={ref} aria-label={label} disabled={disabled} value={value} onChange={e=>onChange(e.target.value)} maxLength={maxLength} spellCheck={false} autoComplete="off" autoCapitalize="off" wrap="off" onScroll={scroll} onKeyDown={key}/>
    </div>
  </div>
})
export default PythonCodeEditor
