#!/usr/bin/env python3
"""
Backward-compatible payment entrypoint.
Stripe-specific logic is now located in payment/stripe.py.
"""

import importlib.util
from pathlib import Path

from stripe import StripeError

try:
    from payment.stripe import (
        STRIPE_PUBLISHABLE_KEY,
        CreditTier,
        PaymentConfig,
        create_checkout_session,
        get_tier_info,
        list_all_tiers,
        validate_config,
    )
except ModuleNotFoundError:
    # Fallback for direct execution: python payment/payment.py
    stripe_module_path = Path(__file__).with_name("stripe.py")
    spec = importlib.util.spec_from_file_location("payment_stripe_local", stripe_module_path)
    stripe_logic = importlib.util.module_from_spec(spec)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load stripe logic module.")
    spec.loader.exec_module(stripe_logic)

    STRIPE_PUBLISHABLE_KEY = stripe_logic.STRIPE_PUBLISHABLE_KEY
    CreditTier = stripe_logic.CreditTier
    PaymentConfig = stripe_logic.PaymentConfig
    create_checkout_session = stripe_logic.create_checkout_session
    get_tier_info = stripe_logic.get_tier_info
    list_all_tiers = stripe_logic.list_all_tiers
    validate_config = stripe_logic.validate_config


if __name__ == "__main__":
    # Test script to verify configuration
    try:
        validate_config()
        print("✅ Stripe configuration is valid\n")
        
        print("📦 Available Credit Tiers:")
        for tier_info in list_all_tiers():
            print(f"  • {tier_info['name']}: {tier_info['credits']} credits @ ${tier_info['price_usd']:.2f}")
        
        print("\n💳 Example: Creating checkout session for Starter tier...")
        url = create_checkout_session(CreditTier.STARTER, customer_email="test@example.com")
        print(f"Checkout URL: {url}")
        
    except StripeError as error:
        print(f"❌ Stripe Error: {error}")
    except Exception as error:
        print(f"❌ Error: {error}")
