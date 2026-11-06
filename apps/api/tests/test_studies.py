import time
from collections.abc import Generator
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import (
    PYDICOM_IMPLEMENTATION_UID,
    CTImageStorage,
    ExplicitVRLittleEndian,
    generate_uid,
)
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from radar_api import inference_jobs
from radar_api import main as main_module
from radar_api.contracts import ReportContent
from radar_api.database import Base, get_session
from radar_api.inference_service import ModelUnavailableError
from radar_api.main import app
from radar_api.models import (
    ImageAssetRecord,
    InferenceScoreRecord,
)
from radar_api.security import rate_limiter
from radar_api.storage import PrivateImageStore

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def override_session() -> Generator[Session, None, None]:
    with TestSession() as session:
        yield session


app.dependency_overrides[get_session] = override_session
client = TestClient(app)


def setup_function() -> None:
    app.dependency_overrides[get_session] = override_session
    Base.metadata.create_all(bind=engine)
    rate_limiter.clear()


def teardown_function() -> None:
    rate_limiter.clear()
    Base.metadata.drop_all(bind=engine)


def wait_for_job(study_id: str, job_id: str) -> dict[str, object]:
    for _ in range(100):
        response = client.get(f"/v1/studies/{study_id}/inference-jobs/{job_id}")
        assert response.status_code == 200
        result = response.json()
        if result["status"] in {"completed", "failed"}:
            return result
        time.sleep(0.01)
    raise AssertionError("Inference job did not finish within one second")


def test_create_and_read_study() -> None:
    created = client.post("/v1/studies", json={})

    assert created.status_code == 201
    study = created.json()
    assert study["modality"] == "CT"
    assert study["status"] == "uploaded"
    assert study["slices"] == []

    study_id = study["study_id"]
    assert client.get(f"/v1/studies/{study_id}").json() == study
    assert client.get("/v1/studies").json() == [study]


def test_create_study_rejects_patient_identifying_fields() -> None:
    response = client.post("/v1/studies", json={"patient_name": "Example Person"})

    assert response.status_code == 422


def test_unknown_study_returns_not_found() -> None:
    response = client.get("/v1/studies/00000000-0000-4000-8000-000000000001")

    assert response.status_code == 404
    assert response.json() == {"detail": "Study not found"}


def make_ct_dicom(
    *,
    z_position: float = 0,
    modality: str = "CT",
    patient_name: str = "",
    study_uid: str | None = None,
    series_uid: str | None = None,
) -> bytes:
    study_uid = study_uid or generate_uid()
    series_uid = series_uid or generate_uid()
    sop_uid = generate_uid()
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = CTImageStorage
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID
    dataset = FileDataset("", {}, file_meta=file_meta, preamble=b"\0" * 128)
    dataset.SOPClassUID = CTImageStorage
    dataset.SOPInstanceUID = sop_uid
    dataset.StudyInstanceUID = study_uid
    dataset.SeriesInstanceUID = series_uid
    dataset.Modality = modality
    dataset.PatientIdentityRemoved = "YES"
    dataset.PatientName = patient_name
    dataset.Rows = 2
    dataset.Columns = 2
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = "MONOCHROME2"
    dataset.BitsAllocated = 16
    dataset.BitsStored = 16
    dataset.HighBit = 15
    dataset.PixelRepresentation = 0
    dataset.ImagePositionPatient = [0, 0, z_position]
    dataset.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    dataset.PixelData = b"\x01\x00\x02\x00\x03\x00\x04\x00"
    buffer = BytesIO()
    dataset.save_as(buffer, enforce_file_format=True)
    return buffer.getvalue()


def create_study() -> str:
    response = client.post("/v1/studies", json={})
    assert response.status_code == 201
    return response.json()["study_id"]


def test_upload_accepts_anonymized_ct_series_and_stores_privately(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    storage_root = tmp_path / "private"
    monkeypatch.setenv("RADAR_STORAGE_DIR", str(storage_root))
    study_id = create_study()
    series_study_uid = generate_uid()
    series_uid = generate_uid()
    first = make_ct_dicom(z_position=5, study_uid=series_study_uid, series_uid=series_uid)
    second = make_ct_dicom(z_position=1, study_uid=series_study_uid, series_uid=series_uid)

    response = client.post(
        f"/v1/studies/{study_id}/dicom",
        files=[
            ("files", ("../../first.dcm", first, "application/dicom")),
            ("files", ("second.dcm", second, "application/dicom")),
        ],
    )

    assert response.status_code == 201
    result = response.json()
    assert result["status"] == "ready"
    assert [item["index"] for item in result["slices"]] == [0, 1]
    assert [item["z_position_mm"] for item in result["slices"]] == [1.0, 5.0]
    assert "storage_key" not in response.text
    assert "first.dcm" not in response.text

    with TestSession() as session:
        assets = list(session.scalars(select(ImageAssetRecord)).all())
    assert len(assets) == 2
    store = PrivateImageStore(storage_root)
    stored_paths = [store.path_for(asset.storage_key) for asset in assets]
    assert all(
        path.is_relative_to(storage_root.resolve()) and path.is_file() for path in stored_paths
    )
    assert {path.read_bytes() for path in stored_paths} == {first, second}


@pytest.mark.parametrize(
    ("payload", "filename", "detail"),
    [
        (b"not a DICOM file", "image.dcm", "DICOM file is corrupted or cannot be decoded"),
        (
            None,
            "patient.dcm",
            "DICOM contains identifying metadata; upload an anonymized series",
        ),
    ],
)
def test_upload_rejects_corrupt_and_identifiable_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    payload: bytes | None,
    filename: str,
    detail: str,
) -> None:
    monkeypatch.setenv("RADAR_STORAGE_DIR", str(tmp_path / "private"))
    study_id = create_study()
    if payload is None:
        payload = make_ct_dicom(patient_name="Example^Person")

    response = client.post(
        f"/v1/studies/{study_id}/dicom",
        files={"files": (filename, payload, "application/dicom")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == detail
    assert client.get(f"/v1/studies/{study_id}").json()["slices"] == []


def test_upload_rejects_non_ct_series(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RADAR_STORAGE_DIR", str(tmp_path / "private"))
    study_id = create_study()
    response = client.post(
        f"/v1/studies/{study_id}/dicom",
        files={"files": ("image.dcm", make_ct_dicom(modality="MR"), "application/dicom")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Only CT images are accepted"


def test_upload_rejects_files_from_different_series(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RADAR_STORAGE_DIR", str(tmp_path / "private"))
    study_id = create_study()
    series_study_uid = generate_uid()
    response = client.post(
        f"/v1/studies/{study_id}/dicom",
        files=[
            (
                "files",
                (
                    "first.dcm",
                    make_ct_dicom(
                        z_position=0,
                        study_uid=series_study_uid,
                        series_uid=generate_uid(),
                    ),
                    "application/dicom",
                ),
            ),
            (
                "files",
                (
                    "second.dcm",
                    make_ct_dicom(
                        z_position=1,
                        study_uid=series_study_uid,
                        series_uid=generate_uid(),
                    ),
                    "application/dicom",
                ),
            ),
        ],
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "DICOM files do not belong to the same CT series"
    assert client.get(f"/v1/studies/{study_id}").json()["slices"] == []


def test_upload_enforces_size_limit_and_cleans_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage_root = tmp_path / "private"
    monkeypatch.setenv("RADAR_STORAGE_DIR", str(storage_root))
    monkeypatch.setenv("RADAR_MAX_DICOM_FILE_BYTES", "10")
    study_id = create_study()

    response = client.post(
        f"/v1/studies/{study_id}/dicom",
        files={"files": ("large.dcm", make_ct_dicom(), "application/dicom")},
    )

    assert response.status_code == 413
    assert not list(storage_root.glob("incoming-*.tmp"))
    assert client.get(f"/v1/studies/{study_id}").json()["slices"] == []


def test_private_store_rejects_path_traversal(tmp_path: Path) -> None:
    store = PrivateImageStore(tmp_path / "private")

    with pytest.raises(ValueError, match="outside the private root"):
        store.path_for("../public/image.dcm")


def test_web_fixture_series_upload_and_study_list_status_transition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage_root = tmp_path / "private"
    monkeypatch.setenv("RADAR_STORAGE_DIR", str(storage_root))
    fixture_dir = (
        Path(__file__).resolve().parents[2] / "web" / "public" / "fixtures" / "dicom" / "brain-ct"
    )
    fixture_files = sorted(fixture_dir.glob("slice-*.dcm"))
    assert len(fixture_files) == 5

    study_id = create_study()
    initial_list = client.get("/v1/studies").json()
    assert len(initial_list) == 1
    assert initial_list[0]["status"] == "uploaded"

    response = client.post(
        f"/v1/studies/{study_id}/dicom",
        files=[
            ("files", (path.name, path.read_bytes(), "application/dicom")) for path in fixture_files
        ],
    )
    assert response.status_code == 201
    updated = response.json()
    assert updated["status"] == "ready"
    assert len(updated["slices"]) == 5
    assert [s["z_position_mm"] for s in updated["slices"]] == [
        -15.0,
        -10.0,
        1.5,
        6.5,
        11.5,
    ]

    study_list = client.get("/v1/studies").json()
    assert len(study_list) == 1
    assert study_list[0]["study_id"] == study_id
    assert study_list[0]["status"] == "ready"
    assert len(study_list[0]["slices"]) == 5

    analysis_resp = client.get(f"/v1/studies/{study_id}/analysis")
    assert analysis_resp.status_code == 200
    analysis = analysis_resp.json()
    assert analysis["schema_version"] == "1.0.0"
    assert analysis["model_version"]["provider"] == "demo_fixture"
    assert analysis["model_version"]["model_id"] == "synthetic-fixture"
    assert analysis["model_version"]["prompt_version"] == "demo-fixture-v1"
    assert len(analysis["findings"]) == 1

    finding = analysis["findings"][0]
    expected_evidence_ids = {
        updated["slices"][2]["slice_id"],
        updated["slices"][3]["slice_id"],
    }
    assert set(finding["evidence_slice_ids"]) == expected_evidence_ids
    assert finding["review_status"] == "pending"

    preview_resp = client.get(
        f"/v1/studies/{study_id}/slices/{updated['slices'][2]['slice_id']}/image"
    )
    assert preview_resp.status_code == 200
    assert preview_resp.headers["content-type"] == "image/png"

    dicom_resp = client.get(
        f"/v1/studies/{study_id}/slices/{updated['slices'][4]['slice_id']}/dicom"
    )
    assert dicom_resp.status_code == 200
    assert dicom_resp.headers["content-type"] == "application/dicom"
    assert dicom_resp.content == fixture_files[4].read_bytes()

    review_resp = client.post(
        f"/v1/studies/{study_id}/findings/{finding['finding_id']}/review",
        json={"review_status": "accepted"},
    )
    assert review_resp.status_code == 201
    assert review_resp.json()["previous_review_status"] == "pending"
    assert review_resp.json()["review_status"] == "accepted"

    # Uploading slice-4.dcm alone (Z=11.5mm, normal convexity) yields 0 findings
    single_study_id = create_study()
    single_upload = client.post(
        f"/v1/studies/{single_study_id}/dicom",
        files=[("files", ("slice-4.dcm", fixture_files[4].read_bytes(), "application/dicom"))],
    )
    assert single_upload.status_code == 201
    single_analysis = client.get(f"/v1/studies/{single_study_id}/analysis")
    assert single_analysis.status_code == 200
    assert single_analysis.json()["findings"] == []
    assert single_analysis.json()["model_version"]["provider"] == "demo_fixture"


def test_inference_job_persists_slice_scores_and_model_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RADAR_STORAGE_DIR", str(tmp_path / "private"))
    monkeypatch.setattr(inference_jobs, "SessionLocal", TestSession)
    fixture_dir = (
        Path(__file__).resolve().parents[2] / "web" / "public" / "fixtures" / "dicom" / "brain-ct"
    )
    fixture_files = sorted(fixture_dir.glob("slice-*.dcm"))
    study_id = create_study()
    upload = client.post(
        f"/v1/studies/{study_id}/dicom",
        files=[
            ("files", (path.name, path.read_bytes(), "application/dicom")) for path in fixture_files
        ],
    )
    assert upload.status_code == 201

    monkeypatch.setattr(
        inference_jobs,
        "score_local_checkpoint",
        lambda paths: {
            "model_id": "test-densenet-v1",
            "checkpoint_sha256": "a" * 64,
            "device": "cpu",
            "slices": [
                {
                    "file": path.name,
                    "scores": {"0": 0.9 if index else 0.1, "1": 0.1 if index else 0.9},
                }
                for index, path in enumerate(paths)
            ],
        },
    )
    queued = client.post(f"/v1/studies/{study_id}/inference-jobs")
    assert queued.status_code == 202
    job = wait_for_job(study_id, queued.json()["job_id"])
    assert job["status"] == "completed"

    scores_response = client.get(f"/v1/studies/{study_id}/scores")
    assert scores_response.status_code == 200
    scores = scores_response.json()
    assert scores["model_id"] == "test-densenet-v1"
    assert scores["checkpoint_sha256"] == "a" * 64
    assert len(scores["slices"]) == 5
    assert scores["slices"][0]["class_1_score"] == 0.9

    analysis_response = client.get(f"/v1/studies/{study_id}/analysis")
    assert analysis_response.status_code == 200
    analysis = analysis_response.json()
    assert analysis["model_version"]["provider"] == "local_checkpoint"
    assert analysis["model_version"]["preprocessing_version"] == "densenet121-ct-preprocessing/v2"
    assert len(analysis["findings"]) == 1
    assert analysis["findings"][0]["evidence_slice_ids"] == [scores["slices"][0]["slice_id"]]
    with TestSession() as session:
        assert len(list(session.scalars(select(InferenceScoreRecord)).all())) == 10


def test_inference_job_records_model_unavailable_without_fake_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RADAR_STORAGE_DIR", str(tmp_path / "private"))
    monkeypatch.setattr(inference_jobs, "SessionLocal", TestSession)
    study_id = create_study()
    upload = client.post(
        f"/v1/studies/{study_id}/dicom",
        files={"files": ("slice.dcm", make_ct_dicom(), "application/dicom")},
    )
    assert upload.status_code == 201

    def no_model(_paths: list[Path]) -> dict[str, object]:
        raise ModelUnavailableError("checkpoint unavailable")

    monkeypatch.setattr(inference_jobs, "score_local_checkpoint", no_model)
    queued = client.post(f"/v1/studies/{study_id}/inference-jobs")
    assert queued.status_code == 202
    job = wait_for_job(study_id, queued.json()["job_id"])
    assert job["status"] == "failed"
    assert job["error_code"] == "model_unavailable"
    assert client.get(f"/v1/studies/{study_id}/analysis").status_code == 404
    assert client.get(f"/v1/studies/{study_id}").json()["status"] == "failed"


def test_manual_report_draft_is_versioned_and_rejects_unknown_citations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RADAR_STORAGE_DIR", str(tmp_path / "private"))
    fixture_dir = (
        Path(__file__).resolve().parents[2] / "web" / "public" / "fixtures" / "dicom" / "brain-ct"
    )
    fixture_files = sorted(fixture_dir.glob("slice-*.dcm"))
    study_id = create_study()
    upload = client.post(
        f"/v1/studies/{study_id}/dicom",
        files=[
            ("files", (path.name, path.read_bytes(), "application/dicom")) for path in fixture_files
        ],
    )
    assert upload.status_code == 201
    finding_id = client.get(f"/v1/studies/{study_id}/analysis").json()["findings"][0]["finding_id"]
    content = {
        "findings": [{"text": "Synthetic source-cited draft.", "finding_ids": [finding_id]}],
        "impression": {"text": "Requires human review.", "finding_ids": [finding_id]},
        "limitations": "Research prototype; not for clinical use.",
    }
    saved = client.post(
        f"/v1/studies/{study_id}/reports/drafts",
        json={"manual_content": content},
    )
    assert saved.status_code == 201
    assert saved.json()["generation_mode"] == "manual_fallback"
    assert saved.json()["version"] == 1

    invalid_content = {
        **content,
        "impression": {
            "text": "Unsupported citation.",
            "finding_ids": ["00000000-0000-4000-8000-000000000099"],
        },
    }
    rejected = client.post(
        f"/v1/studies/{study_id}/reports/drafts",
        json={"manual_content": invalid_content},
    )
    assert rejected.status_code == 422
    listed = client.get(f"/v1/studies/{study_id}/reports/drafts")
    assert listed.status_code == 200
    assert [item["version"] for item in listed.json()] == [1]


def test_finding_correction_is_versioned_and_audited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RADAR_STORAGE_DIR", str(tmp_path / "private"))
    fixture_dir = (
        Path(__file__).resolve().parents[2] / "web" / "public" / "fixtures" / "dicom" / "brain-ct"
    )
    fixture_files = sorted(fixture_dir.glob("slice-*.dcm"))
    study_id = create_study()
    uploaded = client.post(
        f"/v1/studies/{study_id}/dicom",
        files=[
            ("files", (path.name, path.read_bytes(), "application/dicom")) for path in fixture_files
        ],
    )
    assert uploaded.status_code == 201
    finding = client.get(f"/v1/studies/{study_id}/analysis").json()["findings"][0]
    corrected = client.put(
        f"/v1/studies/{study_id}/findings/{finding['finding_id']}",
        json={
            "confidence": 0.42,
            "evidence_slice_ids": finding["evidence_slice_ids"],
        },
    )
    assert corrected.status_code == 201
    event = corrected.json()
    assert event["action"] == "edit"
    assert event["version"] == 2
    assert event["review_status"] == "uncertain"
    assert event["previous_snapshot"]["confidence"] == 0.84
    assert event["current_snapshot"]["confidence"] == 0.42

    reviews = client.get(f"/v1/studies/{study_id}/findings/{finding['finding_id']}/reviews")
    assert reviews.status_code == 200
    assert [item["version"] for item in reviews.json()] == [2]


def test_meta_report_route_uses_only_deidentified_saved_findings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RADAR_STORAGE_DIR", str(tmp_path / "private"))
    fixture_dir = (
        Path(__file__).resolve().parents[2] / "web" / "public" / "fixtures" / "dicom" / "brain-ct"
    )
    fixture_files = sorted(fixture_dir.glob("slice-*.dcm"))
    study_id = create_study()
    uploaded = client.post(
        f"/v1/studies/{study_id}/dicom",
        files=[
            ("files", (path.name, path.read_bytes(), "application/dicom")) for path in fixture_files
        ],
    )
    assert uploaded.status_code == 201
    finding = client.get(f"/v1/studies/{study_id}/analysis").json()["findings"][0]
    submitted_source: list[dict[str, object]] = []

    def fake_meta_draft(source: list[dict[str, object]]) -> tuple[ReportContent, str]:
        submitted_source.extend(source)
        finding_id = source[0]["finding_id"]
        return (
            ReportContent.model_validate(
                {
                    "findings": [
                        {"text": "Source-supported synthetic finding.", "finding_ids": [finding_id]}
                    ],
                    "impression": {
                        "text": "Human review required.",
                        "finding_ids": [finding_id],
                    },
                    "limitations": "Research prototype; not for clinical use.",
                }
            ),
            "mock-meta-model",
        )

    monkeypatch.setattr(main_module, "generate_report_content", fake_meta_draft)
    response = client.post(f"/v1/studies/{study_id}/reports/drafts", json={})
    assert response.status_code == 201
    assert response.json()["generation_mode"] == "meta_model_api"
    assert response.json()["model_id"] == "mock-meta-model"
    assert submitted_source == [
        {
            "finding_id": finding["finding_id"],
            "category": "suspected_intracranial_hemorrhage",
            "confidence": 0.84,
            "review_status": "pending",
            "evidence_slice_ids": finding["evidence_slice_ids"],
        }
    ]
