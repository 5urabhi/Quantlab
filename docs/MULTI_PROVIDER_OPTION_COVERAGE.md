# Multi-provider option coverage — Dhan, Zerodha, Upstox

**Status:** Software support added. Actual access requires authorized accounts and provider entitlements; no live vendor request is made in CI. QuantLab never sends trading orders.

## Scope

**Trading → Option Chain** now displays a multi-provider source inventory. Choose BANKNIFTY or NIFTY 50, select the source (**all connected**, **Dhan only**, **Upstox only**), then choose any *original provider-reported active expiry*. The table contains every CE and PE strike returned by each approved source for that expiry, not just the nearest 5/10/100 strikes. The existing premium-range filter is opt-in.

- **Dhan:** Existing original current BANKNIFTY expiry list and option-chain snapshots, plus independently configured 20-bid/20-ask WebSocket and background BANKNIFTY expiry collector. Source packets are not faked or backfilled. An original Dhan master must be recent to permit exact NSE_FNO depth selection and validated lot calculations.
- **Upstox (optional):** Read-only v2 `GET /option/contract` and `GET /option/chain`, supporting **BANKNIFTY** and **NIFTY 50**. A manually issued OAuth token from an Upstox developer account is pasted into the local UI and stored in `data/research_workspace/upstox/read_only_token.json` with POSIX 0600 permissions. No token is ever returned, written to browser localStorage or logged. A local `UPSTOX_ACCESS_TOKEN` environment variable can be used instead. Token presence is not session verification; the next explicit expiry request tests access.
- **Zerodha Kite:** Shown as a connected data source only when its existing local equity-history fallback login is present. **It does not pretend to be an option-chain quote provider.** Kite supports option contract discovery and batched quotes independently; adapting its broader F&O master and quote API is a distinct task, not silently enabled by the existing equity-only fallback.

## No silent quote stitching

A row is identified by index, expiry date, strike and CE/PE. When both providers return the same row, the **Dhan quote** is preferred; its bid and ask come from the same Dhan snapshot. A valid Upstox quote is used in place of a failed Dhan bid/ask only when **both exact NSE exchange token + current Dhan master + expiry/strike/side + lot size** verify the *same* security. The resulting row is labeled with its quote provider, available alternatives and local received timestamp. Contradictory verified IDs are counted and blocked from cross-source promotion.

Source availability, quote freshness and provider errors are displayed. The aggregated display is not an exchange NBBO or executable fill. Upstox-only contracts with unverified Dhan depth identity are **visible, but not selectable for the Dhan 20-level stream or lot-based trade preview**. NIFTY 50 Upstox is currently discovery/quote-view only, pending independent Dhan master reconciliation.

## Current vs historical options

This workflow expands **current** option-chain visibility only. It cannot reconstruct historical 20-level order books or earlier option bid/ask prices. Upstox documents separate expired instrument contract and candle endpoints, potentially requiring a qualifying plan. Access and availability must be proven against the authorized local account before using it for historical CE/PE option-P&L backtesting.

## Operational safeguards

1. Manual opt-in to save credentials under private local storage. Only fixed official Upstox hosts and two allowlisted GET paths are reachable. Response bodies are bounded, redirects are blocked and network/auth errors are sanitized.
2. Contracts must match an original Upstox catalog row and the same underlying/expiry/strike/side. Exchange ID and lot-size tradeable status require exact corroboration by a current Dhan master.
3. Existing Dhan recorder permissions, cadence, historical capture, and source schema are untouched. New Upstox quote browsing does not auto-start live capture or place broker orders.
4. Cache option contracts for 5 minutes and Upstox chains for 20 seconds to limit provider load; the existing Dhan rate limiter remains active.
5. No additional original-data repairs, backfill claims, or broker order capability are included.

## Local test

After merged CI passes:

```bash
cd ~/Desktop/codes/quantlab
git pull --ff-only origin main
bash run.sh
```

Open **Trading → Option Chain**. Inspect Dhan and Zerodha configuration badges, use **Connect Upstox** if you have an authorized token, and select **All connected · Dhan preferred**. Confirm that every original listed expiry and strike for the selected index appears. Inspect per-row **Price source**, timestamps, verified ID, actual lot size, quote flags, error messages and current-session indication. Try switching to NIFTY 50; do not treat unmatched quotes as verified Dhan depth contracts.

Offline tests:

```bash
python -m unittest discover -s tests -p 'test_multi_option_sources.py' -v
python -m unittest discover -s tests -p 'test_live_option_chain.py' -v
npm run build
```

Actual source right, entitlements, accurate exchange quotes, historical option P&L and 20-level execution timing are not certified by synthetic CI fixtures.
