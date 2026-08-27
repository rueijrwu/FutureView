# FutureView Profitability Research Handoff

Last consolidated: 2026-08-27

The profitability research has been restarted from first principles. `Theory.md` is the authoritative theoretical statement; `Implementation.md` defines the implementation/program/API framework.

Current fixed objective:

> Under a fixed Strategy, use only a fixed window of historical price-volume information available before a legal Entry to estimate Entry profitability probability and expected profit.

Current definitions for a historical evaluation window W:

- `E_i`: realized profit associated with legal Entry i.
- `L_W = min(E_i)`: lowest observed legal-Entry profit.
- `U_W = max(E_i)`: highest observed legal-Entry profit.
- `C_W = U_W - L_W`.
- `Q_i = (U_W - E_i) / C_W` for `C_W > 0`.
- `B_W`: Strategy-independent baseline profit over the same window, using a fixed baseline rule.

Primitive predictive information is historical price and volume. Conventional technical indicators are treated as transformations of this primitive information rather than mandatory model inputs.

The intended learned structure is conceptually:

```text
past price-volume X
        -> learned representation Z
        -> Strategy profitability estimate
```

The separation between representation and profitability is conceptual and does not yet imply two separately trained models.

Do not resume the previous profitability Autoencoder experiment. Its implementation was removed from this restarted branch. Existing older results are historical exploratory work only.

## Immediate next question

Do not choose CNN architecture, latent dimension, loss, or technical indicators yet.

Begin with:

> What exactly should the learned representation Z represent? What information from raw historical price-volume data should it preserve so that it is useful for estimating the profitability of the fixed Strategy?
