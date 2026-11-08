"use client";

import Link from "next/link";
import { Suspense } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { useAuth } from "@/components/AuthContext";

const NAV_ITEMS = [
  { href: "/", label: "Workspace", icon: "/figma/f33da.svg" },
  { href: "/studies", label: "Studies", icon: "/figma/ed921.svg" },
  { href: "/studies?status=ready", label: "Review", icon: "/figma/d8e0f.svg" },
  { href: "/system", label: "System", icon: "/figma/0c433.svg" },
];

export function HeaderNav() {
  return (
    <Suspense fallback={<HeaderNavFallback />}>
      <HeaderNavContent />
    </Suspense>
  );
}

function HeaderNavFallback() {
  return (
    <header className="app-header" aria-hidden="true">
      <div className="header-inner">
        <span className="brand-group">
          <span className="brand-mark">R</span>
          <span className="brand-wordmark">radar <span>AI</span></span>
        </span>
      </div>
    </header>
  );
}

function HeaderNavContent() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { user, loading, signOut } = useAuth();
  const isLoginPage = pathname === "/login";
  const isStudyDetailPage = pathname.startsWith("/studies/") && pathname !== "/studies";
  const reviewQueueActive = searchParams.get("status") === "ready";

  if (isStudyDetailPage) return null;

  return (
    <header className="app-header">
      <div className="header-inner">
        <Link href={user ? "/" : "/login"} className="brand-group" aria-label="RADAR AI home">
          <span className="brand-mark" aria-hidden="true">R</span>
          <span className="brand-wordmark">radar <span>AI</span></span>
        </Link>

        {!isLoginPage && (
          <nav aria-label="Primary navigation">
            <ul className="nav-links">
              {NAV_ITEMS.map((item) => {
                const isActive = item.href === "/"
                  ? pathname === "/"
                  : item.href === "/system"
                    ? pathname.startsWith("/system")
                    : pathname.startsWith("/studies") && item.label === (reviewQueueActive ? "Review" : "Studies");
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className={`nav-link ${isActive ? "nav-link-active" : ""}`}
                      aria-current={isActive ? "page" : undefined}
                    >
                      <img src={item.icon} alt="" aria-hidden="true" />
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>
        )}

        {!isLoginPage && (
          <div className="header-meta">
            <span className="environment-label">Research environment</span>
            {loading ? (
              <span className="session-dot" role="status" aria-label="Memeriksa sesi" />
            ) : user ? (
              <div className="account-control">
                <span className="account-name" title={user.email ?? user.uid}>
                  {user.email ?? user.displayName ?? user.uid.slice(0, 8)}
                </span>
                <button
                  type="button"
                  className="user-avatar"
                  onClick={() => void signOut()}
                  aria-label="Keluar dari sesi peneliti"
                  title="Keluar"
                >
                  <img src="/figma/d06c2.svg" alt="" aria-hidden="true" />
                  <span>{(user.displayName ?? user.email ?? "ID").slice(0, 2).toUpperCase()}</span>
                </button>
              </div>
            ) : (
              <Link href="/login" className="user-avatar" aria-label="Masuk sebagai peneliti" title="Masuk">
                <img src="/figma/d06c2.svg" alt="" aria-hidden="true" />
                <span>ID</span>
              </Link>
            )}
          </div>
        )}
      </div>
    </header>
  );
}
