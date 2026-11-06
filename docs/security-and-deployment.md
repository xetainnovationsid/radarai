# Security and deployment

## Implemented protections

- Production API calls require a verified Firebase ID token or a server-held API key. Development
  can use the local development principal; production must set `RADAR_ENV=production` and
  `RADAR_AUTH_REQUIRED=true`.
- Each study is owned by the principal that created it. Study metadata, DICOM retrieval, inference,
  findings, reports, and review history return `404` to other principals.
- Review events record the authenticated reviewer, old status, and new status. Events are append-only
  through the API; no edit or delete route is exposed.
- DICOM uploads are size-limited, validated for CT and identifying metadata, and stored outside
  static web roots. File names and storage keys are never returned.
- Meta report generation sends only saved de-identified finding facts and evidence IDs. The API key
  must remain server-side. The browser does not accept or bundle an API key.
- Request logs omit query strings, body content, authorization values, and exception messages.
  Failures include a request ID and an exception class only.
- `/health` is a liveness check. `/health/ready` checks the database connection and returns 503 if
  the database is unavailable.

Rate limits use an in-process sliding-window limiter. They protect a single API worker and reset
when it restarts; use a shared gateway or shared store before scaling to multiple API replicas.

## Local container deployment

The repository includes a CPU-only API image and a PostgreSQL-backed Docker Compose stack. The API
binds to loopback by default. It runs Alembic migrations at startup and persists PostgreSQL data and
private image files in named volumes. A trained checkpoint is mounted read-only from the local
model-artifacts directory; the image never contains model weights.

1. Set a URL-safe PostgreSQL password, an API key, and the allowed web origin in the PowerShell
   session. Do not put production keys in source control:

   ```powershell
   $env:POSTGRES_PASSWORD = "generate-a-long-url-safe-secret"
   $env:RADAR_API_KEYS = "generate-a-separate-long-random-key"
   $env:RADAR_WEB_ORIGINS = "http://localhost:3000"
   ```

2. Start the service from the repository root:

   ```powershell
   docker compose up --build -d
   docker compose ps
   Invoke-RestMethod http://localhost:8000/health/ready
   ```

3. The Compose API runs with production authentication enabled. Configure `FIREBASE_PROJECT_ID`
   and the matching web Firebase settings to sign in through the browser. API keys are for
   server-to-server access only. Never place `RADAR_API_KEYS` or `MODEL_API_KEY` in a `NEXT_PUBLIC_*`
   variable.

4. To enable local model inference, put a compatible checkpoint under
   `apps/api/data/model-artifacts/ct-binary-densenet121.pt` before starting Compose. Without it,
   inference jobs fail with the safe `model_unavailable` code. To enable Meta report drafts, set
   `MODEL_API_KEY` only in the API deployment environment; without it, cited manual drafts remain
   available.

The Compose API is a local/review deployment, not a publicly reachable production release. Public
deployment still needs an operator-selected host, HTTPS termination, Firebase project settings,
domain-specific CORS, backups, a provisioned validated checkpoint, and a real health-check URL.

## Recovery and data handling

- Back up the PostgreSQL volume and private-image volume together. A database restore without the
  matching image volume leaves study metadata without the source images.
- A failed inference job records a stable `error_code`; retry by requesting a new job after fixing
  the missing checkpoint or input issue.
- Do not put patient data in this prototype. Use only synthetic or properly de-identified samples.
- Model outputs are research-only and require human review; they must not be used to diagnose,
  triage, or make treatment decisions.
