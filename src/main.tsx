import React,{Suspense} from 'react'
import ReactDOM from 'react-dom/client'

// V2 is the default. The exact old React workbench remains available during
// migration at ?ui=classic, enabling live-feature regression testing/rollback.
const App = React.lazy(()=>import('./Workstation'))
const ClassicApp = React.lazy(()=>import('./WorkstationClassic'))
const Selected = new URLSearchParams(window.location.search).get('ui')==='classic'
  ?ClassicApp:App

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Suspense fallback={<div role="status" style={{padding:24,color:'#b5d6e6'}}>
      Loading local QuantLab workspace…
    </div>}>
      <Selected/>
    </Suspense>
  </React.StrictMode>
)
