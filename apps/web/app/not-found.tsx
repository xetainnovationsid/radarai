import Link from "next/link";

export default function NotFound() {
  return (
    <section className="state-card" role="region" aria-label="Page not found">
      <div style={{ marginBottom: 12 }}>
        <span className="badge badge-warning mono">404_NOT_FOUND</span>
      </div>
      <h1 style={{ margin: "0 0 10px 0", fontSize: "1.4rem" }}>
        Requested Study or Route Not Found
      </h1>
      <p style={{ margin: "0 0 22px 0", color: "var(--text-secondary)" }}>
        The study UUID or route segment you requested does not exist in the synthetic demonstration
        catalog.
      </p>
      <Link href="/" className="btn btn-primary">
        Return to Triage Dashboard
      </Link>
    </section>
  );
}
