# BUG-13: GitHub Actions CI Runner Disk Exhaustion from Full CUDA PyTorch Wheels & Untracked Fixtures

**Severity:** P2 (Medium)  
**Component:** `.github/workflows/ci.yml`, `.gitignore`, & `apps/api/requirements.txt`  
**Found in:** CI Build Run #65 & #66  
**Type:** CI/CD Infrastructure Failure (`OSError: [Errno 28] No space left on device` & Missing Test Fixtures)  
**Status:** Resolved  
**Notice:** Research prototype only — **NOT FOR CLINICAL USE**.

---

## 1. Description

During GitHub Actions CI execution on `ubuntu-latest`:
1. The `API lint and tests` workflow failed with an out-of-disk exception (`[Errno 28] No space left on device`) due to default PyPI resolution pulling massive NVIDIA CUDA 13 binaries (>10 GB uncompressed).
2. The `Web lint and typecheck` workflow failed on `npm test` (`scripts/verify-dicom-fixture.mjs`) because `.gitignore` contained `*.dcm` on line 31, preventing `apps/web/public/fixtures/dicom/brain-ct/slice-*.dcm` from being committed to the git repository.

```text
Installing collected packages: nvidia-cusparselt-cu13, mpmath, cuda-toolkit, websockets, uvloop, 
typing-extensions, triton, tqdm, sympy, setuptools, ruff, pyyaml, python-multipart, python-dotenv, 
pygments, pydicom, psycopg-binary, pluggy, Pillow, packaging, nvidia-nvtx, nvidia-nvjitlink, 
nvidia-nccl-cu13, nvidia-cufile, nvidia-cuda-runtime, nvidia-cuda-nvrtc, nvidia-cuda-cupti, 
nvidia-cuda-cccl, numpy, networkx, MarkupSafe, iniconfig, idna, httptools, hf-xet, h11, fsspec, 
filelock, cuda-pathfinder, click, certifi, annotated-types, annotated-doc, uvicorn, typing-inspection, 
SQLAlchemy, pytest, pydantic-core, psycopg, opentelemetry-api, nvidia-nvshmem-cu13, nvidia-cusparse, 
nvidia-cufft, nvidia-cublas, nibabel, Mako, jinja2, httpcore, cuda-bindings, anyio, watchfiles, 
starlette, pydantic, nvidia-cusolver, nvidia-cudnn-cu13, httpx, alembic, huggingface-hub, fastapi, 
torch, torchvision
ERROR: Could not install packages due to an OSError: [Errno 28] No space left on device

Error: Process completed with exit code 1.
```

---

## 2. Root Cause Analysis

1. **Backend CUDA Bloat**: On standard Linux runners, `pip install -r requirements.txt` defaults to GPU-enabled PyTorch wheels with CUDA 13. The compressed downloads exceed 4.5 GB and unpack to over 10 GB. Standard GitHub Actions runners only have ~14 GB of free root disk space. Furthermore, pip cache (`cache: pip`) preserved large wheel fragments, exacerbating disk pressure.
2. **Frontend Untracked Fixtures**: `.gitignore` contained `*.dcm` without an exception for synthetic public demo fixtures. As a result, git never checked out `apps/web/public/fixtures/dicom/brain-ct/slice-*.dcm`, causing `node scripts/verify-dicom-fixture.mjs` (`npm test`) to fail with `AssertionError: Missing DICOM fixture file`.

---

## 3. Remediation Applied

1. **Allow Synthetic Web Fixtures in `.gitignore`**:
   ```gitignore
   # Data and model artifacts: never commit study data or model weights by default
   data/
   *.dcm
   !apps/web/public/fixtures/**/*.dcm
   *.nii
   ```
   Tracked the 5 synthetic phantom slices in git (`~660 KB` total, zero patient data).

2. **Maximize Runner Disk Space & Enforce CPU PyTorch in `.github/workflows/ci.yml`**:
   ```yaml
     api:
       name: API lint and tests
       runs-on: ubuntu-latest
       defaults:
         run:
           working-directory: apps/api
       steps:
         - name: Maximize runner disk space
           run: |
             sudo rm -rf /usr/share/dotnet
             sudo rm -rf /usr/local/lib/android
             sudo rm -rf /opt/ghc
             sudo rm -rf /opt/hostedtoolcache/CodeQL
         - uses: actions/checkout@v4
         - uses: actions/setup-python@v5
           with:
             python-version: "3.12"
         - name: Install dependencies (CPU-only PyTorch to prevent CUDA disk exhaustion)
           run: |
             python -m pip install --no-cache-dir --upgrade pip
             python -m pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
             python -m pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
         - name: Lint
           run: python -m ruff check .
         - name: Test
           run: python -m pytest
   ```

### Verification & Benefits
- **Disk Space**: Removing pre-installed Android, .NET, and GHC toolchains reclaims **>25 GB** of disk space on the runner.
- **CPU PyTorch**: Enforcing `--extra-index-url https://download.pytorch.org/whl/cpu` prevents pip from reinstalling the PyPI CUDA wheel.
- **Web Verification**: `apps/web/public/fixtures/dicom/brain-ct/` now exists in repository checkouts, allowing `npm test` to pass seamlessly.
