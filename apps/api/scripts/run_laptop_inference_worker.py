"""Poll the RADAR API and run its checkpoint inference jobs on this computer."""

from __future__ import annotations

import hashlib
import logging
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from uuid import UUID

import httpx
from dotenv import load_dotenv

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT / "src"))
load_dotenv(API_ROOT / ".env.worker")

from radar_api.inference_service import (  # noqa: E402
    ModelUnavailableError,
    score_local_checkpoint,
)
from radar_api.localization_service import (  # noqa: E402
    LocalizationInputError,
    LocalizationUnavailableError,
    localize_dicom_series,
)

logging.basicConfig(
    level=os.getenv("RADAR_WORKER_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s radar-worker %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("radar_worker")


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required setting: {name} (configure apps/api/.env.worker)")
    return value


def run() -> None:
    checkpoint = API_ROOT / "data" / "model-artifacts" / "ct-binary-densenet121.pt"
    if not checkpoint.is_file():
        raise SystemExit("The local DenseNet121 checkpoint is missing.")
    os.environ["RADAR_CT_CHECKPOINT"] = str(checkpoint.resolve())
    base_url = _required("RADAR_WORKER_API_URL").rstrip("/")
    token = _required("RADAR_WORKER_TOKEN")
    study_filter = os.getenv("RADAR_WORKER_STUDY_ID", "").strip()
    if study_filter:
        try:
            study_filter = str(UUID(study_filter))
        except ValueError as error:
            raise SystemExit("RADAR_WORKER_STUDY_ID must be a valid study UUID.") from error
    if not base_url.startswith("https://") and not base_url.startswith("http://127.0.0.1"):
        raise SystemExit("RADAR_WORKER_API_URL must use HTTPS outside localhost")
    headers = {"Authorization": f"Bearer {token}"}
    poll_seconds = max(1.0, float(os.getenv("RADAR_WORKER_POLL_SECONDS", "3")))
    timeout = httpx.Timeout(120.0, connect=15.0)
    with httpx.Client(
        base_url=base_url,
        headers=headers,
        timeout=timeout,
        follow_redirects=False,
    ) as client:
        health = client.get("/internal/worker/health")
        health.raise_for_status()
        import torch

        if not torch.cuda.is_available():
            raise SystemExit("CUDA is unavailable; the laptop worker requires the local GPU.")
        os.environ["RADAR_CT_DEVICE"] = "cuda"
        logger.info(
            "Connected to backend; device=%s",
            torch.cuda.get_device_name(0),
        )
        while True:
            try:
                claim_kwargs = {"json": {"study_id": study_filter}} if study_filter else {}
                response = client.post("/internal/worker/claim", **claim_kwargs)
                response.raise_for_status()
                payload = response.json()
                job = payload.get("job")
                if not job:
                    time.sleep(poll_seconds)
                    continue
                _run_job(client, job, payload.get("slices", []))
            except KeyboardInterrupt:
                logger.info("Worker stopped")
                return
            except Exception as error:
                logger.error("Worker loop error: %s", type(error).__name__)
                time.sleep(poll_seconds)


def _run_job(client: httpx.Client, job: dict[str, str], slices: list[dict[str, object]]) -> None:
    job_id = job["job_id"]
    lease_token = job.get("lease_token", "")
    if not lease_token:
        logger.error("Job %s did not include a worker lease", job_id)
        return
    lease_headers = {"X-RADAR-Worker-Lease": lease_token}
    if not slices:
        _fail(client, job_id, lease_headers, "inference_failed")
        return
    heartbeat_stop = threading.Event()
    heartbeat = threading.Thread(
        target=_heartbeat_job,
        args=(
            str(client.base_url).rstrip("/"),
            client.headers["Authorization"],
            job_id,
            lease_headers,
            heartbeat_stop,
        ),
        name=f"radar-heartbeat-{job_id[:8]}",
        daemon=True,
    )
    heartbeat.start()
    try:
        with tempfile.TemporaryDirectory(prefix="radar-inference-") as directory:
            paths: list[Path] = []
            slice_ids: list[str] = []
            for item in sorted(slices, key=lambda value: int(value["index"])):
                slice_id = str(item["slice_id"])
                index = int(item["index"])
                response = client.get(
                    f"/internal/worker/jobs/{job_id}/slices/{slice_id}",
                    headers=lease_headers,
                )
                response.raise_for_status()
                digest = hashlib.sha256(response.content).hexdigest()
                if digest != response.headers.get("X-DICOM-SHA256"):
                    raise ValueError("slice checksum mismatch")
                path = Path(directory) / f"slice-{index:06d}.dcm"
                path.write_bytes(response.content)
                paths.append(path)
                slice_ids.append(slice_id)

            result = score_local_checkpoint(paths)
            response_rows = []
            for slice_id, output in zip(slice_ids, result["slices"], strict=True):
                response_rows.append({"slice_id": slice_id, "scores": output["scores"]})
            localization_payload = None
            try:
                localization_result = localize_dicom_series(tuple(str(path) for path in paths))
                localization_rows = []
                for slice_id, output in zip(slice_ids, localization_result["slices"], strict=True):
                    localization_rows.append(
                        {
                            "slice_id": slice_id,
                            "index": int(output["index"]),
                            "image_width": int(output["image_width"]),
                            "image_height": int(output["image_height"]),
                            "box": output["box"],
                            "mask_pixels": int(output["mask_pixels"]),
                        }
                    )
                localization_payload = {
                    "model_id": localization_result["model_id"],
                    "checkpoint_sha256": localization_result["checkpoint_sha256"],
                    "device": localization_result["device"],
                    "threshold": localization_result["threshold"],
                    "slices": localization_rows,
                }
                logger.info("SAMIHS CUDA localization completed (%d slices)", len(slice_ids))
            except (LocalizationInputError, LocalizationUnavailableError) as error:
                logger.error("SAMIHS unavailable for job %s (%s)", job_id, type(error).__name__)
            except Exception as error:
                logger.error("SAMIHS failed for job %s (%s)", job_id, type(error).__name__)
            completion = client.post(
                f"/internal/worker/jobs/{job_id}/complete",
                headers=lease_headers,
                json={
                    "model_id": result["model_id"],
                    "checkpoint_sha256": result["checkpoint_sha256"],
                    "device": result["device"],
                    "slices": response_rows,
                    "localization": localization_payload,
                },
            )
            completion.raise_for_status()
        logger.info("Completed job %s (%d slices)", job_id, len(slices))
    except ModelUnavailableError as error:
        logger.error("Job %s has no runnable local model (%s)", job_id, type(error).__name__)
        _fail(client, job_id, lease_headers, "model_unavailable")
    except Exception as error:
        logger.error("Job %s failed: %s", job_id, type(error).__name__)
        _fail(client, job_id, lease_headers, "inference_failed")
    finally:
        heartbeat_stop.set()
        heartbeat.join(timeout=2)


def _heartbeat_job(
    base_url: str,
    authorization: str,
    job_id: str,
    lease_headers: dict[str, str],
    stop: threading.Event,
) -> None:
    headers = {"Authorization": authorization, **lease_headers}
    with httpx.Client(
        base_url=base_url,
        headers=headers,
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=False,
    ) as heartbeat_client:
        while not stop.wait(60):
            try:
                response = heartbeat_client.post(f"/internal/worker/jobs/{job_id}/heartbeat")
                if response.status_code == 409:
                    logger.error("Job %s lease expired or was reclaimed", job_id)
                    return
                response.raise_for_status()
            except Exception as error:
                logger.warning("Job %s heartbeat failed: %s", job_id, type(error).__name__)


def _fail(
    client: httpx.Client,
    job_id: str,
    lease_headers: dict[str, str],
    error_code: str,
) -> None:
    try:
        response = client.post(
            f"/internal/worker/jobs/{job_id}/fail",
            headers=lease_headers,
            json={"error_code": error_code},
        )
        response.raise_for_status()
    except Exception as error:
        logger.error("Could not report failure for job %s: %s", job_id, type(error).__name__)


if __name__ == "__main__":
    run()
