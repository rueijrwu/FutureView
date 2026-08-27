# FutureView / Strategy-1 Layer-1 Path Sample-Space Handoff

Last consolidated: 2026-08-27

## 1. Core objective

Strategy-1 itself already embeds a preference for particular market price/volume structures through its entry, add-on, and exit rules. Layer 1 should therefore avoid adding further price/volume structural information when evaluating the strategy's realized historical profitability.

For a fixed historical window `W`, Layer 1 asks:

> Given Strategy-1's legal realized outcomes in this window, what does the strategy's realized profit capability look like?

Layer 1 is intended as a pre-filter. It should identify intervals in which Strategy-1 itself lacks sufficient realized profit expectation without first explaining the market structure that caused that result.

Layer 2 is separate and later asks which causal price/volume structures correspond to different Strategy-1 profitability states.

The methodological boundary is therefore:

```text
Layer 1: realized Strategy-1 outcomes / profits
Layer 2: price-volume structure explaining or predicting those outcomes
```

If Layer 1 itself filters using additional price/volume structure, Layer 2 would inherit a selection-biased market sample.

## 2. Strategy-1 already implies market-structure preference

The strategy includes conditions such as moving-average alignment for Entry, breakout conditions for add-ons, and MA5/MA10 conditions for exits.

Therefore the strategy is not market-structure neutral. Its realized profitability across history already reflects whether the surrounding market structure happened to suit the strategy.

Layer 1 does not need to explain that structure. Its job is to observe the realized consequence of applying the fixed strategy.

## 3. Fundamental issue: path populations are nested

The current path definition needs to be reconsidered before further Autoencoder interpretation.

Let:

```text
S_E       = Entry opportunities
S_EA1     = Entry opportunities whose future evolution also reaches Add1
S_EA1A2   = Entry opportunities whose future evolution reaches Add1 and Add2
```

Then structurally:

```text
S_EA1A2 ⊆ S_EA1 ⊆ S_E
```

These are not three independent populations.

At the Entry time, all members of these sets satisfy the same Entry requirement. Whether a particular Entry later reaches Add1 or Add2 is only known from its future evolution.

Therefore an Entry that later reaches Add1 is still a member of the original Entry population; an Entry that reaches Add2 is also a member of both preceding populations.

Treating `Entry only`, `Entry + Add1`, and `Entry + Add1 + Add2` as unrelated independent categories may therefore misrepresent the Strategy-1 outcome sample space or double-count nested outcomes.

## 4. Entry opportunity versus future execution branch

A useful distinction for the next discussion is:

### Entry opportunity

A historical time point at which Strategy-1's Entry condition is satisfied.

### Future execution branch

After that Entry, the future can realize different legal strategy evolutions, for example:

```text
E -> Exit
E -> A1 -> Exit
E -> A1 -> A2 -> Exit
```

with potentially different legal exit branches.

The unresolved question is how these branches should enter the Layer-1 probability/sample space.

They might be:

- alternative outcomes associated with one Entry opportunity;
- independent realized paths;
- or elements of a hierarchical/nested representation.

No choice is currently frozen.

## 5. Avoid introducing additional market structure into Layer 1

The previous representation included execution sequences and therefore implicitly included timing information such as when add-ons and exits occurred and how long capital remained deployed.

This now needs reconsideration.

Path duration and execution timing are produced jointly by the strategy rules and future price evolution. Therefore including them directly in Layer 1 can indirectly encode market dynamics that Layer 2 is intended to analyze.

For now, do not assume that any of the following belongs in the final Layer-1 representation:

```text
price path
volume
technical indicators
path duration
entry-to-add timing
entry-to-exit timing
capital-exposure sequence
```

This is not a claim that these variables are useless. It means their inclusion must be justified against the Layer-1 / Layer-2 separation.

## 6. Clean observable: realized profit

For a legal Strategy-1 outcome `i`, define:

```text
R_i = realized profit of outcome i
```

For a fixed window `W`, the cleanest current object is the collection of realized Strategy-1 profits:

```text
R_W = {R_1, R_2, ..., R_n}
```

The central question is how to define the independent elements of this set correctly given the nested Entry/Add1/Add2 structure.

Existing descriptive bounds remain:

```text
L_W = min(R_W)
U_W = max(R_W)
```

They describe observed realized-profit bounds only. No `good`, `bad`, or `neutral` classification is imposed.

## 7. Autoencoder and z are exploratory, not the current foundation

Previous pilots used an Autoencoder to compress fixed-window Strategy-1 path/profit data into a latent coordinate `z`, and descriptive relationships between `z`, `L`, `U`, and realized profits were examined.

Those experiments demonstrated that the implemented outcome representation contains low-dimensional structure.

However, interpretation of `z` is now paused because a more fundamental issue comes first:

> What exactly constitutes one independent Strategy-1 outcome/path in the Layer-1 sample space?

If nested paths are represented incorrectly, later interpretation of `z`, path count `N`, or any learned distribution can inherit that definition error.

Therefore existing Autoencoder results are exploratory evidence, not a commitment to the current representation.

## 8. N is downstream of the path-definition problem

Previous work examined:

```text
N(W) = number of legal paths in W
```

But the meaning of `N` depends on what is counted as an independent path.

If `S_EA1 ⊆ S_E`, counting an Entry observation and its later Add1 branch as independent observations may change `N` by construction.

Therefore the immediate question is not whether `N` should be included or removed. The prior question is:

> What is one independent Strategy-1 outcome?

## 9. Current research boundary

The clean current statement is:

> Layer 1 should use Strategy-1's legal realized profit outcomes to understand the strategy's profitability within a fixed historical window, while avoiding additional price/volume structure that could pre-filter the market structures later studied by Layer 2.

Before further modeling, the Strategy-1 outcome/path sample space must be defined correctly, especially the nested relationship:

```text
S_EA1A2 ⊆ S_EA1 ⊆ S_E
```

## 10. Starting question for the next discussion

Do not begin with Autoencoder architecture, latent dimension, `z`, `N`, classification, or Layer 2.

Begin here:

> Given one legal Strategy-1 Entry, define Entry, Add1, Add2, and Exit outcomes from the perspective of sets and a probability sample space. Resolve how the nested relation `S_EA1A2 ⊆ S_EA1 ⊆ S_E` should be represented without introducing additional price/volume structure into Layer 1.
