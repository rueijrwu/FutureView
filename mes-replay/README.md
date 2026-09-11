# MES Replay

Standalone MES historical replay and backtest application. This is the new primary FutureView direction.

## Data

Raw Databento monthly `*.ohlcv-1m.dbn.zst` files live under `../data/databento/mes/raw` via Git LFS. Prepared Parquet and replay manifests live under `mes-replay/runtime/` and are not committed.

## Local setup

```bash
git lfs pull
cd mes-replay
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[test]'
```

## Prepare replay data

One-month smoke:

```bash
mes-replay prepare --raw ../data/databento/mes/raw --runtime ./runtime --limit 1
```

Full archive:

```bash
mes-replay prepare --raw ../data/databento/mes/raw --runtime ./runtime
```

## Run locally

```bash
mes-replay serve --manifest ./runtime/manifest.json --host 127.0.0.1 --port 8787
```

Open <http://127.0.0.1:8787>.

## Replay semantics

- 5-minute bars are the replay clock.
- The browser never receives bars after the current replay cursor.
- UI input, chart axis, status and contract ranges display America/New_York time (ET); storage and backend timestamps remain UTC.
- `1x` = 1 bar/second, `5x` = 5 bars/second, up to `100x`; `Max` processes as fast as the engine permits.
- High speeds may be sent to the browser in ordered batches; the engine never skips bars.
- The first version replays an explicit real MES contract. Causal front-contract selection and rollover remain separate layers.

## Tests

```bash
pytest -q tests
```

## Cloudflare

The production web visualization is intended to replace the old FutureView site and use the existing Cloudflare/R2 infrastructure.
