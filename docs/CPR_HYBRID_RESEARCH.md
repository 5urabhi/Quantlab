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
