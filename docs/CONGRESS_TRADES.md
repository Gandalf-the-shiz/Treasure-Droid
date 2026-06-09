# Congressional Trade Intelligence

Tracks U.S. politician stock disclosures (Pelosi-tracker style) and feeds the
Robinhood prep agent.

## Data sources

| Source | Key / setup | Notes |
|--------|-------------|-------|
| **kadoa congress-trading-monitor** | none | Default; ~54k STOCK Act trades via GitHub |
| **Quiver Quantitative** | `QUIVER_API_KEY` | Best quality if subscribed |
| **capitol-api** | `CAPITOL_API_URL` | Self-hosted House PTR parser |

## Artifacts

| File | Contents |
|------|----------|
| `data/congress/trades_recent.json` | Recent normalized trades |
| `data/congress/signals_by_symbol.json` | Per-ticker scores, Pelosi flags |
| `data/congress/leaderboard.json` | Most active politicians |
| `data/congress/notable_trades.json` | Watchlist politician trades |
| `config/congress_watchlist.json` | Pelosi weights and aliases |

## Signals per symbol

- `congress_score` — net politician buying intensity (0–1)
- `congress_boost` — position size multiplier for Robinhood manifest (max ~1.35)
- `pelosi_buy` — Nancy Pelosi purchase in window
- `notable_politicians` — watchlist names active on this ticker

## Pipeline

```powershell
python scripts/fetch-congress-trades.py
python scripts/train-investor-v3.py      # optional CONGRESS_BOOST_ENABLED=true
python scripts/enrich_congress_decisions.py
python scripts/generate_trade_signals.py # applies boost to manifest orders
```

## API (local server)

- `GET /api/congress/signals`
- `GET /api/congress/leaderboard`
- `GET /api/congress/notable`
- `GET /api/congress/symbol/{TICKER}`
- `POST /api/congress/refresh`

## Environment

```bash
QUIVER_API_KEY=
CAPITOL_API_URL=http://127.0.0.1:3000
CONGRESS_BOOST_ENABLED=true
CONGRESS_POLICY_WEIGHT=0.12
CONGRESS_PELOSI_EXTRA=0.05
CONGRESS_TRADE_BOOST=true
```
