# CLAUDE.md

This file guides Claude Code (claude.ai/code) when working in this repository.

## What this project does

Values **cross-border power transmission capacity** between European day-ahead
markets using the Margrabe spread-option formula. Hourly spot prices for two
zones give the per-hour implicit capacity value `max(S2 − S1, 0)`; a single
volatility `sigma` is fitted to the Margrabe function by Levenberg–Marquardt
(`scipy.optimize.curve_fit`); the fitted model is then priced against forward
prices to obtain capacity value and deltas per delivery profile (base / peak /
offpeak). A net-P&L backtest compares that realized value against the actual
JAO long-term-rights auction clearing price (the cost of holding capacity).

Domain reference: `Dokumentacia p_soft.pdf` in the repo root.

## Layout

Single source of truth — no parallel copies (the old `p_soft/`, `_test/`,
`BorderSpread/`, `Old/` snapshots have been removed).

```
spot_model/            # the package — import as `from spot_model import ...`
  __init__.py
  loader.py            # all data access + forward-product helpers
  delivery_class.py    # base / peak / offpeak hour masks (Delivery)
  border_class.py      # DataBorderClass: load spot, compute implicit value, aggregate
  capacity_class.py    # Capacity / ImplicitCapacity (fit + price), CapacityDict
examples/
  capacity_test.py     # fit sigma + price a border against forward prices
  backtest_test.py     # net P&L: realized spread value − JAO auction cost
data/
  spot.csv             # offline historical DA prices (source='csv' fallback)
  jao/                 # JAO market-data exports = LTR auction clearing prices
    JAO_marketdata_export_*.xlsx
  .cache/              # generated price cache (git-ignored)
Dokumentacia p_soft.pdf
requirements.txt
```

## Running

From the repo root (the examples bootstrap `sys.path` so they run from anywhere):

```powershell
python examples/capacity_test.py     # pricing demo (default SOURCE='entsoe')
python examples/backtest_test.py     # net-P&L backtest
```

Install deps with `pip install -r requirements.txt` (pandas, numpy, scipy,
matplotlib). `capacity.plot(...)` builds matplotlib figures with the `Agg`
backend (no window); the examples already set that.

## Data sources (in `loader.py`)

- **`spot_loader(country_list, bT, eT, path=None)`** — reads `data/spot.csv`
  (the bundled history is 2016-01..2019-05). Offline fallback.
- **`entsoe_spot_loader(country_list, bT, eT)`** — pulls live DA prices from the
  ENTSO-E Transparency Platform via the sibling **ClaudeWorkspace `plumbing`**
  package. Returns the same shape as `spot_loader` (naive hourly index named
  `date`, one column per model country code). Requires `plumbing` importable and
  `ENTSOE_API_TOKEN` in ClaudeWorkspace's `.env`. The workspace location
  defaults to a hardcoded path in `loader.py`; override with the
  `CLAUDE_WORKSPACE` env var.
- **`jao_spread_loader(border_list, bT, eT)`** — realized signed DA spreads per
  directional border from JAO `priceSpread`. `border_X_Y == price(Y) − price(X)`
  (JAO's sign convention is inverted, but it maps to the model border with the
  **same ordering** — verified to machine precision against ENTSO-E). Core CCR
  borders only, **data from 2022-06-08**.
- **`jao_auction_loader(path=None, border_list=None)`** — LTR **monthly base
  auction clearing prices** (the capacity *cost*) from `data/jao/*.xlsx`. Returns
  one row per (border, month) with `price_eur_mwh` + offered/requested/allocated
  MW. We read the `.xlsx` straight from its zip/XML because openpyxl can't open
  these files (malformed stylesheet).
- **`DataBorderClass.load_data(source='csv'|'entsoe')`** chooses the spot source.

## Core abstractions

- **Border naming**: `"de_hu"` → first = `S1` (from), second = `S2` (to).
  Direction matters; `de_hu` and `hu_de` are different capacities with different
  deltas. Country codes are lowercase and **cannot contain `_`** (the data has
  `de`, not `de_lu`; `itnord`, not `it_nord`), since `_` separates the two
  endpoints. Extend `DataBorderClass.dictionary_borders` to add markets, and the
  `_ENTSOE_AREA` / `_JAO_ZONE` maps in `loader.py` to add live-pull mappings.
- **`Delivery`**: `base` = all hours; `peak` = hours 8–19 weekdays; `offpeak` =
  `base AND NOT peak`. The monthly "Every day 00:00-24:00" auction product = base.
- **`ImplicitCapacity`**: `capa_fit(data, delivery, scaling)` fits `sigma` (± 1
  covariance → `sig_low/mid/upp`); `capa_price` / `capa_delta` evaluate Margrabe.
- **`delivery_mean(df, delivery)`**: mean of each column over a delivery
  profile's hours — used for realized backtest values and forward proxies.

## Gotchas worth knowing before editing

- **ENTSO-E AT zone split**: AT only became a standalone bidding zone on
  2018-10-01 (part of `DE_AT_LU` before). Pulling `AT` for earlier dates returns
  no data — the `at_be` example uses a 2019 window for the ENTSO-E path.
- **JAO Core data starts 2022-06-08**; backtest windows must be 2022-06 onward.
- **JAO auction prices are manual exports.** The auctions.jao.eu API is
  token-gated (`AUTH_API_KEY`, free but a registration form) and **not wired**.
  Drop fresh `JAO_marketdata_export_*.xlsx` into `data/jao/` to extend coverage.
  Current exports: monthly BASE, 18 directional borders, 2025 + 2026-H1.
- **Net-P&L caveat**: realized value uses `max(spread, 0)` (optimal ex-post use),
  an upper bound on what a real PTR holder earns; the backtest excludes
  zero-offer rows and collapses multiple auction sessions per delivery month.
- **Windows case-insensitive FS**: the data dir is tracked lowercase as `data/`
  in git even though it may display as `Data` locally — keep paths lowercase.
- **Pre-existing code smells** (carried over, not yet fixed): `border_class.py`
  uses `raise('...')` (raises `TypeError`, not the intended message) in a couple
  of guards; `CapacityDict.sort` is broken (`self.__result_dict.update.items()`).
  `fwd_price_loader` still has a hardcoded mac path but is unused by the examples
  (they build forward prices inline via `calc_prods`).
