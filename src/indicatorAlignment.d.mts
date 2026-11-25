import type {ResearchPlotData,ResearchTrace} from './ResearchPlots'
export type Source='index_minutes'|'chain_spot_receipts'
export type SourceRow=(string|number|undefined)[]
export type AlignedMonitor={id:string;name:string;revision:number;last_utc:string;alignment:{source:Source;expiry:string|null;rows:SourceRow[]};plot:ResearchPlotData}
export function alignIndicator(overlay:AlignedMonitor,source:Source,expiry:string|null,rows:SourceRow[],plotX:(string|number)[]):ResearchTrace[]|null
