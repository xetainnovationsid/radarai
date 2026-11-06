import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const SESSION_COOKIE_NAME = "radar_auth_session";

function isValidJwtFormat(token: string): boolean {
  const parts = token.split(".");
  if (parts.length !== 3) return false;
  return parts.every((part) => /^[A-Za-z0-9_-]+$/.test(part) && part.length > 0);
}

export async function POST(request: NextRequest) {
  if (request.headers.get("x-requested-with") !== "XMLHttpRequest") {
    return NextResponse.json(
      { detail: "Missing required CSRF protection header" },
      { status: 403 }
    );
  }

  let body: { idToken?: unknown };
  try {
    body = (await request.json()) as { idToken?: unknown };
  } catch {
    return NextResponse.json({ detail: "Invalid JSON payload" }, { status: 400 });
  }

  const idToken = typeof body.idToken === "string" ? body.idToken.trim() : "";
  if (!idToken || idToken.length > 4096 || !isValidJwtFormat(idToken)) {
    return NextResponse.json({ detail: "Invalid ID token format" }, { status: 400 });
  }

  const response = NextResponse.json({ status: "ok" });
  const isProd = process.env.NODE_ENV === "production";
  response.cookies.set({
    name: SESSION_COOKIE_NAME,
    value: "authenticated",
    httpOnly: true,
    secure: isProd,
    sameSite: "lax",
    path: "/",
    maxAge: 3600,
  });
  return response;
}

export async function DELETE(request: NextRequest) {
  if (request.headers.get("x-requested-with") !== "XMLHttpRequest") {
    return NextResponse.json(
      { detail: "Missing required CSRF protection header" },
      { status: 403 }
    );
  }
  const response = NextResponse.json({ status: "signed_out" });
  response.cookies.delete(SESSION_COOKIE_NAME);
  return response;
}

