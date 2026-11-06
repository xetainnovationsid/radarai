from collections.abc import Generator
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import (
    PYDICOM_IMPLEMENTATION_UID,
    CTImageStorage,
    ExplicitVRLittleEndian,
    generate_uid,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from radar_api.database import Base, get_session
from radar_api.main import app
from radar_api.models import (
    FindingEvidenceRecord,
    ModelVersionRecord,
    PersistedFindingRecord,
    StudyRecord,
    StudySliceRecord,
)
from radar_api.security import (
    Principal,
    create_hmac_session_token,
    rate_limiter,
    set_custom_token_verifier,
)

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
    set_custom_token_verifier(None)


def teardown_function() -> None:
    set_custom_token_verifier(None)
    rate_limiter.clear()
    Base.metadata.drop_all(bind=engine)


def make_test_dicom(
    *,
    burned_in: str | None = None,
    with_overlay: bool = False,
) -> bytes:
    sop_uid = generate_uid()
    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = CTImageStorage
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = PYDICOM_IMPLEMENTATION_UID
    dataset = FileDataset("", {}, file_meta=file_meta, preamble=b"\0" * 128)
    dataset.SOPClassUID = CTImageStorage
    dataset.SOPInstanceUID = sop_uid
    dataset.StudyInstanceUID = generate_uid()
    dataset.SeriesInstanceUID = generate_uid()
    dataset.Modality = "CT"
    dataset.PatientIdentityRemoved = "YES"
    dataset.Rows = 2
    dataset.Columns = 2
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = "MONOCHROME2"
    dataset.BitsAllocated = 16
    dataset.BitsStored = 16
    dataset.HighBit = 15
    dataset.PixelRepresentation = 0
    dataset.ImagePositionPatient = [0, 0, 0]
    dataset.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    if burned_in is not None:
        dataset.BurnedInAnnotation = burned_in
    if with_overlay:
        dataset.add_new((0x6000, 0x3000), "OB", b"\x01\x02")
    dataset.PixelData = b"\x01\x00\x02\x00\x03\x00\x04\x00"
    buffer = BytesIO()
    dataset.save_as(buffer, enforce_file_format=True)
    return buffer.getvalue()


def test_security_headers_and_rate_limit_headers_are_set() -> None:
    response = client.get("/v1/studies")

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "no-store" in response.headers["Cache-Control"]
    assert "default-src 'none'" in response.headers["Content-Security-Policy"]
    assert "X-Request-ID" in response.headers
    assert "X-RateLimit-Limit" in response.headers
    assert "X-RateLimit-Remaining" in response.headers

    preflight = client.options(
        "/v1/studies/00000000-0000-4000-8000-000000000001/findings/00000000-0000-4000-8000-000000000002",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert preflight.status_code == 200
    assert "PUT" in preflight.headers["access-control-allow-methods"]


def test_auth_required_blocks_unauthenticated_requests_and_allows_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RADAR_AUTH_REQUIRED", "true")
    monkeypatch.setenv("RADAR_API_KEYS", "secret-key-alpha,secret-key-beta")

    unauth = client.get("/v1/studies")
    assert unauth.status_code == 401
    assert unauth.headers.get("WWW-Authenticate") == "Bearer"

    bad_key = client.get("/v1/studies", headers={"X-API-Key": "wrong-key"})
    assert bad_key.status_code == 401

    good_key = client.get("/v1/studies", headers={"X-API-Key": "secret-key-beta"})
    assert good_key.status_code == 200


def test_hmac_session_and_firebase_oauth_record_authenticated_reviewer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RADAR_AUTH_REQUIRED", "true")
    monkeypatch.setenv("RADAR_API_SECRET_KEY", "super-secret-signing-key-at-least-32b")
    monkeypatch.setenv("RADAR_ALLOWED_EMAIL_DOMAINS", "telkomuniversity.ac.id")

    set_custom_token_verifier(
        lambda token: (
            Principal(
                subject="firebase:uid-123",
                auth_method="firebase_jwt",
                email="researcher@telkomuniversity.ac.id",
                uid="uid-123",
            )
            if token == "valid-firebase-token"
            else Principal(
                subject="firebase:uid-ext",
                auth_method="firebase_jwt",
                email="outsider@example.com",
                uid="uid-ext",
            )
            if token == "unauthorized-domain-token"
            else Principal(
                subject="firebase:uid-other",
                auth_method="firebase_jwt",
                email="other@telkomuniversity.ac.id",
                uid="uid-other",
            )
            if token == "other-firebase-token"
            else None
        )
    )

    me_resp = client.get(
        "/v1/auth/me",
        headers={"Authorization": "Bearer valid-firebase-token"},
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["authenticated"] is True
    assert me_resp.json()["reviewer_id"] == "researcher@telkomuniversity.ac.id"

    forbidden_resp = client.get(
        "/v1/studies",
        headers={"Authorization": "Bearer unauthorized-domain-token"},
    )
    assert forbidden_resp.status_code == 403

    study_id = uuid4()
    slice_id = uuid4()
    asset_id = uuid4()
    model_version_id = uuid4()
    finding_id = uuid4()
    with TestSession() as session:
        session.add(
            StudyRecord(
                study_id=study_id,
                modality="CT",
                status="ready",
                owner_id="firebase:uid-123",
            )
        )
        session.add(
            ModelVersionRecord(
                model_version_id=model_version_id,
                provider="demo_fixture",
                model_id="test",
                prompt_version="v1",
            )
        )
        session.add(
            StudySliceRecord(
                slice_id=slice_id,
                study_id=study_id,
                index=0,
                image_asset_id=asset_id,
                z_position_mm=0.0,
            )
        )
        session.add(
            PersistedFindingRecord(
                finding_id=finding_id,
                study_id=study_id,
                category="suspected_intracranial_hemorrhage",
                confidence=0.8,
                review_status="pending",
                model_version_id=model_version_id,
            )
        )
        session.add(
            FindingEvidenceRecord(
                finding_id=finding_id,
                slice_id=slice_id,
            )
        )
        session.commit()

    review_resp = client.post(
        f"/v1/studies/{study_id}/findings/{finding_id}/review",
        json={"review_status": "accepted"},
        headers={"Authorization": "Bearer valid-firebase-token"},
    )
    assert review_resp.status_code == 201
    assert review_resp.json()["reviewer"] == "researcher@telkomuniversity.ac.id"

    other_owner_resp = client.get(
        f"/v1/studies/{study_id}",
        headers={"Authorization": "Bearer other-firebase-token"},
    )
    assert other_owner_resp.status_code == 404

    hmac_token = create_hmac_session_token(
        "reviewer-2",
        secret_key="super-secret-signing-key-at-least-32b",
        email="dr.andi@telkomuniversity.ac.id",
    )
    hmac_resp = client.get(
        "/v1/auth/me",
        headers={"Authorization": f"Bearer {hmac_token}"},
    )
    assert hmac_resp.status_code == 200
    assert hmac_resp.json()["auth_method"] == "hmac_session"


def test_local_dev_token_allowed_in_development(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import base64
    import json
    import time

    header = (
        base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
        .decode()
        .rstrip("=")
    )
    payload = (
        base64.urlsafe_b64encode(
            json.dumps(
                {
                    "sub": "local-dev-researcher",
                    "email": "researcher@radar-ai.local",
                    "name": "Dev",
                    "exp": int(time.time()) + 3600,
                }
            ).encode()
        )
        .decode()
        .rstrip("=")
    )
    sig = base64.urlsafe_b64encode(b"radar-local-dev-signature").decode().rstrip("=")
    token = f"{header}.{payload}.{sig}"

    monkeypatch.setenv("RADAR_ENV", "development")
    dev_resp = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert dev_resp.status_code == 200
    assert dev_resp.json()["auth_method"] == "local_dev"
    assert dev_resp.json()["reviewer_id"] == "researcher@radar-ai.local"

    monkeypatch.setenv("RADAR_ENV", "production")
    prod_resp = client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert prod_resp.status_code == 401


def test_rate_limiter_enforces_upload_and_general_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RADAR_UPLOAD_RATE_LIMIT_PER_MINUTE", "2")

    first = client.post("/v1/studies", json={})
    second = client.post("/v1/studies", json={})
    third = client.post("/v1/studies", json={})

    assert first.status_code == 201
    assert second.status_code == 201
    assert third.status_code == 429
    assert "Retry-After" in third.headers


def test_upload_blocks_executable_magic_bytes_and_forbidden_dicom_annotations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RADAR_STORAGE_DIR", str(tmp_path / "private"))
    study_id = client.post("/v1/studies", json={}).json()["study_id"]

    exe_resp = client.post(
        f"/v1/studies/{study_id}/dicom",
        files={"files": ("malware.dcm", b"MZ\x90\x00\x03\x00\x00\x00", "application/dicom")},
    )
    assert exe_resp.status_code == 422
    assert "forbidden executable" in exe_resp.json()["detail"].lower()

    html_mime_resp = client.post(
        f"/v1/studies/{study_id}/dicom",
        files={"files": ("xss.dcm", make_test_dicom(), "text/html")},
    )
    assert html_mime_resp.status_code == 422
    assert "forbidden file content type" in html_mime_resp.json()["detail"].lower()

    burned_resp = client.post(
        f"/v1/studies/{study_id}/dicom",
        files={"files": ("burned.dcm", make_test_dicom(burned_in="YES"), "application/dicom")},
    )
    assert burned_resp.status_code == 422
    assert "burned-in annotations" in burned_resp.json()["detail"].lower()

    overlay_resp = client.post(
        f"/v1/studies/{study_id}/dicom",
        files={"files": ("overlay.dcm", make_test_dicom(with_overlay=True), "application/dicom")},
    )
    assert overlay_resp.status_code == 422
    assert "overlay planes" in overlay_resp.json()["detail"].lower()
