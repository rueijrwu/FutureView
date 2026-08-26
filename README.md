# FutureView

FutureView studies whether causal price/volume structure can identify when a fixed trading strategy has favorable future economic outcomes.

## Canonical documentation

The project documentation is intentionally consolidated into two files:

- `RESEARCH.md` — research question, Strategy 1 research definition, L / μ / U / Q semantics, SPY/QQQ/SMH evidence, strategy-headroom finding, validation principles, and current research direction.
- `IMPLEMENT.md` — executable Strategy 1 semantics, label construction, data/holdout rules, model baselines, workflows, commands, reproducibility requirements, and historical implementation notes.

Use `RESEARCH.md` as the source of truth for **what FutureView means and what has been learned**.

Use `IMPLEMENT.md` as the source of truth for **how the repository implements and reproduces the research**.

## Current reduced question

```text
Given only causal OHLCV information observable at a formal Strategy 1 Entry,
can a model identify Entries whose future legal Strategy 1 paths have better
L (lower outcome), μ (mean return), and U (upper opportunity)?
```

A key current principle is to distinguish:

```text
strategy headroom != model skill
```

Before judging a model on SPY, QQQ, SMH, or another symbol, first establish how much entry-selection/timing value Strategy 1 itself creates relative to simple baselines.

## Documentation policy

Do not create new root-level Markdown files for each experiment. Research conclusions should be added to `RESEARCH.md`; implementation/workflow details should be added to `IMPLEMENT.md`.
