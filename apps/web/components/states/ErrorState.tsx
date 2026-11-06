interface ErrorStateProps {
  title?: string;
  message?: string;
  errorCode?: string;
  onRetry?: () => void;
}

export function ErrorState({
  title = "Unable to Retrieve Study Analysis Payload",
  message = "The Meta Model API or RADAR backend service returned an unavailable status. In compliance with safety guidelines, RADAR AI does not substitute unvalidated inference when the model service is unreachable.",
  errorCode = "ERR_RADAR_UPSTREAM_503",
  onRetry,
}: ErrorStateProps) {
  return (
    <div className="state-card state-card-error" role="alert" aria-live="assertive">
      <div style={{ marginBottom: 12 }}>
        <span className="badge badge-danger mono">{errorCode}</span>
      </div>
      <h2 style={{ margin: "0 0 10px 0", fontSize: "1.25rem" }}>{title}</h2>
      <p
        style={{
          margin: "0 0 20px 0",
          color: "var(--text-secondary)",
          fontSize: "0.92rem",
        }}
      >
        {message}
      </p>
      <div
        style={{
          display: "flex",
          justifyContent: "center",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        {onRetry && (
          <button type="button" className="btn btn-primary" onClick={onRetry}>
            Retry Connection / Restore Demo Queue
          </button>
        )}
      </div>
    </div>
  );
}
