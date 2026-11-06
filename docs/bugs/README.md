# RADAR AI — Comprehensive Bug & Defect Audit

**Date:** 2026-10-29 (WIB)  
**Scope:** Full repository audit (`apps/web`, `apps/api`, `packages/contracts`, `docs/`, `scripts/`)  
**Project:** RADAR AI — Meta Global AI Developer Hackathon 2026  
**Notice:** Research prototype only — **NOT FOR CLINICAL USE**.

---

## 1. Executive Summary

This document presents a comprehensive audit of all discovered bugs, architectural gaps, memory leaks, deprecation warnings, and edge-case vulnerabilities identified across the RADAR AI codebase.

Each issue is classified by severity, root cause, reproduction steps, affected files, and recommended remediation.

---

## 2. Bug Registry & Severity Matrix

| Bug ID | Title | Component | Severity | Status |
| :--- | :--- | :--- | :---: | :---: |
| **[BUG-01](./BUG-01-study-viewer-empty-slices-crash.md)** | `StudyViewerClient` runtime crash on empty model slices (`Reduce of empty array`) | Frontend (`apps/web`) | **P1 (High)** | Resolved (RDA-4) |
| **[BUG-02](./BUG-02-cornerstone-viewport-integration-gap.md)** | Orphaned `CornerstoneViewport` & documentation drift with `StudyViewerClient` | Frontend (`apps/web`) | **P2 (Medium)** | Resolved (RDA-4) |
| **[BUG-03](./BUG-03-web-memory-leak-blob-url-cleanup.md)** | Object URL memory leak during rapid CT slice scrubbing | Frontend (`apps/web`) | **P2 (Medium)** | Resolved (RDA-4) |
| **[BUG-04](./BUG-04-missing-npm-test-script.md)** | Missing `npm test` script in `apps/web/package.json` | Tooling / CI | **P3 (Low)** | Resolved (RDA-4) |
| **[BUG-05](./BUG-05-edge-rate-limiter-in-memory-state.md)** | Ephemeral in-memory rate limiting state in serverless & distributed environments | Security / Middleware | **P2 (Medium)** | Documented |
| **[BUG-06](./BUG-06-framework-deprecation-warnings.md)** | Next.js 16 `middleware` & Starlette `TestClient` deprecation warnings | Frameworks | **P3 (Low)** | Documented |
| **[BUG-07](./BUG-07-dicom-rendering-edge-cases.md)** | Window width floating-point division by zero & redundant disk I/O in DICOM decoding | Backend (`apps/api`) | **P3 (Low)** | Documented / Fix available |
| **[BUG-08](./BUG-08-unbounded-client-slice-cache-memory-leak.md)** | Unbounded client-side memory growth in `CornerstoneViewport` (`parsedSliceCache` & `customMetadataStore`) | Frontend (`apps/web`) | **P2 (Medium)** | Documented / Fix available |
| **[BUG-09](./BUG-09-cornerstone-webgl-context-lifecycle.md)** | WebGL2 context leaks and unhandled context loss on rapid study switching in `CornerstoneViewport` | Frontend (`apps/web`) | **P2 (Medium)** | Documented / Fix available |
| **[BUG-10](./BUG-10-api-rate-limiter-eviction-starvation.md)** | Sliding window rate limiter inactive bucket eviction starvation & process memory retention | Backend (`apps/api`) | **P2 (Medium)** | Documented / Fix available |
| **[BUG-11](./BUG-11-dicom-slice-ordering-floating-precision.md)** | Sub-millimeter floating-point slice ordering key jitter in multi-slice DICOM upload | Backend (`apps/api`) | **P3 (Low)** | Documented / Fix available |
| **[BUG-12](./BUG-12-viewer-slice-selection-race-condition.md)** | Race condition in `StudyViewerClient` initial slice selection vs async `fetchModelScores` | Frontend (`apps/web`) | **P3 (Low)** | Resolved (RDA-4) |
| **[BUG-13](./BUG-13-ci-runner-disk-exhaustion-cuda-wheels.md)** | GitHub Actions CI runner disk exhaustion from full CUDA PyTorch wheels (`[Errno 28] No space left on device`) | Tooling / CI | **P2 (Medium)** | Resolved |
| **[BUG-14](./BUG-14-dicom-uid-null-byte-padding-validation.md)** | DICOM Part 5 odd-byte trailing null pad (`\x00`) rejection in backend UID validation | Backend (`apps/api`) | **P2 (Medium)** | Documented / Fix available |
| **[BUG-15](./BUG-15-firebase-token-refresh-thundering-herd.md)** | Concurrent Firebase ID token refresh thundering herd race condition in web client | Frontend (`apps/web`) | **P2 (Medium)** | Documented / Fix available |
| **[BUG-16](./BUG-16-report-editor-localstorage-quota-eviction.md)** | Client-side report draft `localStorage` origin quota starvation and missing LRU eviction | Frontend (`apps/web`) | **P3 (Low)** | Documented / Fix available |
| **[BUG-17](./BUG-17-dicom-preamble-magic-byte-false-positives.md)** | DICOM Part 10 preamble heuristic collision with active content magic byte detection | Security / Ingestion | **P3 (Low)** | Documented / Fix available |

---

## 3. Severity Definitions

- **P1 (High)**: Causes uncaught runtime exceptions, page crashes, or data loss under valid or edge-case workflows.
- **P2 (Medium)**: Architectural discrepancies, client-side resource leaks, unhandled WebGL context loss, or security bypasses in multi-instance/serverless production deployments.
- **P3 (Low)**: Tooling mismatches, framework deprecation warnings, sub-millimeter precision jitter, or UI scrubbing race conditions without fatal failure.

---

## 4. Remediation Priority Roadmap

1. **Sprint 2 Completed Hardening (Resolved)**:
   - Patched `BUG-01`: Safeguarded `Array.prototype.reduce` in `StudyViewerClient.tsx` against empty slice arrays.
   - Patched `BUG-02`: Integrated `CornerstoneViewport` into `StudyViewerClient` with dual-mode toggle and interactive HU probe.
   - Patched `BUG-03`: Added cancellation tracking and revoked abandoned Object URLs during async slice image resolution.
   - Patched `BUG-04`: Added `"test": "node scripts/verify-dicom-fixture.mjs"` to `apps/web/package.json`.
   - Patched `BUG-12`: Added `userInteractedRef` in `StudyViewerClient.tsx` to prevent async `fetchModelScores` from overriding deliberate slice selection.
   - Patched `BUG-13`: Locked CPU-only PyTorch wheels on CI runners and pruned unused toolchains, eliminating runner disk exhaustion.

2. **Next Sprint (Standards Compliance, Concurrency & Client Resource Optimization)**:
   - Patch `BUG-14`: Strip null byte pads (`\0`) alongside whitespace in `dicom_validation.py` to prevent false rejection of compliant DICOM Part 5 UIDs.
   - Patch `BUG-15`: Add in-flight singleton promise deduplication to `getValidIdToken()` in `firebase-auth.ts` to prevent thundering-herd session invalidation.
   - Patch `BUG-16`: Implement LRU eviction for `radar_report_draft_v1_*` in `ReportEditor.tsx` when `QuotaExceededError` occurs.
   - Patch `BUG-17`: Validate `"DICM"` offset 128 before applying offset-0 magic prefix heuristics to eliminate preamble false positives on legacy scanner hardware.
   - Patch `BUG-08`: Implement bounded LRU eviction (e.g. max 64 slices) for `parsedSliceCache` and `customMetadataStore` in `CornerstoneViewport.tsx`.
   - Patch `BUG-09`: Explicitly invoke `engine.disableElement(viewportId)` before `engine.destroy()`, and handle `webglcontextlost`/`webglcontextrestored` events.
   - Patch `BUG-10`: Add background/periodic sweep to evict inactive buckets from `SlidingWindowRateLimiter` in `security.py`.
   - Patch `BUG-11`: Round `slice_position` to 3 decimal places (1 micron) before sorting uploaded slices in `main.py` and `dicom_validation.py`.

3. **Infrastructure & Production Readiness**:
   - Resolve `BUG-05` by providing a distributed Redis/Upstash adapter for edge rate limiting in production.
   - Resolve `BUG-06` by migrating `apps/web/middleware.ts` to `apps/web/proxy.ts` once Next.js 16 stabilizes the proxy convention.
   - Resolve `BUG-07` by caching decoded DICOM datasets in memory to eliminate redundant disk reads between metadata and PNG rendering.
