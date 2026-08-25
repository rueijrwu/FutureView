# Strategy 1 — Entry-Value Indicator Experiment

This document records the event-conditioned Strategy 1 entry-value experiment. The frozen Strategy 1 mechanics are unchanged.

## Research question

> Under the fixed Strategy 1 execution rules, can a model provide a useful score for whether the current legal Entry1 is worth taking?

The learning problem is intentionally narrower than the historical Oracle-value framing.

## Learning target

Each sample is a legal Strategy 1 `Entry1` event.

```text
input = causal OHLCV ending at the Entry1 close
learning target = realized return from taking this Entry1 and then following frozen Strategy 1
horizon = at most 30 trading sessions
```

The model is not asked to reproduce a perfect future pattern or imitate the Oracle.

## Oracle role

Oracle is benchmark only.

```text
OracleValue = future-known best legal Strategy 1 campaign in the same 30-session interval
```

The Oracle candidate set includes the current legal Entry1 itself. Dataset invariants enforce:

```text
OracleValue >= max(0, EntryReturn)
OracleRegret = OracleValue - EntryReturn >= 0
```

Therefore Oracle is a valid future-known upper benchmark for the current decision point. It is never used as a learning target.

## Fixed 5-year setup

```text
period = 5y
samples = 94 legal Entry1 events
lookback = 50 daily sessions
horizon = 30 sessions
train events = 40
OOS test events = 10 per fold
folds = 4
purge = at least 60 raw trading sessions
seeds = 20260821,20260822,20260823,20260824,20260825
no random split
```

Dataset baseline:

```text
entry mean = +0.000948
entry median = +0.000297
entry win rate = 51.1%
Oracle mean = +0.009501
mean regret = +0.008553
```

The unconditional legal Entry1 edge is therefore small. The useful-model question is whether high model scores separate materially better entries from this baseline.

## Models compared

```text
CNN_A                  2,764 params
CNN_B                  3,730 params
CNN_A_PLUS_SUMMARY20   2,924 params
SUMMARY_RIDGE
CONSTANT
```

## Entry-return results

### Summary Ridge

```text
mean Spearman = -0.130303
mean top20 lift = +0.002891
mean MAE = 0.033615
```

Ridge is not a stable ranking model for entry return in this event-conditioned formulation.

### CNN A

Seed summaries:

```text
seed 20260821  Spearman +0.209091  top20 lift +0.002437
seed 20260822  Spearman +0.478788  top20 lift +0.011640
seed 20260823  Spearman +0.039394  top20 lift +0.003824
seed 20260824  Spearman -0.057576  top20 lift +0.000749
seed 20260825  Spearman +0.042424  top20 lift +0.000749
```

Cross-seed:

```text
Spearman mean = +0.142424
Spearman std = 0.188786
positive seeds = 4/5

top20 lift mean = +0.003880
std = 0.004047
positive seeds = 5/5

MAE mean = 0.024417
```

Interpretation: CNN A is the only tested model with a positive top-20% realized-entry-return lift in every seed. This is the strongest current evidence that the model may provide a useful Entry Quality Score under Strategy 1.

However, fold-level ranking remains unstable. In particular, Fold 2 is adverse for most CNN A seeds. The result is therefore promising evidence, not yet a robust pass.

### CNN B

```text
Spearman mean = +0.001212
std = 0.102791

top20 lift mean = -0.000512
positive seeds = 3/5

MAE mean = 0.022377
```

CNN B does not establish useful entry-quality ranking.

### CNN A + Summary20

```text
Spearman mean = -0.049697
std = 0.237655

top20 lift mean = -0.000545
positive seeds = 3/5

MAE mean = 0.097443
```

The direct Summary20 fusion fails again and should remain hold/fail.

## Oracle-Regret benchmark

The canonical Oracle benchmark metric is now:

```text
OracleRegret = OracleValue - EntryReturn
```

Lower regret is better. Since Oracle is the future-known best legal solution at the same decision point, regret measures how much return the current entry leaves on the table relative to that upper benchmark.

The regret-first analysis does **not** train on Oracle or regret. Models are still trained only on `EntryReturn`. Regret is evaluated after OOS predictions are produced.

Primary regret diagnostics:

```text
overall_regret_mean
  mean OracleRegret across all legal OOS Entry1 events

top_regret_mean
  mean OracleRegret among the model's top-20% scored entries

regret_reduction_vs_all
  overall_regret_mean - top_regret_mean
  positive is better

top_oracle_match_rate
  fraction of top-scored entries with regret approximately zero
  no additional tunable threshold; numerical epsilon only
```

The intended indicator test is:

> If a model's high-score entries have higher realized EntryReturn **and** lower OracleRegret than the full legal-entry set, the score is useful both economically and relative to the future-known benchmark.

Raw capture ratio is no longer a primary metric because `EntryReturn / OracleValue` becomes unstable when OracleValue is close to zero.

## Regret-first 5-year result

The same 94 legal Entry1 samples, four chronological OOS folds, five seeds, 40-event training window, 10-event OOS test blocks, and 60-session raw purge were reused. The learning target remained `EntryReturn`; only the benchmark layer changed.

### Summary across models

```text
SUMMARY_RIDGE
  entry Spearman mean        -0.130303
  top20 lift mean            +0.002891
  top regret mean            0.006868
  regret reduction vs all   -0.000259
  Oracle match rate mean     0.375

CNN_A
  entry Spearman mean        +0.142424
  top20 lift mean            +0.003880
  top regret mean            0.003902
  regret reduction vs all   +0.002706
  Oracle match rate mean     0.525

CNN_B
  entry Spearman mean        +0.001212
  top20 lift mean            -0.000512
  top regret mean            0.005982
  regret reduction vs all   +0.000626
  Oracle match rate mean     0.400

CNN_A_PLUS_SUMMARY20
  entry Spearman mean        -0.049697
  top20 lift mean            -0.000545
  top regret mean            0.006326
  regret reduction vs all   +0.000282
  Oracle match rate mean     0.350
```

### Interpretation

CNN A is the only tested model that simultaneously shows:

```text
positive mean entry-return ranking
positive top20 realized-return lift
positive regret reduction of meaningful size
lowest mean top regret among the learned models
highest mean Oracle match rate
```

Its top-scored entries reduce mean regret by approximately:

```text
0.002706 = 0.2706 percentage points of initial capital
```

relative to the full legal-entry set on the evaluated OOS folds.

This strengthens the Entry Quality Score interpretation. CNN A is not merely selecting entries with somewhat higher realized return; its high-score subset is also closer, on average, to the future-known Strategy 1 optimum.

However, the result is still not fully regime-stable. Fold 2 remains adverse for several CNN A seeds, including negative regret reduction for seeds `20260821`, `20260824`, and `20260825`. Therefore the correct status remains:

```text
CNN A = promising Entry Quality Score
        stronger evidence after regret analysis
        not yet robustly established across regimes
```

The terminal `S1 ENTRY_REGRET PASS` emitted by the runner means the experiment completed successfully; it should not be interpreted as a scientific pass of the model hypothesis.

## Current model status

```text
CNN A:
  primary entry-quality model
  promising / stronger evidence after Oracle-Regret analysis
  not yet robustly established

Summary Ridge:
  no longer strong under the entry-value target
  negative mean regret reduction

CNN B:
  fail / hold

CNN A + Summary20:
  fail / hold
```

## Metric interpretation

Primary trading-indicator metrics are:

```text
1. top-score realized Entry Return
2. top-score lift versus all legal Entry1 events
3. top-score win rate
4. top-score OracleRegret
5. regret reduction versus all legal entries
6. Oracle match rate
7. fold stability
8. seed stability
9. Spearman as a ranking diagnostic
```

MAE is secondary. A model can be useful as an indicator without producing well-calibrated percentage-return estimates.

## Current conclusion

The historical question was whether a CNN could predict the future best Oracle opportunity. The current question is more realistic:

> Can the model score the quality of this legal entry under fixed Strategy 1 execution?

On the current five-year, four-fold, five-seed experiment, CNN A gives the strongest evidence so far. Its top-20% entry-return lift is positive in all five seeds, and the regret-first analysis shows the strongest average reduction in distance to the future-known optimum.

The evidence is now stronger than under entry-return lift alone, but Fold 2 prevents a robust cross-regime claim. The next scientific focus should therefore be regime stability of the score rather than further gate or threshold tuning.
