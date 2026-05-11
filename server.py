from typing import Optional, List, Any, Dict, Tuple
import os
import argparse
import json
import mimetypes
import base64
import io
import logging
import smtplib
import threading
import zipfile
import re
from collections import deque
from datetime import datetime, timezone
from urllib.parse import quote
from email.message import EmailMessage

from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import stripe

from gem import load_image_source, run_generation_pipeline
from fb_core.db_admin import FirebaseAdmin, _normalize_email, _ensure_user_exists_in_auth
from payment.stripe import (
    CreditTier,
    list_all_tiers,
    get_payment_catalog_stable,
    create_checkout_session_payload,
    get_checkout_status,
    verify_webhook_event,
)


class ProcessRequest(BaseModel):
    """Request body for the gem.py workflow: cover art generation process."""
    
    # Input parameters
    input: str = Field(default="", description="Optional path to local folder, file, or direct web image URL")
    
    # Design parameters
    theme: str = Field(default="Mathematical and physical futuristic", description="Design theme")
    bg_texture: str = Field(default="sharp", description="Background texture")
    math: str = Field(default="golden ratio proportions", description="Mathematical geometry rule")
    name: str = Field(default="", description="Product name (leave empty for no text)")
    typo: str = Field(default="futuristic", description="Typography style")
    colors: str = Field(default="black and white", description="Color palette")
    tags: str = Field(default="A colorful luxury cyberpunk lighter-cover with glowing orange neon elements and elegant typography.", 
                     description="Additional tags for design")
    
    # Output and dimension parameters
    output_dir: str = Field(default="output", description="Directory to save generated content")
    height: int = Field(default=600, description="Height in pixel")
    width: int = Field(default=600, description="Width in pixel")
    
    # API Key
    gem_api_key: Optional[str] = Field(default=None, description="Gemini API key (uses env var if not provided)")
    pasted_images: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Optional pasted image payloads, each item: {name, data_url}",
    )
    user_id: Optional[str] = Field(default=None, description="Authenticated app user id for Firebase file mirror")
    user_email: Optional[str] = Field(default=None, description="Authenticated user email for notifications")
    use_free: bool = Field(default=False, description="Request one free daily execution when available")

    # File-type creation switches (jpg is always generated)
    generate_svg: bool = Field(default=True, description="Generate lithography SVG (out.svg)")
    generate_stl: bool = Field(default=True, description="Generate 3-D STL mesh (out.stl)")
    generate_html: bool = Field(default=True, description="Generate interactive 3-D HTML (out.html)")
    generate_animation: bool = Field(default=True, description="Generate animated SVG (animated.svg)")


class GeneratedArtifact(BaseModel):
    name: str
    relative_path: str
    mime_type: str
    size_bytes: int
    view_url: str
    download_url: str


class FreeGenerationStatusSnapshot(BaseModel):
    can_use_free: bool = Field(description="Whether user can still use free generation today")
    free_generations_used: int = Field(description="Number of free generations used today")
    free_generations_limit: int = Field(description="Max number of free generations allowed per day")
    last_free_generation_date: Optional[str] = Field(default=None, description="ISO date of last free generation")


class ProcessResponse(BaseModel):
    """Response body for the process endpoint."""
    
    success: bool = Field(description="Whether the process completed successfully")
    message: str = Field(description="Status message")
    output_dir: Optional[str] = Field(default=None, description="Directory where output was saved")
    run_dir: Optional[str] = Field(default=None, description="Run-specific output directory")
    input_artifacts: List[GeneratedArtifact] = Field(default_factory=list, description="Temp-store input files")
    artifacts: List[GeneratedArtifact] = Field(default_factory=list, description="Generated local files")
    stack_download_url: Optional[str] = Field(default=None, description="Download URL for a ZIP containing all generated files")
    local_copy_dir: Optional[str] = Field(default=None, description="Local mirror directory for generated image files")
    preview_image_data_url: Optional[str] = Field(default=None, description="Base64 preview for generated jpg")
    firebase_files: List[dict] = Field(default_factory=list, description="Uploaded Firebase file metadata")
    free_generation_status: Optional[FreeGenerationStatusSnapshot] = Field(default=None, description="Updated free generation status after this request")
    error: Optional[str] = Field(default=None, description="Error message if process failed")


class AuthUserRequest(BaseModel):
    user: dict = Field(default_factory=dict, description="Google user object/claims")


class AuthUserResponse(BaseModel):
    success: bool
    message: str
    user: Optional[dict] = None
    error: Optional[str] = None


class CheckoutRequest(BaseModel):
    tier: str = Field(description="starter | professional | enterprise")
    quantity: int = Field(default=1, ge=1, le=10000, description="How many units of the selected tier to purchase")
    customer_email: Optional[str] = Field(default=None, description="Customer email for receipt")
    user_id: Optional[str] = Field(default=None, description="Authenticated app user id")


class CheckoutResponse(BaseModel):
    success: bool
    message: str
    checkout_url: Optional[str] = None
    session_id: Optional[str] = None
    expires_at: Optional[int] = None
    error: Optional[str] = None


class FreeGenerationStatusResponse(BaseModel):
    success: bool
    message: str
    can_use_free: bool = Field(description="Whether user can still use free generation today")
    free_generations_used: int = Field(description="Number of free generations used today")
    free_generations_limit: int = Field(description="Max number of free generations allowed per day")
    last_free_generation_date: Optional[str] = Field(default=None, description="ISO date of last free generation")
    error: Optional[str] = None


class CheckoutStatusResponse(BaseModel):
    success: bool
    message: str
    checkout: Optional[dict] = None
    error: Optional[str] = None


class PaymentWebhookNotificationResponse(BaseModel):
    success: bool
    message: str
    notification: Optional[dict] = None
    error: Optional[str] = None


class UserProfileResponse(BaseModel):
    success: bool
    message: str
    user: Optional[dict] = None
    error: Optional[str] = None


class OutputHistoryResponse(BaseModel):
    success: bool
    message: str
    runs: List[dict] = Field(default_factory=list)
    error: Optional[str] = None


app = FastAPI(title="lighter0", version="1.0.0", docs_url="/docs", openapi_url="/openapi.json")

logger = logging.getLogger("lighter0.server")

MAX_PASTED_IMAGES = int((os.getenv("MAX_PASTED_IMAGES") or "8").strip())
MAX_PASTED_IMAGE_BYTES = int((os.getenv("MAX_PASTED_IMAGE_BYTES") or str(8 * 1024 * 1024)).strip())
MAX_TOTAL_PASTED_BYTES = int((os.getenv("MAX_TOTAL_PASTED_BYTES") or str(32 * 1024 * 1024)).strip())
MAX_STACK_FILE_COUNT = int((os.getenv("MAX_STACK_FILE_COUNT") or "200").strip())
MAX_STACK_ZIP_BYTES = int((os.getenv("MAX_STACK_ZIP_BYTES") or str(100 * 1024 * 1024)).strip())
MAX_RENDER_DIMENSION = int((os.getenv("MAX_RENDER_DIMENSION") or "4096").strip())
TRUST_PROXY_HEADERS = (os.getenv("TRUST_PROXY_HEADERS") or "false").strip().lower() == "true"
ENFORCE_ID_TOKEN_AUTH = (os.getenv("ENFORCE_ID_TOKEN_AUTH") or "true").strip().lower() == "true"
CHECK_REVOKED_ID_TOKEN = (os.getenv("CHECK_REVOKED_ID_TOKEN") or "true").strip().lower() == "true"
WEBHOOK_PROCESSING_TTL_SECONDS = int((os.getenv("WEBHOOK_PROCESSING_TTL_SECONDS") or "300").strip())
RATE_LIMIT_PROCESS_PER_MINUTE = int((os.getenv("RATE_LIMIT_PROCESS_PER_MINUTE") or "10").strip())
RATE_LIMIT_CHECKOUT_PER_HOUR = int((os.getenv("RATE_LIMIT_CHECKOUT_PER_HOUR") or "5").strip())
PAYMENT_EVENTS_CACHE_TTL_SECONDS = int((os.getenv("PAYMENT_EVENTS_CACHE_TTL_SECONDS") or "3").strip())
CHECKOUT_STATUS_CACHE_TTL_SECONDS = int((os.getenv("CHECKOUT_STATUS_CACHE_TTL_SECONDS") or "4").strip())
TESTING_REDIRECT_BASE_URL = "https://verbose-giggle-wwxvxvv4v76f9wr5-8000.app.github.dev"
DEFAULT_REDIRECT_BASE_URL = "https://example.com"

_SAFE_USER_ID = re.compile(r"^[A-Za-z0-9_\-:.@]{1,128}$")

# ---------------------------------------------------------------------------
# In-memory sliding-window rate limiter (no external dependency required)
# ---------------------------------------------------------------------------
_rl_store: Dict[str, deque] = {}
_rl_lock = threading.Lock()
_payment_events_cache: Dict[str, Any] = {
    "loaded_at": 0.0,
    "mtime": None,
    "data": [],
}
_payment_events_lock = threading.Lock()
_checkout_status_cache: Dict[str, Dict[str, Any]] = {}
_checkout_status_lock = threading.Lock()


def _check_rate_limit(key: str, limit: int, window_seconds: int) -> None:
    """Raise HTTP 429 if *key* has exceeded *limit* requests within *window_seconds*.

    Uses a thread-safe sliding window backed by a module-level deque.
    """
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - window_seconds
    with _rl_lock:
        if key not in _rl_store:
            _rl_store[key] = deque()
        bucket = _rl_store[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Max {limit} requests per {window_seconds}s.",
            )
        bucket.append(now)

def _extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    raw = str(authorization or "").strip()
    if not raw:
        return None
    if not raw.lower().startswith("bearer "):
        return None
    token = raw[7:].strip()
    return token or None


def _verify_id_token(authorization: Optional[str]) -> Optional[Dict[str, Any]]:
    token = _extract_bearer_token(authorization)
    if not token:
        return None
    try:
        from firebase_admin import auth as fb_auth
    except Exception as error:
        raise HTTPException(status_code=503, detail="Authentication backend is not available.") from error

    try:
        claims = fb_auth.verify_id_token(token, check_revoked=CHECK_REVOKED_ID_TOKEN)
        if not isinstance(claims, dict):
            raise HTTPException(status_code=401, detail="Invalid authentication token.")
        return claims
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=401, detail="Invalid or expired authentication token.") from error


def _resolve_authenticated_identity(
    request: Request,
    provided_uid: Optional[str] = None,
    provided_email: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str], Optional[Dict[str, Any]]]:
    claims = _verify_id_token(request.headers.get("authorization"))
    if claims is None:
        if ENFORCE_ID_TOKEN_AUTH:
            raise HTTPException(status_code=401, detail="Missing Bearer token.")
        return (provided_uid or "").strip() or None, _normalize_email(provided_email), None

    token_uid = str(claims.get("uid") or claims.get("sub") or "").strip() or None
    token_email = _normalize_email(claims.get("email"))

    candidate_uid = (provided_uid or "").strip()
    candidate_email = _normalize_email(provided_email)

    if candidate_uid and token_uid and candidate_uid != token_uid:
        raise HTTPException(status_code=403, detail="Token identity does not match provided user_id.")
    if candidate_email and token_email and candidate_email != token_email:
        raise HTTPException(status_code=403, detail="Token identity does not match provided user_email.")

    return token_uid, token_email, claims


def _allowed_public_hosts() -> List[str]:
    raw = (os.getenv("ALLOWED_PUBLIC_HOSTS") or "").strip()
    if not raw:
        return []
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


def _is_allowed_output_public_path(relative_path: str) -> bool:
    normalized = (relative_path or "").replace("\\", "/").lstrip("/")
    blocked_prefixes = ("output/payments/",)
    if any(normalized.startswith(prefix) for prefix in blocked_prefixes):
        return False
    return True


def _validate_identity_fields(user_id: Optional[str], user_email: Optional[str]) -> None:
    user_id_value = (user_id or "").strip()
    user_email_value = (user_email or "").strip()

    if user_id_value and not _SAFE_USER_ID.fullmatch(user_id_value):
        raise HTTPException(status_code=400, detail="Invalid user_id format.")
    if user_email_value and not _is_valid_email(user_email_value):
        raise HTTPException(status_code=400, detail="Invalid user_email format.")


def _validate_process_dimensions(height: int, width: int) -> None:
    if height <= 0 or width <= 0:
        raise HTTPException(status_code=400, detail="height and width must be positive integers.")
    if height > MAX_RENDER_DIMENSION or width > MAX_RENDER_DIMENSION:
        raise HTTPException(
            status_code=400,
            detail=f"height/width exceed max allowed dimension ({MAX_RENDER_DIMENSION}).",
        )


def _validate_and_limit_pasted_images(pasted_images: List[Dict[str, str]]) -> List[Dict[str, str]]:
    if not pasted_images:
        return []
    if len(pasted_images) > MAX_PASTED_IMAGES:
        raise HTTPException(status_code=400, detail=f"Too many pasted_images. Max allowed: {MAX_PASTED_IMAGES}.")
    return pasted_images

_cors_dev_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
_cors_env_raw = (os.getenv("CORS_ALLOWED_ORIGINS") or "").strip()
_cors_origins = (
    [o.strip() for o in _cors_env_raw.split(",") if o.strip()]
    if _cors_env_raw
    else _cors_dev_origins
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _payments_dir() -> str:
    path = os.path.join("output", "payments")
    os.makedirs(path, exist_ok=True)
    return path


def _append_payment_event(event: dict) -> None:
    events_file = os.path.join(_payments_dir(), "events.jsonl")
    with open(events_file, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=True) + "\n")
    # Invalidate cache immediately so subsequent reads observe the newest event.
    with _payment_events_lock:
        _payment_events_cache["loaded_at"] = 0.0
        _payment_events_cache["mtime"] = None
        _payment_events_cache["data"] = []


_JSONL_SCAN_MAX_LINES = int((os.getenv("PAYMENT_EVENTS_MAX_SCAN_LINES") or "5000").strip())


def _read_payment_events() -> List[dict]:
    events_file = os.path.join(_payments_dir(), "events.jsonl")
    if not os.path.isfile(events_file):
        with _payment_events_lock:
            _payment_events_cache["loaded_at"] = 0.0
            _payment_events_cache["mtime"] = None
            _payment_events_cache["data"] = []
        return []

    now_ts = datetime.now(timezone.utc).timestamp()
    try:
        file_mtime = os.path.getmtime(events_file)
    except Exception:
        file_mtime = None

    with _payment_events_lock:
        cache_mtime = _payment_events_cache.get("mtime")
        cache_loaded = float(_payment_events_cache.get("loaded_at") or 0.0)
        cache_data = _payment_events_cache.get("data")
        if (
            file_mtime is not None
            and cache_mtime == file_mtime
            and (now_ts - cache_loaded) <= PAYMENT_EVENTS_CACHE_TTL_SECONDS
            and isinstance(cache_data, list)
        ):
            return list(cache_data)

    parsed: List[dict] = []
    lines_read = 0
    with open(events_file, "r", encoding="utf-8") as fh:
        for raw in fh:
            lines_read += 1
            if lines_read > _JSONL_SCAN_MAX_LINES:
                logger.warning("[EVENTS] JSONL scan capped at %s lines", _JSONL_SCAN_MAX_LINES)
                break
            line = (raw or "").strip()
            if not line:
                continue
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    with _payment_events_lock:
        _payment_events_cache["loaded_at"] = now_ts
        _payment_events_cache["mtime"] = file_mtime
        _payment_events_cache["data"] = list(parsed)
    return parsed


def _get_checkout_status_cached(session_id: str) -> Dict[str, Any]:
    key = str(session_id or "").strip()
    now_ts = datetime.now(timezone.utc).timestamp()

    with _checkout_status_lock:
        cached = _checkout_status_cache.get(key)
        if cached and float(cached.get("expires_at") or 0.0) > now_ts:
            data = cached.get("data")
            if isinstance(data, dict):
                return dict(data)

    info = get_checkout_status(key)
    ttl = CHECKOUT_STATUS_CACHE_TTL_SECONDS
    if str(info.get("is_paid") or "").lower() in {"true", "1"} or bool(info.get("is_paid")):
        ttl = max(ttl, 15)

    with _checkout_status_lock:
        _checkout_status_cache[key] = {
            "expires_at": now_ts + max(1, int(ttl)),
            "data": dict(info or {}),
        }
    return dict(info or {})


def _was_webhook_event_processed(event_id: Optional[str]) -> bool:
    needle = str(event_id or "").strip()
    if not needle:
        return False
    for item in _read_payment_events():
        kind = str(item.get("kind") or "").strip().lower()
        seen_id = str(item.get("event_id") or "").strip()
        if kind == "webhook.processed" and seen_id == needle:
            return True
    return False


def _webhook_state_path(event_id: str) -> str:
    return f"system/payment_webhooks/{event_id}"


def _acquire_webhook_event_lock(event_id: Optional[str]) -> bool:
    key = str(event_id or "").strip()
    if not key:
        return False

    admin = FirebaseAdmin(user_id="system", env_id=os.getenv("ENV_ID", "default"))
    if admin.db_manager is None:
        raise HTTPException(status_code=503, detail="Webhook idempotency store unavailable.")

    now_iso = datetime.now(timezone.utc).isoformat()
    acquired = {"value": False}

    def _updater(current):
        state = current if isinstance(current, dict) else {}
        status = str(state.get("status") or "").strip().lower()
        updated_raw = str(state.get("updated_at") or "").strip()
        stale_processing = False
        if status == "processing" and updated_raw:
            try:
                last_update = datetime.fromisoformat(updated_raw.replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - last_update.astimezone(timezone.utc)).total_seconds()
                stale_processing = age > WEBHOOK_PROCESSING_TTL_SECONDS
            except Exception:
                stale_processing = False
        if status == "processed":
            acquired["value"] = False
            return state
        if status == "processing" and not stale_processing:
            acquired["value"] = False
            return state
        state["status"] = "processing"
        state["updated_at"] = now_iso
        acquired["value"] = True
        return state

    admin.db_manager.transact(path=_webhook_state_path(key), update_fn=_updater)
    return bool(acquired["value"])


def _finalize_webhook_event_lock(event_id: Optional[str], status: str, reason: Optional[str] = None) -> None:
    key = str(event_id or "").strip()
    if not key:
        return
    admin = FirebaseAdmin(user_id="system", env_id=os.getenv("ENV_ID", "default"))
    if admin.db_manager is None:
        return
    payload: Dict[str, Any] = {
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if reason:
        payload["reason"] = reason[:300]
    admin.db_manager.update_data(path=_webhook_state_path(key), data=payload)


def _is_valid_email(value: Optional[str]) -> bool:
    if value is None:
        return True
    email = value.strip()
    return "@" in email and "." in email and " " not in email


def _request_base_url(request: Request) -> str:
    from urllib.parse import urlparse

    allowed_hosts = _allowed_public_hosts()
    is_testing = (os.getenv("TESTING") or "false").strip().lower() == "true"
    public_base_url = TESTING_REDIRECT_BASE_URL if is_testing else DEFAULT_REDIRECT_BASE_URL

    def _normalize_host(host_value: str) -> str:
        return str(host_value or "").strip().lower()

    def _is_local_host(host_value: str) -> bool:
        host = _normalize_host(host_value)
        if not host:
            return False
        host_only = host.split(":", 1)[0]
        return host_only in {"localhost", "127.0.0.1", "0.0.0.0"}

    def _validate_host(host_value: str, source: str) -> None:
        if allowed_hosts and _normalize_host(host_value) not in allowed_hosts:
            raise HTTPException(status_code=400, detail=f"{source} host is not allowed for checkout redirection.")

    def _extract_base_from_url(url_value: str, source: str) -> Optional[str]:
        text = str(url_value or "").strip()
        if not (text.startswith("http://") or text.startswith("https://")):
            return None
        parsed = urlparse(text)
        scheme = (parsed.scheme or "https").strip().lower()
        host = _normalize_host(parsed.netloc)
        if not host:
            return None
        if _is_local_host(host):
            return None
        _validate_host(host, source)
        return f"{scheme}://{host}"

    # 0) Explicit override for production/stable deployments.
    if public_base_url:
        explicit = _extract_base_from_url(public_base_url, "PUBLIC_BASE_URL")
        if explicit:
            return explicit

    # 1) Browser-origin signals (works for frontend -> API calls).
    for header_name, source in (("origin", "Origin"), ("referer", "Referer")):
        try:
            candidate = _extract_base_from_url(request.headers.get(header_name), source)
            if candidate:
                return candidate
        except HTTPException:
            raise
        except Exception:
            pass

    # 2) RFC Forwarded header (proxy-standard).
    forwarded_raw = str(request.headers.get("forwarded") or "").strip()
    if forwarded_raw:
        try:
            first_part = forwarded_raw.split(",", 1)[0]
            pairs = [item.strip() for item in first_part.split(";") if item.strip()]
            f_proto = ""
            f_host = ""
            for pair in pairs:
                if "=" not in pair:
                    continue
                k, v = pair.split("=", 1)
                key = k.strip().lower()
                val = v.strip().strip('"')
                if key == "proto":
                    f_proto = val
                elif key == "host":
                    f_host = val
            if f_host and not _is_local_host(f_host):
                scheme = (f_proto or "https").strip().lower()
                host = _normalize_host(f_host)
                _validate_host(host, "Forwarded")
                return f"{scheme}://{host}"
        except Exception:
            pass

    # 3) X-Forwarded-* headers (common ingress/proxy behavior).
    xf_host_raw = str(request.headers.get("x-forwarded-host") or "").strip()
    xf_proto_raw = str(request.headers.get("x-forwarded-proto") or "").strip()
    xf_port_raw = str(request.headers.get("x-forwarded-port") or "").strip()
    if xf_host_raw:
        xf_host = _normalize_host(xf_host_raw.split(",")[0].strip())
        if xf_host and not _is_local_host(xf_host):
            scheme = (xf_proto_raw.split(",")[0].strip().lower() if xf_proto_raw else "https") or "https"
            host_with_port = xf_host
            if xf_port_raw:
                p = xf_port_raw.split(",")[0].strip()
                if p and ":" not in host_with_port and p not in {"80", "443"}:
                    host_with_port = f"{host_with_port}:{p}"
            _validate_host(host_with_port, "X-Forwarded")
            return f"{scheme}://{host_with_port}"

    # 4) Host/request URL if already public.
    host_header = _normalize_host(request.headers.get("host") or "")
    if host_header and not _is_local_host(host_header):
        scheme = (str(request.url.scheme or "https").strip().lower() or "https")
        _validate_host(host_header, "Request")
        return f"{scheme}://{host_header}"

    url_host = _normalize_host(request.url.netloc or "")
    if url_host and not _is_local_host(url_host):
        scheme = (str(request.url.scheme or "https").strip().lower() or "https")
        _validate_host(url_host, "Request")
        return f"{scheme}://{url_host}"

    # 5) Codespaces fallback for dynamic dev domains.
    codespace_name = str(os.getenv("CODESPACE_NAME") or "").strip()
    if codespace_name:
        port = str(os.getenv("PORT") or "8000").strip() or "8000"
        codespaces_domain = str(os.getenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN") or "app.github.dev").strip()
        host = f"{codespace_name}-{port}.{codespaces_domain}"
        _validate_host(host, "Codespaces")
        return f"https://{host}"

    raise HTTPException(status_code=400, detail="Could not resolve public base URL for checkout redirection.")


def _checkout_redirect_urls(request: Request) -> Dict[str, str]:
    base_url = _request_base_url(request).rstrip("/")
    return {
        "success_url": f"{base_url}/checkout/success",
        "cancel_url": f"{base_url}/checkout/failed",
    }


def _project_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _default_output_dir() -> str:
    path = os.path.join(_project_root(), "output")
    os.makedirs(path, exist_ok=True)
    return path


def _safe_relpath(path: str, root: str) -> str:
    rel = os.path.relpath(path, root)
    return rel.replace(os.sep, "/")


def _safe_output_user_segment(user_key: str) -> str:
    raw = str(user_key or "").strip()
    if not raw:
        return "anonymous"
    safe = re.sub(r"[^A-Za-z0-9._@:-]+", "_", raw)
    return safe[:128] or "anonymous"


def _resolve_output_file(file_path: str) -> str:
    output_root = _default_output_dir()
    cleaned = os.path.normpath((file_path or "").strip()).lstrip("/\\")
    absolute = os.path.abspath(os.path.join(_project_root(), cleaned))

    if not absolute.startswith(output_root + os.sep):
        raise HTTPException(status_code=403, detail="File path is outside output directory.")
    if not os.path.isfile(absolute):
        raise HTTPException(status_code=404, detail="File not found.")
    if not _is_allowed_output_public_path(_safe_relpath(absolute, _project_root())):
        raise HTTPException(status_code=403, detail="File path is not publicly accessible.")
    return absolute


def _resolve_output_dir(dir_path: str) -> str:
    output_root = _default_output_dir()
    cleaned = os.path.normpath((dir_path or "").strip()).lstrip("/\\")
    absolute = os.path.abspath(os.path.join(_project_root(), cleaned))

    if not absolute.startswith(output_root + os.sep):
        raise HTTPException(status_code=403, detail="Directory path is outside output directory.")
    if not os.path.isdir(absolute):
        raise HTTPException(status_code=404, detail="Directory not found.")
    if not _is_allowed_output_public_path(_safe_relpath(absolute, _project_root()) + "/"):
        raise HTTPException(status_code=403, detail="Directory path is not publicly accessible.")
    return absolute


def _build_stack_zip_bytes(source_dir: str) -> bytes:
    buffer = io.BytesIO()
    file_count = 0
    cumulative_size = 0
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(source_dir):
            for name in sorted(files):
                absolute = os.path.join(root, name)
                file_count += 1
                if file_count > MAX_STACK_FILE_COUNT:
                    raise HTTPException(status_code=400, detail=f"Too many files for stack download (max {MAX_STACK_FILE_COUNT}).")
                size = os.path.getsize(absolute)
                cumulative_size += size
                if cumulative_size > MAX_STACK_ZIP_BYTES:
                    raise HTTPException(status_code=400, detail=f"Stack download exceeds max size ({MAX_STACK_ZIP_BYTES} bytes).")
                arcname = os.path.relpath(absolute, source_dir).replace(os.sep, "/")
                zf.write(absolute, arcname)
    buffer.seek(0)
    return buffer.getvalue()


def _collect_artifacts(run_dir: str):
    project_root = _project_root()
    artifacts: List[GeneratedArtifact] = []
    preview_image_data_url = None

    if not os.path.isdir(run_dir):
        return artifacts, preview_image_data_url

    for name in sorted(os.listdir(run_dir)):
        absolute = os.path.join(run_dir, name)
        if not os.path.isfile(absolute):
            continue

        relative_path = _safe_relpath(absolute, project_root)
        mime_type = mimetypes.guess_type(absolute)[0] or "application/octet-stream"
        encoded_relative_path = quote(relative_path, safe="/")

        artifacts.append(
            GeneratedArtifact(
                name=name,
                relative_path=relative_path,
                mime_type=mime_type,
                size_bytes=os.path.getsize(absolute),
                view_url=f"/api/files/view/{encoded_relative_path}",
                download_url=f"/api/files/download/{encoded_relative_path}",
            )
        )

        if preview_image_data_url is None and mime_type.startswith("image/"):
            try:
                with open(absolute, "rb") as fh:
                    b64 = base64.b64encode(fh.read()).decode("ascii")
                preview_image_data_url = f"data:{mime_type};base64,{b64}"
            except Exception:
                preview_image_data_url = None

    return artifacts, preview_image_data_url


def _extension_for_mime(mime_type: str) -> str:
    if mime_type == "image/jpeg":
        return ".jpg"
    ext = mimetypes.guess_extension(mime_type or "")
    if not ext:
        return ".bin"
    return ext


def _decode_data_url(data_url: str) -> Tuple[bytes, str]:
    raw = (data_url or "").strip()
    if not raw:
        raise ValueError("Empty data_url")

    if raw.startswith("data:") and "," in raw:
        header, payload = raw.split(",", 1)
        header_lower = header.lower()
        mime_type = "application/octet-stream"
        if header_lower.startswith("data:"):
            mime_candidate = header[5:].split(";", 1)[0].strip()
            if mime_candidate:
                mime_type = mime_candidate
        if not mime_type.startswith("image/"):
            raise ValueError("Only image data URLs are allowed")
        try:
            decoded = base64.b64decode(payload, validate=True)
        except Exception as error:
            raise ValueError("Invalid base64 payload in data_url") from error
        if len(decoded) > MAX_PASTED_IMAGE_BYTES:
            raise ValueError(f"Image exceeds max size ({MAX_PASTED_IMAGE_BYTES} bytes)")
        return decoded, mime_type

    # Fallback: assume plain base64 without data URL header.
    try:
        decoded = base64.b64decode(raw, validate=True)
    except Exception as error:
        raise ValueError("Invalid base64 payload") from error
    if len(decoded) > MAX_PASTED_IMAGE_BYTES:
        raise ValueError(f"Image exceeds max size ({MAX_PASTED_IMAGE_BYTES} bytes)")
    return decoded, "application/octet-stream"


def _store_pasted_images(request_id: str, pasted_images: List[Dict[str, str]]) -> Tuple[str, List[GeneratedArtifact]]:
    pasted_images = _validate_and_limit_pasted_images(pasted_images)
    temp_store_dir = os.path.join(_default_output_dir(), "temp_store", request_id)
    os.makedirs(temp_store_dir, exist_ok=True)

    artifacts: List[GeneratedArtifact] = []
    project_root = _project_root()
    total_written = 0

    for idx, item in enumerate(pasted_images, start=1):
        if not isinstance(item, dict):
            continue

        data_url = str(item.get("data_url") or "").strip()
        if not data_url:
            continue

        file_bytes, mime_type = _decode_data_url(data_url)
        if not str(mime_type or "").startswith("image/"):
            continue
        requested_name = os.path.basename(str(item.get("name") or "").strip())
        if requested_name:
            base, ext = os.path.splitext(requested_name)
            if not ext:
                ext = _extension_for_mime(mime_type)
            file_name = f"{base or f'image_{idx:03d}'}{ext}"
        else:
            file_name = f"image_{idx:03d}{_extension_for_mime(mime_type)}"

        absolute = os.path.join(temp_store_dir, file_name)
        with open(absolute, "wb") as fh:
            fh.write(file_bytes)
        total_written += len(file_bytes)
        if total_written > MAX_TOTAL_PASTED_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"Total pasted image payload exceeds max allowed size ({MAX_TOTAL_PASTED_BYTES} bytes).",
            )

        relative_path = _safe_relpath(absolute, project_root)
        encoded_relative_path = quote(relative_path, safe="/")
        artifacts.append(
            GeneratedArtifact(
                name=file_name,
                relative_path=relative_path,
                mime_type=mime_type,
                size_bytes=os.path.getsize(absolute),
                view_url=f"/api/files/view/{encoded_relative_path}",
                download_url=f"/api/files/download/{encoded_relative_path}",
            )
        )

    return temp_store_dir, artifacts


def _send_email_notification(to_email: Optional[str], subject: str, body: str) -> bool:
    """Send notification email using SMTP env configuration."""
    recipient = (to_email or "").strip()
    if not recipient:
        logger.warning("[EMAIL] skipped send due to missing recipient")
        return False

    admin_email = (os.getenv("ADMIN_EMAIL") or "").strip()
    admin_password = (os.getenv("ADMIN_PASSWORD") or "").strip()
    smtp_host = (os.getenv("SMTP_HOST") or "smtp.gmail.com").strip()
    smtp_port = int((os.getenv("SMTP_PORT") or "587").strip())
    smtp_use_tls = (os.getenv("SMTP_USE_TLS") or "true").strip().lower() == "true"

    if not admin_email or not admin_password:
        logger.warning("[EMAIL] skipped send because ADMIN_EMAIL/ADMIN_PASSWORD are not configured")
        return False

    try:
        msg = EmailMessage()
        msg["From"] = admin_email
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.set_content(body)

        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as smtp:
            smtp.ehlo()
            if smtp_use_tls:
                smtp.starttls()
                smtp.ehlo()
            smtp.login(admin_email, admin_password)
            smtp.send_message(msg)

        logger.info("[EMAIL] sent to=%s subject=%s", recipient, subject)
        return True
    except Exception as error:
        logger.warning("[EMAIL] failed to send to=%s error=%s", recipient, error)
        return False


def _validated_artifacts(artifacts: List[GeneratedArtifact]) -> List[GeneratedArtifact]:
    """Keep only artifacts that can be safely rendered and downloaded by the frontend."""
    validated: List[GeneratedArtifact] = []
    for item in artifacts:
        if not item.relative_path:
            continue
        if not item.view_url or not item.download_url:
            continue
        validated.append(item)
    return validated


def _local_auth_user_from_claims(claims: dict) -> dict:
    return {
        "created": False,
        "lookup": claims.get("sub") or claims.get("email") or claims.get("uid"),
        "uid": claims.get("sub") or claims.get("uid"),
        "email": claims.get("email"),
        "display_name": claims.get("name") or claims.get("displayName") or claims.get("display_name"),
        "photo_url": claims.get("picture") or claims.get("photoURL") or claims.get("photo_url"),
        "disabled": False,
        "firebase_synced": False,
    }


def _is_firebase_config_error(error: Exception) -> bool:
    message = str(error).lower()
    markers = (
        "project id is required",
        "default firebase app does not exist",
        "failed to initialize a certificate credential",
        "unable to load pem file",
        "firebase_admin is not available",
    )
    return any(marker in message for marker in markers)


def _tier_credit_lookup() -> Dict[str, int]:
    lookup: Dict[str, int] = {}
    try:
        for item in list_all_tiers():
            tier_name = str(item.get("tier", "")).strip().lower()
            credits = int(item.get("credits", 0) or 0)
            if tier_name:
                lookup[tier_name] = credits
    except Exception:
        return {"starter": 100, "professional": 500, "enterprise": 1500}

    if not lookup:
        return {"starter": 100, "professional": 500, "enterprise": 1500}
    return lookup


def _resolve_user_profile(email: Optional[str], uid: Optional[str]) -> dict:
    email_key = _normalize_email(email)
    uid_key = (uid or "").strip() if uid else None

    tier_credits = _tier_credit_lookup()

    # --- Canonical credit balance: read from Firebase RTDB (atomic source of truth) ---
    rtdb_credits: Optional[int] = None
    billing_key = _usage_user_id(uid_key, email_key)
    if billing_key:
        try:
            env_id = os.getenv("ENV_ID", "default")
            admin = FirebaseAdmin(user_id=billing_key, env_id=env_id)
            if admin.db_manager is not None:
                rtdb_credits = admin.get_credits()
        except Exception as _credit_err:
            logger.warning("[PROFILE] RTDB credit lookup failed for %s: %s", billing_key, _credit_err)

    # --- Purchase history: JSONL (capped scan, best-effort audit trail) ---
    events = _read_payment_events()

    checkout_by_session: Dict[str, dict] = {}
    paid_sessions = set()

    for event in events:
        kind = str(event.get("kind", "")).strip().lower()
        session_id = str(event.get("session_id") or "").strip()

        if kind == "checkout.created" and session_id:
            checkout_by_session[session_id] = {
                "session_id": session_id,
                "tier": str(event.get("tier") or "").strip().lower(),
                "quantity": int(event.get("quantity") or 1),
                "customer_email": str(event.get("customer_email") or "").strip().lower(),
                "at": event.get("at"),
            }

        if kind in {"checkout.status.checked", "stripe.webhook"} and session_id:
            payment_status = str(event.get("payment_status") or "").strip().lower()
            status = str(event.get("status") or "").strip().lower()
            if payment_status == "paid" or status == "paid":
                paid_sessions.add(session_id)

    purchases = []
    for session_id, checkout in checkout_by_session.items():
        checkout_email = checkout.get("customer_email") or ""
        if email_key and checkout_email != email_key:
            continue

        tier = checkout.get("tier") or "starter"
        quantity = int(checkout.get("quantity") or 1)
        unit_credits = int(tier_credits.get(tier, 0))
        total_credits = unit_credits * quantity

        purchases.append(
            {
                "session_id": session_id,
                "tier": tier,
                "quantity": quantity,
                "credits": total_credits,
                "is_paid": session_id in paid_sessions,
                "at": checkout.get("at"),
            }
        )

    # Use RTDB balance when available; fall back to JSONL-derived sum for degraded mode
    if rtdb_credits is not None:
        display_credits = rtdb_credits
    else:
        display_credits = sum(item["credits"] for item in purchases if item["is_paid"])

    pending_credits = sum(item["credits"] for item in purchases if not item["is_paid"])

    user = {
        "uid": uid_key or None,
        "email": email_key or None,
        "credits": display_credits,
        "pending_credits": pending_credits,
        "paid_purchases": sum(1 for item in purchases if item["is_paid"]),
        "pending_purchases": sum(1 for item in purchases if not item["is_paid"]),
        "purchases": sorted(purchases, key=lambda x: x.get("at") or "", reverse=True)[:8],
        "credit_source": "rtdb" if rtdb_credits is not None else "jsonl_fallback",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    return user


def _get_today_iso_date() -> str:
    """Return today's date in ISO format (YYYY-MM-DD)"""
    return datetime.now(timezone.utc).date().isoformat()


def _get_single_execution_credit_cost() -> int:
    raw = (os.getenv("COST_CREDITS_SINGLE_EXECUTION") or "100").strip()
    try:
        value = int(raw)
    except Exception as error:
        raise ValueError("COST_CREDITS_SINGLE_EXECUTION must be an integer") from error
    if value <= 0:
        raise ValueError("COST_CREDITS_SINGLE_EXECUTION must be greater than 0")
    return value


def _get_free_daily_limit() -> int:
    raw = (os.getenv("FREE_DAILY_TRIES") or "1").strip()
    try:
        value = int(raw)
    except Exception as error:
        raise ValueError("FREE_DAILY_TRIES must be an integer") from error
    if value < 0:
        raise ValueError("FREE_DAILY_TRIES must be 0 or greater")
    return value


def _usage_user_id(uid: Optional[str], email: Optional[str]) -> Optional[str]:
    uid_value = (uid or "").strip()
    if uid_value:
        return uid_value
    email_value = _normalize_email(email)
    if email_value:
        return email_value
    return None


def _record_user_history(
    uid: Optional[str],
    email: Optional[str],
    action: str,
    status: str = "ok",
    details: Optional[Dict[str, Any]] = None,
    request_id: Optional[str] = None,
) -> None:
    user_key = _usage_user_id(uid, email)
    if not user_key:
        return

    admin = FirebaseAdmin(user_id=user_key, env_id=os.getenv("ENV_ID", "default"))
    if admin.db_manager is None:
        return

    try:
        admin.ensure_user_spaces()
        admin.record_history_event(
            action=action,
            status=status,
            details=details if isinstance(details, dict) else {},
            request_id=request_id,
        )
    except Exception as tracking_error:
        logger.warning("[HISTORY] failed action=%s user=%s error=%s", action, user_key, tracking_error)


def _upsert_user_output_space(
    uid: Optional[str],
    email: Optional[str],
    run_id: str,
    status: str,
    meta: Optional[Dict[str, Any]] = None,
    files: Optional[List[Dict[str, Any]]] = None,
) -> None:
    user_key = _usage_user_id(uid, email)
    if not user_key:
        return

    admin = FirebaseAdmin(user_id=user_key, env_id=os.getenv("ENV_ID", "default"))
    if admin.db_manager is None:
        return

    try:
        clean_run_id = admin.ensure_output_space(run_id=run_id, meta=meta if isinstance(meta, dict) else {}, status=status)
        if files:
            admin.record_output_files(run_id=clean_run_id, files=files)
        elif status and status != "completed":
            admin.ensure_output_space(run_id=clean_run_id, meta=meta if isinstance(meta, dict) else {}, status=status)
    except Exception as output_error:
        logger.warning("[OUTPUT_SPACE] failed run_id=%s user=%s error=%s", run_id, user_key, output_error)


def _get_daily_free_usage(uid: Optional[str], email: Optional[str]) -> Dict[str, Any]:
    user_key = _usage_user_id(uid, email)
    today = _get_today_iso_date()
    limit = _get_free_daily_limit()

    if not user_key:
        return {
            "can_use_free": False,
            "used_today": limit,
            "limit": limit,
            "last_free_date": None,
            "timestamps": {},
            "today": today,
            "user_key": None,
            "source": "anonymous",
        }

    admin = FirebaseAdmin(user_id=user_key, env_id=os.getenv("ENV_ID", "default"))
    if admin.db_manager is None:
        # Fail closed: do not grant free tries when usage state cannot be verified.
        return {
            "can_use_free": False,
            "used_today": limit,
            "limit": limit,
            "last_free_date": None,
            "timestamps": {},
            "today": today,
            "user_key": user_key,
            "source": "firebase_unavailable",
        }

    usage_path = f"{admin.database}/usage/free_daily"
    usage = admin.db_manager.get_data(path=usage_path) or {}
    usage_date = str(usage.get("date") or "").strip()
    used_today = int(usage.get("used_count") or 0) if usage_date == today else 0
    timestamps = usage.get("timestamps") if isinstance(usage.get("timestamps"), dict) else {}
    last_free_date = usage_date or None

    return {
        "can_use_free": used_today < limit,
        "used_today": used_today,
        "limit": limit,
        "last_free_date": last_free_date,
        "timestamps": timestamps,
        "today": today,
        "user_key": user_key,
        "source": "firebase",
    }


def _record_workflow_execution(
    uid: Optional[str],
    email: Optional[str],
    request_id: str,
    mode: str,
    cost_credits: int,
) -> None:
    user_key = _usage_user_id(uid, email)
    if not user_key:
        return

    admin = FirebaseAdmin(user_id=user_key, env_id=os.getenv("ENV_ID", "default"))
    if admin.db_manager is None:
        return

    now_iso = datetime.now(timezone.utc).isoformat()
    attempts_path = f"{admin.database}/usage/workflow_executions"
    admin.db_manager.update_data(
        path=attempts_path,
        data={
            request_id: {
                "at": now_iso,
                "mode": mode,
                "cost_credits": int(cost_credits),
            }
        },
    )


def _consume_daily_free_try(uid: Optional[str], email: Optional[str], request_id: str) -> bool:
    usage_state = _get_daily_free_usage(uid, email)
    if not usage_state.get("can_use_free"):
        return False

    user_key = usage_state.get("user_key")
    if not user_key:
        return False

    admin = FirebaseAdmin(user_id=user_key, env_id=os.getenv("ENV_ID", "default"))
    if admin.db_manager is None:
        return False

    usage_path = f"{admin.database}/usage/free_daily"
    now_iso = datetime.now(timezone.utc).isoformat()
    today = usage_state.get("today") or _get_today_iso_date()
    daily_limit = int(usage_state.get("limit") or 0)
    txn_meta = {"consumed": False}

    def _updater(current):
        state = current if isinstance(current, dict) else {}
        existing_date = str(state.get("date") or "").strip()
        existing_used = int(state.get("used_count") or 0) if existing_date == today else 0
        timestamps = state.get("timestamps") if isinstance(state.get("timestamps"), dict) else {}

        if str(request_id) in timestamps:
            txn_meta["consumed"] = True
            return state

        if existing_used >= daily_limit:
            txn_meta["consumed"] = False
            return state

        timestamps[str(request_id)] = now_iso
        state["date"] = today
        state["used_count"] = existing_used + 1
        state["timestamps"] = timestamps
        state["last_try_at"] = now_iso
        txn_meta["consumed"] = True
        return state

    admin.db_manager.transact(path=usage_path, update_fn=_updater)
    return bool(txn_meta["consumed"])


def _check_can_use_free_generation(uid: Optional[str], email: Optional[str]) -> tuple[bool, Optional[str], int, int]:
    """Check free daily usage in Firebase RTDB and return status tuple."""
    try:
        usage = _get_daily_free_usage(uid, email)
        return (
            bool(usage.get("can_use_free")),
            usage.get("last_free_date"),
            int(usage.get("used_today") or 0),
            int(usage.get("limit") or 0),
        )
    except Exception as e:
        print(f"[WARN] Error checking free generation status: {e}")
        limit = _get_free_daily_limit()
        return False, None, limit, limit


def _mark_free_generation_used(uid: Optional[str], email: Optional[str]) -> bool:
    """
    Mark that a user has used their free generation today.
    Returns True if successful, False otherwise.
    """
    try:
        marker_id = f"free-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}"
        return _consume_daily_free_try(uid, email, marker_id)
    except Exception as e:
        print(f"[WARN] Error marking free generation as used: {e}")
        return False


def _get_free_generation_status_snapshot(uid: Optional[str], email: Optional[str]) -> FreeGenerationStatusSnapshot:
    can_use_free, last_free_date, free_used, free_limit = _check_can_use_free_generation(uid, email)
    return FreeGenerationStatusSnapshot(
        can_use_free=can_use_free,
        free_generations_used=free_used,
        free_generations_limit=free_limit,
        last_free_generation_date=last_free_date,
    )


def _safe_iso_sort_value(value: Any) -> str:
    text = str(value or "").strip()
    return text


def _build_output_history_payload(uid: Optional[str], email: Optional[str]) -> List[Dict[str, Any]]:
    user_key = _usage_user_id(uid, email)
    if not user_key:
        return []

    admin = FirebaseAdmin(user_id=user_key, env_id=os.getenv("ENV_ID", "default"))
    if admin.db_manager is None:
        return []

    output_root = admin.db_manager.get_data(path=f"{admin.database}/output") or {}
    if not isinstance(output_root, dict):
        return []

    runs: List[Dict[str, Any]] = []
    for run_id, run_data in output_root.items():
        if run_id in {"created_at", "updated_at"}:
            continue
        if not isinstance(run_data, dict):
            continue

        files_obj = run_data.get("files") if isinstance(run_data.get("files"), dict) else {}
        files_payload: List[Dict[str, Any]] = []

        for _, file_item in files_obj.items():
            if not isinstance(file_item, dict):
                continue

            file_name = str(file_item.get("name") or file_item.get("relative_path") or "file").strip()
            mime_type = str(file_item.get("mime_type") or "application/octet-stream").strip()
            size_bytes = int(file_item.get("size_bytes") or 0)
            firebase_path = str(file_item.get("firebase_path") or "").strip()
            relative_path = str(file_item.get("relative_path") or "").strip()

            if not firebase_path and relative_path:
                absolute_local_path = os.path.abspath(os.path.join(_project_root(), relative_path))
                if not os.path.isfile(absolute_local_path):
                    continue
            
            # Use stored view_url/download_url directly (handles both local and firebase paths)
            view_url = file_item.get("view_url")  # Fallback to stored local view_url if firebase_path empty
            download_url = file_item.get("download_url")

            files_payload.append(
                {
                    "name": file_name,
                    "mime_type": mime_type,
                    "size_bytes": size_bytes,
                    "firebase_path": firebase_path or None,
                    "view_url": view_url,
                    "download_url": download_url,
                }
            )

        runs.append(
            {
                "run_id": run_id,
                "status": str(run_data.get("status") or "unknown"),
                "created_at": run_data.get("created_at"),
                "updated_at": run_data.get("updated_at"),
                "meta": run_data.get("meta") if isinstance(run_data.get("meta"), dict) else {},
                "files": files_payload,
                "file_count": len(files_payload),
            }
        )

    runs.sort(
        key=lambda item: (
            _safe_iso_sort_value(item.get("updated_at")),
            _safe_iso_sort_value(item.get("created_at")),
            str(item.get("run_id") or ""),
        ),
        reverse=True,
    )
    return runs


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "message": "Validation failed",
            "error": exc.errors(),
        },
    )


@app.post("/auth-user", operation_id="auth_user", response_model=AuthUserResponse)
async def auth_user(request: AuthUserRequest) -> AuthUserResponse:
    """Receives Google-authenticated user payload and creates/fetches user in Firebase Auth."""
    claims = request.user or {}
    env_id = os.getenv("ENV_ID", "default")
    candidate_uid = str(claims.get("sub") or claims.get("uid") or "").strip() or None
    candidate_email = _normalize_email(claims.get("email"))
    try:
        if not isinstance(claims, dict) or not claims:
            raise HTTPException(status_code=400, detail="Missing user payload.")

        user_id = str(claims.get("sub") or claims.get("email") or claims.get("uid") or "default")
        admin = FirebaseAdmin(user_id=user_id, env_id=env_id)

        created_user = admin.create_user_from_google_claims(claims)
        canonical_uid = str(created_user.get("uid") or user_id).strip() or user_id

        tracking_admin = FirebaseAdmin(user_id=canonical_uid, env_id=env_id)
        if tracking_admin.db_manager is not None:
            tracking_admin.ensure_user_spaces()

        _record_user_history(
            uid=canonical_uid,
            email=created_user.get("email"),
            action="auth.user_processed",
            status="ok",
            request_id=f"auth-{canonical_uid}",
            details={
                "created": bool(created_user.get("created")),
                "lookup": created_user.get("lookup"),
            },
        )

        return AuthUserResponse(
            success=True,
            message="User processed successfully",
            user=created_user,
        )
    except HTTPException:
        raise
    except ValueError as ve:
        _record_user_history(
            uid=candidate_uid,
            email=candidate_email,
            action="auth.user_processed",
            status="error",
            details={"error": str(ve)},
            request_id="auth-error",
        )
        if _is_firebase_config_error(ve):
            return AuthUserResponse(
                success=True,
                message="Authenticated user accepted; Firebase sync is not configured.",
                user=_local_auth_user_from_claims(request.user or {}),
                error=str(ve),
            )
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        _record_user_history(
            uid=candidate_uid,
            email=candidate_email,
            action="auth.user_processed",
            status="error",
            details={"error": str(e)},
            request_id="auth-error",
        )
        if _is_firebase_config_error(e):
            return AuthUserResponse(
                success=True,
                message="Authenticated user accepted; Firebase sync is not configured.",
                user=_local_auth_user_from_claims(request.user or {}),
                error=str(e),
            )
        return AuthUserResponse(
            success=False,
            message="Failed to process authenticated user",
            error=str(e),
        )


@app.get("/health", operation_id="health_check", include_in_schema=False)
async def health_check() -> JSONResponse:
    return JSONResponse(content={"status": "ok", "version": "1.0.0"})


@app.get("/tiers", operation_id="list_credit_tiers")
async def get_credit_tiers():
    try:
        catalog = get_payment_catalog_stable()
        return {
            "success": True,
            "tiers": catalog.get("tiers", []),
            "catalog": {
                "product_id": catalog.get("product_id"),
                "price_id": catalog.get("price_id"),
                "currency": catalog.get("currency"),
                "unit_price_cents": catalog.get("unit_price_cents"),
                "unit_price_display": catalog.get("unit_price_display"),
            },
        }
    except Exception as error:
        error_msg = str(error)
        logger.error(f"[TIERS] Failed to load pricing: {error_msg}")
        raise HTTPException(status_code=500, detail=error_msg)


@app.get("/user-profile", operation_id="get_user_profile", response_model=UserProfileResponse)
async def get_user_profile(request: Request, email: Optional[str] = None, uid: Optional[str] = None) -> UserProfileResponse:
    try:
        resolved_uid, resolved_email, _ = _resolve_authenticated_identity(
            request=request,
            provided_uid=uid,
            provided_email=email,
        )
        if not resolved_email and not resolved_uid:
            raise HTTPException(status_code=400, detail="Authenticated identity is required.")

        user = _resolve_user_profile(resolved_email, resolved_uid)
        return UserProfileResponse(
            success=True,
            message="User profile resolved",
            user=user,
        )
    except HTTPException:
        raise
    except Exception as error:
        return UserProfileResponse(
            success=False,
            message="Failed to resolve user profile",
            error=str(error),
        )


@app.get("/free-generation-status", operation_id="check_free_generation_status", response_model=FreeGenerationStatusResponse)
async def check_free_generation_status(request: Request, email: Optional[str] = None, uid: Optional[str] = None) -> FreeGenerationStatusResponse:
    try:
        resolved_uid, resolved_email, _ = _resolve_authenticated_identity(
            request=request,
            provided_uid=uid,
            provided_email=email,
        )
        if not resolved_email and not resolved_uid:
            raise HTTPException(status_code=400, detail="Authenticated identity is required.")

        can_use_free, last_free_date, free_used, free_limit = _check_can_use_free_generation(resolved_uid, resolved_email)
        
        return FreeGenerationStatusResponse(
            success=True,
            message="Free generation status retrieved",
            can_use_free=can_use_free,
            free_generations_used=free_used,
            free_generations_limit=free_limit,
            last_free_generation_date=last_free_date,
        )
    except HTTPException:
        raise
    except Exception as error:
        return FreeGenerationStatusResponse(
            success=False,
            message="Failed to check free generation status",
            can_use_free=False,
            free_generations_used=0,
            free_generations_limit=_get_free_daily_limit(),
            error=str(error),
        )


@app.get("/output-history", operation_id="get_output_history", response_model=OutputHistoryResponse)
async def get_output_history(request: Request, email: Optional[str] = None, uid: Optional[str] = None) -> OutputHistoryResponse:
    try:
        resolved_uid, resolved_email, _ = _resolve_authenticated_identity(
            request=request,
            provided_uid=uid,
            provided_email=email,
        )
        if not resolved_uid and not resolved_email:
            raise HTTPException(status_code=400, detail="Authenticated identity is required.")

        runs = _build_output_history_payload(resolved_uid, resolved_email)
        return OutputHistoryResponse(
            success=True,
            message="Output history resolved",
            runs=runs,
        )
    except HTTPException:
        raise
    except Exception as error:
        return OutputHistoryResponse(
            success=False,
            message="Failed to resolve output history",
            runs=[],
            error=str(error),
        )


@app.get("/output-file", operation_id="get_output_file")
async def get_output_file(
    request: Request,
    firebase_path: str,
    download: bool = False,
    email: Optional[str] = None,
    uid: Optional[str] = None,
):
    resolved_uid, resolved_email, _ = _resolve_authenticated_identity(
        request=request,
        provided_uid=uid,
        provided_email=email,
    )

    clean_path = str(firebase_path or "").strip().replace("\\", "/")
    if not clean_path:
        raise HTTPException(status_code=400, detail="firebase_path is required")

    allowed_prefixes = []
    if resolved_uid:
        allowed_prefixes.append(f"users/{resolved_uid}/output/")
    if resolved_email:
        allowed_prefixes.append(f"users/{resolved_email}/output/")

    if not any(clean_path.startswith(prefix) for prefix in allowed_prefixes):
        raise HTTPException(status_code=403, detail="Requested file path is not accessible for this user.")

    try:
        from firebase_admin import storage
    except Exception as error:
        raise HTTPException(status_code=503, detail="Firebase storage is not available.") from error

    bucket = storage.bucket()
    if bucket is None or not bucket.name:
        raise HTTPException(status_code=503, detail="Firebase storage bucket is not configured.")

    blob = bucket.blob(clean_path)
    if not blob.exists():
        raise HTTPException(status_code=404, detail="Requested output file was not found.")

    data = blob.download_as_bytes()
    media_type = str(blob.content_type or mimetypes.guess_type(clean_path)[0] or "application/octet-stream")
    filename = os.path.basename(clean_path) or "output.bin"
    headers = {}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'

    return StreamingResponse(io.BytesIO(data), media_type=media_type, headers=headers)


@app.post("/checkout", operation_id="create_checkout", response_model=CheckoutResponse)
async def create_checkout(request: CheckoutRequest, http_request: Request) -> CheckoutResponse:
    resolved_uid: Optional[str] = None
    resolved_email: Optional[str] = None
    normalized_email: Optional[str] = None
    try:
        resolved_uid, resolved_email, _ = _resolve_authenticated_identity(
            request=http_request,
            provided_uid=request.user_id,
            provided_email=request.customer_email,
        )
        _validate_identity_fields(resolved_uid, resolved_email)
        rl_key = f"checkout:{resolved_uid or resolved_email or http_request.client.host}"
        _check_rate_limit(rl_key, RATE_LIMIT_CHECKOUT_PER_HOUR, 3600)
        tier_value = (request.tier or "").strip().lower()
        if tier_value not in {item.value for item in CreditTier}:
            raise HTTPException(status_code=400, detail="Invalid tier. Use starter, professional, or enterprise.")

        # Normalize and validate email
        normalized_email = _normalize_email(resolved_email)
        if not normalized_email:
            raise HTTPException(status_code=400, detail="Invalid customer_email format.")

        tier = CreditTier(tier_value)
        metadata = {
            "source": "lighter0_api",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if resolved_uid:
            metadata["user_id"] = resolved_uid

        redirect_urls = _checkout_redirect_urls(http_request)

        payload = create_checkout_session_payload(
            tier=tier,
            quantity=request.quantity,
            customer_email=normalized_email,
            metadata=metadata,
            success_url=redirect_urls["success_url"],
            cancel_url=redirect_urls["cancel_url"],
        )

        _append_payment_event(
            {
                "kind": "checkout.created",
                "at": datetime.now(timezone.utc).isoformat(),
                "session_id": payload.get("session_id"),
                "tier": payload.get("tier"),
                "quantity": request.quantity,
                "customer_email": normalized_email,
                "status": payload.get("status"),
            }
        )

        _record_user_history(
            uid=resolved_uid,
            email=normalized_email,
            action="payment.checkout_created",
            status="ok",
            request_id=str(payload.get("session_id") or "checkout-created"),
            details={
                "tier": payload.get("tier"),
                "quantity": int(request.quantity),
                "checkout_status": payload.get("status"),
            },
        )

        return CheckoutResponse(
            success=True,
            message="Checkout session created",
            checkout_url=payload.get("checkout_url"),
            session_id=payload.get("session_id"),
            expires_at=payload.get("expires_at"),
        )
    except HTTPException:
        raise
    except ValueError as error:
        _record_user_history(
            uid=resolved_uid,
            email=normalized_email or resolved_email,
            action="payment.checkout_created",
            status="error",
            details={"error": str(error), "tier": request.tier, "quantity": int(request.quantity)},
            request_id="checkout-error",
        )
        raise HTTPException(status_code=400, detail=str(error))
    except stripe.error.StripeError as error:
        _record_user_history(
            uid=resolved_uid,
            email=normalized_email or resolved_email,
            action="payment.checkout_created",
            status="error",
            details={"error": str(error), "tier": request.tier, "quantity": int(request.quantity)},
            request_id="checkout-error",
        )
        raise HTTPException(status_code=502, detail=f"Stripe error while creating checkout: {error}")
    except Exception as error:
        _record_user_history(
            uid=resolved_uid,
            email=normalized_email or resolved_email,
            action="payment.checkout_created",
            status="error",
            details={"error": str(error), "tier": request.tier, "quantity": int(request.quantity)},
            request_id="checkout-error",
        )
        return CheckoutResponse(
            success=False,
            message="Failed to create checkout session",
            error=str(error),
        )


@app.get("/checkout/{session_id}", operation_id="get_checkout_state", response_model=CheckoutStatusResponse)
async def checkout_status(session_id: str, request: Request) -> CheckoutStatusResponse:
    try:
        if not re.fullmatch(r"^[A-Za-z0-9_]{8,128}$", (session_id or "").strip()):
            raise HTTPException(status_code=400, detail="Invalid session_id format.")
        info = _get_checkout_status_cached(session_id)

        # Strip PII from response when caller is unauthenticated
        claims = _verify_id_token(request.headers.get("authorization"))
        if claims is None:
            info = {k: v for k, v in (info or {}).items() if k not in {"customer_email", "customer_details", "customer"}}

        _append_payment_event(
            {
                "kind": "checkout.status.checked",
                "at": datetime.now(timezone.utc).isoformat(),
                "session_id": info.get("session_id"),
                "status": info.get("status"),
                "payment_status": info.get("payment_status"),
            }
        )

        message = "Checkout state resolved"
        if info.get("is_stale"):
            message = "Checkout is stale and should be recreated"
        elif info.get("is_expired"):
            message = "Checkout has expired"
        elif info.get("is_paid"):
            message = "Checkout is paid"

        return CheckoutStatusResponse(success=True, message=message, checkout=info)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except stripe.error.StripeError as error:
        raise HTTPException(status_code=502, detail=f"Stripe error while fetching checkout state: {error}")
    except Exception as error:
        return CheckoutStatusResponse(
            success=False,
            message="Failed to load checkout status",
            error=str(error),
        )


@app.get("/payment/webhook-latest", operation_id="get_latest_payment_webhook", response_model=PaymentWebhookNotificationResponse)
async def payment_webhook_latest(request: Request, email: Optional[str] = None, uid: Optional[str] = None) -> PaymentWebhookNotificationResponse:
    try:
        resolved_uid, resolved_email, _ = _resolve_authenticated_identity(
            request=request,
            provided_uid=uid,
            provided_email=email,
        )
        _validate_identity_fields(resolved_uid, resolved_email)

        email_key = _normalize_email(resolved_email)
        if not email_key:
            raise HTTPException(status_code=400, detail="Authenticated email is required.")

        events = _read_payment_events()
        for event in reversed(events):
            kind = str(event.get("kind") or "").strip().lower()
            event_email = _normalize_email(event.get("customer_email"))
            if event_email != email_key:
                continue

            if kind == "webhook.processed":
                return PaymentWebhookNotificationResponse(
                    success=True,
                    message="Latest payment webhook notification resolved",
                    notification={
                        "event_id": str(event.get("event_id") or ""),
                        "session_id": str(event.get("session_id") or ""),
                        "at": event.get("at"),
                        "status": "success",
                        "title": "Payment successful",
                        "message": "Credits purchase completed and applied to your account.",
                    },
                )

            if kind == "stripe.webhook":
                payment_status = str(event.get("payment_status") or "").strip().lower()
                is_success = payment_status == "paid"
                return PaymentWebhookNotificationResponse(
                    success=True,
                    message="Latest payment webhook notification resolved",
                    notification={
                        "event_id": str(event.get("event_id") or ""),
                        "session_id": str(event.get("session_id") or ""),
                        "at": event.get("at"),
                        "status": "success" if is_success else "failed",
                        "title": "Payment successful" if is_success else "Payment failed",
                        "message": (
                            "Credits purchase completed and applied to your account."
                            if is_success
                            else "Payment was not completed. No credits were applied."
                        ),
                    },
                )

        return PaymentWebhookNotificationResponse(
            success=True,
            message="No payment webhook notification available",
            notification=None,
        )
    except HTTPException:
        raise
    except Exception as error:
        return PaymentWebhookNotificationResponse(
            success=False,
            message="Failed to load payment webhook notification",
            error=str(error),
        )


@app.post("/payment/webhook", operation_id="stripe_webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(default=None, alias="Stripe-Signature"),
):
    payload = await request.body()
    customer_email: Optional[str] = None
    user_uid: Optional[str] = None

    try:
        event = verify_webhook_event(payload=payload, signature=stripe_signature or "")
        def _safe_get(obj: Any, key: str, default: Any = None) -> Any:
            if obj is None:
                return default
            if isinstance(obj, dict):
                return obj.get(key, default)
            getter = getattr(obj, "get", None)
            if callable(getter):
                try:
                    return getter(key, default)
                except TypeError:
                    pass
            return getattr(obj, key, default)

        event_type = _safe_get(event, "type")
        event_id = _safe_get(event, "id")
        event_data = _safe_get(event, "data", {}) or {}
        event_object = _safe_get(event_data, "object", {}) or {}

        session_id = _safe_get(event_object, "id")
        payment_status = str(_safe_get(event_object, "payment_status") or "").strip().lower()

        # Extract and normalize customer email early so event logs can be matched by user.
        customer_email = (
            _safe_get(_safe_get(event_object, "customer_details", {}), "email")
            or _safe_get(event_object, "customer_email")
            or ""
        )
        customer_email = _normalize_email(customer_email)
        
        lock_acquired = _acquire_webhook_event_lock(str(event_id or ""))
        if not lock_acquired:
            logger.info("[WEBHOOK] duplicate or in-flight event ignored event_id=%s", event_id)
            return {"received": True, "duplicate": True}

        normalized = {
            "kind": "stripe.webhook",
            "at": datetime.now(timezone.utc).isoformat(),
            "event_id": event_id,
            "event_type": event_type,
            "session_id": session_id,
            "customer_email": customer_email,
            "payment_status": _safe_get(event_object, "payment_status"),
            "status": _safe_get(event_object, "status"),
        }
        _append_payment_event(normalized)
        
        logger.info(
            "[WEBHOOK] received event_type=%s session_id=%s payment_status=%s customer_email=%s",
            event_type,
            session_id,
            payment_status,
            customer_email or "(none)",
        )

        # ========================================
        # TRANSFER CREDITS FROM PENDING TO CURRENT
        # ========================================
        if payment_status == "paid" and session_id and customer_email:
            try:
                # 0. Ensure user exists in Firebase Auth
                logger.info("[WEBHOOK] ensuring user exists for email=%s", customer_email)
                user_uid = _ensure_user_exists_in_auth(customer_email)
                if not user_uid:
                    logger.error("[WEBHOOK] failed to get/create user for email=%s", customer_email)
                    raise ValueError(f"Failed to create/fetch user for {customer_email}")
                
                # 1. Find the checkout event for this session
                events = _read_payment_events()
                checkout_event = None
                for evt in reversed(events):
                    if (evt.get("kind", "").lower() == "checkout.created" 
                        and evt.get("session_id") == session_id):
                        checkout_event = evt
                        break
                
                if checkout_event:
                    tier = str(checkout_event.get("tier", "starter")).strip().lower()
                    quantity = int(checkout_event.get("quantity", 1) or 1)
                    tier_credits = _tier_credit_lookup()
                    unit_credits = int(tier_credits.get(tier, 0))
                    total_credits = unit_credits * quantity
                    
                    # 2. Add credits to Firebase using UID (RTDB path-safe canonical key)
                    env_id = os.getenv("ENV_ID", "default")
                    admin = FirebaseAdmin(user_id=user_uid, env_id=env_id)
                    
                    if admin.db_manager is None:
                        logger.warning("[WEBHOOK] db_manager not available, cannot transfer credits")
                        raise ValueError("Firebase DB manager not available")
                    
                    result = admin.add_credits_atomic(
                        credits=total_credits,
                        operation_id=f"stripe:{event_id}",
                    )
                    
                    logger.info(
                        "[WEBHOOK] credits transferred user_id=%s tier=%s quantity=%s total_credits=%s result=%s",
                        user_uid,
                        tier,
                        quantity,
                        total_credits,
                        result,
                    )
                    
                    # 3. Log transfer event
                    _append_payment_event({
                        "kind": "webhook.processed",
                        "at": datetime.now(timezone.utc).isoformat(),
                        "event_id": event_id,
                        "session_id": session_id,
                        "customer_email": customer_email,
                        "tier": tier,
                        "credits": total_credits,
                        "firebase_result": result,
                    })

                    _record_user_history(
                        uid=user_uid,
                        email=customer_email,
                        action="payment.webhook_processed",
                        status="ok",
                        request_id=str(event_id or session_id or "webhook-processed"),
                        details={
                            "session_id": session_id,
                            "event_type": event_type,
                            "payment_status": payment_status,
                            "credits": total_credits,
                            "tier": tier,
                        },
                    )
                else:
                    logger.warning(
                        "[WEBHOOK] no checkout.created found for session_id=%s email=%s",
                        session_id,
                        customer_email,
                    )
            except Exception as credit_error:
                _record_user_history(
                    uid=user_uid,
                    email=customer_email,
                    action="payment.webhook_processed",
                    status="error",
                    request_id=str(event_id or session_id or "webhook-error"),
                    details={"error": str(credit_error), "session_id": session_id, "event_type": event_type},
                )
                logger.error(
                    "[WEBHOOK] failed to transfer credits session_id=%s email=%s error=%s",
                    session_id,
                    customer_email,
                    credit_error,
                )

        # Send email notification
        if customer_email:
            _send_email_notification(
                to_email=customer_email,
                subject=f"lighter0 webhook update: {event_type}",
                body=(
                    f"Webhook action received.\n\n"
                    f"Event type: {event_type}\n"
                    f"Session ID: {session_id or '(none)'}\n"
                    f"Payment status: {payment_status}\n"
                    f"Checkout status: {_safe_get(event_object, 'status')}\n"
                ),
            )
        else:
            logger.warning("[WEBHOOK] no customer email available for event_id=%s", event_id)

        _finalize_webhook_event_lock(str(event_id or ""), "processed")
        return {"received": True}
    except ValueError as error:
        _record_user_history(
            uid=user_uid,
            email=customer_email,
            action="payment.webhook_processed",
            status="error",
            request_id=str(locals().get("event_id") or "webhook-error"),
            details={"error": str(error)},
        )
        _finalize_webhook_event_lock(str(locals().get("event_id") or ""), "failed", reason=str(error))
        secret_present = bool((os.getenv("STRIPE_WEBHOOK_SECRET") or "").strip())
        signature_present = bool((stripe_signature or "").strip())
        error_text = str(error)

        logger.warning(
            "[WEBHOOK] rejected validation_error=%s secret_present=%s signature_present=%s payload_bytes=%s",
            error_text,
            secret_present,
            signature_present,
            len(payload or b""),
        )

        _append_payment_event(
            {
                "kind": "stripe.webhook.rejected",
                "at": datetime.now(timezone.utc).isoformat(),
                "reason": error_text,
                "secret_present": secret_present,
                "signature_present": signature_present,
            }
        )

        raise HTTPException(status_code=400, detail=error_text)
    except Exception as error:
        _record_user_history(
            uid=user_uid,
            email=customer_email,
            action="payment.webhook_processed",
            status="error",
            request_id=str(locals().get("event_id") or "webhook-error"),
            details={"error": str(error)},
        )
        _finalize_webhook_event_lock(str(locals().get("event_id") or ""), "failed", reason=str(error))
        logger.exception("[WEBHOOK] processing failed: %s", error)
        raise HTTPException(status_code=500, detail=f"Webhook processing failed: {error}")


@app.post("/process", operation_id="process_cover_art", response_model=ProcessResponse)
async def process_cover_art(request: ProcessRequest, http_request: Request) -> ProcessResponse:
    """
    Single route process: Generates cover art from images using the gem.py workflow.
    Includes all parameters from the gem.py pipeline.
    
    Accepts image input (URL, local file, or folder), design parameters, and outputs
    a generated cover image with vector conversion and 3D processing.
    """
    request_id = f"gen-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}"
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    billing_user_id: Optional[str] = None
    env_id = os.getenv("ENV_ID", "default")
    temp_store_dir: Optional[str] = None
    requested_use_free = bool(getattr(request, "use_free", False))

    try:
        logger.info(
            "[PROCESS][%s] start input=%s user_id=%s use_free=%s",
            request_id,
            request.input,
            (request.user_id or "").strip() or "anonymous",
            requested_use_free,
        )

        resolved_uid, resolved_email, _ = _resolve_authenticated_identity(
            request=http_request,
            provided_uid=request.user_id,
            provided_email=request.user_email,
        )
        _validate_identity_fields(resolved_uid, resolved_email)
        _validate_process_dimensions(request.height, request.width)
        _validate_and_limit_pasted_images(request.pasted_images)

        user_id = (resolved_uid or "").strip()
        user_email = (resolved_email or "").strip()
        billing_user_id = _usage_user_id(user_id, user_email)
        if not billing_user_id:
            raise HTTPException(status_code=401, detail="Authenticated identity is required for processing.")
        rl_key = f"process:{billing_user_id}"
        _check_rate_limit(rl_key, RATE_LIMIT_PROCESS_PER_MINUTE, 60)

        _upsert_user_output_space(
            uid=user_id,
            email=user_email,
            run_id=request_id,
            status="started",
            meta={
                "input": bool((request.input or "").strip()),
                "use_free": requested_use_free,
                "height": int(request.height),
                "width": int(request.width),
            },
        )
        _record_user_history(
            uid=user_id,
            email=user_email,
            action="process.started",
            status="ok",
            request_id=request_id,
            details={"use_free": requested_use_free},
        )

        # Resolve API key: use provided key or fall back to environment variable
        api_key = request.gem_api_key or os.getenv("GEM_API_KEY")
        if not api_key:
            raise ValueError("Gemini API key is required. Provide via parameter or GEM_API_KEY env var.")

        cost_credits = _get_single_execution_credit_cost()

        can_use_free_now, _, free_used_today, free_limit = _check_can_use_free_generation(user_id, user_email)
        use_free_execution = requested_use_free and bool(can_use_free_now)

        logger.info(
            "[PROCESS][%s] billing decision requested_use_free=%s effective_use_free=%s free_used_today=%s free_limit=%s cost_credits=%s",
            request_id,
            requested_use_free,
            use_free_execution,
            free_used_today,
            free_limit,
            cost_credits,
        )

        # ── Pre-generation gate: verify free try OR sufficient credits BEFORE any pipeline work ──
        if use_free_execution:
            # Free try granted – no credit check needed.
            logger.info("[PROCESS][%s] access granted via free daily try (%s/%s used)", request_id, free_used_today, free_limit)
        else:
            # Paid path: verify Firebase is reachable and credits are sufficient.
            _billing_admin = FirebaseAdmin(user_id=billing_user_id, env_id=env_id)
            if _billing_admin.db_manager is None:
                raise HTTPException(
                    status_code=503,
                    detail="Unable to validate your credit balance because the billing service is temporarily unavailable. Please try again shortly.",
                )

            available_credits = _billing_admin.get_credits()
            logger.info(
                "[PROCESS][%s] credit check user_id=%s available=%s required=%s",
                request_id,
                billing_user_id,
                available_credits,
                cost_credits,
            )

            if available_credits < cost_credits:
                # Explain why free didn't apply (if the user requested it) so the message is actionable.
                if requested_use_free and not can_use_free_now:
                    free_detail = (
                        f" Your free daily generation has already been used today "
                        f"({free_used_today}/{free_limit})."
                    )
                else:
                    free_detail = ""

                _send_email_notification(
                    to_email=user_email,
                    subject="lighter0: insufficient credits",
                    body=(
                        f"Your generation request could not be processed.\n\n"
                        f"Credits available: {available_credits}\n"
                        f"Credits required:  {cost_credits}\n"
                        f"{free_detail.strip()}\n\n"
                        f"Please purchase additional credits to continue."
                    ),
                )
                raise HTTPException(
                    status_code=402,
                    detail=(
                        f"Insufficient credits: you have {available_credits} credit(s) but "
                        f"{cost_credits} is required for one generation.{free_detail} "
                        f"Please purchase credits to continue."
                    ),
                )

        # Keep generated outputs local-only under output/<user>/<request_id>.
        effective_input = (request.input or "").strip()
        local_user_segment = _safe_output_user_segment(billing_user_id)
        effective_output_dir = os.path.join("output", local_user_segment, request_id)
        input_artifacts: List[GeneratedArtifact] = []
        os.makedirs(os.path.join(_project_root(), effective_output_dir), exist_ok=True)

        if request.pasted_images:
            temp_store_dir, input_artifacts = _store_pasted_images(request_id, request.pasted_images)
            if not input_artifacts:
                raise ValueError("pasted_images were provided but no valid image payloads were saved")
            effective_input = temp_store_dir
            logger.info(
                "[PROCESS][%s] temp_store input enabled dir=%s saved_images=%s output_dir=%s",
                request_id,
                _safe_relpath(temp_store_dir, _project_root()),
                len(input_artifacts),
                effective_output_dir,
            )
        
        # 1. Load images only when an explicit input source exists.
        images = []
        if effective_input:
            logger.info("[PROCESS][%s] loading images from input", request_id)
            images = load_image_source(effective_input)
            if images:
                logger.info("[PROCESS][%s] loaded_images=%s", request_id, len(images))
            else:
                logger.info("[PROCESS][%s] no images loaded from input=%s; continuing without images", request_id, effective_input)
        else:
            logger.info("[PROCESS][%s] no input source provided; continuing without images", request_id)
        
        # 2. Create args namespace to mimic command-line args
        args = argparse.Namespace(
            input=effective_input,
            theme=request.theme,
            bg_texture=request.bg_texture,
            math=request.math,
            name=request.name,
            typo=request.typo,
            colors=request.colors,
            tags=request.tags,
            output_dir=effective_output_dir,
            height=request.height,
            width=request.width
        )
        
        # 3. Run the generation pipeline
        logger.info("[PROCESS][%s] generation pipeline started", request_id)
        pipeline_result = run_generation_pipeline(
            images=images,
            theme=request.theme,
            bg_texture=request.bg_texture,
            math_rule=request.math,
            product_name=request.name,
            typo_style=request.typo,
            color_palette=request.colors,
            tags=request.tags,
            output_dir=effective_output_dir,
            args=args,
            gem_api_key=api_key,
            height=request.height,
            width=request.width,
            generate_svg=request.generate_svg,
            generate_stl=request.generate_stl,
            generate_html=request.generate_html,
            generate_animation=request.generate_animation,
        )

        run_dir_value = None
        if isinstance(pipeline_result, dict):
            run_dir_value = pipeline_result.get("run_dir")

        if not run_dir_value:
            raise RuntimeError("Generation pipeline did not return a run directory.")

        run_dir = os.path.abspath(run_dir_value)
        artifacts, preview_image_data_url = _collect_artifacts(run_dir)
        validated_artifacts = _validated_artifacts(artifacts)
        invalid_artifacts = len(artifacts) - len(validated_artifacts)
        stack_download_url = None
        local_copy_dir_rel = None

        logger.info(
            "[PROCESS][%s] artifacts collected total=%s validated=%s invalid=%s run_dir=%s",
            request_id,
            len(artifacts),
            len(validated_artifacts),
            invalid_artifacts,
            _safe_relpath(run_dir, _project_root()),
        )

        firebase_files: List[dict] = []
        logger.info("[PROCESS][%s] cloud media persistence disabled; returning run artifacts only", request_id)

        output_file_records: List[Dict[str, Any]] = []
        for item in validated_artifacts:
            output_file_records.append(
                {
                    "name": item.name,
                    "mime_type": item.mime_type,
                    "relative_path": item.relative_path,
                    "size_bytes": item.size_bytes,
                    "view_url": item.view_url,
                    "download_url": item.download_url,
                }
            )

        _upsert_user_output_space(
            uid=user_id,
            email=user_email,
            run_id=request_id,
            status="completed" if validated_artifacts else "no_artifacts",
            meta={
                "run_dir": _safe_relpath(run_dir, _project_root()),
                "local_copy_dir": local_copy_dir_rel,
                "validated_artifacts": len(validated_artifacts),
                "storage_mode": "local_only",
            },
            files=output_file_records,
        )
        
        # Charge/consume only when validated artifacts are ready for frontend consumption.
        if validated_artifacts:
            if use_free_execution:
                success = _consume_daily_free_try(user_id, user_email, request_id)
                if success:
                    logger.info("[PROCESS][%s] free generation consumed user_id=%s", request_id, billing_user_id)
                else:
                    logger.warning("[PROCESS][%s] failed to mark free generation user_id=%s", request_id, billing_user_id)
            else:
                admin = FirebaseAdmin(user_id=billing_user_id, env_id=env_id)
                try:
                    deduction_result = admin.deduct_credits_atomic(
                        credits=cost_credits,
                        operation_id=f"run:{request_id}",
                        require_full_amount=True,
                    )
                except ValueError as deduction_error:
                    if "insufficient credits" in str(deduction_error).lower():
                        raise HTTPException(status_code=402, detail="insufficient credits for execution")
                    raise
                logger.info(
                    "[PROCESS][%s] credits deducted user_id=%s cost=%s result=%s",
                    request_id,
                    billing_user_id,
                    cost_credits,
                    deduction_result,
                )

            try:
                _record_workflow_execution(
                    uid=user_id,
                    email=user_email,
                    request_id=request_id,
                    mode="free" if use_free_execution else "paid",
                    cost_credits=0 if use_free_execution else cost_credits,
                )
            except Exception as usage_error:
                logger.warning("[PROCESS][%s] usage tracking failed: %s", request_id, usage_error)

            _record_user_history(
                uid=user_id,
                email=user_email,
                action="process.completed",
                status="ok",
                request_id=request_id,
                details={
                    "mode": "free" if use_free_execution else "paid",
                    "validated_artifacts": len(validated_artifacts),
                },
            )
        else:
            logger.warning(
                "[PROCESS][%s] skipping free/credit mutation because no validated artifacts were returned",
                request_id,
            )
            _record_user_history(
                uid=user_id,
                email=user_email,
                action="process.completed",
                status="error",
                request_id=request_id,
                details={"error": "no validated artifacts"},
            )
        
        refreshed_free_generation_status = _get_free_generation_status_snapshot(user_id, user_email)

        return ProcessResponse(
            success=True,
            message="Cover art generation completed successfully",
            output_dir=_safe_relpath(effective_output_dir, _project_root()),
            run_dir=_safe_relpath(run_dir, _project_root()),
            input_artifacts=input_artifacts,
            artifacts=validated_artifacts,
            stack_download_url=stack_download_url,
            local_copy_dir=local_copy_dir_rel,
            preview_image_data_url=preview_image_data_url,
            firebase_files=firebase_files,
            free_generation_status=refreshed_free_generation_status,
        )
        
    except ValueError as ve:
        _upsert_user_output_space(
            uid=user_id,
            email=user_email,
            run_id=request_id,
            status="failed",
            meta={"error": str(ve), "storage_mode": "local_only"},
        )
        _record_user_history(
            uid=user_id,
            email=user_email,
            action="process.failed",
            status="error",
            request_id=request_id,
            details={"error": str(ve)},
        )
        logger.error("[PROCESS] validation error: %s", str(ve))
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        _upsert_user_output_space(
            uid=user_id,
            email=user_email,
            run_id=request_id,
            status="failed",
            meta={"error": str(e), "storage_mode": "local_only"},
        )
        _record_user_history(
            uid=user_id,
            email=user_email,
            action="process.failed",
            status="error",
            request_id=request_id,
            details={"error": str(e)},
        )
        logger.exception("[PROCESS] generation failed request_id=%s error=%s", request_id, e)
        return ProcessResponse(
            success=False,
            message="Cover art generation failed",
            error="Internal processing error"
        )


@app.get("/files/view/{file_path:path}", operation_id="view_generated_file")
async def view_generated_file(file_path: str):
    absolute = _resolve_output_file(file_path)
    mime_type = mimetypes.guess_type(absolute)[0] or "application/octet-stream"
    return FileResponse(path=absolute, media_type=mime_type)


@app.get("/files/download/{file_path:path}", operation_id="download_generated_file")
async def download_generated_file(file_path: str):
    absolute = _resolve_output_file(file_path)
    filename = os.path.basename(absolute)
    return FileResponse(path=absolute, media_type="application/octet-stream", filename=filename)


@app.get("/files/download-stack/{dir_path:path}", operation_id="download_generated_stack")
async def download_generated_stack(dir_path: str):
    absolute_dir = _resolve_output_dir(dir_path)
    zip_bytes = _build_stack_zip_bytes(absolute_dir)
    run_name = os.path.basename(absolute_dir.rstrip(os.sep)) or "stack"
    file_name = f"{run_name}_stack.zip"
    headers = {"Content-Disposition": f'attachment; filename="{file_name}"'}
    return StreamingResponse(io.BytesIO(zip_bytes), media_type="application/zip", headers=headers)


# ---------------------------------------------------------------------------
# Admin: Stripe Reconciliation
# ---------------------------------------------------------------------------

def _verify_admin_key(x_admin_key: Optional[str] = Header(default=None)) -> None:
    """Dependency: validate X-Admin-Key header against ADMIN_SECRET_KEY env var."""
    secret = (os.getenv("ADMIN_SECRET_KEY") or "").strip()
    if not secret or len(secret) < 16:
        raise HTTPException(status_code=503, detail="Admin key is not configured on this server.")
    provided = (x_admin_key or "").strip()
    if not provided or provided != secret:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Key header.")


@app.get("/admin/reconcile", operation_id="admin_reconcile_payments")
async def admin_reconcile_payments(
    days: int = 7,
    x_admin_key: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Reconcile Stripe paid checkout sessions against RTDB webhook records.

    Returns a report of sessions that are paid in Stripe but missing or failed
    in the webhook processing store (potential missed credit grants).

    Protected by X-Admin-Key header (ADMIN_SECRET_KEY env var, min 16 chars).
    """
    _verify_admin_key(x_admin_key)

    days_clamped = max(1, min(int(days), 30))
    since_ts = int((datetime.now(timezone.utc).timestamp()) - days_clamped * 86400)

    sessions_checked = 0
    processed_ok: List[str] = []
    missing_or_failed: List[Dict[str, Any]] = []
    stripe_errors: List[str] = []

    try:
        params: Dict[str, Any] = {"limit": 100, "created": {"gte": since_ts}}
        has_more = True
        starting_after = None

        while has_more:
            if starting_after:
                params["starting_after"] = starting_after
            page = stripe.checkout.Session.list(**params)
            sessions = list(page.data or [])
            has_more = bool(page.has_more)
            if sessions:
                starting_after = sessions[-1].id

            for session in sessions:
                sessions_checked += 1
                sid = session.id if hasattr(session, "id") else str(session.get("id", ""))
                payment_status = (
                    session.payment_status if hasattr(session, "payment_status")
                    else session.get("payment_status", "")
                ) or ""
                payment_intent = (
                    session.payment_intent if hasattr(session, "payment_intent")
                    else session.get("payment_intent")
                )

                if payment_status.lower() != "paid":
                    continue

                # Determine the event key used for idempotency lock
                # Webhooks are keyed by payment_intent id when available, else session id
                lock_key = str(payment_intent or sid).strip()
                rtdb_state: Optional[Dict[str, Any]] = None
                try:
                    admin = FirebaseAdmin(user_id="system", env_id=os.getenv("ENV_ID", "default"))
                    if admin.db_manager:
                        raw = admin.db_manager.get_data(path=_webhook_state_path(lock_key))
                        if isinstance(raw, dict):
                            rtdb_state = raw
                except Exception as _rtdb_err:
                    logger.warning("[RECONCILE] RTDB lookup failed for %s: %s", lock_key, _rtdb_err)

                webhook_status = str((rtdb_state or {}).get("status") or "").strip().lower()
                customer_email_raw = (
                    session.customer_email if hasattr(session, "customer_email")
                    else session.get("customer_email")
                )
                metadata_raw = (
                    dict(session.metadata) if hasattr(session, "metadata") and session.metadata
                    else dict(session.get("metadata") or {})
                )
                entry = {
                    "session_id": sid,
                    "payment_intent": lock_key,
                    "customer_email": customer_email_raw,
                    "metadata": metadata_raw,
                    "webhook_status": webhook_status or "not_found",
                }

                if webhook_status == "processed":
                    processed_ok.append(sid)
                else:
                    missing_or_failed.append(entry)

    except HTTPException:
        raise
    except stripe.error.StripeError as stripe_err:
        stripe_errors.append(str(stripe_err))
        logger.error("[RECONCILE] Stripe error: %s", stripe_err)
    except Exception as err:
        logger.exception("[RECONCILE] Unexpected error: %s", err)
        raise HTTPException(status_code=500, detail="Reconciliation failed unexpectedly.")

    return JSONResponse(content={
        "ok": True,
        "since_days": days_clamped,
        "sessions_checked": sessions_checked,
        "processed_count": len(processed_ok),
        "missing_or_failed_count": len(missing_or_failed),
        "missing_or_failed": missing_or_failed,
        "stripe_errors": stripe_errors,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })


@app.get("/admin/webhook-selftest", operation_id="admin_webhook_selftest")
async def admin_webhook_selftest(
    x_admin_key: Optional[str] = Header(default=None),
) -> JSONResponse:
    """Return a safe snapshot of the webhook setup for operator verification."""
    _verify_admin_key(x_admin_key)

    testing_mode = (os.getenv("TESTING") or "false").strip().lower() == "true"
    expected_public_base_url = TESTING_REDIRECT_BASE_URL if testing_mode else DEFAULT_REDIRECT_BASE_URL
    webhook_urls = [
        f"{expected_public_base_url}/payment/webhook",
        f"{expected_public_base_url}/api/payment/webhook",
    ]

    return JSONResponse(content={
        "success": True,
        "testing": testing_mode,
        "public_base_url": expected_public_base_url,
        "webhook_urls": webhook_urls,
        "stripe_webhook_secret_configured": bool((os.getenv("STRIPE_WEBHOOK_SECRET") or "").strip()),
        "admin_secret_configured": bool((os.getenv("ADMIN_SECRET_KEY") or "").strip()),
        "expected_public_port": 8000,
        "expected_webhook_response_without_signature": {
            "status_code": 400,
            "detail": "Missing Stripe signature header.",
        },
    })



