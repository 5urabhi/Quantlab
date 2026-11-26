# CPR / EMA options research: baseline, ML, offline RL

This is an offline research entry point, not an execution system. Start with:

```bash
bash run.sh cpr-research
```

The command reads the original shared BANKNIFTY one-minute receipts and verified
Dhan rolling near-monthly option receipts. It never calls a data provider, uses
a brokerage login or submits orders. Run outside weekday 08:30–16:00 IST.
The default range is the last 100 calendar days, end exclusive, and the most
recent 60 observed index sessions within it are reserved regardless of option
coverage. A shorter range runs only descriptive rule-based comparisons.

The default is a five-minute EMA 9/21 crossover with price above the upper CPR
for calls or below the lower CPR for puts. CPR and OHLC are calculated from the
preceding weekday's complete 375-minute index session. Missing weekdays block
the signal, including unverified exchange holidays; special weekend sessions
are excluded. This is deliberately conservative, not an authoritative exchange
calendar. The prior session warms the EMA; a missing
current index minute stops the later session signal clock. All account comparisons share
the same fixed, nonoverlapping crossover reservations, at most three per session.
This is a specific proposed rule, not a reconstruction of every discretionary
entry or CPR rejection used by the trader. Previous-day O/H/L/C distances,
CPR distances and width, direction-normalized EMA gap, time, moneyness, premium
funding normalized to a fixed INR 17,000 reference (independent of account budget),
and a fresh-crossover flag are the initial ML inputs. No invented historical OI, IV, Greeks,
constituent weights, global signals or order-book prices are used.

## Explicit assumptions

- INR 17,000 paper capital per independent daily account. Default INR 4,250
  full premium-plus-fee exposure and gross realized daily loss allowance.
  Reserve against remaining cash and loss allowance. There is no leverage.
- Assume 30 units per historical lot; never claim exchange-verified lot size.
  Choose closest affordable strike inside 1.5% moneyness; prefer the smallest
  affordable lot count, and never switch strike based on later availability.
- Buy at the open one full minute after the decision (two minutes after the
  signal bar begins); exits follow the same completed-mark/delayed-open rule.
  Model adverse premium costs of 35 bps per side by default and current
  estimated Zerodha charges. Neither the spread nor fills are observed.
- Take profit at a 10% net mark; fixed stop at a -5% net mark. An exit may
  realize a different return. The learned exit cannot override the target,
  stop or time cap. Default maximum holding period 60 minutes; no overnight.
  No-stop is only a research comparator, with the same full-premium exposure
  budget and same time cap, not a proposed deployment policy.
- Missing or conflicting bars are never interpolated. Missing hypothetical exit
  prices do not prevent holding; a chosen exit without an observed delayed
  open censors the position. Missing mark bars truncate the path. Unobserved entries or
  unresolved exits halt that day's virtual account. Rejected modeled entries
  above budget are treated as hypothetical limit misses, not actual orders.
  Full-path Q training requires all hypothetical exits to be observable, so
  conditional results can be affected by missingness. Aggregate conditional
  P&L across independent day accounts is not compounded performance.

## Separate learning data from the trading account

The earlier 30 training sessions reserve the original crossovers plus a fixed
nonoverlapping grid of CPR/EMA-aligned continuation windows. A crossover and
grid window at the same timestamp are deduplicated; the two calendars can
otherwise overlap. At each learning anchor, use at most five nearest qualifying
strikes with one hypothetical lot, **regardless of account affordability**.
The 10 validation sessions use only the original crossover signals, but may
also include up to five strikes. No holdout rows enter fitting or selection.
ML uses anchor-balanced weights; Q averages within strike trajectory then
within anchor, and support counts distinct anchors and days. Correlated strikes
and overlapping windows are not independent market sessions. This expansion
may improve sample support but does not guarantee sufficient usable observations
or transfer to the original crossover distribution.

For account evaluation, retain the chosen affordable single contract at the
original crossover, the explicit full-premium exposure allowance, and remaining
cash and daily loss allowance gates. Distinguish missing observed signal quotes,
no qualifying observed contract and no affordable qualifying contract.
The report shows learning support and trading support separately.

## Methods and holdout

The first 30 reserved sessions train models, next 10 select the supervised
candidate by multiclass Brier score, final 20 are untouched for final scoring.
All splits are based on dates rather than outcome quality. The supervised
labels are realized net target >=10%, loss <=-5%, or other, after the delayed
fixed-stop exit. A mark crossing is not itself a realized hit. Logistic
regression and a bounded random forest are fitted only on earlier observations.
Minimum 40 training labels across 20 distinct anchors and 15 sessions, at
least five distinct anchors per class, and 10 distinct validation anchors across
five sessions. Model selection uses anchor-weighted validation Brier scores. The filter requires predicted target
probability >=0.50 and positive train-class-weighted expected return. These
thresholds are research assumptions, not optimized after looking at test data.

Offline fitted tabular Q iteration uses earlier fully observed paths. It
compares hold and exit, using realized net return as terminal reward. States
bin marked P&L, elapsed time, direction-adjusted index trend and drawdown.
20 deterministic Bellman sweeps; at least five distinct training episodes and
three training sessions per state. Unsupported/tied states use the fixed rule.
Complete-path training is potentially selective and actions are simulated under
a small price-taking assumption. This is not deep RL, a live exploration agent
or proof of optimal action. Model selection and action bins are fixed before
holdout. A Q digest, source digests and split support are retained.

Compare ten methods: no-stop, fixed-stop, ML-filtered fixed-stop, offline Q
exits, ML-filtered offline Q exits, fixed 15% emergency stop, Q exits with the
same 15% emergency stop, two profit-activated trailing-stop comparators (5% and 15% initial stops), and remain in cash. The wider pair isolates learned
exits from simply giving positions more room. Both force the 10% net target
and the time cap. Wider stops are exploratory paper assumptions, not loss caps.
The previously viewed 60-session window is now exploratory; reserve later
unseen sessions for independent confirmation. Missing models are
reported as insufficient support, not silently replaced with profitable
outcomes. Holdout metrics include observable ML Brier score, conditional net
P&L, costs, target hits, wins, daily drawdown and unresolved entries/exits.
No-trade is a zero-return benchmark; the other methods with no scored trades
have null P&L. No empirical promotion, actual execution, margin or profitability
is certified.

The JSON report under `results/cpr_hybrid_*.json` includes the stage report,
trade/abstention journal and original source checksums. Default parameters
can be varied as **separate exploratory** studies, e.g.:

```bash
bash run.sh cpr-research --frame 3 --hold 30
bash run.sh cpr-research --risk-budget 9000
```

The larger exposure is a paper-only sensitivity, not recommended risk. Do not
select the best holdout settings and re-label that same holdout independent.
When data are insufficient, use the existing Data Manager to inspect and
complete historical coverage. Future work: verified constituent/context
features, exact-contract receipt execution, prospective frozen-model tests,
and a separate entry/exit MDP. No changes to existing scalping/spread engines.


## Profit-activated trailing comparators (v3)

Both trailing comparators retain the 10% net target, identical entry
selection, account exposure, execution delay and time cap. Before a
completed net return mark reaches +3%, retain the initial -5% or -15%
stop mark, respectively. Once activated, the floor is the greater of
the initial stop mark and the highest completed net mark minus three
percentage points. The floor never decreases. The fixed target, initial
stop and timeout take precedence; otherwise an observed mark at or
below the floor triggers a delayed exit. Example: a peak net mark of
+8% produces a +5% floor. This is not a promised fill or profit:
missing exit evidence censors the trade, and a delayed observed open can
realize less than the floor, including a loss.

The activation and distance are fixed illustrative research assumptions,
not selected from test outcomes. Trailing is a rule-based comparator, not
a newly trained RL policy. Existing RL policies are unchanged. The report
adds exit-reason counts and sampled open-position minimum/maximum returns
and peak-to-mark drawdown through each exit decision, including censored
paths. Closed-account drawdown alone can hide large temporary losses.
These are completed-mark diagnostics, not intrabar or fill-time extrema.


## Daily opportunity scanner (v4)

The original crossover mode remains the default, so existing reports and
comparisons can be reproduced. Run the expanded mode separately:

```bash
bash run.sh cpr-research --entry-mode daily_scan --frame 5 --hold 60 --risk-budget 12000
```

This is a paper-only sensitivity with a larger full-premium exposure allowance;
it is not a recommendation to risk INR 12,000. Scan fresh confirmed crossovers
and scheduled 15-minute checkpoints using completed index candles. At a
checkpoint, an aligned EMA direction outside CPR qualifies for further
evaluation; classify the opportunity using the following precedence:
fresh crossover, previous-day high/low breakout, CPR retest, CPR breakout,
opening-range breakout (first 15 minutes, observed only after completion), or
trend continuation. These are deterministic candidate labels, not proven edges.
No trade is forced inside CPR, without appropriate quotes, or when risk or
model gates reject the candidate.

Earlier training uses the same original nonoverlapping crossover and fixed
continuation learning grid as v3. The daily scanner uses its own validation
candidate distribution; multiple strikes and overlapping windows are correlated.
Account evaluation processes opportunities chronologically, skips decisions
while a previous position is open through the delayed exit timestamp, limits
attempted entries to three per session, and halts the day on unresolved entry
or exit evidence. Daily coverage distinguishes reserved days, opportunities,
affordable observed candidate paths, attempted entries, modeled entered
positions and scored exits. A candidate path may be affordable yet never
entered by the actual policy; a censored position is not a scored trade.
The full JSON includes per-session counts even on zero-opportunity days.
This is not a guarantee of daily trades or profitability. The previous
evaluation dates have already been viewed, so compare exploratory outcomes
and reserve fresh independent sessions for confirmation.


## Context, ranked entries and adaptive exits (v5)

Run the additional comparison in one command:

```bash
bash run.sh cpr-research --entry-mode regime_scan --frame 5 --hold 60 \
    --risk-budget 12000 --wings 5 --context-mode archive --rank-entries
```

This is retrospective paper research. The INR 12,000 allowance is not a
recommended live risk setting. Use `--context-mode receipt` for evidence
known at actual import time; archive mode trusts reviewed historical
availability dates and is not prospective verification. `--context-mode off
--rank-entries` tests technical ranking without optional context. Existing
crossover and daily_scan modes remain available. Wider wings read already
saved verified near-monthly BANKNIFTY receipts only; use Data Manager's
existing option-history sync for missing eligible wings. No API calls are
made by this study. Exact-contract fills, lot size and bid/ask remain
unverified. NIFTY option history is not wired into this BANKNIFTY-specific
receipt loader.

Constituents: automatically select the dated BANKNIFTY one-minute batch with
the greatest manifest date overlap (or pass its ID using
`--context-batch ID`). Read original hashed files and pinned membership;
require 16 consecutive completed bars for every member. Include
direction-normalized 5/15-minute momentum, breadth, dispersion, signed
relative volume against at least five earlier same-time observations,
and HDFCBANK/ICICIBANK/SBIN momentum when they were members. Weighted
features require an earlier verified weight snapshot; unweighted breadth
is never described as official index attribution. A missing member
blocks that context scope, not the original technical baseline.

Global: use the shared market-context store and existing availability
timeline. S&P/Nasdaq/US bank, Asian equities, GIFT NIFTY, USD/INR,
VIX, oil, yields, and available participant inputs are represented by
observed changes, age, appropriate stable levels and missing indicators.
Require evidence from all three global-equity/Asia/macro groups. No
same-day US close or later report can be used before its documented
availability; ambiguous sources are excluded. Context-rule comparators
require positive directional bank breadth (at least one-third net),
5/15-minute momentum and weighted confirmation if weights are verified;
global rules require aligned mean observed equity and Asian returns.
These rules are hypotheses, not causal estimates of market influence.

For each of technical, constituent, global and combined scopes, compare
matched technical and augmented ML models on the same available
observations; also compare context rules against the same matched
fixed-stop benchmark. Training is earlier-only. Candidate models,
temperature, prior-shift shrinkage and entry probability thresholds
are all tuned on the development validation split; this is not an
independent calibration experiment. Compare predictive Brier score
against a smoothed training class prior on matched nearest-contract
evaluation observations. Threshold selection uses sequential validation
accounts: at least five completed trades over three days, no unresolved
entries or exits, and positive modeled net P&L. If none passes, abstain.
Candidate ranking is by expected net position return derived from
calibrated class probabilities and train-only class-average returns,
with target probability and moneyness as deterministic ties. Select
from signal-time affordable single lots without filtering on future
fill/exit availability. If the chosen entry/exit is missing, censor it;
never replace it using hindsight. A later remaining-budget rejection
does not re-rank against the smaller budget. Compare fixed, trailing
and the existing frozen technical Q exit policy. Global/constituent
inputs affect entry decisions; the Q state itself is not augmented.
Prediction labels still correspond to fixed-stop net outcomes, not
trailing or Q policy outcomes.

The regime_scan mode adds exploratory completed-bar CPR rejection
inside the band when EMA separation is <=5 bps; ambiguous both-edge
touches abstain. The volatility-trailing comparator uses the standard
3% activation and a 2–6 percentage-point gap based on twice the
dispersion of the five most recent completed mark changes, defaulting
to 3 points until enough marks are available. Its stop floor can only
ratchet upward. Every strategy remains subject to execution delay,
position exposure, time cap, and sequential-account restrictions.
No parameter is approved for live orders. Prior evaluation dates
have already been inspected; fresh forward dates are needed before
claiming any improvement. Report stores context source metadata,
timestamped factor evidence, coverage, validation gates and scoped
results. Context missingness or absent usable training labels is an
explicit blocker, not synthesized evidence.


## Context data readiness and historical recovery

Run the local context-only preflight before another expensive option replay:

```bash
bash run.sh cpr-context-check
```

It verifies original index bars, checks the same recent 60-session regime
scanner, and reports candidate membership manifests, explicit local
validation failures, mapped symbols, verified source digests, available
sessions per symbol, missing member counts, global inventory by receipt
mode and date range, and train/validation/evaluation context coverage.
It makes no provider requests by default.

CPR may now read a bounded slice of a longer pinned BANKNIFTY membership
batch, including up to 35 days of volume warmup. It still validates the
original membership hash and exact security mapping and respects the
pinned covered-through date. Other historical studies retain their
original 240-day whole-batch guard. Auto selection tries remaining
overlapping manifests if a higher-ranked one fails validation; it never
chooses on model outcomes. Missing member bars remain blockers. Original
files and manifests are not changed.

If authorized to use FRED/ALFRED, set FRED_API_KEY in the existing ignored
local .env (never paste it into chat, a report, or a committed file). Then
run outside Indian market priority hours:

```bash
bash run.sh cpr-context-check --fetch-fred --confirm-reviewed
```

The command uses the existing fixed FRED endpoints and seven reviewed
series mappings, requests bounded historical real-time periods, retains
original payloads in the canonical context store, and marks imports as
archive only. The real-time-period date is **not** an exact publication
timestamp; use noon UTC on the next day as a conservative availability
assumption. This deliberately sacrifices freshness to avoid same-day
lookahead. It neither invents historical GIFT NIFTY prices nor backdates
live receipts. See FRED's real-time-period and series observations API
documentation. Provider permissions, vintage availability, data access
and coverage remain local acceptance requirements. If no FRED key or
eligible rows exist, report that explicitly. Conflicting source identities
are not overwritten.

Enable reviewed automatic context feeds in Global Markets for future
receipt-time observations. FRED is only a daily context subset, not the
complete global market, participant, or intraday futures universe.


## Source recovery and 15:20 IST square-off (v6)

The FRED archive loader classifies HTTP 400 responses without logging raw
provider text or secrets. It attempts real-time-period history, then a
bounded period, then initial-release-only history where supported. It
does not substitute today's revised observations into historical
availability. Failed factors remain unavailable. Existing successful
imports are preserved.

An optional independent Alpaca source provides daily raw US-listed ETF
proxy series (SPY, QQQ, KBE, EWJ, FXI, TLT, GLD). EWJ/FXI are US-traded
Japan/China exposure proxies, not actual Asian exchange indices or
intraday feeds. TLT is a bond-price proxy, not a Treasury yield. Each
series has a distinct factor identity and explicit IEX or SIP source.
The global feature schema is versioned; older contextual models must
not be reused with a different input schema.

Use local ignored .env credentials:
```text
APCA_API_KEY_ID=...
APCA_API_SECRET_KEY=...
```

Then, after reviewing the source terms and archive assumptions:
```bash
bash run.sh cpr-context-check --fetch-fred --fetch-alpaca --confirm-reviewed
```
The default Alpaca feed is IEX; select `--alpaca-feed sip` only if
entitled and before creating a series with IEX identity. No trading
endpoint is used. Daily proxy timestamps are New York midnight;
availability is assumed no earlier than 00:15 New York time on the
following day. This is deliberately conservative retrospective evidence,
not provider-vintage proof; raw historical bars may be corrected later.
Unfinished days and incomplete response pages are rejected or excluded.
Missing observations are not generated.

The preflight also reports the locally documented membership source's
coverage date. If the chosen BANKNIFTY batch ends before the validation
or holdout period, refresh the dated membership source and run existing
automatic market-library maintenance with index and constituents enabled,
outside Indian market priority hours. It reuses checked Dhan caches and
does not extend membership beyond documented coverage. A stale provider
membership reconstruction remains a blocker even after price downloads.

All CPR paper strategies now have a hard scheduled square-off at
15:20 IST. A 60-minute policy must fit before that cutoff. Use
`--hold 0` for the separate session-hold experiment: no fixed duration,
minimum 15 minutes reserved before square-off, normal target and policy
stops still active. The no-stop comparator may hold until target or
square-off. Missing monitoring bars trigger a conservative exit request;
a missing requested exit open retries the first later observed open
of the same strike/side/expiry family through 15:29 IST only. This is
a conditional proxy for a pending exit, not evidence of actual broker
execution. Never choose a better later price, use a different strike,
or carry to the next session. A missing entry remains unverified; if
all later same-session exit observations are unavailable, the exit
remains censored. Q fitting continues to require complete original
decision and exact delayed-open trajectories. Reports separate unverified
entries/exits, recovered delayed exits, max delay and exits after 15:20.
The strategy is still paper-only and no live broker square-off is certified.
