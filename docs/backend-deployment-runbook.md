# Backend deployment runbook

## Local review deployment

Use the root `docker-compose.yml` for a repeatable PostgreSQL-backed API deployment. The API image
uses CPU-only PyTorch, applies Alembic migrations before startup, runs as an unprivileged user, and
stores images and model artifacts outside the image. DICOM fixtures, weights, credentials, and the
local database are excluded from the build context.

Set `POSTGRES_PASSWORD` to a long URL-safe secret, `RADAR_API_KEYS` to a separate random key for
server-to-server use, and `RADAR_WEB_ORIGINS` to the exact frontend origins. Set Firebase project
configuration to enable browser login. To enable Meta report drafting, set `MODEL_API_KEY` only in
the API environment. Mount a compatible checkpoint into the configured read-only model directory
to enable local inference. Neither Meta nor local model inference is faked when configuration is
missing.

```powershell
$env:POSTGRES_PASSWORD = "use-a-long-url-safe-random-value"
$env:RADAR_API_KEYS = "use-a-different-long-random-value"
$env:RADAR_WEB_ORIGINS = "http://localhost:3000"
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://localhost:8000/health/ready
docker compose logs --tail 100 api
```

The API is bound to `127.0.0.1:8000`. This is suitable for local integration review and is not a
public deployment. A public environment needs an operator-selected host, TLS, DNS, Firebase setup,
environment-specific CORS, backups, and a provisioned research checkpoint. No cloud credentials or
production domain are configured in this repository, so no public deployment has been made.

## Study and inference operations

1. Create a study and upload a synthetic or properly de-identified CT series.
2. Request `POST /v1/studies/{study_id}/inference-jobs` and poll the returned job ID.
3. On `completed`, read `/analysis` and `/scores`. On `failed`, use the returned stable error code
   and request a new job after correcting configuration.
4. A report draft is generated from saved findings through `POST /reports/drafts`; if Meta is
   unavailable, compose a manual cited draft by sending `manual_content`.
5. Readiness is checked at `/health/ready`; liveness is checked at `/health`.

Back up and restore PostgreSQL and private-image volumes as one unit. A database-only restore cannot
recover the DICOM objects it references. Review `docs/security-and-deployment.md` before exposing
the service beyond loopback.
