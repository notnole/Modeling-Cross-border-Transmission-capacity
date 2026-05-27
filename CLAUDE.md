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

## Running the example

There is no test framework, no `requirements.txt`, no entry-point script. The canonical way to exercise the pipeline is to run the example directly from inside `_test/` so its flat imports resolve:

```powershell
cd "p_soft\_test"
python capacity_test.py
```

Forward prices are **hardcoded in `capacity_test.py`** (the dict around line 39) — edit that dict to change the pricing scenario. `capacity.plot(...)` opens a matplotlib 3D window per border; comment it out for headless runs.

Dependencies (install manually): `pandas`, `numpy`, `scipy`, `matplotlib`.

## Data paths are hardcoded — fix before running

`p_soft/Loaders/loader.py` (and its `_test/` copy) has absolute paths baked into the default `path` arguments:

- `spot_loader` defaults to `C:\Data\spot_price.csv` (Windows-only; will fail elsewhere).
- `fwd_price_loader` and `jao_auction_loader` default to `/Users/marek/Documents/Excel/Data/...` (the original author's Mac paths).

Actual spot data lives in `Data/spot.csv` (and `Data/spot.xlsx`, `p_soft/spot prices.xlsx`). Either edit the default path in `loader.py` or pass `path=...` through — but note that `DataBorderClass.load_data` does not forward `path_spot` to `spot_loader`, so changing the default in `loader.py` is the simpler fix.

CSV format: `date` column formatted `YYYY MM DD HH`, one column per country code (`cz, sk, hu, de_lu, fr, ...`); `#N/A` is used for missing values.

## Core abstractions

- **Border naming**: borders are strings like `"de_hu"` — first country = `S1` (from), second = `S2` (to). Direction matters: `de_hu` and `hu_de` are separate capacities with different deltas. The country codes must exist in `DataBorderClass.dictionary_borders` (extend that dict to add new markets).
- **`DataBorderClass`** (`border_class.py`): loads spot history, computes per-hour implicit value `max(S2 − S1, 0)`, then `aggregate_data(freq, delivery=...)` resamples to monthly/quarterly/yearly means while masking by delivery profile (base/peak/offpeak) via `Utilities.delivery_class.Delivery`. The `_state` flag (0 → 1) guards calls.
- **`Delivery`**: builds boolean masks over an hourly datetime index. `peak` = hours 8–19, weekdays only; `offpeak` = `base AND NOT peak`.
- **`Capacity` / `ImplicitCapacity`** (`capacity_class.py`): `capa_fit(data, delivery_, scaling)` fits `sigma` and stores `sig_low/mid/upp` (± 1 covariance) per delivery profile. `scaling` rescales `sigma` by `sqrt(scaling)` (use this when fitting on shorter horizons than the contract). `capa_price` / `capa_delta` evaluate Margrabe on forward prices.
- **`CapacityDict`**: aggregator for many borders, joins fitted capacities with forward prices via `load_fwd_prices()` and produces a result table. Note: `CapacityDict.sort` is broken (`self.__result_dict.update.items()`) — fix before relying on it.

## Known bugs / pitfalls worth knowing before editing

- `border_class.py:44` uses `if _border_type is 'implicit'` — works by string interning luck on CPython, will silently break under different runtimes. Use `==`.
- `border_class.py:58/87` use `raise('...')` (calling `raise` on a string) instead of raising an exception class — these will themselves raise `TypeError`, not the intended message.
- `CapacityDict.sort` in `capacity_class.py:243` — see above.
- `BorderSpread/Capacity.py` does not work (`ABC.ABCMeta` is not valid); ignore it.
- The `Old/` and `__MACOSX/` directories, plus the `*.zip` archives, are dead weight from prior snapshots.
