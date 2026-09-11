# FutureView Cloud Runtime

Cloudflare Worker + Durable Object + R2 + D1 runtime for FutureView Replay.

The runtime is product agnostic. MES is the first configured product. Raw Databento archives live under R2 `raw/databento/<dataset>/<product>/<schema>/`; prepared replay shards currently use the existing production replay namespace for compatibility.
