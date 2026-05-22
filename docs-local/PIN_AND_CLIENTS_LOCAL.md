# Omi Pin + Clients → Local Backend

How to "flash" the Omi pin so it talks to the custom local backend, and the integration story for the iOS / Flutter app and the macOS desktop app — with **local-only operation as the non-negotiable constraint**.

---

## TL;DR (read this first)

**The Omi pin does not have a configurable backend URL.** It is a Bluetooth Low Energy peripheral. It captures audio with a PDM mic, encodes it with Opus, and broadcasts it over BLE. It has no Wi-Fi radio, no IP stack, no DNS, no HTTP client, no concept of "backend." Repointing it at a different backend therefore is **not a firmware change** — it is a *companion-app* change. You flash firmware only to:

- update audio / battery / storage / haptics behavior on the device itself,
- change BLE service or characteristic UUIDs (rarely necessary),
- enable/disable on-device features (offline storage, T5838 AAD, monitor build, etc.).

The **flow** the pin participates in is:

```
[Omi pin]  ──BLE Opus audio──►  [Phone or Mac running a "host" client]  ──HTTPS/WS──►  [Backend]
```

So "flash the pin to point at the local backend" really means three pieces of work, in this order:

1. **(Optional)** Build and OTA-flash the latest pin firmware so its BLE behavior matches what the host apps expect. The firmware itself never talks to the backend.
2. **Repoint the host client** (mobile app or desktop app) to `http://<your-mac-ip>:8088` instead of `https://api.omi.me`.
3. **Cope with the cloud-only features** the host apps assume on top of the API URL (Firebase auth, Pusher, ElevenLabs, Stripe, OAuth integrations, agent-proxy WebSocket, etc.). For local-only operation either gate those off in the client, or accept reduced functionality.

The rest of this document is how to do each piece carefully, what works out-of-the-box, what does not, and what's the minimum-effort path to "I press the pin button, my Mac records audio, transcribes locally with Whisper, embeds locally, indexes to Qdrant, and answers in Ollama."

---

## 1. Hardware / firmware reality check

### 1.1 What the pin actually is

- SoC: **Nordic nRF5340** (dual-core Cortex-M33, no Wi-Fi).
- RTOS: **Zephyr** built with **nRF Connect SDK 2.9.0**.
- Bootloader: **MCUboot** with dual-bank slots; OTA over BLE via MCUmgr/SMP.
- Bluetooth-only connectivity. There is no IP stack compiled in, by design.
- Source: `omi/firmware/omi/` (production board) and `omi/firmware/devkit/` (dev kits).
- High-level architecture and OTA process: `omi/firmware/BUILD_AND_OTA_FLASH.md`.

What lives in `omi/firmware/omi/src/`:
```
main.c                      — boot sequence, LED/haptic/IMU/mic/codec/transport plumbing
mic.c                       — PDM microphone capture
codec.c (in lib/core/)      — Opus encode of mic frames
transport.c (in lib/core/)  — BLE GATT services that stream Opus + battery + button events
sd_card.c, spi_flash.c      — offline storage
nfc.c                       — emits an NDEF URI ( https://friend.based.com/pair?id=<deviceid> ) for tap-to-pair
mcuboot_boot_zephyr.c       — boot into MCUmgr update mode via button combo
```

The only string in the entire firmware that looks like a URL is in `nfc.c`. It is a *pairing deep-link* surfaced over NFC — it tells a phone to open the app and hand it the device ID; nothing in the firmware itself ever resolves that URL. You can leave it alone.

> **Therefore: do not waste time chasing a "set my backend URL" build flag in firmware. There isn't one and there shouldn't be.**

### 1.2 What "flashing the pin" actually accomplishes for local-only

You only need to flash the pin if any of these are true:

- You bought the device and it shipped with stale firmware that the current host app refuses to talk to.
- You want to enable/disable offline SD-card storage (`CONFIG_OMI_ENABLE_OFFLINE_STORAGE`).
- You want to change BLE GATT UUIDs to namespace your device away from production firmware.
- You want serial-console debug output (DevKit only).
- You're modifying audio framing, button behavior, or battery thresholds.

If none of those apply: **skip the flash entirely.** A stock pin already speaks the same BLE protocol the local-mode host clients will use, because the protocol is what the firmware defines, not what the backend expects.

---

## 2. (Optional) Building and flashing the firmware

This section is only relevant if §1.2 says you need it. The full canonical procedure is in `omi/firmware/BUILD_AND_OTA_FLASH.md`; what follows is the local-only abridged version.

### 2.1 Toolchain prerequisites (macOS)

```bash
# nrfutil — Nordic's CLI
brew install nrfutil

# nRF Connect SDK 2.9.0 + GNU Arm Embedded toolchain
nrfutil install toolchain-manager
nrfutil toolchain-manager install --ncs-version v2.9.0

# Build deps
brew install ninja ccache cmake

# (For wired flashing, optional) J-Link tools
brew install --cask segger-jlink

# (For OTA, recommended) nRF Connect for Mobile on your phone
#   iOS:     https://apps.apple.com/app/nrf-connect-for-mobile/id1054362403
#   Android: https://play.google.com/store/apps/details?id=no.nordicsemi.android.mcp
```

### 2.2 Workspace init

```bash
cd omi/firmware   # from project root
mkdir -p v2.9.0 && cd v2.9.0
nrfutil toolchain-manager launch --ncs-version v2.9.0 --shell
# inside the nRF shell:
west init -m https://github.com/nrfconnect/sdk-nrf --mr v2.9.0
west update
exit
```

### 2.3 Build

Pin (production) build, no SD-card, BLE OTA enabled — the configuration the local-mode host apps are designed for:

```bash
cd omi/firmware   # from project root
nrfutil toolchain-manager launch --ncs-version v2.9.0 --shell

# inside the nRF shell:
cd omi
west build -b omi_v2 -p auto    # 'omi_v2' or whatever board preset matches your hardware
exit
```

Build artifacts land in `omi/build/` — the OTA-relevant one is `omi/build/zephyr/app_update.bin` (or `dfu_application.zip` for the MCUboot SMP DFU path). Wired-flash artifacts are `merged.hex` and `zephyr.hex`.

> If you want offline SD-card storage on, edit `omi/firmware/omi/omi.conf` and set `CONFIG_OMI_ENABLE_OFFLINE_STORAGE=y` before building. This is orthogonal to backend choice — the SD card just buffers Opus frames whenever BLE isn't connected; later, when a host app reconnects, the firmware streams the buffered file. Local-only operation handles this fine because the buffered audio is consumed by the local host app, not uploaded to the cloud.

### 2.4 Flash — wired (DevKit only)

```bash
nrfutil toolchain-manager launch --ncs-version v2.9.0 --shell
cd omi/firmware/devkit
west flash --erase
# or, if west flash can't find the runner:
nrfjprog --program build/zephyr/merged.hex --chiperase --reset --verify
```

### 2.5 Flash — OTA over BLE (production pin)

The production pin has no exposed SWD pins; OTA is the supported path. Use **nRF Connect for Mobile** on your phone:

1. Power on the pin and put it in DFU mode (the firmware advertises an MCUmgr SMP service whenever it's not paired with the official app — the exact button combo for your board is in `BUILD_AND_OTA_FLASH.md`).
2. Open nRF Connect for Mobile → Scanner → connect to the pin (advertised name typically `OmiDevkit*` or `Omi*`).
3. In the device view, open the **DFU** option.
4. Select `dfu_application.zip` from the build (transfer it to your phone via AirDrop / cloud / USB).
5. Hit **Start**. The pin reboots into MCUboot, swaps slots, and comes back up on the new firmware.

Verification: pair the pin with the local host app (§3) and confirm Opus audio streams.

### 2.6 What the flash does **not** change

- It does **not** make the pin "know about" the local backend. The pin is a peripheral; it has no idea where its audio ends up.
- It does **not** alter Wi-Fi, hostnames, certificate trust, or HTTP client settings — none of those exist on the device.
- It does **not** require any change to the local backend you're running.

**Conclusion: rebuild the firmware only when the firmware itself needs a behavior change.** "Repoint the device at a custom backend" is not such a change.

---

## 3. Repointing the host clients at the local backend

This is the part that *actually* makes the pin's audio land in your local Whisper + Ollama + Qdrant stack. There are two host options.

### 3.1 Option A — Flutter mobile app (`app/`)

The Flutter app is the canonical pin host: it scans for BLE, pairs, receives Opus, and pushes to the backend.

**Status of integration with the local-only backend:** ⚠️ **Partial — non-trivial changes required.**

The app talks to the backend via two URLs:

| URL | Source | Local-mode replacement |
|-----|--------|------------------------|
| HTTP API base | `Env.apiBaseUrl` (from `app/.env` `API_BASE_URL`) — overridable at runtime via `Env.overrideApiBaseUrl()` | `http://<mac-ip>:8088` |
| WebSocket (agent proxy + transcribe) | `Env.agentProxyWsUrl` — derived from `apiBaseUrl` by replacing `api.` with `agent.` (`wss://agent.omi.me/v1/agent/ws`); also overridable via `Env.overrideAgentProxyWsUrl()` | `ws://<mac-ip>:8088/ws` and `ws://<mac-ip>:8088/v1/transcribe/stream` |

The app **also** assumes:

- **Firebase Authentication** for login (Google/Apple OAuth + ID-token bearer). Our local backend rejects Firebase tokens — `auth.local_auth` issues plain HS256 JWTs. The app's auth layer will need to be redirected at `POST /v1/auth/login` and stop sending Firebase tokens. This is the single biggest integration cost.
- **Hosted Pusher** (`HOSTED_PUSHER_API_URL` on the backend) for realtime event fan-out. The local backend uses native FastAPI WebSockets (`/ws`); the app will need a small client adapter that subscribes to the WS and decodes the same payload schema Pusher events used.
- **Stripe / subscription gates** (`omi+`, `omi+ unlimited`). The app silently disables features when `users.subscription` is missing. This is fine in local mode — it just means certain paid features stay greyed out — but the code paths that *check* the subscription must not crash on the local user record's empty `extra` JSON.
- **Hosted ElevenLabs TTS / OpenAI TTS / Hume** for voice replies and emotion. These will simply be unavailable in local-only mode unless you bolt on a local TTS like Piper.
- **OAuth integrations** (Whoop, Notion, Google, Apple, Twitter): all dead-on-arrival in local mode. Disable in the UI.

**Minimum-viable repointing procedure (rough but works):**

```bash
cd app   # from project root

# 1. Configure the env file the build picks up.
cp .env.template .env
# edit .env:
#   API_BASE_URL=http://192.168.x.y:8088
#   POSTHOG_API_KEY=
#   GOOGLE_MAPS_API_KEY=
#   USE_WEB_AUTH=false
#   USE_AUTH_CUSTOM_TOKEN=true   # important — disables Firebase ID-token path
#   STAGING_API_URL=

# 2. Build for iOS or Android pointing at the local IP.
bash setup.sh ios       # one-time
flutter run --dart-define=API_BASE_URL=http://192.168.x.y:8088
```

> **Important:** the phone and the Mac must be on the same Wi-Fi/LAN. Use your Mac's LAN IP (`ipconfig getifaddr en0`), not `127.0.0.1` — `localhost` on the phone resolves to the phone itself, not your Mac.

**What you must change in the app source for true local-only operation:**

1. `app/lib/services/auth/` (or wherever the Firebase ID token is fetched): replace the `getIdToken()` call with a tiny client that calls `POST /v1/auth/register` once, then `POST /v1/auth/login`, stores the returned JWT, and uses it as the bearer token for every subsequent request. The change is a few hundred lines and is mostly mechanical.
2. The conversation/transcribe pipeline: replace the legacy upload endpoint(s) with `POST /v1/transcribe` (multipart) for prerecorded chunks, and `WS /v1/transcribe/stream` for streaming sessions (start with a JWT message, then stream raw PCM16 frames, then a `"END"` text message).
3. The realtime layer: replace the Pusher channel subscription with a single `WebSocket(ws://<mac>:8088/ws?token=$JWT)` connection; route incoming JSON envelopes to the same dispatcher that previously consumed Pusher events.
4. Subscription/billing/payment flows: gate them so a missing subscription does not crash; show a single "Local mode — paid features unavailable" banner.
5. Apps marketplace, OAuth integrations, Twilio phone calls, Hume emotion: hide entirely or stub returning empty lists.

**Rough effort:** 1–2 weeks of focused Flutter work to get pin → BLE → app → local backend → transcript visible in the conversations tab. Add another week for chat-with-LLM and memory search.

> **Reality check:** the Flutter app is roughly 200k lines of Dart. The local backend exposes only the six routers in `routers_local/`. Most of the app's features have no counterpart locally. A pragmatic local-only build should aim for: pair → record → transcribe → save conversation → search memories → chat. That subset is achievable. Full feature parity with the cloud build is not the goal.

### 3.2 Option B — macOS desktop app (`desktop/`)

**Status:** ⚠️ **Worse fit than mobile, because the desktop app does not pair with the pin over BLE — it relies on the Mac's microphone or screen audio capture.** Unless you've added BLE pairing yourself, the desktop app is an orthogonal product to the pin.

If you only care about audio captured on the Mac (without using the pin), the desktop app is the simpler local target:

- Two URLs to redirect, both in `desktop/Backend-Rust/.env` (also reads `~/.omi.env` and `desktop/.env`):

  ```bash
  # Desktop's *own* Rust backend — the helper that does VM provisioning, Crisp,
  # config fetch. Not strictly required in local mode; you can leave it pointing
  # at a stub or run the Rust backend locally on :10201.
  OMI_DESKTOP_API_URL=http://localhost:10201

  # The Python backend — this is what you redirect at main_local.
  OMI_PYTHON_API_URL=http://127.0.0.1:8088
  ```

- Same caveats as mobile re: Firebase auth, Pusher, ElevenLabs, agent proxy, subscription gating. The desktop also calls a Gemini agent over WebSocket for the "Proactive Assistants" feature; that needs its own local model or it must be disabled.

- Auth path in `desktop/Desktop/Sources/AuthService.swift`: currently uses Firebase web auth + custom-token sign-in. Redirect to your local register/login JSON endpoints similar to the mobile section.

**If you don't strictly need the desktop app, skip it.** It is more deeply coupled to the cloud than mobile.

### 3.3 Option C — BLE pin bridge (`pin_bridge.py`) — **implemented, recommended**

The leanest local-only setup skips both first-party apps and uses the BLE bridge that already exists in `pin_bridge/`. This is **built and working today**.

```bash
cd pin_bridge   # from project root
conda activate omilocal
pip install bleak opuslib websockets   # one-time
python pin_bridge.py --token "$TOKEN"
```

`pin_bridge.py`:
- Scans for the pin via CoreBluetooth (`bleak`)
- Subscribes to the audio GATT characteristic
- Reassembles multi-chunk BLE packets with `FrameAssembler`
- Decodes Opus → PCM16 via `opuslib`
- Streams PCM to `ws://127.0.0.1:8088/v4/listen?codec=linear16&sample_rate=16000`
- Automatically drains the pin's SD card on connect via `pin_offline_drain.py`

Strengths:
- No client repointing or client patching needed.
- 100% local, 100% inspectable.
- No Firebase, no Stripe, no Pusher, no agent-proxy.
- SD card drain happens automatically (no separate command).

Weaknesses:
- No polished UI — conversations appear in the admin panel at `/admin/` instead.

**For "I want it working today, locally": use this path.** See `pin_bridge/README.md` and RUNBOOK §10.1 for full setup.

> **iOS codec note:** The iOS app (§3.1) sends raw Opus bytes with `codec=opus`. The local `listen.py` only handles PCM. iOS transcription produces garbage or empty results. `pin_bridge.py` is the only path that correctly decodes Opus before sending to Whisper.

---

## 4. Decision matrix

| Goal | Use |
|------|-----|
| Local-only, today, pin → transcript → search → chat | **§3.3 (`pin_bridge.py`) — built, works today** |
| Pin + polished mobile UI, local-only, willing to fork the app | §3.1 (Flutter, with auth/pusher/subscription patches — note iOS Opus gap) |
| Mac mic only, no pin, polished desktop UI, willing to fork | §3.2 (desktop, with similar patches) |
| Want offline SD drain from pin when it was away from BLE | `pin_bridge.py` — handles this automatically on reconnect |
| Want iOS WAL sync (phone buffered audio, off-network) | Implemented: `POST /v2/sync-local-files` in `routers_local/sync.py` |
| Want offline storage on the pin so disconnects don't lose audio | Build firmware with `CONFIG_OMI_ENABLE_OFFLINE_STORAGE=y` (§2) — stock pin already works |
| Want to debug what the pin is sending | DevKit board, build with `CONFIG_LOG=y` etc. (see firmware README), then nRF Serial Terminal in VS Code |
| Want OTA from the desktop instead of the phone | Use `mcumgr` CLI over a USB BLE dongle on the Mac with `mcumgr image upload`, but the official path is nRF Connect for Mobile |

---

## 5. End-to-end checklist for a fresh local-only deploy with the pin

> Pre-condition: `main_local` is running and healthy on the Mac at `http://127.0.0.1:8088` (see `RUNBOOK.md` and `SETUP_FROM_SCRATCH.md`).

1. **Flash firmware?** Only if §1.2 says yes. Otherwise skip — the stock firmware is fine.
2. **Pick a host** (§3): bridge script (§3.3) for fastest, mobile (§3.1) for full UX, desktop (§3.2) only if you don't need the pin.
3. **Get a JWT from the local backend:**
   ```bash
   curl -sS -X POST http://127.0.0.1:8088/v1/auth/register \
     -H 'Content-Type: application/json' \
     -d '{"email":"you@omi.dev","password":"hunter2"}'
   curl -sS -X POST http://127.0.0.1:8088/v1/auth/login \
     -H 'Content-Type: application/json' \
     -d '{"email":"you@omi.dev","password":"hunter2"}'
   ```
4. **Configure the host with that JWT and base URL.**
5. **Pair the pin** (BLE-side) with whatever host you chose. Confirm Opus packets are arriving. (Mobile: pin shows up in the app's device list. Bridge: the script logs received packet counts.)
6. **Verify the local stack:** speak into the pin, then check that:
   - the WebSocket transcribe session emits `partial` updates and a final transcript,
   - `GET /v1/conversations` shows a new conversation (if the host writes one),
   - a memory you create gets indexed in Qdrant (`POST /v1/memories/search` returns it),
   - `POST /v1/chat` responds via Ollama.

If all five of those work, you have a fully local pin → transcript → memory → LLM → chat loop.

---

## 6. What "local-only" *cannot* be guaranteed for, and why

Even with the strictest setup, the following can leak to the network unless you actively disable them — list them up-front so you can audit:

- **OTA flashing via nRF Connect for Mobile** is local-only **after** you have the `dfu_application.zip` on your phone, but downloading the nRF Connect app itself goes through the App Store. There is no way around that.
- **Phone DNS / NTP / push** unrelated to Omi will still be active on the phone, regardless of what the Omi app does. If you need a true RF-isolated environment, run the host on a separate device.
- **The first-party Flutter app, even rebuilt, links Firebase Analytics, Crashlytics, and Sentry SDKs.** They make network calls at startup unless you remove them from `pubspec.yaml` or stub them out. To be local-only you must rip those out.
- **`utils.observability` (LangSmith) and `utils.subscription` (Stripe price IDs) are imported at startup of the cloud `main.py`.** You sidestep this by running `main_local` (which does not import them). Don't accidentally `uvicorn main:app` instead of `uvicorn main_local:app` or you lose the local-only guarantee.
- **The desktop app will try `OMI_PYTHON_API_URL=https://api.omi.me` if you forget to set it.** Set the env *before* launching `desktop/run.sh`, and verify with Charles/Wireshark on first boot.
- **`https://friend.based.com/pair?id=…` NDEF URI** in firmware — it is only emitted if NFC is read by a phone. Nothing makes a request unless someone scans the pin with NFC.

---

## 7. Files mentioned

- `omi/firmware/BUILD_AND_OTA_FLASH.md` — canonical build/flash steps.
- `omi/firmware/readme.md` — firmware overview.
- `omi/firmware/omi/src/lib/core/transport.h` — BLE GATT service definitions (audio + battery + button).
- `omi/firmware/omi/src/main.c` — boot sequence; entry to all subsystems.
- `omi/firmware/omi/src/lib/core/nfc.c` — the only URL-shaped string in the firmware (NFC pairing URI; safe to ignore for local-only).
- `app/lib/env/env.dart` — Flutter `apiBaseUrl` + `agentProxyWsUrl` overrides.
- `app/.env.template` — Flutter env template.
- `desktop/.env.example` — desktop env template (`OMI_PYTHON_API_URL`).
- `backend/main_local.py` — local-only API the host clients should point at.
- `backend/routers_local/` — the six endpoints local hosts use (auth, chat, conversations, memories, transcribe, ws).

---

## 8. Final recommendation

If your goal is "I have an Omi pin and I want it working entirely locally":

1. **Do not rebuild the firmware unless you have a specific behavior change in mind.** The pin already does the right thing.
2. **Run `main_local` as documented in `RUNBOOK.md` / `SETUP_FROM_SCRATCH.md`.**
3. **Use `pin_bridge.py` (§3.3) as your host.** It exists at `pin_bridge/`, is fully implemented, decodes Opus→PCM, and drains the SD card automatically. See `pin_bridge/README.md` and RUNBOOK §10.1.
4. **Do not rely on the iOS app for transcription.** The iOS app sends raw Opus over WebSocket but the local backend only handles PCM — transcripts will be empty. The iOS app is still useful for WAL sync (audio buffered when off-network syncs via `POST /v2/sync-local-files`).
5. **Defer forking the Flutter or desktop apps until you need the UI.** Once `pin_bridge.py` is working end-to-end, you have a known-good reference for the JWT shape and WebSocket protocol.
