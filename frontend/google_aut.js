(function (global) {
  "use strict";

  // Use compat bundles because this file relies on the global firebase namespace.
  var FIREBASE_SCRIPT_SRC = "https://www.gstatic.com/firebasejs/10.7.0/firebase-app-compat.js";
  var FIREBASE_AUTH_SCRIPT_SRC = "https://www.gstatic.com/firebasejs/10.7.0/firebase-auth-compat.js";

  var firebaseScriptPromise = null;
  var firebaseAuthScriptPromise = null;

  var config = {
    endpoint: "/auth-user",
    onAuthSuccess: null,
    onAuthError: null
  };

  function loadScripts() {
    return Promise.all([loadFirebaseScript(), loadFirebaseAuthScript()]);
  }

  function loadFirebaseScript() {
    if (global.firebase && global.firebase.app) {
      return Promise.resolve();
    }

    if (firebaseScriptPromise) {
      return firebaseScriptPromise;
    }

    firebaseScriptPromise = new Promise(function (resolve, reject) {
      var script = document.createElement("script");
      script.src = FIREBASE_SCRIPT_SRC;
      script.async = true;
      script.defer = true;
      script.onload = function () {
        resolve();
      };
      script.onerror = function () {
        reject(new Error("Firebase app script could not be loaded."));
      };
      document.head.appendChild(script);
    });

    return firebaseScriptPromise;
  }

  function loadFirebaseAuthScript() {
    if (global.firebase && global.firebase.auth) {
      return Promise.resolve();
    }

    if (firebaseAuthScriptPromise) {
      return firebaseAuthScriptPromise;
    }

    firebaseAuthScriptPromise = new Promise(function (resolve, reject) {
      var script = document.createElement("script");
      script.src = FIREBASE_AUTH_SCRIPT_SRC;
      script.async = true;
      script.defer = true;
      script.onload = function () {
        resolve();
      };
      script.onerror = function () {
        reject(new Error("Firebase auth script could not be loaded."));
      };
      document.head.appendChild(script);
    });

    return firebaseAuthScriptPromise;
  }

  function extractUserData(firebaseUser) {
    if (!firebaseUser) {
      return null;
    }

    return {
      uid: firebaseUser.uid,
      email: firebaseUser.email,
      displayName: firebaseUser.displayName,
      photoURL: firebaseUser.photoURL,
      emailVerified: firebaseUser.emailVerified,
      phoneNumber: firebaseUser.phoneNumber,
      metadata: {
        creationTime: firebaseUser.metadata.creationTime,
        lastSignInTime: firebaseUser.metadata.lastSignInTime
      }
    };
  }

  async function postUserToBackend(userData) {
    if (!userData) {
      return null;
    }

    var response = await fetch(config.endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ user: userData })
    });

    if (!response.ok) {
      throw new Error("Failed to send authenticated user to server.");
    }

    var contentType = response.headers.get("content-type") || "";
    if (contentType.indexOf("application/json") !== -1) {
      return response.json();
    }

    return response.text();
  }

  async function initializeGoogleAuth(options) {
    var opts = options || {};

    config.endpoint = opts.endpoint || config.endpoint;
    config.onAuthSuccess = opts.onAuthSuccess || null;
    config.onAuthError = opts.onAuthError || null;

    // Use global firebaseConfig from firebase-config.js
    if (!global.firebaseConfig) {
      throw new Error("Firebase configuration not found. Ensure firebase-config.js is loaded.");
    }

    await loadScripts();

    var app = global.firebase.apps && global.firebase.apps.length
      ? global.firebase.app()
      : global.firebase.initializeApp(global.firebaseConfig);
    global.auth = global.firebase.auth(app);

    global.auth.onAuthStateChanged(async function (user) {
      if (user) {
        var userData = extractUserData(user);
        try {
          await postUserToBackend(userData);
          if (typeof config.onAuthSuccess === "function") {
            config.onAuthSuccess(userData);
          }
        } catch (error) {
          if (typeof config.onAuthError === "function") {
            config.onAuthError(error);
          }
        }
      }
    });
  }

  async function signInWithGoogle() {
    if (!global.firebase || !global.auth) {
      throw new Error("Firebase is not initialized.");
    }

    try {
      var provider = new global.firebase.auth.GoogleAuthProvider();
      var result = await global.auth.signInWithPopup(provider);

      var userData = extractUserData(result.user);
      await postUserToBackend(userData);

      if (typeof config.onAuthSuccess === "function") {
        config.onAuthSuccess(userData);
      }

      return userData;
    } catch (error) {
      if (typeof config.onAuthError === "function") {
        config.onAuthError(error);
      }
      throw error;
    }
  }

  async function signOut() {
    if (!global.auth) {
      throw new Error("Firebase is not initialized.");
    }

    try {
      await global.auth.signOut();
    } catch (error) {
      if (typeof config.onAuthError === "function") {
        config.onAuthError(error);
      }
      throw error;
    }
  }

  global.GoogleAuth = {
    initializeGoogleAuth: initializeGoogleAuth,
    signInWithGoogle: signInWithGoogle,
    signOut: signOut,
    postAuthenticatedUser: postUserToBackend
  };
})(window);
