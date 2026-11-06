# RADAR AI

RADAR AI is a research prototype for assisting review of brain CT studies. It is **not for clinical use** and does not replace a qualified clinician.

This repository follows the RADAR AI setup task in Jira: [RDA-8](https://iqbaldovandraa.atlassian.net/browse/RDA-8). Product work is tracked in Jira project **RDA**.

## Repository layout

```text
apps/
  api/             FastAPI service and API smoke tests
  web/             Next.js App Router application
docs/              Architecture and development workflow
packages/
  contracts/       Shared API contract documentation
```

## Requirements

- Node.js 20.9 or newer and npm
- Python 3.12

## Local setup

1. Copy `.env.example` to `apps/web/.env.local` and fill in local values. Do not commit local environment files or credentials.
2. Start the web app:

   ```powershell
   cd apps/web
   npm install
   npm run dev
   ```

3. In a second terminal, start the API:

   ```powershell
   cd apps/api
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   $env:PYTHONPATH = "src"
   python -m alembic upgrade head
   uvicorn radar_api.main:app --reload --port 8000
   ```

The web app runs at <http://localhost:3000>; the API health check is at <http://localhost:8000/health>.
The API uses a local SQLite database by default. Set `DATABASE_URL` to a PostgreSQL SQLAlchemy URL
before running Alembic and the API to use PostgreSQL, for example
`postgresql+psycopg://radar:radar@localhost:5432/radar`. Do not use real patient data.
Study metadata is available at `GET /v1/studies` and `GET /v1/studies/{study_id}`; create an empty
CT study record with `POST /v1/studies` and `{}`. Upload an anonymized CT series to
`POST /v1/studies/{study_id}/dicom` using repeated multipart `files` fields.
The API stores files under `apps/api/data/private-images` by default, outside the web app's
static directories. Configure `RADAR_STORAGE_DIR` to select another private directory, and adjust
upload limits with `RADAR_MAX_DICOM_FILE_BYTES`, `RADAR_MAX_DICOM_SERIES_BYTES`,
`RADAR_MAX_DICOM_FILES`, and `RADAR_MAX_DICOM_PIXELS` as needed. Do not use patient data.
The shared API response contract is documented in [`docs/api-contract-v1.md`](docs/api-contract-v1.md)
and served as JSON Schema at <http://localhost:8000/v1/contracts/study-analysis>.
The web app lists saved studies, uploads anonymized DICOM series, and displays CT slice previews
from the private API. Configure `RADAR_WEB_ORIGINS` for the local web origin when it differs from
the defaults. In development, requests without credentials use the local `local-reviewer`
principal. Production requires a verified Firebase token or server-held API key; study reads and
writes are restricted to the authenticated study owner. Reviewer decisions are attributed to that
identity in the append-only audit log. Offline DenseNet121 scoring is available through
`apps/api/scripts/score_ct.py` when a compatible, locally provisioned checkpoint is supplied. The
API runs inference as a pollable job and persists per-slice scores with checkpoint hash, model ID,
preprocessing version, and device. No checkpoint is shipped, so operators must provision a
validated research checkpoint before inference can complete. Meta report generation is optional;
without a server-side `MODEL_API_KEY`, the API accepts a source-cited manual draft. This remains a
research prototype, not for clinical use.

## Quality checks

```powershell
cd apps/web
npm install
npm test
npm run lint
npm run typecheck

cd ../api
python -m pip install -r requirements.txt
python -m ruff check .
python -m pytest
```

GitHub Actions runs these checks for pull requests and pushes to `main`. CI does not need secrets. The lockfile should be committed after the first dependency install so CI can switch to `npm ci`.

## Git and pull requests

- Keep `main` releasable; do development on short-lived branches named `feat/<summary>`, `fix/<summary>`, or `docs/<summary>`.
- Use pull requests to merge into `main`. Link the relevant Jira issue in the PR title or body (for example, `RDA-8`).
- Require passing CI and at least one approval before merging. Enable branch protection for `main` in GitHub repository settings once repository administration is available.
- Do not commit patient data, model weights, secrets, or generated datasets. Use only anonymized or synthetic fixtures approved for the project.

## Scope and safety

The project is an early research/demo prototype. Model outputs are experimental, require human review, and must not be used to diagnose, triage, or make treatment decisions. Follow the data license and privacy requirements before using any dataset.
No repository software license has been provided yet; do not assume code reuse is licensed until the project owner selects and adds one.

The RSNA Brain CT Hemorrhage dataset licensing assessment, source metadata manifest, and outstanding local profiling dependency are documented in [`docs/rsna-ich-licensing-and-profile.md`](docs/rsna-ich-licensing-and-profile.md) and [`docs/rsna-ich-source-manifest.json`](docs/rsna-ich-source-manifest.json). Dataset files and patient-level metadata must remain outside this repository.
The Sprint 1 preprocessing, grouped split-manifest, memory budget, and dependent-workstream handoff are documented in [`docs/dicom-preprocessing-handoff.md`](docs/dicom-preprocessing-handoff.md).
The offline DenseNet121 checkpoint contract, inference command, current validation evidence, and data/model handoff are documented in [`docs/ct-inference-handoff.md`](docs/ct-inference-handoff.md).
The optional pretrained SAMIHS hemorrhage mask localizer, one-time offline provisioning, viewer boxes, and validation limits are documented in [`docs/ich-localization-handoff.md`](docs/ich-localization-handoff.md). It uses existing weights only; it does not train or fine-tune.
The supported model scope, validation limits, provenance, and human oversight requirements are summarized in [`docs/model-card.md`](docs/model-card.md).
The Cornerstone3D DICOM viewer integration, Hounsfield Unit voxel probing, cranial windowing presets, bidirectional slice-to-finding evidence linking, and non-diagnostic model provenance display are documented in [`docs/dicom-viewer-integration.md`](docs/dicom-viewer-integration.md).
The findings sidebar, structured report editor, slice citation insertion, reviewer actions, and visible failure recovery are documented in [`docs/findings-report-editor-handoff.md`](docs/findings-report-editor-handoff.md).
Backend container deployment, configuration, health checks, data volumes, and recovery steps are in [`docs/backend-deployment-runbook.md`](docs/backend-deployment-runbook.md).
Release, licensing, deployment, and event-submission evidence is tracked in [`docs/release-checklist.md`](docs/release-checklist.md).
Engineering workflow changes are summarized in [`docs/release-notes.md`](docs/release-notes.md).


