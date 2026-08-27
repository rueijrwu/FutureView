# AE Low-Dimensional Profitability-Space Test

## Research question

Before introducing a CNN or assuming any semantic meaning for a latent coordinate, test a narrower hypothesis:

> Do historical Strategy-1 outcome descriptors admit a stable low-dimensional representation?

The Autoencoder is used only to test compression of historical outcome descriptors. It is not trained to predict mean profit, win rate, future price, or any preassigned notion of information strength or tradable value.

## Historical descriptor space

For each fixed historical evaluation window W, Strategy-1 legal realized paths are generated first. From those paths compute descriptors such as:

- L_W: minimum realized Strategy profit;
- U_W: maximum realized Strategy profit;
- C_W = U_W - L_W;
- Q-distribution summaries, where Q_i = (U_W - E_i)/(U_W - L_W);
- market baseline B_hold;
- random-entry baseline distribution summaries.

The baseline family may expand later. More baselines are useful only when they have clear null/reference meaning; the Autoencoder is expected to reveal when different baselines mainly repeat the same information.

## Important control for algebraic redundancy

Known identities such as C = U - L create trivial redundancy. Therefore the first experiment compares:

1. a full descriptor set containing C;
2. a core descriptor set with the algebraically redundant C term removed.

A low-dimensional result is more meaningful if it persists in the core descriptor set rather than appearing only because exact mathematical identities were supplied as separate inputs.

## Autoencoder protocol

For each descriptor set:

1. order historical windows chronologically;
2. use the earliest 70% for training, the next 15% for validation, and the final 15% for test;
3. standardize using training-period statistics only;
4. train Autoencoders over several latent dimensions;
5. compare validation and chronological test reconstruction error;
6. select the smallest latent dimension whose validation reconstruction error is within 10% of the best tested validation error.

The exact 10% rule is a pilot rule, not a theoretical constant. The complete dimension sweep must be retained so later analysis does not depend on that single threshold.

## Post-hoc profit observation

Only after Z has been learned are profit statistics that were excluded from the Autoencoder input brought back for observation.

The first pilot keeps the following out of the AE input:

- mean realized path profit;
- median realized path profit;
- path win rate.

After Z is formed, their relationships with each latent coordinate are reported post-hoc. These quantities do not influence the formation of Z.

This ordering is deliberate:

```text
historical Strategy descriptors
        -> Autoencoder
        -> low-dimensional Z
        -> only then observe profit statistics
```

No causal or predictive relationship between Z and profit is assumed in advance.

## Stop condition

Do not proceed to CNN representation learning merely because an Autoencoder can reconstruct the descriptor vector.

The present stage should first establish whether:

1. a genuinely low-dimensional Z exists on chronological held-out data; and
2. after Z is fixed, any economically interesting profit structure appears in that space.

If the low-dimensional structure is weak or unstable, the representation hypothesis should be revised before proceeding.

## Initial empirical dataset

The first pilot reuses the existing Strategy-1 historical path-generation framework and the existing SMH daily-data research path. No frontend or web application is involved.
