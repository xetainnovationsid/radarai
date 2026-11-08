"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import type { Study, StudyStatus } from "@radar-ai/contracts";
import { useAuth } from "@/components/AuthContext";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingSkeleton } from "@/components/states/LoadingSkeleton";
import {
  ApiUploadError,
  apiFetch,
  assertValidUuid,
  fetchDemoDicomFixtures,
  formatBytes,
  uploadDicomSeriesWithProgress,
  validateDicomFilesBeforeUpload,
} from "@/lib/api-client";

type UploadStage =
  | "idle"
  | "validating"
  | "creating"
  | "uploading"
  | "completed"
  | "error";

type StatusFilter = "all" | StudyStatus;

const STATUS_LABELS: Record<StudyStatus, string> = {
  ready: "Awaiting review",
  uploaded: "Uploaded",
  processing: "Processing",
  failed: "Needs attention",
};

export default function DashboardPage() {
  const { user, authRequired } = useAuth();

  // Study queue state
  const [studies, setStudies] = useState<Study[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [queueError, setQueueError] = useState("");
  const [queueErrorCode, setQueueErrorCode] = useState("ERR_RADAR_QUEUE");
  const [lastSyncedAt, setLastSyncedAt] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [searchQuery, setSearchQuery] = useState("");

  // Upload workflow state
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploadStage, setUploadStage] = useState<UploadStage>("idle");
  const [uploadPercent, setUploadPercent] = useState(0);
  const [uploadedBytes, setUploadedBytes] = useState(0);
  const [totalUploadBytes, setTotalUploadBytes] = useState(0);
  const [uploadError, setUploadError] = useState("");
  const [uploadErrorCode, setUploadErrorCode] = useState("ERR_RADAR_UPLOAD");
  const [uploadSuccessMessage, setUploadSuccessMessage] = useState("");
  const [loadingFixtures, setLoadingFixtures] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const refresh = useCallback(async (isBackground = false) => {
    if (!isBackground) {
      setRefreshing(true);
    }
    try {
      const response = await apiFetch("/v1/studies");
      if (response.status === 401) {
        setQueueErrorCode("ERR_AUTH_401");
        throw new Error(
          "Autentikasi diperlukan. Silakan klik 'Login Peneliti' di bagian atas halaman."
        );
      }
      if (response.status === 429) {
        setQueueErrorCode("ERR_RATE_LIMIT_429");
        throw new Error(
          "Batas laju permintaan (rate limit) tercapai. Tunggu beberapa saat sebelum memuat ulang."
        );
      }
      if (!response.ok) {
        setQueueErrorCode(`ERR_HTTP_${response.status}`);
        throw new Error(`API returned ${response.status}`);
      }
      const data = (await response.json()) as Study[];
      setStudies(data);
      setQueueError("");
      setLastSyncedAt(
        new Date().toLocaleTimeString("id-ID", {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        })
      );
    } catch (cause) {
      if (!isBackground) {
        setQueueError(
          cause instanceof Error && !cause.message.startsWith("API returned")
            ? cause.message
            : "Tidak dapat menghubungi layanan backend RADAR AI. Pastikan server API berjalan di port 8000."
        );
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    let ignore = false;
    async function loadInitialStudies() {
      try {
        const response = await apiFetch("/v1/studies");
        if (response.status === 401) {
          if (!ignore) setQueueErrorCode("ERR_AUTH_401");
          throw new Error(
            "Autentikasi diperlukan. Silakan klik 'Login Peneliti' di bagian atas halaman."
          );
        }
        if (response.status === 429) {
          if (!ignore) setQueueErrorCode("ERR_RATE_LIMIT_429");
          throw new Error(
            "Batas laju permintaan (rate limit) tercapai. Tunggu beberapa saat sebelum memuat ulang."
          );
        }
        if (!response.ok) {
          if (!ignore) setQueueErrorCode(`ERR_HTTP_${response.status}`);
          throw new Error(`API returned ${response.status}`);
        }
        const data = (await response.json()) as Study[];
        if (!ignore) {
          setStudies(data);
          setQueueError("");
          setLastSyncedAt(
            new Date().toLocaleTimeString("id-ID", {
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
            })
          );
        }
      } catch (cause) {
        if (!ignore) {
          setQueueError(
            cause instanceof Error && !cause.message.startsWith("API returned")
              ? cause.message
              : "Tidak dapat menghubungi layanan backend RADAR AI. Pastikan server API berjalan di port 8000."
          );
        }
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    }
    void loadInitialStudies();
    return () => {
      ignore = true;
    };
  }, [user]);

  // Poll automatically when any study is actively processing
  useEffect(() => {
    const hasActiveProcessing = studies.some(
      (study) => study.status === "processing"
    );
    if (!hasActiveProcessing) return;

    const timer = setInterval(() => {
      void refresh(true);
    }, 6000);
    return () => clearInterval(timer);
  }, [studies, refresh]);

  const totalSelectedBytes = useMemo(
    () => selectedFiles.reduce((acc, file) => acc + file.size, 0),
    [selectedFiles]
  );

  const statusCounts = useMemo(() => {
    const counts: Record<StatusFilter, number> = {
      all: studies.length,
      ready: 0,
      uploaded: 0,
      processing: 0,
      failed: 0,
    };
    for (const study of studies) {
      if (study.status in counts) {
        counts[study.status] += 1;
      }
    }
    return counts;
  }, [studies]);

  const filteredStudies = useMemo(() => {
    const normalizedQuery = searchQuery.trim().toLowerCase();
    return studies.filter((study) => {
      const matchesStatus =
        statusFilter === "all" || study.status === statusFilter;
      const matchesQuery =
        !normalizedQuery ||
        study.study_id.toLowerCase().includes(normalizedQuery) ||
        study.study_id.slice(0, 8).toLowerCase().includes(normalizedQuery);
      return matchesStatus && matchesQuery;
    });
  }, [studies, statusFilter, searchQuery]);

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const files = event.target.files ? Array.from(event.target.files) : [];
    setSelectedFiles(files);
    setUploadError("");
    setUploadSuccessMessage("");
    if (files.length > 0 && uploadStage === "error") {
      setUploadStage("idle");
    }
  }

  function clearSelectedFiles() {
    setSelectedFiles([]);
    setUploadStage("idle");
    setUploadPercent(0);
    setUploadedBytes(0);
    setTotalUploadBytes(0);
    setUploadError("");
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }

  function cancelActiveUpload() {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
  }

  const executeUpload = useCallback(
    async (filesToUpload: File[]) => {
      if (filesToUpload.length === 0) {
        setUploadStage("error");
        setUploadErrorCode("ERR_NO_FILES");
        setUploadError("Pilih minimal satu file DICOM CT (.dcm) terlebih dahulu.");
        return;
      }
      if (authRequired && !user) {
        setUploadStage("error");
        setUploadErrorCode("ERR_AUTH_REQUIRED");
        setUploadError(
          "Silakan login melalui Firebase OAuth terlebih dahulu sebelum mengunggah studi DICOM."
        );
        return;
      }

      setUploadError("");
      setUploadSuccessMessage("");
      setUploadStage("validating");
      setUploadPercent(10);
      const totalBytes = filesToUpload.reduce((sum, f) => sum + f.size, 0);
      setTotalUploadBytes(totalBytes);
      setUploadedBytes(0);

      let createdStudyId: string | null = null;
      const controller = new AbortController();
      abortControllerRef.current = controller;

      try {
        // Stage 1: Client-side binary DICM Part 10 validation
        const validatedFiles = await validateDicomFilesBeforeUpload(filesToUpload);

        // Stage 2: Create study metadata record
        setUploadStage("creating");
        setUploadPercent(20);
        const created = await apiFetch("/v1/studies", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ modality: "CT" }),
          signal: controller.signal,
        });

        if (created.status === 401) {
          throw new ApiUploadError(
            "Sesi autentikasi tidak valid atau telah berakhir. Silakan login kembali.",
            401,
            "ERR_AUTH_401"
          );
        }
        if (created.status === 429) {
          throw new ApiUploadError(
            "Terlalu banyak permintaan pembuatan studi (HTTP 429). Silakan tunggu 1 menit.",
            429,
            "ERR_RATE_LIMIT_429"
          );
        }
        if (!created.ok) {
          throw new ApiUploadError(
            `Gagal membuat catatan studi di server (HTTP ${created.status}).`,
            created.status,
            `ERR_CREATE_STUDY_${created.status}`
          );
        }

        const studyRecord = (await created.json()) as Study;
        createdStudyId = assertValidUuid(studyRecord.study_id, "Study ID");

        // Stage 3: Stream multipart DICOM slices with live progress
        setUploadStage("uploading");
        setUploadPercent(25);
        const updatedStudy = await uploadDicomSeriesWithProgress(
          createdStudyId,
          validatedFiles,
          (progress) => {
            setUploadedBytes(progress.loaded);
            setTotalUploadBytes(progress.total);
            // Map network upload progress into 25%..95% of overall bar
            const scaledPercent = 25 + Math.round((progress.percent / 100) * 70);
            setUploadPercent(Math.min(95, scaledPercent));
          },
          controller.signal
        );

        createdStudyId = null;
        setUploadStage("completed");
        setUploadPercent(100);
        setUploadedBytes(totalBytes);
        setUploadSuccessMessage(
          validatedFiles.length === 1
            ? `Irisan DICOM CT berhasil divalidasi dan disimpan (Study ${updatedStudy.study_id
                .slice(0, 8)
                .toUpperCase()}, status: ${updatedStudy.status}).`
            : `Seri CT (${validatedFiles.length} irisan, ${formatBytes(
                totalBytes
              )}) tervalidasi dan tersimpan di penyimpanan privat (Study ${updatedStudy.study_id
                .slice(0, 8)
                .toUpperCase()}, status: ${updatedStudy.status}).`
        );

        setSelectedFiles([]);
        if (fileInputRef.current) {
          fileInputRef.current.value = "";
        }
        await refresh();
      } catch (cause) {
        if (createdStudyId) {
          await apiFetch(`/v1/studies/${createdStudyId}`, {
            method: "DELETE",
          }).catch(() => undefined);
        }
        setUploadStage("error");
        if (cause instanceof ApiUploadError) {
          setUploadErrorCode(cause.code);
          setUploadError(cause.message);
        } else if (cause instanceof Error) {
          setUploadErrorCode("ERR_VALIDATION_CLIENT");
          setUploadError(cause.message);
        } else {
          setUploadErrorCode("ERR_UPLOAD_UNKNOWN");
          setUploadError("Unggah seri DICOM gagal karena kesalahan tak terduga.");
        }
      } finally {
        abortControllerRef.current = null;
      }
    },
    [authRequired, refresh, user]
  );

  async function handleFormSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const filesFromInput = fileInputRef.current?.files
      ? Array.from(fileInputRef.current.files)
      : [];
    const targetFiles =
      selectedFiles.length > 0 ? selectedFiles : filesFromInput;
    if (selectedFiles.length === 0 && filesFromInput.length > 0) {
      setSelectedFiles(filesFromInput);
    }
    await executeUpload(targetFiles);
  }

  async function handleLoadAndUploadDemoFixtures() {
    setLoadingFixtures(true);
    setUploadError("");
    setUploadSuccessMessage("");
    try {
      const fixtureFiles = await fetchDemoDicomFixtures();
      setSelectedFiles(fixtureFiles);
      await executeUpload(fixtureFiles);
    } catch (cause) {
      setUploadStage("error");
      setUploadErrorCode("ERR_FIXTURE_LOAD");
      setUploadError(
        cause instanceof Error
          ? cause.message
          : "Gagal memuat file sampel DICOM riset."
      );
    } finally {
      setLoadingFixtures(false);
    }
  }

  const isUploading =
    uploadStage === "validating" ||
    uploadStage === "creating" ||
    uploadStage === "uploading";

  const stageDescription = useMemo(() => {
    switch (uploadStage) {
      case "validating":
        return "Memvalidasi header biner DICM Part 10 & aturan keamanan...";
      case "creating":
        return "Menginisialisasi catatan studi CT anonim di server...";
      case "uploading":
        return `Mengunggah ${selectedFiles.length} irisan DICOM ke penyimpanan privat...`;
      case "completed":
        return "Unggahan selesai dan terverifikasi.";
      case "error":
        return "Unggahan terhenti karena kesalahan.";
      default:
        return "";
    }
  }, [uploadStage, selectedFiles.length]);

  const awaitingReviewCount = studies.filter((study) => study.status === "ready").length;
  const recentStudies = studies.slice(0, 3);

  return (
    <div className="dashboard-shell workspace-shell">
      <section className="workspace-overview">
        <div className="workspace-primary">
          <div className="workspace-intro">
            <p className="eyebrow">RESEARCH WORKSPACE <span>/</span> {new Date().toLocaleDateString("en-GB", { weekday: "long", day: "2-digit", month: "short" }).toUpperCase()}</p>
            <h1>A clearer picture<br />of every study.</h1>
            <p className="lead">One focused space to manage scans, review model suggestions,<br className="desktop-break" /> and make the next decision with confidence.</p>
          </div>

          <section className="priority-review-card" aria-labelledby="priority-title">
            <div className="priority-copy">
              <p className="eyebrow">YOUR NEXT ACTION</p>
              <h2 id="priority-title">
                {awaitingReviewCount > 0
                  ? `${awaitingReviewCount} ${awaitingReviewCount === 1 ? "scan is" : "scans are"} ready\nfor human review.`
                  : "Your workspace is ready\nfor a new scan."}
              </h2>
              <p>{awaitingReviewCount > 0 ? "Review study status and model suggestions before making a decision." : "Start with a de-identified DICOM CT series when you are ready."}</p>
              <Link className="priority-action" href={awaitingReviewCount > 0 ? "#review-queue" : "#dicom-upload"}>
                {awaitingReviewCount > 0 ? "CONTINUE REVIEW" : "START A STUDY"}<span aria-hidden="true"> ↗</span>
              </Link>
            </div>
            <div className="priority-orbit" aria-hidden="true">
              <img className="orbit-outer" src="/figma/64b4e.svg" alt="" />
              <img className="orbit-inner" src="/figma/7363b.svg" alt="" />
              <img className="orbit-point" src="/figma/f88e2.svg" alt="" />
            </div>
          </section>
        </div>

        <aside className="research-pulse" aria-labelledby="pulse-title">
          <h2 id="pulse-title">Today’s pulse</h2>
          <p className="pulse-caption">A quiet snapshot of the queue.</p>
          <div className="pulse-metric">
            <strong>{loading ? "—" : studies.length.toString().padStart(2, "0")}</strong>
            <span>total studies</span>
          </div>
          <div className="pulse-metric">
            <strong>{loading ? "—" : awaitingReviewCount.toString().padStart(2, "0")}</strong>
            <span>awaiting review</span>
          </div>
          <div className="pulse-activity">
            <h3>Recent activity</h3>
            {loading ? (
              <p className="activity-empty">Checking study queue…</p>
            ) : recentStudies.length > 0 ? recentStudies.slice(0, 2).map((study, index) => (
              <Link className="activity-row" href={`/studies/${study.study_id}`} key={study.study_id}>
                <img src={index === 0 ? "/figma/6a09b.svg" : "/figma/ee222.svg"} alt="" />
                <span>
                  <strong>{study.status === "ready" ? "Study ready for review" : study.status === "processing" ? "Study analysis in progress" : study.status === "failed" ? "Study needs attention" : "New CT series uploaded"}</strong>
                  <small>{study.study_id.slice(0, 8).toUpperCase()} · {study.slices.length} slices</small>
                </span>
              </Link>
            )) : (
              <p className="activity-empty">New study activity will appear here.</p>
            )}
          </div>
        </aside>
      </section>

      <section className="workspace-recent" aria-labelledby="recent-title">
        <div className="workspace-section-heading">
          <div>
            <p className="eyebrow">RECENT STUDIES</p>
            <h2 id="recent-title">Jump back in</h2>
          </div>
          <Link className="text-link" href="#study-library">View all studies <span aria-hidden="true">↗</span></Link>
        </div>

        {loading ? (
          <LoadingSkeleton label="Loading recent CT studies…" />
        ) : queueError ? (
          <div className="workspace-inline-error" role="status">Study queue is unavailable right now. Details are shown below.</div>
        ) : recentStudies.length > 0 ? (
          <div className="recent-study-grid">
            {recentStudies.map((study, index) => (
              <Link className="recent-study-card" href={`/studies/${study.study_id}`} key={study.study_id}>
                <span className={`study-index study-index-${index + 1}`}>{String(index + 1).padStart(2, "0")}</span>
                <span className="recent-study-copy">
                  <strong>CT-{study.study_id.slice(0, 8).toUpperCase()}</strong>
                  <small>{study.modality} · {study.slices.length} slices</small>
                </span>
                <span className={`recent-study-status status-${study.status}`}>{STATUS_LABELS[study.status] ?? study.status}</span>
                <span className="study-open-arrow" aria-hidden="true">↗</span>
              </Link>
            ))}
          </div>
        ) : (
          <div className="recent-empty-state">
            <p>No studies in your workspace yet.</p>
            <Link className="button-secondary" href="#dicom-upload">Start with a DICOM series</Link>
          </div>
        )}
        <p className="workspace-footnote">Research-only workspace. Experimental output requires qualified human review.</p>
      </section>

      <section className="upload-panel workspace-upload" id="dicom-upload" aria-labelledby="upload-title">
        <div className="upload-panel-heading">
          <p className="eyebrow">PRIVATE INGESTION</p>
          <h2 id="upload-title">Begin with the images.</h2>
          <p>Choose an anonymized DICOM CT series. The upload is validated and stored in private research storage.</p>
        </div>
        <div className="upload-actions-group">
          <form className="upload-form" onSubmit={handleFormSubmit}>
            <label className="dicom-file-label" htmlFor="dicom-files">
              <span className="upload-symbol" aria-hidden="true">↑</span>
              <strong>{selectedFiles.length > 0 ? `${selectedFiles.length} file${selectedFiles.length === 1 ? "" : "s"} selected` : "Choose DICOM files"}</strong>
              <small>or browse .dcm files from your computer</small>
            </label>
            <input ref={fileInputRef} id="dicom-files" type="file" accept=".dcm,application/dicom" multiple disabled={isUploading || loadingFixtures} onChange={handleFileChange} />
            <div className="upload-controls-row">
              <button className="button-primary" type="submit" disabled={isUploading || loadingFixtures || selectedFiles.length === 0}>{isUploading ? "Uploading…" : "Validate and upload"}</button>
              <button type="button" className="button-secondary" disabled={isUploading || loadingFixtures} onClick={() => void handleLoadAndUploadDemoFixtures()} title="Load and upload five synthetic, de-identified research DICOM slices">{loadingFixtures ? "Loading sample…" : "Use research sample"}</button>
              {isUploading && <button type="button" className="button-danger" onClick={cancelActiveUpload}>Cancel</button>}
            </div>
          </form>

          {selectedFiles.length > 0 && (
            <div className="file-selection-summary" aria-live="polite">
              <div className="file-summary-header">
                <span><strong>{selectedFiles.length} files</strong> selected · {formatBytes(totalSelectedBytes)}</span>
                {!isUploading && <button type="button" className="button-secondary" onClick={clearSelectedFiles}>Clear selection</button>}
              </div>
              <div className="file-chips-list">
                {selectedFiles.slice(0, 12).map((file, idx) => <span key={`${file.name}-${idx}`} className="file-chip">{file.name} <small>({formatBytes(file.size)})</small></span>)}
                {selectedFiles.length > 12 && <span className="file-chip">+{selectedFiles.length - 12} more</span>}
              </div>
            </div>
          )}
          {isUploading && (
            <div className="upload-progress-box" role="status" aria-live="polite" aria-busy="true">
              <div className="progress-header"><span className="progress-stage-label">{stageDescription}</span><span className="progress-metrics">{uploadPercent}% · {formatBytes(uploadedBytes)} / {formatBytes(totalUploadBytes)}</span></div>
              <div className="progress-track" role="progressbar" aria-valuenow={uploadPercent} aria-valuemin={0} aria-valuemax={100} aria-label="DICOM CT upload progress"><div className="progress-fill" style={{ width: `${uploadPercent}%` }} /></div>
            </div>
          )}
          {uploadStage === "error" && uploadError && (
            <div className="upload-error-box" role="alert" aria-live="assertive">
              <div className="upload-error-header"><strong>DICOM upload failed</strong><span className="badge badge-danger mono">{uploadErrorCode}</span></div>
              <p>{uploadError}</p>
              <div className="upload-error-actions">
                {selectedFiles.length > 0 && <button type="button" className="button-primary" onClick={() => void executeUpload(selectedFiles)}>Try again ({selectedFiles.length})</button>}
                <button type="button" className="button-secondary" onClick={clearSelectedFiles}>Reset selection</button>
              </div>
            </div>
          )}
          {uploadSuccessMessage && <div className="notice notice-success" role="status">{uploadSuccessMessage}</div>}
        </div>
        <p className="upload-note">DICOM Part 10 validation checks file size, patient identifiers, embedded overlays, and series geometry before private storage.</p>
      </section>

      <section className="queue-panel workspace-library" id="study-library" aria-labelledby="queue-title">
        <div className="section-heading">
          <div><p className="eyebrow">STUDY LIBRARY</p><h2 id="queue-title">All studies</h2></div>
          <div className="queue-meta-actions">
            {lastSyncedAt && <span className="last-synced-text">Synced {lastSyncedAt} WIB</span>}
            <button type="button" className="button-secondary" disabled={loading || refreshing} onClick={() => void refresh()}>{refreshing ? "Refreshing…" : "Refresh"}</button>
          </div>
        </div>

        {!loading && !queueError && studies.length > 0 && (
          <div className="queue-toolbar">
            <div className="study-filter-tabs" role="tablist" aria-label="Filter by study status">
              {([
                { key: "all", label: "All" }, { key: "ready", label: "Ready" }, { key: "uploaded", label: "Uploaded" }, { key: "processing", label: "Processing" }, { key: "failed", label: "Failed" },
              ] as const).map((tab) => (
                <button key={tab.key} type="button" role="tab" aria-selected={statusFilter === tab.key} className={`study-filter-tab ${statusFilter === tab.key ? "active" : ""}`} onClick={() => setStatusFilter(tab.key)}>
                  {tab.label}<span className="study-filter-count">{statusCounts[tab.key]}</span>
                </button>
              ))}
            </div>
            <input type="search" className="study-search-input" placeholder="Search study ID…" aria-label="Search study ID" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} />
          </div>
        )}

        {loading ? (
          <LoadingSkeleton label="Loading CT studies and processing status from the API…" />
        ) : queueError ? (
          <ErrorState title="Study library could not load" message={queueError} errorCode={queueErrorCode} onRetry={() => void refresh()} />
        ) : studies.length === 0 ? (
          <EmptyState title="No CT studies in the library yet" description="Upload an anonymized DICOM series or load the synthetic research sample to try the upload and viewer workflow." actionLabel={loadingFixtures ? "Loading sample…" : "Use research sample"} onAction={() => void handleLoadAndUploadDemoFixtures()} />
        ) : filteredStudies.length === 0 ? (
          <div className="queue-state" role="status"><strong>No studies match these filters</strong><span>Change the status filter or search term to see more studies.</span></div>
        ) : (
          <div className="table-wrap"><table className="study-table">
            <thead><tr><th scope="col">Study ID</th><th scope="col">Modality</th><th scope="col">Slices</th><th scope="col">Status</th><th scope="col">Action</th></tr></thead>
            <tbody>{filteredStudies.map((study) => (
              <tr key={study.study_id}>
                <td><span className="study-code">{study.study_id.slice(0, 8).toUpperCase()}</span><small>{study.study_id}</small></td>
                <td>{study.modality}</td><td>{study.slices.length}</td>
                <td><span className={`status-pill status-${study.status}`} aria-label={`Study status: ${study.status}`}><span className="status-dot" aria-hidden="true" />{STATUS_LABELS[study.status] ?? study.status}</span></td>
                <td><Link className="table-link" href={`/studies/${study.study_id}`}>Open viewer <span aria-hidden="true">→</span></Link></td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </section>

      <p id="review-queue" className="research-note"><strong>Research prototype only · Not for clinical use.</strong> All model suggestions require review by a qualified radiologist.</p>
    </div>
  );
}
