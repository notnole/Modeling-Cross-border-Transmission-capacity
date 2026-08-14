# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Values **cross-border power transmission capacity** between European day-ahead electricity markets using the Margrabe spread-option formula. Historical hourly spot prices for two countries are loaded, the per-hour implicit capacity value (`max(S2 − S1, 0)`) is computed, a single volatility `sigma` is fitted by Levenberg–Marquardt to the Margrabe function (`scipy.optimize.curve_fit`), and that fitted model is then priced against forward curves to obtain capacity value and deltas per delivery profile (base / peak / offpeak).

Domain reference: `Dokumentacia p_soft.pdf` in the repo root.

## Repository layout — three parallel copies of the same code

This is important: there is no single source of truth. The same classes appear in three places with subtle differences:

- **`p_soft/`** — current package layout. `border_class.py` and `capacity_class.py` at the top, helpers in `Loaders/loader.py` and `Utilities/delivery_class.py`. Imports use the subpackage paths (`import Loaders.loader as ld`).
- **`p_soft/_test/`** — a **flat copy** of the same modules (`border_class.py`, `capacity_class.py`, `loader.py`, `delivery_class.py`) plus the runnable example `capacity_test.py`. Imports are flat (`import loader as ld`). This is the directory you actually `cd` into to run the example, because `capacity_test.py` uses flat imports.
- **`BorderSpread/`** — an older snapshot. Diverges from `p_soft/` (e.g., missing `it`, `dkw`, `dke` from the border dictionary; no `'M' → 'MS'` resampling fix; `Capacity.py` here is a broken stub with typo `ImpicitCapacity` and `ABC.ABCMeta` — do not import from it). Treat as legacy.

When editing, **mirror changes into all relevant copies** or the example will silently run against the old code. The `p_soft/` versions are the canonical ones; `_test/` is the runnable mirror.

## How to run it — the current pipeline

`run_capacity.py` is the entry point. The `p_soft/` classes are called unchanged;
everything around them (data, windowing, scoring) lives in `prep/` and the runner.

```powershell
# 1. hourly DAM panel  -> Data/spot_current.csv + Data/spot_hourly.parquet
python prep\build_spot.py --start 2021-01-01

# 2. monthly BASE forward closes -> Data/fwd_monthly.csv (+ Data/fwd_price.csv)
python prep\build_forwards.py --xlsx "$HOME\Downloads\FORWARD_PRODUCTS.xlsx"

# 3. price the live board, and score the model against realised payoffs
python run_capacity.py predict  --window 12
python run_capacity.py backtest --window 12
```

Outputs land in `outputs/`. Dependencies come from the workspace root
(`pip install -e .` at `Coders-Workspace`): `pandas`, `numpy`, `scipy`,
`matplotlib`, plus `plumbing.okte` / `plumbing.entsoe` for the pulls.

`p_soft/_test/capacity_test.py` is the **original** example and is left as
found: it asks for `de_hu` over 2023 with forwards hardcoded in a dict at line
39, and cannot run against any data file in the repo (see Data below).

## Data

| File | What | Built by |
|---|---|---|
| `Data/spot_current.csv` | hourly DAM, one column per zone, `date` as `%Y %m %d %H` **UTC wall clock** | `prep/build_spot.py` |
| `Data/spot_hourly.parquet` | same panel, tz-aware UTC — the canonical copy | `prep/build_spot.py` |
| `Data/fwd_monthly.csv` | long: `trade_date, zone, delivery_month, close` | `prep/build_forwards.py` |
| `Data/fwd_price.csv` | one delivery month in the `fwd_price_loader` shape | `prep/build_forwards.py` |
| `Data/spot.csv` (+ `.xlsx`) | **legacy, do not use** — see below | shipped |

Spot sources: **SK from OKTE** `/dam/results` column `price`; every other zone
from **ENTSO-E** `day_ahead_prices`. OKTE's `priceCz`/`priceHu`/`priceRo` and
`atc*` columns exist in the response but are empty in every year checked (2023,
2024, 2025, 2026) — legacy pre-SDAC fields, do not use them. SK/CZ/HU/AT/... DA
went hourly → 15-min on **2025-10-01**; the builder resamples everything to
hourly means so one series spans the switch.

Forwards come from a **`FORWARD_PRODUCTS.xlsx`** export, long format:
`MD.EP.<exchange>.<root>.BASE.FIX.MID.<M|Q|Y>.<year>[.<period>]`. The `root` is
the **EEX short code, not the area code** — decoded via `prep/zones.py`, which
mirrors `plumbing/eex/catalog.md`. Traps: an expired contract carries **`0`**,
not NaN (66% of rows); Year contracts have no period field; Poland (`FP`/`PLPX`)
has Year contracts only, so no SK-PL monthly pricing.

**Why `Data/spot.csv` is retired.** It covers only 2016-01 → 2019-05, its `de_lu`
column is 83% empty (and the border dictionary wants `de`), its `ro` column is
junk (Jan-2019 mean 352 EUR/MWh), and it is stamped in **naive CET**: 02:00 is
missing on spring-forward and duplicated on fall-back, so the index is
non-unique and non-monotonic and `resample().mean()` double-weights one hour a
year. The replacement is UTC-stamped for that reason. Consequence: base month
means are taken over UTC hours, so a month boundary sits 1–2 h off the
CET-defined EEX contract (2 hours in ~720 — immaterial for a base average).
`Delivery.peak`/`offpeak` would be genuinely wrong on a UTC index; the forwards
are BASE-only so they are never used.

## Core abstractions

- **Border naming**: borders are strings like `"de_hu"` — first country = `S1` (from), second = `S2` (to). Direction matters: `de_hu` and `hu_de` are separate capacities with different deltas. The country codes must exist in `DataBorderClass.dictionary_borders` (extend that dict to add new markets).
- **`DataBorderClass`** (`border_class.py`): loads spot history, computes per-hour implicit value `max(S2 − S1, 0)`, then `aggregate_data(freq, delivery=...)` resamples to monthly/quarterly/yearly means while masking by delivery profile (base/peak/offpeak) via `Utilities.delivery_class.Delivery`. The `_state` flag (0 → 1) guards calls.
- **`Delivery`**: builds boolean masks over an hourly datetime index. `peak` = hours 8–19, weekdays only; `offpeak` = `base AND NOT peak`.
- **`Capacity` / `ImplicitCapacity`** (`capacity_class.py`): `capa_fit(data, delivery_, scaling)` fits `sigma` and stores `sig_low/mid/upp` (± 1 covariance) per delivery profile. `scaling` rescales `sigma` by `sqrt(scaling)` (use this when fitting on shorter horizons than the contract). `capa_price` / `capa_delta` evaluate Margrabe on forward prices.
- **`CapacityDict`**: aggregator for many borders, joins fitted capacities with forward prices via `load_fwd_prices()` and produces a result table. Note: `CapacityDict.sort` is broken (`self.__result_dict.update.items()`) — fix before relying on it.

## Where it stands (2026-08-14)

It runs and predicts. `backtest --window 12` over **39 delivery months ×
10 directed borders = 390 border-months** (2023-02 → 2026-07, forward board
taken on the last trade date before delivery, sigma fitted on the 12 whole
months before it):

| | EUR/MWh |
|---|---|
| mean realised value `mean(max(P2−P1,0))` | 4.28 |
| mean model value | 3.51 |
| mean intrinsic `max(F2−F1,0)` | 2.53 |
| **MAE model** | **2.44** |
| MAE intrinsic (no-option-value baseline) | 2.74 |
| ME model | **−0.77** |

The option layer earns its keep: it beats the intrinsic baseline on **272 / 390
(70%)** border-months and cuts MAE 11%. Two honest caveats:

1. **It captures only 56% of the true time value** — modelled 0.98 against a
   realised `value − intrinsic` of 1.75 — hence the −0.77 systematic
   underprediction. That is the monthly-mean aggregation diluting sigma, as
   expected — fitting sigma on 12 monthly means throws away exactly the
   intra-month dispersion that makes the option worth something.
2. **The bigger error source is the forward spread, not sigma.** Every worst
   miss is a forward-curve miss: SK-HU Jul-2024 priced off F = 87.80 / 89.55
   (spread 1.75) and realised 40.57 because spot came in 96.22 / 135.57
   (spread 39). Margrabe takes `F` as given, so it inherits that error whole.
   Chasing sigma will not fix these.

Fitted sigma tracks the decoupling trend — 0.034 (2023) → 0.057 (2024) → 0.091
(2025) — so the fit is not inert; on the retired 2018 CZ/HU file it collapsed to
0.023 and the model degenerated to intrinsic with delta ±1.

Live board (`predict`, board 2026-08-06, 12-month window): sigma 0.056 SK-HU /
0.069 SK-CZ / 0.083 CZ-DE / 0.121 AT-DE, time value 0.1–2.1 EUR/MWh.
`outputs/prediction_2026-08-06_w12.csv`, `outputs/backtest_w12.csv`.

## Fixed in `p_soft/` (2026-08-14)

Minimum set to make the model run on current data. **No model logic changed** —
the fit, the Margrabe evaluation and the aggregation are exactly as found.

- `Utilities/delivery_class.py` — `Delivery` now normalises its input to a
  `DatetimeIndex`. Under pandas ≥ 2.1 `Series.dt.to_pydatetime()` returns a
  Series, so `pd.to_datetime(...).to_frame()` landed a `RangeIndex` and every
  `index.hour` lookup raised `AttributeError`. This killed everything
  downstream of `aggregate_data`. Masks themselves unchanged.
- `border_class.py` — `is 'implicit'` → `==`; `load_data` now forwards
  `path_spot` to `spot_loader`; `pl` added to `dictionary_borders`;
  string-`raise` → `RuntimeError`.
- `Loaders/loader.py` — the three hardcoded absolute paths (`C:\Data\...`,
  `/Users/marek/...`) now default to this repo's `Data/`; string-`raise` →
  `KeyError` with the available columns in the message.
- `capacity_class.py` — five string-`raise` calls → real exceptions.

## Known bugs still present — read before trusting an output

- **`sig_low`/`sig_upp` are not a 1-sigma band.** `capa_fit`
  (`capacity_class.py:127-129`) subtracts/adds `curve_fit`'s **covariance** as
  if it were a standard deviation. Use `sig_mid` / `capa_price_mid` only;
  `run_capacity.py` does.
- **`ImplicitCapacity` only ever fits `border[0]`.** `capa_fit` and `plot` read
  `self.border[0]`, so constructing one object with several borders silently
  fits the first and prices the rest with its sigma — which is wrong, because
  the payoff `max(S2−S1,0)` is one-sided and direction matters. The original
  `capacity_test.py` has this bug live. `run_capacity.py` sidesteps it by
  building one `ImplicitCapacity` per border.
- **All delivery profiles share one dict.** `__init__` does
  `{key: aux_dict for key in delivery}` with a single `aux_dict` object, so
  fitting `base` also overwrites `peak` and `offpeak`. Only safe with one
  profile.
- `CapacityDict.add_capacity` does `.extend(capa_type())` on a **string**, so
  `border_type` gets 8 entries per border and desyncs from every other column.
- `CapacityDict.sort` — `self.__result_dict.update.items()`, `AttributeError`.
- `loader.calc_prods` — the "all three profiles supplied" consistency check
  recomputes offpeak with a **`+`** where the hour-weighted identity needs
  `−`, overwriting a correct offpeak and printing a bogus warning. The
  one-missing branch has the sign right.
- `margrabe`/`delta` use `math.log`: scalars only, and a non-positive forward
  raises. Spot history does contain negatives, which is fine (the fit sees
  monthly means) but do not feed hourly prices in.
- `BorderSpread/Capacity.py` does not work (`ABC.ABCMeta` is not valid); ignore it.
- `p_soft/_test/loader.py` parses `%Y-%m-%d %H:%M:%S`, but every CSV in the repo
  is `%Y %m %d %H` — the "runnable mirror" cannot read the repo's own data.
- The `Old/` and `__MACOSX/` directories, plus the `*.zip` archives, are dead weight from prior snapshots.
