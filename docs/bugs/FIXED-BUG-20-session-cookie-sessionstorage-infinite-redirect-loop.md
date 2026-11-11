# BUG-20: Cross-Tab `sessionStorage` vs HTTP-Only `radar_auth_session` Cookie Desynchronization Causes Infinite Redirect Loop & Open Redirect in Auth Flows

**Severity:** P1 (High)  
**Component:** `apps/web/middleware.ts`, `apps/web/components/AuthContext.tsx`, `apps/web/lib/firebase-auth.ts`, & `apps/web/app/api/auth/session/route.ts`  
**Found in:** Post-Sprint 2 Codebase Audit (2026-11-11)  
**Status:** Open / Fix Available  
**Type:** Authentication Loop (`ERR_TOO_MANY_REDIRECTS`) & Open Redirect Vulnerability  
**Notice:** Research prototype only — **NOT FOR CLINICAL USE**.

---

## 1. Description

When web authentication enforcement is enabled (`NEXT_PUBLIC_REQUIRE_AUTH=true`), the Next.js application tracks session state in two separate storage mechanisms with **mismatched browser lifetimes and scopes**:

1. **Client-Side Auth State ([`apps/web/lib/firebase-auth.ts`](../../apps/web/lib/firebase-auth.ts), lines 48–75)**: Stored in `window.sessionStorage` (`radar_ai_firebase_session_v1`), which is isolated to a **single browser tab**.
2. **Server/Edge Middleware Auth State ([`apps/web/app/api/auth/session/route.ts`](../../apps/web/app/api/auth/session/route.ts), lines 34–42)**: Stored in an `httpOnly` cookie (`radar_auth_session=authenticated`, `maxAge: 3600`, `path: "/"`), which is shared across **all tabs and windows** of the browser origin for 1 hour.

### Root Cause 1: Infinite Redirect Loop (`/` ↔ `/login`) on New Tab or Cleared `sessionStorage`
1. A researcher logs in on Tab 1. Both `window.sessionStorage` (Tab 1 only) and the `radar_auth_session` cookie (browser-wide) are populated.
2. The researcher opens a new tab (Tab 2) to `/studies` or `/`, or closes and reopens the tab within 1 hour:
   - **Step A (Edge Middleware)**: [`apps/web/middleware.ts`](../../apps/web/middleware.ts) (line 140) sees `hasSessionCookie === true` and serves the requested page (`200 OK`).
   - **Step B (Client `AuthProvider`)**: [`apps/web/components/AuthContext.tsx`](../../apps/web/components/AuthContext.tsx) (lines 48–53) calls `loadStoredSession()`. Because `window.sessionStorage` is empty in Tab 2, it sets `user = null` and `loading = false` **without clearing the server cookie (`DELETE /api/auth/session`)**.
   - **Step C (Client Route Guard)**: `AuthContext.tsx` (lines 100–105) sees `authRequired && !user && !isLoginPage` and executes `router.replace("/login")`.
   - **Step D (Edge Middleware on `/login`)**: `middleware.ts` (lines 147–153) intercepts the navigation to `/login`:
     ```typescript
     if (isLoginPage && hasSessionCookie) {
       const destination = request.nextUrl.searchParams.get("redirect") || "/";
       return applySecurityHeaders(
         NextResponse.redirect(new URL(destination, request.url)),
         pathname
       );
     }
     ```
     Because `radar_auth_session` is still present in `request.cookies`, the middleware immediately redirects back to `/` (`307 Temporary Redirect`)!
   - **Result**: The browser loops infinitely between `/` and `/login` until the tab crashes or the user manually clears browser cookies in DevTools.

### Root Cause 2: Unvalidated `?redirect=` Open Redirect in `middleware.ts` and `AuthContext.tsx`
- In `apps/web/middleware.ts` (lines 148–151):
  `const destination = request.nextUrl.searchParams.get("redirect") || "/";`
  `NextResponse.redirect(new URL(destination, request.url))`
  In JavaScript's `URL` constructor, `new URL("https://evil.example.com", "https://radar.example.com/login")` and `new URL("//evil.example.com", "https://radar.example.com/login")` resolve to `https://evil.example.com/`.
- In `apps/web/components/AuthContext.tsx` (lines 108–110):
  `const destination = params.get("redirect") || "/";`
  `router.replace(destination);`
  Passing `/login?redirect=https://evil.example.com` redirects an authenticated user to an arbitrary external phishing domain after login.

---

## 2. Reproduction Steps

### Reproducing the Infinite Redirect Loop:
1. Set `NEXT_PUBLIC_REQUIRE_AUTH=true` in `apps/web/.env.local`.
2. Sign in on `/login`.
3. Open a second browser tab to `http://localhost:3000/` (or delete `radar_ai_firebase_session_v1` from `sessionStorage` while keeping cookies).
4. Observe the browser rapidly oscillating between `http://localhost:3000/` and `http://localhost:3000/login`.

### Reproducing the Open Redirect:
1. While signed in (with `radar_auth_session` cookie set), navigate to:
   `http://localhost:3000/login?redirect=https://example.com`
2. Observe that `middleware.ts` responds with `HTTP 307 Location: https://example.com/`.

---

## 3. Impact Analysis

- **Complete Lockout in Multi-Tab Research Workflows**: Opening a study link in a new tab (`target="_blank"` or Cmd/Ctrl+Click) triggers an unrecoverable redirect loop whenever `NEXT_PUBLIC_REQUIRE_AUTH=true`.
- **Phishing / Open Redirect Vector**: Attackers can craft links to `/login?redirect=https://attacker.tld` that redirect researchers to an external site immediately upon authentication.

---

## 4. Recommended Remediation

1. **Clear Stale Server Cookie Before Redirecting to `/login`** in `apps/web/components/AuthContext.tsx`:
```typescript
// In AuthContext.tsx restoreSession():
const stored = loadStoredSession();
if (!stored) {
  await signOutFirebase(); // Deletes stale radar_auth_session cookie via DELETE /api/auth/session
  if (!ignore) setLoading(false);
  return;
}
```
2. **Sanitize `redirect` Target to Internal Relative Paths Only** in both `middleware.ts` and `AuthContext.tsx`:
```typescript
function sanitizeRedirectPath(raw: string | null): string {
  if (!raw) return "/";
  const trimmed = raw.trim();
  if (!trimmed.startsWith("/") || trimmed.startsWith("//") || trimmed.startsWith("/\\")) {
    return "/";
  }
  return trimmed;
}
```
