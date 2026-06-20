# Zerodha XIRR + Index Benchmark Dashboard

A shareable, self-updating dashboard that computes your **capital-deployed XIRR** from a Zerodha equity ledger CSV and benchmarks it against major Indian indices.

**All data stays in your browser.** The frontend never uploads your ledger — it only fetches pre-computed index price JSON from this repo.

## Live Demo

👉 **[Open Dashboard](https://<your-username>.github.io/zerodha-xirr-benchmark/)**

## How It Works

1. **Paste** your Zerodha equity ledger CSV (Console → Reports → Ledger → Equity)
2. **Enter** your current total account value (holdings MV + idle cash)
3. **See** your XIRR vs each index benchmark, with bar charts and a weighted basket comparison

### What's Computed

- **Your XIRR**: Money-weighted return (XIRR) on capital deployed via your actual deposit/withdrawal dates
- **Benchmark XIRR**: What you'd have earned if every deposit bought index units and every withdrawal redeemed pro-rata, using the same cash flow dates
- **Weighted basket**: Blend multiple index benchmarks with adjustable weights

### Privacy

- Ledger CSV is parsed entirely in JavaScript — no server, no upload, no analytics
- The only network calls fetch `data/meta.json` and `data/<index>.json` from GitHub Pages

## Index Data Sources

| Index | Ticker (yfinance) | History From | Status |
|---|---|---|---|
| Nifty 50 | `^NSEI` | 2007 | ✅ |
| Sensex | `^BSESN` | 2005 | ✅ |
| Nifty 500 | `^CRSLDX` | 2005 | ✅ |
| Nifty Midcap 150 | `NIFTYMIDCAP150.NS` | 2019 | ✅ |
| Nifty Next 50 | `JUNIORBEES.NS` (ETF proxy) | 2009 | ✅ |
| Nifty Smallcap 250 | — | — | ❌ unavailable |

**Why Nifty Next 50 uses an ETF proxy:** Yahoo Finance has no direct ticker for the Nifty Next 50 index. `JUNIORBEES.NS` (Nippon India ETF Junior BeES) closely tracks it and has history from 2009. Note that ETF prices include tracking error and expense ratio.

**Why Nifty Smallcap 250 is unavailable:** yfinance returns minimal/no data for this index, and alternative libraries (nsepython, jugaad-data) are broken due to NSE API changes. It's marked `unavailable` in the UI rather than showing fabricated data.

All indices are **price indices** (no dividends) — matching the brief's requirement to ignore dividends on both the portfolio and benchmark side.

## Data Pipeline

`scripts/update_indices.py` runs daily via GitHub Actions:

1. Fetches new price data from yfinance for each configured index
2. Merges with existing JSON (idempotent — dedupes by date, never deletes history)
3. Validates each series (monotonic dates, plausible close values)
4. Writes `data/<key>.json` and `data/meta.json`
5. Commits changes to the repo (heartbeat commit even if all sources fail)

### Adding a New Index

1. Add an entry to the `INDICES` dict in `scripts/update_indices.py`:
   ```python
   "my_index": {
       "ticker": "TICKER.NS",
       "name": "My Index",
       "source": "yfinance",
   },
   ```
2. Run `python scripts/update_indices.py` to verify it fetches data
3. Commit and push — the frontend auto-discovers new indices from `meta.json`

### Resilience

- Each index is fetched in its own `try/except` — one failure doesn't abort others
- If a fetch fails but existing data exists, the index stays `ok` with its last-known date
- `meta.json` is always updated (heartbeat) to keep the GitHub Actions cron active

## 60-Day Cron Mitigation

GitHub disables scheduled workflows on repos with no activity for 60 days. The daily heartbeat commit (updating `meta.json` timestamp even when no price data changes) keeps the repo active. If the cron stops:

1. Go to the repo's **Actions** tab
2. Find the "Update Index Data" workflow
3. Click **Enable workflow**, then **Run workflow** manually

## Telegram Alerts

If any index data is stale (>3 days old), the pipeline sends a Telegram alert. To set up:

1. Create a bot via [@BotFather](https://t.me/BotFather) and get the token
2. Get your chat ID (send `/start` to [@userinfobot](https://t.me/userinfobot))
3. Add these as GitHub Actions **secrets**:
   - `TELEGRAM_TOKEN` — your bot token
   - `TELEGRAM_CHAT` — your chat ID

Without these secrets, alerts are silently skipped.

## Repo Structure

```
/                          static frontend (index.html + JS), served by GitHub Pages
/data/<key>.json           per-index history: [{"date":"YYYY-MM-DD","close":number}, ...] ascending
/data/meta.json            {updated, indices:{<key>:{status,source,latestDate,latestClose}}}
/scripts/update_indices.py data pipeline (Python + yfinance)
/.github/workflows/update.yml  daily cron + manual trigger
```

## Setup

1. Fork/clone this repo
2. Enable GitHub Pages (Settings → Pages → Source: main branch, root `/`)
3. Optionally set Telegram secrets (see above)
4. Run the pipeline once manually: Actions → Update Index Data → Run workflow
5. Visit `https://<username>.github.io/zerodha-xirr-benchmark/`

## No Dividends

By design, this tool ignores dividends on both sides:
- **Portfolio**: the ledger CSV captures capital flows only, not dividend income
- **Benchmarks**: all indices use price-return (not total-return) data

This is a deliberate simplification to keep the comparison apples-to-apples.
