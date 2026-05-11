#!/usr/bin/env python3
"""
Frontend module for the lighter0 application.
Serves HTML templates with React-based UI for cover art generation and payment processing.
"""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import json
import os


ADMIN_CONTACT_NAME = (os.getenv("ADMIN_CONTACT_NAME") or "Benedikt Sterra").strip()
ADMIN_CONTACT_EMAIL = (os.getenv("ADMIN_EMAIL") or "office@botworld.cloud").strip()


def _runtime_config_script() -> str:
    config = {
        "adminContactName": ADMIN_CONTACT_NAME,
        "adminContactEmail": ADMIN_CONTACT_EMAIL,
    }
    return f'<script>window.LIGHTER0_RUNTIME_CONFIG = {json.dumps(config)};</script>'


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>lighter0 - Cover Art Generator</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Manrope:wght@400;500;600;700&display=swap" rel="stylesheet">
    <script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
    <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
    <script src="/static/firebase-config.js"></script>
    <script src="/static/google_aut.js"></script>
    <script src="/static/privacy_policy.js"></script>
    <style>
        :root {
            --bg-0: #f6f8fc;
            --bg-1: #fbfcff;
            --bg-2: #ffffff;
            --bg-soft: #f3f5fa;
            --line-0: #e7ebf2;
            --line-1: #d8deea;
            --text-0: #1d2433;
            --text-1: #4a556b;
            --text-2: #6d7890;
            --accent-0: #667eea;
            --accent-1: #764ba2;
            --ok-bg: #e7f6ee;
            --ok-fg: #1f6b41;
            --warn-bg: #fff4e7;
            --warn-fg: #8a5a1f;
            --err-bg: #fdecef;
            --err-fg: #8a2333;
            --radius-lg: 20px;
            --radius-md: 14px;
            --radius-sm: 10px;
            --shadow-card: 0 16px 40px rgba(28, 40, 64, 0.10);
            --shadow-soft: 0 10px 24px rgba(36, 52, 83, 0.08);
        }

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: 'Manrope', 'Segoe UI', sans-serif;
            color: var(--text-0);
            min-height: 100vh;
            padding: 20px;
            background:
                radial-gradient(circle at 8% 0%, rgba(102, 126, 234, 0.15), transparent 32%),
                radial-gradient(circle at 90% 10%, rgba(118, 75, 162, 0.10), transparent 36%),
                linear-gradient(170deg, #f8faff 0%, #f2f5fa 60%, #eef2f8 100%);
            margin: 0;
        }

        .container {
            width: 100%;
            max-width: none;
            margin: 0 auto;
            padding: 0 20px;
            box-sizing: border-box;
        }

        .app-shell {
            display: grid;
            gap: 20px;
        }

        header {
            background: linear-gradient(160deg, rgba(255, 255, 255, 0.96), rgba(248, 251, 255, 0.92));
            border: 1px solid var(--line-0);
            border-radius: var(--radius-lg);
            padding: 26px 28px;
            box-shadow: var(--shadow-soft);
            text-align: left;
        }

        header h1 {
            font-family: 'Fraunces', serif;
            font-size: clamp(1.9rem, 2.2vw, 2.7rem);
            letter-spacing: -0.02em;
            line-height: 1.12;
            color: var(--text-0);
            margin-bottom: 8px;
        }

        header p {
            color: var(--text-1);
            font-size: 1.03rem;
            max-width: 760px;
        }

        .main-content {
            width: 100%;
            box-sizing: border-box;
        }

        .generator-layout {
            display: grid;
            grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
            gap: 20px;
            align-items: start;
            width: 100%;
            box-sizing: border-box;
        }

        .generator-layout > * {
            min-width: 0;
        }

        @media (max-width: 980px) {
            .generator-layout {
                grid-template-columns: 1fr;
            }
        }

        .card {
            background: linear-gradient(180deg, var(--bg-2), var(--bg-1));
            border-radius: var(--radius-lg);
            border: 1px solid var(--line-0);
            padding: 26px;
            box-shadow: var(--shadow-card);
            width: 100%;
            box-sizing: border-box;
        }

        .card h2 {
            font-family: 'Fraunces', serif;
            font-size: 1.66rem;
            color: var(--text-0);
            margin-bottom: 20px;
            padding-bottom: 14px;
            border-bottom: 1px solid var(--line-0);
        }

        .form-group {
            margin-bottom: 18px;
        }

        label {
            display: block;
            margin-bottom: 8px;
            font-weight: 700;
            color: #2a3347;
            font-size: 0.92rem;
            letter-spacing: 0.01em;
        }

        input[type="text"],
        input[type="email"],
        input[type="number"],
        input[type="url"],
        textarea,
        select {
            width: 100%;
            border: 1px solid var(--line-1);
            background: #ffffff;
            border-radius: var(--radius-sm);
            padding: 12px 14px;
            font-size: 0.98rem;
            font-family: inherit;
            color: var(--text-0);
            transition: border-color .2s ease, box-shadow .2s ease, background .2s ease;
        }

        input::placeholder,
        textarea::placeholder {
            color: #9ca6bc;
        }

        input[type="text"]:focus,
        input[type="email"]:focus,
        input[type="number"]:focus,
        input[type="url"]:focus,
        textarea:focus,
        select:focus {
            outline: none;
            border-color: var(--accent-0);
            box-shadow: 0 0 0 4px rgba(102, 126, 234, 0.14);
            background: #fcfdff;
        }

        textarea {
            resize: vertical;
            min-height: 110px;
        }

        .form-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 14px;
        }

        @media (max-width: 640px) {
            .form-row {
                grid-template-columns: 1fr;
            }
        }

        .button-group {
            display: flex;
            gap: 12px;
            margin-top: 24px;
        }

        button {
            appearance: none;
            border-radius: var(--radius-sm);
            border: 1px solid transparent;
            padding: 12px 18px;
            font-size: 0.95rem;
            font-weight: 700;
            font-family: inherit;
            cursor: pointer;
            transition: transform .15s ease, box-shadow .2s ease, background .2s ease, border-color .2s ease;
            flex: 1;
        }

        button:disabled {
            cursor: not-allowed;
            opacity: 0.62;
        }

        .btn-primary {
            color: #ffffff;
            background: linear-gradient(135deg, var(--accent-0), #5b95f2);
            box-shadow: 0 9px 18px rgba(102, 126, 234, 0.28);
        }

        .btn-primary:hover:not(:disabled) {
            transform: translateY(-1px);
            box-shadow: 0 12px 22px rgba(102, 126, 234, 0.32);
        }

        .btn-secondary {
            color: var(--text-1);
            background: #ffffff;
            border-color: var(--line-1);
            box-shadow: 0 5px 12px rgba(35, 48, 74, 0.07);
        }

        .btn-secondary:hover:not(:disabled) {
            background: #f9fbff;
            border-color: #c8d2e4;
        }

        .tier-selector {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
            gap: 12px;
            margin-bottom: 14px;
        }

        .tier-card {
            border: 1px solid var(--line-1);
            border-radius: var(--radius-md);
            padding: 16px;
            background: #ffffff;
            text-align: center;
            cursor: pointer;
            transition: border-color .2s ease, box-shadow .2s ease, transform .15s ease;
        }

        .tier-card:hover {
            border-color: #9eb2f0;
            transform: translateY(-1px);
            box-shadow: 0 9px 18px rgba(74, 95, 145, 0.10);
        }

        .tier-card.selected {
            border-color: var(--accent-0);
            background: linear-gradient(180deg, #ffffff, #f5f8ff);
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.12);
        }

        .tier-card h3 {
            color: #2d364a;
            margin-bottom: 8px;
            font-size: 1.05rem;
        }

        .tier-card .credits {
            color: #385bcf;
            font-size: 1.7rem;
            line-height: 1.1;
            margin: 8px 0;
            font-weight: 800;
        }

        .tier-card .price {
            color: var(--accent-1);
            font-size: 1.2rem;
            margin-top: 4px;
            font-weight: 700;
        }

        .status-message {
            padding: 12px 14px;
            border-radius: var(--radius-sm);
            margin-bottom: 16px;
            border: 1px solid transparent;
            font-weight: 600;
            font-size: 0.93rem;
        }

        .status-success {
            background: var(--ok-bg);
            border-color: #c7e6d3;
            color: var(--ok-fg);
        }

        .status-error {
            background: var(--err-bg);
            border-color: #f3c4ce;
            color: var(--err-fg);
        }

        .status-loading {
            background: var(--warn-bg);
            border-color: #f2deba;
            color: var(--warn-fg);
        }

        .loader {
            display: inline-block;
            width: 16px;
            height: 16px;
            border: 2px solid rgba(23, 37, 66, 0.18);
            border-radius: 50%;
            border-top-color: var(--accent-0);
            animation: spinner 0.8s linear infinite;
            vertical-align: -2px;
        }

        @keyframes spinner {
            to { transform: rotate(360deg); }
        }

        .help-text {
            font-size: 0.84rem;
            line-height: 1.4;
            color: var(--text-2);
            margin-top: 6px;
        }

        .tabs {
            display: inline-flex;
            gap: 8px;
            margin: 4px 0 4px;
            padding: 6px;
            border: 1px solid var(--line-0);
            border-radius: 999px;
            background: rgba(255, 255, 255, 0.82);
            box-shadow: 0 4px 10px rgba(39, 53, 82, 0.07);
        }

        .tab-button {
            flex: 0;
            border-radius: 999px;
            border: 1px solid transparent;
            background: transparent;
            padding: 10px 16px;
            color: #586379;
            font-size: 0.9rem;
            font-weight: 700;
        }

        .tab-button.active {
            color: #23314d;
            border-color: #d8deeb;
            background: #ffffff;
            box-shadow: 0 4px 12px rgba(33, 46, 74, 0.10);
        }

        .auth-card {
            background: linear-gradient(165deg, rgba(255, 255, 255, 0.98), rgba(247, 250, 255, 0.94));
            border: 1px solid var(--line-0);
            border-radius: var(--radius-lg);
            padding: 18px 20px;
            margin: 4px 0;
            box-shadow: var(--shadow-soft);
        }

        .auth-row {
            display: flex;
            gap: 12px;
            align-items: center;
            flex-wrap: wrap;
        }

        .auth-status {
            margin-top: 8px;
            color: var(--text-1);
            font-size: 0.9rem;
        }

        .user-card-grid {
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 14px;
            align-items: start;
        }

        .user-card-meta {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 8px 14px;
        }

        .user-card-actions {
            display: flex;
            flex-direction: column;
            gap: 10px;
            min-width: 150px;
        }

        .artifacts-panel {
            background: linear-gradient(135deg, #1a1f2e 0%, #232836 100%);
            border: 1px solid #3a4456;
            border-radius: var(--radius-lg);
            padding: 26px;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08), 0 16px 40px rgba(28, 40, 64, 0.10);
            min-height: 400px;
            width: 100%;
            box-sizing: border-box;
        }

        .artifacts-panel h3 {
            font-family: 'Fraunces', serif;
            font-size: 1.4rem;
            color: #ffffff;
            margin-bottom: 20px;
            padding-bottom: 14px;
            border-bottom: 1px solid #3a4456;
        }

        .artifact-preview {
            width: 100%;
            border-radius: 10px;
            border: 1px solid #4a5368;
            margin-bottom: 18px;
            overflow: hidden;
            box-shadow: 0 8px 20px rgba(0, 0, 0, 0.40);
        }

        .artifact-preview img {
            width: 100%;
            display: block;
            background: #000000;
        }

        .artifact-list {
            display: grid;
            gap: 10px;
        }

        .temp-thumb-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
            gap: 10px;
            margin-bottom: 14px;
        }

        .temp-thumb-card {
            border: 1px solid #3f4a60;
            border-radius: 8px;
            background: #2a2f3f;
            padding: 8px;
            cursor: pointer;
            transition: border-color .2s ease, transform .15s ease, box-shadow .2s ease;
            text-align: left;
            color: #e8eef5;
        }

        .temp-thumb-card:hover {
            transform: translateY(-1px);
            border-color: #7f9cff;
            box-shadow: 0 8px 14px rgba(32, 44, 74, 0.32);
        }

        .temp-thumb-card.selected {
            border-color: #90a7ff;
            box-shadow: 0 0 0 2px rgba(144, 167, 255, 0.28);
        }

        .temp-thumb-card img {
            width: 100%;
            height: 72px;
            object-fit: cover;
            border-radius: 6px;
            border: 1px solid #465169;
            background: #151922;
            display: block;
            margin-bottom: 6px;
        }

        .temp-thumb-name {
            font-size: 0.78rem;
            color: #cdd8ea;
            line-height: 1.2;
            word-break: break-word;
        }

        .large-preview-wrap {
            border: 1px solid #4a5368;
            border-radius: 10px;
            overflow: hidden;
            margin-bottom: 14px;
            background: #121722;
        }

        .large-preview-wrap img {
            width: 100%;
            max-height: 320px;
            object-fit: contain;
            background: #0d111a;
            display: block;
        }

        .large-preview-label {
            padding: 8px 10px;
            border-top: 1px solid #3b4459;
            font-size: 0.82rem;
            color: #c7d2e9;
            word-break: break-word;
        }

        .paste-zone {
            border: 1px dashed #bfd0ee;
            background: #f7faff;
            border-radius: var(--radius-sm);
            padding: 12px;
            color: #44516b;
        }

        .paste-zone textarea {
            min-height: 70px;
            background: #ffffff;
        }

        .artifact-item {
            background: #2a2f3f;
            border: 1px solid #3a4456;
            border-radius: 8px;
            padding: 12px 14px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .artifact-item .file-name {
            color: #e8eef5;
            font-weight: 600;
            font-size: 0.95rem;
            word-break: break-word;
        }

        .artifact-item .file-size {
            color: #9ca6bc;
            font-size: 0.85rem;
        }

        .artifact-item .file-actions {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }

        .artifact-item a {
            display: inline-block;
            padding: 6px 12px;
            background: linear-gradient(135deg, var(--accent-0), #5b95f2);
            color: #ffffff;
            border-radius: 6px;
            text-decoration: none;
            font-size: 0.85rem;
            font-weight: 600;
            transition: transform .15s ease, box-shadow .2s ease;
        }

        .artifact-item a:hover {
            transform: translateY(-1px);
            box-shadow: 0 8px 14px rgba(102, 126, 234, 0.30);
        }

        .artifacts-empty {
            color: #9ca6bc;
            text-align: center;
            padding: 40px 20px;
            font-size: 0.95rem;
        }

        .artifacts-loading {
            min-height: 280px;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-direction: column;
            gap: 12px;
            color: #d7e3fb;
            text-align: center;
        }

        .artifacts-loading .loader {
            width: 34px;
            height: 34px;
            border-width: 3px;
            border-color: rgba(220, 230, 252, 0.20);
            border-top-color: #8fa8ff;
        }

        .artifacts-loading-title {
            font-size: 1rem;
            font-weight: 700;
            color: #e6eefc;
        }

        .artifacts-loading-sub {
            font-size: 0.9rem;
            color: #b8c6e2;
            max-width: 320px;
            line-height: 1.4;
        }

        .history-bar {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 10px;
            margin-bottom: 14px;
        }

        .history-folder {
            border: 1px solid #3f4a60;
            border-radius: 8px;
            background: #242a39;
            color: #dbe6ff;
            padding: 10px;
            text-align: left;
            cursor: pointer;
            transition: border-color .2s ease, box-shadow .2s ease, transform .15s ease;
        }

        .history-folder:hover {
            transform: translateY(-1px);
            border-color: #7f9cff;
            box-shadow: 0 8px 14px rgba(32, 44, 74, 0.32);
        }

        .history-folder.selected {
            border-color: #90a7ff;
            box-shadow: 0 0 0 2px rgba(144, 167, 255, 0.30);
            background: linear-gradient(180deg, #2b3350, #262d43);
        }

        .history-folder-title {
            font-size: 0.82rem;
            font-weight: 700;
            color: #eef4ff;
            word-break: break-word;
            line-height: 1.2;
            margin-bottom: 6px;
        }

        .history-folder-meta {
            font-size: 0.74rem;
            color: #b8c6e2;
            line-height: 1.25;
        }

        .toast-wrap {
            position: fixed;
            right: 22px;
            bottom: 22px;
            z-index: 1000;
            pointer-events: none;
        }

        .toast-card {
            min-width: 280px;
            max-width: 420px;
            border-radius: 12px;
            border: 1px solid var(--line-0);
            box-shadow: 0 14px 32px rgba(22, 32, 52, 0.14);
            padding: 12px 14px;
            background: #ffffff;
            animation: toast-in .2s ease;
        }

        .toast-card strong {
            display: block;
            font-size: 0.9rem;
            margin-bottom: 2px;
        }

        .toast-card p {
            margin: 0;
            font-size: 0.85rem;
            line-height: 1.35;
            color: var(--text-1);
        }

        .toast-success {
            border-color: #bedecb;
            background: linear-gradient(180deg, #f6fff9, #edf8f1);
        }

        .toast-success strong {
            color: #1e6a42;
        }

        .toast-error {
            border-color: #f0c4ce;
            background: linear-gradient(180deg, #fff7f9, #fff0f3);
        }

        .toast-error strong {
            color: #8d2236;
        }

        @keyframes toast-in {
            from {
                opacity: 0;
                transform: translateY(8px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        @media (max-width: 760px) {
            body {
                padding: 14px;
            }

            .card,
            .auth-card,
            header {
                padding: 18px;
            }

            .tabs {
                width: 100%;
                justify-content: space-between;
            }

            .tab-button {
                flex: 1;
            }

            .user-card-grid {
                grid-template-columns: 1fr;
            }

            .user-card-actions {
                flex-direction: row;
            }
        }
    </style>
</head>
<body>
    <div id="root"></div>
    
    __RUNTIME_CONFIG_SCRIPT__
    <script src="/static/app.js"></script>
</body>
</html>
"""


frontend_app = FastAPI(title="lighter0-frontend", version="1.0.0")
frontend_static_dir = os.path.join(os.path.dirname(__file__), "frontend")
checkout_success_page = os.path.join(frontend_static_dir, "checkout_success.html")
checkout_failed_page = os.path.join(frontend_static_dir, "checkout_failed.html")
if os.path.isdir(frontend_static_dir):
    frontend_app.mount("/static", StaticFiles(directory=frontend_static_dir), name="static")


@frontend_app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main frontend HTML with React UI."""
    return (
        HTML_TEMPLATE
        .replace("__RUNTIME_CONFIG_SCRIPT__", _runtime_config_script())
        .replace("__ADMIN_CONTACT_NAME__", ADMIN_CONTACT_NAME)
        .replace("__ADMIN_CONTACT_EMAIL__", ADMIN_CONTACT_EMAIL)
    )


@frontend_app.get("/index.html", response_class=HTMLResponse)
async def index():
    """Serve the main frontend HTML with React UI."""
    return (
        HTML_TEMPLATE
        .replace("__RUNTIME_CONFIG_SCRIPT__", _runtime_config_script())
        .replace("__ADMIN_CONTACT_NAME__", ADMIN_CONTACT_NAME)
        .replace("__ADMIN_CONTACT_EMAIL__", ADMIN_CONTACT_EMAIL)
    )


@frontend_app.get("/checkout/success")
async def checkout_success_redirect_page():
    """Serve checkout success redirect page from frontend static directory."""
    if os.path.isfile(checkout_success_page):
        return FileResponse(checkout_success_page, media_type="text/html")
    return HTMLResponse('<meta http-equiv="refresh" content="0; url=/?checkout=success">')


@frontend_app.get("/checkout/cancel")
async def checkout_cancel_redirect_page():
    """Backward-compatible alias for failed checkout route."""
    if os.path.isfile(checkout_failed_page):
        return FileResponse(checkout_failed_page, media_type="text/html")
    return HTMLResponse('<meta http-equiv="refresh" content="0; url=/?checkout=failed">')


@frontend_app.get("/checkout/failed")
async def checkout_failed_redirect_page():
    """Serve checkout failed redirect page from frontend static directory."""
    if os.path.isfile(checkout_failed_page):
        return FileResponse(checkout_failed_page, media_type="text/html")
    return HTMLResponse('<meta http-equiv="refresh" content="0; url=/?checkout=failed">')


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(frontend_app, host="0.0.0.0", port=3000)
