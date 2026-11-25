export type SnapshotCell = string | number | boolean | null
import type {ResearchPlotData} from './ResearchPlots'
export type PythonSnapshot = {targetId?:string;title:string;provenance:string;columns:string[];rows:SnapshotCell[][]}
export const PYTHON_SNAPSHOT_EVENT='quantlab:python-snapshot'
export const STRATEGY_SCRIPT_EVENT='quantlab:strategy-script'
export function openSnapshotInPython(snapshot:PythonSnapshot){
  window.dispatchEvent(new CustomEvent(PYTHON_SNAPSHOT_EVENT,{detail:snapshot}))
}

export const PYTHON_APPLY_EVENT='quantlab:python-apply'
export type PythonApplied={snapshot:PythonSnapshot;plot:ResearchPlotData;runId:string;mode:'companion'|'overlay'}
export function applyPythonResult(detail:PythonApplied){
  return !window.dispatchEvent(new CustomEvent(PYTHON_APPLY_EVENT,{detail,cancelable:true}))
}
