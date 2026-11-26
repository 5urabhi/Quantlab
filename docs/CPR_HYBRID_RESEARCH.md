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


## Completed-candle pattern research and fixed bank panel (v7)

Quick direction-only study (no option replay or network calls):

```bash
bash run.sh candle-research
```

It uses 60 reserved observed index sessions split chronologically 30/10/20.
For 1, 5, 15 and 30-minute trailing candles, build causal morphology from
completed original bars: signed body, wick lengths, relative range, close
location, three-candle direction, realized movement and volatility, session
range position and time. Fixed pattern flags include bullish/bearish
engulfing, lower/upper rejection, inside/outside bars, three rising/falling
candle bodies and local breakout. A missing prefix invalidates the feature;
15-minute context is explicitly masked during warmup in the CPR feature
vector. The next completed candle's body color (open-to-close) is separate
from directional return relative to the decision close. Direction labels
use a predeclared one-basis-point flat band. Pattern tables include
next-color counts, subsequent three-candle color sequence counts, directional
frequencies, and upward/downward price excursions. Multi-candle sequences
can overlap and are descriptive, not independent trades. Compare a
training-only class prior, shrunk empirical pattern/color lookup, regularized
logistic regression and shallow random forest. Select on validation
multiclass Brier score; report all later comparisons, per-day weighted
accuracy and directional coverage. These previously inspected dates remain
exploratory. The output is saved under results/candle_patterns_*.json.

Enable the independently labeled five-bank research panel in Data Centre >
Automatic data maintenance. It downloads HDFCBANK, ICICIBANK, SBIN, AXISBANK
and KOTAKBANK with the existing serialized Dhan queue and shared verified
minute files. Existing configurations migrate with this new scope OFF.
Historical CPR uses exact identities from an earlier pinned membership
manifest and can read their subsequent stock candles without asserting
that the official index membership continued. This is a fixed exploratory
watchlist selected for economic relevance, not a survivorship-free index
or an official weighted attribution. The true dated-membership study still
stops at documented coverage. Automatic maintenance retains the original
membership refresh and attempts to repair missing verified member bars;
new membership evidence remains necessary for later true constituents.
Enable index and options maintenance, set wings to 5, and approve the
desired recurring scopes. The duplicate POST maintenance route is resolved;
legacy bodyless derived-only repair remains compatible.

Global Markets > Configure automatic source collection now includes opt-in
Alpaca daily and optional five-minute US ETF proxies, plus existing FRED,
Twelve Data and announcements. Existing settings migrate with Alpaca OFF.
Select the same entitled IEX/SIP feed already used for the factor archive;
changing provider identity is not silently accepted. Completed five-minute
bars use actual receipt timestamps and a separate factor identity. During
Indian trading hours, US ETFs may have no trades or be stale; they are
not actual global futures, Asian exchange or GIFT NIFTY intraday feeds.
Those still require reviewed entitled sources. The worker runs while the
app is open, never submits orders, and does not backdate recent receipts.

Run a fast matching context audit after panel acquisition:

```bash
bash run.sh cpr-context-check --fixed-panel --hold 0
```

Full additional comparisons:

```bash
bash run.sh cpr-research --entry-mode regime_scan --hold 0 --frame 5 \
    --risk-budget 12000 --wings 5 --context-mode archive --rank-entries \
    --patterns --fixed-panel --context-q --debit-spreads
```

The INR 12,000 exposure is a historical paper diagnostic, not a live
recommendation. Pattern, global+pattern, true constituent+global+pattern,
fixed-bank panel and panel+global(+pattern) scopes compare augmented ML to
the technical baseline on matched eligible observations. A direction-only
5-minute candle forecast is selected using development data, then used
only on later CPR signals as an additional rule; it requires at least 55%
probability in the signal direction and a 10 percentage point advantage
over the opposite direction. The prior-only model cannot approve entries.
Option-outcome ML receives raw completed-candle features, not in-sample
index predictions. Earlier-only contextual Q uses a compact frozen
entry-time agreement/mixed/conflict regime from the requested observed
scope, plus the existing dynamic P&L/time/trend/drawdown state. Compare
against technical Q fitted on the same earlier scope rows; missing or
unsupported Q states fall back to the fixed stop/target. This does not
continuously update global/constituent state during the position.
ML validation now also requires no exits after 15:20 and at most two
minutes of modeled exit delay; a previously recovered 108-minute exit
is not acceptable promotion evidence.

Debit-spread comparators pair the same observed rolling expiry family and
side using a lower-strike long CALL/higher-strike short CALL or the reverse
for PUT. Only same-minute, positive-volume, price-consistent observations
are used. Use deterministic signal-time selection, modeled Zerodha fees
for both legs, and original delayed-exit and square-off control. Compare
gross-long funding plus fees with a separately labeled counterfactual
net-debit-plus-fees budget. Neither verifies broker margin, exact expiry
identity, synchronous executable quotes, legging risk or fills. A
net-debit-affordable pair can still require far more capital at the
broker. Recover missing exit evidence only at the first later valid
paired open in the same session. Keep this in paper research.

No additional data source, price, or result is synthesized. These are
experimental policies, not live deployment approval. Freeze policy and
reserve new prospective sessions before making an independent claim;
the existing rolling historical results are exploratory.


## Expanded sequence and first-passage research (v8)

Start with the index-only statistical study; no option replay or provider
downloads are required. The default 60 sessions remain reproducible.
Choose 90 or 120 only if that many original observed sessions are saved.

```bash
bash run.sh candle-research --sessions 90 --first-passage \
    --context-mode archive --fixed-panel
```

Chronological splits are 30/10/20, 45/15/30 or 60/20/40, over at most
200 calendar days. Missing dates are never synthesized. A fixed clock
reserves nonoverlapping 5/15/30-minute outcome windows within each session.
The feature set includes trailing 3/5/10/20 completed five-minute candles,
signed returns, sequence efficiency, range expansion, prior-high/low
distance, momentum acceleration/deceleration and volatility. Short
histories use explicit masks. Inputs are computed before future labels;
no missing bar is forward-filled. Long windows are warmup-limited.

For symmetric index barriers 25/50/100/200 points, first touch has four
classes: upper first, lower first, neither, ambiguous. If a minute opens
outside a barrier, its open establishes the observed first touch. Both
touches inside a single minute with open between the barriers are
ambiguous. Missing path bars censor the full outcome. The terminal
movement target is distinct (down at least the threshold, within band,
up at least the threshold). Class priors and shallow multi-output random
forests are trained on earlier sessions; choose each forecast using
validation Brier, report later Brier and accuracy. Compare shorter
pattern features with sequences, then sequences with global changes
and ages, all five banks' completed 5/15/30m returns, relative volume
and index divergence, or both. Exact matched rows for each ablation.
Individual bank targets are next 5/15/30m direction and relative
performance against BANKNIFTY, using a fixed +/-1bp band and complete
same-identity future paths. If the panel source hash changes during the
run, do not compare those targets. The bank panel is not official index
membership. Report session-block bootstrap differences, not independent
minute-level confidence or multiplicity-adjusted significance.

The CLI saves results/candle_barriers_*.json; open Market Intelligence >
Market Overview > Saved candle sequences & first-passage research to
view the latest saved study. This is a collapsed read-only results panel
in the existing React UI, not a live forecast or new application.

Then compare the expanded option inputs, keeping existing paper-only
budget and delayed-open rules:

```bash
bash run.sh cpr-research --entry-mode regime_scan --hold 0 --frame 5 \
    --sessions 90 --dense-training --risk-budget 12000 --wings 5 \
    --context-mode archive --rank-entries --patterns --fixed-panel \
    --sequences --derivatives --context-q --dynamic-q
```

With insufficient data, use --sessions 60 rather than silently claiming
the larger experiment. The dense sampler takes the earliest qualifying
earlier scanner opportunity in each 15-minute bin (no future
availability or outcome selection). It permits overlapping training
trajectories; weight by session, then anchor, then strike; Q aggregation
also weights by step within each trajectory. Preaggregate dense Q
Bellman contributions to avoid repeating the transition scan. Validation
and holdout trading still enforce the same nonoverlapping account
positions and risk controls. Do not interpret more correlated anchors
or strikes as more independent days.

Sequences and original rolling option OI, raw provider IV and relative
volume are separate matched ML ablations. Optional values missing or
inconsistent across duplicate source receipts remain masked. Five-minute
OI and IV changes compare the same observed side/strike/family; raw IV
units are not assumed to be decimals or percentages. No new option
provider calls. The dynamic Q comparator uses neutral fixed-bank and
as-of global state combined with the most recently completed five-minute
index move, aligned to option direction. It refreshes at each completed
five-minute clock, never backdates a later state; missing or unsupported
states fall back to the fixed target/stop. This is a retrospective
contextual Q ablation on the same earlier learning trajectories, not a
live controller. The ordinary Q comparator and frozen-entry context Q
are retained. Funding sensitivity is a descriptive count of observed
signal-time minimum funding versus hypothetical budgets, not a
recommendation to increase risk, verified broker margin or fill coverage.

The 60-session rolling study has already been inspected. Larger
historical windows do not create independent confirmation of repeatedly
examined dates. Reserve new sessions before any policy promotion. No
changes to current order permissions, no synthetic missing prices,
and no guarantees of profitability. Debit spreads remain optional
and are omitted from the example due to their negative earlier results.


## Volatility regimes, direct utility and forward reservation (v9)

Run the regime study separately from expensive option replay:

```bash
bash run.sh candle-research --sessions 90 --regimes \
    --context-mode archive --fixed-panel
```

This retains original completed index and stock receipts. It measures
5/30-minute RMS returns in basis points, path efficiency, shorter
opposing returns, relative range, and the prior 20 sessions' same-clock
median RMS (requires at least five earlier observations; otherwise an
explicit missing mask). Fixed observed regime labels are up/down trend,
up/down reversal candidate and range. They are descriptive past-state
heuristics, not labels for a future direction. Volatility state is
expanded/compressed/normal. Future RMS is expansion above 1.25 times
the trailing 30-minute RMS, contraction below 0.8, otherwise stable.
The training-only prior, shrunk regime lookup, shrunk regime+pattern
lookup and shallow multioutput forest compete on validation Brier.

Normalized price barriers are 0.75, 1.5 and 3 times the decision-time
index point scale: spot times trailing 30-minute one-minute RMS in
return units times square root of horizon, with a 0.05 bp RMS floor and
one-point scale floor. This is a scaling heuristic, not a Brownian
assumption or guarantee of barrier crossing. Future outcomes never
change the barrier. Missing path bars censor the target; within-minute
order ambiguity remains a separate class. Compare the bank-augmented
forest on identical rows. A separate ridge experiment predicts future
index return from lagged HDFC/ICICI 5/15/30m returns and the same index
regime inputs. Select ridge penalty on earlier development dates.
Report matched day-block error differences, not causal attribution.
All existing fixed-point and individual bank target studies remain
available. New reports are saved as results/candle_regimes_*.json.

For direct expected net return and execution-risk research:

```bash
bash run.sh cpr-research --entry-mode regime_scan --hold 0 --frame 5 \
    --sessions 90 --dense-training --risk-budget 12000 --wings 5 \
    --context-mode archive --rank-entries --fixed-panel --regimes \
    --utility-research --freeze-utility
```

Previous options studies can still opt into --patterns, --sequences,
--derivatives, --context-q and --dynamic-q; these are not required for
this focused comparison. The direct model compares technical inputs
plus decision-time observation quality with the same inputs plus regime
features. It fits conditional timely net return per planned funding,
execution failure, first observed fixed target/stop/other/unverified
trigger, and an adverse stress utility on earlier trajectories. Trigger
order is evaluated at observed marks, not intraminute price order.
The direct candidate gate requires at least 8/10 recent same-strike
observations and the last three all observed, positive predicted timely
net return and expected stress utility, predicted failure <=10%, and
positive 20th percentile of stress-forest tree estimates. The tree
disagreement statistic is not a calibrated confidence interval.
Only planned affordable candidates are ranked; future fill availability
cannot enter features or ranking.

Missing entries/exits, monitoring-gap exits even if promptly recovered,
late square-off and exits delayed more than two minutes are explicitly
unacceptable execution observations. The strict account lane halts that
session after such a failure. Keep recovered prices and realized proxy
net separate from stress accounting. An unresolved attempted position
or unacceptable recovered exit incurs a full planned-funding loss
scenario (or the larger observed loss); this is deliberately adverse,
not a certified loss bound or actual charge. Candidate-level model
targets also penalize non-timely funding failures; the account lane
does not charge an ordinary rejected funding attempt as a realized loss.
Report conditional proxy P&L and stress utility separately. Earlier-only
session weighting remains. Weighted logistic features use a centered
two-pass finite scaler to avoid cancellation on nearly constant
context columns. No warning suppression.

Choose a utility threshold only on development dates with >=10 timely
scored trades across >=5 days, positive stress utility, no unresolved
trades, no monitoring-gap/late exits, no delayed exits beyond two
minutes. An unsuccessful gate abstains. Never tune on the holdout.

Explicit --freeze-utility exports only the predesignated regime utility
lane if its development gate passes. The numeric tree arrays are
serialized as JSON (not pickle) with code hashes, source digest, fixed
threshold, settings and a 45-calendar-day reservation beginning strictly
after both the freeze date in IST and the previously examined sessions.
A blocked gate creates no policy. The local hash is an integrity check,
not an externally attested timestamp. After the reservation ends:

```bash
bash run.sh cpr-research --forward-utility results/utility_forward_<sha256>.json
```

Only the frozen reservation/settings are used. No model fitting,
changing the date window, or early scoring. The forward report is
created once under its policy digest. Missing weekdays are explicitly
reported (not verified as market holidays); source corrections, rolling
contract identity, actual receipt chronology and execution remain
limitations. This is a fixed later-date replay of frozen parameters,
not a genuine recorded live paper order stream. No strategy is
automatically promoted, and no execution permission is granted. These
research updates do not modify the React workstation layout.


## Execution evidence and matched horizon screen (v1)

One local command runs the CPR regression suite followed by the new
saved-source audit and development study:

```bash
bash run.sh cpr-next --sessions 90
```

An exact 60, 90 or 120 observed-session split is required. It does not
rerun the already inspected later dates for new strategy selection.
Results are saved under results/cpr_execution_evidence_*.json. The
request audit checks all observed dates (including no-signal sessions)
and both sides. A checked receipt may be empty; it establishes only
request coverage. A separate quote inventory reports observed minute
slots, positive, zero and missing volume. For chosen fixed-strike
entry/exit failures report conflicts, missing side or strike rows,
observed strike range, zero/unknown volume, receipt-window status,
and whether the index bar was observed. The training probe uses the
earlier dense anchors and up to eleven one-lot candidates; validation
and recent data-quality probes use account-affordable nearest
candidates. These are not actual order fills or independent trades.
Missing bars outside the observed strike range may reflect rolling
window truncation, not proof of a particular cause. No synthetic
quotes, forward filling or deletion of verified receipts.

Existing authorized automatic data maintenance prioritizes missing
expired option request windows intersecting saved observed BANKNIFTY
sessions. Other dates remain in scope; no inference of holidays from
absent data. Checked/empty receipts are not automatically overwritten.
The audit command itself makes no provider requests and does not
start, stop or change the recorder or maintenance settings.

On training and validation dates only, compare five predetermined
holding limits (5/15/30/60 minutes and mandatory 15:20 IST square-off)
using a common signal clock with at least 60 minutes remaining.
Use the same selected strike and one assumed 30-unit lot at 35 and
75 bps adverse premium penalty per side, selecting affordable
candidates under the higher cost assumption. Actual delayed price
proxies and modeled fees still vary with the cost lane. Retain the
existing fixed 10% target/5% stop and strict session halt after
unresolved or unacceptable execution observations. Keep realized
proxy P&L and deliberately adverse full-funding stress separate.
Same capital 17,000 INR, exposure and gross-loss budget 12,000 INR;
not a recommendation to increase capital or risk. A development
hypothesis requires positive earlier stress with no stress failures
and the previous strict validation gate at both costs. No selection
on already examined recent dates, no new policy freeze or promotion.
Positive minute volume is not proof of fill, exact listed contract,
or historical bid/ask. Results do not guarantee live returns.


## Original option receipt repair and exact live identities

With the local workstation stopped normally during off-market priority
hours, use:

```bash
bash run.sh cpr-repair --sessions 90
```

Runs CPR, history-sync, maintenance and full-feed regression tests; loads
only the local ignored .env; requires existing opted-in read-only options
maintenance and authenticated Dhan access. Fills missing verified
near-month request windows for the actual observed study dates, up to 440
core requests per invocation. Prioritize observed sessions and ATM +/-5
before wider offsets. The new process lock coordinates updated backend
and CLI history-sync writers. An already running old backend may not
honor it, so the standalone command refuses to run while the usual
local API port is occupied. It never terminates the recorder.

Dhan's v2 expired-options documentation describes up to ATM +/-10
for near-expiry index options. Test both signs and sides at each width
6 through 10 on one already expired observed session. Only observed
positive-volume rows support the incremental width. A rejected or empty
response cannot establish coverage; a verified receipt is never
overwritten. A supported wider scope gets up to 112 additional requests
and the already authorized maintenance scope can expand to that width.
No claim that the probe proves wider availability on all dates. Bounded
passes are resumable; ordinary authorized maintenance fills remaining
request windows outside priority hours. Read-only audit retains the
ATM +/-5 comparison and, when wider observations were verified, a
separate wider audit. No unseen date is treated as a market holiday.

The existing full-universe Dhan quote/OI feed now preserves each
subscription session's exact master identity, expiry, strike, side
and lot size in the existing SQLite database. Reordering by distance
to ATM no longer causes unnecessary reconnects. Existing valid IDs
take priority if subscription capacity binds. No new socket or change
to the live packet mode. Existing REST chain bid/ask and rotating
depth recorders remain enabled according to their previous consent.
New chain snapshots also record REST request duration. The saved-data
audit reports bounded exact-mapping coverage, bid/ask spread per lot,
source trade age at receipt and measured REST round-trip time. Legacy
unmapped records remain explicitly unmapped. These are not actual
order latency, fill prices, continuous per-contract books or execution
certification. No orders are transmitted. New live mapping/duration
fields begin on the next normal workstation start and market session.


### Productive maintenance cadence

The opted-in background maintenance worker schedules another bounded pass
two minutes after a successful partial pass if new option receipts were
saved with requests remaining, unattempted eligible bank-session repairs
remain, or index windows were downloaded with uncovered windows remaining.
The existing per-pass caps (112 option requests and two equity repair
dates per instrument), serialized queue, provider pacing, seven-day
per-date repair cooldown, storage guard and Indian market priority window
remain unchanged. Provider errors, unreadable receipts, blocked sources or
no immediately actionable work retain the ordinary four-hour backoff;
checked scopes retain the 24-hour interval. Legacy productive checkpoints
resume promptly without requiring a manual check. The maintenance card
and status API expose the retry reason. A gap may remain despite a
successful original-source request; no prices or membership are inferred.
