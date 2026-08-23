# Score v2

FutureView Score v2 shifts the ranking objective from raw recent relative return toward sustainable 3-week-to-3-month leadership.

## Formula

```text
StockScore =
  25% RS20 percentile
+ 20% RS60 percentile
+ 20% TrendScore
+ 15% BreakoutScore
+ 10% VolumeScore
+ 10% PersistenceScore
- ExtensionPenalty
```

The positive component weights sum to 1.0. Extension is a separate penalty rather than a positive component.

## Persistence

PersistenceScore is the fraction of the most recent 20 market sessions in which a symbol appeared in the preliminary Top 50. Missing sessions count as zero. This favors sustained leaders over one-day or event-driven jumps while remaining fully point-in-time.

## Extension penalty

The hard eligibility limit remains 3 ATR above SMA20. Score v2 additionally applies a smooth quadratic penalty beginning at 1.5 ATR:

```text
scaled = clip((extension_atr - 1.5) / 1.5, 0, 1)
extension_penalty = 0.12 * scaled^2
```

Therefore moderately extended leaders remain eligible, while names near the 3 ATR hard limit receive a meaningful score reduction.

## Dashboard rank history

A missing 5-day or 20-day prior rank means the symbol was not present in that historical ranked universe. The dashboard displays this state as `NEW` rather than `0` so new entrants are not confused with unchanged ranks.

## Data implications

Changing Score v2 parameters does not require another Massive bootstrap. Raw OHLCV remains unchanged in R2; the scanner can recompute features, persistence, penalties, rankings, and Top 50 from retained history.
