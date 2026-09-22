# Order types and fill conventions

The simulator supports **market**, **limit**, **stop** and **stop-limit** orders, and any of the four can carry a **bracket** — a take-profit, a stop-loss, or both, attached to the entry.

Every fill rule below is a *modelling convention*, not a lookup. The replay source is
1-minute OHLCV (`src/futureview_replay/cloud_export.py`) — there are no tick prints, no
bid/ask and no intrabar sequence. We can know that a minute traded through a price; we
can never know when inside that minute, or whether the high or the low came first. The
conventions here are chosen to be honest rather than flattering, because a simulator
that fills you at your best case teaches the wrong lesson.

## Causality

Orders are evaluated inside the canonical bar-release loop (`replay-session.js`), against
the bar being released, one bar at a time. Nothing reads a later bar. Two consequences
worth stating:

- Evaluation runs on every canonical **1-minute** bar even when the chart is showing 5m,
  30m, 4h or 1D candles. Display aggregation is a separate layer, so a limit that fills
  in the second minute of a 5-minute candle fills at that minute.
- An order becomes eligible starting with the **next** released bar. You can never place
  an order on a bar you have already seen and have it fill on that same bar.

## Fill rules

Let `o`, `h`, `l` be the open, high and low of the bar being released.

| Type | Trigger | Fill price |
| --- | --- | --- |
| Market | next released bar | `o` |
| Buy limit `L` | `o <= L` or `l < L` | `min(L, o)` |
| Sell limit `L` | `o >= L` or `h > L` | `max(L, o)` |
| Buy stop `S` | `h >= S` | `max(S, o)` |
| Sell stop `S` | `l <= S` | `min(S, o)` |
| Stop-limit | stop rule above | rests as a limit from the **next** bar |

Three deliberate asymmetries:

- **Limits require the bar to trade through the price; stops trigger on a touch.** A stop
  is a market trigger. A resting limit sitting exactly at a bar's extreme is behind a
  queue we cannot model, so a bar whose low merely touches your buy limit is not a fill.
- **Limits get open improvement.** A bar that opens through your limit fills at the open,
  which is better than your price. A marketable limit therefore behaves like a market
  order, as it should.
- **Stops eat the gap.** A bar that gapped straight through your stop never traded at it,
  so the fill is the open, which is worse than your stop. This is the case where the
  naive convention lies to you about your worst risk.

A stop-limit does not fill on the bar that triggered it. With no intrabar sequence we
cannot claim the limit was still reachable after the stop printed within the same minute.

## Evaluation order within one bar

Several orders can trigger on the same minute, and the position maths is order-dependent —
whether a stop or a limit is applied first can decide whether you end up flat or flipped.
The order is fixed and tested:

1. stops and stop-limits
2. market orders
3. limits

then by placement sequence within each group.

## Costs

Charged per fill, in their own buckets rather than folded into the fill price, so the
average price stays readable as the price that actually printed and `total_pnl` subtracts
the costs explicitly.

| Product | Commission (per contract, per side) | Slippage |
| --- | --- | --- |
| MES | $0.62 | 1 tick = $1.25 per contract |
| ES | $2.25 | 1 tick = $12.50 per contract |

Slippage applies to anything that reaches the market — market orders and triggered stops.
**Resting limits do not slip**: they fill at their own price or better, or they do not
fill. A stop-limit fills as a limit, so it does not slip either.

Both rates live in `PRODUCT_SPECS` in `cloudflare/worker/replay-session-core.js` and are
published in the account snapshot as `commission_per_side` and `slippage_ticks`.

## Validation

- Prices must sit on the contract's tick grid (0.25).
- A buy stop must be above the current price and a sell stop below it. A stop already
  through the market is an order-entry mistake, not a stop.
- Quantity is an integer from 1 to 100.

## Bracket orders

A bracket attaches a take-profit and/or a stop-loss to an entry order of any type. Both
legs are optional independently — a take-profit alone, a stop-loss alone, or both.

- **The legs do not exist until the entry fills.** Placing a bracket creates one order,
  the entry. Its take-profit and stop-loss prices ride along on that order, unused,
  until it fills; only then are the two exit orders created.
- **They start eligible on the next bar, never the one that filled the entry.** Same rule
  as a triggered stop-limit, same reason: nothing gets to react to a move it wasn't
  resting for yet. A bar that would have hit the stop-loss instantly does not touch it if
  that bar is also the one that filled the entry.
- **The two legs are one-cancels-other (OCO).** A fill on either cancels the other,
  evaluated in the same pass as the fill so both can never fill from the same bar's move.
  Stops are still evaluated before limits within a bar (see above), so if both legs would
  trigger on the same bar the stop-loss wins and the take-profit is cancelled unfilled.
- **Cancelling a leg by hand does not cancel its sibling.** Only a fill triggers the OCO
  cancellation. Cancelling one leg yourself leaves the other working, so a bracket can be
  pared down to a single protective order on purpose.
- **Prices are validated against the entry, not the current market**, using the entry's
  own price for a limit or stop entry, or the last traded price for a market entry: a buy
  bracket's take-profit must be above that reference and its stop-loss below it (mirrored
  for a sell bracket). This catches the order backwards, not catches it too late.
- **Quantity always matches the entry's fill.** There is no partial-fill model, so the
  exit legs close exactly what the entry opened. A bracket does not account for a position
  changed by other orders in the meantime — see Not implemented.

## Lifecycle

Working orders rest until they fill or are cancelled, and survive across bars, pauses and
reconnects. `Restart` and `Clear` cancel everything. There is no DAY time-in-force: an
order works for as long as the replay does, unless auto-flatten (below) cancels it first.

Orders are persisted to D1 in `trade_orders` (migrations `0006_order_types.sql` and
`0007_bracket_orders.sql`), and each fill records the `order_id` and `order_type` that
produced it, plus `bracket_role` when the fill came from a bracket leg.

## Auto-flatten at session end

Selectable per session ("Auto-flatten at session end" checkbox, on by default; live-toggled
mid-session with no restart, via the `set_auto_flatten` websocket command). When on, the
moment the replay crosses the CME daily session roll (18:00 ET — `SESSION_ROLL_HOUR_ET` in
`resolver.py`, mirrored as `sessionDateAt` in `replay-session-core.js`), any open position is
closed at a market order against the outgoing session's last traded price, paying the same
commission and one tick of slippage as any other market fill, and every resting order
(entries and bracket legs alike) is cancelled — never carried into the next day's session.
This also closes the known reduce-only gap for the forced case: a resting bracket's legs are
cancelled along with everything else, not left to trade against a position that no longer
exists. When off, positions and resting orders carry through the roll exactly as before.

## Not implemented

Trailing stops, reduce-only, order modification, and any account-level protection against
a bracket's legs outliving the position they were meant to close (if you flatten manually
while a bracket is still working, its legs keep working and will trade against whatever
position exists when they fire). Cancelling and re-placing is the current path for a
change to any resting order, bracket legs included.
