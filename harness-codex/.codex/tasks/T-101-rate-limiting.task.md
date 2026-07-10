# Task: Add per-client rate limiting to the FastAPI layer

**Task ID:** T-101
**Branch:** agent/T-101-rate-limiting

## Goal

Cap API requests at 60/min per client, enforced in FastAPI middleware, with counters in Redis (shared with arq — separate keyspace `ratelimit:*`).

## Acceptance Criteria

- [ ] `RateLimitMiddleware` in `src/api/middleware.py`
- [ ] 429 response with `Retry-After` header when exceeded
- [ ] Limit configurable via `Settings.rate_limit_per_minute` (default 60)
- [ ] Counters expire — no unbounded Redis growth
- [ ] Unit tests: allow path, block path, window reset, header correctness
- [ ] Integration test: real Redis (testcontainers), concurrent clients isolated
- [ ] Coverage stays ≥ 80%; all gates green
- [ ] ADR `docs/adr/00X-rate-limiting.md` if design deviates from sliding window

## Context Files

```
core/src/api/main.py
core/src/settings.py
core/tests/unit/
core/tests/integration/test_stores.py   # testcontainers patterns
```

## Notes

- Sliding-window counter via Redis `INCR` + `EXPIRE`; no Lua unless tests show a race
- Key by client IP for now; leave a hook for API-key identity later
- TesterAgent first — tests MUST fail before implementation
