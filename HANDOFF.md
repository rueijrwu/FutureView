# FutureView Replay

Primary branch: `master`.

FutureView is now a generic historical market replay/backtest platform. MES is the first configured product, not the engine identity.

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
futureview-replay fetch-raw --product MES --from 2019-05 --to 2019-06
futureview-replay prepare --product MES
futureview-replay serve --manifest runtime/MES/manifest.json
```

Raw Databento archives are migrating from Git LFS to R2. Final raw source of truth:

```text
futureview-data/raw/databento/<DATASET>/<PRODUCT>/<SCHEMA>/
```

Local data lives under `.local-data/` and is not committed.

## Invariants

- Browser never receives bars beyond replay cursor.
- Actual contract identity is preserved.
- 5m is the primary replay clock; 1m remains available for later realistic fills.
- ET for user-facing time; UTC for storage/protocol.
- Playback speed never changes bar resolution or logical ordering.
- Manual and automated trading must eventually share one execution engine.

## Cloud

Cloudflare Worker + Durable Object + R2 + D1 remains the production architecture. The current production replay-shard namespace `mes-replay/v1` is temporarily retained for compatibility while raw-data storage is migrated and product selection is generalized.

## Next

1. Finish and verify raw DBN archive migration to R2.
2. Remove `.dbn.zst` and Git LFS tracking from `master`.
3. Switch CI/deploy to `futureview-replay fetch-raw` from R2.
4. Add product selection/catalog so MES, MNQ, NQ, ES, etc. share the same replay engine.
5. Add shared Order/Fill/Position/Account execution primitives.
