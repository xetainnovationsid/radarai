interface LoadingSkeletonProps {
  label?: string;
}

export function LoadingSkeleton({
  label = "Loading brain CT studies and inference telemetry...",
}: LoadingSkeletonProps) {
  return (
    <div role="status" aria-busy="true" aria-live="polite">
      <span className="sr-only">{label}</span>

      <div className="metrics-grid" aria-hidden="true">
        {[1, 2, 3, 4].map((index) => (
          <div key={index} className="metric-card">
            <div className="skeleton-box" style={{ height: 14, width: "55%" }} />
            <div
              className="skeleton-box"
              style={{ height: 32, width: "40%", marginTop: 6 }}
            />
            <div
              className="skeleton-box"
              style={{ height: 12, width: "75%", marginTop: 6 }}
            />
          </div>
        ))}
      </div>

      <div className="panel-card" aria-hidden="true">
        <div className="panel-header">
          <div className="skeleton-box" style={{ height: 20, width: 220 }} />
          <div className="skeleton-box" style={{ height: 28, width: 120 }} />
        </div>
        <div style={{ padding: 20, display: "flex", flexDirection: "column", gap: 14 }}>
          {[1, 2, 3, 4].map((row) => (
            <div
              key={row}
              className="skeleton-box"
              style={{ height: 46, width: "100%" }}
            />
          ))}
        </div>
      </div>

      <p
        style={{
          textAlign: "center",
          color: "var(--text-muted)",
          fontSize: "0.875rem",
          marginTop: 12,
        }}
      >
        {label}
      </p>
    </div>
  );
}
