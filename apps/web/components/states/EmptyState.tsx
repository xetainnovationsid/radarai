interface EmptyStateProps {
  title?: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
}

export function EmptyState({
  title = "No Brain CT Studies in Triage Queue",
  description = "No studies match the current filter or none have been uploaded in this session. You can load the synthetic demonstration fixtures (Schema v1.0.0) to inspect the review workflow.",
  actionLabel = "Load Synthetic CT Fixtures",
  onAction,
}: EmptyStateProps) {
  return (
    <section
      className="state-card"
      role="region"
      aria-label="Empty studies queue notification"
    >
      <div style={{ marginBottom: 12 }}>
        <span className="badge badge-neutral mono">QUEUE_EMPTY</span>
      </div>
      <h2 style={{ margin: "0 0 10px 0", fontSize: "1.25rem" }}>{title}</h2>
      <p
        style={{
          margin: "0 0 22px 0",
          color: "var(--text-secondary)",
          fontSize: "0.92rem",
        }}
      >
        {description}
      </p>
      {onAction && (
        <button type="button" className="btn btn-primary" onClick={onAction}>
          {actionLabel}
        </button>
      )}
    </section>
  );
}
