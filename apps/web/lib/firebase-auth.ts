/**
 * Firebase OAuth & Identity Toolkit Client for RADAR AI.
 *
 * Uses Firebase Auth REST APIs (Identity Toolkit v1 + Secure Token v1) and
 * Google OAuth2 popup flow with sessionStorage token isolation.
 */

export interface AuthUser {
  uid: string;
  email: string | null;
  displayName: string | null;
  photoUrl: string | null;
  emailVerified: boolean;
  idToken: string;
  refreshToken: string;
  expiresAt: number;
  provider: "google.com" | "password" | "dev_mode";
}

export interface FirebaseClientConfig {
  apiKey: string;
  authDomain: string;
  projectId: string;
  googleClientId: string;
}

const SESSION_STORAGE_KEY = "radar_ai_firebase_session_v1";

export function getFirebaseConfig(): FirebaseClientConfig {
  return {
    apiKey: (process.env.NEXT_PUBLIC_FIREBASE_API_KEY ?? "").trim(),
    authDomain: (process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN ?? "").trim(),
    projectId: (process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID ?? "").trim(),
    googleClientId: (process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ?? "").trim(),
  };
}

export function isFirebaseConfigured(): boolean {
  const cfg = getFirebaseConfig();
  return Boolean(cfg.apiKey && cfg.projectId);
}

export function isWebAuthRequired(): boolean {
  const raw = (process.env.NEXT_PUBLIC_REQUIRE_AUTH ?? "").trim().toLowerCase();
  return raw === "true" || raw === "1" || raw === "yes";
}

export function loadStoredSession(): AuthUser | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as AuthUser;
    if (!parsed?.uid || !parsed?.idToken || typeof parsed.expiresAt !== "number") {
      window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function saveStoredSession(user: AuthUser | null): void {
  if (typeof window === "undefined") return;
  try {
    if (!user) {
      window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
      return;
    }
    window.sessionStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(user));
  } catch {
    // Ignore storage quota errors in private browsing mode.
  }
}

async function syncServerCookie(idToken: string | null): Promise<void> {
  if (typeof window === "undefined") return;
  try {
    if (idToken) {
      await fetch("/api/auth/session", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest",
        },
        body: JSON.stringify({ idToken }),
      });
    } else {
      await fetch("/api/auth/session", {
        method: "DELETE",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
    }
  } catch {
    // Non-fatal if running in static export mode.
  }
}

export async function refreshFirebaseSession(user: AuthUser): Promise<AuthUser | null> {
  const { apiKey } = getFirebaseConfig();
  if (!apiKey || !user.refreshToken) return null;

  try {
    const response = await fetch(
      `https://securetoken.googleapis.com/v1/token?key=${encodeURIComponent(apiKey)}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          grant_type: "refresh_token",
          refresh_token: user.refreshToken,
        }),
      }
    );
    if (!response.ok) {
      saveStoredSession(null);
      await syncServerCookie(null);
      return null;
    }
    const data = (await response.json()) as {
      id_token: string;
      refresh_token: string;
      expires_in: string;
      user_id: string;
    };
    const expiresInSec = Number.parseInt(data.expires_in, 10) || 3600;
    const updated: AuthUser = {
      ...user,
      uid: data.user_id || user.uid,
      idToken: data.id_token,
      refreshToken: data.refresh_token || user.refreshToken,
      expiresAt: Date.now() + (expiresInSec - 60) * 1000,
    };
    saveStoredSession(updated);
    await syncServerCookie(updated.idToken);
    return updated;
  } catch {
    return null;
  }
}

export async function getValidIdToken(): Promise<string | null> {
  const session = loadStoredSession();
  if (!session) return null;
  if (Date.now() < session.expiresAt) {
    return session.idToken;
  }
  const refreshed = await refreshFirebaseSession(session);
  return refreshed?.idToken ?? null;
}

export async function signInWithEmailPassword(
  email: string,
  password: string
): Promise<AuthUser> {
  const { apiKey } = getFirebaseConfig();
  if (!apiKey) {
    throw new Error(
      "NEXT_PUBLIC_FIREBASE_API_KEY belum dikonfigurasi di environment aplikasi."
    );
  }

  const response = await fetch(
    `https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=${encodeURIComponent(apiKey)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: email.trim(),
        password,
        returnSecureToken: true,
      }),
    }
  );

  if (!response.ok) {
    const errBody = (await response.json().catch(() => ({}))) as {
      error?: { message?: string };
    };
    const code = errBody.error?.message ?? "AUTH_FAILED";
    if (
      code.includes("INVALID_LOGIN_CREDENTIALS") ||
      code.includes("INVALID_PASSWORD") ||
      code.includes("EMAIL_NOT_FOUND")
    ) {
      throw new Error("Email atau kata sandi tidak valid.");
    }
    if (code.includes("TOO_MANY_ATTEMPTS_TRY_LATER")) {
      throw new Error("Terlalu banyak percobaan login gagal. Coba lagi beberapa saat.");
    }
    throw new Error(`Autentikasi Firebase gagal (${code}).`);
  }

  const data = (await response.json()) as {
    localId: string;
    email: string;
    displayName?: string;
    idToken: string;
    refreshToken: string;
    expiresIn: string;
  };

  const expiresInSec = Number.parseInt(data.expiresIn, 10) || 3600;
  const user: AuthUser = {
    uid: data.localId,
    email: data.email || email.trim(),
    displayName: data.displayName || data.email.split("@")[0] || "Researcher",
    photoUrl: null,
    emailVerified: true,
    idToken: data.idToken,
    refreshToken: data.refreshToken,
    expiresAt: Date.now() + (expiresInSec - 60) * 1000,
    provider: "password",
  };
  saveStoredSession(user);
  await syncServerCookie(user.idToken);
  return user;
}

export async function exchangeGoogleTokenWithFirebase(
  googleIdTokenOrAccessToken: { idToken?: string; accessToken?: string }
): Promise<AuthUser> {
  const { apiKey } = getFirebaseConfig();
  if (!apiKey) {
    throw new Error(
      "NEXT_PUBLIC_FIREBASE_API_KEY belum dikonfigurasi di environment aplikasi."
    );
  }

  const postBodyParams = new URLSearchParams({ providerId: "google.com" });
  if (googleIdTokenOrAccessToken.idToken) {
    postBodyParams.set("id_token", googleIdTokenOrAccessToken.idToken);
  } else if (googleIdTokenOrAccessToken.accessToken) {
    postBodyParams.set("access_token", googleIdTokenOrAccessToken.accessToken);
  } else {
    throw new Error("Token OAuth Google tidak ditemukan.");
  }

  const requestUri =
    typeof window !== "undefined" ? window.location.origin : "http://localhost:3000";

  const response = await fetch(
    `https://identitytoolkit.googleapis.com/v1/accounts:signInWithIdp?key=${encodeURIComponent(apiKey)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        postBody: postBodyParams.toString(),
        requestUri,
        returnIdpCredential: true,
        returnSecureToken: true,
      }),
    }
  );

  if (!response.ok) {
    const errBody = (await response.json().catch(() => ({}))) as {
      error?: { message?: string };
    };
    throw new Error(
      `Gagal memverifikasi OAuth Google dengan Firebase (${errBody.error?.message ?? response.status}).`
    );
  }

  const data = (await response.json()) as {
    localId: string;
    email?: string;
    emailVerified?: boolean;
    displayName?: string;
    photoUrl?: string;
    idToken: string;
    refreshToken: string;
    expiresIn: string;
  };

  const expiresInSec = Number.parseInt(data.expiresIn, 10) || 3600;
  const user: AuthUser = {
    uid: data.localId,
    email: data.email ?? null,
    displayName: data.displayName ?? data.email ?? "Google Researcher",
    photoUrl: data.photoUrl ?? null,
    emailVerified: Boolean(data.emailVerified ?? true),
    idToken: data.idToken,
    refreshToken: data.refreshToken,
    expiresAt: Date.now() + (expiresInSec - 60) * 1000,
    provider: "google.com",
  };
  saveStoredSession(user);
  await syncServerCookie(user.idToken);
  return user;
}

export async function signInWithGooglePopup(): Promise<AuthUser> {
  const { googleClientId } = getFirebaseConfig();
  if (!googleClientId) {
    throw new Error(
      "NEXT_PUBLIC_GOOGLE_CLIENT_ID belum dikonfigurasi untuk Google OAuth popup."
    );
  }
  if (typeof window === "undefined") {
    throw new Error("Google OAuth hanya dapat dijalankan di browser.");
  }

  const stateBytes = new Uint8Array(16);
  window.crypto.getRandomValues(stateBytes);
  const state = Array.from(stateBytes, (b) => b.toString(16).padStart(2, "0")).join("");
  const nonceBytes = new Uint8Array(16);
  window.crypto.getRandomValues(nonceBytes);
  const nonce = Array.from(nonceBytes, (b) => b.toString(16).padStart(2, "0")).join("");

  const redirectUri = `${window.location.origin}/api/auth/oauth-callback`;
  const authUrl = new URL("https://accounts.google.com/o/oauth2/v2/auth");
  authUrl.searchParams.set("client_id", googleClientId);
  authUrl.searchParams.set("redirect_uri", redirectUri);
  authUrl.searchParams.set("response_type", "id_token token");
  authUrl.searchParams.set("scope", "openid email profile");
  authUrl.searchParams.set("nonce", nonce);
  authUrl.searchParams.set("state", state);
  authUrl.searchParams.set("prompt", "select_account");

  return new Promise<AuthUser>((resolve, reject) => {
    let popup: Window | null = null;
    let timeoutId = 0;
    let checkClosed = 0;
    let completed = false;

    function cleanup() {
      window.clearTimeout(timeoutId);
      window.clearInterval(checkClosed);
      window.removeEventListener("message", onMessage);
    }

    function finish(payload: {
      state?: string;
      idToken?: string;
      accessToken?: string;
      error?: string;
    }) {
      if (completed) return;
      completed = true;
      // The callback waits for this acknowledgement before closing. This avoids
      // racing the browser's popup.closed signal against the queued message.
      popup?.postMessage(
        { type: "RADAR_GOOGLE_OAUTH_ACK", state: payload.state ?? "" },
        window.location.origin
      );
      cleanup();
      if (payload.error) {
        reject(new Error(`Google OAuth gagal: ${payload.error}`));
        return;
      }
      if (payload.state !== state) {
        reject(new Error("Validasi CSRF state OAuth gagal."));
        return;
      }
      void exchangeGoogleTokenWithFirebase({
        idToken: payload.idToken,
        accessToken: payload.accessToken,
      }).then(resolve, reject);
    }

    function onMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin) return;
      if (popup && event.source !== popup) return;
      handlePayload(event.data);
    }

    function handlePayload(data: unknown) {
      const payload = data as {
        type?: string;
        state?: string;
        idToken?: string;
        accessToken?: string;
        error?: string;
      } | null;
      if (!payload || payload.type !== "RADAR_GOOGLE_OAUTH_RESULT") return;
      finish(payload);
    }

    // Register the receiver before opening the popup so a fast Google redirect
    // cannot post its result before the listener exists.
    window.addEventListener("message", onMessage);
    timeoutId = window.setTimeout(() => {
      cleanup();
      reject(
        new Error(
          "Google OAuth tidak mengembalikan respons. Pastikan domain dan redirect URI OAuth diizinkan."
        )
      );
    }, 120_000);

    popup = window.open(
      authUrl.toString(),
      "radar_google_oauth",
      "width=520,height=640,menubar=no,toolbar=no,location=no,status=no"
    );
    if (!popup) {
      cleanup();
      reject(new Error("Popup login diblokir oleh browser. Izinkan popup untuk situs ini."));
      return;
    }

    // The callback waits for an acknowledgement before closing, so a closed
    // window here means the user cancelled before the callback completed.
    if (!completed) {
      checkClosed = window.setInterval(() => {
        if (!completed && popup?.closed) {
          cleanup();
          reject(new Error("Jendela login Google ditutup sebelum selesai."));
        }
      }, 600);
    }
  });
}

export async function signOutFirebase(): Promise<void> {
  saveStoredSession(null);
  await syncServerCookie(null);
}

function base64UrlEncode(text: string): string {
  if (typeof window === "undefined") {
    return Buffer.from(text).toString("base64url");
  }
  return btoa(text).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
}

export async function signInWithDevAccount(
  email = "researcher@radar-ai.local",
  name = "Peneliti Riset RADAR AI"
): Promise<AuthUser> {
  const header = base64UrlEncode(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const payload = base64UrlEncode(
    JSON.stringify({
      sub: "local-dev-researcher",
      email,
      name,
      iat: Math.floor(Date.now() / 1000),
      exp: Math.floor(Date.now() / 1000) + 86400,
    })
  );
  const sig = base64UrlEncode("radar-local-dev-signature");
  const dummyJwt = `${header}.${payload}.${sig}`;

  const user: AuthUser = {
    uid: "local-dev-researcher",
    email,
    displayName: name,
    photoUrl: null,
    emailVerified: true,
    idToken: dummyJwt,
    refreshToken: "dev-refresh-token",
    expiresAt: Date.now() + 86400 * 1000,
    provider: "dev_mode",
  };
  saveStoredSession(user);
  await syncServerCookie(user.idToken);
  return user;
}


