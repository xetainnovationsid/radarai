# BUG-10: Sliding Window Rate Limiter Inactive Bucket Eviction Starvation & Process Memory Retention

**Severity:** P2 (Medium)  
**Component:** `apps/api/src/radar_api/security.py`  
**Found in:** Sprint 2 Hardening Audit  
**Type:** In-Memory Leak / Eviction Starvation  
**Notice:** Research prototype only — **NOT FOR CLINICAL USE**.

---

## 1. Description

In [`apps/api/src/radar_api/security.py`](file:///Users/shine/Documents/Shine's%20Personal%20Folder/Code/Tel-U/radar-ai/apps/api/src/radar_api/security.py), the `SlidingWindowRateLimiter` maintains a dictionary mapping client IP addresses to timestamps in a `deque[float]`:

```python
# Lines 516-559 in security.py:
class SlidingWindowRateLimiter:
    """Thread-safe, bounded-memory sliding-window rate limiter."""

    def __init__(self, max_keys: int = 4096) -> None:
        self._max_keys = max_keys
        self._buckets: dict[str, deque[float]] = {}
        self._lock = Lock()

    def check(
        self, key: str, *, limit: int, window_seconds: float = 60.0
    ) -> tuple[bool, int, int]:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            # Stale key eviction ONLY triggered if key not in buckets AND capacity exceeded:
            if key not in self._buckets and len(self._buckets) >= self._max_keys:
                stale_keys = [
                    k
                    for k, timestamps in self._buckets.items()
                    if not timestamps or timestamps[-1] <= cutoff
                ]
                for stale in stale_keys:
                    self._buckets.pop(stale, None)
                if len(self._buckets) >= self._max_keys:
                    oldest_key = next(iter(self._buckets))
                    self._buckets.pop(oldest_key, None)

            bucket = self._buckets.setdefault(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            # ...
```

### Root Cause
Stale bucket eviction is gated exclusively behind:
```python
if key not in self._buckets and len(self._buckets) >= self._max_keys:
```
This causes an **eviction starvation** flaw:
1. **Low to Moderate Traffic Environments**: When fewer than 4,096 distinct client IPs connect to the API, `len(self._buckets) >= self._max_keys` is never met.
2. **Ephemeral Client IPs**: IPs that sent requests hours or days earlier (e.g. dynamic DHCP, mobile carrier rotation, transient health check proxies, or security port scanners) remain in `self._buckets` forever, holding an empty or stale `deque` object.
3. **Empty Bucket Retention**: When `bucket.popleft()` drains all expired timestamps, the key is **not** deleted from `self._buckets`. Thus `self._buckets` grows monotonically up to 4,096 entries and never shrinks, even when completely idle.
4. **Single-Lock Lock Contention**: Under concurrent requests, acquiring `self._lock` to evaluate `stale_keys = [k for k, timestamps in self._buckets.items() ...]` performs an $O(N)$ linear scan of up to 4,096 dictionary items while holding the global mutex, introducing latency spikes on API endpoints.

---

## 2. Reproduction Steps

1. In Python REPL, instantiate `limiter = SlidingWindowRateLimiter(max_keys=4096)`.
2. Simulate 2,000 requests from distinct IPs:
   ```python
   for i in range(2000):
       limiter.check(f"192.168.1.{i}", limit=60)
   ```
3. Sleep for 65 seconds (past the 60-second sliding window).
4. Inspect `len(limiter._buckets)`: It remains `2000`.
5. Perform requests from already registered IPs: `len(limiter._buckets)` remains `2000`. The expired entries are never released from process memory.

---

## 3. Impact Analysis

- **Memory Overhead**: Persistent dictionary retention of thousands of empty deques over long-running API daemon instances.
- **Lock Jitter**: Periodic $O(N)$ iteration across 4,096 keys during capacity overflow blocks incoming requests on fast-path endpoints (`/v1/auth/me`, `/v1/studies`).

---

## 4. Recommended Remediation

1. Delete empty buckets during the per-key check when all timestamps have expired:
   ```python
   while bucket and bucket[0] <= cutoff:
       bucket.popleft()
   # If empty after pruning and not being added to:
   ```
2. Schedule a low-frequency periodic sweep (or randomized 1/100 request sweep) to evict all keys whose `timestamps[-1] <= cutoff`:
   ```python
   if len(self._buckets) > 256 and (random.random() < 0.02):
       stale = [k for k, v in self._buckets.items() if not v or v[-1] <= cutoff]
       for k in stale:
           self._buckets.pop(k, None)
   ```
3. For multi-worker production deployments, replace the in-memory dictionary with a shared Redis sliding window token counter.

