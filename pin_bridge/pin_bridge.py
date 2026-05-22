#!/usr/bin/env python3
"""Omi pin → local backend BLE bridge.

Pairs with an Omi pin over Bluetooth Low Energy, reassembles the Opus audio
frames the firmware streams over GATT notifications, decodes them to PCM16,
and pushes the PCM into ``main_local``'s streaming-transcribe WebSocket so
local Whisper can produce a transcript.

Constraints baked in (read from the firmware in
``omi/omi/firmware/omi/src/lib/core/``):

- Audio service UUID:        ``19B10000-E8F2-537E-4F6C-D104768A1214``
- Audio data characteristic: ``19B10001-E8F2-537E-4F6C-D104768A1214`` (NOTIFY)
- Audio format characteristic: ``19B10002-…`` (READ — used to confirm Opus)
- Encoder: Opus, 16 kHz mono, 20 ms frames (320 samples), 32 kbps CBR-ish, complexity 3
- BLE wire framing: each notification is ``[id_lo, id_hi, sub_index, ...payload]``.
  When MTU < frame, one Opus frame is split across multiple notifications that
  share the same packet id; ``sub_index == 0`` marks the first chunk.

Usage:
    python pin_bridge.py --token "$JWT"
    python pin_bridge.py --token "$JWT" --backend ws://127.0.0.1:8088
    python pin_bridge.py --scan-only        # just list nearby BLE devices
    python pin_bridge.py --device-name Omi  # pair by name prefix instead of address
    python pin_bridge.py --address XX:XX:XX:XX:XX:XX

Default endpoint: ``/v4/listen`` — header-based Bearer auth, full conversation
lifecycle (conversation persisted + indexed on WS close).  Emits
``transcript_segment``, ``conversation_processing_started``, and
``conversation_event`` JSON events to the terminal.

Use ``--legacy-endpoint`` to fall back to ``/v1/transcribe/stream`` (first-frame
JWT auth, no conversation lifecycle — only raw transcript events).

Hit Ctrl-C to stop. With ``/v4/listen`` the backend creates the conversation on
WS close; with ``--legacy-endpoint`` the script sends a literal ``"END"`` text
frame to trigger the final transcript response.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import signal
import struct
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

# ---------- Constants pulled directly from the firmware -----------------------

OMI_AUDIO_SERVICE_UUID = "19B10000-E8F2-537E-4F6C-D104768A1214"
OMI_AUDIO_DATA_CHAR_UUID = "19B10001-E8F2-537E-4F6C-D104768A1214"
OMI_AUDIO_FORMAT_CHAR_UUID = "19B10002-E8F2-537E-4F6C-D104768A1214"

OMI_BUTTON_SERVICE_UUID = "23BA7924-0000-1000-7450-346EAC492E92"
OMI_BUTTON_CHAR_UUID = "23BA7925-0000-1000-7450-346EAC492E92"
OMI_HAPTIC_SERVICE_UUID = "CAB1AB95-2EA5-4F4D-BB56-874B72CFC984"
OMI_HAPTIC_CHAR_UUID = "CAB1AB96-2EA5-4F4D-BB56-874B72CFC984"

# bleak is case-insensitive, but lower-casing matches what BlueZ/CoreBluetooth
# emit so it's friendlier in logs.
OMI_AUDIO_DATA_CHAR_UUID = OMI_AUDIO_DATA_CHAR_UUID.lower()
OMI_AUDIO_FORMAT_CHAR_UUID = OMI_AUDIO_FORMAT_CHAR_UUID.lower()
OMI_AUDIO_SERVICE_UUID = OMI_AUDIO_SERVICE_UUID.lower()
OMI_BUTTON_SERVICE_UUID = OMI_BUTTON_SERVICE_UUID.lower()
OMI_BUTTON_CHAR_UUID = OMI_BUTTON_CHAR_UUID.lower()
OMI_HAPTIC_SERVICE_UUID = OMI_HAPTIC_SERVICE_UUID.lower()
OMI_HAPTIC_CHAR_UUID = OMI_HAPTIC_CHAR_UUID.lower()

OPUS_SAMPLE_RATE = 16000
OPUS_CHANNELS = 1
OPUS_FRAME_MS = 20                                  # firmware emits 20 ms frames
OPUS_FRAME_SAMPLES = OPUS_SAMPLE_RATE * OPUS_FRAME_MS // 1000   # 320

# Each BLE notification carries this 3-byte little-endian header followed by
# (a slice of) one Opus frame. See transport.c:1024-1031.
NET_BUFFER_HEADER_SIZE = 3

DEFAULT_DEVICE_NAME_PREFIX = "Omi"

# ------------------------------------------------------------------------------

logger = logging.getLogger("pin_bridge")

try:
    from pin_offline_drain import drain_offline_storage as _drain_offline_storage

    _OFFLINE_DRAIN_AVAILABLE = True
except ImportError:
    _OFFLINE_DRAIN_AVAILABLE = False


async def write_haptic(client, pattern_byte: int = 1) -> None:
    """Write a haptic pattern to the pin. Call from within a BleakClient context."""
    await client.write_gatt_char(OMI_HAPTIC_CHAR_UUID, bytes([pattern_byte]), response=False)


@dataclass
class FrameAssembler:
    """Reassembles Opus frames from BLE notification chunks.

    The firmware tags every notification with a packet id (uint16 LE) and a
    sub-index (uint8). Chunks of the same packet id concatenate to form one
    Opus payload. ``sub_index == 0`` starts a new packet; nonzero indices
    continue the previous packet.
    """

    current_id: Optional[int] = None
    current_buf: bytearray = field(default_factory=bytearray)
    completed: int = 0
    out_of_order: int = 0
    dropped: int = 0

    def feed(self, payload: bytes) -> Optional[bytes]:
        """Return a complete Opus frame when the next frame boundary is crossed.

        A frame boundary is a new notification with sub_index == 0.  The
        previously accumulated buffer is only emitted at that point, so
        multi-chunk frames are returned whole rather than as partial payloads.
        """
        if len(payload) < NET_BUFFER_HEADER_SIZE + 1:
            self.dropped += 1
            return None

        packet_id = payload[0] | (payload[1] << 8)
        sub_index = payload[2]
        chunk = payload[NET_BUFFER_HEADER_SIZE:]

        if sub_index == 0:
            # New frame starting — the previous buffer (if any) is now complete.
            prev_frame: Optional[bytes] = None
            if self.current_id is not None:
                if self.current_buf:
                    prev_frame = bytes(self.current_buf)
                    self.completed += 1
                else:
                    self.dropped += 1
            self.current_id = packet_id
            self.current_buf = bytearray(chunk)
            return prev_frame  # None on the very first notification
        else:
            if self.current_id is None or packet_id != self.current_id:
                self.out_of_order += 1
                self.current_id = None
                self.current_buf.clear()
                return None
            self.current_buf.extend(chunk)
            return None

    def flush(self) -> Optional[bytes]:
        """Emit whatever is left in the buffer (call once the stream has ended)."""
        if self.current_buf:
            frame = bytes(self.current_buf)
            self.completed += 1
            self.current_buf.clear()
            self.current_id = None
            return frame
        self.current_id = None
        return None


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _import_runtime(thin: bool = False, scan_only: bool = False):
    """Import bleak / websockets lazily so --help works without them.

    scan_only: only bleak is needed (no WebSocket, no Opus).
    thin:      bleak + websockets needed, opuslib skipped (backend decodes Opus).
    normal:    bleak + websockets + opuslib all required.
    """
    _py = sys.executable
    _env_hint = (
        f"\nActive Python: {_py}"
        "\nIf packages are installed but not found, you may be in the wrong environment."
        "\nRun via run.sh (handles conda activation) or activate omilocal first:"
        "\n  conda activate omilocal"
    )
    base_deps = "bleak websockets" if thin else "bleak opuslib websockets"
    try:
        import bleak  # noqa: F401
        from bleak import BleakClient, BleakScanner  # noqa: F401
        from bleak.exc import BleakError  # noqa: F401
    except ImportError:
        sys.exit(f"bleak is not installed. Run: pip install {base_deps}{_env_hint}")

    if scan_only:
        return  # scan-only never opens a WebSocket or decodes audio

    if not thin:
        try:
            import opuslib  # noqa: F401
        except ImportError:
            sys.exit(
                "opuslib is not installed. Run: "
                "pip install opuslib  (and 'brew install opus' on macOS first)\n"
                f"Alternatively, use --thin to skip local Opus decoding entirely.{_env_hint}"
            )
    try:
        import websockets  # noqa: F401
    except ImportError:
        sys.exit(f"websockets is not installed. Run: pip install websockets{_env_hint}")


async def scan_only(timeout: float = 6.0) -> int:
    from bleak import BleakScanner

    print(f"Scanning for {timeout:.1f}s…")
    devices = await BleakScanner.discover(timeout=timeout)
    if not devices:
        print("No devices seen. Make sure the pin is powered and not already connected.")
        return 1
    for d in devices:
        _meta = getattr(d, "metadata", None)
        services = ", ".join(_meta.get("uuids", []) or []) if _meta else ""
        print(f"  {d.address}  rssi={getattr(d, 'rssi', '?'):>4}  name={d.name!r}  services=[{services}]")
    return 0


async def find_device(
    *,
    address: Optional[str],
    name_prefix: str,
    timeout: float,
):
    from bleak import BleakScanner

    if address:
        device = await BleakScanner.find_device_by_address(address, timeout=timeout)
        if device is None:
            raise RuntimeError(f"Device {address} not found within {timeout:.0f}s")
        return device

    logger.info("Scanning for a BLE peripheral whose name starts with %r…", name_prefix)
    device = await BleakScanner.find_device_by_filter(
        lambda d, _ad: bool(d.name and d.name.startswith(name_prefix)),
        timeout=timeout,
    )
    if device is None:
        raise RuntimeError(
            f"No BLE peripheral with name prefix {name_prefix!r} appeared within "
            f"{timeout:.0f}s. Try --scan-only to inspect what is actually advertising."
        )
    return device


async def stream_session(
    *,
    device,
    backend_url: str,
    token: str,
    save_pcm_to: Optional[str],
    save_opus_to: Optional[str],
    stop_event: asyncio.Event,
    log_partials: bool,
    use_v4_listen: bool = True,
    thin: bool = False,
) -> None:
    from bleak import BleakClient
    from bleak.exc import BleakError
    import websockets

    if not thin:
        import opuslib
        decoder = opuslib.Decoder(OPUS_SAMPLE_RATE, OPUS_CHANNELS)
    else:
        decoder = None

    assembler = FrameAssembler()

    if save_pcm_to and thin:
        logger.warning("--save-pcm ignored in --thin mode (no PCM is decoded locally)")

    if use_v4_listen:
        codec_param = "opus" if thin else "linear16"
        ws_url = (
            backend_url.rstrip("/")
            + f"/v4/listen?sample_rate=16000&codec={codec_param}&language=en"
        )
        ws_kwargs = {
            "additional_headers": {"Authorization": f"Bearer {token}"},
            "max_size": None,
            "ping_interval": 20,
            "ping_timeout": 20,
        }
    else:
        ws_url = backend_url.rstrip("/") + "/v1/transcribe/stream"
        ws_kwargs = {"max_size": None, "ping_interval": 20, "ping_timeout": 20}

    logger.info("Connecting to backend WS: %s", ws_url)

    pcm_sink = open(save_pcm_to, "wb") if save_pcm_to and not thin else None
    opus_sink_file = open(save_opus_to, "wb") if save_opus_to else None
    opus_sink = opus_sink_file  # kept for live-audio notification diagnostics

    bytes_sent = 0
    frames_decoded = 0
    last_log = time.monotonic()

    async with websockets.connect(ws_url, **ws_kwargs) as ws:
        if not use_v4_listen:
            # Legacy protocol: first text frame is the JWT.
            await ws.send(token)

        # Drain any immediate auth-failure response without blocking forever.
        try:
            first = await asyncio.wait_for(ws.recv(), timeout=0.5)
            try:
                payload = json.loads(first)
            except (TypeError, ValueError):
                payload = {"raw": first}
            if isinstance(payload, dict) and payload.get("error"):
                raise RuntimeError(f"Backend rejected token: {payload['error']}")
        except asyncio.TimeoutError:
            pass

        async def reader_task() -> None:
            try:
                async for msg in ws:
                    if isinstance(msg, bytes):
                        continue
                    try:
                        evt = json.loads(msg)
                    except ValueError:
                        logger.debug("ws raw: %s", msg)
                        continue
                    kind = evt.get("type")
                    if use_v4_listen:
                        if kind == "transcript_segment" and log_partials:
                            for seg in evt.get("segments", []):
                                logger.info("partial: %s", seg.get("text", ""))
                        elif kind == "conversation_processing_started":
                            logger.info(
                                "Processing conversation %s…",
                                evt.get("conversation_id", ""),
                            )
                        elif kind == "conversation_event":
                            conv = evt.get("conversation", {})
                            structured = conv.get("structured", {})
                            logger.info(
                                "Conversation saved — id=%s title=%r",
                                conv.get("id", ""),
                                structured.get("title", ""),
                            )
                    else:
                        if kind == "partial" and log_partials:
                            logger.info("partial: %s", evt.get("text", ""))
                        elif kind == "final":
                            logger.info("FINAL TRANSCRIPT:\n%s", evt.get("text", ""))
            except websockets.exceptions.ConnectionClosed:
                pass

        reader = asyncio.create_task(reader_task())

        send_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=64)

        async def sender_task() -> None:
            nonlocal bytes_sent
            while True:
                pcm = await send_queue.get()
                if pcm is None:  # type: ignore[unreachable]
                    return
                try:
                    await ws.send(pcm)
                    bytes_sent += len(pcm)
                except websockets.exceptions.ConnectionClosed:
                    return

        sender = asyncio.create_task(sender_task())

        def on_audio_packet(_handle: int, data: bytearray) -> None:
            nonlocal frames_decoded, last_log
            try:
                if opus_sink:
                    opus_sink.write(bytes(data))

                frame = assembler.feed(bytes(data))
                if frame is None:
                    return

                if thin:
                    # Forward the raw assembled Opus frame; the backend decodes it.
                    payload = frame
                else:
                    # Decode Opus → PCM16 LE locally before sending.
                    payload = decoder.decode(frame, OPUS_FRAME_SAMPLES, decode_fec=False)
                    if pcm_sink:
                        pcm_sink.write(payload)
                frames_decoded += 1

                # Hand off to the WS sender on the event loop.
                try:
                    send_queue.put_nowait(payload)
                except asyncio.QueueFull:
                    logger.warning("send queue full — dropping a 20 ms frame")

                now = time.monotonic()
                if now - last_log >= 5.0:
                    logger.info(
                        "rx: frames=%d sent=%dKB asm.completed=%d ooo=%d dropped=%d",
                        frames_decoded,
                        bytes_sent // 1024,
                        assembler.completed,
                        assembler.out_of_order,
                        assembler.dropped,
                    )
                    last_log = now
            except Exception:
                logger.exception("on_audio_packet failed")

        async with BleakClient(device, timeout=20.0) as client:
            logger.info("Connected to %s (%s)", device.name, device.address)

            # Optional sanity probe: read the format characteristic so we know
            # the firmware really is in Opus mode.
            try:
                fmt_bytes = await client.read_gatt_char(OMI_AUDIO_FORMAT_CHAR_UUID)
                logger.info("audio format characteristic: %s", fmt_bytes.hex())
            except Exception as exc:
                logger.debug("format characteristic read failed: %s", exc)

            def on_button_packet(_handle: int, data: bytearray) -> None:
                logger.info("button event: %s", data.hex())

            try:
                await client.start_notify(OMI_BUTTON_CHAR_UUID, on_button_packet)
                logger.debug("Subscribed to button notifications")
            except Exception as exc:
                logger.debug("Button subscription skipped (characteristic unavailable): %s", exc)

            try:
                await write_haptic(client, 1)
                logger.debug("Haptic 'ready' signal sent")
            except Exception as exc:
                logger.debug("Haptic write skipped: %s", exc)

            # Drain any audio recorded while the pin was out of range.
            # Audio notifications are intentionally NOT started yet — starting them
            # before the drain completes causes the live BLE callback to contend
            # with the drain for the fixed-size send queue, dropping live frames.
            if _OFFLINE_DRAIN_AVAILABLE:
                try:
                    offline_frames = await _drain_offline_storage(
                        client,
                        decoder,
                        send_queue,
                        pcm_sink=pcm_sink,
                        opus_sink=opus_sink_file.write if opus_sink_file else None,
                        decode_opus=not thin,
                    )
                    if offline_frames:
                        logger.info(
                            "Offline drain complete — pushed %d %s frames. Starting live audio.",
                            offline_frames,
                            "Opus" if thin else "PCM",
                        )
                except Exception:
                    logger.exception("Offline drain failed — continuing with live audio")
            else:
                logger.debug("pin_offline_drain not available — skipping offline drain")

            # Start live audio only after the drain queue has been flushed.
            await client.start_notify(OMI_AUDIO_DATA_CHAR_UUID, on_audio_packet)
            logger.info(
                "Subscribed to audio notifications. Speak into the pin. "
                "Ctrl-C to stop and flush the transcript."
            )

            try:
                await stop_event.wait()
            finally:
                with contextlib.suppress(BleakError):
                    await client.stop_notify(OMI_AUDIO_DATA_CHAR_UUID)
                with contextlib.suppress(Exception):
                    await client.stop_notify(OMI_BUTTON_CHAR_UUID)

        # Flush the final partially-accumulated Opus frame before draining the WS.
        final_frame = assembler.flush()
        if final_frame is not None:
            try:
                if thin:
                    payload = final_frame
                else:
                    payload = decoder.decode(final_frame, OPUS_FRAME_SAMPLES, decode_fec=False)
                    if pcm_sink:
                        pcm_sink.write(payload)
                frames_decoded += 1
                try:
                    send_queue.put_nowait(payload)
                except asyncio.QueueFull:
                    logger.warning("send queue full — dropping flushed final frame")
            except Exception:
                logger.debug("failed to process flushed final Opus frame")

        # Drain the send queue before closing — 5 s cap so a stalled WebSocket
        # sender (TCP backpressure from a busy backend) doesn't hang the process.
        _drain_deadline = time.monotonic() + 5.0
        while not send_queue.empty() and time.monotonic() < _drain_deadline:
            await asyncio.sleep(0.05)
        if not send_queue.empty():
            logger.warning(
                "Send queue drain timed out — discarding %d buffered frame(s)",
                send_queue.qsize(),
            )

        if not use_v4_listen:
            # Legacy protocol: send "END" text frame to trigger final transcript.
            with contextlib.suppress(websockets.exceptions.ConnectionClosed):
                await ws.send("END")

        # Cancel both tasks, then wait briefly for clean exit.
        reader.cancel()
        sender.cancel()
        with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
            await asyncio.wait_for(
                asyncio.gather(reader, sender, return_exceptions=True),
                timeout=5.0,
            )

    if pcm_sink:
        pcm_sink.close()
        logger.info("Wrote raw PCM16 mono 16kHz to %s", save_pcm_to)
    if opus_sink:
        opus_sink.close()
        logger.info("Wrote concatenated Opus frames to %s", save_opus_to)


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--token",
        default=os.environ.get("OMI_LOCAL_JWT"),
        help="JWT from POST /v1/auth/login. Defaults to env OMI_LOCAL_JWT.",
    )
    p.add_argument(
        "--backend",
        default=os.environ.get("OMI_LOCAL_BACKEND", "ws://127.0.0.1:8088"),
        help="ws:// or wss:// base URL of the local backend. Default: ws://127.0.0.1:8088",
    )
    p.add_argument(
        "--device-name",
        default=DEFAULT_DEVICE_NAME_PREFIX,
        help=f"BLE name prefix to match. Default: {DEFAULT_DEVICE_NAME_PREFIX!r}",
    )
    p.add_argument("--address", help="Match by exact BLE address instead of name prefix.")
    p.add_argument("--scan-only", action="store_true", help="Just print nearby BLE peripherals and exit.")
    p.add_argument("--scan-timeout", type=float, default=10.0, help="Scan timeout (s). Default: 10")
    p.add_argument(
        "--save-pcm",
        help="Write decoded PCM16 mono 16 kHz to this path for offline diagnostics.",
    )
    p.add_argument(
        "--save-opus",
        help="Write the raw concatenated Opus notification payloads to this path.",
    )
    p.add_argument("--no-partials", action="store_true", help="Suppress per-chunk partial transcripts.")
    p.add_argument(
        "--thin",
        action="store_true",
        help=(
            "Thin mode: forward raw assembled Opus frames to the backend without local decoding. "
            "The backend decodes Opus (opuslib is already installed there). "
            "On the bridge machine, only 'pip install bleak websockets' is required — "
            "no opuslib, no 'brew install opus'. "
            "Note: offline SD drain is skipped in thin mode."
        ),
    )
    p.add_argument(
        "--legacy-endpoint",
        action="store_true",
        help=(
            "Use the old /v1/transcribe/stream endpoint (first-frame JWT auth, no "
            "conversation lifecycle). Default is /v4/listen with header auth."
        ),
    )
    p.add_argument("-v", "--verbose", action="store_true", help="Debug logging.")
    return p.parse_args(argv)


async def amain(args: argparse.Namespace) -> int:
    if args.scan_only:
        return await scan_only(args.scan_timeout)

    if not args.token:
        sys.exit("--token (or OMI_LOCAL_JWT env) is required when not using --scan-only.")

    device = await find_device(
        address=args.address,
        name_prefix=args.device_name,
        timeout=args.scan_timeout,
    )

    stop_event = asyncio.Event()

    def _stop(*_args) -> None:
        if not stop_event.is_set():
            logger.info("Stopping…")
            stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, _stop)

    try:
        await stream_session(
            device=device,
            backend_url=args.backend,
            token=args.token,
            save_pcm_to=args.save_pcm,
            save_opus_to=args.save_opus,
            stop_event=stop_event,
            log_partials=not args.no_partials,
            use_v4_listen=not args.legacy_endpoint,
            thin=args.thin,
        )
        return 0
    except RuntimeError as exc:
        logger.error("%s", exc)
        return 2


def main(argv=None) -> int:
    args = parse_args(argv)
    _setup_logging(args.verbose)
    _import_runtime(thin=args.thin, scan_only=args.scan_only)
    try:
        return asyncio.run(amain(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
