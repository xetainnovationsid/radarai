export function DisclaimerBanner() {
  return (
    <div
      className="disclaimer-banner"
      role="region"
      aria-label="Research prototype safety disclaimer"
    >
      <div>
        <strong>PROTOTYPING ONLY — NOT FOR CLINICAL USE:</strong> RADAR AI is an experimental
        research prototype for the Meta Global AI Developer Hackathon 2026. Outputs require
        qualified human review and must never be used for clinical diagnosis, triage, or patient
        care.
      </div>
      <span className="badge badge-warning mono">Schema v1.0.0 • Epic RDA-4</span>
    </div>
  );
}
