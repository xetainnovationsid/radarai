"use client";

import { usePathname, useRouter } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";
import {
  isFirebaseConfigured,
  isWebAuthRequired,
  loadStoredSession,
  refreshFirebaseSession,
  signInWithDevAccount,
  signInWithEmailPassword,
  signInWithGooglePopup,
  signOutFirebase,
} from "@/lib/firebase-auth";
import type { AuthUser } from "@/lib/firebase-auth";

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  firebaseConfigured: boolean;
  authRequired: boolean;
  signInWithGoogle: () => Promise<void>;
  signInWithEmail: (email: string, password: string) => Promise<void>;
  signInWithDev: (email?: string, name?: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const firebaseConfigured = isFirebaseConfigured();
  const authRequired = isWebAuthRequired();

  useEffect(() => {
    let ignore = false;
    async function restoreSession() {
      const stored = loadStoredSession();
      if (!stored) {
        if (!ignore) setLoading(false);
        return;
      }
      if (Date.now() < stored.expiresAt) {
        if (!ignore) {
          setUser(stored);
          setLoading(false);
        }
        return;
      }
      const refreshed = await refreshFirebaseSession(stored);
      if (!ignore) {
        setUser(refreshed);
        setLoading(false);
      }
    }
    void restoreSession();
    return () => {
      ignore = true;
    };
  }, []);

  const signInWithGoogle = useCallback(async () => {
    const signedIn = await signInWithGooglePopup();
    setUser(signedIn);
  }, []);

  const signInWithEmail = useCallback(async (email: string, password: string) => {
    const signedIn = await signInWithEmailPassword(email, password);
    setUser(signedIn);
  }, []);

  const signInWithDev = useCallback(async (email?: string, name?: string) => {
    const signedIn = await signInWithDevAccount(email, name);
    setUser(signedIn);
  }, []);

  const signOut = useCallback(async () => {
    await signOutFirebase();
    setUser(null);
    router.push("/login");
  }, [router]);

  // Client-side route protection:
  useEffect(() => {
    if (loading) return;
    const isLoginPage = pathname === "/login";
    const isPublic = pathname.startsWith("/api/auth/");

    if (authRequired && !user && !isLoginPage && !isPublic) {
      const redirectUrl =
        pathname === "/"
          ? "/login"
          : `/login?redirect=${encodeURIComponent(pathname)}`;
      router.replace(redirectUrl);
    } else if (user && isLoginPage) {
      if (typeof window !== "undefined") {
        const params = new URLSearchParams(window.location.search);
        const destination = params.get("redirect") || "/";
        router.replace(destination);
      } else {
        router.replace("/");
      }
    }
  }, [user, loading, pathname, router, authRequired]);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      loading,
      firebaseConfigured,
      authRequired,
      signInWithGoogle,
      signInWithEmail,
      signInWithDev,
      signOut,
    }),
    [
      user,
      loading,
      firebaseConfigured,
      authRequired,
      signInWithGoogle,
      signInWithEmail,
      signInWithDev,
      signOut,
    ]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth harus digunakan di dalam AuthProvider.");
  }
  return ctx;
}
