# FutureView Replay Handoff

Primary branch: `master`

FutureView is now a generic historical market replay/backtest platform. `MES` is the first configured product, not the engine identity.

## Current structure

```text
src/futureview_replay/
tests/
cloudflare/
data/raw_sources.json
.github/workflows/
```

Python package: `futureview_replay`
CLI: `futureview-replay`

## Raw data

Raw Databento DBN files are no longer stored in Git/LFS. The source of truth is Cloudflare R2:

```text
futureview-data/raw/databento/<DATASET>/<PRODUCT>/<SCHEMA>/
```

Current MES source:

```text
raw/databento/GLBX.MDP3/MES/ohlcv-1m/
```

The R2 manifest contains per-file byte size, SHA-256 and object key. Git stores only the source catalog/digest in `data/raw_sources.json`.

Verified migration snapshot:

```text
files: 89
total bytes: 52,183,820
R2 manifest SHA-256: a90b528a1f4d9da4b886bb46581d8b570f65e279108a97cf668708b873e1f47b
```

## Local workflow

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
futureview-replay fetch-raw --product MES --from 2019-05 --to 2019-06
futureview-replay prepare --product MES
futureview-replay serve --manifest runtime/MES/manifest.json
```

Local raw/cache data belongs under `.local-data/` and must not be committed.

## Replay invariants

- 5m main replay clock.
- actual futures contract identity preserved.
- browser never receives future bars past the cursor.
- ET for display, UTC for storage/protocol.
- playback speed never changes bar resolution or logical order.
- 1m data retained for later realistic fill simulation.
- synthetic/back-adjusted prices must never be execution truth.

## Cloud

Production architecture remains Cloudflare Worker + Durable Object + R2 + D1. The public application is FutureView. The existing replay-shard prefix `mes-replay/v1` is temporarily retained only for production compatibility; package/runtime identity is generic.

## CI / deployment

Relevant workflows:

```text
.github/workflows/replay-python.yml
.github/workflows/replay-cloudflare-check.yml
.github/workflows/replay-cloudflare-deploy.yml
```

CI/deploy fetch raw data from R2 using `futureview-replay fetch-raw`; they no longer depend on Git LFS raw DBN files.

## Next

1. Add a product catalog/selector so MES, MNQ, NQ, ES, etc. can share the same UI/runtime.
2. Migrate legacy replay shard namespace from `mes-replay/v1` to a product-aware generic layout when convenient.
3. Add shared Order / Fill / Position / Account primitives.
4. Add manual Market Buy/Sell/Flatten.
5. Add 1m execution simulation, tick rounding, configurable commission/slippage, then Limit/Stop and causal rollover.
