"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "@/components/AuthContext";

const NAV_ITEMS = [
  { href: "/", label: "Triage Dashboard" },
  { href: "/system", label: "System & Security Status" },
];

export function HeaderNav() {
  const pathname = usePathname();
  const { user, loading, signOut } = useAuth();
  const isLoginPage = pathname === "/login";

  return (
    <header className="app-header">
      <div className="header-inner">
        <div className="brand-group">
          <Link href={user ? "/" : "/login"} className="brand-group" aria-label="RADAR AI Home">
            <div className="brand-mark" aria-hidden="true">
              R
            </div>
            <div>
              <span className="brand-title">
                RADAR AI
                <span className="badge badge-neutral mono">CT Research</span>
              </span>
              <span className="brand-subtitle">
                Brain CT Review Assistance • Meta AI Hackathon 2026
              </span>
            </div>
          </Link>
        </div>

        {!isLoginPage && user && (
          <nav aria-label="Primary navigation">
            <ul className="nav-links">
              {NAV_ITEMS.map((item) => {
                const isActive =
                  item.href === "/"
                    ? pathname === "/"
                    : pathname.startsWith(item.href.split("/").slice(0, 2).join("/"));
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className={`nav-link ${isActive ? "nav-link-active" : ""}`}
                      aria-current={isActive ? "page" : undefined}
                    >
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>
        )}

        <div className="header-meta">
          {loading ? (
            <span className="badge badge-neutral">Memeriksa sesi…</span>
          ) : user ? (
            <>
              <span className="badge badge-neutral" title={user.email ?? user.uid}>
                {user.provider === "dev_mode" ? "Dev" : "OAuth"}:{" "}
                {user.email ?? user.displayName ?? user.uid.slice(0, 8)}
              </span>
              <button
                type="button"
                className="button-secondary"
                onClick={() => void signOut()}
              >
                Keluar
              </button>
            </>
          ) : isLoginPage ? (
            <span className="badge badge-neutral">Autentikasi Diperlukan</span>
          ) : (
            <Link href="/login" className="button-primary">
              Masuk
            </Link>
          )}
          <span>Research prototype</span>
        </div>
      </div>
    </header>
  );
}
