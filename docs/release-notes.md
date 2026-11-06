# Release notes

## Unreleased — engineering workflow update

- Added persisted asynchronous local inference jobs with pollable state, stable failure codes,
  per-slice subtype scores, and checkpoint/model/preprocessing provenance.
- Added source-cited Meta report drafts and a persisted manual fallback. Reports remain unsigned and
  require a human review.
- Added study ownership checks, versioned finding corrections, before/after audit snapshots, a
  database readiness endpoint, safer error logging, and removed browser-bundled API key support.
- Added a CPU-oriented API container and local PostgreSQL Compose deployment with private data
  volumes and a deployment runbook.
- Added model, API, security, release, and submission documentation.

### Verification

- API: 40 tests passed; Ruff passed.
- Web: lint and typecheck passed; `npm test` passed with all DICOM and viewer checks.
- Alembic migrations applied to a temporary SQLite database through revision `20261105_0004`.
- Docker deployment and live model-provider calls were not run in the local environment.

### Configuration and limitations

- A compatible local checkpoint is required for successful inference; none is included in the
  repository.
- `MODEL_API_KEY` must be set in the API environment for Meta report generation. Manual report
  drafting remains available without it.
- A public deployment requires an operator-selected host, TLS, Firebase configuration, and
  environment-specific secrets. The Compose deployment binds to loopback.
- No repository software license has been selected or added.
