"use client";

import { useState } from "react";
import { useAuth } from "@/components/AuthContext";
import { API_BASE, apiFetch } from "@/lib/api-client";

interface AuthStatusPayload {
  authenticated: boolean;
  auth_required: boolean;
  auth_method: string;
  subject: string;
  reviewer_id: string;
  email: string | null;
}

export default function SystemStatusPage() {
  const { user, firebaseConfigured, authRequired } = useAuth();
  const [status, setStatus] = useState<"idle" | "checking" | "online" | "offline">("idle");
  const [detail, setDetail] = useState("The latest API and authentication state appears after a health check.");
  const [authStatus, setAuthStatus] = useState<AuthStatusPayload | null>(null);
  const [rateInfo, setRateInfo] = useState<string>("Not checked");

  async function checkHealth() {
    setStatus("checking");
    setDetail(
      API_BASE
        ? `Checking ${API_BASE}/health and /v1/auth/me…`
        : "Checking backend configuration…"
    );
    try {
      const response = await apiFetch("/health");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const health = (await response.json()) as { status?: string; environment?: string };

      const meResp = await apiFetch("/v1/auth/me");
      const limit = meResp.headers.get("X-RateLimit-Limit");
      const remaining = meResp.headers.get("X-RateLimit-Remaining");
      if (limit && remaining) setRateInfo(`${remaining} / ${limit} requests per minute`);
      if (meResp.ok) setAuthStatus((await meResp.json()) as AuthStatusPayload);

      setStatus("online");
      setDetail(`API active · ${health.environment ?? "environment not reported"}`);
    } catch (error) {
      setStatus("offline");
      setDetail(error instanceof Error ? error.message : "The API could not be reached.");
    }
  }

  return (
    <div className="system-page">
      <section className="system-overview" aria-labelledby="system-title">
        <div className="system-main-column">
          <header className="system-intro">
            <p className="eyebrow">SYSTEM <span>/</span> SERVICE HEALTH</p>
            <h1 id="system-title">Keep the workflow<br />in a healthy state.</h1>
            <p>Connectivity and safeguards, presented clearly. No green checks before verification.</p>
          </header>

          <section className={`system-connection status-${status}`} aria-labelledby="connection-title">
            <div className="system-connection-copy">
              <p className="eyebrow">BACKEND CONNECTION</p>
              <h2 id="connection-title">{status === "idle" ? "Not checked" : status === "checking" ? "Checking connection…" : status === "online" ? "Connected" : "Unavailable"}</h2>
              <p role="status" aria-live="polite">{detail}</p>
              <button type="button" className="system-check-button" disabled={status === "checking"} onClick={() => void checkHealth()}>
                {status === "checking" ? "Checking…" : "Check API health"}
              </button>
            </div>
            <div className="system-signal" aria-hidden="true">
              {[28, 43, 58, 39, 70, 50, 36, 57, 43, 62, 48].map((height, index) => <span key={index} style={{ height }} />)}
            </div>
            <small className="system-signal-caption">Live status is shown after a check</small>
          </section>
        </div>

        <aside className="verification-card" aria-labelledby="verification-title">
          <h2 id="verification-title">Verification points</h2>
          <p>A single source of truth for research operations.</p>
          <ol>
            <li><span>01</span><div><strong>Identity</strong><small>Firebase OAuth / API token</small><em>{firebaseConfigured ? "Firebase configured" : "Firebase not configured"}</em></div></li>
            <li><span>02</span><div><strong>DICOM validation</strong><small>Format and metadata checks</small><em>Part 10 · PHI / PN blocked</em></div></li>
            <li><span>03</span><div><strong>Data handling</strong><small>Private storage / no-store</small><em>Private research storage</em></div></li>
            <li><span>04</span><div><strong>Rate limiting</strong><small>Edge and backend controls</small><em>{rateInfo}</em></div></li>
          </ol>
        </aside>
      </section>

      <section className="system-contract" id="contract" aria-labelledby="contract-title">
        <div className="system-contract-heading">
          <div><p className="eyebrow">MODEL &amp; API CONTRACT</p><h2 id="contract-title">Research safeguards</h2></div>
          <div className="system-shortcuts"><a href="#model-evaluation">Model evaluation <span aria-hidden="true">→</span></a><a href="#security-layers">Security <span aria-hidden="true">↗</span></a></div>
        </div>
        <div className="system-contract-grid" id="model-evaluation">
          <article><span>01</span><p>API contract</p><strong>v1.0.0</strong></article>
          <article><span>02</span><p>Model provider</p><strong>Local checkpoint</strong></article>
          <article><span>03</span><p>Data target</p><strong>RSNA ICH</strong></article>
          <article><span>04</span><p>Intended use</p><strong>Research only</strong></article>
        </div>
      </section>

      <div className="system-detail-grid">
        <section className="system-detail-card" aria-labelledby="identity-title">
          <p className="eyebrow">IDENTITY &amp; SESSION</p>
          <h2 id="identity-title">Research access</h2>
          <dl className="study-metadata">
            <div><dt>Firebase OAuth</dt><dd>{firebaseConfigured ? "Configured" : "Not configured"}</dd></div>
            <div><dt>Research session</dt><dd>{user ? user.email ?? user.uid : "Not signed in"}</dd></div>
            <div><dt>API enforcement</dt><dd>{authStatus ? authStatus.auth_required ? `Required (${authStatus.auth_method})` : `Optional (${authStatus.auth_method})` : authRequired ? "OAuth required" : "Optional in development"}</dd></div>
            <div><dt>Rate limiter</dt><dd>{rateInfo}</dd></div>
          </dl>
        </section>
        <section className="system-detail-card" id="security-layers" aria-labelledby="safety-title">
          <p className="eyebrow">SECURITY LAYERS</p>
          <h2 id="safety-title">Data stays protected</h2>
          <p>Token verification, request rate limits, DICOM Part 10 validation, patient identifier checks, and strict browser security headers are applied across the workflow.</p>
          <div className="system-safety-label">Research prototype · Not for clinical use</div>
        </section>
      </div>
      <p className="system-footnote">Infrastructure safeguards must be validated server-side before deployment.</p>
    </div>
  );
}
