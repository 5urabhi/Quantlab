/** NSE *regular window* in Indian Standard Time; NOT a holiday/exchange status API.
 * A live label requires fresh broker packets on top of this schedule.
 * Special sessions and holidays are deliberately not inferred from weekdays.
 */
export type MarketWindow = {
  istClock:string;
  regularWindow:boolean;
  weekday:string;
  label:string;
  note:string;
};
const dateParts=new Intl.DateTimeFormat('en-GB',{
  timeZone:'Asia/Kolkata',weekday:'short',hour:'2-digit',minute:'2-digit',hourCycle:'h23',
});
const clock=new Intl.DateTimeFormat('en-IN',{
  timeZone:'Asia/Kolkata',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23',
});
export function nseMarketWindow(atEpochMs:number):MarketWindow{
  const date=new Date(atEpochMs);
  const parts=Object.fromEntries(dateParts.formatToParts(date).map(p=>[p.type,p.value]));
  const minuteOfDay=Number(parts.hour)*60+Number(parts.minute);
  const weekday=parts.weekday||'';
  const weekdayWindow=['Mon','Tue','Wed','Thu','Fri'].includes(weekday);
  const regularWindow=weekdayWindow&&minuteOfDay>=9*60+15&&minuteOfDay<15*60+30;
  return {
    istClock:clock.format(date)+' IST',
    regularWindow,
    weekday,
    label:regularWindow?'Within regular NSE session hours':'Outside regular NSE session hours',
    note:'Schedule only. Holidays and special sessions require exchange confirmation; a LIVE badge requires fresh broker observations.',
  };
}
