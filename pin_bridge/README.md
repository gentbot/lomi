# pin_bridge — Omi pin → local backend (BLE bridge)

A small, dependency-light Python program that pairs with an Omi pin over
Bluetooth Low Energy, decodes the audio it streams, and pushes the audio into
the local-only backend (`main_local`) for transcription. **No cloud, no
official app required.**

```
[Omi pin]  ──BLE Opus 16kHz mono──►  pin_bridge.py  ──WS PCM16──►  main_local on this Mac
                                          │
                                          └─► local Whisper, Qdrant, Ollama, SQLite
```

This is the recommended first integration path described in
`code/PIN_AND_CLIENTS_LOCAL.md` §3.3.

---

## What it does, exactly

1. Scans for a BLE peripheral whose name starts with `Omi` (override with
   `--device-name` or `--address`).
2. Connects, optionally reads the audio-format characteristic
   (`19B10002-…`) for sanity, then subscribes to GATT notifications on the
   audio-data characteristic (`19B10001-…`).
3. Reassembles the firmware's 3-byte BLE framing (`packet_id_lo, packet_id_hi,
   sub_index`) into complete Opus frames.
4. Decodes each Opus frame to PCM16 mono at 16 kHz (320 samples = 20 ms).
5. Connects to `ws://127.0.0.1:8088/v4/listen` with an `Authorization: Bearer
   <jwt>` header, then streams binary PCM frames live.
6. Logs `transcript_segment` partial events as Whisper produces them.
7. On Ctrl-C, closes the WebSocket cleanly — the backend creates and persists
   the conversation to SQLite + Qdrant and emits a `conversation_event`.

Use `--legacy-endpoint` to use the old `/v1/transcribe/stream` path (first-frame
JWT auth, no conversation lifecycle).

All identifiers and audio parameters are read straight from the firmware
source (`omi/omi/firmware/omi/src/lib/core/transport.c` and `config.h`).

---

## Prerequisites

- macOS (Apple Silicon or Intel) with Bluetooth on.
- Python 3.11 — the same `omilocal` conda env you already created for the
  backend (see `code/SETUP_FROM_SCRATCH.md`).
- `main_local` running on `http://127.0.0.1:8088` (see `RUNBOOK.md`).
- The Omi pin powered on and not currently paired with another host (the
  official Flutter app, another bridge instance, etc.).
- Homebrew Opus library:
  ```bash
  brew install opus
  ```
  `opuslib` (Python) is a thin ctypes wrapper around the system library; it
  fails at import time without it.

### Bluetooth permission on macOS

The first time you run a Python script that uses CoreBluetooth, macOS will
prompt to authorize "Terminal" (or whatever app is hosting your shell —
iTerm, VS Code, etc.) for Bluetooth access. Approve the prompt. If you missed
it: *System Settings → Privacy & Security → Bluetooth* and toggle the host
app on. No reboot required.

---

## Install

From this directory:

```bash
conda activate omilocal
pip install -r requirements.txt
```

Or, since you typically run the bridge alongside the backend:

```bash
pip install bleak opuslib websockets
```

---

## Quickstart

Two terminals.

**Terminal A — backend** (already covered in `RUNBOOK.md`):
```bash
conda activate omilocal
cd ~/Documents/codebase/OMI/code/omi/backend
uvicorn main_local:app --host 0.0.0.0 --port 8088
```

**Terminal B — bridge:**
```bash
cd ~/Documents/codebase/OMI/code/pin_bridge

# One-shot — handles login + dep install + run.
OMI_EMAIL=you@omi.dev OMI_PASSWORD=hunter2 ./run.sh
```

You should see:
```
[run.sh] obtained JWT (length=...)
13:42:01 INFO    pin_bridge: Connecting to backend WS: ws://127.0.0.1:8088/v4/listen?sample_rate=16000&codec=linear16&language=en
13:42:02 INFO    pin_bridge: Connected to Omi-XXXX (XX:XX:XX:XX:XX:XX)
13:42:02 INFO    pin_bridge: audio format characteristic: 01
13:42:02 INFO    pin_bridge: Subscribed to audio notifications. Speak into the pin. Ctrl-C to stop and flush the transcript.
```

Speak into the pin. After ~5 seconds you should start seeing `partial:` lines.
Hit Ctrl-C to stop — the backend will persist the conversation and emit a
`conversation_event` confirmation line.

---

## Manual usage

```bash
conda activate omilocal

# 1) get a JWT from the backend
JWT=$(./login.sh you@omi.dev hunter2)

# 2) sanity-check what's in BLE range without connecting
python pin_bridge.py --scan-only

# 3) connect by name prefix (default)
python pin_bridge.py --token "$JWT"

# 4) connect by exact MAC (use this if multiple Omi pins are nearby)
python pin_bridge.py --token "$JWT" --address XX:XX:XX:XX:XX:XX

# 5) save raw audio for diagnostics
python pin_bridge.py --token "$JWT" \
  --save-pcm /tmp/pin.pcm \
  --save-opus /tmp/pin.opus
```

The PCM dump is plain 16 kHz mono signed 16-bit little-endian; play it with
ffmpeg:
```bash
ffplay -f s16le -ar 16000 -ac 1 -i /tmp/pin.pcm
```

---

## Environment variables

| Variable | Default | Meaning |
|----------|---------|---------|
| `OMI_LOCAL_BACKEND` | `ws://127.0.0.1:8088` | WS base URL of `main_local`. The script appends `/v4/listen?…` (or `/v1/transcribe/stream` with `--legacy-endpoint`). |
| `OMI_LOCAL_BACKEND_HTTP` (login.sh) | `http://127.0.0.1:8088` | HTTP base URL for `/v1/auth/{register,login}`. |
| `OMI_LOCAL_JWT` | — | Pre-fetched JWT. If set, `run.sh` skips the login step. |
| `OMI_EMAIL` / `OMI_PASSWORD` | — | Used by `run.sh` and `login.sh` if no positional args. |

---

## How the wire format works (read this if you're debugging)

The firmware's transport layer (`omi/omi/firmware/omi/src/lib/core/transport.c`)
builds each BLE notification as:

```
byte 0          packet_id (low 8 bits)        ──┐
byte 1          packet_id (high 8 bits)         │ NET_BUFFER_HEADER_SIZE = 3
byte 2          sub_index inside packet        ──┘
byte 3..N       Opus payload chunk
```

- One *Opus frame* corresponds to **one packet_id** but may be split across
  multiple notifications when the negotiated MTU is smaller than the frame.
- `sub_index == 0` always starts a new packet. Subsequent chunks share the
  same `packet_id` and have monotonically increasing `sub_index`.
- The encoder is set up at boot in `codec.c`:
  ```
  16 kHz, mono, 32 kbps, complexity 3, no DTX, no FEC, voice signal,
  CODEC_PACKAGE_SAMPLES = 320  (20 ms frames)
  CODEC_OUTPUT_MAX_BYTES = 160
  ```
- The audio-format characteristic (`19B10002-…`) is a single byte. The
  script logs it on connect; today it is always `01` (Opus).

`FrameAssembler` in `pin_bridge.py` implements the reassembly. If you need
to debug, run with `-v` and watch the per-5s stats line:

```
INFO  rx: frames=1234 sent=987KB asm.completed=1234 ooo=0 dropped=0
```

`ooo` (out-of-order) and `dropped` should both stay at 0 in a healthy
session. Persistent nonzero values usually mean BLE packet loss — typically
caused by RF interference or distance.

---

## Troubleshooting

| Symptom | Likely cause / fix |
|---------|--------------------|
| `bleak is not installed` | `pip install -r requirements.txt` inside `omilocal`. |
| `opuslib is not installed` | `brew install opus && pip install opuslib`. |
| Stays "Scanning…" forever | The pin is already paired with another host (close the official app), or it is in offline-storage mode (toggle BLE off/on, or power-cycle the pin). Run `--scan-only` to confirm what's advertising. |
| `Backend rejected token: invalid token` | The JWT expired (`LOCAL_JWT_TTL_SECONDS`) or `LOCAL_JWT_SECRET` was rotated since login. Re-run `login.sh`. |
| First `partial` takes 30+ seconds | Whisper is loading. The model is loaded lazily on first audio. After that, partials arrive every ~5 s. |
| `partial` lines look garbled | You probably configured `LOCAL_WHISPER_MODEL=tiny` and the speech is non-English. Bump to `base` or `small`. |
| BLE prompt never appears, status says "Bluetooth permission denied" | *System Settings → Privacy & Security → Bluetooth* — enable for your terminal app. |
| `[Errno 50] Protocol not available` on macOS Sonoma | Apple regression; opening *System Settings → Bluetooth → On/Off toggle* once usually clears it. |
| Pin keeps disconnecting after a few minutes | Battery low or RF interference. Charge it / move closer. |
| Final transcript is empty | The backend received no audio frames — usually because Opus decoding failed. Check `asm.dropped` and `ooo` stats; if they are nonzero, save Opus with `--save-opus` and replay offline. |
| `database is locked` warnings on the backend side | You started multiple uvicorn workers. Use `--workers 1`. |

---

## What this script deliberately does *not* do

- **No automatic memory extraction.** Conversations are saved to SQLite and
  indexed in Qdrant, but LLM-based memory/insight extraction is not triggered
  automatically at end of session.
- **No speaker diarization.** Local mode runs single-speaker by design
  (`ENABLE_DIARIZATION=false`). Every transcript is attributed to `SPEAKER_00`.

---

## What is now implemented

- **Offline SD card drain** (`pin_offline_drain.py`) — when the pin reconnects
  after being offline with `CONFIG_OMI_ENABLE_OFFLINE_STORAGE=y`, the full
  multi-file GATT storage protocol is executed automatically: CMD_LIST_FILES,
  per-file CMD_READ_FILE, SD block parsing, Opus decode, frames injected into
  the live send queue. Runs immediately on every connect before entering the
  live stream loop.
- **Haptic feedback** — a haptic pulse is written to the pin's haptic
  characteristic on successful connect, confirming the bridge is live.
- **Button subscriptions** — the pin's button-state characteristic is
  subscribed to; button events are logged (start/stop/segment triggers can be
  added in `stream_session()` as needed).

---

## Files

- `pin_bridge.py` — the bridge.
- `pin_offline_drain.py` — GATT storage drain (offline audio recovery).
- `login.sh` — register (idempotent) + login → prints JWT.
- `run.sh` — convenience wrapper: activate `omilocal`, ensure deps, log in,
  run the bridge.
- `requirements.txt` — Python deps.

For the bigger picture and the place this script fits in the migration,
see:

- `code/MIGRATION_STATUS.md`
- `code/RUNBOOK.md`
- `code/PIN_AND_CLIENTS_LOCAL.md`
- `code/SETUP_FROM_SCRATCH.md`
