"use client";

import { useMemo, useRef, useState } from "react";
import type {
  ClinicalReportDraft,
  ReportReviewStatus,
  Study,
  StudyAnalysisResponse,
  StudyLocalizations,
  StudyModelScores,
} from "@radar-ai/contracts";
import { apiFetch, assertValidUuid } from "@/lib/api-client";

export const NON_CLINICAL_REPORT_DISCLAIMER =
  "PROTOTYPING ONLY — NOT FOR CLINICAL USE. Laporan ini adalah draf riset eksperimental berbantuan AI. Seluruh irisan DICOM wajib ditinjau secara mandiri oleh klinisi yang berwenang.";

const STORAGE_PREFIX = "radar_report_draft_v1_";

const REPORT_STATUS_LABELS: Record<ReportReviewStatus, string> = {
  draft: "DRAFT · Draf Awal",
  in_review: "IN REVIEW · Sedang Ditinjau",
  approved: "APPROVED · Disetujui Reviewer",
  rejected: "REJECTED · Ditolak / Revisi",
};

export interface ReportEditorProps {
  study: Study;
  studyCode: string;
  analysis: StudyAnalysisResponse | null;
  modelScores: StudyModelScores | null;
  localizations: StudyLocalizations | null;
  activeSliceIdx: number;
  onSelectSlice: (index: number) => void;
  reviewerId: string;
  onStatusChange?: (status: ReportReviewStatus) => void;
}

export function synthesizeDraftFromAi({
  study,
  studyCode,
  analysis,
  modelScores,
  localizations,
  reviewerId,
}: {
  study: Study;
  studyCode: string;
  analysis: StudyAnalysisResponse | null;
  modelScores: StudyModelScores | null;
  localizations: StudyLocalizations | null;
  reviewerId: string;
}): ClinicalReportDraft {
  const nowIso = new Date().toISOString();
  const modelName =
    analysis?.model_version.model_id ??
    modelScores?.model_id ??
    "densenet121-rsna-ich";
  const providerName =
    analysis?.model_version.provider ?? "local_checkpoint";

  const findingsLines: string[] = [];

  if (analysis && analysis.findings.length > 0) {
    for (const finding of analysis.findings) {
      const sliceRefs = finding.evidence_slice_ids
        .map((sliceId) => {
          const idx = study.slices.findIndex((s) => s.slice_id === sliceId);
          if (idx < 0) return null;
          const z = study.slices[idx]?.z_position_mm;
          return `[Irisan #${idx + 1}${z != null ? `, Z: ${z} mm` : ""}]`;
        })
        .filter(Boolean)
        .join(", ");

      findingsLines.push(
        `• Temuan kandidat AI (${finding.category}): Skor prediksi model ${(
          finding.confidence * 100
        ).toFixed(0)}% (belum terkalibrasi) pada referensi ${
          sliceRefs || "irisan terkait"
        }. Status audit temuan: ${finding.review_status.toUpperCase()}.`
      );
    }
  }

  if (modelScores && modelScores.slices.length > 0) {
    const topSlice = modelScores.slices.reduce((best, curr) =>
      curr.class_1_score > best.class_1_score ? curr : best
    );
    const zPos = study.slices[topSlice.index]?.z_position_mm;
    findingsLines.push(
      `• Klasifikasi per-irisan DenseNet-121 (${modelScores.model_id}): Skor kandidat label positif ICH tertinggi pada [Irisan #${
        topSlice.index + 1
      }${zPos != null ? `, Z: ${zPos} mm` : ""}] sebesar ${(
        topSlice.class_1_score * 100
      ).toFixed(1)}% (negatif: ${(topSlice.class_0_score * 100).toFixed(1)}%).`
    );
  }

  if (localizations && localizations.slices.length > 0) {
    const maskedSlices = localizations.slices.filter((s) => s.box !== null);
    if (maskedSlices.length > 0) {
      const largest = maskedSlices.reduce((best, curr) =>
        curr.mask_pixels > best.mask_pixels ? curr : best
      );
      findingsLines.push(
        `• Segmentasi lesi SAMIHS (${localizations.model_id}): Teridentifikasi kandidat mask pada ${maskedSlices.length} irisan. Area mask terbesar pada [Irisan #${
          largest.index + 1
        }] (${largest.mask_pixels} piksel, threshold ${localizations.threshold}).`
      );
    } else {
      findingsLines.push(
        `• Segmentasi lesi SAMIHS: Tidak ditemukan area mask kandidat di atas threshold ${localizations.threshold}.`
      );
    }
  }

  if (findingsLines.length === 0) {
    findingsLines.push(
      `• Seri CT kepala terdiri dari ${study.slices.length} irisan aksial.`,
      "• Belum ada kandidat temuan otomatis yang tersimpan atau skor inference lokal belum dijalankan.",
      "• Evaluasi atenuasi parenkim, sistem ventrikel, dan garis tengah dilakukan secara manual melalui Cornerstone3D DICOM viewport."
    );
  } else {
    findingsLines.push(
      "• Evaluasi tambahan: Struktur garis tengah (midline), sisterna basalis, sistem ventrikel, dan tulang kalvarium ditinjau secara mandiri menggunakan preset window Brain (W:80 L:40), Subdural (W:200 L:75), dan Bone (W:2500 L:480)."
    );
  }

  const hasPositiveCandidate =
    (analysis && analysis.findings.length > 0) ||
    (modelScores?.slices.some((s) => s.class_1_score >= 0.5) ?? false);

  const impressionText = hasPositiveCandidate
    ? `Ditemukan kandidat hiperdensitas intrakranial yang mencurigakan perdarahan intrakranial (ICH) pada studi ${studyCode} berdasarkan deteksi prototipe AI. Seluruh skor bersifat eksperimental dan belum terkalibrasi — memerlukan verifikasi radiologis mandiri segera.`
    : `Tidak terdeteksi kandidat perdarahan intrakranial fokal berkepercayaan tinggi oleh model prototipe pada studi ${studyCode}. Korelasi klinis dan pembacaan manual penuh tetap diperlukan.`;

  return {
    report_id: `RPT-${study.study_id.slice(0, 8).toUpperCase()}`,
    study_id: study.study_id,
    study_code: studyCode,
    status: "draft",
    clinical_indication:
      "Evaluasi CT kepala non-kontras untuk skrining riset perdarahan intrakranial akut (ICH) / defisit neurologis fokal.",
    technique: `CT kepala aksial non-kontras (${study.slices.length} irisan DICOM Part 10). Analisis berbantuan model riset ${modelName} (${providerName}) dan inspeksi Hounsfield Unit (HU) interaktif.`,
    findings: findingsLines.join("\n"),
    impression: impressionText,
    reviewer_notes:
      "Tinjauan prototipe riset RADAR AI selesai. Verifikasi multi-window (Brain, Subdural, Stroke, Bone) telah dilakukan.",
    reviewer_id: reviewerId,
    concurrence_confirmed: false,
    created_at: nowIso,
    updated_at: nowIso,
    signed_at: null,
    non_clinical_disclaimer: NON_CLINICAL_REPORT_DISCLAIMER,
  };
}

function loadSavedDraft(studyId: string): ClinicalReportDraft | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(`${STORAGE_PREFIX}${studyId}`);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<ClinicalReportDraft>;
    if (parsed && typeof parsed.findings === "string" && parsed.study_id === studyId) {
      return {
        report_id: parsed.report_id ?? `RPT-${studyId.slice(0, 8).toUpperCase()}`,
        study_id: studyId,
        study_code: parsed.study_code ?? `CT-${studyId.slice(0, 8).toUpperCase()}`,
        status: parsed.status ?? "draft",
        clinical_indication: parsed.clinical_indication ?? "",
        technique: parsed.technique ?? "",
        findings: parsed.findings,
        impression: parsed.impression ?? "",
        reviewer_notes: parsed.reviewer_notes ?? "",
        reviewer_id: parsed.reviewer_id ?? "local-reviewer",
        concurrence_confirmed: Boolean(parsed.concurrence_confirmed),
        created_at: parsed.created_at ?? new Date().toISOString(),
        updated_at: parsed.updated_at ?? new Date().toISOString(),
        signed_at: parsed.signed_at ?? null,
        non_clinical_disclaimer: NON_CLINICAL_REPORT_DISCLAIMER,
      };
    }
  } catch {
    // Ignore storage read errors
  }
  return null;
}

export function formatReportAsMarkdown(draft: ClinicalReportDraft): string {
  return [
    `# LAPORAN RISET RADIOLOGI CT KEPALA — ${draft.study_code}`,
    "",
    `> **PERINGATAN KESELAMATAN:** ${draft.non_clinical_disclaimer}`,
    "",
    `- **Report ID:** \`${draft.report_id}\``,
    `- **Study ID:** \`${draft.study_id}\``,
    `- **Status Laporan:** \`${draft.status.toUpperCase()}\``,
    `- **Reviewer:** \`${draft.reviewer_id}\``,
    `- **Terakhir Diperbarui:** ${new Date(draft.updated_at).toLocaleString("id-ID")}`,
    draft.signed_at
      ? `- **Disahkan Pada:** ${new Date(draft.signed_at).toLocaleString("id-ID")}`
      : `- **Status Pengesahan:** Belum disahkan (Draf)`,
    "",
    "## 1. Indikasi Klinis",
    draft.clinical_indication.trim() || "—",
    "",
    "## 2. Teknik Pemeriksaan",
    draft.technique.trim() || "—",
    "",
    "## 3. Temuan (Findings & Referensi Irisan)",
    draft.findings.trim() || "—",
    "",
    "## 4. Kesan / Kesimpulan (Impression)",
    draft.impression.trim() || "—",
    "",
    "## 5. Catatan & Rekomendasi Reviewer",
    draft.reviewer_notes.trim() || "—",
    "",
    "---",
    `*RADAR AI Research Prototype · ${draft.non_clinical_disclaimer}*`,
  ].join("\n");
}

export function ReportEditor({
  study,
  studyCode,
  analysis,
  modelScores,
  localizations,
  activeSliceIdx,
  onSelectSlice,
  reviewerId,
  onStatusChange,
}: ReportEditorProps) {
  const [draft, setDraft] = useState<ClinicalReportDraft>(() => {
    const saved = loadSavedDraft(study.study_id);
    if (saved) return saved;
    return synthesizeDraftFromAi({
      study,
      studyCode,
      analysis,
      modelScores,
      localizations,
      reviewerId,
    });
  });

  const [actionError, setActionError] = useState("");
  const [actionErrorCode, setActionErrorCode] = useState("");
  const [feedbackBanner, setFeedbackBanner] = useState("");
  const [lastSavedTime, setLastSavedTime] = useState<string>("");
  const [savingToApi, setSavingToApi] = useState(false);

  const findingsTextareaRef = useRef<HTMLTextAreaElement | null>(null);

  const activeSlice = study.slices[activeSliceIdx] ?? null;
  const activeSliceScore = useMemo(
    () => modelScores?.slices.find((s) => s.index === activeSliceIdx) ?? null,
    [modelScores, activeSliceIdx]
  );

  // Extract cited slice numbers (e.g., "#1", "Irisan #3") from findings and impression text
  const citedSliceIndicesInReport = useMemo(() => {
    const combined = `${draft.findings}\n${draft.impression}`;
    const regex = /#(\d+)/g;
    const found = new Set<number>();
    let match: RegExpExecArray | null = regex.exec(combined);
    while (match !== null) {
      const oneBased = Number.parseInt(match[1], 10);
      if (
        Number.isFinite(oneBased) &&
        oneBased >= 1 &&
        oneBased <= study.slices.length
      ) {
        found.add(oneBased - 1);
      }
      match = regex.exec(combined);
    }
    return Array.from(found).sort((a, b) => a - b);
  }, [draft.findings, draft.impression, study.slices.length]);

  function persistDraft(nextDraft: ClinicalReportDraft, showNotice?: string) {
    setDraft(nextDraft);
    setActionError("");
    setActionErrorCode("");
    onStatusChange?.(nextDraft.status);

    try {
      if (typeof window !== "undefined") {
        window.localStorage.setItem(
          `${STORAGE_PREFIX}${study.study_id}`,
          JSON.stringify(nextDraft)
        );
      }
      const timeLabel = new Date().toLocaleTimeString("id-ID", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
      setLastSavedTime(timeLabel);
      if (showNotice) {
        setFeedbackBanner(showNotice);
      }
    } catch {
      setActionError(
        "Gagal menyimpan draf ke penyimpanan lokal browser (kuota penuh atau mode privat)."
      );
      setActionErrorCode("ERR_REPORT_STORAGE");
    }
  }

  function updateField<K extends keyof ClinicalReportDraft>(
    field: K,
    value: ClinicalReportDraft[K]
  ) {
    const nowIso = new Date().toISOString();
    const nextDraft: ClinicalReportDraft = {
      ...draft,
      [field]: value,
      reviewer_id: reviewerId,
      updated_at: nowIso,
      // If an approved report is manually edited, revert status to in_review so it must be re-approved
      status:
        draft.status === "approved" &&
        field !== "status" &&
        field !== "concurrence_confirmed"
          ? "in_review"
          : draft.status,
      signed_at:
        draft.status === "approved" &&
        field !== "status" &&
        field !== "concurrence_confirmed"
          ? null
          : draft.signed_at,
    };
    persistDraft(nextDraft);
  }

  function handleSynthesizeFromAi() {
    const generated = synthesizeDraftFromAi({
      study,
      studyCode,
      analysis,
      modelScores,
      localizations,
      reviewerId,
    });
    persistDraft(
      generated,
      "Draf laporan berhasil disintesis ulang dari hasil inference AI terbaru."
    );
  }

  async function handleGenerateMetaDraft() {
    if (!analysis?.findings.length) {
      setActionError("Belum ada temuan tersimpan sebagai sumber draf laporan.");
      setActionErrorCode("ERR_REPORT_SOURCE_REQUIRED");
      return;
    }
    setSavingToApi(true);
    setActionError("");
    setActionErrorCode("");
    try {
      const safeStudyId = assertValidUuid(study.study_id, "Study ID");
      const response = await apiFetch(
        `/v1/studies/${safeStudyId}/reports/drafts`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }
      );
      const result = (await response.json().catch(() => ({}))) as {
        report_id?: string;
        version?: number;
        detail?: string;
        model_id?: string | null;
        content?: {
          findings?: Array<{ text: string; finding_ids: string[] }>;
          impression?: { text: string; finding_ids: string[] };
          limitations?: string;
        };
      };
      if (!response.ok || !result.content || !result.report_id) {
        throw new Error(result.detail ?? `Draf Meta gagal dibuat (HTTP ${response.status}).`);
      }
      const findingText = result.content.findings
        ?.map((item) => `${item.text} [Temuan: ${item.finding_ids.join(", ")}]`)
        .join("\n") ?? "";
      const nowIso = new Date().toISOString();
      const nextDraft: ClinicalReportDraft = {
        ...draft,
        report_id: result.report_id,
        findings: findingText,
        impression: result.content.impression
          ? `${result.content.impression.text} [Temuan: ${result.content.impression.finding_ids.join(", ")}]`
          : draft.impression,
        reviewer_notes: `${draft.reviewer_notes.trim()}\nMeta model: ${result.model_id ?? "unknown"}. Draf masih memerlukan review manusia.`.trim(),
        status: "draft",
        reviewer_id: reviewerId,
        updated_at: nowIso,
        signed_at: null,
      };
      persistDraft(
        nextDraft,
        `Draf Meta v${result.version ?? "?"} tersimpan di API. Periksa kutipan dan edit sebelum review.`
      );
    } catch (cause) {
      setActionError(cause instanceof Error ? cause.message : "Draf Meta tidak dapat dibuat.");
      setActionErrorCode("ERR_META_REPORT_DRAFT");
    } finally {
      setSavingToApi(false);
    }
  }

  async function handleSaveManualDraftToApi() {
    const sourceFindingIds = analysis?.findings.map((finding) => finding.finding_id) ?? [];
    if (sourceFindingIds.length === 0) {
      setActionError("Manual fallback memerlukan minimal satu temuan tersimpan untuk dikutip.");
      setActionErrorCode("ERR_REPORT_SOURCE_REQUIRED");
      return;
    }
    setSavingToApi(true);
    setActionError("");
    setActionErrorCode("");
    try {
      const safeStudyId = assertValidUuid(study.study_id, "Study ID");
      const response = await apiFetch(
        `/v1/studies/${safeStudyId}/reports/drafts`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            manual_content: {
              findings: [
                {
                  text: draft.findings.trim() || "Manual reviewer draft.",
                  finding_ids: sourceFindingIds,
                },
              ],
              impression: {
                text: draft.impression.trim() || "Requires human review.",
                finding_ids: sourceFindingIds,
              },
              limitations:
                draft.non_clinical_disclaimer || "Research prototype; not for clinical use.",
            },
          }),
        }
      );
      const result = (await response.json().catch(() => ({}))) as {
        version?: number;
        detail?: string;
      };
      if (!response.ok) {
        throw new Error(result.detail ?? `Simpan draf gagal (HTTP ${response.status}).`);
      }
      setFeedbackBanner(`Draf manual v${result.version ?? "?"} tersimpan di API dengan kutipan temuan.`);
    } catch (cause) {
      setActionError(cause instanceof Error ? cause.message : "Draf manual tidak dapat disimpan.");
      setActionErrorCode("ERR_MANUAL_REPORT_SAVE");
    } finally {
      setSavingToApi(false);
    }
  }

  function handleInsertActiveSliceCitation() {
    if (!activeSlice) {
      setActionError("Tidak ada irisan aktif yang dapat dikutip.");
      setActionErrorCode("ERR_NO_ACTIVE_SLICE");
      return;
    }

    const zLabel =
      activeSlice.z_position_mm != null
        ? `, Z: ${activeSlice.z_position_mm} mm`
        : "";
    const scoreLabel = activeSliceScore
      ? `, Skor ICH: ${(activeSliceScore.class_1_score * 100).toFixed(1)}%`
      : "";
    const citationToken = `[Irisan #${activeSliceIdx + 1}${zLabel}${scoreLabel}]`;

    const textarea = findingsTextareaRef.current;
    let nextFindings = draft.findings;

    if (textarea && typeof textarea.selectionStart === "number") {
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      const before = draft.findings.slice(0, start);
      const after = draft.findings.slice(end);
      const needsLeadingSpace =
        before.length > 0 && !before.endsWith(" ") && !before.endsWith("\n");
      nextFindings = `${before}${needsLeadingSpace ? " " : ""}${citationToken}${after}`;
    } else {
      nextFindings = `${draft.findings.trimEnd()}\n• Observasi manual pada ${citationToken}: `;
    }

    const nextDraft: ClinicalReportDraft = {
      ...draft,
      findings: nextFindings,
      reviewer_id: reviewerId,
      updated_at: new Date().toISOString(),
    };
    persistDraft(
      nextDraft,
      `Kutipan ${citationToken} ditambahkan ke bagian Temuan.`
    );
  }

  function handleReviewerStatusAction(targetStatus: ReportReviewStatus) {
    setFeedbackBanner("");
    if (targetStatus === "approved") {
      if (!draft.findings.trim() || !draft.impression.trim()) {
        setActionError(
          "Bagian Temuan (Findings) dan Kesan (Impression) tidak boleh kosong sebelum menyetujui laporan."
        );
        setActionErrorCode("ERR_REPORT_EMPTY_FIELDS");
        return;
      }
      if (!draft.concurrence_confirmed) {
        setActionError(
          "Harap centang pernyataan konfirmasi peninjauan manual non-klinis sebelum menyetujui (Approve) laporan."
        );
        setActionErrorCode("ERR_REPORT_CONCURRENCE_REQUIRED");
        return;
      }
    }

    const nowIso = new Date().toISOString();
    const nextDraft: ClinicalReportDraft = {
      ...draft,
      status: targetStatus,
      reviewer_id: reviewerId,
      updated_at: nowIso,
      signed_at: targetStatus === "approved" ? nowIso : null,
    };

    const statusNoticeMap: Record<ReportReviewStatus, string> = {
      draft: "Status laporan dikembalikan menjadi Draf (Draft).",
      in_review: "Laporan ditandai Sedang Ditinjau (In Review).",
      approved: `Laporan riset ${studyCode} telah DISETUJUI (Approved) oleh ${reviewerId}.`,
      rejected: "Draf laporan ditolak dan memerlukan revisi manual.",
    };

    persistDraft(nextDraft, statusNoticeMap[targetStatus]);
  }

  async function handleCopyReportText() {
    setActionError("");
    try {
      const markdown = formatReportAsMarkdown(draft);
      await navigator.clipboard.writeText(markdown);
      setFeedbackBanner("Teks laporan riset berhasil disalin ke clipboard.");
    } catch {
      setActionError(
        "Gagal menyalin ke clipboard. Gunakan tombol Unduh Markdown (.md) sebagai alternatif."
      );
      setActionErrorCode("ERR_CLIPBOARD_DENIED");
    }
  }

  function handleDownloadFile(format: "md" | "json") {
    setActionError("");
    try {
      const content =
        format === "md"
          ? formatReportAsMarkdown(draft)
          : JSON.stringify(draft, null, 2);
      const mimeType =
        format === "md"
          ? "text/markdown;charset=utf-8"
          : "application/json;charset=utf-8";
      const blob = new Blob([content], { type: mimeType });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `RADAR-Report-${studyCode}.${format}`;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      URL.revokeObjectURL(url);
      setFeedbackBanner(
        `File RADAR-Report-${studyCode}.${format} berhasil diunduh.`
      );
    } catch {
      setActionError(`Gagal mengunduh file laporan .${format}.`);
      setActionErrorCode("ERR_EXPORT_DOWNLOAD");
    }
  }

  function handlePrintReport() {
    if (typeof window !== "undefined") {
      window.print();
    }
  }

  const statusBadgeClass =
    draft.status === "approved"
      ? "badge-success"
      : draft.status === "rejected"
        ? "badge-danger"
        : draft.status === "in_review"
          ? "badge-warning"
          : "badge-neutral";

  return (
    <div className="report-editor-shell" aria-label="Editor laporan riset radiologi">
      {/* Header & Status Pill */}
      <div className="report-editor-header">
        <div>
          <p className="eyebrow">STRUCTURED RESEARCH REPORT EDITOR</p>
          <h3>Draf Laporan & Pengesahan Reviewer</h3>
        </div>
        <span className={`badge ${statusBadgeClass} mono`}>
          {REPORT_STATUS_LABELS[draft.status]}
        </span>
      </div>

      {/* Visible Error Banner for Report Actions */}
      {actionError && (
        <div className="notice notice-error report-notice" role="alert">
          <div className="report-notice-header">
            <strong>Gagal memproses tindakan laporan</strong>
            {actionErrorCode && (
              <span className="badge badge-danger mono">{actionErrorCode}</span>
            )}
          </div>
          <p style={{ margin: "4px 0 0" }}>{actionError}</p>
        </div>
      )}

      {/* Feedback Banner */}
      {feedbackBanner && !actionError && (
        <div className="notice notice-success report-notice" role="status">
          {feedbackBanner}
        </div>
      )}

      {/* AI Draft Synthesis & Active Slice Citation Toolbar */}
      <div className="report-ai-toolbar">
        <button
          type="button"
          className="button-primary button-sm"
          onClick={handleSynthesizeFromAi}
          title="Sintesis ulang draf otomatis dari temuan model, skor DenseNet121, dan lokalisasi SAMIHS"
        >
          ✨ Buat / Perbarui Draf dari AI
        </button>
        <button
          type="button"
          className="button-primary button-sm"
          onClick={() => void handleGenerateMetaDraft()}
          disabled={savingToApi || !analysis?.findings.length}
          title="Minta Meta membuat draf terstruktur dari temuan tersimpan saja"
        >
          {savingToApi ? "Menyimpan…" : "Buat Draf Meta"}
        </button>
        <button
          type="button"
          className="button-secondary button-sm"
          onClick={() => void handleSaveManualDraftToApi()}
          disabled={savingToApi || !analysis?.findings.length}
          title="Simpan teks manual ke API dengan kutipan temuan tersimpan"
        >
          Simpan Draf Manual ke API
        </button>
        <button
          type="button"
          className="button-secondary button-sm"
          disabled={!activeSlice}
          onClick={handleInsertActiveSliceCitation}
          title="Sisipkan kutipan irisan CT yang sedang aktif ke dalam teks Temuan"
        >
          + Kutip Irisan Aktif (#{activeSlice ? activeSliceIdx + 1 : 0})
        </button>
        {lastSavedTime && (
          <span className="report-autosave-meta mono">
            Tersimpan: {lastSavedTime}
          </span>
        )}
      </div>

      {/* Interactive Slice Citations Found in Report */}
      {citedSliceIndicesInReport.length > 0 && (
        <div className="report-citation-bar" aria-label="Referensi irisan dalam laporan">
          <span className="citation-bar-label">Irisan dikutip di laporan:</span>
          <div className="citation-chip-group">
            {citedSliceIndicesInReport.map((sliceIdx) => {
              const isCurrent = sliceIdx === activeSliceIdx;
              const zMm = study.slices[sliceIdx]?.z_position_mm;
              return (
                <button
                  key={sliceIdx}
                  type="button"
                  className={`evidence-link${isCurrent ? " active" : ""}`}
                  onClick={() => onSelectSlice(sliceIdx)}
                  title={`Lompat ke irisan #${sliceIdx + 1} di viewport DICOM`}
                >
                  ★ Irisan #{sliceIdx + 1}
                  {zMm != null ? ` (${zMm} mm)` : ""}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Manual Report Editing Form */}
      <div className="report-form-stack">
        <div className="report-field-group">
          <label htmlFor="report-indication">
            1. Indikasi Klinis (Clinical Indication)
          </label>
          <textarea
            id="report-indication"
            className="report-textarea report-textarea-sm"
            rows={2}
            value={draft.clinical_indication}
            onChange={(e) => updateField("clinical_indication", e.target.value)}
            placeholder="Masukkan indikasi klinis pemeriksaan CT kepala…"
          />
        </div>

        <div className="report-field-group">
          <label htmlFor="report-technique">
            2. Teknik Pemeriksaan & Provenance Model (Technique)
          </label>
          <textarea
            id="report-technique"
            className="report-textarea report-textarea-sm"
            rows={2}
            value={draft.technique}
            onChange={(e) => updateField("technique", e.target.value)}
            placeholder="Deskripsi protokol akuisisi CT dan model AI…"
          />
        </div>

        <div className="report-field-group">
          <div className="report-field-label-row">
            <label htmlFor="report-findings">
              3. Temuan Radiologis & Bukti Irisan (Findings)
            </label>
            <span className="mono muted-copy">
              {draft.findings.length} karakter
            </span>
          </div>
          <textarea
            id="report-findings"
            ref={findingsTextareaRef}
            className="report-textarea"
            rows={6}
            value={draft.findings}
            onChange={(e) => updateField("findings", e.target.value)}
            placeholder="Uraikan temuan per irisan CT, atenuasi HU, dan evaluasi anatomi…"
          />
        </div>

        <div className="report-field-group">
          <div className="report-field-label-row">
            <label htmlFor="report-impression">
              4. Kesan / Kesimpulan Riset (Impression)
            </label>
            <span className="mono muted-copy">
              {draft.impression.length} karakter
            </span>
          </div>
          <textarea
            id="report-impression"
            className="report-textarea report-textarea-md"
            rows={3}
            value={draft.impression}
            onChange={(e) => updateField("impression", e.target.value)}
            placeholder="Ringkasan kesan utama hasil tinjauan…"
          />
        </div>

        <div className="report-field-group">
          <label htmlFor="report-notes">
            5. Catatan & Rekomendasi Reviewer (Reviewer Notes)
          </label>
          <textarea
            id="report-notes"
            className="report-textarea report-textarea-sm"
            rows={2}
            value={draft.reviewer_notes}
            onChange={(e) => updateField("reviewer_notes", e.target.value)}
            placeholder="Catatan audit tambahan, koreksi terhadap prediksi model, atau rekomendasi tindak lanjut…"
          />
        </div>
      </div>

      {/* Reviewer Concurrence & Sign-off Box */}
      <div className="report-signoff-box">
        <h4>Tindakan & Pengesahan Reviewer (Human-in-the-Loop)</h4>
        <label className="concurrence-checkbox-label">
          <input
            type="checkbox"
            checked={draft.concurrence_confirmed}
            onChange={(e) =>
              updateField("concurrence_confirmed", e.target.checked)
            }
          />
          <span>
            Saya (<strong>{reviewerId}</strong>) telah meninjau irisan DICOM secara
            mandiri dan mengonfirmasi bahwa laporan ini adalah{" "}
            <strong>PROTOTIPE RISET — BUKAN UNTUK PENGGUNAAN KLINIS</strong>.
          </span>
        </label>

        <div className="reviewer-action-buttons">
          <button
            type="button"
            className={`button-secondary button-sm${
              draft.status === "draft" ? " active-status-btn" : ""
            }`}
            onClick={() => handleReviewerStatusAction("draft")}
          >
            Simpan Draf
          </button>
          <button
            type="button"
            className={`button-secondary button-sm${
              draft.status === "in_review" ? " active-status-btn" : ""
            }`}
            onClick={() => handleReviewerStatusAction("in_review")}
          >
            Tandai Ditinjau
          </button>
          <button
            type="button"
            className="button-primary button-sm"
            onClick={() => handleReviewerStatusAction("approved")}
          >
            ✓ Setujui Laporan (Approve)
          </button>
          <button
            type="button"
            className="button-danger button-sm"
            onClick={() => handleReviewerStatusAction("rejected")}
          >
            ✕ Tolak / Revisi
          </button>
        </div>

        {draft.status === "approved" && draft.signed_at && (
          <div className="signoff-stamp" role="status">
            <strong>✓ DISETUJUI OLEH REVIEWER (APPROVED)</strong>
            <span>
              Reviewer: <code>{draft.reviewer_id}</code> · Waktu:{" "}
              {new Date(draft.signed_at).toLocaleString("id-ID")} · ID:{" "}
              <code>{draft.report_id}</code>
            </span>
          </div>
        )}
      </div>

      {/* Export & Handoff Actions */}
      <div className="report-export-toolbar" aria-label="Ekspor laporan riset">
        <span className="export-label">Ekspor & Handoff:</span>
        <div className="export-buttons-row">
          <button
            type="button"
            className="button-secondary button-sm"
            onClick={() => void handleCopyReportText()}
          >
            Salin Teks
          </button>
          <button
            type="button"
            className="button-secondary button-sm"
            onClick={() => handleDownloadFile("md")}
          >
            Unduh (.md)
          </button>
          <button
            type="button"
            className="button-secondary button-sm"
            onClick={() => handleDownloadFile("json")}
          >
            Unduh (.json)
          </button>
          <button
            type="button"
            className="button-secondary button-sm"
            onClick={handlePrintReport}
          >
            Cetak / PDF
          </button>
        </div>
      </div>

      {/* Print-Only Clinical Research Summary Sheet */}
      <section className="print-only-report" aria-hidden="true">
        <h1>LAPORAN RISET RADIOLOGI CT KEPALA — {studyCode}</h1>
        <p className="print-disclaimer">{draft.non_clinical_disclaimer}</p>
        <p>
          <strong>Report ID:</strong> {draft.report_id} |{" "}
          <strong>Study ID:</strong> {draft.study_id} |{" "}
          <strong>Status:</strong> {draft.status.toUpperCase()} |{" "}
          <strong>Reviewer:</strong> {draft.reviewer_id}
        </p>
        <hr />
        <h2>1. Indikasi Klinis</h2>
        <p>{draft.clinical_indication}</p>
        <h2>2. Teknik Pemeriksaan</h2>
        <p>{draft.technique}</p>
        <h2>3. Temuan Radiologis (Findings)</h2>
        <pre>{draft.findings}</pre>
        <h2>4. Kesan (Impression)</h2>
        <p>{draft.impression}</p>
        <h2>5. Catatan Reviewer</h2>
        <p>{draft.reviewer_notes}</p>
      </section>
    </div>
  );
}

