# MES Replay

Standalone containerized MES historical bar replay application. It does not import the legacy `futureview` Python package.

## Data

Raw Databento monthly `*.ohlcv-1m.dbn.zst` files are read from the repository LFS archive at `../data/databento/mes/raw` and mounted read-only into the container. Prepared Parquet files and the manifest live under `mes-replay/runtime/` and are not committed.

## First run

```bash
git lfs pull
cd mes-replay
docker compose build
docker compose run --rm replay prepare --raw /data/raw --runtime /data/runtime
docker compose up
```

Open <http://127.0.0.1:8787>.

## Replay semantics

- 5-minute bars are the replay clock.
- The browser never receives bars after the current replay cursor.
- `1x` = 1 bar/second, `5x` = 5 bars/second, up to `100x`; `Max` processes as fast as the engine permits.
- High speeds may be sent to the browser in ordered batches; the engine never skips bars.
- The first version replays an explicit real MES contract. Causal front-contract selection and rollover are separate later layers.

## Tests

```bash
docker compose run --rm --entrypoint pytest replay -q /app/tests
```
