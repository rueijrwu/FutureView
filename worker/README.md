# FutureView Worker API

The Worker is the dynamic read layer between the browser and the private R2 research store.

Current API contract:

- `GET /api/health` — service health.
- `GET /api/rankings/latest` — latest dashboard-ready ranking payload read from R2.

The Worker must not recompute strategy logic. Python remains the canonical research engine; the Worker only reads published research outputs.
