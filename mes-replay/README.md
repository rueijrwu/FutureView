# MES Replay

Standalone MES historical bar replay application. It does not import the legacy `futureview` Python package.

## Data

Raw Databento monthly `*.ohlcv-1m.dbn.zst` files are read from the repository LFS archive at `../data/databento/mes/raw`. Prepared Parquet files, replay manifests, and cloud-export shards live under `mes-replay/runtime/` and are not committed.

## Local setup

```bash
git lfs pull
cd mes-replay
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[test]'
```

Prepare the MES archive:

```bash
mes-replay prepare --raw ../data/databento/mes/raw --runtime ./runtime
```

For a quick smoke test, add `--limit 1`.

Start the local replay UI:

```bash
mes-replay serve --manifest ./runtime/manifest.json --host 127.0.0.1 --port 8787
```

Open <http://127.0.0.1:8787>.

## Replay semantics

- 5-minute bars are the replay clock.
- The browser never receives bars after the current replay cursor.
- `1x` = 1 bar/second, `5x` = 5 bars/second, up to `100x`; `Max` processes as fast as the engine permits.
- High speeds may be sent to the browser in ordered batches; the engine never skips bars.
- The first version replays an explicit real MES contract. Causal front-contract selection and rollover are separate later layers.

## Cloud export

```bash
mes-replay cloud-export --runtime ./runtime --output ./runtime/cloud-export
```

The generated compact gzip shards are suitable for the Cloudflare R2-backed replay runtime under `mes-replay/cloudflare/`.

## Tests

```bash
pytest -q
```
