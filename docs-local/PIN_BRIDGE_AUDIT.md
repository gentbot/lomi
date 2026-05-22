# pin_bridge — Issues Audit

Audit of bugs and issues found during review sessions. Items are listed
chronologically within each section; each entry names the affected file(s),
describes the problem, and summarises what was done.

---

## Fixed

### 1. `run.sh` — `--backend` flag not forwarded to `login.sh`

**File:** `pin_bridge/run.sh`

`run.sh` calls `login.sh` to fetch a JWT before handing off to `pin_bridge.py`.
`login.sh` uses `OMI_LOCAL_BACKEND_HTTP` for its HTTP POST to `/v1/auth/login`,
defaulting to `http://127.0.0.1:8088`. When a user passed `--backend
ws://<YOUR_SERVER_IP>:8088` to `run.sh`, that flag was forwarded to `pin_bridge.py`
via `"$@"` but was never seen by `login.sh`. The login step hit `127.0.0.1` and
failed before `pin_bridge.py` ever ran.

**Fix:** `run.sh` now pre-scans its own argument list for `--backend` and
`--backend=…` before calling `login.sh`, derives `OMI_LOCAL_BACKEND_HTTP` by
replacing `ws://` → `http://` (and `wss://` → `https://`), and exports it so
`login.sh` inherits the correct base URL. The existing `OMI_LOCAL_BACKEND_HTTP`
env var is not overwritten if already set, so manual overrides still work.

---

### 2. `run.sh` — `opuslib` always installed even in `--thin` mode

**File:** `pin_bridge/run.sh`

The pip install step unconditionally ran:
```
python -m pip install --quiet bleak opuslib websockets 'PyJWT>=2'
```
even when `--thin` was passed. In thin mode `opuslib` is not used (the backend
decodes Opus), and installing it requires `brew install opus` first. Users on
machines without Homebrew Opus could not use `--thin` via `run.sh`.

**Fix:** `run.sh` pre-scans for `--thin` and runs a shorter install in that case:
```
python -m pip install --quiet bleak websockets
```

---

### 3. `_import_runtime` — Unhelpful error when packages "installed but not found"

**File:** `pin_bridge/pin_bridge.py`

The import failure messages said only `"bleak is not installed. Run: pip
install …"`. If the user had already installed the packages — but in a different
Python environment than the one running the script — the message gave no
actionable clue.

**Fix:** Error messages now include the active Python executable path
(`sys.executable`) and suggest activating the `omilocal` conda environment or
running via `run.sh` which handles activation automatically.

---

### 4. `_import_runtime` — `--scan-only` unnecessarily required `websockets`

**File:** `pin_bridge/pin_bridge.py`

`main()` called `_import_runtime(thin=args.thin or args.scan_only)`. Passing
`thin=True` for scan-only skipped the `opuslib` check but still checked
`websockets`. Scan-only mode never opens a WebSocket; it only calls
`BleakScanner.discover`. A user who just wanted to list nearby BLE devices would
fail if `websockets` was not installed.

**Fix:** `_import_runtime` now accepts a separate `scan_only` parameter and
returns immediately after the `bleak` check when `scan_only=True`. `main()` now
calls `_import_runtime(thin=args.thin, scan_only=args.scan_only)`.

---

### 5. `run.sh` / `pin_bridge.py` — `PyJWT` listed as a dependency but never used

**Files:** `pin_bridge/run.sh`, `pin_bridge/pin_bridge.py`

`PyJWT>=2` appeared in both `run.sh` pip install commands and was referenced in
the `--thin` argparse help string and `_import_runtime` docstring. Neither
`pin_bridge.py` nor `pin_offline_drain.py` nor `login.sh` ever imports or uses
`jwt`. It was a dead dependency from an earlier design where the bridge verified
tokens client-side.

**Fix:** Removed from both `run.sh` install lines and from the `--thin` help
text. The `requirements-thin.txt` and `requirements-full.txt` files did not list
it and were not changed.

---

### 6. `scan_only()` — `d.metadata` removed in bleak 0.22+

**File:** `pin_bridge/pin_bridge.py`

`scan_only()` accessed `d.metadata` to extract UUIDs for display. The
`metadata` attribute was deprecated in bleak 0.22 and removed in 0.23. The
requirements pin `bleak>=0.21` with no upper bound, so future installs could
pull in a version that raises `AttributeError` here.

**Fix:** Changed to `getattr(d, "metadata", None)` so the line is a no-op on
bleak versions that have removed the attribute rather than crashing.

---

### 7. `pin_offline_drain.py` — `await send_queue.put()` hangs if WebSocket drops during drain

**File:** `pin_bridge/pin_offline_drain.py`

The offline SD-card drain runs immediately after the BLE connection is
established, before entering the live recording loop. Audio frames are queued
via `await send_queue.put(payload)`. If the WebSocket connection dropped while
the drain was in progress, `sender_task` would exit (catching
`ConnectionClosed`), leaving nobody to consume from the queue. With `maxsize=64`
the queue fills in seconds and `await send_queue.put()` then blocks forever with
no timeout.

**Fix:** Replaced with `await asyncio.wait_for(send_queue.put(payload),
timeout=5.0)`. On `TimeoutError`, the drain logs a warning and returns the
frames queued so far rather than hanging indefinitely.

---

### 8. `stream_session` — Live audio dropped en masse when offline drain is active

**File:** `pin_bridge/pin_bridge.py`

`start_notify(OMI_AUDIO_DATA_CHAR_UUID, on_audio_packet)` was called immediately
after BLE connect, before the offline drain ran. The drain pushes stored SD-card
frames into the 64-slot `send_queue` as fast as the BLE storage protocol
delivers them, keeping the queue constantly full. The live BLE audio callback
(`on_audio_packet`) uses `put_nowait` — when the queue is full it logs "send
queue full — dropping a 20 ms frame" and discards the frame. During any offline
drain this produced a continuous flood of drop warnings and silently lost all
live audio for the duration of the drain.

**Symptom:** Dozens to hundreds of "send queue full — dropping a 20 ms frame"
warnings per second immediately after connecting when the pin has stored offline
audio.

**Fix:** Moved `start_notify` for the audio characteristic to **after** the
offline drain completes. The drain now has exclusive use of the queue; live audio
notifications are registered only once the drain queue has been flushed to the
backend. The `stop_notify` call in the `finally` block already uses
`contextlib.suppress(BleakError)`, so it handles the case where a drain
exception prevents the audio subscription from ever being started.

---

### 9. `stream_session` — Ctrl-C hangs the process for 4–7 minutes

**File:** `pin_bridge/pin_bridge.py`

After Ctrl-C the shutdown sequence is:

1. `stop_event` is set → `stop_event.wait()` returns.
2. BLE notifications stopped, `BleakClient` context exits (BLE disconnects).
3. Final frame flushed — if the queue was full, logged as "dropping flushed
   final frame".
4. `while not send_queue.empty(): await asyncio.sleep(0.05)` — **no timeout**.
5. Reader waited 10 s, then both tasks cancelled.

Step 4 is the hang. After a long session (especially one with an offline drain),
the backend may be busy with Whisper or LLM processing and stops reading from the
TCP socket. This causes TCP backpressure — `await ws.send(pcm)` inside
`sender_task` blocks waiting for the OS to drain the send buffer. `sender_task`
is stuck; the queue never empties; the drain loop spins every 50 ms forever.
`sender.cancel()` at step 5 is unreachable, so `sender_task` is never cancelled,
and the WebSocket is never closed. The process must be killed with `kill` or a
second Ctrl-C.

**Fix:**

- Added a 5-second deadline to the queue drain loop. On timeout, the remaining
  buffered frames are discarded and a warning is logged.
- Replaced the sequential "wait for reader, then cancel sender" logic with
  explicit cancellation of **both** tasks followed by a single bounded
  `asyncio.gather` wait (5-second cap). This guarantees both tasks are cancelled
  regardless of which one is slow.

Maximum shutdown time after Ctrl-C is now bounded at ~10–15 seconds (5 s queue
drain + 5 s task cancellation + WebSocket close handshake).

---

## Found — Not Fixed

### A. File handle leak for `--save-pcm` / `--save-opus` on exception paths

**File:** `pin_bridge/pin_bridge.py`

When `--save-pcm` or `--save-opus` are passed, `stream_session` opens file
handles near the top of the function and closes them explicitly at the bottom.
If an exception propagates out of the `async with websockets.connect(…)` block
(e.g. `BleakError`, unexpected disconnect), the close statements at the bottom
are never reached and the handles leak.

**Why not fixed:** These are diagnostic-only flags that most users never pass.
On any process exit — including one triggered by an unhandled exception — the OS
reclaims all open file descriptors. The correct fix (wrapping the entire
`async with` block in `try/finally`) requires re-indenting ~180 lines of the
function body; the risk of introducing a new indentation-related bug in
well-tested path code outweighs the benefit of fixing a minor leak on a rarely
used code path.

**Workaround:** If the session exits abnormally while `--save-pcm`/`--save-opus`
are active, the partial output file will still be present on disk and readable
up to the point of failure.

---

### B. `run.sh --scan-only` requires credentials even though scan-only needs no JWT

**File:** `pin_bridge/run.sh`

When `run.sh` is invoked with `--scan-only`, it still attempts to fetch a JWT
(step 3) before passing `--scan-only` through to `pin_bridge.py`. If
`OMI_LOCAL_JWT` is not set and `OMI_EMAIL`/`OMI_PASSWORD` are not provided,
`run.sh` exits with an error before any BLE scan happens. `pin_bridge.py` itself
handles `--scan-only` correctly and needs no token, but `run.sh` does not
special-case it.

**Why not fixed:** The workaround is straightforward — either set
`OMI_LOCAL_JWT=dummy` or call `pin_bridge.py --scan-only` directly (after
activating the `omilocal` env). Fixing `run.sh` would require detecting
`--scan-only` in the pre-scan arg loop and skipping the JWT step, which is safe
to add but was not prioritised given the easy workaround.

---

### C. `README.md` — Stale content for `--thin` and multi-machine usage

**File:** `pin_bridge/README.md`

The README predates the `--thin` flag and the multi-machine (`--backend`)
support. Specifically:

- Quickstart and manual-usage sections show only the single-machine
  `ws://127.0.0.1:8088` default; no example of `--backend` for remote backends.
- No section describing `--thin` mode, its reduced dependency set, or when to
  use it.
- The troubleshooting table entry for `bleak is not installed` still says only
  `pip install -r requirements.txt inside omilocal`, not mentioning the
  wrong-Python-environment scenario (which was the actual cause in the reported
  incident).
- The sample terminal log in the Quickstart still shows `ws://127.0.0.1:8088`.

**Why not fixed:** Documentation-only issue; no runtime behaviour is affected.
The RUNBOOK (`docs-local/RUNBOOK.md` §10.1 and §10.5.1) contains up-to-date
instructions for both thin mode and multi-machine usage, which is the primary
reference for this project's local setup.
