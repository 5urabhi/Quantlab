# NSE session policy integration (reviewed November 27, 2026)

Scope: regular NSE trading-day boundaries, not a universal exchange holiday or special-session calendar. The authoritative schedules are NSE/CMTR/74466 and NSE/FAOP/74467 (effective August 3, 2026), revised by NSE/CMTR/77355 and NSE/FAOP/77356 (effective December 7, 2026). See NSE CAS 2.0 FAQ, version 1, November 6, 2026: https://nsearchives.nseindia.com/web/mediaattachment/2026-11/FAQs_for_CM_and_FO_FOR_CAS_2.0_20261109152618.pdf . NSE F&O underlyings: https://www.nseindia.in/static/products-services/equity-derivatives-list-underlyings-information .

All minute clocks are IST, with an exclusive close and inclusive 09:15 open.

| Dates | CAS cash CTS | Other cash CTS | Derivatives segment | Expiring index contract |
|---|---|---|---|---|
| Before Aug 3 | 09:15–15:30 (375) | 09:15–15:30 | 09:15–15:30 | 15:30 |
| Aug 3 through Dec 6, 2026 | 09:15–15:15 (360) | 09:15–15:30 | 09:15–15:40 (385) | 15:40 |
| From Dec 7, 2026 | 09:15–15:30 (375) | 09:15–15:30 | 09:15–15:45 (390) | 15:30 |

August closing auction runs from 15:15 through matching at 15:35. From December, auction order-entry/transition runs 15:30–15:40, followed by matching through 15:45 and transition through 15:50. Neither auction nor post-close trading is treated as continuous cash OHLCV. A scheduled contract trading cutoff is not a verified settlement timestamp.

## Review evidence and eligibility

The existing shared policy is expanded from 14 to the 16 exact NSE_EQ identities in saved BANKNIFTY batch batch_705d84bb56304777. The user's checksum-verified stock-clock audit of August 3 through October 13 reported exactly 360 aligned minutes on each of 50 index comparison sessions for every identity. Fresh one-day HDFCBANK and ICICIBANK probes on August 3 and October 13 reproduced the schedule. All 16 are reviewed NSE derivative underlyings. The map is a narrow normal-session research policy, not a point-in-time exchange-wide CAS security master. Unknown identities or explicit mismatches retain the conservative 375-minute baseline; a future eligibility change requires reviewed dated source evidence. Special sessions and extraordinary halts remain outside this policy. No fabricated minutes, interpolation, inferred holidays, deletion, or replacement of original source data.

## Integration and limits

- Automatic bank repair already uses the shared session policy; all 16 exact reviewed mappings now share it.
- Original stock minute coverage and audit use dated expected minutes, exclude auction/post-close observations, and distinguish a missing CTS observation from scheduled closure. Daily research prefers native daily records on reviewed CAS days rather than treating the last CTS trade as the auction close.
- BANKNIFTY five-minute candle and sequence studies retain the same 375-slot **index comparison grid**, never forward-fill a closed stock, expose scheduled-open features and separately report scheduled-closed, undocumented-membership and observed windows. Historical alpha masks constituent observations outside CTS; its last comparison bar is not official settlement. Existing model results require new evaluation after the feature-schema change. No model trained or promoted here.
- The read-only option capture gate already follows derivatives segment hours. Constituent cash and stock-derivative packet filters now use the corresponding schedule. Option chain expiry selection, cached expiry filters and advanced-options assumptions distinguish expiring index contracts from the full derivatives session. Historical rolling option receipts without exact expiry remain a bounded comparison-window study, not certified full-session coverage. Participant report availability cannot precede the scheduled derivative-segment close.
- Other legacy fixed-window research protocols remain fixed comparison horizons, not a new exchange-wide full-session guarantee. Historical daily membership and weights, missing index data, FRED coverage, full derivative/auction archives, broker-specific cutoffs, exact settlement values and special trading sessions still require their own evidence. No changes to order endpoints.

## Local verification

Run offline tests on the branch before loading it into the live workstation. Then re-audit the original stock batch over 2026-08-01 to 2026-10-14; the expected result on the previously audited bytes is 50 complete CTS sessions per reviewed stock, 18,000 observed slots per stock, not an invented extension to 375. A separate audit of the full acquisition range is needed for global readiness. Backend reload after merge is necessary for the recorder and maintenance code; never stop active recording just to change historical coverage.
