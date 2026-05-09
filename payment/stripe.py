#!/usr/bin/env python3
"""
Stripe payment logic for credit package checkout.

SaaS best practice:
- One product (STRIPE_PRODUCT_ID) represents one credit unit.
- Each tier defines how many credits (quantity) the user buys.
- Price per unit is fetched live from Stripe (product's default_price).
- Checkout: line_item = { price: <price_id>, quantity: <tier_credits> }
- Total price = unit_price * quantity (calculated by Stripe).
- No hardcoded price IDs. No fallback dummy prices.
"""

import os
import logging
from enum import Enum
from typing import Optional, Any, Dict
from datetime import datetime, timezone

import stripe
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

stripe.api_key = os.getenv("STRIPE_API_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STALE_PAYMENT_WINDOW_SECONDS = int(os.getenv("STALE_PAYMENT_WINDOW_SECONDS", "900"))

_resolved_price_cache: Optional[Dict[str, Any]] = None


class CreditTier(str, Enum):
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class PaymentConfig:
    PRODUCT_ID = (os.getenv("STRIPE_PRODUCT_ID") or "").strip()

    TIERS = {
        CreditTier.STARTER:      {"name": "Starter",      "quantity": int(os.getenv("STRIPE_AMOUNT_STARTER",      "100"))},
        CreditTier.PROFESSIONAL: {"name": "Professional",  "quantity": int(os.getenv("STRIPE_AMOUNT_PROFESSIONAL", "500"))},
        CreditTier.ENTERPRISE:   {"name": "Enterprise",    "quantity": int(os.getenv("STRIPE_AMOUNT_ENTERPRISE",  "1500"))},
    }

    SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL", "")
    CANCEL_URL  = os.getenv("STRIPE_CANCEL_URL",  "")


def _fmt(unit_amount: int, currency: str) -> str:
    sym = "$" if currency.lower() == "usd" else ""
    val = unit_amount / 100
    return f"{sym}{val:.2f}" if sym else f"{val:.2f} {currency.upper()}"


def _fetch_price_from_stripe() -> Dict[str, Any]:
    """
    Fetch the active price for the configured product from Stripe.
    Strategy: use product default_price, else first active price.
    """
    if not PaymentConfig.PRODUCT_ID:
        raise ValueError(
            "STRIPE_PRODUCT_ID is not set. Add it to .env: STRIPE_PRODUCT_ID=prod_xxx"
        )

    logger.info("[STRIPE] Fetching price for product %s", PaymentConfig.PRODUCT_ID)

    try:
        product = stripe.Product.retrieve(
            PaymentConfig.PRODUCT_ID,
            #expand=["default_price"],
        )
        print("STRIPE PRODUCT RECEIVED:")
    except stripe.error.InvalidRequestError as exc:
        raise ValueError(
            f"Product '{PaymentConfig.PRODUCT_ID}' not found in Stripe. "
            f"Check that STRIPE_PRODUCT_ID and STRIPE_API_KEY belong to the same Stripe account. "
            f"Detail: {exc}"
        ) from exc

    # Use default_price if available
    default_price = os.getenv("STRIPE_PRICE_ID")
    if default_price:
        if isinstance(default_price, str):
            p = stripe.Price.retrieve(default_price)
            print("STRIPE PRICE RECEIVED:", p)
        else:
            p = default_price
        pid         = p.get("id") if isinstance(p, dict) else p.id
        unit_amount = int(p.get("unit_amount", 0) if isinstance(p, dict) else p.unit_amount or 0)
        currency    = str(p.get("currency", "usd") if isinstance(p, dict) else p.currency or "usd").lower()
        logger.info("[STRIPE] Using default_price %s — %s/unit", pid, _fmt(unit_amount, currency))
        return {"price_id": pid, "product_id": PaymentConfig.PRODUCT_ID, "unit_amount": unit_amount, "currency": currency}

    # Fallback: first active price of this product
    prices = stripe.Price.list(product=PaymentConfig.PRODUCT_ID, active=True, limit=1)
    data   = list(prices.data or [])
    if not data:
        raise ValueError(
            f"No active price found for product '{PaymentConfig.PRODUCT_ID}'. "
            f"Go to Stripe Dashboard → Products → {PaymentConfig.PRODUCT_ID} → Add a price."
        )
    p = data[0]
    logger.info("[STRIPE] Using first active price %s — %s/unit", p.id, _fmt(p.unit_amount or 0, p.currency or "usd"))
    return {
        "price_id":   p.id,
        "product_id": str(p.product),
        "unit_amount": int(p.unit_amount or 0),
        "currency":   str(p.currency or "usd").lower(),
    }


def get_active_price(force_refresh: bool = False) -> Dict[str, Any]:
    global _resolved_price_cache
    if _resolved_price_cache is None or force_refresh:
        _resolved_price_cache = _fetch_price_from_stripe()
    return _resolved_price_cache


def get_payment_catalog() -> Dict[str, Any]:
    price       = get_active_price()
    unit_amount = price["unit_amount"]
    currency    = price["currency"]
    price_id    = price["price_id"]
    product_id  = price["product_id"]

    tiers = []
    for tier, cfg in PaymentConfig.TIERS.items():
        qty   = cfg["quantity"]
        total = unit_amount * qty
        tiers.append({
            "tier":               tier.value,
            "name":               cfg["name"],
            "credits":            qty,
            "quantity":           qty,
            "price_id":           price_id,
            "product_id":         product_id,
            "unit_price_cents":   unit_amount,
            "unit_price_display": _fmt(unit_amount, currency),
            "total_price_cents":  total,
            "price_display":      _fmt(total, currency),
            "currency":           currency,
        })

    return {
        "product_id":         product_id,
        "price_id":           price_id,
        "currency":           currency,
        "unit_price_cents":   unit_amount,
        "unit_price_display": _fmt(unit_amount, currency),
        "tiers":              tiers,
    }


def get_payment_catalog_stable() -> Dict[str, Any]:
    return get_payment_catalog()


def list_all_tiers() -> list:
    return get_payment_catalog()["tiers"]


def validate_config() -> bool:
    if not stripe.api_key:
        raise ValueError("STRIPE_API_KEY is not configured.")
    if not PaymentConfig.PRODUCT_ID:
        raise ValueError("STRIPE_PRODUCT_ID is not configured.")
    return True


def create_checkout_session(
    tier, 
    quantity=1, 
    customer_email=None, 
    metadata=None, 
    success_url=None, 
    cancel_url=None
    ) -> str:
    return create_checkout_session_payload(
        tier=tier, quantity=quantity, customer_email=customer_email,
        metadata=metadata, success_url=success_url, cancel_url=cancel_url,
    )["checkout_url"]


def create_checkout_session_payload(
    tier: CreditTier,
    quantity: int = 1,
    customer_email: Optional[str] = None,
    metadata: Optional[dict] = None,
    success_url: Optional[str] = None,
    cancel_url: Optional[str] = None,
) -> Dict[str, Any]:
    validate_config()

    if tier not in PaymentConfig.TIERS:
        raise ValueError(f"Invalid tier: {tier}. Valid: {[t.value for t in CreditTier]}")
    if quantity < 1:
        raise ValueError("quantity must be >= 1")

    success_target = (success_url or PaymentConfig.SUCCESS_URL or "").strip()
    cancel_target  = (cancel_url  or PaymentConfig.CANCEL_URL  or "").strip()
    if not success_target or not cancel_target:
        raise ValueError("success_url and cancel_url are required.")

    price          = get_active_price()
    price_id       = price["price_id"]
    unit_amount    = price["unit_amount"]
    currency       = price["currency"]
    tier_quantity  = PaymentConfig.TIERS[tier]["quantity"]
    total_quantity = tier_quantity * int(quantity)
    total_cents    = unit_amount * total_quantity

    meta = dict(metadata or {})
    meta.update({
        "tier":             tier.value,
        "tier_credits":     str(tier_quantity),
        "pack_count":       str(quantity),
        "credits":          str(total_quantity),
        "product_id":       price["product_id"],
        "price_id":         price_id,
        "unit_price_cents": str(unit_amount),
        "total_cents":      str(total_cents),
    })

    session_params: Dict[str, Any] = {
        "payment_method_types": ["card"],
        "line_items": [{"price": price_id, "quantity": total_quantity}],
        "mode":        "payment",
        "success_url": success_target,
        "cancel_url":  cancel_target,
        "metadata":    meta,
    }
    if customer_email:
        session_params["customer_email"] = customer_email

    logger.info(
        "[CHECKOUT] tier=%s credits=%d price_id=%s total=%s",
        tier.value, total_quantity, price_id, _fmt(total_cents, currency),
    )

    try:
        session = stripe.checkout.Session.create(**session_params)
    except stripe.error.StripeError as exc:
        raise stripe.error.StripeError(f"Failed to create checkout session: {exc}") from exc

    return {
        "session_id":       session.id,
        "checkout_url":     session.url,
        "expires_at":       session.expires_at,
        "payment_status":   session.payment_status,
        "status":           session.status,
        "tier":             tier.value,
        "price_id":         price_id,
        "product_id":       price["product_id"],
        "unit_price_cents": unit_amount,
        "total_cents":      total_cents,
        "total_quantity":   total_quantity,
    }


def verify_webhook_event(payload: bytes, signature: str):
    if not STRIPE_WEBHOOK_SECRET:
        raise ValueError("STRIPE_WEBHOOK_SECRET is not configured.")
    if not signature:
        raise ValueError("Missing Stripe signature header.")
    try:
        return stripe.Webhook.construct_event(payload, signature, STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError as exc:
        raise ValueError(
            "Invalid Stripe webhook signature. Ensure STRIPE_WEBHOOK_SECRET matches the exact webhook endpoint secret (whsec_...) for this URL and mode (test/live)."
        ) from exc
    except Exception as exc:
        raise ValueError(f"Invalid webhook payload: {exc}") from exc


def retrieve_checkout_session(session_id: str):
    validate_config()
    if not (session_id or "").strip():
        raise ValueError("session_id is required.")
    try:
        return stripe.checkout.Session.retrieve(session_id.strip())
    except stripe.error.StripeError as exc:
        raise stripe.error.StripeError(f"Failed to retrieve session: {exc}") from exc


def get_checkout_status(session_id: str, stale_after_seconds: Optional[int] = None) -> Dict[str, Any]:
    session    = retrieve_checkout_session(session_id)
    now        = datetime.now(timezone.utc).timestamp()
    expires_at = int(session.expires_at or 0)
    stale_thr  = stale_after_seconds if stale_after_seconds is not None else STALE_PAYMENT_WINDOW_SECONDS

    is_paid    = session.payment_status == "paid"
    is_expired = session.status == "expired" or (expires_at > 0 and now > expires_at)
    is_stale   = session.status == "open" and expires_at > 0 and (now - expires_at) > stale_thr

    status = "open"
    if is_paid:      status = "paid"
    elif is_expired: status = "expired"
    elif is_stale:   status = "stale"

    return {
        "session_id":     session.id,
        "status":         status,
        "stripe_status":  session.status,
        "payment_status": session.payment_status,
        "expires_at":     session.expires_at,
        "customer_email": session.customer_email,
        "metadata":       dict(session.metadata or {}),
        "is_paid":        is_paid,
        "is_stale":       is_stale,
        "is_expired":     is_expired,
    }
