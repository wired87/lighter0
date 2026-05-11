        const { useState, useEffect } = React;
        const API_BASE = window.location.port === '3000' ? 'http://localhost:8000' : '';
        const RUNTIME_CONFIG = window.LIGHTER0_RUNTIME_CONFIG || {};
        const ADMIN_CONTACT_NAME = String(RUNTIME_CONFIG.adminContactName || 'Benedikt Sterra');
        const ADMIN_CONTACT_EMAIL = String(RUNTIME_CONFIG.adminContactEmail || 'office@botworld.cloud');

        // localStorage helpers for persistent authentication state
        const LOCAL_STORAGE_USER_KEY = 'lighter0_authenticated_user';
        const LOCAL_STORAGE_TOKEN_KEY = 'lighter0_cached_id_token';
        const PAYMENT_WEBHOOK_LAST_TOAST_EVENT_KEY = 'lighter0_last_payment_webhook_toast_event_id';
        const AUTH_BOOT_TIMEOUT_MS = 2500;
        let googleAuthInitPromise = null;
        
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

        function clearCachedAuthToken() {
            localStorage.removeItem(LOCAL_STORAGE_TOKEN_KEY);
        }

        function loadLastPaymentWebhookToastEventId() {
            return String(localStorage.getItem(PAYMENT_WEBHOOK_LAST_TOAST_EVENT_KEY) || '').trim();
        }

        function saveLastPaymentWebhookToastEventId(eventId) {
            const cleanEventId = String(eventId || '').trim();
            if (!cleanEventId) {
                return;
            }
            localStorage.setItem(PAYMENT_WEBHOOK_LAST_TOAST_EVENT_KEY, cleanEventId);
        }

        function saveCachedAuthToken(token, expiresAtMs) {
            if (!token) {
                clearCachedAuthToken();
                return;
            }
            const payload = {
                token,
                expiresAtMs: Number(expiresAtMs || 0),
            };
            localStorage.setItem(LOCAL_STORAGE_TOKEN_KEY, JSON.stringify(payload));
        }

        function loadCachedAuthToken() {
            try {
                const raw = localStorage.getItem(LOCAL_STORAGE_TOKEN_KEY);
                if (!raw) {
                    return null;
                }
                const parsed = JSON.parse(raw);
                const token = String((parsed && parsed.token) || '').trim();
                const expiresAtMs = Number((parsed && parsed.expiresAtMs) || 0);
                if (!token || !Number.isFinite(expiresAtMs)) {
                    clearCachedAuthToken();
                    return null;
                }
                // Safety margin to avoid using almost-expired tokens.
                if (Date.now() >= (expiresAtMs - 60 * 1000)) {
                    clearCachedAuthToken();
                    return null;
                }
                return token;
            } catch (error) {
                clearCachedAuthToken();
                return null;
            }
        }

        function decodeJwtExpiryMs(token) {
            try {
                const parts = String(token || '').split('.');
                if (parts.length < 2) {
                    return 0;
                }
                const normalized = parts[1].replace(/-/g, '+').replace(/_/g, '/');
                const payload = JSON.parse(atob(normalized));
                const exp = Number(payload && payload.exp);
                if (!Number.isFinite(exp) || exp <= 0) {
                    return 0;
                }
                return exp * 1000;
            } catch (_) {
                return 0;
            }
        }

        // Process Result Store (Redux-like with localStorage persistence)
        const PROCESS_RESULT_STORE_KEY = 'lighter0_latest_process_result';

        function saveProcessResultToStore(processResponse) {
            if (!processResponse) {
                localStorage.removeItem(PROCESS_RESULT_STORE_KEY);
                return;
            }
            try {
                localStorage.setItem(PROCESS_RESULT_STORE_KEY, JSON.stringify(processResponse));
            } catch (error) {
                console.warn('Failed to persist process result:', error);
            }
        }

        function loadProcessResultFromStore() {
            try {
                const stored = localStorage.getItem(PROCESS_RESULT_STORE_KEY);
                return stored ? JSON.parse(stored) : null;
            } catch (error) {
                console.warn('Failed to load process result from store:', error);
                return null;
            }
        }

        function useProcessResultStore() {
            const [resultData, setResultData] = useState(() => loadProcessResultFromStore());

            const updateResultData = (data) => {
                saveProcessResultToStore(data);
                setResultData(data);
            };

            return [resultData, updateResultData];
        }

        async function refreshAndStoreFirebaseIdToken(forceRefresh) {
            if (!window.auth || !window.auth.currentUser) {
                return null;
            }
            const currentUser = window.auth.currentUser;
            if (!currentUser.getIdToken) {
                return null;
            }

            const token = await currentUser.getIdToken(!!forceRefresh);
            let expiresAtMs = 0;
            if (currentUser.getIdTokenResult) {
                try {
                    const tokenResult = await currentUser.getIdTokenResult();
                    expiresAtMs = Date.parse(tokenResult && tokenResult.expirationTime ? tokenResult.expirationTime : '');
                } catch (_) {
                    expiresAtMs = 0;
                }
            }
            if (!Number.isFinite(expiresAtMs) || expiresAtMs <= 0) {
                expiresAtMs = decodeJwtExpiryMs(token);
            }
            saveCachedAuthToken(token, expiresAtMs);
            return token;
        }

        async function ensureFirebaseAuthInitialized() {
            if (window.auth && window.auth.currentUser) {
                return true;
            }
            if (!window.firebaseConfig || !window.GoogleAuth || !window.GoogleAuth.initializeGoogleAuth) {
                return false;
            }

            if (window.GoogleAuth.ensureFirebaseReady) {
                try {
                    await window.GoogleAuth.ensureFirebaseReady({
                        endpoint: `${API_BASE}/api/auth-user`,
                    });
                } catch (error) {
                    console.warn('Firebase namespace bootstrap failed:', error);
                }
            }

            if (!googleAuthInitPromise) {
                googleAuthInitPromise = window.GoogleAuth.initializeGoogleAuth({
                    endpoint: `${API_BASE}/api/auth-user`,
                }).catch((error) => {
                    console.warn('Firebase auth bootstrap failed:', error);
                    return false;
                });
            }

            await googleAuthInitPromise;

            if (!window.auth || !window.auth.onAuthStateChanged) {
                return !!(window.auth && window.auth.currentUser);
            }

            if (window.auth.currentUser) {
                return true;
            }

            return await new Promise((resolve) => {
                let resolved = false;
                const timeout = window.setTimeout(() => {
                    if (resolved) return;
                    resolved = true;
                    if (typeof unsubscribe === 'function') {
                        unsubscribe();
                    }
                    resolve(!!(window.auth && window.auth.currentUser));
                }, AUTH_BOOT_TIMEOUT_MS);

                const unsubscribe = window.auth.onAuthStateChanged(() => {
                    if (resolved) return;
                    resolved = true;
                    window.clearTimeout(timeout);
                    if (typeof unsubscribe === 'function') {
                        unsubscribe();
                    }
                    if (window.auth && window.auth.currentUser) {
                        refreshAndStoreFirebaseIdToken(false).catch(() => {});
                    } else {
                        clearCachedAuthToken();
                    }
                    resolve(!!(window.auth && window.auth.currentUser));
                }, () => {
                    if (resolved) return;
                    resolved = true;
                    window.clearTimeout(timeout);
                    if (typeof unsubscribe === 'function') {
                        unsubscribe();
                    }
                    clearCachedAuthToken();
                    resolve(false);
                });
            });
        }

        async function getFirebaseIdToken(forceRefresh) {
            try {
                await ensureFirebaseAuthInitialized();
                if (!window.auth || !window.auth.currentUser || !window.auth.currentUser.getIdToken) {
                    return loadCachedAuthToken();
                }
                return await refreshAndStoreFirebaseIdToken(!!forceRefresh);
            } catch (error) {
                console.warn('Failed to get Firebase ID token:', error);
                return loadCachedAuthToken();
            }
        }

        async function buildApiHeaders(extraHeaders) {
            const headers = { ...(extraHeaders || {}) };
            const token = await getFirebaseIdToken();
            if (token) {
                headers['Authorization'] = `Bearer ${token}`;
            }
            return headers;
        }

        async function apiFetch(url, options) {
            const requestOptions = { ...(options || {}) };
            requestOptions.headers = await buildApiHeaders(requestOptions.headers);

            let response = await fetch(url, requestOptions);
            if (response.status !== 401) {
                return response;
            }

            const refreshedToken = await getFirebaseIdToken(true);
            if (!refreshedToken) {
                return response;
            }

            requestOptions.headers = {
                ...(requestOptions.headers || {}),
                Authorization: `Bearer ${refreshedToken}`,
            };
            response = await fetch(url, requestOptions);
            return response;
        }

        async function extractErrorMessage(response, fallbackMessage) {
            const fallback = fallbackMessage || `Request failed with status ${response.status}`;
            try {
                const payload = await response.json();
                if (payload && typeof payload === 'object') {
                    if (typeof payload.detail === 'string' && payload.detail.trim()) {
                        return payload.detail;
                    }
                    if (typeof payload.error === 'string' && payload.error.trim()) {
                        return payload.error;
                    }
                    if (typeof payload.message === 'string' && payload.message.trim()) {
                        return payload.message;
                    }
                }
            } catch (_) {
                // Ignore parsing errors and fall back to plain text below.
            }

            try {
                const text = await response.text();
                if (text && text.trim()) {
                    return text.trim();
                }
            } catch (_) {
                // Ignore text decoding errors.
            }
            return fallback;
        }

        function normalizeFreeGenerationStatus(payload) {
            if (!payload || typeof payload !== 'object') {
                return null;
            }

            const used = Number(payload.free_generations_used || 0);
            const limit = Number(payload.free_generations_limit || 0);
            return {
                can_use_free: !!payload.can_use_free,
                free_generations_used: Number.isFinite(used) ? used : 0,
                free_generations_limit: Number.isFinite(limit) ? limit : 0,
                last_free_generation_date: payload.last_free_generation_date || null,
            };
        }

        function getFreeGenerationStatusText(status) {
            if (!status) {
                return 'Loading free tries...';
            }

            const used = Number(status.free_generations_used || 0);
            const limit = Number(status.free_generations_limit || 0);
            return status.can_use_free
                ? `✨ Free try available: ${used}/${limit} used today`
                : `⭐ Daily free try used: ${used}/${limit} used today`;
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
                                'mp4': { emoji: '🎞️', label: 'MP4 Video', category: 'video' },
                                'webm': { emoji: '🎞️', label: 'WebM Video', category: 'video' },
                'pdf': { emoji: '📄', label: 'PDF Document', category: 'document' },
                'json': { emoji: '📋', label: 'JSON Data', category: 'data' },
                'html': { emoji: '🌐', label: 'HTML Document', category: 'web' },
                                'htm': { emoji: '🌐', label: 'HTML Document', category: 'web' },
                                'stl': { emoji: '🧊', label: 'STL 3D Model', category: 'model' },
                'zip': { emoji: '📦', label: 'ZIP Archive', category: 'archive' },
                'txt': { emoji: '📝', label: 'Text File', category: 'document' }
            };
            return typeMap[ext] || { emoji: '📁', label: fileName, category: 'file' };
        }

                function getArtifactExtension(file) {
                        return String((file && (file.name || file.relative_path || ''))).split('.').pop().toLowerCase();
                }

                function getArtifactPreviewMode(file) {
                        if (!file) return 'empty';

                        const fileName = String(file.name || file.relative_path || '').toLowerCase();
                        const ext = getArtifactExtension(file);
                        const mime = String(file.mime_type || '').toLowerCase();

                        if (ext === 'stl' || mime === 'model/stl' || mime === 'application/sla') {
                                return 'stl';
                        }

                        if (ext === 'html' || ext === 'htm' || mime === 'text/html') {
                                return 'html';
                        }

                        if (ext === 'json' || mime.includes('json')) {
                                return 'json';
                        }

                        if (ext === 'mp4' || ext === 'webm' || mime.startsWith('video/')) {
                                return 'video';
                        }

                        if (ext === 'gif' || ext === 'webp') {
                                return 'animation';
                        }

                        if (ext === 'svg') {
                                return fileName.includes('animated') ? 'animation' : 'image';
                        }

                        if (mime.startsWith('image/')) {
                                return 'image';
                        }

                        if (ext === 'txt' || mime.startsWith('text/')) {
                                return 'text';
                        }

                        return 'file';
                }

                function buildStlViewerSrcDoc(modelUrl, title) {
                        const safeUrl = JSON.stringify(modelUrl || '');
                        const safeTitle = JSON.stringify(title || '3D Model');
                        const safeTitleAttr = String(title || '3D Model').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

                        return `<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>${safeTitleAttr}</title>
    <style>
        html, body { width: 100%; height: 100%; margin: 0; overflow: hidden; background: radial-gradient(circle at top, #1d2440 0%, #0c1020 52%, #05070f 100%); color: #eaf1ff; font-family: Arial, sans-serif; }
        #wrap { position: relative; width: 100%; height: 100%; }
        #hud { position: absolute; left: 14px; top: 14px; z-index: 2; padding: 10px 12px; border-radius: 10px; background: rgba(8, 12, 24, 0.68); backdrop-filter: blur(10px); border: 1px solid rgba(175, 190, 255, 0.15); box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35); }
        #hud .title { font-size: 13px; font-weight: 700; margin-bottom: 4px; }
        #hud .sub { font-size: 11px; opacity: 0.72; line-height: 1.4; }
        #status { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; z-index: 1; font-size: 13px; color: rgba(234, 241, 255, 0.8); letter-spacing: 0.02em; }
        canvas { display: block; width: 100%; height: 100%; }
    </style>
</head>
<body>
    <div id="wrap">
        <div id="hud">
            <div class="title">${safeTitleAttr}</div>
            <div class="sub">Drag to rotate · scroll to zoom · right-click to pan</div>
        </div>
        <div id="status">Loading STL preview...</div>
    </div>
    <script type="module">
        import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.164.1/build/three.module.js';
        import { STLLoader } from 'https://cdn.jsdelivr.net/npm/three@0.164.1/examples/jsm/loaders/STLLoader.js';
        import { OrbitControls } from 'https://cdn.jsdelivr.net/npm/three@0.164.1/examples/jsm/controls/OrbitControls.js';

        const MODEL_URL = ${safeUrl};
        const STATUS = document.getElementById('status');
        const WRAP = document.getElementById('wrap');

        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0x08101f);

        const camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 0.1, 5000);
        camera.position.set(120, 120, 160);

        const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
        renderer.setPixelRatio(window.devicePixelRatio || 1);
        renderer.setSize(window.innerWidth, window.innerHeight);
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        WRAP.appendChild(renderer.domElement);

        const controls = new OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;
        controls.dampingFactor = 0.08;
        controls.target.set(0, 0, 0);

        scene.add(new THREE.AmbientLight(0xffffff, 1.0));
        const key = new THREE.DirectionalLight(0xffffff, 2.3);
        key.position.set(1, 1.5, 2);
        scene.add(key);
        const fill = new THREE.DirectionalLight(0x8fb6ff, 0.65);
        fill.position.set(-2, -1, 1.2);
        scene.add(fill);

        const grid = new THREE.GridHelper(280, 14, 0x5c678b, 0x25304a);
        grid.position.y = -70;
        scene.add(grid);

        const loader = new STLLoader();

        function fitCamera(object3d) {
            const box = new THREE.Box3().setFromObject(object3d);
            const size = box.getSize(new THREE.Vector3());
            const center = box.getCenter(new THREE.Vector3());
            object3d.position.x -= center.x;
            object3d.position.y -= center.y;
            object3d.position.z -= center.z;
            const maxSize = Math.max(size.x, size.y, size.z) || 1;
            const fitDistance = maxSize * 1.9;
            camera.position.set(fitDistance, fitDistance * 0.8, fitDistance);
            camera.near = maxSize / 100;
            camera.far = maxSize * 20;
            camera.updateProjectionMatrix();
            controls.target.set(0, 0, 0);
            controls.update();
        }

        loader.load(MODEL_URL, (geometry) => {
            geometry.computeVertexNormals();
            const material = new THREE.MeshStandardMaterial({ color: 0xf3f6ff, metalness: 0.05, roughness: 0.92, flatShading: false });
            const mesh = new THREE.Mesh(geometry, material);
            mesh.rotation.x = -Math.PI / 2;
            scene.add(mesh);
            fitCamera(mesh);
            STATUS.style.display = 'none';
        }, undefined, (error) => {
            STATUS.textContent = 'Failed to load STL preview.';
            console.error(error);
        });

        window.addEventListener('resize', () => {
            camera.aspect = window.innerWidth / window.innerHeight;
            camera.updateProjectionMatrix();
            renderer.setSize(window.innerWidth, window.innerHeight);
        });

        function animate() {
            requestAnimationFrame(animate);
            controls.update();
            renderer.render(scene, camera);
        }

        animate();
    </script>
</body>
</html>`;
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
            const [authenticatedUser, setAuthenticatedUser] = useState(loadAuthenticatedUserFromStorage());
            const [userProfile, setUserProfile] = useState(null);
            const [loadingProfile, setLoadingProfile] = useState(false);
            const [freeGenerationStatus, setFreeGenerationStatus] = useState(null);
            const [toast, setToast] = useState(null);
            const [activity, setActivity] = useState({
                generations: 0,
                lastAction: 'No actions yet.'
            });

            const resetAuthSession = (message) => {
                saveAuthenticatedUserToStorage(null);
                clearCachedAuthToken();
                setAuthenticatedUser(null);
                setUserProfile(null);
                setFreeGenerationStatus(null);
                if (message) {
                    setAuthStatus(message);
                }
            };

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
                    const response = await apiFetch(`${API_BASE}/api/free-generation-status?${query.toString()}`);
                    if (!response.ok) {
                        if (response.status === 401) {
                            resetAuthSession('Session expired. Please sign in again.');
                            return;
                        }
                        throw new Error(await extractErrorMessage(response, 'Failed to load free generation status'));
                    }
                    const payload = await response.json();
                    if (payload && payload.success) {
                        setFreeGenerationStatus(normalizeFreeGenerationStatus(payload));
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
                    const response = await apiFetch(`${API_BASE}/api/user-profile?${query.toString()}`);
                    if (!response.ok) {
                        if (response.status === 401) {
                            resetAuthSession('Session expired. Please sign in again.');
                            return;
                        }
                        throw new Error(await extractErrorMessage(response, 'Failed to load user profile'));
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
                            refreshAndStoreFirebaseIdToken(true).catch(() => {});
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
                    clearCachedAuthToken();
                    setAuthenticatedUser(null);
                    setUserProfile(null);
                    setActivity({ generations: 0, lastAction: 'No actions yet.' });
                    setAuthStatus('Not authenticated');
                }
            };

            useEffect(() => {
                ensureFirebaseAuthInitialized();
            }, []);

            useEffect(() => {
                if (authenticatedUser) {
                    refreshUserProfile(authenticatedUser);
                    refreshFreeGenerationStatus(authenticatedUser);
                }
            }, [authenticatedUser]);

            useEffect(() => {
                if (!authenticatedUser) {
                    return;
                }

                let cancelled = false;

                const pollPaymentWebhookNotification = async () => {
                    const email = (authenticatedUser.email || '').trim();
                    const uid = (authenticatedUser.uid || '').trim();
                    if (!email && !uid) {
                        return;
                    }

                    try {
                        const query = new URLSearchParams();
                        if (email) query.set('email', email);
                        if (uid) query.set('uid', uid);
                        const response = await apiFetch(`${API_BASE}/api/payment/webhook-latest?${query.toString()}`);
                        if (!response.ok) {
                            return;
                        }

                        const payload = await response.json();
                        const notification = payload && payload.success ? payload.notification : null;
                        if (!notification) {
                            return;
                        }

                        const eventId = String(notification.event_id || '').trim();
                        if (!eventId) {
                            return;
                        }

                        if (eventId === loadLastPaymentWebhookToastEventId()) {
                            return;
                        }

                        saveLastPaymentWebhookToastEventId(eventId);
                        if (cancelled) {
                            return;
                        }

                        const isSuccess = String(notification.status || '').toLowerCase() === 'success';
                        setToast({
                            type: isSuccess ? 'success' : 'error',
                            title: notification.title || (isSuccess ? 'Payment successful' : 'Payment failed'),
                            message: notification.message || (isSuccess
                                ? 'Credits purchase completed and applied to your account.'
                                : 'Payment was not completed. No credits were applied.'),
                        });
                        refreshUserProfile(authenticatedUser);
                    } catch (_) {
                        // Best-effort polling only.
                    }
                };

                pollPaymentWebhookNotification();
                const intervalId = window.setInterval(pollPaymentWebhookNotification, 4000);
                return () => {
                    cancelled = true;
                    window.clearInterval(intervalId);
                };
            }, [authenticatedUser]);

            useEffect(() => {
                const params = new URLSearchParams(window.location.search || '');
                const checkout = (params.get('checkout') || '').trim().toLowerCase();
                if (checkout !== 'success' && checkout !== 'cancel' && checkout !== 'failed') {
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
                        title: 'Payment failed or canceled',
                        message: 'Checkout did not complete. No charge was made.'
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

                    <div className="main-content">
                        <CoverArtGenerator authenticatedUser={authenticatedUser} freeGenerationStatus={freeGenerationStatus} onFreeGenerationStatusChange={setFreeGenerationStatus} onAction={recordAction} />
                    </div>

                    <div className="main-content" style={{ marginTop: '40px', borderTop: '1px solid #d8deea', paddingTop: '40px' }}>
                        <PaymentSection authenticatedUser={authenticatedUser} onAction={recordAction} />
                    </div>

                    {toast && (
                        <div className="toast-wrap" aria-live="polite" aria-atomic="true">
                            <div className={`toast-card ${toast.type === 'success' ? 'toast-success' : 'toast-error'}`}>
                                <strong>{toast.title}</strong>
                                <p>{toast.message}</p>
                            </div>
                        </div>
                    )}

                    <footer style={{ marginTop: '20px', padding: '16px 18px', border: '1px solid #dfe5f0', borderRadius: '12px', background: '#f8faff', color: '#30405f' }}>
                        <div style={{ fontWeight: 700, marginBottom: '8px' }}>Impressum</div>
                        <div style={{ marginBottom: '6px' }}>Admin Kontakt: {ADMIN_CONTACT_NAME}</div>
                        <div style={{ marginBottom: '8px' }}>
                            Admin E-Mail: <a href={`mailto:${ADMIN_CONTACT_EMAIL}`}>{ADMIN_CONTACT_EMAIL}</a>
                        </div>
                        <div style={{ fontSize: '14px' }}>
                            Datenschutz:{' '}
                            <a
                                href={window.BRAINMASTER_PRIVACY_POLICY_URL || 'https://botworld.cloud/privacy-policy'}
                                target="_blank"
                                rel="noreferrer"
                            >
                                Privacy Policy
                            </a>
                            {' '}|{' '}
                            Terms:{' '}
                            <a href="/static/terms_of_service.html" target="_blank" rel="noreferrer">
                                Terms of Service
                            </a>
                        </div>
                    </footer>
                </div>
            );
        }

        function CoverArtGenerator({ authenticatedUser, freeGenerationStatus, onFreeGenerationStatusChange, onAction }) {
            const [resultData, setResultData] = useProcessResultStore();
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
                use_free: freeGenerationStatus && freeGenerationStatus.can_use_free,
                generate_svg: true,
                generate_stl: true,
                generate_html: true,
                generate_animation: true,
            });
            
            const [status, setStatus] = useState({ type: null, message: '' });
            const [loading, setLoading] = useState(false);
            const [selectedPreviewArtifactPath, setSelectedPreviewArtifactPath] = useState('');
            const [selectedArtifactText, setSelectedArtifactText] = useState('');
            const [selectedArtifactTextLoading, setSelectedArtifactTextLoading] = useState(false);
            const [selectedArtifactTextError, setSelectedArtifactTextError] = useState('');

            useEffect(() => {
                setFormData(prev => ({
                    ...prev,
                    use_free: !!(freeGenerationStatus && freeGenerationStatus.can_use_free)
                }));
            }, [freeGenerationStatus && freeGenerationStatus.can_use_free]);

            const getArtifactKey = (file) => {
                if (!file) return '';
                return String(file.firebase_path || file.relative_path || file.name || '');
            };
            
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

            const activeResultData = resultData;
            const allFolderItems = (activeResultData && Array.isArray(activeResultData.artifacts)) ? activeResultData.artifacts : [];
            const selectedPreviewArtifact = allFolderItems.find((item) => getArtifactKey(item) === selectedPreviewArtifactPath) || null;
            const selectedPreviewMode = getArtifactPreviewMode(selectedPreviewArtifact);

            useEffect(() => {
                if (allFolderItems.length === 0) {
                    setSelectedPreviewArtifactPath('');
                    return;
                }
                const preferredArtifact = allFolderItems.find((item) => {
                    const mode = getArtifactPreviewMode(item);
                    return mode === 'image' || mode === 'animation' || mode === 'video' || mode === 'json' || mode === 'html' || mode === 'stl';
                }) || allFolderItems[0];
                const preferredKey = getArtifactKey(preferredArtifact);
                if (preferredKey && preferredKey !== selectedPreviewArtifactPath) {
                    setSelectedPreviewArtifactPath(preferredKey);
                }
            }, [resultData]);

            useEffect(() => {
                let cancelled = false;

                if (!selectedPreviewArtifact || selectedPreviewMode !== 'json' || !selectedPreviewArtifact.view_url) {
                    setSelectedArtifactText('');
                    setSelectedArtifactTextLoading(false);
                    setSelectedArtifactTextError('');
                    return () => {
                        cancelled = true;
                    };
                }

                setSelectedArtifactText('');
                setSelectedArtifactTextError('');
                setSelectedArtifactTextLoading(true);

                (async () => {
                    try {
                        const response = await fetch(`${API_BASE}${selectedPreviewArtifact.view_url}`);
                        if (!response.ok) {
                            throw new Error(`Failed to load JSON preview (${response.status})`);
                        }
                        const rawText = await response.text();
                        let formattedText = rawText;
                        try {
                            formattedText = JSON.stringify(JSON.parse(rawText), null, 2);
                        } catch (_) {
                            // Keep raw text if the payload is not strict JSON.
                        }
                        if (!cancelled) {
                            setSelectedArtifactText(formattedText);
                            setSelectedArtifactTextError('');
                        }
                    } catch (error) {
                        if (!cancelled) {
                            setSelectedArtifactTextError(error && error.message ? error.message : 'Failed to load JSON preview');
                        }
                    } finally {
                        if (!cancelled) {
                            setSelectedArtifactTextLoading(false);
                        }
                    }
                })();

                return () => {
                    cancelled = true;
                };
            }, [selectedPreviewArtifactPath, resultData]);

            const renderSelectedArtifactPreview = () => {
                if (!selectedPreviewArtifact) {
                    return (
                        <div style={{ padding: '24px', textAlign: 'center', color: '#6d7890', fontStyle: 'italic' }}>
                            No artifact selected. Generate output or choose a file below.
                        </div>
                    );
                }

                const previewUrl = `${API_BASE}${selectedPreviewArtifact.view_url || ''}`;
                const fileTitle = selectedPreviewArtifact.name || selectedPreviewArtifact.relative_path || 'Generated artifact';

                if (selectedPreviewMode === 'html') {
                    return (
                        <div className="large-preview-wrap" style={{ padding: 0, overflow: 'hidden' }}>
                            <iframe
                                src={previewUrl}
                                title={fileTitle}
                                style={{ width: '100%', height: '560px', border: 'none', background: '#fff' }}
                                sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
                            />
                            <div className="large-preview-label" style={{ position: 'static', marginTop: '10px' }}>
                                {fileTitle}
                            </div>
                        </div>
                    );
                }

                if (selectedPreviewMode === 'stl') {
                    return (
                        <div className="large-preview-wrap" style={{ padding: 0, overflow: 'hidden' }}>
                            <iframe
                                srcDoc={buildStlViewerSrcDoc(previewUrl, fileTitle)}
                                title={fileTitle}
                                style={{ width: '100%', height: '560px', border: 'none', background: '#08101f' }}
                                loading="lazy"
                            />
                            <div className="large-preview-label" style={{ position: 'static', marginTop: '10px' }}>
                                {fileTitle}
                            </div>
                        </div>
                    );
                }

                if (selectedPreviewMode === 'json') {
                    return (
                        <div className="large-preview-wrap" style={{ padding: '18px', alignItems: 'stretch' }}>
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
                                <div className="large-preview-label" style={{ position: 'static', margin: 0 }}>
                                    {fileTitle}
                                </div>
                                <a href={previewUrl} target="_blank" rel="noreferrer" style={{ color: 'var(--accent)', textDecoration: 'none', fontSize: '0.85em' }}>
                                    Open raw
                                </a>
                            </div>
                            {selectedArtifactTextLoading ? (
                                <div style={{ padding: '20px', color: '#cdd8ea' }}>Loading JSON preview...</div>
                            ) : selectedArtifactTextError ? (
                                <div style={{ padding: '20px', color: '#ffb4b4' }}>{selectedArtifactTextError}</div>
                            ) : (
                                <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: '560px', overflow: 'auto', color: '#eef4ff', background: 'rgba(4, 10, 22, 0.75)', border: '1px solid var(--line-1)', borderRadius: '10px', padding: '16px', fontSize: '0.84em', lineHeight: 1.55 }}>
                                    {selectedArtifactText || '{}'}
                                </pre>
                            )}
                        </div>
                    );
                }

                if (selectedPreviewMode === 'animation') {
                    if (String(selectedPreviewArtifact.mime_type || '').startsWith('video/')) {
                        return (
                            <div className="large-preview-wrap" style={{ padding: 0, overflow: 'hidden' }}>
                                <video
                                    src={previewUrl}
                                    controls
                                    autoPlay
                                    loop
                                    muted
                                    playsInline
                                    style={{ width: '100%', maxHeight: '560px', background: '#0a1220' }}
                                />
                                <div className="large-preview-label" style={{ position: 'static', marginTop: '10px' }}>
                                    {fileTitle}
                                </div>
                            </div>
                        );
                    }

                    return (
                        <div className="large-preview-wrap" style={{ padding: 0, overflow: 'hidden' }}>
                            <object
                                data={previewUrl}
                                type="image/svg+xml"
                                style={{ width: '100%', height: '560px', border: 'none', background: '#0a1220' }}
                            >
                                <img src={previewUrl} alt={fileTitle} style={{ width: '100%', maxHeight: '560px', objectFit: 'contain' }} />
                            </object>
                            <div className="large-preview-label" style={{ position: 'static', marginTop: '10px' }}>
                                {fileTitle}
                            </div>
                        </div>
                    );
                }

                if (selectedPreviewMode === 'image') {
                    return (
                        <div className="large-preview-wrap">
                            <img src={previewUrl} alt={fileTitle} />
                            <div className="large-preview-label">
                                {fileTitle}
                            </div>
                        </div>
                    );
                }

                return (
                    <div style={{ padding: '24px', textAlign: 'center', color: '#6d7890', fontStyle: 'italic' }}>
                        This file type can be downloaded, but no inline preview is available.
                    </div>
                );
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
                        use_free: formData.use_free || false,
                        generate_svg: formData.generate_svg !== false,
                        generate_stl: formData.generate_stl !== false,
                        generate_html: formData.generate_html !== false,
                        generate_animation: formData.generate_animation !== false,
                    };
                    const response = await apiFetch(`${API_BASE}/api/process`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify(payload)
                    });
                    
                    if (!response.ok) {
                        throw new Error(await extractErrorMessage(response, 'Generation failed'));
                    }
                    
                    const result = await response.json();
                    if (!result || result.success === false) {
                        throw new Error(result && (result.error || result.message) ? (result.error || result.message) : 'Generation failed');
                    }
                    if (typeof onFreeGenerationStatusChange === 'function' && result.free_generation_status) {
                        onFreeGenerationStatusChange(normalizeFreeGenerationStatus(result.free_generation_status));
                    }
                    setResultData(result);
                    const firstPreviewableArtifact = (result.artifacts || []).find((item) => {
                        const mode = getArtifactPreviewMode(item);
                        return mode === 'image' || mode === 'animation' || mode === 'video' || mode === 'json' || mode === 'html' || mode === 'stl';
                    });
                    const firstInputArtifact = (result.input_artifacts || [])[0];
                    setSelectedPreviewArtifactPath(
                        firstPreviewableArtifact
                            ? getArtifactKey(firstPreviewableArtifact)
                            : (firstInputArtifact ? firstInputArtifact.relative_path : '')
                    );
                    setStatus({
                        type: 'success',
                        message: '✅ Cover art generated successfully! Watch for live updates...'
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

                            <div className="form-group">
                                <label style={{ fontWeight: 700, marginBottom: 8, display: 'block' }}>Output File Types</label>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 16px' }}>
                                    {[
                                        { key: 'generate_svg',       label: 'SVG (lithography)',  locked: false },
                                        { key: 'generate_stl',       label: 'STL (3-D mesh)',      locked: false },
                                        { key: 'generate_html',      label: 'HTML (3-D viewer)',   locked: false },
                                        { key: 'generate_animation', label: 'Animation SVG',       locked: false },
                                        { key: '_jpg_locked',        label: 'JPG (image)',         locked: true  },
                                    ].map(({ key, label, locked }) => (
                                        <label key={key} style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: locked ? 'not-allowed' : 'pointer', opacity: locked ? 0.6 : 1 }}>
                                            <input
                                                type="checkbox"
                                                checked={locked ? true : !!formData[key]}
                                                disabled={locked}
                                                onChange={locked ? undefined : () => setFormData(prev => ({ ...prev, [key]: !prev[key] }))}
                                                style={{ width: 16, height: 16, accentColor: 'var(--accent)' }}
                                            />
                                            <span style={{ fontSize: '0.9em' }}>{label}{locked && ' ✓'}</span>
                                        </label>
                                    ))}
                                </div>
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
                                        setSelectedPreviewArtifactPath('');
                                    }}
                                >
                                    Reset
                                </button>
                            </div>
                            
                            {authenticatedUser && (
                                <div className="help-text" style={{ marginTop: '12px', textAlign: 'center', fontWeight: 600, color: freeGenerationStatus && freeGenerationStatus.can_use_free ? 'var(--ok-fg)' : 'var(--text-2)' }}>
                                    {getFreeGenerationStatusText(freeGenerationStatus)}
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
                        ) : (
                            <>
                                <h3>Result Space</h3>

                                {(() => {
                                    return (
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                                            {/* SECTION 1: TOP - Selected media preview */}
                                            <div style={{ borderBottom: '1px solid var(--line-1)', paddingBottom: '16px' }}>
                                                <div className="help-text" style={{ color: '#cdd8ea', marginBottom: '12px', fontWeight: '600' }}>
                                                    {selectedPreviewMode === 'stl' ? '🧊' : selectedPreviewMode === 'html' ? '🌐' : selectedPreviewMode === 'json' ? '📋' : selectedPreviewMode === 'animation' ? '🎬' : '🖼️'} Selected Preview
                                                </div>
                                                {renderSelectedArtifactPreview()}
                                            </div>

                                            {/* SECTION 2 - Vertical list of all generated files from current run */}
                                            <div style={{ borderBottom: '1px solid var(--line-1)', paddingBottom: '16px' }}>
                                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
                                                    <div className="help-text" style={{ color: '#cdd8ea', fontWeight: '600', margin: 0 }}>
                                                        📁 Current Run Files ({allFolderItems.length})
                                                    </div>
                                                    {allFolderItems.length > 0 && activeResultData && activeResultData.run_dir && (
                                                        <button
                                                            type="button"
                                                            className="btn-secondary"
                                                            onClick={async () => {
                                                                try {
                                                                    const downloadPath = activeResultData.run_dir || '';
                                                                    const url = `${API_BASE}/api/files/download-stack/${encodeURIComponent(downloadPath)}`;
                                                                    const response = await fetch(url);
                                                                    if (!response.ok) {
                                                                        throw new Error('Failed to download files');
                                                                    }
                                                                    const blob = await response.blob();
                                                                    const link = document.createElement('a');
                                                                    link.href = URL.createObjectURL(blob);
                                                                    link.download = `run_${(activeResultData.run_dir || '').split('/').pop() || 'artifacts'}_files.zip`;
                                                                    document.body.appendChild(link);
                                                                    link.click();
                                                                    document.body.removeChild(link);
                                                                    URL.revokeObjectURL(link.href);
                                                                } catch (error) {
                                                                    alert('Error downloading files: ' + (error && error.message ? error.message : 'Unknown error'));
                                                                }
                                                            }}
                                                            style={{ padding: '8px 16px', fontSize: '0.9em' }}
                                                        >
                                                            ⬇️ Download All
                                                        </button>
                                                    )}
                                                </div>
                                                {allFolderItems.length > 0 ? (
                                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '600px', overflowY: 'auto' }}>
                                                        {allFolderItems.map((file) => {
                                                            const artifactKey = getArtifactKey(file);
                                                            const isSelected = selectedPreviewArtifactPath === artifactKey;
                                                            const isImage = String(file.mime_type || '').startsWith('image/');
                                                            const fileExt = (String(file.name || file.relative_path || '').split('.').pop() || 'file').toUpperCase();
                                                            const fileSize = file.size_bytes ? (file.size_bytes / 1024).toFixed(1) : '0';
                                                            return (
                                                                <button
                                                                    key={artifactKey}
                                                                    type="button"
                                                                    onClick={() => setSelectedPreviewArtifactPath(artifactKey)}
                                                                    style={{
                                                                        padding: '12px',
                                                                        borderRadius: '6px',
                                                                        border: isSelected ? '2px solid var(--accent)' : '1px solid var(--border)',
                                                                        background: isSelected ? 'rgba(var(--accent-rgb), 0.1)' : 'transparent',
                                                                        cursor: 'pointer',
                                                                        textAlign: 'left',
                                                                        transition: 'all 0.2s ease',
                                                                        display: 'flex',
                                                                        alignItems: 'center',
                                                                        gap: '12px',
                                                                    }}
                                                                >
                                                                    {isImage ? (
                                                                        <img 
                                                                            src={`${API_BASE}${file.view_url}`} 
                                                                            alt={file.name || 'image'}
                                                                            style={{ width: '48px', height: '48px', borderRadius: '4px', objectFit: 'cover', flexShrink: 0 }}
                                                                        />
                                                                    ) : (
                                                                        <div style={{ width: '48px', height: '48px', borderRadius: '4px', background: '#e0e7ff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.75em', fontWeight: '600', color: '#4f51b6', flexShrink: 0 }}>
                                                                            {fileExt}
                                                                        </div>
                                                                    )}
                                                                    <div style={{ flex: 1, minWidth: 0 }}>
                                                                        <div style={{ fontSize: '0.95em', fontWeight: '500', color: isSelected ? 'var(--accent)' : '#eef4ff', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                                            {file.name || file.relative_path}
                                                                        </div>
                                                                        <div style={{ fontSize: '0.8em', color: '#aaa', marginTop: '4px' }}>
                                                                            {String(file.mime_type || 'unknown')} • {fileSize} KB
                                                                        </div>
                                                                    </div>
                                                                </button>
                                                            );
                                                        })}
                                                    </div>
                                                ) : (
                                                    <div style={{ padding: '24px', textAlign: 'center', color: '#6d7890', fontStyle: 'italic' }}>
                                                        No generated files yet. Start a run above.
                                                    </div>
                                                )}
                                            </div>
                                        </div>
                                    );
                                })()}
                            </>
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
                    const response = await apiFetch(`${API_BASE}/api/checkout`, {
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
                        if (response.status === 401) {
                            throw new Error('Session expired. Please sign in again.');
                        }
                        throw new Error(await extractErrorMessage(response, 'Payment setup failed'));
                    }
                    
                    const result = await response.json();
                    if (onAction) {
                        onAction('checkout_started');
                    }
                    const checkoutWindow = window.open(result.checkout_url, '_blank', 'noopener,noreferrer');
                    if (!checkoutWindow) {
                        throw new Error('Popup blocked. Please allow popups for this site and try again.');
                    }
                    setStatus({ type: 'success', message: '✅ Checkout opened in a new tab. Complete payment there.' });
                    setLoading(false);
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
    