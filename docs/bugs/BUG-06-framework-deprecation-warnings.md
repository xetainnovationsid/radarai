# BUG-06: Framework & Tooling Deprecation Warnings

**Severity:** P3 (Low)  
**Component:** Next.js 16 (`apps/web/middleware.ts`) & Starlette TestClient (`apps/api/tests/`)  
**Found in:** Sprint 2 Audit  
**Type:** Deprecation Warning / Future Compatibility Risk

---

## 1. Description

### A. Next.js 16 Middleware Deprecation Warning
Running `npm --prefix apps/web run build` emits:

```text
⚠ The "middleware" file convention is deprecated. Please use "proxy" instead.

  To migrate automatically, run:
  npx @next/codemod@canary middleware-to-proxy .

  Learn more: https://nextjs.org/docs/messages/middleware-to-proxy
```

Next.js 16 has reorganized edge routing and recommends replacing `middleware.ts` with `proxy.ts` (or explicit route handlers/proxy rewrites) for request filtering and rate limiting.

### B. Starlette TestClient Deprecation Warning
Running `pytest apps/api/tests` emits:

```text
fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
```

The installed version of `fastapi` and `starlette` flags the legacy `httpx` driver in test environments.

---

## 2. Impact Analysis

- **Maintainability**: Low currently, but future major version bumps (`Next.js 17`, `FastAPI 1.0 / Starlette 1.0`) will turn these deprecation warnings into breaking errors.
- **Log Noise**: Pollutes test and build logs.

---

## 3. Recommended Remediation

1. Run `npx @next/codemod@canary middleware-to-proxy .` in `apps/web/` or rename and adapt `middleware.ts` to `proxy.ts`.
2. Update `apps/api/requirements.txt` to align `fastapi`, `starlette`, and `httpx` versions according to Starlette's updated test client guidelines.

