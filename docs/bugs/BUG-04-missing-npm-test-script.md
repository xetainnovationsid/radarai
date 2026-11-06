# BUG-04: Missing `npm test` Script in `apps/web/package.json`

**Severity:** P3 (Low)  
**Component:** `apps/web/package.json` & Developer Tooling  
**Found in:** Sprint 2 Audit  
**Type:** Missing Configuration / CI Tooling Failure

---

## 1. Description

In [`docs/dicom-viewer-integration.md`](file:///Users/shine/Documents/Shine's%20Personal%20Folder/Code/Tel-U/radar-ai/docs/dicom-viewer-integration.md) line 71:

```markdown
- Verify DICOM headers & HU calibration: `cd apps/web && npm test`
```

However, [`apps/web/package.json`](file:///Users/shine/Documents/Shine's%20Personal%20Folder/Code/Tel-U/radar-ai/apps/web/package.json) only defines:

```json
"scripts": {
  "dev": "next dev",
  "build": "next build",
  "start": "next start",
  "lint": "eslint .",
  "typecheck": "tsc --noEmit"
}
```

Running `npm test` inside `apps/web` fails immediately:

```text
npm error Missing script: "test"
npm error To see a list of scripts, run:
npm error   npm run
```

---

## 2. Impact Analysis

- **CI/CD Failure**: Standard CI jobs executing `npm test` will exit with code 1.
- **Developer Onboarding**: Breaks the documented verification workflow in `docs/dicom-viewer-integration.md`.

---

## 3. Recommended Fix

Add the test script to `apps/web/package.json`:

```json
"scripts": {
  "dev": "next dev",
  "build": "next build",
  "start": "next start",
  "lint": "eslint .",
  "typecheck": "tsc --noEmit",
  "test": "node scripts/verify-dicom-fixture.mjs"
}
```

