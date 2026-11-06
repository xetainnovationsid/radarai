"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  Study,
  StudyAnalysisResponse,
  StudyModelScores,
  StudyLocalizations,
  FindingReviewStatus,
  InferenceJob,
} from "@radar-ai/contracts";
import { useAuth } from "@/components/AuthContext";
import { StudyStatusBadge } from "@/components/ClinicalBadge";
import {
  CRANIAL_WINDOW_PRESETS,
  type WindowPreset,
} from "@/components/CornerstoneViewport";
import { DisclaimerBanner } from "@/components/DisclaimerBanner";
import { FindingsSidebar } from "@/components/FindingsSidebar";
import {
  API_BASE,
  apiFetch,
  assertValidUuid,
  fetchAuthenticatedImageBlobUrl,
  isValidUuid,
} from "@/lib/api-client";
import { getDemoStudyById, type DemoStudyEntry } from "@/lib/demo-data";

const CornerstoneViewport = dynamic(
  () => import("@/components/CornerstoneViewport"),
  {
    ssr: false,
    loading: () => (
      <div className="ct-canvas-placeholder" role="status">
        <p className="muted-copy">Memuat mesin Cornerstone3D DICOM Part 10…</p>
      </div>
    ),
  }
);

type ViewerRenderMode = "dicom" | "preview";

async function fetchModelScores(studyId: string): Promise<StudyModelScores> {
  const safeId = assertValidUuid(studyId, "Study ID");
  const response = await apiFetch(`/v1/studies/${safeId}/inference-jobs`, {
    method: "POST",
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail ?? `Inferensi tidak tersedia (HTTP ${response.status}).`);
  }
  let job = (await response.json()) as InferenceJob;
  for (let attempt = 0; attempt < 180; attempt += 1) {
    if (job.status === "completed") break;
    if (job.status === "failed") {
      throw new Error(`Inferensi gagal (${job.error_code ?? "unknown_error"}).`);
    }
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
    const poll = await apiFetch(
      `/v1/studies/${safeId}/inference-jobs/${assertValidUuid(job.job_id, "Job ID")}`
    );
    if (!poll.ok) {
      const body = (await poll.json().catch(() => ({}))) as { detail?: string };
      throw new Error(body.detail ?? `Status inferensi tidak tersedia (HTTP ${poll.status}).`);
    }
    job = (await poll.json()) as InferenceJob;
  }
  if (job.status !== "completed") {
    throw new Error("Inferensi masih berjalan. Muat ulang studi untuk memeriksa statusnya.");
  }
  const responseScores = await apiFetch(`/v1/studies/${safeId}/scores`);
  if (!responseScores.ok) {
    const body = (await responseScores.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail ?? `Skor model tidak tersedia (HTTP ${responseScores.status}).`);
  }
  return (await responseScores.json()) as StudyModelScores;
}

async function fetchStudyLocalizations(studyId: string): Promise<StudyLocalizations> {
  const safeId = assertValidUuid(studyId, "Study ID");
  const response = await apiFetch(`/v1/studies/${safeId}/localizations`);
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string };
    throw new Error(body.detail ?? `Lokalisasi lesi tidak tersedia (HTTP ${response.status}).`);
  }
  return (await response.json()) as StudyLocalizations;
}

async function fetchStudyAnalysis(studyId: string): Promise<StudyAnalysisResponse | null> {
  const safeId = assertValidUuid(studyId, "Study ID");
  const response = await apiFetch(`/v1/studies/${safeId}/analysis`);
  return response.ok ? ((await response.json()) as StudyAnalysisResponse) : null;
}

export function StudyViewerClient({ studyId }: { studyId: string }) {
  const { user, authRequired } = useAuth();
  const [study, setStudy] = useState<Study | null>(null);
  const [demoEntry, setDemoEntry] = useState<DemoStudyEntry | null>(null);
  const [analysis, setAnalysis] = useState<StudyAnalysisResponse | null>(null);
  const [modelScores, setModelScores] = useState<StudyModelScores | null>(null);
  const [localizations, setLocalizations] = useState<StudyLocalizations | null>(null);
  const [localizationError, setLocalizationError] = useState("");
  const [scoreError, setScoreError] = useState("");
  const [index, setIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [inferring, setInferring] = useState(false);
  const [error, setError] = useState("");
  const [reviewError, setReviewError] = useState("");
  const [reviewSuccess, setReviewSuccess] = useState("");
  const [blobImage, setBlobImage] = useState<{ sliceId: string; url: string } | null>(null);

  // Track manual slice navigation to prevent async score resolution from overriding user intent (BUG-12)
  const userInteractedRef = useRef(false);

  // Viewer interactive controls
  const [viewerMode, setViewerMode] = useState<ViewerRenderMode>("dicom");
  const [windowPreset, setWindowPreset] = useState<WindowPreset>(
    CRANIAL_WINDOW_PRESETS[0]
  );
  const [showOverlay, setShowOverlay] = useState(true);

  const selectSlice = useCallback((nextIndex: number) => {
    userInteractedRef.current = true;
    setIndex(nextIndex);
  }, []);

  const slice = study?.slices[index];

  // Safe reduction for top positive slice score (BUG-01 remediation)
  const topCandidate = useMemo(() => {
    if (!modelScores?.slices || modelScores.slices.length === 0) return null;
    return modelScores.slices.reduce((best, current) =>
      current.class_1_score > best.class_1_score ? current : best
    );
  }, [modelScores]);

  const activeSliceScore = useMemo(
    () => modelScores?.slices.find((item) => item.index === index) ?? null,
    [modelScores, index]
  );

  const activeLocalization = useMemo(
    () => localizations?.slices.find((item) => item.index === index) ?? null,
    [localizations, index]
  );

  // Compute set of cited evidence slice IDs across all findings
  const citedSliceIds = useMemo(() => {
    const ids = new Set<string>();
    if (!analysis?.findings) return ids;
    for (const finding of analysis.findings) {
      for (const sliceId of finding.evidence_slice_ids) {
        ids.add(sliceId);
      }
    }
    return ids;
  }, [analysis]);

  const isActiveSliceEvidence = Boolean(
    slice && (citedSliceIds.has(slice.slice_id) || topCandidate?.index === index)
  );

  const isSyntheticFixtureStudy = Boolean(
    demoEntry || analysis?.model_version.provider === "demo_fixture"
  );

  // Map study slices to exact uploaded DICOM endpoints or local demo fixtures for Cornerstone3D
  const dicomImageIds = useMemo(() => {
    if (!study || study.slices.length === 0) return [];
    if (demoEntry) {
      return study.slices.map((_, sliceIdx) => {
        const clampedFixtureIndex = Math.min(4, Math.max(0, sliceIdx));
        return `wadouri:/fixtures/dicom/brain-ct/slice-${clampedFixtureIndex}.dcm`;
      });
    }
    return study.slices.map(
      (item) => `wadouri:/v1/studies/${study.study_id}/slices/${item.slice_id}/dicom`
    );
  }, [demoEntry, study]);

  const fallbackImageUrl = useMemo(() => {
    if (!slice || !isValidUuid(studyId) || !isValidUuid(slice.slice_id)) return "";
    if (demoEntry) return "";
    return `${API_BASE}/v1/studies/${studyId}/slices/${slice.slice_id}/image`;
  }, [slice, studyId, demoEntry]);

  // Memory-safe Object URL management on rapid slice scrubbing (BUG-03 remediation)
  useEffect(() => {
    if (!slice || demoEntry) {
      return;
    }
    const targetSliceId = slice.slice_id;
    const controller = new AbortController();
    let isCancelled = false;
    let activeUrl: string | null = null;

    fetchAuthenticatedImageBlobUrl(studyId, targetSliceId, controller.signal)
      .then((objectUrl) => {
        if (isCancelled) {
          URL.revokeObjectURL(objectUrl);
          return;
        }
        activeUrl = objectUrl;
        setBlobImage({ sliceId: targetSliceId, url: objectUrl });
      })
      .catch(() => {
        if (!controller.signal.aborted && !isCancelled) {
          setBlobImage(null);
        }
      });

    return () => {
      isCancelled = true;
      controller.abort();
      if (activeUrl) {
        URL.revokeObjectURL(activeUrl);
      }
    };
  }, [slice, studyId, user, demoEntry]);

  // Keyboard navigation (Left / Right arrows) for slice traversal
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (!study || study.slices.length === 0) return;
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "SELECT" ||
          target.tagName === "TEXTAREA")
      ) {
        return;
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        userInteractedRef.current = true;
        setIndex((current) => Math.max(0, current - 1));
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        userInteractedRef.current = true;
        setIndex((current) => Math.min(study.slices.length - 1, current + 1));
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [study]);

  const activeImageUrl =
    slice && blobImage?.sliceId === slice.slice_id
      ? blobImage.url
      : fallbackImageUrl;

  const resolveInitialSliceIndex = useCallback(
    (targetStudy: Study, targetAnalysis: StudyAnalysisResponse | null): number => {
      if (targetStudy.slices.length === 0) return 0;
      const firstCitedId = targetAnalysis?.findings[0]?.evidence_slice_ids[0];
      if (firstCitedId) {
        const citedIndex = targetStudy.slices.findIndex(
          (item) => item.slice_id === firstCitedId
        );
        if (citedIndex >= 0) return citedIndex;
      }
      return 0;
    },
    []
  );

  const applyDemoFallback = useCallback(
    (matchedDemo: DemoStudyEntry) => {
      const demoStudy = matchedDemo.analysis.study;
      userInteractedRef.current = false;
      setDemoEntry(matchedDemo);
      setStudy(demoStudy);
      setAnalysis(matchedDemo.analysis);
      setViewerMode("dicom");
      setIndex(resolveInitialSliceIndex(demoStudy, matchedDemo.analysis));
      setModelScores(null);
      setLocalizations(null);
      setScoreError(
        "Studi ini adalah fixture sintetik lokal (demo_fixture). Skor model real-time memerlukan studi terunggah dengan RADAR_CT_CHECKPOINT."
      );
      setLocalizationError(
        "Lokalisasi SAMIHS real-time memerlukan volume seri CT yang diunggah ke penyimpanan API lokal."
      );
      setError("");
    },
    [resolveInitialSliceIndex]
  );

  const runInferenceRefresh = useCallback(async () => {
    if (demoEntry) {
      setAnalysis(demoEntry.analysis);
      return;
    }
    setInferring(true);
    setScoreError("");
    setLocalizationError("");

    try {
      const safeStudyId = assertValidUuid(studyId, "Study ID");
      const analysisResponse = await apiFetch(`/v1/studies/${safeStudyId}/analysis`);
      if (analysisResponse.ok) {
        const resolvedAnalysis = (await analysisResponse.json()) as StudyAnalysisResponse;
        setAnalysis(resolvedAnalysis);
      }

      await Promise.allSettled([
        fetchModelScores(safeStudyId)
          .then((scores) => {
            setModelScores(scores);
            void fetchStudyAnalysis(safeStudyId).then(setAnalysis);
            if (!userInteractedRef.current && scores.slices.length > 0) {
              const best = scores.slices.reduce((a, b) =>
                b.class_1_score > a.class_1_score ? b : a
              );
              setIndex((current) => (current === 0 ? best.index : current));
            }
          })
          .catch((cause: unknown) =>
            setScoreError(
              cause instanceof Error ? cause.message : "Skor model tidak tersedia."
            )
          ),
        fetchStudyLocalizations(safeStudyId)
          .then(setLocalizations)
          .catch((cause: unknown) =>
            setLocalizationError(
              cause instanceof Error ? cause.message : "Lokalisasi lesi tidak tersedia."
            )
          ),
      ]);
    } catch (cause) {
      setScoreError(
        cause instanceof Error ? cause.message : "Gagal memperbarui inference."
      );
    } finally {
      setInferring(false);
    }
  }, [demoEntry, studyId]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    userInteractedRef.current = false;
    const matchedDemo = getDemoStudyById(studyId);
    try {
      const safeStudyId = assertValidUuid(studyId, "Study ID");
      const response = await apiFetch(`/v1/studies/${safeStudyId}`);
      if (response.status === 404 && matchedDemo) {
        applyDemoFallback(matchedDemo);
        return;
      }
      if (response.status === 401) {
        throw new Error(
          "Autentikasi diperlukan untuk membuka studi ini. Silakan login terlebih dahulu."
        );
      }
      if (response.status === 404) throw new Error("Studi tidak ditemukan.");
      if (!response.ok) throw new Error(`API returned ${response.status}`);

      const value = (await response.json()) as Study;
      setDemoEntry(null);
      setStudy(value);
      setViewerMode("dicom");

      const analysisResponse = await apiFetch(`/v1/studies/${safeStudyId}/analysis`);
      const resolvedAnalysis = analysisResponse.ok
        ? ((await analysisResponse.json()) as StudyAnalysisResponse)
        : null;
      setAnalysis(resolvedAnalysis);
      setIndex(resolveInitialSliceIndex(value, resolvedAnalysis));

      setModelScores(null);
      setLocalizations(null);
      setScoreError("");
      setLocalizationError("");

      void fetchModelScores(safeStudyId)
        .then((scores) => {
          setModelScores(scores);
          void fetchStudyAnalysis(safeStudyId).then(setAnalysis);
          if (
            !userInteractedRef.current &&
            !resolvedAnalysis?.findings.length &&
            scores.slices.length > 0
          ) {
            const best = scores.slices.reduce((a, b) =>
              b.class_1_score > a.class_1_score ? b : a
            );
            setIndex((current) => (current === 0 ? best.index : current));
          }
        })
        .catch((cause: unknown) =>
          setScoreError(
            cause instanceof Error ? cause.message : "Skor model tidak tersedia."
          )
        );
      void fetchStudyLocalizations(safeStudyId)
        .then(setLocalizations)
        .catch((cause: unknown) =>
          setLocalizationError(
            cause instanceof Error ? cause.message : "Lokalisasi lesi tidak tersedia."
          )
        );
    } catch (cause) {
      if (matchedDemo) {
        applyDemoFallback(matchedDemo);
      } else {
        setError(cause instanceof Error ? cause.message : "Tidak dapat memuat studi.");
      }
    } finally {
      setLoading(false);
    }
  }, [studyId, applyDemoFallback, resolveInitialSliceIndex]);

  useEffect(() => {
    let ignore = false;
    userInteractedRef.current = false;
    async function fetchStudy() {
      const matchedDemo = getDemoStudyById(studyId);
      try {
        const safeStudyId = assertValidUuid(studyId, "Study ID");
        const response = await apiFetch(`/v1/studies/${safeStudyId}`);
        if (response.status === 404 && matchedDemo) {
          if (!ignore) {
            applyDemoFallback(matchedDemo);
          }
          return;
        }
        if (response.status === 401) {
          throw new Error(
            "Autentikasi diperlukan untuk membuka studi ini. Silakan login terlebih dahulu."
          );
        }
        if (response.status === 404) throw new Error("Studi tidak ditemukan.");
        if (!response.ok) throw new Error(`API returned ${response.status}`);

        const value = (await response.json()) as Study;
        const analysisResponse = await apiFetch(`/v1/studies/${safeStudyId}/analysis`);
        const resolvedAnalysis = analysisResponse.ok
          ? ((await analysisResponse.json()) as StudyAnalysisResponse)
          : null;

        if (!ignore) {
          setDemoEntry(null);
          setStudy(value);
          setAnalysis(resolvedAnalysis);
          setViewerMode("dicom");
          setIndex(resolveInitialSliceIndex(value, resolvedAnalysis));
          setError("");
          setModelScores(null);
          setLocalizations(null);
          setScoreError("");
          setLocalizationError("");
        }

        void fetchModelScores(safeStudyId)
          .then((scores) => {
            if (!ignore) {
              setModelScores(scores);
              void fetchStudyAnalysis(safeStudyId).then((value) => {
                if (!ignore) setAnalysis(value);
              });
              if (
                !userInteractedRef.current &&
                !resolvedAnalysis?.findings.length &&
                scores.slices.length > 0
              ) {
                const best = scores.slices.reduce((a, b) =>
                  b.class_1_score > a.class_1_score ? b : a
                );
                setIndex((current) => (current === 0 ? best.index : current));
              }
            }
          })
          .catch((cause: unknown) => {
            if (!ignore) {
              setScoreError(
                cause instanceof Error ? cause.message : "Skor model tidak tersedia."
              );
            }
          });
        void fetchStudyLocalizations(safeStudyId)
          .then((result) => {
            if (!ignore) setLocalizations(result);
          })
          .catch((cause: unknown) => {
            if (!ignore) {
              setLocalizationError(
                cause instanceof Error ? cause.message : "Lokalisasi lesi tidak tersedia."
              );
            }
          });
      } catch (cause) {
        if (!ignore) {
          if (matchedDemo) {
            applyDemoFallback(matchedDemo);
          } else {
            setError(
              cause instanceof Error ? cause.message : "Tidak dapat memuat studi."
            );
          }
        }
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    }
    void fetchStudy();
    return () => {
      ignore = true;
    };
  }, [studyId, user, applyDemoFallback, resolveInitialSliceIndex]);

  async function recordReview(findingId: string, review_status: FindingReviewStatus) {
    setReviewError("");
    setReviewSuccess("");
    if (demoEntry && analysis) {
      setAnalysis({
        ...analysis,
        findings: analysis.findings.map((finding) =>
          finding.finding_id === findingId
            ? { ...finding, review_status }
            : finding
        ),
      });
      setReviewSuccess(
        `Keputusan reviewer (${review_status.toUpperCase()}) tercatat pada sesi fixture lokal.`
      );
      return;
    }
    if (authRequired && !user) {
      setReviewError(
        "Silakan login dengan akun peneliti (Firebase OAuth) untuk mencatat keputusan review."
      );
      return;
    }
    try {
      const safeStudyId = assertValidUuid(studyId, "Study ID");
      const safeFindingId = assertValidUuid(findingId, "Finding ID");
      const response = await apiFetch(
        `/v1/studies/${safeStudyId}/findings/${safeFindingId}/review`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ review_status }),
        }
      );
      if (response.status === 401) {
        throw new Error(
          "Autentikasi diperlukan untuk menyimpan keputusan reviewer (HTTP 401)."
        );
      }
      if (response.status === 429) {
        throw new Error(
          "Batas laju permintaan (rate limit) tercapai saat menyimpan keputusan reviewer (HTTP 429)."
        );
      }
      if (!response.ok) {
        throw new Error(
          `Keputusan reviewer gagal disimpan (HTTP ${response.status}).`
        );
      }
      if (!analysis) return;
      setAnalysis({
        ...analysis,
        findings: analysis.findings.map((finding) =>
          finding.finding_id === findingId
            ? { ...finding, review_status }
            : finding
        ),
      });
      setReviewSuccess(
        `Keputusan reviewer (${review_status.toUpperCase()}) berhasil disimpan ke log audit server.`
      );
    } catch (cause) {
      setReviewError(
        cause instanceof Error
          ? cause.message
          : "Keputusan reviewer gagal disimpan."
      );
    }
  }

  const studyCode =
    demoEntry?.code ?? `CT-${study?.study_id.slice(0, 8).toUpperCase() ?? "STUDY"}`;
  const reviewerId = user?.email ?? "local-reviewer";

  return (
    <div className="viewer-shell">
      <DisclaimerBanner />

      <nav className="breadcrumbs viewer-breadcrumbs" aria-label="Breadcrumb">
        <Link href="/">← Kembali ke daftar studi</Link>
        <div className="breadcrumb-quick-links">
          <span className="muted-copy">Fixture Referensi:</span>
          <Link
            href="/studies/00000000-0000-4000-8000-000000000001"
            className="evidence-link"
          >
            CT-2026-0101 (5 Irisan DICOM)
          </Link>
        </div>
      </nav>

      {loading && <p role="status">Memuat studi dan referensi irisan…</p>}

      {error && (
        <div className="notice notice-error" role="alert">
          {error}{" "}
          <button
            className="button-secondary"
            type="button"
            onClick={() => void load()}
          >
            Coba lagi
          </button>
        </div>
      )}

      {study && (
        <>
          <header className="viewer-heading">
            <div>
              <p className="eyebrow">
                ANONYMIZED CT STUDY{" "}
                <span>· PROTOTYPING ONLY · NOT FOR CLINICAL USE</span>
              </p>
              <h1>Study {studyCode}</h1>
              <p>
                {study.modality} · {study.slices.length} irisan
                {demoEntry ? ` · ${demoEntry.seriesDescription}` : ""}
              </p>
            </div>
            <div className="viewer-header-badges">
              {isSyntheticFixtureStudy && (
                <span className="badge badge-warning mono">
                  DEMO FIXTURE · SYNTHETIC PHANTOM
                </span>
              )}
              <StudyStatusBadge status={study.status} />
              <span className={`status-pill status-${study.status}`}>
                {study.status}
              </span>
            </div>
          </header>

          <div className="viewer-grid">
            <section className="image-panel" aria-label="CT slice viewer">
              {/* Top Viewer Controls: Mode Switcher, Window Presets & Overlay Toggle */}
              <div className="viewer-controls-bar">
                <div
                  className="viewer-mode-tabs"
                  role="tablist"
                  aria-label="Pilih mode perenderan CT"
                >
                  <button
                    type="button"
                    role="tab"
                    aria-selected={viewerMode === "dicom"}
                    disabled={!slice}
                    title="Render irisan DICOM Part 10 asli dengan probe Hounsfield Unit & preset windowing"
                    className={`viewer-mode-tab${viewerMode === "dicom" ? " active" : ""}`}
                    onClick={() => setViewerMode("dicom")}
                  >
                    Cornerstone3D DICOM (HU Probe)
                  </button>
                  <button
                    type="button"
                    role="tab"
                    aria-selected={viewerMode === "preview"}
                    className={`viewer-mode-tab${viewerMode === "preview" ? " active" : ""}`}
                    onClick={() => setViewerMode("preview")}
                  >
                    Irisan Asli Studi (API PNG)
                  </button>
                </div>

                <div className="viewer-preset-controls">
                  {viewerMode === "dicom" && (
                    <div
                      className="window-preset-group"
                      role="group"
                      aria-label="Preset Window/Level CT"
                    >
                      {CRANIAL_WINDOW_PRESETS.map((preset) => (
                        <button
                          key={preset.id}
                          type="button"
                          className={`preset-pill${
                            windowPreset.id === preset.id ? " active" : ""
                          }`}
                          onClick={() => setWindowPreset(preset)}
                        >
                          {preset.label}
                        </button>
                      ))}
                    </div>
                  )}

                  <label className="overlay-toggle-label">
                    <input
                      type="checkbox"
                      checked={showOverlay}
                      onChange={(event) => setShowOverlay(event.target.checked)}
                    />
                    <span>Overlay Bukti AI</span>
                  </label>
                </div>
              </div>

              {/* Active Slice Telemetry Bar */}
              <div className="image-toolbar">
                <div className="toolbar-slice-info">
                  <span>
                    SLICE {slice ? index + 1 : 0} / {study.slices.length}
                  </span>
                  {slice && citedSliceIds.has(slice.slice_id) && (
                    <span className="evidence-slice-badge">
                      ★ BUKTI TEMUAN TERKAIT
                    </span>
                  )}
                  {topCandidate && topCandidate.index === index && (
                    <span className="candidate-slice-badge">
                      ◆ KANDIDAT SKOR TERTINGGI
                    </span>
                  )}
                </div>
                <div className="toolbar-slice-meta">
                  <span>
                    {slice?.z_position_mm == null
                      ? "Z position unavailable"
                      : `Z ${slice.z_position_mm} mm`}
                  </span>
                  {slice && (
                    <span className="mono">
                      REF: {slice.slice_id.slice(0, 8)}
                    </span>
                  )}
                </div>
              </div>

              {/* Main Viewport Stage */}
              <div className="image-stage">
                {slice ? (
                  <>
                    {viewerMode === "dicom" ? (
                      <div className="cornerstone-stage-wrapper">
                        <CornerstoneViewport
                          studyId={study.study_id}
                          studyCode={studyCode}
                          modality={study.modality}
                          imageIds={dicomImageIds}
                          activeSliceIdx={index}
                          onSliceChange={selectSlice}
                          windowPreset={windowPreset}
                          showOverlay={showOverlay}
                          isEvidenceSlice={isActiveSliceEvidence}
                          currentSliceZ={slice.z_position_mm}
                          currentAssetId={slice.image_asset_id}
                          localizationBox={activeLocalization?.box ?? null}
                          slicePositiveScore={
                            activeSliceScore?.class_1_score ??
                            (citedSliceIds.has(slice.slice_id)
                              ? analysis?.findings[0]?.confidence ?? null
                              : null)
                          }
                        />
                      </div>
                    ) : (
                      <div
                        className="ct-image-frame"
                        style={
                          activeLocalization
                            ? {
                                aspectRatio: `${activeLocalization.image_width} / ${activeLocalization.image_height}`,
                              }
                            : undefined
                        }
                      >
                        {activeImageUrl ? (
                          <>
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img
                              src={activeImageUrl}
                              alt={`Anonymized CT slice ${index + 1} of ${study.slices.length}`}
                            />
                            {showOverlay && activeLocalization?.box && (
                              <div
                                className="ct-lesion-box"
                                style={{
                                  left: `${activeLocalization.box.x * 100}%`,
                                  top: `${activeLocalization.box.y * 100}%`,
                                  width: `${activeLocalization.box.width * 100}%`,
                                  height: `${activeLocalization.box.height * 100}%`,
                                }}
                              >
                                <span>Area mask ICH · riset</span>
                              </div>
                            )}
                          </>
                        ) : (
                          <div className="preview-fallback-box">
                            <p>
                              Pratinjau PNG backend memerlukan irisan yang disimpan di server API.
                            </p>
                            <button
                              type="button"
                              className="button-secondary"
                              onClick={() => setViewerMode("dicom")}
                            >
                              Buka di Cornerstone3D DICOM Viewport
                            </button>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Image-Linked Prediction Badge (Strictly Non-Diagnostic) */}
                    {(activeSliceScore ||
                      (slice && citedSliceIds.has(slice.slice_id))) && (
                      <div
                        className={`ct-model-label${
                          topCandidate?.index === index ||
                          (slice && citedSliceIds.has(slice.slice_id))
                            ? " ct-model-label-candidate"
                            : ""
                        }`}
                        role="status"
                        aria-live="polite"
                      >
                        <strong>
                          {topCandidate?.index === index
                            ? "KANDIDAT LABEL POSITIF ICH TERTINGGI"
                            : slice && citedSliceIds.has(slice.slice_id)
                              ? "IRISAN BUKTI PREDIKSI MODEL (CITED)"
                              : "SKOR LABEL POSITIF ICH"}
                        </strong>
                        <span>
                          {activeSliceScore
                            ? `${(activeSliceScore.class_1_score * 100).toFixed(1)}%`
                            : analysis?.findings[0]
                              ? `${(analysis.findings[0].confidence * 100).toFixed(0)}%`
                              : "—"}
                        </span>
                        <small>
                          Skor model riset · belum terkalibrasi · BUKAN DIAGNOSIS
                        </small>
                      </div>
                    )}
                  </>
                ) : (
                  <p>Studi ini belum memiliki irisan.</p>
                )}
              </div>

              {/* Slice Navigation Controls & Evidence Scrubber */}
              <div className="slice-controls">
                <button
                  className="button-secondary"
                  type="button"
                  disabled={!slice || index === 0}
                  onClick={() => selectSlice(Math.max(0, index - 1))}
                >
                  ← Irisan sebelumnya
                </button>
                <label htmlFor="slice-index">
                  Irisan <strong>{slice ? index + 1 : 0}</strong> dari{" "}
                  {study.slices.length}
                  {slice?.z_position_mm != null && (
                    <span className="slice-z-inline">
                      {" "}
                      (Z: {slice.z_position_mm} mm)
                    </span>
                  )}
                </label>
                <button
                  className="button-secondary"
                  type="button"
                  disabled={!slice || index >= study.slices.length - 1}
                  onClick={() =>
                    selectSlice(Math.min(study.slices.length - 1, index + 1))
                  }
                >
                  Irisan berikutnya →
                </button>
                <input
                  id="slice-index"
                  type="range"
                  min={0}
                  max={Math.max(0, study.slices.length - 1)}
                  value={index}
                  disabled={!slice}
                  onChange={(event) => selectSlice(Number(event.target.value))}
                  aria-label="Pilih irisan CT"
                />

                {/* Direct Slice Reference Strip with Evidence Badging */}
                {study.slices.length > 0 && (
                  <div
                    className="slice-pill-strip"
                    role="group"
                    aria-label="Navigasi langsung ke referensi irisan"
                  >
                    {study.slices.map((item, idx) => {
                      const isCited = citedSliceIds.has(item.slice_id);
                      const isTopScore = topCandidate?.index === idx;
                      const isActive = idx === index;
                      return (
                        <button
                          key={item.slice_id}
                          type="button"
                          className={`slice-pill-btn${isActive ? " active" : ""}${
                            isCited || isTopScore ? " evidence" : ""
                          }`}
                          onClick={() => selectSlice(idx)}
                          title={`Irisan #${idx + 1} (${
                            item.z_position_mm ?? 0
                          } mm)${isCited ? " — Irisan Bukti AI" : ""}`}
                        >
                          <span>#{idx + 1}</span>
                          {isCited && <span aria-hidden="true">★</span>}
                          {!isCited && isTopScore && (
                            <span aria-hidden="true">◆</span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            </section>

            {/* Right Sidebar: Findings, Slice Scores, Localizations, Report Editor & Reviewer Actions */}
            <FindingsSidebar
              study={study}
              studyCode={studyCode}
              analysis={analysis}
              modelScores={modelScores}
              localizations={localizations}
              topCandidate={topCandidate}
              activeSliceScore={activeSliceScore}
              activeSliceIdx={index}
              onSelectSlice={selectSlice}
              isSyntheticFixtureStudy={isSyntheticFixtureStudy}
              scoreError={scoreError}
              localizationError={localizationError}
              reviewError={reviewError}
              reviewSuccess={reviewSuccess}
              inferring={inferring}
              onRetryInference={() => void runInferenceRefresh()}
              onRecordReview={recordReview}
              reviewerId={reviewerId}
            />
          </div>
        </>
      )}
      <p className="research-note">
        Riset prototipe saja — BUKAN UNTUK PENGGUNAAN KLINIS (NOT FOR CLINICAL USE).
        Tinjau seluruh irisan DICOM secara mandiri.
      </p>
    </div>
  );
}
