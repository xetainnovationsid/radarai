import type { FindingReviewStatus, StudyStatus } from "@radar-ai/contracts";

export function StudyStatusBadge({ status }: { status: StudyStatus }) {
  const config: Record<
    StudyStatus,
    { label: string; className: string; symbol: string }
  > = {
    ready: { label: "Ready for Review", className: "badge-success", symbol: "✓" },
    processing: { label: "Processing Slices", className: "badge-warning", symbol: "⟳" },
    uploaded: { label: "Uploaded", className: "badge-neutral", symbol: "↑" },
    failed: { label: "Pipeline Failed", className: "badge-danger", symbol: "✕" },
  };

  const current = config[status];
  return (
    <span className={`badge ${current.className}`}>
      <span aria-hidden="true">{current.symbol}</span>
      <span>{current.label}</span>
    </span>
  );
}

export function ReviewStatusBadge({ status }: { status: FindingReviewStatus }) {
  const config: Record<
    FindingReviewStatus,
    { label: string; className: string; symbol: string }
  > = {
    pending: { label: "Pending Clinician Review", className: "badge-warning", symbol: "●" },
    accepted: { label: "Accepted Finding", className: "badge-success", symbol: "✓" },
    rejected: { label: "Rejected Finding", className: "badge-neutral", symbol: "✕" },
    uncertain: { label: "Uncertain / Needs Consult", className: "badge-danger", symbol: "?" },
  };

  const current = config[status];
  return (
    <span className={`badge ${current.className}`}>
      <span aria-hidden="true">{current.symbol}</span>
      <span>{current.label}</span>
    </span>
  );
}
