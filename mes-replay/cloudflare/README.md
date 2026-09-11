# Cloudflare MES Replay

Standalone cloud visualization/runtime for `mes-replay`.

Architecture:

- Cloudflare Assets serves the chart UI.
- R2 bucket `futureview-data` stores replay data only under `mes-replay/v1/`.
- Durable Object `ReplaySession` owns the active cursor and WebSocket. The browser never receives unreleased future bars.
- D1 database `futureview-mes-replay` records replay session snapshots and later trade history.
- The legacy FutureView Worker/D1 schema is not imported.

## Build R2 replay data

After local DBN preparation:

```bash
cd mes-replay
docker compose run --rm replay cloud-export --runtime /data/runtime --output /data/runtime/cloud-export
```

The export produces `manifest.json` plus compressed monthly contract shards. Upload them under the R2 prefix `mes-replay/v1/`.

## R2 upload

With Wrangler authenticated, from `mes-replay/cloudflare`:

```bash
./publish-r2.sh ../runtime/cloud-export
```

## Local Cloudflare check

```bash
npm install
npm run check
npm run dry-run
```

## Production deploy

The repository workflow `MES Replay Cloudflare Deploy` is manual (`workflow_dispatch`) and resolves/creates the dedicated D1 database before applying migrations and deploying the standalone Worker.
