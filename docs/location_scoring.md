# Location Scoring — Methodology

The `LocationScorer` evaluates the metro area of every job posting against a
50-metro quantitative framework calibrated for an entry-level civil engineer.

This supersedes the original §1.1 placeholder ("coastal / mountains / NYC / LA
premium"), which was a heuristic. The current framework is data-driven and
configurable.

## Five dimensions (each 0.0–5.0)

| Dimension | Sub-signal | Scoring anchor |
|-----------|-----------|----------------|
| **`ce`** — CE Job Market | 2/3 entry-level volume + 1/3 jobs-per-100K density | NoVA: 998 jobs → 4.77 · NYC: 400 → 1.50 · SF: 37 → 0.21 |
| **`col`** — COL-Adjusted Salary | Real net take-home ÷ BEA RPP | `city_real_net / best_real_net × 5` |
| **`home`** — Home Affordability | Years to 20% down on 1–2BR starter (solo income, RPP-adjusted) | Cleveland: 3.3 yr → 5.0 · Boston: negative savings → 0.0 |
| **`mj`** — Cannabis Legal Status | State framework for adult use | Rec 5.0 · Med-Easy 4.5 · Med-Mod 3.5 · Decrim 2.33 · Med-Restrict 2.0 · Banned 1.0 |
| **`dating`** — Dating Market | 2/3 gender ratio (M:F 25–34) + 1/3 pool density (% pop 25–34), quadratic-penalized | Boston 4.9 (highest) · Austin 3.0 (lowest) |

## Five weighting schemes

Defined in `config/cities.yaml`. The active scheme is set in `config/scoring.yaml`.

| Scheme | CE | COL | Home | Cannabis | Dating | Use case |
|---|---|---|---|---|---|---|
| `fit_first`    | 1   | 1 | 1 | **3**   | **3** | Lifestyle-dominant |
| `balanced`     | 1   | 1 | 1 | 1       | 1     | Equal-weight reference (default) |
| `career_relax` | **3** | **2** | **2** | 0.5 | 1 | Career-first, cannabis as minor friction |
| `career_first` | **3** | **2** | **2** | 1   | 1     | Career-dominant |
| `career_only`  | **3** | **2** | 1     | 0   | 0     | CE + finances only |

## Composite formula

```
composite = Σ(weight_i × score_i) / (Σ weights × 5) × 100
```

Yields a 0–100 score that the match engine consumes as a 0.0–1.0 normalized
contribution to `match_score`, weighted by `match_formula.location_weight`
in `config/scoring.yaml` (default 0.30).

## Matching a posting to a metro

`CityMatcher` resolves a posting's `(city, state)` to a canonical metro
using a four-stage ladder:

1. **Exact** — `"Cleveland, OH"` → `cleveland_oh`
2. **Alias** — `"Tysons, VA"` → `dc_nova` (via aliases list)
3. **Fuzzy** — `"Cinncinati, OH"` → `cincinnati_oh` (rapidfuzz token_sort_ratio ≥ 88)
4. **Fallback** — unranked metros (Boise, Honolulu, etc.) → configurable
   neutral composite (default 40.0). Marked `ranked=False` for transparency.

Remote / "Anywhere" / "Multiple Locations" → `match_kind="remote"`, same
fallback composite. Not penalized; just neutral.

## What's not committed

The source analysis PDF (`docs/city_guide.pdf`) is gitignored because it
contains personal candidate framing. The methodology, data values, and
scoring logic are all reproduced openly here and in `config/cities.yaml`.

## Tuning

After funnel data accrues, edit:

- `config/cities.yaml` — adjust dimension scores if a city's market changes
- `config/scoring.yaml` `location.scheme` — switch between schemes
- `config/scoring.yaml` `match_formula.location_weight` — change how
  heavily location influences `match_score` (vs. discipline / benefit /
  trajectory)

Each change is a diff in version control — config-as-code stays auditable.
