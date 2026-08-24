# FutureView CNN Trend Research

This branch is a clean restart focused on SPY price/volume trend prediction.

## Phase 0: Codespaces CPU smoke test

The first run is for code debugging only. It is not a research result and should not be used to judge model quality.

In a GitHub Codespace on branch `cnn-trend-reset`:

```bash
python -m pip install -U pip
python -m pip install -e .
futureview-smoke
```

Expected behavior:

- PyTorch runs on `cpu`
- Model A accepts `[batch, 5, 50]` OHLCV tensors
- Model B splits price `[O,H,L,C]` and volume `[V]`, then fuses them
- both models output 4 trend scores for 15/30/45/60 trading-day horizons
- one Huber-loss forward/backward/optimizer step succeeds
- final line prints `SMOKE PASS`

This smoke test intentionally uses synthetic tensors so model/code errors are isolated from data-download and preprocessing issues.

## Current model definitions

- **Model A:** joint OHLCV multi-scale 1D CNN
- **Model B:** separate price and volume multi-scale 1D CNN branches with fusion
- **Input lookback:** 50 trading sessions
- **Outputs:** Trend15, Trend30, Trend45, Trend60
- **Execution policy for Phase 0:** CPU only

GPU/CUDA is deferred until repeated walk-forward training makes acceleration useful.
