"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import type { FormEvent } from "react";
import { useAuth } from "@/components/AuthContext";

function LoginForm() {
  const searchParams = useSearchParams();
  const redirectTarget = searchParams.get("redirect") || "/";
  const {
    user,
    loading,
    firebaseConfigured,
    signInWithGoogle,
    signInWithEmail,
    signInWithDev,
  } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [authError, setAuthError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleEmailSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAuthError("");
    setSubmitting(true);
    try {
      await signInWithEmail(email, password);
    } catch (err) {
      setAuthError(
        err instanceof Error ? err.message : "Gagal masuk dengan email."
      );
    } finally {
      setSubmitting(false);
    }
  }

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

  async function handleDevLogin() {
    setAuthError("");
    setSubmitting(true);
    try {
      await signInWithDev();
    } catch (err) {
      setAuthError(
        err instanceof Error ? err.message : "Gagal masuk dengan mode pengembang."
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (loading || user) {
    return (
      <div className="dashboard-shell" style={{ display: "grid", placeItems: "center", minHeight: "65vh" }}>
        <div style={{ textAlign: "center" }}>
          <div className="brand-mark" style={{ margin: "0 auto 1.25rem", width: "48px", height: "48px", fontSize: "1.5rem" }}>
            R
          </div>
          <h2>Memverifikasi kredensial peneliti…</h2>
          <p className="muted-copy">Menyiapkan workspace CT RADAR AI yang aman.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="dashboard-shell" style={{ maxWidth: "560px", margin: "2.5rem auto" }}>
      <section className="dashboard-intro" style={{ textAlign: "center", marginBottom: "1.5rem" }}>
        <p className="eyebrow" style={{ justifyContent: "center" }}>
          RADAR AI <span>RESEARCH WORKSPACE</span>
        </p>
        <h1 style={{ fontSize: "2rem", marginTop: "0.25rem" }}>Portal Autentikasi Peneliti</h1>
        <p className="lead" style={{ margin: "0.5rem auto 0" }}>
          Akses terbatas untuk peneliti terotorisasi. Masuk untuk membuka antrean studi CT dan analisis model.
        </p>
      </section>

      <div
        style={{
          background: "rgb(17 25 39 / 94%)",
          border: "1px solid var(--border-strong)",
          borderRadius: "14px",
          padding: "2rem",
          boxShadow: "0 18px 36px rgb(0 0 0 / 40%)",
        }}
      >
        <div style={{ display: "grid", gap: "0.75rem", marginBottom: "1.75rem" }}>
          <button
            type="button"
            className="button-primary"
            disabled={submitting || !firebaseConfigured}
            onClick={() => void handleGoogleLogin()}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: "0.75rem",
              padding: "0.85rem",
              fontSize: "0.95rem",
            }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
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
            Masuk dengan Google OAuth
          </button>

          {!firebaseConfigured && (
            <p className="muted-copy" style={{ textAlign: "center", fontSize: "0.78rem" }}>
              Google OAuth memerlukan <code>NEXT_PUBLIC_FIREBASE_API_KEY</code> di <code>.env.local</code>.
            </p>
          )}
        </div>

        <div
          style={{
            display: "flex",
            alignItems: "center",
            margin: "1.5rem 0",
            color: "var(--text-muted)",
            fontSize: "0.82rem",
          }}
        >
          <div style={{ flex: 1, height: "1px", background: "var(--border-subtle)" }} />
          <span style={{ padding: "0 0.85rem" }}>atau masuk dengan email terdaftar</span>
          <div style={{ flex: 1, height: "1px", background: "var(--border-subtle)" }} />
        </div>

        <form onSubmit={handleEmailSubmit} style={{ display: "grid", gap: "1.1rem" }}>
          <div>
            <label htmlFor="login-email" style={{ display: "block", fontSize: "0.85rem", marginBottom: "0.4rem" }}>
              Email Peneliti
            </label>
            <input
              id="login-email"
              type="email"
              required
              autoComplete="username"
              placeholder="peneliti@telkomuniversity.ac.id"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={{
                width: "100%",
                padding: "0.75rem 0.9rem",
                borderRadius: "8px",
                border: "1px solid var(--border-subtle)",
                background: "var(--bg-primary)",
                color: "var(--text-primary)",
                fontSize: "0.95rem",
              }}
            />
          </div>

          <div>
            <label htmlFor="login-password" style={{ display: "block", fontSize: "0.85rem", marginBottom: "0.4rem" }}>
              Kata Sandi
            </label>
            <input
              id="login-password"
              type="password"
              required
              autoComplete="current-password"
              placeholder="••••••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={{
                width: "100%",
                padding: "0.75rem 0.9rem",
                borderRadius: "8px",
                border: "1px solid var(--border-subtle)",
                background: "var(--bg-primary)",
                color: "var(--text-primary)",
                fontSize: "0.95rem",
              }}
            />
          </div>

          <button
            type="submit"
            className="button-primary"
            disabled={submitting || !firebaseConfigured}
            style={{ marginTop: "0.5rem", padding: "0.75rem" }}
          >
            {submitting ? "Memproses…" : "Masuk ke Workspace"}
          </button>
        </form>

        <div
          style={{
            marginTop: "2rem",
            paddingTop: "1.25rem",
            borderTop: "1px dashed var(--border-subtle)",
            textAlign: "center",
          }}
        >
          <p className="eyebrow" style={{ justifyContent: "center", marginBottom: "0.4rem" }}>
            KOLABORASI & PENGEMBANGAN TIM
          </p>
          <p className="muted-copy" style={{ fontSize: "0.82rem", marginBottom: "0.85rem" }}>
            Bekerja bareng rekan tim secara lokal tanpa setup kunci Firebase? Gunakan sesi pengembang:
          </p>
          <button
            type="button"
            className="button-secondary"
            disabled={submitting}
            onClick={() => void handleDevLogin()}
            style={{ width: "100%", padding: "0.65rem", fontSize: "0.88rem" }}
          >
            ⚡ Masuk Cepat sebagai Peneliti (Mode Dev/Demo)
          </button>
        </div>

        {authError && (
          <div className="notice notice-error" role="alert" style={{ marginTop: "1.25rem" }}>
            {authError}
          </div>
        )}

        {redirectTarget !== "/" && (
          <p className="muted-copy" style={{ textAlign: "center", fontSize: "0.78rem", marginTop: "1rem" }}>
            Setelah masuk, Anda akan diarahkan ke: <code>{redirectTarget}</code>
          </p>
        )}
      </div>

      <p className="research-note" style={{ textAlign: "center", marginTop: "1.5rem" }}>
        Alat bantu riset dan demonstrasi saja. Bukan untuk penggunaan klinis; seluruh hasil memerlukan evaluasi manusia.
      </p>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div
          className="dashboard-shell"
          style={{ display: "grid", placeItems: "center", minHeight: "65vh" }}
        >
          <div style={{ textAlign: "center" }}>
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
            <h2>Memuat halaman login…</h2>
          </div>
        </div>
      }
    >
      <LoginForm />
    </Suspense>
  );
}

