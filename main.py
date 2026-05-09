#!/usr/bin/env python3
"""
Main entry point for lighter0.

Mounts:
  /api   – REST + auth + payment endpoints  (server.py)
  /      – React frontend                   (frontend.py)

FastMCP is kept separate and should be started independently (e.g. on port 8001)
so it stays internal and is never exposed through this public-facing server.
"""

import os
import uvicorn
import firebase_admin
from firebase_admin import credentials
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from server import app as api_app
from server import stripe_webhook
from frontend import frontend_app

def init_firebase():
    """Initialize Firebase Admin SDK from frontend/credentials.json
    
    This file must contain valid Service Account JSON credentials from Firebase Console:
    https://console.firebase.google.com → Project Settings → Service Accounts → Generate New Private Key
    
    The credentials are loaded server-side only and used for:
    - User authentication and creation
    - Realtime Database operations
    - File uploads and access control
    """
    try:
        firebase_admin.get_app()
        print("✅ Firebase Admin SDK already initialized")
        return True
    except ValueError:
        # App not initialized yet, proceed
        pass
    
    cred_path = os.path.join(os.path.dirname(__file__), "frontend", "credentials.json")
    
    if not os.path.exists(cred_path):
        print(f"❌ Firebase credentials file not found: {cred_path}")
        print("   Please create frontend/credentials.json with Service Account JSON from Firebase Console")
        return False
    
    try:
        with open(cred_path, 'r') as f:
            config = f.read().strip()
        
        # Check for unset placeholders
        if "REPLACE_WITH_YOUR" in config:
            print("❌ Firebase credentials contain placeholders (REPLACE_WITH_YOUR_*)")
            print("   Please replace with actual values from Firebase Console:")
            print("   https://console.firebase.google.com → Project Settings → Service Accounts → Generate New Private Key")
            return False
        
        cred = credentials.Certificate(cred_path)
        db_url = os.getenv(
            "FIREBASE_DATABASE_URL",
            "https://bestbrain-39ce7-default-rtdb.firebaseio.com",
        )
        firebase_admin.initialize_app(cred, {"databaseURL": db_url})
        print(f"✅ Firebase Admin SDK initialized successfully (databaseURL={db_url})")
        return True
        
    except ValueError as e:
        if "Invalid" in str(e) or "private" in str(e).lower():
            print(f"❌ Firebase credentials invalid: {e}")
            print("   Ensure frontend/credentials.json is a valid Service Account JSON from Firebase Console")
            print("   https://console.firebase.google.com → Project Settings → Service Accounts → Generate New Private Key")
        else:
            print(f"❌ Firebase initialization failed: {e}")
        return False
        
    except Exception as e:
        print(f"❌ Firebase initialization failed: {e}")
        print("   Ensure frontend/credentials.json has valid Service Account credentials")
        return False

# Initialize Firebase before mounting apps
firebase_initialized = init_firebase()
if not firebase_initialized:
    print("⚠️  Continuing without Firebase. Payment features work. User auth sync disabled.")
else:
    print("✅ Full feature set available including user authentication.")


main_app = FastAPI(title="lighter0", version="1.0.0", docs_url="/api/docs", openapi_url="/api/openapi.json")

main_app.add_middleware(
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

main_app.mount("/api", api_app)

# Stripe sends to /payment/webhook (without /api prefix).
# Register the same handler here so the route works regardless of how
# the Stripe dashboard URL is configured.
main_app.add_api_route(
    "/payment/webhook",
    stripe_webhook,
    methods=["POST"],
    operation_id="stripe_webhook_root",
)

main_app.mount("/", frontend_app)


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "false").lower() == "true"

    # Print the effective webhook URLs so the Stripe dashboard can be updated easily.
    codespace_name = os.getenv("CODESPACE_NAME", "")
    if codespace_name:
        public_base = f"https://{codespace_name}-{port}.app.github.dev"
        print(f"🌐 Public URL: {public_base}")
        print(f"🔔 Stripe webhook URL: {public_base}/payment/webhook")
        print(f"   (also reachable at: {public_base}/api/payment/webhook)")

    uvicorn.run(
        main_app,
        host=host,
        port=port,
        log_level="info",
        reload=reload,
    )
