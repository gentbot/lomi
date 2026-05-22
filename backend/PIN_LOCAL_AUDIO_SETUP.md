# Pin Local Audio Setup

**Goal:** Every byte of audio captured by the Omi pin is processed entirely on your own machines. No audio ever reaches Deepgram, OpenAI, any Google service, or any other outside server.

---

## How audio actually travels from the pin

The pin does not have its own WiFi connection for live audio. It uses Bluetooth Low Energy (BLE) to send audio to a phone or desktop. There are two supported paths to get that audio into the local backend.

### Path 1 — BLE pin bridge (recommended, no iOS app needed)

```
Pin (BLE) → pin_bridge.py → WebSocket → Python backend → faster-whisper (local STT)
```

`pin_bridge.py` in `code/pin_bridge/` connects directly to the pin via macOS CoreBluetooth, decodes the Opus audio to PCM, and streams it to the backend's `/v4/listen` WebSocket. This is the **fully working path today** and requires no iOS app or Xcode build. See `code/pin_bridge/README.md` and RUNBOOK §10.1 for setup.

### Path 2 — iOS app (secondary, has a transcription limitation)

```
Pin (BLE) → iOS app → WebSocket → Python backend → faster-whisper (local STT)
```

The iOS app reads BLE audio frames from the pin and forwards them to the backend's WebSocket. **However, the iOS app sends raw Opus bytes and the local `listen.py` only handles PCM.** The WebSocket connection succeeds and audio arrives at the backend, but Whisper receives undecoded Opus and produces garbage or empty transcripts. The iOS path is documented in RUNBOOK §10.3 but **is not suitable for transcription until Opus decoding is added to `listen.py`**.

The iOS app is still useful for the WebSocket connection itself (pairing, session management, UI), and for offline WAL sync when the phone can't reach the backend (see "Offline audio" below).

The pin's BLE audio is Opus-encoded at 16 kHz. `pin_bridge.py` decodes it to PCM16-LE before sending `codec=linear16`, which Whisper can process correctly.

### Offline audio — SD card and WAL

When the pin has no BLE connection, it records audio to its SD card (up to ~480 MB). When `pin_bridge.py` reconnects over BLE, it automatically drains the SD card and injects the stored audio into the live transcription stream (no separate action needed).

When the iOS app is connected to the pin but the phone cannot reach the backend (e.g. off-network), the app buffers audio as `.bin` WAL files on the phone. On reconnect, the app uploads them to `POST /v2/sync-local-files` (implemented). The sync endpoint decodes Opus and creates a conversation record.

The WiFi feature on the pin is separate — it is not involved in normal live audio streaming.

---

## What touches the network during normal operation

| Action | Goes to |
|---|---|
| Sign in to the iOS app | Google Firebase (authentication only, not audio) |
| BLE audio from pin to phone | Stays on Bluetooth, never on any network |
| WebSocket audio stream | Goes to whatever `API_BASE_URL` is set to |
| STT processing | The backend's configured STT provider |
| LLM processing of transcript | The backend's configured LLM provider |

If `API_BASE_URL` points at your backend machine and the backend uses local STT and LLM, then audio never leaves your LAN after it leaves the pin.

The Firebase sign-in does touch Google's servers. This is a one-time authentication handshake that produces a token. The token is sent along with the WebSocket connection. The local backend has an auth bypass mode that accepts Firebase tokens without re-validating them against Firebase, so after the initial sign-in the backend does not contact Firebase again.

---

## What you need to configure

### 1. Backend `.env` on the backend machine

These settings must be in `omi/backend/.env` (relative to your project root):

```env
AUTH_PROVIDER=local
DB_PROVIDER=sqlite
STT_PROVIDER=local
LLM_PROVIDER=ollama
EMBEDDINGS_PROVIDER=local
VECTOR_DB_PROVIDER=qdrant
EVENT_PROVIDER=websocket
ENABLE_DIARIZATION=false
LOCAL_AUTH_BYPASS=true
```

**What each one does:**

- `AUTH_PROVIDER=local` — uses local JWT tokens for API endpoints
- `DB_PROVIDER=sqlite` — stores conversations, memories, and users in SQLite on disk
- `STT_PROVIDER=local` — uses faster-whisper running on this machine to transcribe audio
- `LLM_PROVIDER=ollama` — uses Ollama running on this machine for AI processing
- `EMBEDDINGS_PROVIDER=local` — uses sentence-transformers on this machine for semantic search
- `VECTOR_DB_PROVIDER=qdrant` — stores embedding vectors in Qdrant running on this machine
- `EVENT_PROVIDER=websocket` — handles real-time events without the Pusher cloud service
- `ENABLE_DIARIZATION=false` — turns off speaker identification, which requires a cloud GPU service that has no local replacement
- `LOCAL_AUTH_BYPASS=true` — allows the iOS app's Firebase-issued token to be accepted by the local backend without the backend contacting Firebase to validate it

**Additional settings for Whisper (faster-whisper):**

```env
LOCAL_WHISPER_MODEL=base
LOCAL_WHISPER_DEVICE=cpu
LOCAL_WHISPER_COMPUTE_TYPE=int8
```

`base` is a reasonable starting model. It is accurate enough for clear speech and runs on CPU without requiring a GPU. If transcription is too slow, try `tiny`. If accuracy is insufficient, try `small`. Larger models require more memory and time.

`cpu` works on any machine. If your machine has a supported GPU you can use `cuda` (Nvidia) or `mps` (Apple Silicon). If you use `mps` or `cuda`, change `int8` to `float16`.

**Ollama settings:**

```env
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3.1
```

Ollama must be installed and running on the backend machine separately. You can verify it is running by opening `http://localhost:11434` in a browser — you should see a plain text response. If Ollama is not running, audio will still be transcribed but the conversation will not be processed by an LLM.

**Qdrant settings:**

```env
QDRANT_URL=http://localhost:6333
```

Qdrant must be running separately. The simplest way to run it is with Docker:

```
docker run -p 6333:6333 qdrant/qdrant
```

If Qdrant is not running, transcription still works but semantic search over conversations will not function.

### 2. Restart the backend

After changing `.env`, stop the server and start it again:

```
conda activate omilocal
uvicorn main_local:app --reload --host 0.0.0.0 --port 8088
```

The `--host 0.0.0.0` flag is required so the server accepts connections from other machines on the network, not just from localhost.

You can confirm the backend is running with the correct settings by opening `http://<YOUR_SERVER_IP>:8088/healthz` in a browser. The response will show which provider is active for each service. It should show:

```json
{
  "ok": true,
  "local_mode": true,
  "providers": {
    "llm": "ollama",
    "stt": "local",
    "embeddings": "local",
    "vector_db": "qdrant",
    "auth": "local",
    "db": "sqlite",
    "events": "websocket",
    "diarization": false
  }
}
```

If any provider shows a cloud value like `openai` or `deepgram`, that setting is not taking effect. Double-check the `.env` file and restart.

### 3. Use pin_bridge.py (no iOS app needed — recommended)

**This step replaces the iOS app requirement.** If you want transcription working today, use `pin_bridge.py` instead:

```bash
cd ~/Documents/codebase/OMI/code/pin_bridge
conda activate omilocal
pip install bleak opuslib websockets   # one-time
python pin_bridge.py --token "$TOKEN"
```

See `code/pin_bridge/README.md` and RUNBOOK §10.1 for the full walkthrough including Bluetooth permission setup, scanning, and offline drain.

### 3b. Build the iOS app from source (optional — transcription has a limitation)

> **Note:** The iOS app connects to the local backend but does not produce working transcripts because it sends raw Opus audio and the local `listen.py` only handles PCM. Use `pin_bridge.py` (above) for transcription. The iOS app path is still useful if you want the Omi app UI, for WAL sync, or for testing purposes.

The iOS app has the backend URL compiled into it at build time. The stock app from the App Store points at `https://api.omi.me` and cannot be changed. You must build your own copy with the local URL.

**Requirements on the build machine:**

- macOS
- Xcode (install from the Mac App Store)
- Flutter SDK (install from flutter.dev)
- The repository cloned locally

**Steps:**

1. Go to `omi/app/` in the repository
2. Create the file `omi/app/.dev.env` with the following content:

```env
API_BASE_URL=http://<YOUR_SERVER_IP>:8088
STAGING_API_URL=http://<YOUR_SERVER_IP>:8088
USE_WEB_AUTH=false
USE_AUTH_CUSTOM_TOKEN=true
```

Leave all other fields blank. You do not need an OpenAI key, Google Maps key, or PostHog key. Features that depend on those will not function, but the WebSocket connection will open and offline WAL sync will work.

3. Run the build setup:

```
cd omi/app
bash setup.sh ios
```

This installs Flutter dependencies and generates the code that reads the `.dev.env` values into the app binary.

4. Connect your iPhone to the Mac with a USB cable.

5. Open Xcode. Open the file `omi/app/ios/Runner.xcworkspace` (not `Runner.xcodeproj`).

6. In Xcode, select your connected iPhone as the build target in the device selector at the top of the window.

7. Press the Run button (triangle) or press `Cmd + R`. Xcode will build the app and install it on your phone.

8. The first time you run a self-built app, iOS will ask you to trust the developer certificate. On your iPhone, go to Settings → General → VPN & Device Management → find your Apple ID → tap Trust.

**Expected outcome:** The app installs on your phone. When you open it you will see the normal Omi sign-in screen. Audio will flow to the backend but transcripts will be empty or garbled — this is the known Opus codec limitation.

---

## Connecting the pin — pin_bridge path (recommended)

1. Make sure the backend is running and LAN-accessible:
   ```bash
   curl http://<YOUR_SERVER_IP>:8088/healthz
   ```

2. Register a local account and log in (one-time):
   ```bash
   curl -sS -X POST http://127.0.0.1:8088/v1/auth/register \
     -H 'Content-Type: application/json' \
     -d '{"email":"pin@omi.dev","password":"hunter2"}'
   export TOKEN=$(curl -sS -X POST http://127.0.0.1:8088/v1/auth/login \
     -H 'Content-Type: application/json' \
     -d '{"email":"pin@omi.dev","password":"hunter2"}' \
     | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
   ```

3. Run the bridge:
   ```bash
   cd ~/Documents/codebase/OMI/code/pin_bridge
   conda activate omilocal
   python pin_bridge.py --token "$TOKEN"
   ```

4. The bridge scans for the pin, connects over BLE, and opens the WebSocket. A haptic buzz on the pin confirms connection. Speak into the pin — partials appear in the terminal within 5–10 seconds.

5. Press `Ctrl-C` to stop. The backend logs the conversation ID and the conversation appears in the admin UI at `http://<YOUR_SERVER_IP>:8088/admin`.

See RUNBOOK §10.1 for detailed troubleshooting, Bluetooth permission setup, and offline SD drain details.

## Connecting the pin — iOS app path (secondary, transcription limited)

If you have built the iOS app (§3b above):

1. Open the app on your iPhone. Sign in via Firebase/Google (one-time auth step).

2. The app will show a pairing screen. Hold the pin near the iPhone and pair it.

3. Once paired (pin LED solid blue), start recording. The app opens a WebSocket to `ws://<YOUR_SERVER_IP>:8088/v4/listen`. Audio arrives at the backend but **transcription will not produce meaningful output** due to the Opus codec limitation.

4. The iOS app is useful for WAL sync: if the phone was off-network while recording, reconnecting syncs the buffered audio through `POST /v2/sync-local-files`.

---

## Verifying nothing is leaving your network

On the backend machine, run:

```
sudo lsof -i -n -P | grep ESTABLISHED | grep -v "127.0.0.1\|192.168.50"
```

While audio is actively being transcribed, this command shows all established network connections. Any connection that is not to localhost (`127.0.0.1`) or your local network (`192.168.50.x`) is going somewhere outside. If the backend is correctly configured with local providers, no audio-related connections to external addresses should appear during a transcription session.

---

## What still touches the internet

Being specific about what cannot be made local:

- **iOS sign-in** — signing in to the app uses Firebase/Google authentication. This is a network call to Google. The audio itself is not involved and does not go to Google. If you are already signed in on your phone, this call only happens on first launch or after the token expires (roughly every hour).
- **Ollama model download** — the first time you use a model, Ollama downloads it from the internet. After that, the model is stored locally and Ollama does not make network calls during inference.
- **faster-whisper model download** — the first time the backend starts with `STT_PROVIDER=local`, it downloads the Whisper model weights from Hugging Face. After that first download, the model is cached locally.

After those one-time downloads are complete, no audio and no transcripts leave your network during normal operation.

---

## What does not work in this setup

- **iOS app transcription** — the iOS app sends raw Opus audio; `listen.py` only handles PCM. Transcripts are garbage. Use `pin_bridge.py` instead.
- **Speaker identification (diarization)** — turned off (`ENABLE_DIARIZATION=false`). The transcript will not label who said what.
- **Google Maps integration** — no key provided, feature is disabled.
- **PostHog analytics** — no key provided, no analytics data is sent.
- **Stripe payments** — not applicable in local mode.
- **ElevenLabs TTS** — no key provided, voice responses are disabled.
- **Perplexity web search in RAG** — no key provided, the LLM cannot search the web during chat.
- **Automatic memory extraction** — conversations are saved but the post-session LLM memory extraction pipeline does not run automatically. Call `POST /v1/chat` with the transcript to extract manually.

The core function — capturing audio, transcribing it, and storing the conversation — works today via `pin_bridge.py`.
