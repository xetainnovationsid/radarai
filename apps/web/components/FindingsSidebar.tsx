"use client";

import { useState } from "react";
import type {
  FindingReviewStatus,
  ReportReviewStatus,
  Study,
  StudyAnalysisResponse,
  StudyLocalizations,
  StudyModelScores,
  StudySliceScore,
} from "@radar-ai/contracts";
import { ReviewStatusBadge } from "@/components/ClinicalBadge";
import { ReportEditor } from "@/components/ReportEditor";

export type SidebarTab = "findings" | "report";

export interface FindingsSidebarProps {
  study: Study;
  studyCode: string;
  analysis: StudyAnalysisResponse | null;
  modelScores: StudyModelScores | null;
  localizations: StudyLocalizations | null;
  topCandidate: StudySliceScore | null;
  activeSliceScore: StudySliceScore | null;
  activeSliceIdx: number;
  onSelectSlice: (index: number) => void;
  isSyntheticFixtureStudy: boolean;
  scoreError: string;
  localizationError: string;
  reviewError: string;
  reviewSuccess: string;
  inferring: boolean;
  onRetryInference: () => void;
  onRecordReview: (findingId: string, status: FindingReviewStatus) => Promise<void>;
  reviewerId: string;
}

export function FindingsSidebar({
  study,
  studyCode,
  analysis,
  modelScores,
  localizations,
  topCandidate,
  activeSliceScore,
  activeSliceIdx,
  onSelectSlice,
  isSyntheticFixtureStudy,
  scoreError,
  localizationError,
  reviewError,
  reviewSuccess,
  inferring,
  onRetryInference,
  onRecordReview,
  reviewerId,
}: FindingsSidebarProps) {
  const [activeTab, setActiveTab] = useState<SidebarTab>("findings");
  const [reportStatus, setReportStatus] = useState<ReportReviewStatus>("draft");
  const [submittingFindingId, setSubmittingFindingId] = useState<string | null>(
    null
  );

  const hasInferenceData = Boolean(
    (analysis && analysis.findings.length > 0) ||
      (modelScores && modelScores.slices.length > 0) ||
      (localizations && localizations.slices.length > 0)
  );

  const allFindingsReviewed = Boolean(
    analysis &&
      analysis.findings.length > 0 &&
      analysis.findings.every((f) => f.review_status !== "pending")
  );

  async function handleReviewAction(
    findingId: string,
    status: FindingReviewStatus
  ) {
    setSubmittingFindingId(findingId);
    try {
      await onRecordReview(findingId, status);
    } finally {
      setSubmittingFindingId(null);
    }
  }

  const findingsCount =
    analysis?.findings.length ?? (topCandidate ? 1 : 0);

  return (
    <aside
      className="review-panel"
      aria-label="Panel analisis temuan, editor laporan, dan keputusan reviewer"
    >
      {/* End-to-End UX Pipeline Progress Tracker: Upload -> View -> Infer -> Draft -> Approve */}
      <div
        className="workflow-stepper"
        role="region"
        aria-label="Status alur kerja tinjauan studi"
      >
        <div className="workflow-step done" title="Seri DICOM berhasil diunggah">
          <span className="step-dot">✓</span>
          <span>1. Upload</span>
        </div>
        <div className="workflow-step done" title="Irisan CT siap ditinjau di viewport">
          <span className="step-dot">✓</span>
          <span>2. View</span>
        </div>
        <div
          className={`workflow-step ${
            hasInferenceData
              ? "done"
              : scoreError && localizationError
                ? "warn"
                : "active"
          }`}
          title="Status inference model AI"
        >
          <span className="step-dot">
            {hasInferenceData ? "✓" : scoreError ? "!" : "3"}
          </span>
          <span>3. Infer</span>
        </div>
        <button
          type="button"
          className={`workflow-step workflow-step-btn ${
            activeTab === "report" || reportStatus !== "draft" ? "done" : "active"
          }`}
          onClick={() => setActiveTab("report")}
          title="Buka draf laporan riset"
        >
          <span className="step-dot">
            {reportStatus !== "draft" ? "✓" : "4"}
          </span>
          <span>4. Draft</span>
        </button>
        <button
          type="button"
          className={`workflow-step workflow-step-btn ${
            reportStatus === "approved" || allFindingsReviewed ? "done" : ""
          }`}
          onClick={() => setActiveTab("report")}
          title="Edit dan setujui laporan riset"
        >
          <span className="step-dot">
            {reportStatus === "approved" ? "✓" : "5"}
          </span>
          <span>5. Approve</span>
        </button>
      </div>

      {/* Sidebar Mode Tabs */}
      <div
        className="sidebar-tabs"
        role="tablist"
        aria-label="Navigasi panel samping"
      >
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "findings"}
          className={`sidebar-tab${activeTab === "findings" ? " active" : ""}`}
          onClick={() => setActiveTab("findings")}
        >
          <span>Temuan & Model AI</span>
          <span className="sidebar-tab-badge mono">{findingsCount}</span>
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === "report"}
          className={`sidebar-tab${activeTab === "report" ? " active" : ""}`}
          onClick={() => setActiveTab("report")}
        >
          <span>Editor Laporan</span>
          <span
            className={`sidebar-tab-badge mono ${
              reportStatus === "approved" ? "badge-approved" : ""
            }`}
          >
            {reportStatus.toUpperCase()}
          </span>
        </button>
      </div>

      {activeTab === "findings" ? (
        <div className="sidebar-tab-content">
          <div className="sidebar-section-header">
            <div>
              <p className="eyebrow">ANALYSIS & SLICE-LINKED FINDINGS</p>
              <h2>Prediksi Model & Referensi Irisan</h2>
            </div>
            <button
              type="button"
              className="button-secondary button-sm"
              disabled={inferring}
              onClick={onRetryInference}
              title="Jalankan ulang atau segarkan hasil analisis model dari server API"
            >
              {inferring ? "Memproses…" : "↻ Segarkan Inference"}
            </button>
          </div>

          <p className="non-diagnostic-callout">
            <strong>PERINGATAN NON-DIAGNOSTIK:</strong> Output di bawah ini adalah
            skor matematis eksperimental yang belum terkalibrasi. Jangan gunakan
            untuk diagnosis klinis atau keputusan medis.
          </p>

          {/* 1. Persisted Findings & Cited Evidence Slices */}
          <div className="findings-section-title-row">
            <h3>1. Kandidat model & keputusan reviewer</h3>
            <button
              type="button"
              className="evidence-link"
              onClick={() => setActiveTab("report")}
            >
              Buka Draf Laporan →
            </button>
          </div>

          {reviewError && (
            <div className="notice notice-error" role="alert">
              <div className="report-notice-header">
                <strong>Gagal menyimpan keputusan reviewer</strong>
                <span className="badge badge-danger mono">ERR_REVIEW_API</span>
              </div>
              <p style={{ margin: "4px 0 0" }}>{reviewError}</p>
            </div>
          )}

          {reviewSuccess && !reviewError && (
            <div className="notice notice-success" role="status">
              {reviewSuccess}
            </div>
          )}

          {analysis?.findings.length ? (
            analysis.findings.map((finding) => {
              const isBusy = submittingFindingId === finding.finding_id;
              return (
                <article className="finding-card" key={finding.finding_id}>
                  <div className="finding-card-header">
                    <h3>Dugaan perdarahan intrakranial (ICH)</h3>
                    <ReviewStatusBadge status={finding.review_status} />
                  </div>
                  <p>
                    Skor prediksi model:{" "}
                    <strong>{(finding.confidence * 100).toFixed(0)}%</strong> · belum
                    terkalibrasi (bukan diagnosis)
                  </p>
                  <p className="muted-copy mono">
                    Kategori: {finding.category} · Model Ver:{" "}
                    {finding.model_version_id.slice(0, 8)}
                  </p>
                  <div className="finding-evidence">
                    <span>Irisan bukti terkait:</span>
                    {finding.evidence_slice_ids.map((sliceId) => {
                      const evidenceIndex = study.slices.findIndex(
                        (item) => item.slice_id === sliceId
                      );
                      const evidenceSlice =
                        evidenceIndex >= 0 ? study.slices[evidenceIndex] : null;
                      const isCurrent = evidenceIndex === activeSliceIdx;
                      return (
                        <button
                          key={sliceId}
                          type="button"
                          className={`evidence-link${isCurrent ? " active" : ""}`}
                          onClick={() =>
                            evidenceIndex >= 0 && onSelectSlice(evidenceIndex)
                          }
                        >
                          ★ Irisan #{evidenceIndex + 1}
                          {evidenceSlice?.z_position_mm != null
                            ? ` (${evidenceSlice.z_position_mm} mm)`
                            : ""}
                        </button>
                      );
                    })}
                  </div>

                  {/* Quick One-Click Reviewer Decision Buttons + Select */}
                  <div className="reviewer-decision-block">
                    <label htmlFor={`review-${finding.finding_id}`}>
                      Keputusan reviewer (audit manusia)
                    </label>
                    <div
                      className="quick-review-btn-group"
                      role="group"
                      aria-label="Tombol cepat keputusan reviewer"
                    >
                      <button
                        type="button"
                        disabled={isBusy}
                        className={`quick-review-btn accept${
                          finding.review_status === "accepted" ? " selected" : ""
                        }`}
                        onClick={() =>
                          void handleReviewAction(finding.finding_id, "accepted")
                        }
                      >
                        ✓ Terima
                      </button>
                      <button
                        type="button"
                        disabled={isBusy}
                        className={`quick-review-btn uncertain${
                          finding.review_status === "uncertain" ? " selected" : ""
                        }`}
                        onClick={() =>
                          void handleReviewAction(finding.finding_id, "uncertain")
                        }
                      >
                        ? Tidak Pasti
                      </button>
                      <button
                        type="button"
                        disabled={isBusy}
                        className={`quick-review-btn reject${
                          finding.review_status === "rejected" ? " selected" : ""
                        }`}
                        onClick={() =>
                          void handleReviewAction(finding.finding_id, "rejected")
                        }
                      >
                        ✕ Tolak
                      </button>
                    </div>

                    <select
                      id={`review-${finding.finding_id}`}
                      value={finding.review_status}
                      disabled={isBusy}
                      onChange={(event) =>
                        void handleReviewAction(
                          finding.finding_id,
                          event.target.value as FindingReviewStatus
                        )
                      }
                    >
                      <option value="pending" disabled>
                        Menunggu review
                      </option>
                      <option value="accepted">Terima (Accepted)</option>
                      <option value="rejected">Tolak (Rejected)</option>
                      <option value="uncertain">Tidak pasti (Uncertain)</option>
                    </select>
                  </div>
                </article>
              );
            })
          ) : topCandidate ? (
            <article className="finding-card">
              <h3>Kandidat skor tertinggi · belum ditinjau</h3>
              <p>
                Skor model untuk label positif ICH:{" "}
                <strong>{(topCandidate.class_1_score * 100).toFixed(1)}%</strong> ·
                irisan #{topCandidate.index + 1}
              </p>
              <button
                className="evidence-link"
                type="button"
                onClick={() => onSelectSlice(topCandidate.index)}
              >
                ◆ Buka irisan kandidat (#{topCandidate.index + 1})
              </button>
              <p className="muted-copy">
                Diturunkan langsung dari skor inference model untuk target anotasi
                RSNA ICH. Belum disimpan sebagai temuan dan belum ditinjau reviewer.
                Skor ini bukan diagnosis atau akurasi model.
              </p>
            </article>
          ) : (
            <div className="notice notice-warning" role="status">
              {isSyntheticFixtureStudy && analysis?.findings.length === 0
                ? "Tidak ada kandidat perdarahan yang ditandai pada irisan studi ini."
                : scoreError
                  ? "Kandidat model belum tersedia karena inference lokal belum aktif."
                  : "Memuat skor inference untuk menampilkan kandidat model…"}
            </div>
          )}

          {/* 2. Per-Slice DenseNet121 Model Scores */}
          <h3>2. Skor model per irisan (riset)</h3>
          {modelScores ? (
            topCandidate ? (
              <article className="finding-card">
                <h3>Skor label positif ICH tertinggi</h3>
                <p>
                  Skor model untuk label dataset positif:{" "}
                  <strong>{(topCandidate.class_1_score * 100).toFixed(1)}%</strong>{" "}
                  · irisan #{topCandidate.index + 1}
                </p>
                <p className="muted-copy">
                  Label dataset negatif:{" "}
                  {(topCandidate.class_0_score * 100).toFixed(1)}% · positif:{" "}
                  {(topCandidate.class_1_score * 100).toFixed(1)}%
                </p>
                {activeSliceScore && (
                  <p className="muted-copy">
                    Irisan aktif (#{activeSliceIdx + 1}): positif{" "}
                    <strong>
                      {(activeSliceScore.class_1_score * 100).toFixed(1)}%
                    </strong>{" "}
                    · negatif {(activeSliceScore.class_0_score * 100).toFixed(1)}%
                  </p>
                )}
                <button
                  className="evidence-link"
                  type="button"
                  onClick={() => onSelectSlice(topCandidate.index)}
                >
                  Lihat irisan skor tertinggi (#{topCandidate.index + 1})
                </button>
                <p className="muted-copy">
                  Label 1 berarti irisan dianotasi mengandung perdarahan pada
                  dataset RSNA ICH; label 0 berarti tidak ada anotasi positif. Ini
                  skor model per irisan, bukan akurasi atau diagnosis; skor belum
                  terkalibrasi.
                </p>
                <p className="muted-copy mono">
                  {modelScores.model_id} · {modelScores.device} · checkpoint{" "}
                  {modelScores.checkpoint_sha256.slice(0, 12)}
                </p>
              </article>
            ) : (
              <p className="muted-copy">Tidak ada skor irisan tersedia.</p>
            )
          ) : (
            <div className="notice notice-warning" role="status">
              <div className="report-notice-header">
                <strong>
                  {scoreError
                    ? "Skor per-irisan DenseNet121 belum tersedia."
                    : "Menjalankan inference lokal…"}
                </strong>
                {scoreError && (
                  <span className="badge badge-warning mono">
                    {isSyntheticFixtureStudy ? "DEMO_FIXTURE" : "ERR_SCORES_503"}
                  </span>
                )}
              </div>
              {scoreError && (
                <>
                  <p style={{ margin: "6px 0 8px" }}>{scoreError}</p>
                  {!isSyntheticFixtureStudy && (
                    <button
                      type="button"
                      className="button-secondary button-sm"
                      disabled={inferring}
                      onClick={onRetryInference}
                    >
                      Coba Lagi Skor Model
                    </button>
                  )}
                </>
              )}
            </div>
          )}

          {/* 3. SAMIHS Segmentation Localization */}
          <h3>3. Lokalisasi area oleh SAMIHS</h3>
          {localizations ? (
            (() => {
              const candidates = localizations.slices.filter(
                (item) => item.box !== null
              );
              const largest = candidates.reduce<
                (typeof candidates)[number] | null
              >(
                (best, current) =>
                  !best || current.mask_pixels > best.mask_pixels
                    ? current
                    : best,
                null
              );
              return (
                <article className="finding-card">
                  {largest ? (
                    <>
                      <p>
                        Mask menemukan area kandidat pada {candidates.length}{" "}
                        irisan. Kotak mengikuti batas area mask irisan, bukan
                        diagnosis.
                      </p>
                      <button
                        className="evidence-link"
                        type="button"
                        onClick={() => onSelectSlice(largest.index)}
                      >
                        Lihat area mask terbesar · irisan #{largest.index + 1}
                      </button>
                    </>
                  ) : study.slices.length < 16 ? (
                    <p>
                      Studi ini hanya berisi {study.slices.length} irisan. Paket
                      model ditujukan untuk volume CT otak sekitar 16–180 irisan;
                      unggah seluruh seri, bukan satu irisan lepas.
                    </p>
                  ) : (
                    <p>
                      Model tidak menghasilkan area mask pada seri ini pada
                      threshold yang dipilih.
                    </p>
                  )}
                  <p className="muted-copy mono">
                    {localizations.model_id} · {localizations.device} · threshold{" "}
                    {localizations.threshold} · checkpoint{" "}
                    {localizations.checkpoint_sha256.slice(0, 12)}
                  </p>
                </article>
              );
            })()
          ) : (
            <div className="notice notice-warning" role="status">
              <div className="report-notice-header">
                <strong>
                  {localizationError
                    ? "Lokalisasi mask SAMIHS belum tersedia."
                    : "Menjalankan model lokalisasi lokal…"}
                </strong>
                {localizationError && (
                  <span className="badge badge-warning mono">
                    {isSyntheticFixtureStudy ? "DEMO_FIXTURE" : "ERR_SAMIHS_503"}
                  </span>
                )}
              </div>
              {localizationError && (
                <>
                  <p style={{ margin: "6px 0 8px" }}>{localizationError}</p>
                  {!isSyntheticFixtureStudy && (
                    <button
                      type="button"
                      className="button-secondary button-sm"
                      disabled={inferring}
                      onClick={onRetryInference}
                    >
                      Coba Lagi Lokalisasi
                    </button>
                  )}
                </>
              )}
            </div>
          )}

          {/* 4. Model Version & Provenance Metadata */}
          <h3>4. Versi Model & Provenance</h3>
          <dl className="study-metadata">
            <div>
              <dt>Status pipeline</dt>
              <dd>{study.status}</dd>
            </div>
            <div>
              <dt>Provider model</dt>
              <dd className="mono">
                {analysis?.model_version.provider ?? "local_checkpoint"}
              </dd>
            </div>
            <div>
              <dt>Model ID</dt>
              <dd className="mono">
                {analysis?.model_version.model_id ??
                  modelScores?.model_id ??
                  "densenet121-rsna-ich"}
              </dd>
            </div>
            <div>
              <dt>Versi prompt / skema</dt>
              <dd className="mono">
                {analysis?.model_version.prompt_version ??
                  analysis?.schema_version ??
                  "v1.0.0"}
              </dd>
            </div>
            {analysis?.model_version.model_version_id && (
              <div>
                <dt>Model Version Ref</dt>
                <dd className="mono">
                  {analysis.model_version.model_version_id.slice(0, 12)}
                </dd>
              </div>
            )}
            {modelScores?.checkpoint_sha256 && (
              <div>
                <dt>Checkpoint SHA-256</dt>
                <dd className="mono">
                  {modelScores.checkpoint_sha256.slice(0, 12)}
                </dd>
              </div>
            )}
            <div>
              <dt>Reviewer aktif</dt>
              <dd>{reviewerId}</dd>
            </div>
            <div>
              <dt>Klasifikasi penggunaan</dt>
              <dd className="safety-tag">NOT FOR CLINICAL USE</dd>
            </div>
          </dl>

          <div className="sidebar-cta-box">
            <button
              type="button"
              className="button-primary"
              style={{ width: "100%" }}
              onClick={() => setActiveTab("report")}
            >
              Lanjut ke Draf & Editor Laporan Riset →
            </button>
          </div>
        </div>
      ) : (
        <div className="sidebar-tab-content">
          <ReportEditor
            key={study.study_id}
            study={study}
            studyCode={studyCode}
            analysis={analysis}
            modelScores={modelScores}
            localizations={localizations}
            activeSliceIdx={activeSliceIdx}
            onSelectSlice={onSelectSlice}
            reviewerId={reviewerId}
            onStatusChange={setReportStatus}
          />
        </div>
      )}
    </aside>
  );
}

