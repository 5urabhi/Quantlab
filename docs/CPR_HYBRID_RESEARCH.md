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
preceding observed complete 375-minute index session; gap over four calendar
days or incomplete prior session blocks the signal. This is not an authoritative
exchange-calendar reconstruction. The prior session warms the EMA; a missing
current index minute stops the later session signal clock. All comparisons share
the same fixed, nonoverlapping signal reservations, at most three per session.
This is a specific proposed rule, not a reconstruction of every discretionary
entry or CPR rejection used by the trader. Previous-day O/H/L/C distances,
CPR distances and width, direction-normalized EMA gap, time, moneyness, premium
and funding are the initial ML inputs. No invented historical OI, IV, Greeks,
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
- Missing or conflicting bars are never interpolated. Unobserved entries or
  unresolved exits halt that day's virtual account. Rejected modeled entries
  above budget are treated as hypothetical limit misses, not actual orders.
  Missing hypothetical exit observations conservatively truncate paths, so
  conditional results can be affected by missingness. Aggregate conditional
  P&L across independent day accounts is not compounded performance.

## Methods and holdout

The first 30 reserved sessions train models, next 10 select the supervised
candidate by multiclass Brier score, final 20 are untouched for final scoring.
All splits are based on dates rather than outcome quality. The supervised
labels are realized net target >=10%, loss <=-5%, or other, after the delayed
fixed-stop exit. A mark crossing is not itself a realized hit. Logistic
regression and a bounded random forest are fitted only on earlier observations.
Minimum 40 training labels across 15 sessions, at least five per class, and
10 validation labels across five sessions. The filter requires predicted target
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

Compare six methods: no-stop, fixed-stop, ML-filtered fixed-stop, offline Q
exits, ML-filtered offline Q exits, and remain in cash. Missing models are
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
