import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const WINDOW_MS = 60_000;
const MAX_API_REQUESTS_PER_WINDOW = 60;
const MAX_PAGE_REQUESTS_PER_WINDOW = 180;
const MAX_TRACKED_IPS = 2048;
const SESSION_COOKIE_NAME = "radar_auth_session";

const ipBuckets = new Map<string, number[]>();

function getClientIp(request: NextRequest): string {
  const forwarded = request.headers.get("x-forwarded-for");
  if (forwarded) {
    const first = forwarded.split(",")[0]?.trim();
    if (first) return first.slice(0, 64);
  }
  const realIp = request.headers.get("x-real-ip")?.trim();
  if (realIp) return realIp.slice(0, 64);
  return "127.0.0.1";
}

function checkEdgeRateLimit(
  key: string,
  limit: number
): { allowed: boolean; remaining: number; resetSeconds: number } {
  const now = Date.now();
  const cutoff = now - WINDOW_MS;

  if (!ipBuckets.has(key) && ipBuckets.size >= MAX_TRACKED_IPS) {
    const firstKey = ipBuckets.keys().next().value;
    if (firstKey) ipBuckets.delete(firstKey);
  }

  const timestamps = (ipBuckets.get(key) ?? []).filter((t) => t > cutoff);
  if (timestamps.length >= limit) {
    ipBuckets.set(key, timestamps);
    const oldest = timestamps[0] ?? now;
    const resetSeconds = Math.max(1, Math.ceil((WINDOW_MS - (now - oldest)) / 1000));
    return { allowed: false, remaining: 0, resetSeconds };
  }

  timestamps.push(now);
  ipBuckets.set(key, timestamps);
  const oldest = timestamps[0] ?? now;
  const resetSeconds = Math.max(1, Math.ceil((WINDOW_MS - (now - oldest)) / 1000));
  return {
    allowed: true,
    remaining: Math.max(0, limit - timestamps.length),
    resetSeconds,
  };
}

function applySecurityHeaders(
  response: NextResponse,
  pathname = ""
): NextResponse {
  const apiBase = (
    process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"
  ).replace(/\/+$/, "");

  const isDev = process.env.NODE_ENV !== "production";
  const devConnectSrc = isDev
    ? "ws: wss: http://localhost:* http://127.0.0.1:* ws://localhost:* ws://127.0.0.1:*"
    : "";

  const cspDirectives = [
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://apis.google.com https://accounts.google.com",
    "style-src 'self' 'unsafe-inline'",
    `img-src 'self' blob: data: ${apiBase} https://*.googleusercontent.com`,
    `connect-src 'self' ${apiBase} https://identitytoolkit.googleapis.com https://securetoken.googleapis.com https://accounts.google.com https://oauth2.googleapis.com ${devConnectSrc}`.trim(),
    "frame-src 'self' https://accounts.google.com https://*.firebaseapp.com",
    "frame-ancestors 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
  ].join("; ");

  response.headers.set("Content-Security-Policy", cspDirectives);
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  response.headers.set(
    "Permissions-Policy",
    "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
  );
  if (pathname === "/api/auth/oauth-callback") {
    response.headers.set("Cross-Origin-Opener-Policy", "unsafe-none");
  } else {
    response.headers.set("Cross-Origin-Opener-Policy", "same-origin-allow-popups");
  }
  if (process.env.NODE_ENV === "production") {
    response.headers.set(
      "Strict-Transport-Security",
      "max-age=63072000; includeSubDomains; preload"
    );
  }
  return response;
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (
    pathname.includes("..") ||
    pathname.toLowerCase().includes("%2e%2e") ||
    pathname.includes("\0")
  ) {
    return applySecurityHeaders(
      NextResponse.json({ detail: "Invalid request path" }, { status: 400 }),
      pathname
    );
  }

  const clientIp = getClientIp(request);
  const isApiRoute = pathname.startsWith("/api/");
  const limit = isApiRoute ? MAX_API_REQUESTS_PER_WINDOW : MAX_PAGE_REQUESTS_PER_WINDOW;
  const bucketKey = `${isApiRoute ? "api" : "page"}:${clientIp}`;
  const rate = checkEdgeRateLimit(bucketKey, limit);

  if (!rate.allowed) {
    const throttled = NextResponse.json(
      { detail: "Terlalu banyak permintaan. Silakan tunggu sebelum mencoba kembali." },
      {
        status: 429,
        headers: {
          "Retry-After": String(rate.resetSeconds),
          "X-RateLimit-Limit": String(limit),
          "X-RateLimit-Remaining": "0",
          "X-RateLimit-Reset": String(rate.resetSeconds),
        },
      }
    );
    return applySecurityHeaders(throttled, pathname);
  }

  const isPublicAuthRoute = pathname.startsWith("/api/auth/");
  const isLoginPage = pathname === "/login";
  const hasSessionCookie = request.cookies.has(SESSION_COOKIE_NAME);
  const isWebAuthEnforced =
    (process.env.NEXT_PUBLIC_REQUIRE_AUTH ?? "").trim().toLowerCase() === "true" ||
    (process.env.NEXT_PUBLIC_REQUIRE_AUTH ?? "").trim().toLowerCase() === "1" ||
    (process.env.NEXT_PUBLIC_REQUIRE_AUTH ?? "").trim().toLowerCase() === "yes";

  // If already authenticated and visiting /login, redirect to /
  if (isLoginPage && hasSessionCookie) {
    const destination = request.nextUrl.searchParams.get("redirect") || "/";
    return applySecurityHeaders(
      NextResponse.redirect(new URL(destination, request.url)),
      pathname
    );
  }

  // If unauthenticated and accessing protected application pages, force redirect to /login only if auth is required
  if (isWebAuthEnforced && !isApiRoute && !isPublicAuthRoute && !isLoginPage && !hasSessionCookie) {
    const loginUrl = new URL("/login", request.url);
    if (pathname !== "/") {
      loginUrl.searchParams.set("redirect", pathname);
    }
    return applySecurityHeaders(NextResponse.redirect(loginUrl), pathname);
  }

  const response = NextResponse.next();
  response.headers.set("X-RateLimit-Limit", String(limit));
  response.headers.set("X-RateLimit-Remaining", String(rate.remaining));
  response.headers.set("X-RateLimit-Reset", String(rate.resetSeconds));
  return applySecurityHeaders(response, pathname);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|fixtures/).*)"],
};
