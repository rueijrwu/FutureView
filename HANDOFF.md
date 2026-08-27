# FutureView Profitability Research Handoff

Last consolidated: 2026-08-27

`Theory.md` is the authoritative theory document. `Implementation.md` is the authoritative implementation framework.

## Current research objective

The Strategy is fixed. The current research is **not** trying to optimize the Strategy, Addon rule, Exit rule, or capital allocation.

The core question is:

> Given a fixed Strategy, can historical price-volume information identify market/Entry states in which that Strategy is closer to its historically achievable upper-profit region?

The immediate historical task is therefore to define the Strategy outcome space correctly, compute its profitability bounds, and study whether high-profit regions have recognizable structure.

## Fixed Strategy path semantics

All current historical Strategy calculations use daily close prices.

Over the five-year sample, first identify:

- all legal Entry dates under the fixed Strategy Entry rule;
- all legal 5-day and 10-day Exit events;
- all retrospective 5-day and 10-day local minima;
- all retrospective 5-day and 10-day local maxima.

For a legal Entry `e` with close `P_e`, let `m_b` be the most recent member of the 5/10-day local-minimum union before Entry. Define the fixed campaign distance:

`D_b = P_e - P[m_b]`.

The initial Entry deploys one third of total campaign capital.

Addon candidates are only later members of the 5/10-day local-maximum union. Let `last_buy_price` be the actual price of the Entry or most recent Addon. The first later local maximum satisfying

`candidate_close - last_buy_price > D_b`

becomes the next Addon. The same original `D_b` is reused for every Addon. At most two Addons are allowed, so total capital deployments are at most:

`Entry + Addon1 + Addon2`.

Each deployment uses one third of the original total-capital denominator. Unused capital remains cash.

Exit rules:

- first legal 5-day exit event: sell 40% of then-current shares;
- a 5-day partial exit does **not** close the campaign and does **not** disable future Addons;
- legal 10-day exit event: liquidate all remaining shares and end the campaign;
- any still-open position is liquidated at the fixed 60-session horizon.

No addon-reference configurations are enumerated. With the Strategy fixed, each eligible legal Entry produces exactly one deterministic Strategy path and one realized outcome `E(e)`.

## Evaluation interval and profitability bounds

Current audit interval:

- window length `W = 60` trading sessions;
- stride `= 1` trading session.

For an interval `W=[t0,t1]`, include every deterministic Strategy path whose **initial Entry** lies inside the interval. The path may continue beyond `t1` until its Strategy exit or 60-session horizon.

For the legal Entry set `I_W`, define:

`E_W = { E(e) : e in I_W }`

`L_W = min E_W`

`U_W = max E_W`

`C_W = U_W - L_W`

For `C_W > 0`:

`Q_i = (U_W - E_i) / C_W`

Interpretation:

- `Q=0`: observed upper-profit bound;
- `Q=1`: observed lower-profit bound;
- smaller `Q`: closer to the best observed fixed-Strategy outcome in that interval.

Crucially, `U_W` is **not** the result of optimizing the Strategy. It is simply the maximum realized outcome among all legal Entries of the already-fixed Strategy in that interval.

## Baselines

Representation A currently uses:

`A = [L, U, B_periodic, B_random]`

`B_periodic`:

- three equal one-third deployments;
- evenly spaced within the evaluation window;
- all tranches marked to the common window end.

`B_random`:

- coarse descriptive indicator only;
- 20 fixed-seed samples per interval;
- each sample uses 1-3 random Entry dates, one-third capital per actual deployment;
- unused capital remains cash;
- not a research target.

Signed baseline comparison:

`A_periodic = U - B_periodic`

Negative values are retained and meaningful. They can indicate intervals where even the best legal fixed-Strategy Entry underperformed periodic deployment.

Do not confuse this with `C = U-L`.

## Latest deterministic-path audit

SMH, five years, current data span approximately 2021-08-27 through 2026-08-27.

Current deterministic path table:

- eligible legal Entries: 348;
- deterministic paths: 348;
- Addon1 rate: 23.85%;
- Addon2 rate: 2.30%.

For `W=60`, stride 1:

- valid intervals: 1137;
- median legal paths per interval: 17;
- mean `U`: +1.21%;
- median `U`: +0.86%;
- mean `B_periodic`: +5.52%;
- median `B_periodic`: +5.92%;
- `P(U > B_periodic) = 33.69%`;
- mean `U-B_periodic = -4.31%`;
- median `U-B_periodic = -4.84%`;
- maximum observed `U-B_periodic = +24.11%`.

Examples of intervals with large positive Strategy-vs-periodic separation still exist. They are useful state information even when the Strategy itself loses money, because periodic deployment may lose substantially more.

## Representation direction

Representation A is descriptive only. Do not use an Autoencoder yet.

Candidate Representation B remains conceptually:

`B = [L, U, B_periodic, B_random, Q10, Q25, Q50, Q75, Q90]`

with quantiles not yet frozen.

The distinction is:

- `L,U,B_i`: absolute profitability scale and baseline context;
- `Q` distribution: normalized shape of legal Strategy outcomes between the observed bounds.

Do not include exact algebraic duplicates such as `C=U-L` or `U-B_i` as independent AE inputs when their source variables are already present.

## What not to do next

Do **not**:

- optimize the Strategy;
- compare forced vs optional Addons as a strategy-quality study;
- reintroduce multiple addon-reference configurations;
- turn the random baseline into a Monte Carlo research project;
- move directly to CNN architecture;
- move directly to AE training before the current profitability-state representation is accepted.

## Immediate next research question

The current Strategy/path definition is considered locked unless a Strategy-rule bug is found.

The next question is:

> Across historical intervals, what structure distinguishes regions where the fixed Strategy has high `U`, or where `U-B_periodic` is strongly positive, from regions where it does not?

This is a **state-identification / profitability-representation** problem, not a Strategy-optimization problem.
