# Free/authorized global-market pilot (no JForex required)

QuantLab uses its existing data/dhan/shared_market.sqlite3. The new
global_market_bars table stores unique exact broker BID OHLCV bars;
global_market_receipts retains the original compressed CSV plus hashes.
It does not overwrite or rename Dhan, cash-index, or GIFT NIFTY series.

## Source and access
Dukascopy publishes an official Historical Data Export and the JForex
IHistory interface. Free demo access is advertised (normally 14 days);
historical instrument entitlements, actual dates and permitted local
storage/research use must be verified with the provider. The website terms
restrict automated scraping and database construction without permission.
Do not run this code without permission under the applicable data terms.
Use only the documented JForex API, not an unofficial website scraper.
No trading account deposit is required for the demo; no order API is used.

References:
- https://www.dukascopy.com/swiss/english/platforms/jforex/
- https://www.dukascopy.com/swiss/english/marketwatch/historical/
- https://www.dukascopy.com/swiss/english/legal-pages/terms-of-use/
- https://www.dukascopy.com/client/javadoc3/com/dukascopy/api/IHistory.html
- https://www.dukascopy.com/swiss/english/cfd/range-of-markets/cfd-indices/
- https://wiki.dukascopy.com/en/manuals/jforex4-desktop/strategies/

## Recommended first run: existing sources, no new account

From the existing QuantLab root, after reviewing the existing FRED and
Alpaca data entitlements:

    .venv/bin/python -m scripts.global_market_data enable-existing --confirm-reviewed
    .venv/bin/python -m scripts.global_market_data inventory

This enables the existing context worker's authorized FRED and Alpaca
daily sources without changing existing provider mappings or selected
Alpaca feed. It does not backfill five years, start a second API worker,
or download Asian opening prices. The earlier audited daily ETF and FRED
observations remain in the same database. Keep QuantLab running for
automatic source receipts.

## Optional direct CSV export: no JForex or extra account

Dukascopy's public Historical Data Export web tool is separate from the
trading platform. Its general website terms restrict database use and
automated collection. Use the following import ONLY if the relevant
data-specific terms or written authorization allow local database storage
and research. Free access alone does not establish that right. No scraper,
browser challenge workaround or automated third-party downloader is provided.

Select the actual named instrument, BID side, GMT/UTC, and 5-minute bars
in an authorized export. Start with a short interval. Save the original CSV.
Supported direct formats are GMT time,Open,High,Low,Close,Volume or
timestamp,open,high,low,close,volume (UTC epoch milliseconds). Explicitly
verify identity, interval, BID side and bar-start timestamp semantics;
they are not inferred from filenames. For example:

    .venv/bin/python -m scripts.global_market_data import-export \
      --file "/absolute/path/japan.csv" --instrument JPN.IDX/JPY \
      --minutes 5 --mode archive --archive-lag-minutes 5 --confirm-reviewed

The archive lag is an illustrative research assumption, not verified
historical publication evidence. Use receipt mode without a reviewed lag.
Original bytes and SHA-256 are retained; repeat imports are idempotent.
For larger datasets export smaller monthly files (maximum 50,000 bars
per file). No permission to scrape or database data is implied.

## Optional JForex route (not necessary for the initial study)
1. Obtain authorized JForex access and review local data-storage rights.
   Install official JForex Desktop and open a demo session. Do not share
   login details in chat or commit them. No funding or order is needed.
2. Open integrations/jforex/QuantLabGlobalExport.java in Strategies,
   compile and choose **Local run**, not historical tester or remote run.
3. Confirm the data rights checkbox. Leave dates blank for a seven-day
   pilot. Choose 5 minutes (or 1 minute), and leave the single instrument
   blank for all ten. History export writes one finalized CSV per
   instrument/calendar-month slice under the platform's files directory.
   The log prints its absolute path. Empty requests do not create a file.
   An existing nonempty completed export is skipped; explicit repair is
   possible but a changed OHLCV conflict is rejected by QuantLab.
4. After reviewing the export, import from the QuantLab root:

       .venv/bin/python -m scripts.global_market_data import \
         --inbox "/absolute/path/quantlab_global_archive" \
         --mode archive --archive-lag-minutes 5 --confirm-reviewed

   The 5-minute lag is an example conservative research assumption, not
   verified historical publication evidence. Review the actual source
   latency and use a suitable positive lag. Without such an assumption use
   receipt mode instead (not usable for historical as-of studies).
   Re-run bounded batches (default 20 new files, max 200) until no new
   files remain. A conflicting bar or lock is reported, never overwritten.
   Do not delete original exports. Inspect the returned counts and dates.

       .venv/bin/python -m scripts.global_market_data inventory
       .venv/bin/python -m scripts.global_market_data features --date 2025-03-03

5. After the pilot succeeds, set from/to dates for the desired historical
   five-year period (UTC, end exclusive). Run separately from the live
   recorder; keep historical SQLite import batches bounded and prefer
   Indian off-hours. Five years of data are a target, not a guarantee.
6. For new bars, run the JForex strategy locally with Live only enabled.
   It writes one atomically finalized bar file when the provider delivers
   a completed BID candle. Import from its quantlab_global_live folder
   by enabling the existing context worker once (with applicable permission):

       .venv/bin/python -m scripts.global_market_data enable-live \
         --inbox "/absolute/path/quantlab_global_live" --confirm-reviewed

   Then keep the authorized JForex session and QuantLab running. The
   worker checks the current and two preceding UTC date folders; older
   missed days must be reviewed/re-imported explicitly. Receipt known
   time is actual QuantLab import time, never bar time. To stop automatic
   intake, run the same module with disable-live. Fully unattended broker
   acquisition and historical gap repair are not certified; the demo may expire. The Java source must be
   compiled and tested in the actual JForex installation.

## Identities and model boundaries
Japan 200+, China A50, Hong Kong and Singapore Blue Chip are CFDs, not
Nikkei, Shanghai Composite, Hang Seng or STI cash prices. Australia, US
500, US 100 Tech, Germany 40, UK 100 and Europe 50 supplement them.
There is deliberately no GIFT NIFTY alias. Do not treat CFD volume as
exchange cash volume. No fabricated opening gap or trading signal.

Opening features use regular Asian cash-market **reference clocks**
in local exchange time (converted to UTC with IANA zones). Exact
contiguous observed 5/15/30/60-minute windows and their availability
cutoffs are required; missing or zero-volume bars invalidate a window.
The latest proxy return also needs a recent closed bar. These reference
windows are not proof of cash-market sessions: foreign holiday/special
session calendars, genuine prior cash close/open, official cash-index
series, GIFT NIFTY and paired BANKNIFTY model validation remain separate
tasks. No training or trading performance claim is made.


## Recommended intraday route: existing Alpaca BOATS feed

Alpaca documents free-plan access to 15-minute-delayed historical BOATS
bars (https://docs.alpaca.markets/us/docs/245-trading-for-trading-api).
A local Nov 24, 2026 three-hour probe returned SPY, QQQ, EWY, FXI, EWJ,
and EWT, with no candles for EWS, EWH, EWA or KBE in that sample.
This proves access to that range, not earlier dates or complete history.
No new platform or subscription is needed for that verified access.

After reviewing applicable data rights:

    .venv/bin/python -m scripts.global_market_data backfill-boats --days 30 --confirm-reviewed
    .venv/bin/python -m scripts.global_market_data enable-boats --confirm-reviewed
    .venv/bin/python -m scripts.global_market_data inventory

Dates are Indian calendar dates; the default excludes today. For
repeatable longer experiments, pin --to-date (exclusive). A bounded
invocation attempts up to eight newest seven-day windows. Repeat with
the same dates to resume verified observed windows, or use --repair
for an explicit recheck. An observed window does NOT certify complete
history; an empty response is not interpreted as a valid holiday or
as successful historical coverage. Original provider JSON bytes are
retained in the same canonical receipts table (legacy gzip column
name original_csv_gzip). No unlicensed scraping or Dhan calls.

The existing context worker requests the delayed trailing hour every
five minutes during the NY 20:00-04:00 reference session plus delay.
New York daylight saving is respected. Keep QuantLab open for actual
receipt evidence. Use disable-boats to stop. Historical archive
availability assumes 20 minutes after the bar ends, more conservative
than the advertised 15-minute delay; receipt mode uses actual import
time. Old data downloaded today cannot become a historical live
receipt. Sparse ETFs must remain missing where anchors are absent.

    .venv/bin/python -m scripts.global_market_data features --date 2026-11-24 --cutoff 09:10

Features include observed-slot coverage, age, delayed session return,
and exact 30-minute-anchor return, not predictive performance. The NY
overnight session may start after Japan's cash open, particularly
during US standard time. These US-listed ETFs are not the local cash
markets and cannot establish actual Asian cash-opening returns.
No GIFT NIFTY data or five-year BOATS coverage is claimed.


## Stop expanding data: small opening benchmark

Use the existing 90-day archive and Dhan receipts, no new downloads:

    .venv/bin/python -m unittest discover -s tests -p 'test_global_open_baseline.py' -v
    .venv/bin/python -m scripts.benchmark_global_open

One 09:10 IST decision per observed date; targets are prior observed
session last minute close to current first minute open, and open to
09:30/09:45 completed minute close. Fixed 30 reserved training dates,
then 10-date expanding blocks. Compare training up-rate, domestic,
global and combined logistic baselines on paired held-out dates.
Only historical evidence available by cutoff; at least one fresh
BOATS session-return anchor is required. Missing daily/ETF values
have explicit indicators. Prior-session constituent breadth and mean
use one pinned dated membership batch, never extrapolated beyond
documented coverage. The --index-only flag provides a faster fallback
if original constituent receipts exceed the bounded read or are absent.
The report lists missing dates and observed membership coverage.
Accuracy, Brier score and log loss are exploratory, not a demonstrated
edge. Index return minus 5 bps is an illustrative cost scenario, not
executable option P&L; no gap P&L is reported. No orders, no live model.
