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

- **Node.js**: 20.9 or newer and npm
- **Python**: 3.12 or newer (tested on Python 3.12–3.14)

---

## How to Run the Project (Langkah Menjalankan Project)

Untuk menjalankan RADAR AI secara lokal, Anda perlu menyalakan **Backend API** (FastAPI) dan **Frontend Web** (Next.js) pada dua terminal terpisah.

### Langkah 1: Konfigurasi Environment Variables

Salin berkas contoh konfigurasi `.env.example` ke direktori backend dan frontend:

**macOS / Linux:**
```bash
# Salin konfigurasi backend
cp .env.example apps/api/.env

# Salin konfigurasi frontend
cp .env.example apps/web/.env.local
```

**Windows (PowerShell):**
```powershell
Copy-Item .env.example apps/api/.env
Copy-Item .env.example apps/web/.env.local
```

> **Catatan:**
> - Konfigurasi default sudah siap pakai untuk pengembangan lokal (`RADAR_AUTH_REQUIRED=false`, database SQLite di `apps/api/radar.db`).
> - Mode rumah sakit klinis diaktifkan secara default (`RADAR_ENFORCE_ANONYMIZATION=false`) sehingga menerima hasil scan CT langsung dari PACS rumah sakit.

---

### Langkah 2: Menjalankan Backend API (Terminal 1)

1. Buka terminal baru dan masuk ke folder `apps/api`:
   ```bash
   cd apps/api
   ```

2. Buat dan aktifkan virtual environment Python:
   - **macOS / Linux:**
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```
   - **Windows (PowerShell):**
     ```powershell
     python -m venv .venv
     .venv\Scripts\Activate.ps1
     ```
   - **Windows (CMD):**
     ```cmd
     python -m venv .venv
     .venv\Scripts\activate.bat
     ```

3. Install dependensi Python:
   ```bash
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```

4. Jalankan migrasi database:
   - **macOS / Linux:**
     ```bash
     export PYTHONPATH=src
     python -m alembic upgrade head
     ```
   - **Windows (PowerShell):**
     ```powershell
     $env:PYTHONPATH = "src"
     python -m alembic upgrade head
     ```

5. Jalankan server FastAPI dengan Uvicorn:
   - **macOS / Linux:**
     ```bash
     export PYTHONPATH=src
     python -m uvicorn radar_api.main:app --reload --port 8000
     ```
   - **Windows (PowerShell):**
     ```powershell
     $env:PYTHONPATH = "src"
     python -m uvicorn radar_api.main:app --reload --port 8000
     ```

API backend akan berjalan di **`http://localhost:8000`**.
- Health check: [http://localhost:8000/health](http://localhost:8000/health)
- API Documentation (Swagger UI): [http://localhost:8000/docs](http://localhost:8000/docs)

---

### Langkah 3: Menjalankan Frontend Web (Terminal 2)

1. Buka terminal kedua dan masuk ke folder `apps/web`:
   ```bash
   cd apps/web
   ```

2. Install dependensi Node.js:
   ```bash
   npm install
   ```

3. Jalankan development server Next.js:
   ```bash
   npm run dev
   ```

Frontend web akan berjalan di **`http://localhost:3000`**.
Buka browser dan akses **`http://localhost:3000`** untuk membuka RADAR AI CT Study Viewer.

---

### Langkah 4 (Opsional): Menjalankan Background Inference Worker

Jika Anda ingin menjalankan pemrosesan model AI (DenseNet121 / SAM-IHS) secara offline di background:
```bash
cd apps/api
# Pastikan virtual environment aktif dan PYTHONPATH diset
python -m radar_api.worker
```

---

## Quality Checks & Testing

Untuk memastikan semua kode berfungsi dengan aman dan lulus verifikasi pengujian:

**Backend Tests & Linting:**
```bash
# Dari root repository atau direktori apps/api:
PYTHONPATH=apps/api/src apps/api/.venv/bin/pytest apps/api/tests
PYTHONPATH=apps/api/src apps/api/.venv/bin/ruff check apps/api
```

**Frontend Tests & Typecheck:**
```bash
# Dari direktori apps/web:
cd apps/web
npm test             # Verifikasi fixture DICOM & Cornerstone integration
npm run typecheck    # TypeScript compiler check
npm run lint         # ESLint check
npm run build        # Production build verification
```

---

## Technical Notes & Database Configuration

The API uses a local SQLite database (`apps/api/radar.db`) by default. To use PostgreSQL instead, set `DATABASE_URL` to a PostgreSQL SQLAlchemy URL before running Alembic and the API, for example:
`postgresql+psycopg://radar:radar@localhost:5432/radar`.

Study metadata is available at `GET /v1/studies` and `GET /v1/studies/{study_id}`; create an empty
CT study record with `POST /v1/studies` and `{}`. Upload a CT series to
`POST /v1/studies/{study_id}/dicom` using multipart `files` fields.
The API stores files under `apps/api/data/private-images` by default, outside the web app's
static directories. Configure `RADAR_STORAGE_DIR` to select another private directory, and adjust
upload limits with `RADAR_MAX_DICOM_FILE_BYTES`, `RADAR_MAX_DICOM_SERIES_BYTES`,
`RADAR_MAX_DICOM_FILES`, and `RADAR_MAX_DICOM_PIXELS` as needed.
The shared API response contract is documented in [`docs/api-contract-v1.md`](docs/api-contract-v1.md)
and served as JSON Schema at <http://localhost:8000/v1/contracts/study-analysis>.
The web app lists saved studies, uploads DICOM series, and displays CT slice previews
from the private API. Configure `RADAR_WEB_ORIGINS` for the local web origin when it differs from
the defaults. In development, requests without credentials use the local `local-reviewer`
principal. Production requires a verified Firebase token or server-held API key; study reads and
writes are restricted to the authenticated study owner. Reviewer decisions are attributed to that
identity in the append-only audit log. Offline DenseNet121 scoring is available through
`apps/api/scripts/score_ct.py` when a compatible, locally provisioned checkpoint is supplied. The
API runs inference as a pollable job and persists per-slice scores with checkpoint hash, model ID,
preprocessing version, and device. DeepSeek V4.1 Flash report drafting is optional; configure
`DEEPSEEK_API_KEY` on the API server to enable generated drafts. Without it, the API accepts a
source-cited manual draft. This remains a research prototype, not for clinical use.

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


