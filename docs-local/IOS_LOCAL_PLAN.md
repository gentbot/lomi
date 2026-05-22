# iOS App — Local Backend Integration Plan

How to make the Omi iOS Flutter app point at the local Python backend, with local
email/password auth, while keeping all local-only code separated from the upstream
project so rebasing remains easy.

---

## Guiding principles

| Principle | Implementation |
|-----------|----------------|
| No hardcoded IPs | `API_BASE_URL` comes from `.dev.env`; IP comes from `LOCAL_MACHINE_HOST` |
| Single source of truth | `desktop/.env.app` holds `LOCAL_MACHINE_HOST`; a sync script propagates it to `app/.dev.env` |
| Upstream separation | All local-only code lives in `lib/local/`; upstream files get minimal hooks only |
| Additive over in-place | New files in new directories never conflict; edits to tracked files are small and clearly marked |

---

## Current state (what already exists)

- `app/.dev.env` already sets `API_BASE_URL=http://<YOUR_SERVER_IP>:8088` — the IP is in a file, but it is not derived from `LOCAL_MACHINE_HOST` and is not documented as a template
- `lib/env/env.dart` already has `Env.overrideApiBaseUrl()` — a runtime override hook, useful for local mode
- Firebase auth is the only sign-in path; no email/password option exists anywhere in the app
- `Info.plist` has no ATS exception — HTTP to any non-localhost IP is blocked by default
- `LOCAL_AUTH_BYPASS=true` in the backend accepts Firebase tokens, so existing Firebase sign-in already works once ATS and URL are fixed

---

## Phase 1 — URL from `.env` + single-source IP

**Goal:** `LOCAL_MACHINE_HOST` in `desktop/.env.app` is the one place the LAN IP lives.
Changing it propagates to every component automatically.

### 1.1 Create `app/.dev.env.example` (tracked in git)

Document every variable the dev build uses:

```ini
# ── LOCAL ONLY — copy to .dev.env and fill in real values ──
# .dev.env is gitignored. This file is the tracked reference.

# Backend URL — set to http://<LOCAL_MACHINE_HOST>:8088
API_BASE_URL=http://localhost:8088

# Staging URL (optional; used by TestFlight builds to hit a different server)
STAGING_API_URL=

# Auth mode
USE_WEB_AUTH=false          # false = native Apple/Google sign-in
USE_AUTH_CUSTOM_TOKEN=true  # true = backend returns Firebase custom token

# Local email/password auth (Phase 3)
LOCAL_AUTH_ENABLED=true

# Optional API keys (leave blank to use backend-proxied values)
OPENAI_API_KEY=
GOOGLE_MAPS_API_KEY=
POSTHOG_API_KEY=
```

### 1.2 Create `scripts/sync-local-ip.sh` (new file, tracked)

A single command to propagate `LOCAL_MACHINE_HOST` from `desktop/.env.app` into
`app/.dev.env` so you never update the IP in two places manually:

```bash
#!/usr/bin/env bash
# sync-local-ip.sh — copy LOCAL_MACHINE_HOST from desktop/.env.app into app/.dev.env
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP_ENV="$REPO_ROOT/desktop/.env.app"
APP_ENV="$REPO_ROOT/app/.dev.env"

if [ ! -f "$DESKTOP_ENV" ]; then
    echo "ERROR: $DESKTOP_ENV not found. Run run-local.sh setup first."
    exit 1
fi

HOST=$(grep "^LOCAL_MACHINE_HOST=" "$DESKTOP_ENV" | head -1 | cut -d= -f2- | tr -d '[:space:]')
HOST="${HOST:-localhost}"

echo "Syncing LOCAL_MACHINE_HOST=$HOST → API_BASE_URL in $APP_ENV"

if [ ! -f "$APP_ENV" ]; then
    cp "$REPO_ROOT/app/.dev.env.example" "$APP_ENV"
fi

if grep -q "^API_BASE_URL=" "$APP_ENV"; then
    sed -i '' "s|^API_BASE_URL=.*|API_BASE_URL=http://$HOST:8088|" "$APP_ENV"
else
    echo "API_BASE_URL=http://$HOST:8088" >> "$APP_ENV"
fi

echo "Done. API_BASE_URL=http://$HOST:8088"
```

Run after any IP change:
```bash
bash scripts/sync-local-ip.sh
flutter pub run build_runner build --delete-conflicting-outputs
```

### 1.3 Verify envied regeneration

After editing `.dev.env`, envied must regenerate `lib/env/dev_env.g.dart`:

```bash
cd app
flutter pub get
flutter pub run build_runner build --delete-conflicting-outputs
```

The generated file bakes `API_BASE_URL` into the compiled binary. Every `.dev.env` change
requires this step — there is no way around it with the current envied setup.

**Files changed:** `app/.dev.env.example` (new), `scripts/sync-local-ip.sh` (new)
**Upstream files touched:** none

---

## Phase 2 — App Transport Security (ATS)

**Goal:** iOS must allow plain HTTP to the LAN IP without hardcoding that IP anywhere.

### Problem

iOS ATS blocks all non-HTTPS connections to non-localhost hosts by default. The RUNBOOK
currently instructs adding a `NSExceptionDomains` entry with the hardcoded IP — that is
the wrong approach (IP changes break it, and it's in a tracked file).

### Solution: `NSAllowsLocalNetworking`

iOS 14+ supports a blanket ATS exception for local-network destinations (link-local,
LAN RFC-1918 addresses). It does not require the IP to be named explicitly:

```xml
<key>NSAppTransportSecurity</key>
<dict>
    <key>NSAllowsLocalNetworking</key>
    <true/>
</dict>
```

This covers any `http://192.168.x.x/`, `http://10.x.x.x/`, `http://172.16-31.x.x/`, and
`http://localhost/` — all without naming a specific IP.

### 2.1 Add ATS entry to `app/ios/Runner/Info.plist`

Find the closing `</dict>` before `</plist>` at the end of the file and insert:

```xml
	<key>NSAppTransportSecurity</key>
	<dict>
		<key>NSAllowsLocalNetworking</key>
		<true/>
	</dict>
```

This is a small, clearly-motivated change to a tracked upstream file. It does not
specify an IP, so it never needs to change when `LOCAL_MACHINE_HOST` changes.

**Upstream conflict risk:** LOW. Upstream rarely modifies the ATS section.
**Upstream note:** `NSAllowsLocalNetworking` is safe to ship; it only affects
local-network IPs, not the public internet.

### 2.2 Update RUNBOOK

- Remove the old "hardcode IP in Info.plist" instructions from §10.3 Steps 4-5
- Replace with a note that ATS is already handled by `NSAllowsLocalNetworking`

**Files changed:** `app/ios/Runner/Info.plist` (one new key/value block)

---

## Phase 3 — Local email/password authentication

**Goal:** A user can sign in with an email address and password against the local
backend's `/v1/auth/login` endpoint, getting a JWT that the app sends as the bearer
token on every API request. No Firebase involved.

This mirrors the desktop app's auth flow exactly.

### Architecture

```
lib/local/                          ← new directory; git-tracked but clearly local-only
  auth/
    local_auth_service.dart         ← HTTP calls to /v1/auth/login and /v1/auth/register
    local_auth_storage.dart         ← JWT persistence in SharedPreferences
  pages/
    local_sign_in_page.dart         ← email/password sign-in UI
    local_register_page.dart        ← first-account registration UI
  local_mode.dart                   ← single bool: is local mode active?
```

Minimal hooks into upstream files:

| File | Change |
|------|--------|
| `lib/env/dev_env.dart` | Add one `@EnviedField` for `LOCAL_AUTH_ENABLED` |
| `lib/env/env.dart` | Expose `Env.localAuthEnabled` getter |
| `lib/backend/http/shared.dart` | `getAuthHeader()` checks local JWT first |
| `lib/pages/onboarding/auth.dart` | Add "Sign in with email" button when `localAuthEnabled` |

### 3.1 `lib/local/local_mode.dart`

```dart
// ── LOCAL ONLY — no upstream equivalent ──
import '../env/env.dart';

bool get isLocalMode => Env.localAuthEnabled;
```

### 3.2 `lib/local/auth/local_auth_storage.dart`

```dart
// ── LOCAL ONLY — no upstream equivalent ──
import 'package:shared_preferences/shared_preferences.dart';

const _kToken = 'local_jwt_token';
const _kExpiry = 'local_jwt_expiry';

class LocalAuthStorage {
  static Future<void> save(String token, DateTime expiry) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_kToken, token);
    await prefs.setInt(_kExpiry, expiry.millisecondsSinceEpoch);
  }

  static Future<String?> getToken() async {
    final prefs = await SharedPreferences.getInstance();
    final expiry = prefs.getInt(_kExpiry);
    if (expiry == null) return null;
    if (DateTime.now().millisecondsSinceEpoch > expiry) {
      await clear();
      return null;
    }
    return prefs.getString(_kToken);
  }

  static Future<void> clear() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_kToken);
    await prefs.remove(_kExpiry);
  }

  static Future<bool> isSignedIn() async => (await getToken()) != null;
}
```

### 3.3 `lib/local/auth/local_auth_service.dart`

```dart
// ── LOCAL ONLY — no upstream equivalent ──
import 'dart:convert';
import 'package:http/http.dart' as http;
import '../../env/env.dart';
import 'local_auth_storage.dart';

class LocalAuthResult {
  final bool success;
  final String? error;
  const LocalAuthResult({required this.success, this.error});
}

class LocalAuthService {
  static String get _base => Env.apiBaseUrl.endsWith('/')
      ? Env.apiBaseUrl.substring(0, Env.apiBaseUrl.length - 1)
      : Env.apiBaseUrl;

  static Future<LocalAuthResult> signIn(String email, String password) async {
    try {
      final resp = await http.post(
        Uri.parse('$_base/v1/auth/login'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'email': email, 'password': password}),
      );
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body) as Map<String, dynamic>;
        final token = data['access_token'] as String?;
        if (token == null) return const LocalAuthResult(success: false, error: 'No token in response');
        // TTL from backend is LOCAL_JWT_TTL_SECONDS; default 30 days
        final expiry = DateTime.now().add(const Duration(days: 30));
        await LocalAuthStorage.save(token, expiry);
        return const LocalAuthResult(success: true);
      }
      final body = jsonDecode(resp.body);
      return LocalAuthResult(success: false, error: body['detail'] ?? 'Login failed');
    } catch (e) {
      return LocalAuthResult(success: false, error: e.toString());
    }
  }

  static Future<LocalAuthResult> register(String email, String password) async {
    try {
      final resp = await http.post(
        Uri.parse('$_base/v1/auth/register'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({'email': email, 'password': password}),
      );
      if (resp.statusCode == 200 || resp.statusCode == 201) {
        return signIn(email, password); // auto sign-in after register
      }
      final body = jsonDecode(resp.body);
      return LocalAuthResult(success: false, error: body['detail'] ?? 'Registration failed');
    } catch (e) {
      return LocalAuthResult(success: false, error: e.toString());
    }
  }

  static Future<void> signOut() => LocalAuthStorage.clear();
}
```

### 3.4 `lib/local/pages/local_sign_in_page.dart`

Full email/password sign-in screen that mirrors the desktop Admin UI pattern:

```dart
// ── LOCAL ONLY — no upstream equivalent ──
import 'package:flutter/material.dart';
import '../auth/local_auth_service.dart';

class LocalSignInPage extends StatefulWidget {
  final VoidCallback onSignedIn;
  const LocalSignInPage({super.key, required this.onSignedIn});

  @override
  State<LocalSignInPage> createState() => _LocalSignInPageState();
}

class _LocalSignInPageState extends State<LocalSignInPage> {
  final _emailCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  bool _loading = false;
  String? _error;
  bool _showRegister = false;

  Future<void> _submit() async {
    setState(() { _loading = true; _error = null; });
    final result = _showRegister
        ? await LocalAuthService.register(_emailCtrl.text.trim(), _passCtrl.text)
        : await LocalAuthService.signIn(_emailCtrl.text.trim(), _passCtrl.text);
    if (!mounted) return;
    if (result.success) {
      widget.onSignedIn();
    } else {
      setState(() { _loading = false; _error = result.error; });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 32, vertical: 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const SizedBox(height: 60),
              const Text('Omi · Local', style: TextStyle(color: Colors.white, fontSize: 28, fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              Text(_showRegister ? 'Create account' : 'Sign in',
                  style: const TextStyle(color: Colors.white54, fontSize: 16)),
              const SizedBox(height: 40),
              TextField(
                controller: _emailCtrl,
                keyboardType: TextInputType.emailAddress,
                autocorrect: false,
                style: const TextStyle(color: Colors.white),
                decoration: _inputDecoration('Email'),
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _passCtrl,
                obscureText: true,
                style: const TextStyle(color: Colors.white),
                decoration: _inputDecoration('Password'),
                onSubmitted: (_) => _submit(),
              ),
              if (_error != null) ...[
                const SizedBox(height: 12),
                Text(_error!, style: const TextStyle(color: Colors.redAccent, fontSize: 13)),
              ],
              const SizedBox(height: 24),
              ElevatedButton(
                onPressed: _loading ? null : _submit,
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.white,
                  foregroundColor: Colors.black,
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                ),
                child: _loading
                    ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2))
                    : Text(_showRegister ? 'Create account' : 'Sign in', fontSize: 16, fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 16),
              TextButton(
                onPressed: () => setState(() { _showRegister = !_showRegister; _error = null; }),
                child: Text(
                  _showRegister ? 'Already have an account? Sign in' : 'No account? Register',
                  style: const TextStyle(color: Colors.white54),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  InputDecoration _inputDecoration(String label) => InputDecoration(
    labelText: label,
    labelStyle: const TextStyle(color: Colors.white54),
    enabledBorder: const OutlineInputBorder(borderSide: BorderSide(color: Colors.white24)),
    focusedBorder: const OutlineInputBorder(borderSide: BorderSide(color: Colors.white)),
    filled: true,
    fillColor: Colors.white10,
  );

  @override
  void dispose() {
    _emailCtrl.dispose();
    _passCtrl.dispose();
    super.dispose();
  }
}
```

### 3.5 Add `LOCAL_AUTH_ENABLED` to env system

**`lib/env/dev_env.dart`** — add one field inside the `DevEnv` class:
```dart
@EnviedField(varName: 'LOCAL_AUTH_ENABLED', defaultValue: false)
static final bool localAuthEnabled = _DevEnv.localAuthEnabled;
```

**`lib/env/env.dart`** — add one getter:
```dart
static bool get localAuthEnabled => _instance?.localAuthEnabled ?? false;
```

**`.dev.env`** — ensure the line exists:
```
LOCAL_AUTH_ENABLED=true
```

### 3.6 Wire local JWT into `getAuthHeader()`

**`lib/backend/http/shared.dart`** — at the top of `getAuthHeader()`, add a local-JWT
check before the Firebase path. This is the one meaningful change to an upstream file:

```dart
import '../../../local/auth/local_auth_storage.dart';  // LOCAL ONLY import

Future<Map<String, String>> getAuthHeader() async {
  // ── LOCAL ONLY — check for local JWT before Firebase ──
  if (Env.localAuthEnabled) {
    final localToken = await LocalAuthStorage.getToken();
    if (localToken != null) {
      return {'Authorization': 'Bearer $localToken'};
    }
  }
  // ── existing Firebase path unchanged below ──
  ...
```

The comment makes it easy to find and remove if merging upstream.

### 3.7 Add email sign-in entry point to the sign-in page

**`lib/pages/onboarding/auth.dart`** — add a third button below Google/Apple when
`Env.localAuthEnabled` is true. This is a small, conditional addition to an upstream file:

```dart
// ── LOCAL ONLY — shown only when LOCAL_AUTH_ENABLED=true ──
if (Env.localAuthEnabled) ...[
  const SizedBox(height: 12),
  OutlinedButton(
    onPressed: () => Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => LocalSignInPage(onSignedIn: widget.onSignIn),
      ),
    ),
    style: OutlinedButton.styleFrom(
      side: const BorderSide(color: Colors.white24),
      padding: const EdgeInsets.symmetric(vertical: 14),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
    ),
    child: const Text('Sign in with email (local)', style: TextStyle(color: Colors.white70)),
  ),
],
```

Place it after the Google button block, before the privacy links section.

### 3.8 Sign-out: clear local token

When the app signs out, clear the local JWT. In `lib/providers/auth_provider.dart`, find
the existing `signOut()` method and add one line:

```dart
// ── LOCAL ONLY ──
if (Env.localAuthEnabled) await LocalAuthStorage.clear();
```

### 3.9 Startup check: restore local session

In `lib/main.dart`, after `Env.init()`, add a check so a locally signed-in user does not
have to log in again on app restart:

```dart
// ── LOCAL ONLY ──
if (Env.localAuthEnabled) {
  final localToken = await LocalAuthStorage.getToken();
  if (localToken != null) {
    // Token is valid — skip Firebase sign-in flow
    // The app will use the local JWT for all requests
  }
}
```

The exact integration point depends on how routing works in `main.dart` — this is a
note to trace the `isSignedIn` check and guard it similarly to the Firebase case.

**Files changed (new):**
- `lib/local/local_mode.dart`
- `lib/local/auth/local_auth_service.dart`
- `lib/local/auth/local_auth_storage.dart`
- `lib/local/pages/local_sign_in_page.dart`

**Files changed (minimal hooks in upstream files):**
- `lib/env/dev_env.dart` — one `@EnviedField` line
- `lib/env/env.dart` — one getter
- `lib/backend/http/shared.dart` — ~5 lines at top of `getAuthHeader()`
- `lib/pages/onboarding/auth.dart` — one conditional button block
- `lib/providers/auth_provider.dart` — one `await LocalAuthStorage.clear()` in sign-out

---

## Phase 4 — Backend endpoint audit

**Goal:** Identify which endpoints the iOS app calls that are not yet implemented in
`main_local.py`, and add stubs or full implementations.

### Known-working endpoints (verified in `main_local.py`)

| Endpoint | Router file |
|----------|-------------|
| `POST /v1/auth/login` | `routers_local/auth.py` |
| `POST /v1/auth/register` | `routers_local/auth.py` |
| `GET /v1/auth/me` | `routers_local/auth.py` |
| `GET /v1/conversations` | `routers_local/memories.py` |
| `POST /v1/conversations` | via `/v4/listen` close |
| `GET /v1/memories` | `routers_local/memories.py` |
| `POST /v1/memories` | `routers_local/memories.py` |
| `POST /v1/memories/search` | `routers_local/memories.py` |
| `POST /v1/chat` | `routers_local/listen.py` |
| `WS /v4/listen` | `routers_local/listen.py` |
| `POST /v2/sync-local-files` | `routers_local/sync.py` |
| `GET /healthz` | `main_local.py` |

### Likely-missing endpoints (audit needed)

These are called by the iOS app based on the API layer in `lib/backend/http/api/`:

| Endpoint | Purpose | Action |
|----------|---------|--------|
| `GET /v1/config/api-keys` | App fetches Firebase API key at runtime | Add stub returning empty object or known keys |
| `GET /v1/apps` | Apps marketplace listing | Return empty list `[]` |
| `GET /v1/users/profile` | User profile fetch | Add or confirm exists |
| `POST /v1/action_items` | Action item creation | Confirm in `routers_local/action_items.py` |
| `GET /v1/action_items` | Action item list | Confirm |
| `POST /v1/transcribe` | One-shot audio file transcription | Confirm |
| `GET /v1/notifications/settings` | Push notification prefs | Return stub |

### Audit process

Run the app against the local backend with network logging enabled, collect all 404s,
and add stubs. All new endpoints go in the appropriate `routers_local/` file. If a
feature is genuinely not supported locally (push notifications, apps marketplace),
return HTTP 200 with an empty response that the app handles gracefully.

**Files changed:** `backend/routers_local/*.py` (additions only, no upstream conflict)

---

## Phase 5 — Build and run end-to-end

### 5.1 Full build sequence

```bash
# 1. Update IP if it changed
bash scripts/sync-local-ip.sh

# 2. Regenerate envied constants
cd app
flutter pub run build_runner build --delete-conflicting-outputs

# 3. Start the backend
cd backend
conda activate omilocal && bash start_local.sh

# 4. Build and deploy to device
cd app
flutter run --flavor dev -d <device-id>
```

### 5.2 Verify connectivity

After sign-in, watch the backend terminal for:
```
INFO:     192.168.x.x:xxxxx - "GET /v1/auth/me HTTP/1.1" 200
INFO:     192.168.x.x:xxxxx - "GET /v1/conversations HTTP/1.1" 200
INFO:     192.168.x.x:xxxxx - "GET /v1/memories HTTP/1.1" 200
```

### 5.3 Verify local JWT auth path

Sign in with email/password. Then:
```bash
sqlite3 backend/omi_local.db \   # run from project root
  "SELECT email FROM users ORDER BY created_at DESC LIMIT 3;"
```
The signed-in account should appear.

---

## Phase summary

| Phase | What it delivers | Upstream files touched | New local files |
|-------|-----------------|----------------------|-----------------|
| 1 — URL from .env | IP in one place, sync script | none | `.dev.env.example`, `scripts/sync-local-ip.sh` |
| 2 — ATS | HTTP to LAN works without hardcoded IP | `ios/Runner/Info.plist` (1 block) | none |
| 3 — Local auth | Email/password sign-in and JWT flow | 5 files, ~5–10 lines each | 4 new files in `lib/local/` |
| 4 — Endpoint audit | App doesn't 404 on missing routes | none | additions to `routers_local/` |
| 5 — Build and run | End-to-end test | none | none |

Phases 1 and 2 are prerequisites — nothing works without URL routing and HTTP access.
Phase 3 can be done before or after Phase 4; they are independent.

---

## Files that must NOT be modified (upstream risk)

| File | Why |
|------|-----|
| `lib/firebase_options_dev.dart` | Firebase credentials — upstream owns this |
| `lib/firebase_options_prod.dart` | Firebase credentials — upstream owns this |
| `ios/Config/Prod/GoogleService-Info.plist` | Prod Firebase config |
| `ios/Config/Dev/GoogleService-Info.plist` | Dev Firebase config |
| `android/app/src/prod/google-services.json` | Prod Android Firebase |
| `pubspec.yaml` | Only add deps here if absolutely needed; conflicts are hard |

---

## Tracking what was changed

Every modification to an upstream file should include a comment:

```dart
// ── LOCAL ONLY — remove this block when merging upstream ──
```

Every new local-only file should include at the top:

```dart
// ── LOCAL ONLY — this file has no upstream equivalent ──
```

This mirrors the convention used in the backend (`routers_local/`, `database/sql/`, etc.)
and makes it trivial to audit what needs attention during an upstream rebase.
