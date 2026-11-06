"""Authentication, rate limiting, and HTTP security layers for the RADAR AI API."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Any, Literal
from uuid import uuid4

import httpx
from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger("radar_api.http")

AuthMethod = Literal[
    "firebase_jwt",
    "firebase_lookup",
    "api_key",
    "hmac_session",
    "local_dev",
]

_SAFE_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_SAFE_REVIEWER_RE = re.compile(r"[^A-Za-z0-9@._:-]+")
_bearer_scheme = HTTPBearer(auto_error=False)
_api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)

# Short-lived cache for verified Firebase ID tokens: sha256(token) -> (Principal, expires_at_epoch)
_TOKEN_CACHE: dict[str, tuple[Principal, float]] = {}
_TOKEN_CACHE_LOCK = Lock()
_MAX_TOKEN_CACHE_SIZE = 1024
_CUSTOM_TOKEN_VERIFIER: Callable[[str], Principal | None] | None = None


@dataclass(frozen=True)
class Principal:
    """Authenticated caller identity used for authorization and audit logging."""

    subject: str
    auth_method: AuthMethod
    email: str | None = None
    uid: str | None = None

    @property
    def reviewer_id(self) -> str:
        """Return a sanitized identifier guaranteed to fit the 64-char DB column."""
        candidate = self.email or self.subject or "local-reviewer"
        cleaned = _SAFE_REVIEWER_RE.sub("_", candidate.strip())
        if not cleaned:
            return "local-reviewer"
        return cleaned[:64]


def set_custom_token_verifier(
    verifier: Callable[[str], Principal | None] | None,
) -> None:
    """Register or clear a custom token verifier (used by unit tests)."""
    global _CUSTOM_TOKEN_VERIFIER
    _CUSTOM_TOKEN_VERIFIER = verifier
    with _TOKEN_CACHE_LOCK:
        _TOKEN_CACHE.clear()


def is_production_env() -> bool:
    return os.getenv("RADAR_ENV", "development").strip().lower() == "production"


def is_auth_required() -> bool:
    """Determine whether authentication is strictly enforced on API endpoints."""
    configured = os.getenv("RADAR_AUTH_REQUIRED", "").strip().lower()
    if configured in {"1", "true", "yes", "on"}:
        return True
    if configured in {"0", "false", "no", "off"}:
        return False
    return is_production_env()


def allowed_web_origins() -> list[str]:
    """Return validated CORS origins; reject wildcard '*' in production."""
    raw = os.getenv(
        "RADAR_WEB_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    )
    origins = [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]
    if is_production_env() and "*" in origins:
        raise RuntimeError("Wildcard '*' in RADAR_WEB_ORIGINS is forbidden in production")
    return origins


def _configured_api_keys() -> list[str]:
    raw = os.getenv("RADAR_API_KEYS", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _configured_allowed_domains() -> set[str]:
    raw = os.getenv("RADAR_ALLOWED_EMAIL_DOMAINS", "")
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _verify_api_key(candidate: str) -> Principal | None:
    keys = _configured_api_keys()
    for index, expected in enumerate(keys):
        if hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8")):
            return Principal(
                subject=f"api-key-{index + 1}",
                auth_method="api_key",
            )
    return None


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode((segment + padding).encode("ascii"))


def create_hmac_session_token(
    subject: str,
    *,
    secret_key: str,
    email: str | None = None,
    ttl_seconds: int = 3600,
) -> str:
    """Create an HS256 token signed with RADAR_API_SECRET_KEY."""
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + ttl_seconds,
        "iss": "radar-ai-session",
    }
    if email:
        payload["email"] = email
    header_bytes = json.dumps(header, separators=(",", ":")).encode()
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode()
    h_b64 = base64.urlsafe_b64encode(header_bytes).rstrip(b"=")
    p_b64 = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=")
    signing_input = h_b64 + b"." + p_b64
    signature = hmac.new(secret_key.encode("utf-8"), signing_input, hashlib.sha256).digest()
    s_b64 = base64.urlsafe_b64encode(signature).rstrip(b"=")
    return (signing_input + b"." + s_b64).decode("ascii")


def _verify_hmac_token(token: str) -> Principal | None:
    secret = os.getenv("RADAR_API_SECRET_KEY", "").strip()
    if not secret or len(secret) < 16:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        header = json.loads(_b64url_decode(parts[0]).decode("utf-8"))
        if header.get("alg") != "HS256":
            return None
        signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
        expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        actual_sig = _b64url_decode(parts[2])
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None
        payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
    except (ValueError, KeyError, UnicodeDecodeError):
        return None

    now = int(time.time())
    exp = payload.get("exp")
    iat = payload.get("iat")
    sub = str(payload.get("sub", "")).strip()
    if not isinstance(exp, (int, float)) or exp < now - 15:
        return None
    if not isinstance(iat, (int, float)) or iat > now + 30:
        return None
    if not sub:
        return None
    email = str(payload.get("email", "")).strip() or None
    if email and not _email_domain_allowed(email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email domain is not authorized for this workspace",
        )
    return Principal(
        subject=sub[:64],
        auth_method="hmac_session",
        email=email,
        uid=sub[:64],
    )


def _verify_dev_token(token: str) -> Principal | None:
    if is_production_env():
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        header = json.loads(_b64url_decode(parts[0]).decode("utf-8"))
        payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
        sig = parts[2].rstrip("=")
        expected_sig = (
            base64.urlsafe_b64encode(b"radar-local-dev-signature")
            .decode("ascii")
            .rstrip("=")
        )
        if (
            header.get("alg") == "HS256"
            and payload.get("sub") == "local-dev-researcher"
            and sig == expected_sig
        ):
            now = time.time()
            exp = payload.get("exp", 0)
            if isinstance(exp, (int, float)) and exp > now:
                email = str(payload.get("email", "researcher@radar-ai.local")).strip() or None
                return Principal(
                    subject="local-dev-researcher",
                    auth_method="local_dev",
                    email=email,
                    uid="local-dev-researcher",
                )
    except Exception:
        return None
    return None


def _email_domain_allowed(email: str) -> bool:
    allowed = _configured_allowed_domains()
    if not allowed:
        return True
    if "@" not in email:
        return False
    domain = email.rsplit("@", 1)[-1].lower()
    return domain in allowed


def _validate_firebase_jwt_claims(token: str) -> tuple[dict[str, Any], float]:
    """Validate unverified Firebase JWT structure and standard claims before remote lookup."""
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token format",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        header = json.loads(_b64url_decode(parts[0]).decode("utf-8"))
        payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed JWT token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error

    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid JWT token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if header.get("alg") != "RS256" or not header.get("kid"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unsupported JWT signature algorithm",
            headers={"WWW-Authenticate": "Bearer"},
        )

    now = time.time()
    exp = payload.get("exp")
    iat = payload.get("iat")
    sub = str(payload.get("sub", "")).strip()
    if not isinstance(exp, (int, float)) or exp <= now - 30:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not isinstance(iat, (int, float)) or iat > now + 60:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token issue time is invalid",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not sub or len(sub) > 128:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token subject is missing",
            headers={"WWW-Authenticate": "Bearer"},
        )

    project_id = (
        os.getenv("FIREBASE_PROJECT_ID", "").strip()
        or os.getenv("NEXT_PUBLIC_FIREBASE_PROJECT_ID", "").strip()
    )
    if project_id:
        expected_issuer = f"https://securetoken.google.com/{project_id}"
        if payload.get("iss") != expected_issuer or payload.get("aud") != project_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication token issuer or audience mismatch",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return payload, float(exp)


def _verify_firebase_token(token: str) -> Principal:
    """Verify a Firebase OAuth ID token using cache, custom verifier, or Firebase/Google APIs."""
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = time.time()
    with _TOKEN_CACHE_LOCK:
        cached = _TOKEN_CACHE.get(token_hash)
        if cached is not None:
            principal, expires_at = cached
            if expires_at > now:
                return principal
            _TOKEN_CACHE.pop(token_hash, None)

    if _CUSTOM_TOKEN_VERIFIER is not None:
        verified = _CUSTOM_TOKEN_VERIFIER(token)
        if verified is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if verified.email and not _email_domain_allowed(verified.email):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Email domain is not authorized for this workspace",
            )
        return verified

    claims, exp = _validate_firebase_jwt_claims(token)
    firebase_api_key = (
        os.getenv("FIREBASE_WEB_API_KEY", "").strip()
        or os.getenv("NEXT_PUBLIC_FIREBASE_API_KEY", "").strip()
    )

    uid = str(claims["sub"]).strip()
    email = str(claims.get("email", "")).strip() or None
    email_verified = bool(claims.get("email_verified", False))

    try:
        if firebase_api_key:
            response = httpx.post(
                f"https://identitytoolkit.googleapis.com/v1/accounts:lookup?key={firebase_api_key}",
                json={"idToken": token},
                timeout=4.0,
            )
            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Firebase ID token verification failed",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            users = response.json().get("users") or []
            if not users or users[0].get("localId") != uid:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Firebase user account not found or mismatched",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            if users[0].get("disabled"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User account is disabled",
                )
            email = users[0].get("email") or email
            email_verified = bool(users[0].get("emailVerified", email_verified))
            auth_method: AuthMethod = "firebase_lookup"
        else:
            response = httpx.get(
                "https://oauth2.googleapis.com/tokeninfo",
                params={"id_token": token},
                timeout=4.0,
            )
            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Google OAuth token verification failed",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            info = response.json()
            if info.get("sub") != uid:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token subject mismatch",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            email = info.get("email") or email
            email_verified = str(info.get("email_verified", "")).lower() == "true" or email_verified
            auth_method = "firebase_jwt"
    except httpx.HTTPError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Identity provider verification service is temporarily unreachable",
        ) from error

    require_verified = os.getenv("RADAR_REQUIRE_VERIFIED_EMAIL", "true").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if email and require_verified and not email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email address must be verified before accessing RADAR AI",
        )
    if email and not _email_domain_allowed(email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email domain is not authorized for this workspace",
        )

    principal = Principal(
        subject=f"firebase:{uid}"[:64],
        auth_method=auth_method,
        email=email,
        uid=uid[:64],
    )
    cache_until = min(exp, now + 300.0)
    with _TOKEN_CACHE_LOCK:
        if len(_TOKEN_CACHE) >= _MAX_TOKEN_CACHE_SIZE:
            _TOKEN_CACHE.clear()
        _TOKEN_CACHE[token_hash] = (principal, cache_until)
    return principal


def require_authenticated_principal(
    request: Request,
    bearer: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    api_key: str | None = Depends(_api_key_scheme),
) -> Principal:
    """Authenticate an API caller via API key, HMAC session, or Firebase OAuth token."""
    raw_auth_header = request.headers.get("authorization", "").strip()
    if raw_auth_header and bearer is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must use Bearer scheme",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if api_key is not None:
        verified_key = _verify_api_key(api_key.strip())
        if verified_key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )
        return verified_key

    if bearer is not None:
        token = bearer.credentials.strip()
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Empty bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        verified_key = _verify_api_key(token)
        if verified_key is not None:
            return verified_key

        verified_hmac = _verify_hmac_token(token)
        if verified_hmac is not None:
            return verified_hmac

        verified_dev = _verify_dev_token(token)
        if verified_dev is not None:
            return verified_dev

        return _verify_firebase_token(token)

    if is_auth_required():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Authentication required. Sign in with Firebase OAuth "
                "or provide a valid API token."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    return Principal(subject="local-reviewer", auth_method="local_dev")


def _extract_client_ip(request: Request) -> str:
    trust_proxy = os.getenv("RADAR_TRUST_PROXY_HEADERS", "false").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if trust_proxy:
        forwarded_for = request.headers.get("x-forwarded-for", "")
        if forwarded_for:
            first_ip = forwarded_for.split(",")[0].strip()
            if first_ip:
                return first_ip[:64]
        real_ip = request.headers.get("x-real-ip", "").strip()
        if real_ip:
            return real_ip[:64]
    if request.client and request.client.host:
        return request.client.host[:64]
    return "unknown"


class SlidingWindowRateLimiter:
    """Thread-safe, bounded-memory sliding-window rate limiter."""

    def __init__(self, max_keys: int = 4096) -> None:
        self._max_keys = max_keys
        self._buckets: dict[str, deque[float]] = {}
        self._lock = Lock()

    def clear(self) -> None:
        with self._lock:
            self._buckets.clear()

    def check(
        self, key: str, *, limit: int, window_seconds: float = 60.0
    ) -> tuple[bool, int, int]:
        """Return (allowed, remaining, retry_after_seconds)."""
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            if key not in self._buckets and len(self._buckets) >= self._max_keys:
                stale_keys = [
                    k
                    for k, timestamps in self._buckets.items()
                    if not timestamps or timestamps[-1] <= cutoff
                ]
                for stale in stale_keys:
                    self._buckets.pop(stale, None)
                if len(self._buckets) >= self._max_keys:
                    oldest_key = next(iter(self._buckets))
                    self._buckets.pop(oldest_key, None)

            bucket = self._buckets.setdefault(key, deque())
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= limit:
                retry_after = max(1, int(window_seconds - (now - bucket[0])) + 1)
                return False, 0, retry_after

            bucket.append(now)
            remaining = max(0, limit - len(bucket))
            reset_seconds = max(1, int(window_seconds - (now - bucket[0])))
            return True, remaining, reset_seconds


rate_limiter = SlidingWindowRateLimiter()


def _rate_limit_for_request(path: str, method: str) -> tuple[str, int] | None:
    if not path.startswith("/v1/"):
        return None
    if method == "OPTIONS":
        return None

    def _env_int(name: str, default: int) -> int:
        raw = os.getenv(name, "").strip()
        if not raw:
            return default
        try:
            value = int(raw)
            return value if value > 0 else default
        except ValueError:
            return default

    if method == "POST" and (path == "/v1/studies" or path.endswith("/dicom")):
        return "upload", _env_int("RADAR_UPLOAD_RATE_LIMIT_PER_MINUTE", 20)
    if method == "POST" and path.endswith("/inference-jobs"):
        return "inference", _env_int("RADAR_INFERENCE_RATE_LIMIT_PER_MINUTE", 30)
    if method == "GET" and (path.endswith("/scores") or path.endswith("/localizations")):
        return "inference", _env_int("RADAR_INFERENCE_RATE_LIMIT_PER_MINUTE", 30)
    return "general", _env_int("RADAR_RATE_LIMIT_PER_MINUTE", 120)


class SecurityAndRateLimitMiddleware(BaseHTTPMiddleware):
    """Apply HTTP security headers, request path sanitization, and sliding-window rate limits."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Any:
        incoming_req_id = request.headers.get("x-request-id", "").strip()
        request_id = (
            incoming_req_id
            if _SAFE_REQUEST_ID_RE.match(incoming_req_id)
            else str(uuid4())
        )

        raw_path = request.url.path
        lower_path = raw_path.lower()
        if (
            ".." in raw_path
            or "%2e%2e" in lower_path
            or "\x00" in raw_path
            or "%00" in lower_path
        ):
            response = JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"detail": "Invalid request path"},
            )
            return self._apply_security_headers(request, response, request_id)

        tier_info = _rate_limit_for_request(raw_path, request.method.upper())
        rate_headers: dict[str, str] = {}
        if tier_info is not None:
            tier, limit = tier_info
            client_ip = _extract_client_ip(request)
            allowed, remaining, reset_or_retry = rate_limiter.check(
                f"{tier}:{client_ip}", limit=limit, window_seconds=60.0
            )
            rate_headers = {
                "X-RateLimit-Limit": str(limit),
                "X-RateLimit-Remaining": str(remaining),
                "X-RateLimit-Reset": str(reset_or_retry),
            }
            if not allowed:
                response = JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={
                        "detail": "Rate limit exceeded. Please wait before retrying.",
                    },
                    headers={**rate_headers, "Retry-After": str(reset_or_retry)},
                )
                return self._apply_security_headers(request, response, request_id)

        try:
            response = await call_next(request)
        except Exception as error:
            logger.error(
                "Unhandled API exception request_id=%s method=%s exception=%s",
                request_id,
                request.method.upper(),
                type(error).__name__,
            )
            response = JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={"detail": "Internal server error"},
            )

        for header_name, header_value in rate_headers.items():
            response.headers.setdefault(header_name, header_value)

        return self._apply_security_headers(request, response, request_id)

    @staticmethod
    def _apply_security_headers(
        request: Request, response: Any, request_id: str
    ) -> Any:
        headers = response.headers
        headers["X-Request-ID"] = request_id
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "no-referrer")
        headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if request.url.path.endswith("/image"):
            headers.setdefault("Cross-Origin-Resource-Policy", "cross-origin")
        else:
            headers.setdefault("Cross-Origin-Resource-Policy", "same-site")

        if request.url.path.startswith("/v1/"):
            headers.setdefault(
                "Content-Security-Policy",
                "default-src 'none'; frame-ancestors 'none'; sandbox",
            )
            if request.url.path.startswith("/v1/studies"):
                headers.setdefault("Cache-Control", "private, no-store, max-age=0")

        if is_production_env() or request.url.scheme == "https":
            headers.setdefault(
                "Strict-Transport-Security",
                "max-age=63072000; includeSubDomains; preload",
            )
        return response
