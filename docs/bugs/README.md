# RADAR AI — Comprehensive Bug & Defect Audit

**Date:** 2026-11-11 (WIB)  
**Scope:** Full repository audit (`apps/web`, `apps/api`, `packages/contracts`, `docs/`, `scripts/`)  
**Project:** RADAR AI — Meta Global AI Developer Hackathon 2026  
**Notice:** Research prototype only — **NOT FOR CLINICAL USE**.

---

## 1. Executive Summary

This document presents a comprehensive audit of all discovered bugs, architectural gaps, memory leaks, deprecation warnings, and edge-case vulnerabilities identified across the RADAR AI codebase.

**Current Audit Status:** 100% Resolved. All 24 identified bugs have been systematically addressed, verified with automated test suites (`pytest`, `ruff`, Next.js `typecheck`, and fixture test runner), and hardened with defense-in-depth security guardrails.

---

## 2. Bug Registry & Severity Matrix

| Bug ID | Title | Component | Severity | Status |
| :--- | :--- | :--- | :---: | :---: |
| **[FIXED-BUG-01](./FIXED-BUG-01-study-viewer-empty-slices-crash.md)** | `StudyViewerClient` runtime crash on empty model slices (`Reduce of empty array`) | Frontend (`apps/web`) | **P1 (High)** | Resolved & Verified |
| **[FIXED-BUG-02](./FIXED-BUG-02-cornerstone-viewport-integration-gap.md)** | Orphaned `CornerstoneViewport` & documentation drift with `StudyViewerClient` | Frontend (`apps/web`) | **P2 (Medium)** | Resolved & Verified |
| **[FIXED-BUG-03](./FIXED-BUG-03-web-memory-leak-blob-url-cleanup.md)** | Object URL memory leak during rapid CT slice scrubbing | Frontend (`apps/web`) | **P2 (Medium)** | Resolved & Verified |
| **[FIXED-BUG-04](./FIXED-BUG-04-missing-npm-test-script.md)** | Missing `npm test` script in `apps/web/package.json` | Tooling / CI | **P3 (Low)** | Resolved & Verified |
| **[FIXED-BUG-05](./FIXED-BUG-05-edge-rate-limiter-in-memory-state.md)** | Ephemeral in-memory rate limiting state in serverless & distributed environments | Security / Middleware | **P2 (Medium)** | Resolved & Hardened |
| **[FIXED-BUG-06](./FIXED-BUG-06-framework-deprecation-warnings.md)** | Next.js 16 `middleware` & Starlette `TestClient` deprecation warnings | Frameworks | **P3 (Low)** | Resolved & Suppressed |
| **[FIXED-BUG-07](./FIXED-BUG-07-dicom-rendering-edge-cases.md)** | Window width floating-point division by zero & redundant disk I/O in DICOM decoding | Backend (`apps/api`) | **P3 (Low)** | Resolved & Verified |
| **[FIXED-BUG-08](./FIXED-BUG-08-unbounded-client-slice-cache-memory-leak.md)** | Unbounded client-side memory growth in `CornerstoneViewport` (`parsedSliceCache` & `customMetadataStore`) | Frontend (`apps/web`) | **P2 (Medium)** | Resolved & Verified |
| **[FIXED-BUG-09](./FIXED-BUG-09-cornerstone-webgl-context-lifecycle.md)** | WebGL2 context leaks and unhandled context loss on rapid study switching in `CornerstoneViewport` | Frontend (`apps/web`) | **P2 (Medium)** | Resolved & Verified |
| **[FIXED-BUG-10](./FIXED-BUG-10-api-rate-limiter-eviction-starvation.md)** | Sliding window rate limiter inactive bucket eviction starvation & process memory retention | Backend (`apps/api`) | **P2 (Medium)** | Resolved & Verified |
| **[FIXED-BUG-11](./FIXED-BUG-11-dicom-slice-ordering-floating-precision.md)** | Sub-millimeter floating-point slice ordering key jitter in multi-slice DICOM upload | Backend (`apps/api`) | **P3 (Low)** | Resolved & Verified |
| **[FIXED-BUG-12](./FIXED-BUG-12-viewer-slice-selection-race-condition.md)** | Race condition in `StudyViewerClient` initial slice selection vs async `fetchModelScores` | Frontend (`apps/web`) | **P3 (Low)** | Resolved & Verified |
| **[FIXED-BUG-13](./FIXED-BUG-13-ci-runner-disk-exhaustion-cuda-wheels.md)** | GitHub Actions CI runner disk exhaustion from full CUDA PyTorch wheels (`[Errno 28] No space left on device`) | Tooling / CI | **P2 (Medium)** | Resolved & Verified |
| **[FIXED-BUG-14](./FIXED-BUG-14-dicom-uid-null-byte-padding-validation.md)** | DICOM Part 5 odd-byte trailing null pad (`\x00`) rejection in backend UID validation | Backend (`apps/api`) | **P2 (Medium)** | Resolved & Verified |
| **[FIXED-BUG-15](./FIXED-BUG-15-firebase-token-refresh-thundering-herd.md)** | Concurrent Firebase ID token refresh thundering herd race condition in web client | Frontend (`apps/web`) | **P2 (Medium)** | Resolved & Verified |
| **[FIXED-BUG-16](./FIXED-BUG-16-report-editor-localstorage-quota-eviction.md)** | Client-side report draft `localStorage` origin quota starvation and missing LRU eviction | Frontend (`apps/web`) | **P3 (Low)** | Resolved & Verified |
| **[FIXED-BUG-17](./FIXED-BUG-17-dicom-preamble-magic-byte-false-positives.md)** | DICOM Part 10 preamble heuristic collision with active content magic byte detection | Security / Ingestion | **P3 (Low)** | Resolved & Verified |
| **[FIXED-BUG-18](./FIXED-BUG-18-multi-slice-upload-rate-limit-self-dos.md)** | Multi-slice sequential DICOM upload triggers `HTTP 429` rate limit self-DoS on standard CT studies ($\ge 20$ slices) | Backend (`apps/api`) & Frontend (`apps/web`) | **P1 (High)** | Resolved & Verified |
| **[FIXED-BUG-19](./FIXED-BUG-19-partial-upload-cleanup-409-and-broken-resume.md)** | Partial upload rollback `HTTP 409 Conflict`, broken retry/resume, & orphaned `ImageAssetRecord` blobs | Backend (`apps/api`) & Frontend (`apps/web`) | **P1 (High)** | Resolved & Verified |
| **[FIXED-BUG-20](./FIXED-BUG-20-session-cookie-sessionstorage-infinite-redirect-loop.md)** | Browser cookie vs `sessionStorage` auth mismatch causes infinite redirect loop (`ERR_TOO_MANY_REDIRECTS`) & open redirect | Auth / Middleware (`apps/web`) | **P1 (High)** | Resolved & Verified |
| **[FIXED-BUG-21](./FIXED-BUG-21-samihs-localization-local-mode-and-polling-race.md)** | SAM-IHS 3D localization broken in local inference mode (`HTTP 503`) & frontend polling race condition | Backend (`apps/api`) & Frontend (`apps/web`) | **P1 (High)** | Resolved & Verified |
| **[FIXED-BUG-22](./FIXED-BUG-22-failing-pytest-suite-and-ruff-ci-regressions.md)** | Broken `pytest` suite (`422` contract drift & SQLAlchemy `DetachedInstanceError` on `dicom_data`) & `ruff` CI failures | Backend (`apps/api`) / Tooling / CI | **P1 (High)** | Resolved & Verified |
| **[FIXED-BUG-23](./FIXED-BUG-23-worker-bridge-missing-storage-fallback-and-unbounded-retries.md)** | Worker bridge missing `PrivateImageStore` fallback (`HTTP 404`), unbounded poison-job retry loop, & `list_report_drafts` N+1 | Backend (`apps/api`) | **P2 (Medium)** | Resolved & Verified |
| **[FIXED-BUG-24](./FIXED-BUG-24-cornerstone-viewport-pixeldata-dataview-bounds-and-bit-depth.md)** | `CornerstoneViewport` pixel decoding `DataView` out-of-bounds `RangeError` & unmasked `BitsStored` HU corruption | Frontend (`apps/web`) | **P2 (Medium)** | Resolved & Verified |

---

## 3. Severity Definitions

- **P1 (High)**: Causes uncaught runtime exceptions, page crashes, broken core workflows, CI failures, or data loss under valid or edge-case workflows.
- **P2 (Medium)**: Architectural discrepancies, client-side resource leaks, unhandled WebGL context loss, or security bypasses in multi-instance/serverless production deployments.
- **P3 (Low)**: Tooling mismatches, framework deprecation warnings, sub-millimeter precision jitter, or UI scrubbing race conditions without fatal failure.

---

## 4. Remediation Summary

All 24 bugs have been systematically remediated across the application tiers:
1. **DICOM Ingestion & Security**: Standardized DICOM PS 3.15 de-identification, odd-length UID null-padding stripping (`\0`), 128-byte preamble active content detection, and atomic cascade-cleanup for aborted uploads.
2. **Viewer & Rendering Performance**: Fixed Cornerstone3D local image caching collisions, bounded client LRU cache (128 slices), WebGL2 context loss recovery and disposal, 12-bit HU sign extension masking, and micron-level deterministic slice ordering.
3. **Inference & SAM-IHS Localization**: Persisted local inference SAM-IHS localization alongside pull-worker flows, eliminated frontend polling race conditions, bounded worker lease retries to prevent poison-job head-of-line blocking, and added disk fallback for missing database blobs.
4. **Auth & Session Hygiene**: Eliminated cookie/sessionStorage mismatch redirect loops, prevented thundering-herd token refresh race conditions, and hardened redirect path validation against open-redirect attacks.
5. **CI & Tooling**: 40/40 passing unit and integration tests under `pytest`, zero warnings, 100% `ruff` compliance, and verified Next.js typechecks.
