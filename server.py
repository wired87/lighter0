from typing import Optional, List, Any, Dict, Tuple
import os
import argparse
import json
import mimetypes
import base64
import logging
import smtplib
from datetime import datetime, timezone
from urllib.parse import quote
from email.message import EmailMessage

from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, FileResponse
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
    use_free: bool = Field(default=False, description="Whether this generation uses the user's free daily generation")


class GeneratedArtifact(BaseModel):
    name: str
    relative_path: str
    mime_type: str
    size_bytes: int
    view_url: str
    download_url: str


class ProcessResponse(BaseModel):
    """Response body for the process endpoint."""
    
    success: bool = Field(description="Whether the process completed successfully")
    message: str = Field(description="Status message")
    output_dir: Optional[str] = Field(default=None, description="Directory where output was saved")
    run_dir: Optional[str] = Field(default=None, description="Run-specific output directory")
    input_artifacts: List[GeneratedArtifact] = Field(default_factory=list, description="Temp-store input files")
    artifacts: List[GeneratedArtifact] = Field(default_factory=list, description="Generated local files")
    preview_image_data_url: Optional[str] = Field(default=None, description="Base64 preview for generated jpg")
    firebase_files: List[dict] = Field(default_factory=list, description="Uploaded Firebase file metadata")
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
    free_generations_used: int = Field(description="Number of free generations used today (0 or 1)")
    last_free_generation_date: Optional[str] = Field(default=None, description="ISO date of last free generation")
    error: Optional[str] = None


class CheckoutStatusResponse(BaseModel):
    success: bool
    message: str
    checkout: Optional[dict] = None
    error: Optional[str] = None


class UserProfileResponse(BaseModel):
    success: bool
    message: str
    user: Optional[dict] = None
    error: Optional[str] = None


app = FastAPI(title="lighter0", version="1.0.0", docs_url="/docs", openapi_url="/openapi.json")

logger = logging.getLogger("lighter0.server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
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


def _read_payment_events() -> List[dict]:
    events_file = os.path.join(_payments_dir(), "events.jsonl")
    if not os.path.isfile(events_file):
        return []

    parsed: List[dict] = []
    with open(events_file, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = (raw or "").strip()
            if not line:
                continue
            try:
                parsed.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return parsed


def _is_valid_email(value: Optional[str]) -> bool:
    if value is None:
        return True
    email = value.strip()
    return "@" in email and "." in email and " " not in email


def _request_base_url(request: Request) -> str:
    forwarded_proto = str(request.headers.get("x-forwarded-proto") or "").strip()
    forwarded_host = str(request.headers.get("x-forwarded-host") or "").strip()

    scheme = (forwarded_proto.split(",")[0].strip() if forwarded_proto else request.url.scheme) or "https"
    host = (forwarded_host.split(",")[0].strip() if forwarded_host else str(request.headers.get("host") or "").strip())
    if not host:
        host = str(request.url.netloc or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail="Could not resolve request host for checkout redirection.")

    return f"{scheme}://{host}"


def _checkout_redirect_urls(request: Request) -> Dict[str, str]:
    base_url = _request_base_url(request).rstrip("/")
    return {
        "success_url": f"{base_url}/?checkout=success",
        "cancel_url": f"{base_url}/?checkout=cancel",
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


def _resolve_output_file(file_path: str) -> str:
    output_root = _default_output_dir()
    cleaned = os.path.normpath((file_path or "").strip()).lstrip("/\\")
    absolute = os.path.abspath(os.path.join(_project_root(), cleaned))

    if not absolute.startswith(output_root + os.sep):
        raise HTTPException(status_code=403, detail="File path is outside output directory.")
    if not os.path.isfile(absolute):
        raise HTTPException(status_code=404, detail="File not found.")
    return absolute


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
        decoded = base64.b64decode(payload)
        return decoded, mime_type

    # Fallback: assume plain base64 without data URL header.
    decoded = base64.b64decode(raw)
    return decoded, "application/octet-stream"


def _store_pasted_images(request_id: str, pasted_images: List[Dict[str, str]]) -> Tuple[str, List[GeneratedArtifact]]:
    temp_store_dir = os.path.join(_default_output_dir(), "temp_store", request_id)
    os.makedirs(temp_store_dir, exist_ok=True)

    artifacts: List[GeneratedArtifact] = []
    project_root = _project_root()

    for idx, item in enumerate(pasted_images, start=1):
        if not isinstance(item, dict):
            continue

        data_url = str(item.get("data_url") or "").strip()
        if not data_url:
            continue

        file_bytes, mime_type = _decode_data_url(data_url)
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

    paid_credits = sum(item["credits"] for item in purchases if item["is_paid"])
    pending_credits = sum(item["credits"] for item in purchases if not item["is_paid"])

    user = {
        "uid": uid_key or None,
        "email": email_key or None,
        "credits": paid_credits,
        "pending_credits": pending_credits,
        "paid_purchases": sum(1 for item in purchases if item["is_paid"]),
        "pending_purchases": sum(1 for item in purchases if not item["is_paid"]),
        "purchases": sorted(purchases, key=lambda x: x.get("at") or "", reverse=True)[:8],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    return user


def _get_today_iso_date() -> str:
    """Return today's date in ISO format (YYYY-MM-DD)"""
    return datetime.now(timezone.utc).date().isoformat()


def _check_can_use_free_generation(uid: Optional[str], email: Optional[str]) -> tuple[bool, Optional[str]]:
    """
    Check if a user can use their free generation today.
    Returns (can_use_free, last_free_generation_date)
    """
    if not uid and not email:
        return False, None
    
    try:
        from firebase_admin import auth as fb_auth
        
        user_record = None
        if uid:
            try:
                user_record = fb_auth.get_user(uid)
            except Exception:
                return True, None  # user not found, can use free
        elif email:
            try:
                user_record = fb_auth.get_user_by_email(email)
            except Exception:
                return True, None
        
        if not user_record:
            return True, None
        
        # Get custom claims
        custom_claims = user_record.custom_claims or {}
        last_free_date = custom_claims.get("last_free_generation_date")
        
        if not last_free_date:
            return True, None
        
        # Check if last free generation was today
        today = _get_today_iso_date()
        if last_free_date == today:
            return False, last_free_date  # Already used today
        
        return True, last_free_date
    except Exception as e:
        print(f"[WARN] Error checking free generation status: {e}")
        return True, None  # Default to allowing free if error


def _mark_free_generation_used(uid: Optional[str], email: Optional[str]) -> bool:
    """
    Mark that a user has used their free generation today.
    Returns True if successful, False otherwise.
    """
    if not uid and not email:
        return False
    
    try:
        from firebase_admin import auth as fb_auth
        
        user_record = None
        if uid:
            try:
                user_record = fb_auth.get_user(uid)
            except Exception:
                return False
        elif email:
            try:
                user_record = fb_auth.get_user_by_email(email)
            except Exception:
                return False
        
        if not user_record:
            return False
        
        # Update custom claims
        today = _get_today_iso_date()
        fb_auth.set_custom_user_claims(
            user_record.uid,
            {"last_free_generation_date": today}
        )
        return True
    except Exception as e:
        print(f"[WARN] Error marking free generation as used: {e}")
        return False


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
    try:
        claims = request.user or {}
        if not isinstance(claims, dict) or not claims:
            raise HTTPException(status_code=400, detail="Missing user payload.")

        env_id = os.getenv("ENV_ID", "default")
        user_id = str(claims.get("sub") or claims.get("email") or claims.get("uid") or "default")
        admin = FirebaseAdmin(user_id=user_id, env_id=env_id)

        created_user = admin.create_user_from_google_claims(claims)

        return AuthUserResponse(
            success=True,
            message="User processed successfully",
            user=created_user,
        )
    except HTTPException:
        raise
    except ValueError as ve:
        if _is_firebase_config_error(ve):
            return AuthUserResponse(
                success=True,
                message="Authenticated user accepted; Firebase sync is not configured.",
                user=_local_auth_user_from_claims(request.user or {}),
                error=str(ve),
            )
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
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
async def get_user_profile(email: Optional[str] = None, uid: Optional[str] = None) -> UserProfileResponse:
    try:
        cleaned_email = (email or "").strip()
        cleaned_uid = (uid or "").strip()
        if not cleaned_email and not cleaned_uid:
            raise HTTPException(status_code=400, detail="Provide email or uid.")

        user = _resolve_user_profile(cleaned_email, cleaned_uid)
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
async def check_free_generation_status(email: Optional[str] = None, uid: Optional[str] = None) -> FreeGenerationStatusResponse:
    try:
        cleaned_email = (email or "").strip()
        cleaned_uid = (uid or "").strip()
        if not cleaned_email and not cleaned_uid:
            raise HTTPException(status_code=400, detail="Provide email or uid.")

        can_use_free, last_free_date = _check_can_use_free_generation(cleaned_uid, cleaned_email)
        free_used = 1 if last_free_date and last_free_date == _get_today_iso_date() else 0
        
        return FreeGenerationStatusResponse(
            success=True,
            message="Free generation status retrieved",
            can_use_free=can_use_free,
            free_generations_used=free_used,
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
            error=str(error),
        )


@app.post("/checkout", operation_id="create_checkout", response_model=CheckoutResponse)
async def create_checkout(request: CheckoutRequest, http_request: Request) -> CheckoutResponse:
    try:
        tier_value = (request.tier or "").strip().lower()
        if tier_value not in {item.value for item in CreditTier}:
            raise HTTPException(status_code=400, detail="Invalid tier. Use starter, professional, or enterprise.")

        # Normalize and validate email
        normalized_email = _normalize_email(request.customer_email)
        if not normalized_email:
            raise HTTPException(status_code=400, detail="Invalid customer_email format.")

        tier = CreditTier(tier_value)
        metadata = {
            "source": "lighter0_api",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if request.user_id:
            metadata["user_id"] = request.user_id.strip()

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
        raise HTTPException(status_code=400, detail=str(error))
    except stripe.error.StripeError as error:
        raise HTTPException(status_code=502, detail=f"Stripe error while creating checkout: {error}")
    except Exception as error:
        return CheckoutResponse(
            success=False,
            message="Failed to create checkout session",
            error=str(error),
        )


@app.get("/checkout/{session_id}", operation_id="get_checkout_state", response_model=CheckoutStatusResponse)
async def checkout_status(session_id: str) -> CheckoutStatusResponse:
    try:
        info = get_checkout_status(session_id)

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


@app.post("/payment/webhook", operation_id="stripe_webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(default=None, alias="Stripe-Signature"),
):
    payload = await request.body()

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
        
        normalized = {
            "kind": "stripe.webhook",
            "at": datetime.now(timezone.utc).isoformat(),
            "event_id": event_id,
            "event_type": event_type,
            "session_id": session_id,
            "payment_status": _safe_get(event_object, "payment_status"),
            "status": _safe_get(event_object, "status"),
        }
        _append_payment_event(normalized)

        # Extract and normalize customer email
        customer_email = (
            _safe_get(_safe_get(event_object, "customer_details", {}), "email")
            or _safe_get(event_object, "customer_email")
            or ""
        )
        customer_email = _normalize_email(customer_email)
        
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
                for evt in events:
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
                    
                    # 2. Add credits to Firebase using user's email as identifier
                    env_id = os.getenv("ENV_ID", "default")
                    admin = FirebaseAdmin(user_id=customer_email, env_id=env_id)
                    
                    if admin.db_manager is None:
                        logger.warning("[WEBHOOK] db_manager not available, cannot transfer credits")
                        raise ValueError("Firebase DB manager not available")
                    
                    result = admin.add_credits(total_credits)
                    
                    logger.info(
                        "[WEBHOOK] credits transferred user_id=%s tier=%s quantity=%s total_credits=%s result=%s",
                        customer_email,
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
                else:
                    logger.warning(
                        "[WEBHOOK] no checkout.created found for session_id=%s email=%s",
                        session_id,
                        customer_email,
                    )
            except Exception as credit_error:
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

        return {"received": True}
    except ValueError as error:
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
        logger.exception("[WEBHOOK] processing failed: %s", error)
        raise HTTPException(status_code=500, detail=f"Webhook processing failed: {error}")


@app.post("/process", operation_id="process_cover_art", response_model=ProcessResponse)
async def process_cover_art(request: ProcessRequest) -> ProcessResponse:
    """
    Single route process: Generates cover art from images using the gem.py workflow.
    Includes all parameters from the gem.py pipeline.
    
    Accepts image input (URL, local file, or folder), design parameters, and outputs
    a generated cover image with vector conversion and 3D processing.
    """
    try:
        request_id = f"gen-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}"
        logger.info(
            "[PROCESS][%s] start input=%s user_id=%s use_free=%s",
            request_id,
            request.input,
            (request.user_id or "").strip() or "anonymous",
            request.use_free,
        )

        # Resolve API key: use provided key or fall back to environment variable
        api_key = request.gem_api_key or os.getenv("GEM_API_KEY")
        if not api_key:
            raise ValueError("Gemini API key is required. Provide via parameter or GEM_API_KEY env var.")

        # Default paths. If pasted images are provided, both input and output switch to temp store.
        effective_input = (request.input or "").strip()
        effective_output_dir = "output"
        input_artifacts: List[GeneratedArtifact] = []
        os.makedirs(_default_output_dir(), exist_ok=True)

        if request.pasted_images:
            temp_store_dir, input_artifacts = _store_pasted_images(request_id, request.pasted_images)
            if not input_artifacts:
                raise ValueError("pasted_images were provided but no valid image payloads were saved")
            effective_input = temp_store_dir
            effective_output_dir = temp_store_dir
            logger.info(
                "[PROCESS][%s] temp_store enabled dir=%s saved_images=%s",
                request_id,
                _safe_relpath(temp_store_dir, _project_root()),
                len(input_artifacts),
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

        logger.info(
            "[PROCESS][%s] artifacts collected total=%s validated=%s invalid=%s run_dir=%s",
            request_id,
            len(artifacts),
            len(validated_artifacts),
            invalid_artifacts,
            _safe_relpath(run_dir, _project_root()),
        )

        firebase_files: List[dict] = []
        user_id = (request.user_id or os.getenv("USER_ID") or "default").strip() or "default"
        user_email = (request.user_email or "").strip()
        env_id = os.getenv("ENV_ID", "default")

        if not request.use_free:
            try:
                admin = FirebaseAdmin(user_id=user_id, env_id=env_id)
                available_credits = admin.get_credits()
                logger.info(
                    "[PROCESS][%s] available credits check user_id=%s credits=%s",
                    request_id,
                    user_id,
                    available_credits,
                )
                if available_credits <= 0:
                    _send_email_notification(
                        to_email=user_email,
                        subject="lighter0: no credits available",
                        body="no credits available",
                    )
                    raise HTTPException(status_code=402, detail="no credits available")
            except HTTPException:
                raise
            except Exception as credit_check_error:
                logger.warning(
                    "[PROCESS][%s] credit availability check failed user_id=%s error=%s",
                    request_id,
                    user_id,
                    credit_check_error,
                )

        if validated_artifacts:
            try:
                admin = FirebaseAdmin(user_id=user_id, env_id=env_id)
                rel_paths = [item.relative_path for item in validated_artifacts]
                firebase_files = admin.upload_local_files_to_user_folder(
                    project_root=_project_root(),
                    relative_paths=rel_paths,
                )
                logger.info(
                    "[PROCESS][%s] firebase upload success uploaded=%s",
                    request_id,
                    len(firebase_files),
                )
            except Exception as upload_error:
                logger.warning("[PROCESS][%s] firebase upload skipped: %s", request_id, upload_error)
        
        # Charge/consume only when validated artifacts are ready for frontend consumption.
        if validated_artifacts:
            if request.use_free:
                success = _mark_free_generation_used(user_id, None)
                if success:
                    logger.info("[PROCESS][%s] free generation consumed user_id=%s", request_id, user_id)
                else:
                    logger.warning("[PROCESS][%s] failed to mark free generation user_id=%s", request_id, user_id)
            else:
                try:
                    admin = FirebaseAdmin(user_id=user_id, env_id=env_id)
                    credit_deduction_cost = 1
                    deduction_result = admin.deduct_credits(credit_deduction_cost)
                    logger.info(
                        "[PROCESS][%s] credits deducted user_id=%s result=%s",
                        request_id,
                        user_id,
                        deduction_result,
                    )
                except Exception as deduction_error:
                    logger.warning("[PROCESS][%s] credit deduction failed: %s", request_id, deduction_error)
        else:
            logger.warning(
                "[PROCESS][%s] skipping free/credit mutation because no validated artifacts were returned",
                request_id,
            )
        
        return ProcessResponse(
            success=True,
            message="Cover art generation completed successfully",
            output_dir=_safe_relpath(os.path.abspath(effective_output_dir), _project_root()),
            run_dir=_safe_relpath(run_dir, _project_root()),
            input_artifacts=input_artifacts,
            artifacts=validated_artifacts,
            preview_image_data_url=preview_image_data_url,
            firebase_files=firebase_files,
        )
        
    except ValueError as ve:
        logger.error("[PROCESS] validation error: %s", str(ve))
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        error_msg = f"Cover art generation failed: {str(e)}"
        logger.exception("[PROCESS] %s", error_msg)
        return ProcessResponse(
            success=False,
            message="Cover art generation failed",
            error=error_msg
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




