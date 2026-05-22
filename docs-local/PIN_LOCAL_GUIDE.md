# Omi Pin — Local Backend Integration Guide

> **Status: COMPLETE — implementation finished.** This was a planning document. All work described here has been implemented:
> - `/v4/listen` WebSocket endpoint: `routers_local/listen.py` ✓
> - Auth bypass (`LOCAL_AUTH_BYPASS=true`): `auth/router_dep.py` ✓
> - PCM upsample (8 kHz → 16 kHz): `routers_local/listen.py` ✓
> - Desktop routing: set `OMI_PYTHON_API_URL` env var ✓
> - iOS routing: build from `.dev.env` with `API_BASE_URL=http://<ip>:8088` ✓
> - BLE pin bridge (no iOS app needed): `pin_bridge/pin_bridge.py` ✓
>
> **Important codec correction:** The Omi pin sends **Opus** audio, not `pcm8`. `pin_bridge.py` decodes Opus→PCM16 before sending `codec=linear16`. The iOS app sends raw Opus bytes with `codec=opus`, and the local `listen.py` does not decode Opus — iOS transcription produces garbage. Use `pin_bridge.py` for working transcription.
>
> **Current operator docs:**
> - **RUNBOOK.md §10** — step-by-step setup for pin bridge, Desktop app, iOS app
> - **PIN_LOCAL_AUDIO_SETUP.md** — audio path overview and known limitations
> - **pin_bridge/README.md** — pin bridge usage reference
>
> The remainder of this document is preserved as protocol reference (§8 event shapes, auth option analysis).

**Scope:** macOS Desktop app, iOS Flutter app (both connect the pin to `main_local.py` instead of the cloud backend).  
**Audience:** An LLM or developer who will implement the changes end-to-end.

---

## 1. Executive Summary

The Omi pin is a BLE wearable that streams PCM audio to a host app. The host app opens a WebSocket to the Python backend at `/v4/listen`, which transcribes the audio, extracts memories, and creates conversation records.

The local backend (`main_local.py`) currently has **no `/v4/listen` endpoint**. It only has `/v1/transcribe/stream` (simple PCM→text, no conversation lifecycle) and `/ws` (broadcast push). Both apps authenticate with **Firebase ID tokens**, but the local backend only accepts **custom JWTs**.

Three classes of work are required before end-to-end local operation works:

| # | Work | Complexity |
|---|------|------------|
| A | Add `/v4/listen` to local backend (transcribe + conversation lifecycle) | High |
| B | Add a local auth bridge that accepts Firebase tokens (or bypass auth) | Medium |
| C | Point each app at the local backend IP:port | Low |

The sections below cover all three for each app, in enough detail to implement without additional research.

---

## 2. Architecture Gap Analysis

### 2.1 What the apps expect

**Both apps** connect a WebSocket to:
```
wss://{backend_host}/v4/listen
  ?language=en
  &sample_rate=16000
  &codec=linear16        (Desktop) / pcm8 (Flutter, 8kHz from BLE)
  &channels=1
  &uid={user_id}         (Flutter only)
  &include_speech_profile=true
  &source=desktop        (Desktop) / omi (Flutter, from BLE source)
  &speaker_auto_assign=enabled
```

**Auth**: HTTP `Authorization: Bearer <firebase_id_token>` header on the WebSocket upgrade request.

**Inbound frames**: raw binary audio (PCM16 LE, no framing header).

**Outbound frames**: JSON objects, multiple event types:
```json
{ "type": "transcript_segment",
  "segments": [{ "id": "…", "text": "…", "speaker": "SPEAKER_00",
                 "is_user": true, "start": 0.0, "end": 2.5 }] }

{ "type": "new_memory_created",
  "memory": { "id": "…", "content": "…", "category": "…" } }

{ "type": "conversation_processing_started",
  "conversation_id": "…" }

{ "type": "conversation_event",
  "conversation": { "id": "…", "structured": { "title": "…", "overview": "…" } } }
```

**Conversation lifecycle**: When the WebSocket closes (or silence timeout elapses), the production backend processes the accumulated transcript into a conversation record. The local implementation must replicate this.

### 2.2 What the local backend provides today

| Endpoint | Purpose | Gap |
|----------|---------|-----|
| `POST /v1/transcribe` | Batch audio→text (REST) | No conversation, no WS |
| `WS /v1/transcribe/stream` | Streaming PCM→text | Wrong URL, wrong protocol, no conversation lifecycle |
| `WS /ws` | Broadcast push channel | Output-only, no audio input |

**Auth gap**: Local backend uses `verify_token()` from `auth/local_auth.py` which validates local JWT (`LOCAL_JWT_SECRET`). Firebase ID tokens will be rejected.

---

## 3. Required Backend Changes

### 3.1 Add a local `/v4/listen` WebSocket endpoint

**File to create**: `backend/routers_local/listen.py`

This endpoint must:
1. Accept the same query parameters as production (language, sample_rate, codec, channels, uid, include_speech_profile, source)
2. Authenticate via `Authorization` header (see §3.2 for auth options)
3. Accept raw binary audio frames
4. Transcribe audio using `faster-whisper` (already wired in `utils/stt/providers/local_streaming.py` and `local_whisper_prerecorded.py`)
5. Emit transcript segment JSON events to the client in real time
6. On WebSocket close (or after `conversation_timeout` seconds of silence), create a Conversation record in SQLite and emit `conversation_processing_started` + `conversation_event` events

**Implementation sketch:**

```python
# routers_local/listen.py
import asyncio
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from auth.local_auth import AuthError, verify_token
from database.sql import repository

router = APIRouter()
logger = logging.getLogger(__name__)


@router.websocket("/v4/listen")
async def local_listen(
    ws: WebSocket,
    language: str = "en",
    sample_rate: int = 16000,
    codec: str = "linear16",
    channels: int = 1,
    uid: Optional[str] = None,
    include_speech_profile: bool = True,
    source: Optional[str] = None,
    conversation_timeout: int = 120,
    speaker_auto_assign: str = "disabled",
):
    await ws.accept()

    # ── Auth ──────────────────────────────────────────────────────────────────
    authorization = ws.headers.get("authorization", "")
    user_id = _authenticate(authorization)
    if user_id is None:
        await ws.send_json({"error": "unauthorized"})
        await ws.close(code=1008)
        return

    # ── Session setup ─────────────────────────────────────────────────────────
    session_id = uuid.uuid4().hex
    accumulated_segments: list[dict] = []
    silence_timer: Optional[asyncio.Task] = None

    async def _emit_transcript(text: str, is_final: bool = False) -> None:
        """Send a transcript_segment event to the client."""
        seg_id = uuid.uuid4().hex
        segment = {"id": seg_id, "text": text, "speaker": "SPEAKER_00",
                   "is_user": True, "start": 0.0, "end": 0.0,
                   "words": [], "translations": []}
        accumulated_segments.append(segment)
        try:
            await ws.send_json({
                "type": "transcript_segment",
                "segments": [segment],
            })
        except Exception:
            pass

    async def _finalize_conversation() -> None:
        """Flush transcript to SQLite + Qdrant, emit conversation events."""
        if not accumulated_segments:
            return
        full_text = " ".join(s["text"] for s in accumulated_segments)
        title = full_text[:80] + ("…" if len(full_text) > 80 else "")
        conv_id = uuid.uuid4().hex
        try:
            await ws.send_json({
                "type": "conversation_processing_started",
                "conversation_id": conv_id,
            })
        except Exception:
            pass

        conv = await asyncio.to_thread(
            repository.create_conversation,
            user_id,
            title=title,
            transcript_segments=accumulated_segments,
        )

        # Optional: index in Qdrant for semantic search
        try:
            from database import vector_db_qdrant as vdb
            await asyncio.to_thread(vdb.upsert_conversation_text_vector,
                                    user_id, conv["id"], full_text)
        except Exception:
            logger.debug("Qdrant upsert failed — continuing without vector index")

        try:
            await ws.send_json({
                "type": "conversation_event",
                "event_type": "new_conversation",
                "conversation": {
                    "id": conv["id"],
                    "structured": {"title": title, "overview": full_text[:200]},
                    "transcript_segments": accumulated_segments,
                },
            })
        except Exception:
            pass

    # ── Audio streaming loop ──────────────────────────────────────────────────
    from utils.stt.providers import local_streaming

    async def _on_partial(text: str) -> None:
        await _emit_transcript(text)

    await local_streaming.start_stream(session_id, on_partial=_on_partial,
                                       sample_rate=sample_rate)
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if msg.get("bytes"):
                await local_streaming.push_audio_chunk(session_id, msg["bytes"])
    except WebSocketDisconnect:
        pass
    finally:
        final = await local_streaming.end_stream(session_id)
        if final:
            await _emit_transcript(final, is_final=True)
        await _finalize_conversation()
        try:
            await ws.close()
        except Exception:
            pass


def _authenticate(authorization: str) -> Optional[str]:
    """
    Accept either:
      - Local JWT:         'Bearer <local_jwt>'
      - Dev bypass:        'Bearer dev-<any_string>'  (local-only convenience)
    Returns user_id string or None on failure.
    """
    if not authorization.startswith("Bearer "):
        return None
    token = authorization[7:]

    # Dev bypass (local only — never enable in prod)
    if token.startswith("dev-"):
        return token[4:] or "local_dev_user"

    try:
        payload = verify_token(token)
        return payload.get("user_id") or payload.get("sub")
    except AuthError:
        return None
```

**Register in `main_local.py`** (add two lines):
```python
from routers_local import listen as local_listen_router  # add to imports
# ...
app.include_router(local_listen_router.router)           # add to router registrations
```

> **Note on `local_streaming.start_stream` signature**: The existing function at
> `utils/stt/providers/local_streaming.py` may not accept a `sample_rate` kwarg.
> Check its signature and either pass it if supported or default to 16000 Hz.
> The pin streams 8000 Hz pcm8 frames; `faster-whisper` needs 16000 Hz input.
> You may need to add 8→16 kHz upsampling (scipy `resample_poly(audio, 2, 1)`)
> or handle codec conversion before pushing chunks.

### 3.2 Auth bridge options (choose one)

The two apps always send Firebase ID tokens. The local backend has no Firebase SDK. Pick the option that best fits your constraints:

#### Option A — Dev bypass (fastest, insecure)

Modify `_authenticate()` in `listen.py` to accept any non-empty Bearer token in dev mode:

```python
import os

def _authenticate(authorization: str) -> Optional[str]:
    if not authorization.startswith("Bearer "):
        return None
    token = authorization[7:]
    if os.getenv("LOCAL_AUTH_BYPASS", "").lower() in ("1", "true"):
        # Accept Firebase tokens by treating the raw token as opaque UID source.
        # Use last 12 chars of token as a stable pseudo-UID.
        return "firebase_" + token[-12:]
    # ... normal JWT path
```

Add to `.env`:
```
LOCAL_AUTH_BYPASS=true
```

**Pros**: Zero dependencies, works immediately.  
**Cons**: No real auth — any token string works. Acceptable for LAN-only local dev.

#### Option B — Firebase Admin SDK token validation (secure)

```bash
pip install firebase-admin
```

Store your Firebase service account JSON at `backend/google-credentials.json` (already used by the production backend).

Add to `auth/local_auth.py`:
```python
import firebase_admin
from firebase_admin import auth as fb_auth, credentials

def _init_firebase():
    if not firebase_admin._apps:
        cred = credentials.Certificate("google-credentials.json")
        firebase_admin.initialize_app(cred)

def verify_firebase_token(id_token: str) -> str:
    """Returns uid or raises AuthError."""
    _init_firebase()
    try:
        decoded = fb_auth.verify_id_token(id_token)
        return decoded["uid"]
    except Exception as e:
        raise AuthError(f"Firebase token invalid: {e}") from e
```

Then in `listen.py`'s `_authenticate()`:
```python
from auth.local_auth import AuthError, verify_token, verify_firebase_token

def _authenticate(authorization: str) -> Optional[str]:
    if not authorization.startswith("Bearer "):
        return None
    token = authorization[7:]
    # Try local JWT first
    try:
        payload = verify_token(token)
        return payload.get("user_id") or payload.get("sub")
    except AuthError:
        pass
    # Fall back to Firebase token
    try:
        return verify_firebase_token(token)
    except AuthError:
        return None
```

**Pros**: Validates real Firebase tokens; same UID as the app uses.  
**Cons**: Requires internet access for Firebase token verification (first call downloads public keys; subsequent calls use cached keys).

#### Option C — Flutter/Desktop app sends local JWT instead (requires app changes)

Register/login with the local backend (`POST /v1/auth/register`, `POST /v1/auth/login`) and store the resulting JWT. Override the token fetched by `getAuthHeader()`. This is the most correct approach but requires app-side code changes (see §5.3 / §4.3).

### 3.3 `local_streaming.py` — codec compatibility

**File**: `backend/utils/stt/providers/local_streaming.py`

The Flutter app sends `codec=pcm8` (8000 Hz, signed 16-bit PCM) from the BLE device.  
The Desktop app sends `codec=linear16` (16000 Hz, signed 16-bit PCM).  
`faster-whisper` requires 16000 Hz mono float32.

Add upsampling in `local_streaming.py` if not already present:

```python
import numpy as np
try:
    from scipy.signal import resample_poly
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False


def _upsample_to_16k(raw_bytes: bytes, source_rate: int) -> np.ndarray:
    """Convert raw PCM16 LE bytes at source_rate to float32 @ 16 kHz."""
    pcm = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    if source_rate == 16000:
        return pcm
    if _HAS_SCIPY:
        factor_up = 16000 // source_rate
        return resample_poly(pcm, factor_up, 1)
    # Fallback: linear interpolation (lower quality but no dep)
    out_len = int(len(pcm) * 16000 / source_rate)
    return np.interp(np.linspace(0, len(pcm), out_len), np.arange(len(pcm)), pcm)
```

Install if needed:
```bash
conda activate omilocal
pip install scipy
```

---

## 4. macOS Desktop App Changes

### 4.1 Current State

The Desktop app (`Desktop/`) connects to the Python backend at:
- **Default**: `https://api.omi.me/`
- **Override**: env var `OMI_PYTHON_API_URL` at launch time

The `TranscriptionService.swift` builds:
```
wss://{base}/v4/listen?language=en&sample_rate=16000&codec=linear16&channels=1
  &include_speech_profile=true&source=desktop&speaker_auto_assign=enabled
```

Auth: `Authorization: Bearer <firebase_id_token>` header.

### 4.2 Redirecting to local backend (no code changes required)

Set the env var before launching `./run.sh`:

```bash
OMI_PYTHON_API_URL=http://<YOUR_SERVER_IP>:8088/ ./run.sh
```

Or add it to the `.env` file loaded by `run.sh` if that file exists (check `run.sh` for env loading).

Alternatively, export it in `~/.zshrc` or `~/.aliases` during development:
```bash
export OMI_PYTHON_API_URL=http://<YOUR_SERVER_IP>:8088/
```

> **Substitute `<YOUR_SERVER_IP>` with your local machine's LAN IP.** Check with `ipconfig getifaddr en0`.

After setting the env var, the Desktop app will send WebSocket connections to:
```
ws://<YOUR_SERVER_IP>:8088/v4/listen?...
```
with a Firebase ID token in the `Authorization` header.

### 4.3 Auth handling (Desktop)

The Desktop app will send a Firebase ID token. Use **Option A** (bypass) or **Option B** (Firebase Admin SDK) from §3.2.

If you want the Desktop to send a local JWT instead (Option C):

**File**: `Desktop/Desktop/Sources/AuthService.swift`

The `getAuthHeader()` method returns `"Bearer \(token)"` where `token` is the stored Firebase ID token. You would need to:
1. Add a `localAuthToken: String?` property to `AuthService`
2. In `getAuthHeader()`, return `"Bearer \(localAuthToken)"` if it is set
3. On app startup (after sign-in), call `POST /v1/auth/login` or `POST /v1/auth/register` on the local backend, store the returned JWT as `localAuthToken`
4. Guard this code path behind an `OMI_LOCAL_MODE` env check so it doesn't affect prod builds

This is the cleanest approach but requires careful implementation to avoid breaking production auth.

### 4.4 API calls beyond transcription (Desktop)

The Desktop app makes REST API calls (conversations, action items, goals, etc.) via `APIClient.swift`. Its `baseURL` comes from `DesktopBackendEnvironment.pythonBaseURL()`, which also reads `OMI_PYTHON_API_URL`. Setting that env var redirects ALL API calls to the local backend.

The local backend implements:
- `GET/POST /v1/conversations` ✓
- `GET /v1/conversations/{id}` ✓
- `GET/POST /v1/memories` ✓
- `GET/POST /v1/action-items` ✓

**Not yet implemented locally** (will 404 or 501):
- `GET /v1/goals` — not in `routers_local`
- `GET /v1/users/profile` — not in `routers_local`
- `GET /v2/messages` (chat history) — partially (`/v1/chat` exists, `/v2/messages` does not)
- `POST /v2/tts/synthesize` — stubs return 501
- `GET /v1/knowledge-graph` — stubs return 501

For the initial pin/transcription use case, none of the missing routes are in the critical path. The app may log 404 errors for these but will not crash.

### 4.5 Desktop validation steps

1. Start the local backend: `cd backend && bash start_local.sh` (from project root)
2. Confirm health: `curl http://<YOUR_SERVER_IP>:8088/healthz`
3. Launch Desktop with: `OMI_PYTHON_API_URL=http://<YOUR_SERVER_IP>:8088/ ./run.sh`
4. Sign in (Firebase auth still works — the Desktop auth flow calls Firebase servers, not the local backend)
5. Pair the pin via the Desktop app's pairing flow
6. Start transcription in the Desktop UI
7. Confirm in the backend terminal that a WebSocket connection is logged at `/v4/listen`
8. Speak — confirm transcript segments appear in the UI
9. Stop transcription — confirm a new conversation appears in `GET /v1/conversations`
10. Check SQLite: `sqlite3 omi_local.db "SELECT id,title FROM conversations LIMIT 10;"`

---

## 5. iOS Flutter App Changes

### 5.1 Current State

The Flutter app builds the WebSocket URL as:
```dart
String url =
    Env.apiBaseUrl!
        .replaceFirst('https://', 'wss://')
        .replaceFirst('http://', 'ws://')
    + 'v4/listen$params';
```

Where `params` includes `?language=&sample_rate=&codec=&uid=&include_speech_profile=&stt_service=&conversation_timeout=&speaker_auto_assign=enabled&vad_gate=enabled`.

`Env.apiBaseUrl` is **build-time baked** from `.dev.env` or `.prod.env` via the `envied` package. The compiled binary has the URL embedded in obfuscated form.

There is a **runtime override** mechanism:
```dart
// lib/env/env.dart
static String? _apiBaseUrlOverride;
static void overrideApiBaseUrl(String url) { _apiBaseUrlOverride = url; }
static String? get apiBaseUrl => _apiBaseUrlOverride ?? _instance.apiBaseUrl;
```

### 5.2 Redirecting to local backend (approach options)

#### Option A — Rebuild the dev flavor (cleanest)

Edit `app/.dev.env`:
```
API_BASE_URL=http://<YOUR_SERVER_IP>:8088/
```

Then regenerate and rebuild:
```bash
cd app
flutter pub run build_runner build --delete-conflicting-outputs
flutter run --flavor dev
```

This produces an app binary that points at the local backend at build time. Auth (Firebase tokens) is still sent; the local backend must accept them (use §3.2 Option A or B).

> `API_BASE_URL` must end with `/` — the code concatenates `v4/listen` directly.

#### Option B — Runtime override without rebuild

Add a hidden developer settings screen that calls `Env.overrideApiBaseUrl()`. Or, more simply, add a call in `main()` after `WidgetsFlutterBinding.ensureInitialized()`:

**File**: `app/lib/main.dart`

```dart
// At top of main():
if (const bool.fromEnvironment('USE_LOCAL_BACKEND')) {
  Env.overrideApiBaseUrl('http://<YOUR_SERVER_IP>:8088/');
}
```

Pass the flag at build time:
```bash
flutter run --flavor dev --dart-define=USE_LOCAL_BACKEND=true
```

This avoids modifying `.dev.env` and works without regenerating env files.

#### Option C — Settings screen toggle (best for ongoing dev)

Add a toggle in the developer settings screen (already exists at `lib/pages/settings/developer.dart` or similar). On toggle:
```dart
Env.overrideApiBaseUrl('http://<YOUR_SERVER_IP>:8088/');
// Reconnect WebSocket by restarting capture provider
context.read<CaptureProvider>().restartSocket();
```

### 5.3 Auth handling (Flutter)

The Flutter app fetches Firebase ID tokens from `AuthService.instance.getIdToken()` (wraps `FirebaseAuth.instance.currentUser!.getIdToken()`). These are sent as `Authorization: Bearer <firebase_token>` headers.

**For local backend:** Use §3.2 Option A (dev bypass — fastest) or Option B (Firebase Admin SDK).

If you want Option C (local JWT from app side), you need to intercept `getAuthHeader()` in `lib/backend/http/shared.dart`:

```dart
// lib/backend/http/shared.dart
Future<String> getAuthHeader() async {
  // Check if we're in local mode and have a cached local token
  if (_localJwt != null && Env.apiBaseUrl!.contains('192.168')) {
    return 'Bearer $_localJwt';
  }
  // ... existing Firebase token logic
}

String? _localJwt;

Future<void> acquireLocalJwt(String email, String password) async {
  final resp = await http.post(
    Uri.parse('${Env.apiBaseUrl}v1/auth/login'),
    headers: {'Content-Type': 'application/json'},
    body: jsonEncode({'email': email, 'password': password}),
  );
  if (resp.statusCode == 200) {
    _localJwt = jsonDecode(resp.body)['access_token'];
  }
}
```

This is fragile across the Firebase auth lifecycle and is **not recommended** unless you need real user isolation in the local DB.

### 5.4 BLE Audio Path

The pin streams Opus-encoded audio at 8000 Hz over BLE. The Flutter `CaptureProvider` captures this via `BleDeviceSource` and feeds it to `TranscriptSegmentSocketService`, which sends the raw bytes to the backend over WebSocket with `codec=pcm8&sample_rate=8000`.

The local backend's `listen.py` receives these bytes. The `local_streaming.py` STT provider must handle 8000 Hz PCM16 (upsampled to 16000 Hz for Whisper — see §3.3).

**Codec value `pcm8`**: Despite the name, this is PCM16 at 8000 Hz (the "8" refers to kHz, not bit depth). No Opus decoding is needed on the backend for this codec path — BLE codec decoding happens on the device side before bytes reach the app.

> **Verify** by checking `BleDeviceSource` in `lib/services/audio_sources/ble_device_source.dart` — confirm it sends decoded PCM bytes (not Opus frames) to the socket.

### 5.5 User ID alignment

The Flutter app includes `uid=<firebase_uid>` in the WebSocket URL. The local backend will receive this as a query parameter. The `listen.py` endpoint should use the `uid` from auth (not the query param) for database operations, since auth is the source of truth. Accept the `uid` param for logging only:

```python
@router.websocket("/v4/listen")
async def local_listen(
    ws: WebSocket,
    uid: Optional[str] = None,   # ignored — use auth-derived user_id
    ...
```

### 5.6 iOS Flutter validation steps

1. Start local backend: `omi-start`
2. Find your Mac's LAN IP: `ipconfig getifaddr en0`  
3. Edit `app/.dev.env` → set `API_BASE_URL=http://<your_ip>:8088/`
4. Rebuild: `flutter pub run build_runner build --delete-conflicting-outputs`
5. Run the dev flavor on a physical device: `flutter run --flavor dev -d <device_id>`  
   (Local HTTP requires device on the same WiFi network as the Mac running the backend)
6. Sign in to the app (Firebase auth — works fine, it calls Firebase servers directly)
7. Pair the pin
8. Start recording — check backend logs for a WebSocket connection at `/v4/listen`
9. Speak — confirm transcript segments appear in the app UI
10. Stop recording — confirm conversation created: `curl -H "Authorization: Bearer <token>" http://<ip>:8088/v1/conversations`
11. Restore `.dev.env` to original value when done

> **HTTPS/HTTP caveat**: iOS blocks plain `http://` connections by default via App Transport Security (ATS). You must either:
> - Use `https://` with a real certificate (e.g. via ngrok or a local cert), OR
> - Add an ATS exception for your local IP in `ios/Runner/Info.plist`:
>   ```xml
>   <key>NSAppTransportSecurity</key>
>   <dict>
>     <key>NSExceptionDomains</key>
>     <dict>
>       <key><YOUR_SERVER_IP></key>
>       <dict>
>         <key>NSExceptionAllowsInsecureHTTPLoads</key>
>         <true/>
>       </dict>
>     </dict>
>   </dict>
>   ```
>   Replace with your actual local IP.

---

## 6. Summary of All File Changes

### Backend (`backend/`)

| File | Change | Required |
|------|--------|----------|
| `routers_local/listen.py` | **CREATE** — `/v4/listen` WebSocket endpoint | Yes |
| `main_local.py` | Import and register `listen.py` router | Yes |
| `auth/local_auth.py` | Add `verify_firebase_token()` (Option B auth) | If using Option B |
| `utils/stt/providers/local_streaming.py` | Add `sample_rate` param + upsampling | If pin sends 8 kHz |
| `.env` | Add `LOCAL_AUTH_BYPASS=true` (Option A) | If using Option A |
| `requirements.txt` | Add `firebase-admin` (Option B) or `scipy` (upsampling) | Optional |

### Desktop (`Desktop/`)

| File | Change | Required |
|------|--------|----------|
| None | Set `OMI_PYTHON_API_URL=http://<ip>:8088/` env var at launch | Yes |
| `Desktop/Sources/AuthService.swift` | Add local JWT path (Option C auth) | Optional |

### Flutter (`app/`)

| File | Change | Required |
|------|--------|----------|
| `.dev.env` | Set `API_BASE_URL=http://<ip>:8088/` | Yes (Option A rebuild) |
| OR `lib/main.dart` | Add `--dart-define` override call | Yes (Option B runtime) |
| `ios/Runner/Info.plist` | Add ATS exception for local IP | Yes (iOS only) |
| `lib/backend/http/shared.dart` | Add `_localJwt` path | Optional (Option C auth) |

---

## 7. Implementation Order

Execute in this order to reach a working state with minimum wasted effort:

1. **Backend: implement `routers_local/listen.py`** with Option A auth bypass (fastest path to test)
2. **Backend: register the router in `main_local.py`** and restart the backend
3. **Desktop: test first** (easiest — just set `OMI_PYTHON_API_URL` and launch)
4. **Validate end-to-end Desktop flow** (pin pairing → transcription → conversation in SQLite)
5. **Backend: add upsampling** if Flutter 8 kHz audio produces garbled transcripts
6. **Flutter: update `.dev.env`** and rebuild
7. **Flutter: add iOS ATS exception** if connections are refused on device
8. **Validate end-to-end Flutter flow** (pin pairing → transcription → conversation)
9. **Replace Option A auth bypass with Option B** (Firebase Admin SDK) if real user isolation is needed

---

## 8. Appendix: `/v4/listen` Event Reference

These are the exact event shapes the Flutter `CaptureProvider` and Desktop `AppState` parse. The local implementation must emit these JSON structures.

### 8.1 Transcript segment
```json
{
  "type": "transcript_segment",
  "segments": [
    {
      "id": "<uuid>",
      "text": "hello world",
      "speaker": "SPEAKER_00",
      "speaker_id": 0,
      "is_user": true,
      "person_id": null,
      "start": 0.0,
      "end": 2.5,
      "words": [],
      "translations": []
    }
  ]
}
```

### 8.2 Conversation processing started
```json
{
  "type": "conversation_processing_started",
  "conversation_id": "<uuid>"
}
```

### 8.3 Conversation event (new conversation)
```json
{
  "type": "conversation_event",
  "event_type": "new_conversation",
  "conversation": {
    "id": "<uuid>",
    "structured": {
      "title": "Meeting about X",
      "overview": "We discussed...",
      "action_items": [],
      "category": "other"
    },
    "transcript_segments": [...],
    "started_at": "2026-05-06T12:00:00Z",
    "finished_at": "2026-05-06T12:05:00Z",
    "source": "omi"
  }
}
```

### 8.4 Memory created
```json
{
  "type": "new_memory_created",
  "memory": {
    "id": "<uuid>",
    "content": "User prefers concise answers",
    "category": "preference",
    "created_at": "2026-05-06T12:00:00Z"
  }
}
```

> The local backend can omit memory extraction initially — the Flutter app handles missing `new_memory_created` events gracefully (no crash). The Desktop app also handles this event optionally.

### 8.5 Error / status events
```json
{ "type": "error", "message": "transcription failed" }
{ "type": "ping" }
```

---

## 9. Known Limitations of Local Mode

| Limitation | Impact |
|-----------|--------|
| No speaker diarization (no pyannote) | All segments labeled `SPEAKER_00` |
| No memory extraction (no Ollama LLM call wired to listen) | No auto-memories from conversations |
| No push notifications | Conversation processing events only via WebSocket |
| No speech profile / speaker ID | `include_speech_profile=true` is accepted but ignored |
| No VAD gating | All audio forwarded to Whisper regardless of silence |
| Single-segment Whisper output | Segments lack precise `start`/`end` timestamps |

These are acceptable for local development and personal use. They can be addressed incrementally:
- **Memory extraction**: after `_finalize_conversation()`, call `Env.llm_client.generate()` with the transcript and a memory-extraction prompt
- **VAD gating**: add WebRTC VAD or silero-vad to filter silent chunks before Whisper
- **Speaker diarization**: run pyannote locally (requires ~1 GB model + GPU or slow CPU)
