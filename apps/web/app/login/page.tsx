"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { useAuth } from "@/components/AuthContext";

function LoginForm() {
  const searchParams = useSearchParams();
  const redirectTarget = searchParams.get("redirect") || "/";
  const {
    user,
    loading,
    firebaseConfigured,
    signInWithGoogle,
  } = useAuth();

  const [authError, setAuthError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleGoogleLogin() {
    setAuthError("");
    setSubmitting(true);
    try {
      await signInWithGoogle();
    } catch (err) {
      setAuthError(
        err instanceof Error ? err.message : "Gagal masuk dengan Google OAuth."
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (loading || user) {
    return (
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          minHeight: "calc(100vh - 160px)",
          padding: "2rem 1.5rem",
        }}
      >
        <div
          style={{
            background: "var(--bg-surface)",
            border: "1px solid var(--border-subtle)",
            borderRadius: "20px",
            padding: "2.75rem 2.25rem",
            maxWidth: "420px",
            width: "100%",
            textAlign: "center",
            boxShadow: "0 10px 30px rgba(18, 32, 29, 0.04)",
          }}
        >
          <div
            className="brand-mark"
            style={{
              margin: "0 auto 1.25rem",
              width: "48px",
              height: "48px",
              fontSize: "1.5rem",
            }}
          >
            R
          </div>
          <h2
            style={{
              fontFamily: "var(--font-display)",
              fontSize: "1.35rem",
              fontWeight: 700,
              color: "var(--text-primary)",
              margin: "0 0 0.5rem",
              letterSpacing: "-0.02em",
            }}
          >
            Memverifikasi Sesi…
          </h2>
          <p
            style={{
              color: "var(--text-muted)",
              fontSize: "0.85rem",
              margin: 0,
              lineHeight: 1.5,
            }}
          >
            Menyiapkan akses aman ke workspace penelitian CT RADAR AI.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        minHeight: "calc(100vh - 160px)",
        padding: "2rem 1.5rem",
      }}
    >
      <div
        style={{
          maxWidth: "440px",
          width: "100%",
        }}
      >
        <div
          style={{
            background: "var(--bg-surface)",
            border: "1px solid var(--border-subtle)",
            borderRadius: "20px",
            padding: "2.75rem 2.25rem 2rem",
            boxShadow: "0 12px 36px rgba(18, 32, 29, 0.05), 0 2px 6px rgba(18, 32, 29, 0.02)",
            textAlign: "center",
          }}
        >
          {/* Brand Eyebrow */}
          <div
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              background: "var(--accent-subtle)",
              color: "var(--accent-primary-hover)",
              padding: "4px 12px",
              borderRadius: "999px",
              fontSize: "0.68rem",
              fontWeight: 700,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
              marginBottom: "1.25rem",
            }}
          >
            <span style={{ fontSize: "0.55rem" }}>●</span> Portal Peneliti
          </div>

          <div
            className="brand-mark"
            style={{
              margin: "0 auto 1.25rem",
              width: "48px",
              height: "48px",
              fontSize: "1.5rem",
            }}
          >
            R
          </div>

          <h1
            style={{
              fontFamily: "var(--font-display)",
              fontSize: "1.6rem",
              fontWeight: 700,
              color: "var(--text-primary)",
              letterSpacing: "-0.03em",
              margin: "0 0 0.5rem",
              lineHeight: 1.25,
            }}
          >
            Masuk ke Workspace
          </h1>

          <p
            style={{
              color: "var(--text-secondary)",
              fontSize: "0.85rem",
              lineHeight: 1.55,
              margin: "0 auto 2rem",
              maxWidth: "340px",
            }}
          >
            Akses platform inferensi CT scan toraks dan visualisasi studi klinis terotorisasi.
          </p>

          {/* Action Button */}
          <div style={{ display: "grid", gap: "0.85rem" }}>
            <button
              type="button"
              disabled={submitting || !firebaseConfigured}
              onClick={() => void handleGoogleLogin()}
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "0.75rem",
                width: "100%",
                padding: "0.85rem 1.25rem",
                fontSize: "0.925rem",
                fontWeight: 600,
                fontFamily: "var(--font-sans)",
                color: "var(--text-primary)",
                background: "var(--bg-surface)",
                border: "1px solid var(--border-strong)",
                borderRadius: "12px",
                cursor: submitting || !firebaseConfigured ? "not-allowed" : "pointer",
                boxShadow: "0 2px 4px rgba(18, 32, 29, 0.04)",
                transition: "all 0.18s ease",
                opacity: submitting ? 0.7 : 1,
              }}
              onMouseEnter={(e) => {
                if (!submitting && firebaseConfigured) {
                  e.currentTarget.style.borderColor = "var(--accent-primary)";
                  e.currentTarget.style.background = "var(--bg-surface-elevated)";
                  e.currentTarget.style.transform = "translateY(-1px)";
                  e.currentTarget.style.boxShadow = "0 4px 10px rgba(18, 32, 29, 0.08)";
                }
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = "var(--border-strong)";
                e.currentTarget.style.background = "var(--bg-surface)";
                e.currentTarget.style.transform = "translateY(0)";
                e.currentTarget.style.boxShadow = "0 2px 4px rgba(18, 32, 29, 0.04)";
              }}
            >
              <svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" style={{ flexShrink: 0 }}>
                <path
                  fill="#EA4335"
                  d="M12 5c1.6 0 3 .6 4.1 1.7l3.1-3.1C17.3 1.8 14.8 1 12 1 7.5 1 3.7 3.6 1.9 7.3l3.7 2.9C6.5 7.4 9 5 12 5z"
                />
                <path
                  fill="#4285F4"
                  d="M23.5 12.3c0-.8-.1-1.7-.2-2.3H12v4.6h6.5c-.3 1.5-1.1 2.8-2.4 3.7l3.7 2.9c2.2-2 3.7-5 3.7-8.9z"
                />
                <path
                  fill="#FBBC05"
                  d="M5.6 14.8c-.2-.7-.4-1.5-.4-2.3 0-.8.1-1.6.4-2.3L1.9 7.3C.7 9.7 0 10.8 0 12s.7 2.3 1.9 4.7l3.7-1.9z"
                />
                <path
                  fill="#34A853"
                  d="M12 23c3.2 0 6-1.1 8-3l-3.7-2.9c-1.1.7-2.5 1.2-4.3 1.2-3 0-5.5-2.4-6.4-5.2L1.9 16c1.8 3.7 5.6 7 10.1 7z"
                />
              </svg>
              <span>{submitting ? "Menghubungkan ke Google…" : "Lanjutkan dengan Google"}</span>
            </button>

            {!firebaseConfigured && (
              <div
                style={{
                  background: "var(--status-warning-bg)",
                  border: "1px solid var(--status-warning-border)",
                  color: "var(--status-warning-text)",
                  borderRadius: "10px",
                  padding: "0.75rem 1rem",
                  fontSize: "0.78rem",
                  lineHeight: 1.45,
                  textAlign: "center",
                }}
              >
                Kunci Firebase belum terpasang. Atur <code>NEXT_PUBLIC_FIREBASE_API_KEY</code> di <code>.env.local</code>.
              </div>
            )}
          </div>

          {/* Error Notice */}
          {authError && (
            <div
              style={{
                marginTop: "1.25rem",
                padding: "0.75rem 1rem",
                borderRadius: "10px",
                background: "var(--status-danger-bg)",
                border: "1px solid var(--status-danger-border)",
                color: "var(--status-danger-text)",
                fontSize: "0.8rem",
                lineHeight: 1.45,
                textAlign: "left",
              }}
              role="alert"
            >
              {authError}
            </div>
          )}

          {/* Redirect Hint */}
          {redirectTarget !== "/" && (
            <p
              style={{
                margin: "1.25rem 0 0",
                color: "var(--text-muted)",
                fontSize: "0.75rem",
              }}
            >
              Diarahkan ke: <code style={{ fontFamily: "var(--font-mono)", background: "var(--bg-canvas)", padding: "2px 6px", borderRadius: "4px" }}>{redirectTarget}</code>
            </p>
          )}

          {/* Card Footer */}
          <div
            style={{
              marginTop: "2rem",
              paddingTop: "1.25rem",
              borderTop: "1px solid var(--border-subtle)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "6px",
              color: "var(--text-muted)",
              fontSize: "0.72rem",
            }}
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
            <span>Autentikasi aman melalui Google OAuth</span>
          </div>
        </div>

        {/* Clinical Disclaimer */}
        <p
          className="research-note"
          style={{
            textAlign: "center",
            marginTop: "1.75rem",
            fontSize: "0.72rem",
            color: "var(--text-muted)",
            lineHeight: 1.5,
          }}
        >
          Platform riset akademis Telkom University. Seluruh visualisasi dan inferensi model memerlukan evaluasi profesional.
        </p>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            minHeight: "calc(100vh - 160px)",
            padding: "2rem 1.5rem",
          }}
        >
          <div
            style={{
              background: "var(--bg-surface)",
              border: "1px solid var(--border-subtle)",
              borderRadius: "20px",
              padding: "2.75rem 2.25rem",
              maxWidth: "420px",
              width: "100%",
              textAlign: "center",
              boxShadow: "0 10px 30px rgba(18, 32, 29, 0.04)",
            }}
          >
            <div
              className="brand-mark"
              style={{
                margin: "0 auto 1.25rem",
                width: "48px",
                height: "48px",
                fontSize: "1.5rem",
              }}
            >
              R
            </div>
            <h2
              style={{
                fontFamily: "var(--font-display)",
                fontSize: "1.35rem",
                fontWeight: 700,
                color: "var(--text-primary)",
                margin: "0 0 0.5rem",
                letterSpacing: "-0.02em",
              }}
            >
              Memuat Halaman…
            </h2>
          </div>
        </div>
      }
    >
      <LoginForm />
    </Suspense>
  );
}
