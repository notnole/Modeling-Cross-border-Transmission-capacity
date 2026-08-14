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

## The bid use case — `run_capacity.py bid`

The intended use: a JAO **monthly** auction for delivery month M closes a median
**12 days before M starts**, so the July right is bid for in mid-June. `bid`
prices every auction as of its own `bid_gate_closure`, using only information
that predated the gate:

- forward board = last close **strictly before the gate's day**. Not before the
  gate *instant*: `trade_date` is midnight-stamped but a settlement is not
  published until that evening, so a same-day close is lookahead for a midday
  gate.
- sigma = the 12 **whole** months before the gate's own month. A part-month stub
  would enter `aggregate_data` as a full monthly point.

Auctions come from `Data/jao_monthly.csv` (`prep/build_auctions.py`, sourced
from `projects/capacities/data/auctions_monthly.parquet`). **8 of the 10
priceable borders are biddable**: `CZ-DE` / `DE-CZ` run no monthly auctions at
all (`plumbing/jao_auctions/catalog.md`).

### It is not a usable bidding rule yet

Over **192 cleared auctions**, 8 corridors, 2024-08 → 2026-07, bidding
`model value` and paying the clearing price when we win:

| | n | mean P&L | total |
|---|---|---|---|
| bid everything (accept any price) | 192 | −0.03 | −5.5 |
| bid = model value | 77 | **+0.36** | +27.9 |
| — excluding DE-AT / AT-DE | 56 | **−0.47** | −26.4 |
| — DE-AT / AT-DE only | 21 | +2.59 | +54.3 |

EUR/MWh per delivered hour. The apparent edge is **one border pair**. Strip
DE-AT/AT-DE and the rule returns −0.472 per auction against −0.477 for
indiscriminate bidding — statistically the same number, reached by trading 39%
as often. And DE-AT is not a model result: bidding *everything* on DE-AT earned
+3.01 per auction over this window because the auction persistently underpriced
it; the model got +3.87, an improvement on an edge that was already there.

Supporting evidence that the signal is weak: **t = +0.68** on the won set
(+0.75 clustered by delivery month), and **corr(model edge, realised P&L) =
−0.010**. Margin sweep peaks around 0.0–0.5 EUR/MWh and goes negative past 1.0,
but on 29 or fewer auctions.

The one thing that does work: sizing. On the borders where the model refuses to
pay up it is usually right to refuse (`skipped_mean` < `rule_mean` on 6 of 8
corridors) — it is the *level* of the fair value, not the *ranking*, that is
unreliable.

Caveats that bound all of the above: it assumes we are a **price taker** (our
bid never moves the clearing price — plausible at small MW against
30-plus-bidder books, unverified), it ignores `maintenance_hours` (the ATC
derating the `capacities` project models), and 24 delivery months on 8 corridors
is a small sample with P&L correlated across corridors within a month.

## The workbook's monthly history is ample — a correction

An earlier version of this file said "the binding constraint is forward history".
That conflated **depth** with **breadth**, and only breadth is a constraint.

Measured on `Data/fwd_monthly.csv` (77,195 closes):

- **1,313 trade dates**, 2023-01-02 → 2026-08-06, and the **max gap between
  consecutive boards is 1 day** for every zone except RO (one 3-day gap). The
  workbook carries a board on essentially every calendar day, which is also why
  it has non-trading-day rows where every settlement is 0.
- **100% of (delivery month, zone) pairs — 3,328 of 3,328 — have a close strictly
  before the gate day.** Depth is a solved problem.

The real gap is which zones the workbook contains: `at cz de fr gr hu it nl ro
sk`. Missing `be bg hr pl si`, and that is a zone-absence problem, not a history
problem.

### FR and NL wired; Italy deliberately not

`fr` (1,313 trade dates) and `nl` (1,200 from 2023-04-25) had full monthly
history sitting unused. Adding them cost one `prep/add_zones.py` spot pull and
four map entries, and unlocked **DE-FR, FR-DE, DE-NL, NL-DE**. Book is now
**20 corridors / 482 cleared auctions**.

Italy is **blocked on basis, not data** (`zones.IT_BASIS_BLOCKED`). `AT-IT`,
`IT-AT`, `FR-IT`, `IT-FR` all land in **IT_NORD** and `GR-IT` in **IT_SUD**, but
EEX lists exactly one Italian root (`FD`) — a national contract. Pricing a
national forward against a zonal spot is the error capacities measured at up to
12x on IT-FR. That needs a basis model, not a map entry. GR is a dead end for a
different reason: its only corridors are GR-BG (no BG history) and GR-IT (IT_SUD).

### What FR/NL bought, and it is the cleanest result in the project

| | n | bid-everything | rule | per auction |
|---|---|---|---|---|
| 16 corridors (before) | 386 | +4,420 | +37,671 | +317 |
| **the 4 FR/NL added** | 96 | **−64,968** | **+11,362** | **+874** |
| all 20 | 482 | −60,548 | **+49,033** | +371 (t = +1.01) |

Bidding blind on FR/NL loses 64,968. The model **declines 83 of 96** and the 13
it takes earn +11,362. On `DE-FR` it bought **0 of 24** — correctly, since mean
realised (1.76) sits below mean clearing (2.49). `FR-DE` is the interesting one:
mean clearing 31.16, the model's MAE there is 10.14 — its worst — and it still
picked 6 winners for +10,030. **The value is in the refusal, not the valuation.**

Contrast with the earlier AT-CZ/AT-HU extension, which lost 26,581: extension
outcome is corridor-specific and unpredictable from the data's availability. Both
were free to wire; one paid, one did not.

## Lower vs average vs max of the two fair values

Marginal pricing means the bid level only selects the **win set**, so the three
combinations are **nested**: `lower ⊆ average ⊆ max`. That makes each relaxation
testable on the auctions it *adds*. Measured on the 20-corridor book:
**360 auctions**, 2025-02 → 2026-07.

| rule | buys | n | total EUR | per auction | t |
|---|---|---|---|---|---|
| Buy everything | any price | 360 | −164,995 | −458 | **−2.47** |
| MAX of the two | either clears | 237 | −28,356 | −120 | −0.57 |
| Fundamental alone | its bid clears | 207 | −7,398 | −36 | −0.17 |
| AVERAGE of the two | the average clears | 179 | +18,695 | +104 | +0.42 |
| Margrabe alone | its value clears | 113 | +13,473 | +119 | +0.32 |
| **LOWER of the two** | **both clear** | **83** | **+34,432** | **+415** | **+0.94** |
| Perfect foresight | the ceiling | 124 | +300,382 | +2,422 | +8.67 |

The monotone ordering survives the bigger book and gets stronger. Note
bid-everything is now **significantly negative** (t = −2.47), so on this book the
auction is efficiently-to-over-priced and refusal is where the value lives.

**LOWER dominates on every metric** — total, per-auction, t and hit rate — and the
nesting says why: every relaxation buys strictly worse auctions.

| the marginal auctions a looser rule admits | n | total | per auction | hit% |
|−−−|−−−|−−−|−−−|−−−|
| average, beyond lower | 96 | −15,737 | −164 | 34.4 |
| max, beyond average | 58 | −47,051 | −811 | 34.5 |

So MAX is the worst of the three and only slightly better than bidding blind:
"either model likes it" is close to "someone had an opinion". AVERAGE lands
between, as arithmetic requires, and its extra 85 auctions lose 124 each.
Ordering the whole list by per-auction P&L reproduces exactly the strictness
ordering, which is the strongest form of the finding: **on this book, tightening
the agreement requirement monotonically improves the outcome, and there is no
interior optimum to tune.** Sample sizes shrink fast, though — LOWER is 78
auctions at t = +0.49, so "best of the three" is not "established".

## Extending to the fundamental model's other countries

Cheap mechanically, and **not free in expectation**. Measured 2026-08-14:

| tier | corridors | what it needs |
|---|---|---|
| **wired now** | **20** | — (16 + the four FR/NL below) |
| done: free, no new data | — | AT-CZ, CZ-AT, AT-HU, HU-AT — map entries only |
| done: workbook history + one spot pull | — | DE-FR, FR-DE, DE-NL, NL-DE |
| blocked on basis, not data | 6 | the Italy corridors — one national EEX contract, zonal spot |
| live-priceable now | 44 | nothing; all 14 EEX zones **confirmed** to return a Month/Base settlement |
| backtestable from 2026-06-19 | 44 | `data/eex/monthly_forwards.parquet`, the local daily collection |

44 of the 106 monthly-auction corridors (**1,149 openings, 363k MW-months**) are
reachable with the fundamental model's 14 zones — up from 16 today.

**The binding constraint is forward history, not zone coverage.** EEX's endpoint
only serves the last ~33 trading days, so a live board is available for all 14
zones but a 2024-08 → 2026-07 backtest is not. Monthly history exists only in the
`FORWARD_PRODUCTS.xlsx` export (10 zones: `at cz de fr gr hu it nl ro sk`) and in
the local daily cache from 2026-06-19. So `be bg hr pl si` — and therefore 24 of
the 28 new corridors — can be **priced live but not validated**. The cache fixes
that with time: 38 of its 39 days are complete across all 14 areas and 8 delivery
months. It is currently missing 2026-08-12 (1 area only) and 2026-08-13 entirely
— the collection job needs a look.

Liquidity is the other filter. Sep-2026 open interest: DE 278,853 / FR 86,930 /
HU 14,068 / NL 11,818, then BE 3,433 / AT 2,845 / CZ 2,191 / GR 1,359 / RO 1,101
/ BG 689 / SK 482 / SI 378, and **HR 202 and PL 12 with no volume at all**. A
settlement on a 12-lot contract is a mark, not a price.

**What the four free corridors actually cost.** Adding AT-CZ/CZ-AT/AT-HU/HU-AT
needed no new data and took two minutes — and lost money: −26,581 on the rule
(−1,108/auction, t = −1.28), taking the whole book from +676/auction (t = +1.88)
to +317 (t = +0.93). Almost all of it is **AT-HU: −37,229**, the corridor with the
highest mean clearing (15.1) and the model's worst fit (MAE 6.6, overprices by
1.1) — and the fundamental model's own tier-A rank-4 pick. CZ-AT was the only
good one (+11,874). Conclusion: extension is a per-corridor decision with its own
validation, never a switch to flip. Turn a corridor on only after it has a
backtest of its own.

## Corrections logged 2026-08-14 (later in the day)

Three things an earlier version of this file got wrong. All three changed a
conclusion, so they are recorded rather than quietly edited away.

**1. `CZ-DE` / `DE-CZ` are biddable after all — through four TSO-split
corridors.** `plumbing/jao_auctions/catalog.md` says no monthly auction runs on
the corridors *named* `CZ-DE` / `DE-CZ`, which is true and which I read as "that
border is not biddable". It is: `DE(50Hz)-CZ`, `DE(TenneT)-CZ`, `CZ-DE(50Hz)`,
`CZ-DE(TenneT)` each run 26 monthly auctions, and `DE`, `DE(50Hz)` and
`DE(TenneT)` are all the **same price zone** (`DE_LU`) — so they share the `cz`
/ `de` forwards and one fitted sigma, and differ only in gate, ATC and
availability. `prep/zones.py::CORRIDOR_TO_BORDER` is now the many-to-one map;
corridor is the auction instrument, border is the pricing key. Never rebuild a
corridor name by upper-casing a border again — the parentheses make it fail
silently.

The consequence is not cosmetic: **12 corridors instead of 8**, and the German
pair turns out to be the *largest* source of P&L in the whole study
(bid-everything +471/auction over 98). Bid-everything over all 12 flips from
−0.03 to **+0.19 EUR/MWh**.

**2. "DE-AT carries the entire result" was wrong.** There are two rich groups,
not one. Ex-DE-AT the agreement rule is now **+3,151** (it was −9,862 on the
8-corridor set). Removing *both* DE-AT and the German-Czech corridors is the
honest control, and there it is −9,862. So: two profitable border groups, and on
everything else the model still adds nothing.

**3. Maintenance is not a discount, and my first note about it was wrong.**
`DE(50Hz)-CZ` averages 172 h/month of reduced ATC with
`maintenance_min_atc_mw = 0` — a 1 MW holder is physically out, up to 694 h in
one month. That does **not** reduce realised value per MWh: under HAR Art 59 a
curtailed holder is made whole at the same `max(spread, 0)` a non-nominated
holder receives, and the catalog is explicit that it "must not be reduced for
it". All 7,728 observed curtailment records read `Network Security` (Art 59);
force majeure (Art 60) *would* change it — there you get the clearing price back
and the margin is 0. The live residual is the Art 59(2)–(4) compensation cap,
which cuts holders pro rata and is unquantifiable without JAO's cap figures.
Note the market seems not to price the difference at all: `DE(50Hz)-CZ` and
`DE(TenneT)-CZ` clear within ~1 EUR of each other on identical prices while one
is curtailed ~172 h/month and the other ~0.

**And an answered question: yes, the "both agree" backtest IS the
lower-of-the-two-bids strategy.** JAO monthly auctions are marginal-priced, so
`min(a, b) >= c` if and only if both `a >= c` and `b >= c`, and you pay `c`
either way. Verified: identical win set (49 of 49) and identical P&L
(+16,104.7) on the 8-corridor set. The equivalence depends on marginal pricing —
under pay-as-bid the same win set would have earned **−12,320** instead, because
the entire result is the gap between the bid and the clearing price.

## Head-to-head with the fundamental model (`projects/capacities`)

`build_chart.py::compare()` joins this project's bid book to
`capacities/price_model/outputs/bids_20260803.csv` on (corridor, delivery
month). That book is the opposite approach — per-zone LGBM day-ahead forecasts
off 64 Volue fundamentals curves, bid at the predicted-value `p50` times a
calibration `k`, no forwards and no fitted volatility. Overlap: **144 auctions,
8 corridors, 2025-02 → 2026-07**. Both are scored against *this* project's
realised values so the target is identical.

**The two projects independently agree on the payoff** — mean |difference|
**0.016 EUR/MWh** across 144 auctions, from separate price pulls (they use
ENTSO-E for SK, this uses OKTE) running the same
`spread.clip(lower=0).mean()`. Two exceptions: their CZ-SK 2025-07 is 1.57
lower because their price file has NaN hours there and `value.py` drops them
(my panel is complete for that month, and my SK/CZ match ENTSO-E to 0.000);
and DST months differ by the one repeated CET hour their window counts.

Value-estimate accuracy, which needs no bidding rule to interpret:

| estimate | ME | MAE | corr |
|---|---|---|---|
| **Margrabe value** (forwards + fitted vol) | **+0.04** | **2.68** | +0.617 |
| Forward spread, floored at 0 | −1.61 | 3.18 | +0.610 |
| Fundamental bid (`p50 × k`) | +1.92 | 3.89 | +0.608 |
| Fundamental `p50` | +2.38 | 3.96 | +0.567 |

**The forwards-only model is the more accurate of the two here** — lower MAE and
nearly no bias, where the fundamental model runs +1.9 to +2.4 EUR/MWh high,
which for a bidder means systematic overpaying. Do not read the +0.04 as
"unbiased": on the longer 390-auction backtest the same model runs ME −0.77, so
the bias is not stable across windows.

Bidding P&L on the 144, EUR at 1 MW (ceiling = 126,792):

| rule | n | total | mean | t | n ex-DE-AT | total ex-DE-AT |
|---|---|---|---|---|---|---|
| Buy everything | 144 | −26,133 | −181 | −0.73 | 108 | −52,313 |
| Fundamental bid | 90 | +707 | +8 | +0.02 | 64 | −34,952 |
| Margrabe bid | 66 | +716 | +11 | +0.03 | 47 | −22,405 |
| **Both agree** | 49 | **+16,105** | **+329** | +0.69 | 32 | **−9,862** |

Neither model alone clears zero. Requiring **both** to agree is 20x either one —
and it still fails the same two tests everything else on this page fails:
t = +0.69, and ex-DE-AT it is a loss. The agreement 2×2 is the part worth
keeping, because it is an ordering rather than a level:

| | fundamental buys | fundamental declines |
|---|---|---|
| **Margrabe buys** | **+329** (n=49) | −905 (n=17) |
| **Margrabe declines** | −376 (n=41) | −309 (n=37) |

**Disagreement is a stay-out signal.** Whenever one model buys and the other
declines, the average auction loses — most sharply when Margrabe buys alone
(−905/auction, t = −1.78). Ex-DE-AT, agreement loses 308/auction against 484 for
buying everything: on borders with no free money, the best this does is lose
less.

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
