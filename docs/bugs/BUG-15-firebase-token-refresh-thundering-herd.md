# BUG-15: Concurrent Firebase ID Token Refresh Thundering Herd Race Condition in Web Client

**Severity:** P2 (Medium)  
**Component:** `apps/web/lib/firebase-auth.ts`  
**Found in:** Comprehensive Codebase Bug Audit  
**Status:** Documented / Fix Available  
**Type:** Concurrency Race Condition / Session Invalidation  
**Notice:** Research prototype only — **NOT FOR CLINICAL USE**.

---

## 1. Description

In [`apps/web/lib/firebase-auth.ts`](../../apps/web/lib/firebase-auth.ts), the helper `getValidIdToken()` checks if the cached Firebase session is nearing expiration:

```typescript
// Lines 143-151 in firebase-auth.ts:
export async function getValidIdToken(): Promise<string | null> {
  const session = loadStoredSession();
  if (!session) return null;
  if (Date.now() < session.expiresAt) {
    return session.idToken;
  }
  const refreshed = await refreshFirebaseSession(session);
  return refreshed?.idToken ?? null;
}
```

### Root Cause
1. In `api-client.ts`, every authenticated request (`apiFetch`, `fetchAuthenticatedImageBlobUrl`, `uploadDicomSeriesWithProgress`) calls `await getValidIdToken()`.
2. When a user opens a study page (`/studies/[id]`), the component fires multiple asynchronous requests concurrently:
   - `fetchStudy` (`GET /v1/studies/{id}`)
   - `fetchModelScores` (`GET /v1/studies/{id}/scores`)
   - `fetchStudyLocalizations` (`GET /v1/studies/{id}/localizations`)
   - `fetchAuthenticatedImageBlobUrl` (`GET /v1/studies/{id}/slices/{slice_id}/image`)
3. If the user's ID token has expired (or is within 60 seconds of expiration), all 4 concurrent requests call `getValidIdToken()` almost simultaneously.
4. Because there is no mutex or in-flight promise deduplication, all 4 callers independently trigger separate POST requests to Google Secure Token API (`https://securetoken.googleapis.com/v1/token?grant_type=refresh_token`).
5. This creates a "thundering herd" race condition:
   - Google Secure Token API rotates the `refreshToken` upon use.
   - The fastest request receives `new_refresh_token_A`.
   - A subsequent concurrent request using the now-invalidated prior `refreshToken` fails with `HTTP 400 Token Has Been Revoked`.
   - The failure handler in `refreshFirebaseSession` immediately executes `saveStoredSession(null)` and `syncServerCookie(null)`, destroying the user's session and forcing an unexpected logout during active study review.

---

## 2. Reproduction Steps

1. Log into RADAR AI using a valid researcher account.
2. Manually alter the session in browser DevTools `sessionStorage` (`radar_ai_firebase_session_v1`) to set `expiresAt: Date.now() - 5000` (simulating expired token).
3. Open a study with 50+ slices.
4. Observe the Network tab in DevTools: multiple simultaneous POST requests to `securetoken.googleapis.com/v1/token` are dispatched.
5. In intermittent runs, one of the later requests returns `HTTP 400 Invalid Refresh Token`, wiping the session and causing subsequent API calls to fail with `HTTP 401 Unauthorized`.

---

## 3. Impact Analysis

- **Spurious Session Termination**: Clinicians/researchers actively reviewing a CT study are suddenly kicked out or see `HTTP 401` errors when saving review findings or editing reports.
- **Unnecessary Egress API Traffic**: Wastes quota against Google Identity Toolkit / Secure Token rate limits.

---

## 4. Recommended Remediation

Introduce a module-scoped in-flight promise singleton to coalesce concurrent refresh invocations:

```typescript
let activeRefreshPromise: Promise<AuthUser | null> | null = null;

export async function getValidIdToken(): Promise<string | null> {
  const session = loadStoredSession();
  if (!session) return null;
  if (Date.now() < session.expiresAt) {
    return session.idToken;
  }

  if (!activeRefreshPromise) {
    activeRefreshPromise = refreshFirebaseSession(session).finally(() => {
      activeRefreshPromise = null;
    });
  }

  const refreshed = await activeRefreshPromise;
  return refreshed?.idToken ?? null;
}
```

