#!/usr/bin/env python3
"""
Frontend module for the lighter0 application.
Serves HTML templates with React-based UI for cover art generation and payment processing.
"""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import os


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
    <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
    <script src="/static/firebase-config.js"></script>
    <script src="/static/google_aut.js"></script>
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
    
    <script type="text/babel">
        const { useState, useEffect } = React;
        const API_BASE = window.location.port === '3000' ? 'http://localhost:8000' : '';

        // localStorage helpers for persistent authentication state
        const LOCAL_STORAGE_USER_KEY = 'lighter0_authenticated_user';
        
        function saveAuthenticatedUserToStorage(user) {
            if (!user) {
                localStorage.removeItem(LOCAL_STORAGE_USER_KEY);
            } else {
                localStorage.setItem(LOCAL_STORAGE_USER_KEY, JSON.stringify(user));
            }
        }
        
        function loadAuthenticatedUserFromStorage() {
            try {
                const stored = localStorage.getItem(LOCAL_STORAGE_USER_KEY);
                return stored ? JSON.parse(stored) : null;
            } catch (error) {
                console.warn('Failed to load user from storage:', error);
                return null;
            }
        }

        // Helper function to get file type information
        function getFileTypeInfo(fileName) {
            const ext = (fileName.split('.').pop() || 'file').toLowerCase();
            const typeMap = {
                'png': { emoji: '🖼️', label: 'PNG Image', category: 'image' },
                'jpg': { emoji: '🖼️', label: 'JPG Image', category: 'image' },
                'jpeg': { emoji: '🖼️', label: 'JPEG Image', category: 'image' },
                'svg': { emoji: '✨', label: 'SVG Vector', category: 'vector' },
                'gif': { emoji: '🎬', label: 'GIF Animation', category: 'image' },
                'webp': { emoji: '🖼️', label: 'WebP Image', category: 'image' },
                'pdf': { emoji: '📄', label: 'PDF Document', category: 'document' },
                'json': { emoji: '📋', label: 'JSON Data', category: 'data' },
                'html': { emoji: '🌐', label: 'HTML Document', category: 'web' },
                'zip': { emoji: '📦', label: 'ZIP Archive', category: 'archive' },
                'txt': { emoji: '📝', label: 'Text File', category: 'document' }
            };
            return typeMap[ext] || { emoji: '📁', label: fileName, category: 'file' };
        }

        // Helper function to get file extension
        function getFileExtension(fileName) {
            return (fileName.split('.').pop() || 'file').toUpperCase();
        }

        function UserInfoCard({ authenticatedUser, authStatus, userProfile, activity, loadingProfile, onRefreshProfile, onSignOut }) {
            const email = (authenticatedUser && authenticatedUser.email) || (userProfile && userProfile.email) || 'Unavailable';
            const uid = (authenticatedUser && authenticatedUser.uid) || (userProfile && userProfile.uid) || 'Unavailable';

            return (
                <div className="auth-card">
                    <label>User Information</label>
                    <div className="user-card-grid">
                        <div className="user-card-meta">
                            <div><strong>Email:</strong> {email}</div>
                            <div><strong>UID:</strong> {uid}</div>
                            <div><strong>Current Credits:</strong> {(userProfile && userProfile.credits) || 0}</div>
                            <div><strong>Pending Credits:</strong> {(userProfile && userProfile.pending_credits) || 0}</div>
                            <div><strong>Paid Purchases:</strong> {(userProfile && userProfile.paid_purchases) || 0}</div>
                            <div><strong>Generations:</strong> {activity.generations}</div>
                            <div className="help-text">{activity.lastAction}</div>
                            <div className="help-text">{authStatus}</div>
                        </div>
                        <div className="user-card-actions">
                            <button type="button" className="btn-secondary" onClick={onRefreshProfile} disabled={loadingProfile}>
                                {loadingProfile ? 'Refreshing...' : 'Refresh Data'}
                            </button>
                            <button type="button" className="btn-secondary" onClick={onSignOut}>
                                Log Out
                            </button>
                        </div>
                    </div>
                </div>
            );
        }

        function App() {
            const [authStatus, setAuthStatus] = useState('Not authenticated');
            const [activeTab, setActiveTab] = useState('generator');
            const [authenticatedUser, setAuthenticatedUser] = useState(loadAuthenticatedUserFromStorage());
            const [userProfile, setUserProfile] = useState(null);
            const [loadingProfile, setLoadingProfile] = useState(false);
            const [freeGenerationStatus, setFreeGenerationStatus] = useState(null);
            const [toast, setToast] = useState(null);
            const [activity, setActivity] = useState({
                generations: 0,
                lastAction: 'No actions yet.'
            });

            const refreshFreeGenerationStatus = async (userArg) => {
                const user = userArg || authenticatedUser;
                if (!user) {
                    setFreeGenerationStatus(null);
                    return;
                }

                const email = (user.email || '').trim();
                const uid = (user.uid || '').trim();
                if (!email && !uid) {
                    return;
                }

                try {
                    const query = new URLSearchParams();
                    if (email) query.set('email', email);
                    if (uid) query.set('uid', uid);
                    const response = await fetch(`${API_BASE}/api/free-generation-status?${query.toString()}`);
                    if (!response.ok) {
                        throw new Error('Failed to load free generation status');
                    }
                    const payload = await response.json();
                    if (payload && payload.success) {
                        setFreeGenerationStatus({
                            can_use_free: payload.can_use_free,
                            free_generations_used: payload.free_generations_used
                        });
                    }
                } catch (error) {
                    console.log('Free generation status check failed:', error.message);
                }
            };

            const refreshUserProfile = async (userArg) => {
                const user = userArg || authenticatedUser;
                if (!user) {
                    setUserProfile(null);
                    return;
                }

                const email = (user.email || '').trim();
                const uid = (user.uid || '').trim();
                if (!email && !uid) {
                    return;
                }

                setLoadingProfile(true);
                try {
                    const query = new URLSearchParams();
                    if (email) query.set('email', email);
                    if (uid) query.set('uid', uid);
                    const response = await fetch(`${API_BASE}/api/user-profile?${query.toString()}`);
                    if (!response.ok) {
                        throw new Error('Failed to load user profile');
                    }
                    const payload = await response.json();
                    if (payload && payload.user) {
                        setUserProfile(payload.user);
                    }
                } catch (error) {
                    setAuthStatus('Profile refresh failed: ' + error.message);
                } finally {
                    setLoadingProfile(false);
                }
            };

            const recordAction = (actionLabel) => {
                setActivity((prev) => ({
                    generations: actionLabel === 'generation_success' ? prev.generations + 1 : prev.generations,
                    lastAction: `Last action: ${actionLabel} at ${new Date().toLocaleTimeString()}`,
                }));
                refreshUserProfile();
            };

            const startGoogleAuth = async () => {
                if (!window.firebaseConfig || !window.firebaseConfig.projectId) {
                    setAuthStatus('Firebase is not configured.');
                    return;
                }

                if (!window.GoogleAuth) {
                    setAuthStatus('Google auth module is not loaded.');
                    return;
                }

                try {
                    setAuthStatus('Initializing Firebase authentication...');
                    await window.GoogleAuth.initializeGoogleAuth({
                        endpoint: `${API_BASE}/api/auth-user`,
                        onAuthSuccess: function (user) {
                            const authUser = user || null;
                            saveAuthenticatedUserToStorage(authUser);
                            setAuthenticatedUser(authUser);
                            refreshUserProfile(authUser);
                            if (authUser && authUser.email) {
                                setAuthStatus('Authenticated as ' + authUser.email);
                            } else {
                                setAuthStatus('Authentication successful.');
                            }
                        },
                        onAuthError: function (error) {
                            saveAuthenticatedUserToStorage(null);
                            setAuthenticatedUser(null);
                            setUserProfile(null);
                            setAuthStatus('Authentication error: ' + error.message);
                        }
                    });
                    setAuthStatus('Opening sign-in dialog...');
                    await window.GoogleAuth.signInWithGoogle();
                } catch (error) {
                    setAuthStatus('Failed: ' + error.message);
                }
            };

            const handleLogout = async () => {
                try {
                    if (window.GoogleAuth && window.GoogleAuth.signOut) {
                        await window.GoogleAuth.signOut();
                    }
                } catch (error) {
                    setAuthStatus('Logout warning: ' + error.message);
                } finally {
                    saveAuthenticatedUserToStorage(null);
                    setAuthenticatedUser(null);
                    setUserProfile(null);
                    setActivity({ generations: 0, lastAction: 'No actions yet.' });
                    setAuthStatus('Not authenticated');
                }
            };

            useEffect(() => {
                if (authenticatedUser) {
                    refreshUserProfile(authenticatedUser);
                    refreshFreeGenerationStatus(authenticatedUser);
                }
            }, [authenticatedUser]);

            useEffect(() => {
                const params = new URLSearchParams(window.location.search || '');
                const checkout = (params.get('checkout') || '').trim().toLowerCase();
                if (checkout !== 'success' && checkout !== 'cancel') {
                    return;
                }

                if (checkout === 'success') {
                    setToast({
                        type: 'success',
                        title: 'Payment successful',
                        message: 'Credits purchase completed. Your profile will refresh shortly.'
                    });
                } else {
                    setToast({
                        type: 'error',
                        title: 'Payment canceled',
                        message: 'Checkout was canceled. No charge was made.'
                    });
                }

                params.delete('checkout');
                const nextQuery = params.toString();
                const nextUrl = `${window.location.pathname}${nextQuery ? `?${nextQuery}` : ''}${window.location.hash || ''}`;
                window.history.replaceState({}, '', nextUrl);

                const timer = window.setTimeout(() => {
                    setToast(null);
                    refreshUserProfile();
                }, 5000);

                return () => window.clearTimeout(timer);
            }, []);

            return (
                <div className="container app-shell">
                    <header>
                        <h1>✨ lighter0</h1>
                        <p>Seamless Cover Art Generator & Payments</p>
                    </header>

                    {authenticatedUser ? (
                        <UserInfoCard
                            authenticatedUser={authenticatedUser}
                            authStatus={authStatus}
                            userProfile={userProfile}
                            activity={activity}
                            loadingProfile={loadingProfile}
                            onRefreshProfile={() => refreshUserProfile()}
                            onSignOut={handleLogout}
                        />
                    ) : (
                        <div className="auth-card">
                            <label>Google Authentication with Firebase</label>
                            <div className="auth-row">
                                <button type="button" className="btn-primary" onClick={startGoogleAuth}>
                                    🔐 Sign in with Google
                                </button>
                            </div>
                            <div className="auth-status">{authStatus}</div>
                        </div>
                    )}

                    <div className="tabs">
                        <button 
                            className={`tab-button ${activeTab === 'generator' ? 'active' : ''}`}
                            onClick={() => setActiveTab('generator')}
                        >
                            🎨 Cover Art Generator
                        </button>
                        <button 
                            className={`tab-button ${activeTab === 'payment' ? 'active' : ''}`}
                            onClick={() => setActiveTab('payment')}
                        >
                            💳 Buy Credits
                        </button>
                    </div>

                    <div className="main-content">
                        {activeTab === 'generator' && <CoverArtGenerator authenticatedUser={authenticatedUser} freeGenerationStatus={freeGenerationStatus} onAction={recordAction} />}
                        {activeTab === 'payment' && <PaymentSection authenticatedUser={authenticatedUser} onAction={recordAction} />}
                    </div>

                    {toast && (
                        <div className="toast-wrap" aria-live="polite" aria-atomic="true">
                            <div className={`toast-card ${toast.type === 'success' ? 'toast-success' : 'toast-error'}`}>
                                <strong>{toast.title}</strong>
                                <p>{toast.message}</p>
                            </div>
                        </div>
                    )}
                </div>
            );
        }

        function CoverArtGenerator({ authenticatedUser, freeGenerationStatus, onAction }) {
            const [formData, setFormData] = useState({
                theme: 'Mathematical and physical futuristic',
                bg_texture: 'sharp',
                math: 'golden ratio proportions',
                name: '',
                typo: 'futuristic',
                colors: 'black and white',
                tags: 'A colorful luxury cyberpunk lighter-cover with glowing orange neon elements and elegant typography.',
                height: 600,
                width: 600,
                pasted_images: [],
                use_free: freeGenerationStatus && freeGenerationStatus.can_use_free
            });
            
            const [status, setStatus] = useState({ type: null, message: '' });
            const [resultData, setResultData] = useState(null);
            const [loading, setLoading] = useState(false);
            const [selectedInputArtifactPath, setSelectedInputArtifactPath] = useState('');

            useEffect(() => {
                setFormData(prev => ({
                    ...prev,
                    use_free: !!(freeGenerationStatus && freeGenerationStatus.can_use_free)
                }));
            }, [freeGenerationStatus && freeGenerationStatus.can_use_free]);
            
            const handleChange = (e) => {
                const { name, value } = e.target;
                setFormData(prev => ({
                    ...prev,
                    [name]: name === 'height' || name === 'width' ? parseInt(value) : value
                }));
            };

            const fileToDataUrl = (file) => new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = () => resolve(String(reader.result || ''));
                reader.onerror = () => reject(new Error('Failed to read image file'));
                reader.readAsDataURL(file);
            });

            const appendImagesToFormData = (files) => {
                const valid = Array.from(files || []).filter(f => f && String(f.type || '').startsWith('image/'));
                if (valid.length === 0) {
                    return;
                }

                Promise.all(valid.map(async (file, index) => ({
                    name: file.name || `pasted_${Date.now()}_${index + 1}.png`,
                    data_url: await fileToDataUrl(file),
                })))
                    .then((items) => {
                        setFormData(prev => ({
                            ...prev,
                            pasted_images: [...(prev.pasted_images || []), ...items],
                        }));
                    })
                    .catch((error) => {
                        setStatus({ type: 'error', message: `❌ Error while reading pasted image: ${error.message}` });
                    });
            };

            const handlePasteImages = (e) => {
                const items = Array.from((e.clipboardData && e.clipboardData.items) || []);
                const imageFiles = items
                    .map(item => item.getAsFile && item.getAsFile())
                    .filter(file => file && String(file.type || '').startsWith('image/'));

                if (imageFiles.length === 0) {
                    return;
                }

                e.preventDefault();
                appendImagesToFormData(imageFiles);
            };

            const handleFileInput = (e) => {
                appendImagesToFormData(e.target.files || []);
                e.target.value = '';
            };

            const clearPastedImages = () => {
                setFormData(prev => ({ ...prev, pasted_images: [] }));
            };
            
            const handleSubmit = async (e) => {
                e.preventDefault();

                setLoading(true);
                setResultData(null);
                setStatus({ type: 'loading', message: 'Generating cover art...' });
                
                try {
                    const payload = {
                        ...formData,
                        user_id: (authenticatedUser && authenticatedUser.uid) ? authenticatedUser.uid : undefined,
                        user_email: (authenticatedUser && authenticatedUser.email) ? authenticatedUser.email : undefined,
                        use_free: formData.use_free || false
                    };
                    const response = await fetch(`${API_BASE}/api/process`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify(payload)
                    });
                    
                    if (!response.ok) {
                        const errorData = await response.json();
                        throw new Error(errorData.detail || 'Generation failed');
                    }
                    
                    const result = await response.json();
                    if (!result || result.success === false) {
                        throw new Error(result && (result.error || result.message) ? (result.error || result.message) : 'Generation failed');
                    }
                    setResultData(result);
                    const firstInputArtifact = (result.input_artifacts || [])[0];
                    setSelectedInputArtifactPath(firstInputArtifact ? firstInputArtifact.relative_path : '');
                    setStatus({
                        type: 'success',
                        message: '✅ Cover art generated successfully!'
                    });
                    if (onAction) {
                        onAction('generation_success');
                    }
                } catch (error) {
                    setStatus({
                        type: 'error',
                        message: `❌ Error: ${error.message}`
                    });
                } finally {
                    setLoading(false);
                }
            };
            
            return (
                <div className="generator-layout">
                    <div className="card">
                        <h2>Generate Cover Art</h2>
                        <form onSubmit={handleSubmit}>
                            {status.type && (
                                <div className={`status-message status-${status.type}`}>
                                    {status.type === 'loading' && <span className="loader"></span>}
                                    {' '}{status.message}
                                </div>
                            )}

                            <div className="form-group">
                                <label>Image File</label>
                                <div className="help-text">No path or URL is required. Upload/paste is optional.</div>
                            </div>

                            <div className="form-group paste-zone">
                                <label htmlFor="paste_images">Paste Images Into Temp Store (Optional)</label>
                                <textarea
                                    id="paste_images"
                                    onPaste={handlePasteImages}
                                    placeholder="Paste image(s) here with Ctrl/Cmd+V. Pasted images are saved in a temp_store on the server and override default input/output for this run."
                                />
                                <input
                                    type="file"
                                    accept="image/*"
                                    multiple
                                    onChange={handleFileInput}
                                    style={{ marginTop: '10px' }}
                                />
                                <div className="help-text">
                                    {formData.pasted_images.length > 0
                                        ? `${formData.pasted_images.length} pasted image(s) queued for upload`
                                        : 'No image files queued yet.'}
                                </div>
                                {formData.pasted_images.length > 0 && (
                                    <button type="button" className="btn-secondary" style={{ marginTop: '10px' }} onClick={clearPastedImages}>
                                        Clear Pasted Images
                                    </button>
                                )}
                            </div>
                            
                            <div className="form-group">
                                <label htmlFor="theme">Theme</label>
                                <input
                                    type="text"
                                    name="theme"
                                    id="theme"
                                    value={formData.theme}
                                    onChange={handleChange}
                                    placeholder="e.g., Mathematical and physical futuristic"
                                />
                            </div>
                            
                            <div className="form-group">
                                <label htmlFor="bg_texture">Background Texture</label>
                                <input
                                    type="text"
                                    name="bg_texture"
                                    id="bg_texture"
                                    value={formData.bg_texture}
                                    onChange={handleChange}
                                    placeholder="e.g., sharp, matte, metallic"
                                />
                            </div>
                            
                            <div className="form-group">
                                <label htmlFor="math">Mathematical Rule</label>
                                <input
                                    type="text"
                                    name="math"
                                    id="math"
                                    value={formData.math}
                                    onChange={handleChange}
                                    placeholder="e.g., golden ratio proportions"
                                />
                            </div>
                            
                            <div className="form-group">
                                <label htmlFor="name">Product Name</label>
                                <input
                                    type="text"
                                    name="name"
                                    id="name"
                                    value={formData.name}
                                    onChange={handleChange}
                                    placeholder="Leave empty for no text"
                                />
                            </div>
                            
                            <div className="form-group">
                                <label htmlFor="typo">Typography Style</label>
                                <input
                                    type="text"
                                    name="typo"
                                    id="typo"
                                    value={formData.typo}
                                    onChange={handleChange}
                                    placeholder="e.g., futuristic, bold, elegant"
                                />
                            </div>
                            
                            <div className="form-group">
                                <label htmlFor="colors">Color Palette</label>
                                <input
                                    type="text"
                                    name="colors"
                                    id="colors"
                                    value={formData.colors}
                                    onChange={handleChange}
                                    placeholder="e.g., black and white, neon orange"
                                />
                            </div>
                            
                            <div className="form-group">
                                <label htmlFor="tags">Additional Tags</label>
                                <textarea
                                    name="tags"
                                    id="tags"
                                    value={formData.tags}
                                    onChange={handleChange}
                                    placeholder="Describe additional design elements..."
                                />
                            </div>
                            
                            <div className="form-row">
                                <div className="form-group">
                                    <label htmlFor="height">Height (pixels)</label>
                                    <input
                                        type="number"
                                        name="height"
                                        id="height"
                                        value={formData.height}
                                        onChange={handleChange}
                                        min="100"
                                        max="2000"
                                    />
                                </div>
                                <div className="form-group">
                                    <label htmlFor="width">Width (pixels)</label>
                                    <input
                                        type="number"
                                        name="width"
                                        id="width"
                                        value={formData.width}
                                        onChange={handleChange}
                                        min="100"
                                        max="2000"
                                    />
                                </div>
                            </div>
                            
                            <div className="button-group">
                                <button type="submit" className="btn-primary" disabled={loading}>
                                    {loading ? (
                                        <>
                                            <span className="loader"></span> Generating...
                                        </>
                                    ) : (
                                        '🚀 Generate Cover Art'
                                    )}
                                </button>
                                <button 
                                    type="button" 
                                    className="btn-secondary"
                                    onClick={() => {
                                        setFormData({
                                            theme: 'Mathematical and physical futuristic',
                                            bg_texture: 'sharp',
                                            math: 'golden ratio proportions',
                                            name: '',
                                            typo: 'futuristic',
                                            colors: 'black and white',
                                            tags: 'A colorful luxury cyberpunk lighter-cover with glowing orange neon elements and elegant typography.',
                                            height: 600,
                                            width: 600,
                                            pasted_images: [],
                                            use_free: freeGenerationStatus && freeGenerationStatus.can_use_free
                                        });
                                        setStatus({ type: null, message: '' });
                                        setResultData(null);
                                        setSelectedInputArtifactPath('');
                                    }}
                                >
                                    Reset
                                </button>
                            </div>
                            
                            {authenticatedUser && (
                                <div className="help-text" style={{ marginTop: '12px', textAlign: 'center', fontWeight: 600, color: freeGenerationStatus && freeGenerationStatus.can_use_free ? 'var(--ok-fg)' : 'var(--text-2)' }}>
                                    {freeGenerationStatus ? (
                                        freeGenerationStatus.can_use_free ? (
                                            '✨ Free try available: 0/1 used today'
                                        ) : (
                                            '⭐ Daily free try used: 1/1 used today'
                                        )
                                    ) : (
                                        'Loading free tries...'
                                    )}
                                </div>
                            )}
                        </form>
                    </div>

                    <div className="artifacts-panel">
                        {loading ? (
                            <div className="artifacts-loading" aria-live="polite" aria-busy="true">
                                <span className="loader" aria-hidden="true"></span>
                                <div className="artifacts-loading-title">Creating media...</div>
                                <div className="artifacts-loading-sub">Your files are being generated. Results will appear here automatically.</div>
                            </div>
                        ) : resultData ? (
                            <>
                                <h3>Temp Store + Generated Files</h3>

                                {resultData.input_artifacts && resultData.input_artifacts.length > 0 && (
                                    <>
                                        <div className="help-text" style={{ color: '#cdd8ea', marginBottom: '8px' }}>
                                            Temp-store images (select to preview large)
                                        </div>
                                        <div className="temp-thumb-grid">
                                            {resultData.input_artifacts.map((file) => {
                                                const src = `${API_BASE}${file.view_url}`;
                                                const isSelected = selectedInputArtifactPath === file.relative_path;
                                                return (
                                                    <button
                                                        key={file.relative_path}
                                                        type="button"
                                                        className={`temp-thumb-card ${isSelected ? 'selected' : ''}`}
                                                        onClick={() => setSelectedInputArtifactPath(file.relative_path)}
                                                    >
                                                        <img src={src} alt={file.name || 'temp image'} />
                                                        <div className="temp-thumb-name">{file.name || file.relative_path}</div>
                                                    </button>
                                                );
                                            })}
                                        </div>
                                    </>
                                )}

                                {(() => {
                                    const selected = (resultData.input_artifacts || []).find(
                                        (item) => item.relative_path === selectedInputArtifactPath
                                    );
                                    const firstGeneratedImage = (resultData.artifacts || []).find((item) =>
                                        String(item.mime_type || '').startsWith('image/')
                                    );
                                    if (!selected && !resultData.preview_image_data_url && !firstGeneratedImage) {
                                        return null;
                                    }

                                    return (
                                        <div className="large-preview-wrap">
                                            <img
                                                src={selected
                                                    ? `${API_BASE}${selected.view_url}`
                                                    : (resultData.preview_image_data_url || `${API_BASE}${firstGeneratedImage.view_url}`)}
                                                alt="Selected preview"
                                            />
                                            <div className="large-preview-label">
                                                {selected ? selected.name : (firstGeneratedImage ? firstGeneratedImage.name : 'Generated preview')}
                                            </div>
                                        </div>
                                    );
                                })()}

                                {resultData.artifacts && resultData.artifacts.length > 0 && (
                                    <>
                                        <div className="help-text" style={{ color: '#cdd8ea', marginBottom: '8px' }}>
                                            Generated files
                                        </div>
                                        <div className="artifact-list">
                                            {resultData.artifacts.map((file) => {
                                                const fileName = file.name || file.relative_path || 'Unknown';
                                                const fileSize = Math.round((file.size_bytes || 0) / 1024);
                                                const fileType = getFileTypeInfo(fileName);
                                                return (
                                                    <div key={file.relative_path} className="artifact-item">
                                                        <div className="file-name" title={fileName}>
                                                            {fileType.emoji} {fileType.label}
                                                        </div>
                                                        <div className="file-size">{fileSize} KB • {getFileExtension(fileName)}</div>
                                                        <div className="file-actions">
                                                            <a href={`${API_BASE}${file.view_url}`} target="_blank" rel="noreferrer">👁️ View</a>
                                                            <a href={`${API_BASE}${file.download_url}`} target="_blank" rel="noreferrer" download>📥 Download</a>
                                                        </div>
                                                    </div>
                                                );
                                            })}
                                        </div>
                                    </>
                                )}

                                {(!resultData.artifacts || resultData.artifacts.length === 0) &&
                                 (!resultData.input_artifacts || resultData.input_artifacts.length === 0) && (
                                    <div className="artifacts-empty" style={{ padding: '20px 0 0', color: '#b9c7e3' }}>
                                        <p>No renderable output files were returned for this run.</p>
                                    </div>
                                )}
                            </>
                        ) : (
                            <div className="artifacts-empty">
                                <p>📂 Temp-store files and generated files will appear here</p>
                            </div>
                        )}
                    </div>
                </div>
            );
        }
        
        function PaymentSection({ authenticatedUser, onAction }) {
            const [selectedTier, setSelectedTier] = useState('starter');
            const [status, setStatus] = useState({ type: null, message: '' });
            const [loading, setLoading] = useState(false);
            const [tiers, setTiers] = useState([]);
            const [catalog, setCatalog] = useState(null);
            const [loadingTiers, setLoadingTiers] = useState(true);
            const customerEmail = (authenticatedUser && authenticatedUser.email) ? authenticatedUser.email : '';

            useEffect(() => {
                let active = true;

                const loadPaymentCatalog = async () => {
                    setLoadingTiers(true);
                    try {
                        const response = await fetch(`${API_BASE}/api/tiers`);
                        if (!response.ok) {
                            const text = await response.text();
                            throw new Error(text || 'Failed to load payment tiers');
                        }

                        const payload = await response.json();
                        const tierItems = Array.isArray(payload.tiers) ? payload.tiers : [];
                        if (!active) return;

                        setCatalog(payload.catalog || null);
                        setTiers(tierItems);
                        if (tierItems.length > 0) {
                            const starter = tierItems.find(item => (item.tier || '').toLowerCase() === 'starter');
                            setSelectedTier((starter && starter.tier) ? starter.tier : (tierItems[0].tier || 'starter'));
                        }
                    } catch (error) {
                        if (!active) return;
                        setStatus({ type: 'error', message: `❌ Pricing unavailable: ${error.message}` });
                    } finally {
                        if (active) {
                            setLoadingTiers(false);
                        }
                    }
                };

                loadPaymentCatalog();
                return () => {
                    active = false;
                };
            }, []);
            
            const handlePayment = async (e) => {
                e.preventDefault();
                
                if (!customerEmail.trim()) {
                    setStatus({ type: 'error', message: 'Please sign in with Google before purchasing credits' });
                    return;
                }

                if (!tiers.some(item => item.tier === selectedTier)) {
                    setStatus({ type: 'error', message: 'Please select a valid payment tier' });
                    return;
                }
                
                setLoading(true);
                setStatus({ type: 'loading', message: 'Redirecting to payment...' });
                
                try {
                    const response = await fetch(`${API_BASE}/api/checkout`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({
                            tier: selectedTier,
                            customer_email: customerEmail,
                            user_id: (authenticatedUser && authenticatedUser.uid) ? authenticatedUser.uid : undefined
                        })
                    });
                    
                    if (!response.ok) {
                        const errorData = await response.json();
                        throw new Error(errorData.detail || 'Payment setup failed');
                    }
                    
                    const result = await response.json();
                    if (onAction) {
                        onAction('checkout_started');
                    }
                    // Open Stripe checkout in new tab (_blank) and keep current session
                    window.open(result.checkout_url, '_blank');
                } catch (error) {
                    setStatus({
                        type: 'error',
                        message: `❌ Error: ${error.message}`
                    });
                    setLoading(false);
                }
            };
            
            return (
                <>
                    <div className="card">
                        <h2>Purchase Credits</h2>
                        <form onSubmit={handlePayment}>
                            {status.type && (
                                <div className={`status-message status-${status.type}`}>
                                    {status.type === 'loading' && <span className="loader"></span>}
                                    {' '}{status.message}
                                </div>
                            )}
                            
                            <div className="form-group">
                                <label>Select Package</label>
                                <div className="tier-selector">
                                    {tiers.map(tier => (
                                        <div
                                            key={tier.tier}
                                            className={`tier-card ${selectedTier === tier.tier ? 'selected' : ''}`}
                                            onClick={() => setSelectedTier(tier.tier)}
                                        >
                                            <h3>{tier.name || tier.tier}</h3>
                                            <div className="credits">{tier.credits} Credits</div>
                                            <div className="price">{tier.price_display || '-'}</div>
                                            <div className="help-text" style={{ marginTop: '6px' }}>
                                                Unit: {tier.unit_price_display || '-'}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                                {loadingTiers && <div className="help-text">Loading pricing...</div>}
                                {!loadingTiers && tiers.length === 0 && (
                                    <div className="help-text">No payment tiers available.</div>
                                )}
                            </div>

                            {catalog && (
                                <div className="form-group">
                                    <label>Stripe Catalog</label>
                                    <div className="help-text">Product ID: {catalog.product_id || 'n/a'}</div>
                                    <div className="help-text">Price ID: {catalog.price_id || 'n/a'}</div>
                                    <div className="help-text">Unit Price: {catalog.unit_price_display || 'n/a'}</div>
                                </div>
                            )}
                            
                            <div className="form-group">
                                <label>Authenticated Email</label>
                                <div className="help-text">
                                    {customerEmail ? `Receipt will be sent to ${customerEmail}` : 'Sign in with Google to use your account email for checkout.'}
                                </div>
                            </div>
                            
                            <div className="button-group">
                                <button type="submit" className="btn-primary" disabled={loading || loadingTiers || tiers.length === 0}>
                                    {loading ? (
                                        <>
                                            <span className="loader"></span> Processing...
                                        </>
                                    ) : (
                                        '💳 Proceed to Payment'
                                    )}
                                </button>
                            </div>
                        </form>
                    </div>
                </>
            );
        }
        
        ReactDOM.render(<App />, document.getElementById('root'));
    </script>
</body>
</html>
"""


frontend_app = FastAPI(title="lighter0-frontend", version="1.0.0")
frontend_static_dir = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.isdir(frontend_static_dir):
    frontend_app.mount("/static", StaticFiles(directory=frontend_static_dir), name="static")


@frontend_app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main frontend HTML with React UI."""
    return HTML_TEMPLATE


@frontend_app.get("/index.html", response_class=HTMLResponse)
async def index():
    """Serve the main frontend HTML with React UI."""
    return HTML_TEMPLATE


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(frontend_app, host="0.0.0.0", port=3000)
