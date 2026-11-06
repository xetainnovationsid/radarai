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
  const [detail, setDetail] = useState("Pemeriksaan API belum dijalankan.");
  const [authStatus, setAuthStatus] = useState<AuthStatusPayload | null>(null);
  const [rateInfo, setRateInfo] = useState<string>("Belum diperiksa");

  async function checkHealth() {
    setStatus("checking");
    setDetail(`Menghubungi ${API_BASE}/health dan /v1/auth/me…`);
    try {
      const response = await apiFetch("/health");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const health = (await response.json()) as { status?: string; environment?: string };

      const meResp = await apiFetch("/v1/auth/me");
      const limit = meResp.headers.get("X-RateLimit-Limit");
      const remaining = meResp.headers.get("X-RateLimit-Remaining");
      if (limit && remaining) {
        setRateInfo(`${remaining} / ${limit} req/menit tersisa`);
      }
      if (meResp.ok) {
        setAuthStatus((await meResp.json()) as AuthStatusPayload);
      }

      setStatus("online");
      setDetail(`API aktif · ${health.environment ?? "environment tidak diketahui"}`);
    } catch (error) {
      setStatus("offline");
      setDetail(error instanceof Error ? error.message : "API tidak dapat dihubungi.");
    }
  }

  return (
    <div className="dashboard-shell">
      <section className="dashboard-intro">
        <div>
          <p className="eyebrow">SYSTEM & SECURITY</p>
          <h1>Status layanan & keamanan</h1>
          <p className="lead">Konfigurasi konektivitas, autentikasi Firebase OAuth, dan lapisan proteksi aktif.</p>
        </div>
      </section>

      <section className="queue-panel system-panel">
        <div className="section-heading">
          <div>
            <p className="eyebrow">FASTAPI & SECURITY CHECK</p>
            <h2>Konektivitas backend & sesi</h2>
          </div>
          <button
            className="button-primary"
            type="button"
            disabled={status === "checking"}
            onClick={() => void checkHealth()}
          >
            {status === "checking" ? "Memeriksa…" : "Periksa API & Keamanan"}
          </button>
        </div>
        <div className="notice" role="status" aria-live="polite">{detail}</div>
        <dl className="study-metadata" style={{ marginTop: "1rem" }}>
          <div>
            <dt>Firebase OAuth (Web)</dt>
            <dd>{firebaseConfigured ? "Terkonfigurasi" : "Belum diatur di .env.local"}</dd>
          </div>
          <div>
            <dt>Sesi Peneliti</dt>
            <dd>{user ? `${user.email ?? user.uid} (${user.provider})` : "Belum login"}</dd>
          </div>
          <div>
            <dt>Mode Enforcement API</dt>
            <dd>
              {authStatus
                ? authStatus.auth_required
                  ? `Ketat (${authStatus.auth_method})`
                  : `Dev/Riset (${authStatus.auth_method})`
                : authRequired
                  ? "Wajib OAuth"
                  : "Opsional (Dev)"}
            </dd>
          </div>
          <div>
            <dt>Rate Limiter API</dt>
            <dd>{rateInfo}</dd>
          </div>
        </dl>
      </section>

      <section className="queue-panel system-panel">
        <p className="eyebrow">MODEL & CONTRACT</p><h2>Inference lokal per studi</h2>
        <p className="muted-copy">Viewer meminta skor dari checkpoint DenseNet121 lokal saat studi dibuka. Label checkpoint mengikuti anotasi irisan dataset RSNA ICH: 1 berarti hemorrhage dianotasi hadir, 0 berarti tidak ada anotasi positif. Skor tetap eksperimental, tidak terkalibrasi, dan tidak otomatis menjadi diagnosis atau temuan tersimpan.</p>
        <dl className="study-metadata"><div><dt>Kontrak API</dt><dd>v1.0.0</dd></div><div><dt>Provider model</dt><dd>Checkpoint lokal, status per lingkungan</dd></div><div><dt>Target label</dt><dd>RSNA ICH · anotasi perdarahan per irisan</dd></div><div><dt>Kegunaan</dt><dd>Riset saja</dd></div></dl>
      </section>

      <section className="queue-panel system-panel">
        <p className="eyebrow">SECURITY LAYERS</p>
        <h2>Lapisan proteksi aktif</h2>
        <p className="muted-copy">
          Aplikasi dilengkapi dengan verifikasi token Firebase OAuth / API Key, sliding-window rate limiting di Edge & FastAPI, validasi biner DICOM Part 10 & sanitasi tag PHI/PN/Overlay, serta header keamanan HTTP ketat (CSP, HSTS, X-Frame-Options, nosniff).
        </p>
        <dl className="study-metadata">
          <div><dt>Kontrak API</dt><dd>v1.0.0 (extra=forbid)</dd></div>
          <div><dt>Batas Unggah DICOM</dt><dd>Maks 64 MB/file · 512 MB/seri</dd></div>
          <div><dt>Proteksi Data</dt><dd>Cache-Control: private, no-store</dd></div>
          <div><dt>Kegunaan</dt><dd>Riset saja (bukan klinis)</dd></div>
        </dl>
      </section>
    </div>
  );
}

