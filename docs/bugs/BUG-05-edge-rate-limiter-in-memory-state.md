# BUG-05: Ephemeral In-Memory Rate Limiting in Serverless / Edge Environments

**Severity:** P2 (Medium)  
**Component:** `apps/web/middleware.ts` & `apps/api/src/radar_api/security.py`  
**Found in:** Sprint 2 Audit  
**Type:** Distributed Systems Limitation / Security Edge Case

---

## 1. Description

Both the Next.js edge middleware and the FastAPI backend rely on in-memory data structures to track client IP request windows:

- In [`apps/web/middleware.ts`](file:///Users/shine/Documents/Shine's%20Personal%20Folder/Code/Tel-U/radar-ai/apps/web/middleware.ts):
  ```typescript
  const ipBuckets = new Map<string, number[]>();
  ```
- In [`apps/api/src/radar_api/security.py`](file:///Users/shine/Documents/Shine's%20Personal%20Folder/Code/Tel-U/radar-ai/apps/api/src/radar_api/security.py):
  ```python
  class SlidingWindowRateLimiter:
      def __init__(self, max_keys: int = 4096) -> None:
          self._buckets: dict[str, deque[float]] = {}
          self._lock = Lock()
  ```

### Vulnerability / Limitation in Distributed Production:
1. In serverless platforms (e.g. Vercel Edge, AWS Lambda, Cloud Run), each edge region and each concurrent container instance maintains its own isolated memory space.
2. An attacker can distribute requests across different serverless instances or regions to bypass the 60 req/min limit (`60 * N instances`).
3. Whenever an edge instance cold-starts or recycles, `ipBuckets` resets to empty, instantly resetting all rate limits for all client IPs.

---

## 2. Impact Analysis

- **Security & DoS Resistance**: Rate limits are only effective against a single warm instance; ineffective against distributed or multi-region scraping.
- **Resource Protection**: Heavy endpoints (e.g. DICOM series staging and GPU inference) could be saturated if deployed behind a multi-worker gateway without shared state.

---

## 3. Recommended Remediation

For production deployments:
1. Support a distributed key-value store (e.g. Redis / Upstash / Cloudflare KV) using atomic sliding window tokens (`ZADD` / `ZREMRANGEBYSCORE`).
2. Provide a graceful fallback to the in-memory map when `REDIS_URL` or `UPSTASH_REDIS_REST_URL` is omitted (local development mode).

