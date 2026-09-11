# FutureView MES Replay Cloudflare Runtime

This directory contains the production Cloudflare runtime for the new FutureView MES replay application.

Production identity:
- Worker name: `futureview`
- R2 bucket: `futureview-data`
- Replay objects prefix: `mes-replay/v1/`
- D1 database: `futureview-mes-replay`
- Durable Object class: `ReplaySession`

The browser UI and API are served by the same Worker deployment. The legacy FutureView dashboard is no longer the production target.

## Data publish

Prepare locally or in CI:

```bash
cd mes-replay
mes-replay prepare --raw ../data/databento/mes/raw --runtime ./runtime
mes-replay cloud-export --runtime ./runtime --output ./runtime/cloud-export
```

Publish the generated cloud export under the `mes-replay/v1/` prefix in `futureview-data`, then deploy the Worker.

All backend timestamps remain UTC. Browser input and chart display use America/New_York (ET).
