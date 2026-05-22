"""Offline SD-card audio drain for the Omi pin.

Implements the multi-file GATT storage protocol from
``omi/firmware/omi/src/lib/core/storage.c``.

Protocol flow
-------------
1. Read the READ characteristic to get the file count (4-byte LE fields:
   total_bytes, file_count, free_bytes, flags).  Skip if file_count == 0.
2. Subscribe to WRITE characteristic notifications.
3. Send CMD_LIST_FILES (0x10) → receive one notification:
   ``[count:1][ts:4 BE][size:4 BE]*``
4. For each file index 0 … count-1:
   a. Send CMD_READ_FILE (0x11, index:1, offset:4 BE).
   b. Receive a 1-byte ack notification (0 = accepted).
   c. Receive data notifications: ``[timestamp:4 BE][packed_audio:N]``.
   d. Receive done notification: single byte ``{100}`` (0x64).
   Firmware auto-deletes successfully transferred files.
5. Unsubscribe.

Audio packing format (SD card / over the wire)
----------------------------------------------
SD blocks are 440 bytes. Each block contains back-to-back records:
    [frame_size : 1 byte] [opus_data : frame_size bytes] …
A "dangling" size byte may sit at offset 405 of a block without its payload
crossing into the next block. The parser is purely streaming — it does NOT
know about 440-byte block boundaries; it just reads (size, data) pairs until
the chunk is exhausted, discarding any trailing size byte that has no following
data.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import struct
from typing import Callable, List, Optional

logger = logging.getLogger("pin_offline_drain")

# ── GATT UUIDs (OMI pin firmware, storage.c) ──────────────────────────────────

STORAGE_SERVICE_UUID = "30295780-4301-eabd-2904-2849adfeae43"
STORAGE_WRITE_CHAR_UUID = "30295781-4301-eabd-2904-2849adfeae43"
STORAGE_READ_CHAR_UUID = "30295782-4301-eabd-2904-2849adfeae43"

# ── Command bytes ──────────────────────────────────────────────────────────────

CMD_LIST_FILES: int = 0x10
CMD_READ_FILE: int = 0x11
CMD_STOP_SYNC: int = 0x03

# ── Audio geometry (must match firmware config.h) ─────────────────────────────

_OPUS_FRAME_SAMPLES: int = 320   # CODEC_PACKAGE_SAMPLES = 160 * 2
_TIMESTAMP_PREFIX: int = 4       # bytes at the head of every data notification

_DONE_BYTE: int = 0x64           # 100 decimal — firmware signals EOF with this single byte


def _parse_audio_chunk(chunk: bytes) -> List[bytes]:
    """Return a list of raw Opus frames extracted from a packed audio chunk.

    Format: ``[size:1][opus_data:size]...`` repeated until the buffer is
    exhausted.  A trailing size byte with no following data is silently dropped
    (natural consequence of 440-byte SD block packing).
    """
    frames: List[bytes] = []
    pos = 0
    while pos < len(chunk):
        size = chunk[pos]
        pos += 1
        if size == 0:
            continue
        if pos + size > len(chunk):
            # Dangling size byte at end of SD block — no payload follows.
            break
        frames.append(chunk[pos : pos + size])
        pos += size
    return frames


async def drain_offline_storage(
    client,
    decoder,
    send_queue: asyncio.Queue,
    *,
    pcm_sink=None,
    opus_sink: Optional[Callable[[bytes], None]] = None,
    decode_opus: bool = True,
) -> int:
    """Download all pending offline audio from the pin's SD card.

    When ``decode_opus=True``, each stored Opus frame is decoded to PCM16 and
    queued for a ``linear16`` backend session.  The decoder must not be None.

    When ``decode_opus=False``, each stored Opus frame is queued directly so a
    thin bridge can forward it to ``/v4/listen?codec=opus`` and let the backend
    decode it.  No ``opuslib`` import is required on the bridge machine.

    Parameters
    ----------
    client:
        An active ``bleak.BleakClient`` instance already inside a context.
    decoder:
        An ``opuslib.Decoder`` configured for 16 kHz mono.  Required when
        ``decode_opus=True``; ignored (may be None) when ``decode_opus=False``.
    send_queue:
        ``asyncio.Queue`` shared with the WS sender.  Items are raw PCM16 bytes
        when ``decode_opus=True``, or raw Opus frame bytes when
        ``decode_opus=False``.
    pcm_sink:
        Optional writable file-like for raw PCM diagnostics (only used when
        ``decode_opus=True``).
    opus_sink:
        Optional callable receiving each raw Opus frame for diagnostics.
    decode_opus:
        When True (default), decode Opus → PCM before queuing.  When False,
        queue raw Opus frames directly so the backend can decode them.

    Returns
    -------
    int
        Total number of frames pushed onto *send_queue*.
    """
    if decode_opus and decoder is None:
        raise ValueError("decoder is required when decode_opus=True")

    # ── 1. Quick check: how many files are waiting? ────────────────────────────
    try:
        meta_bytes = await client.read_gatt_char(STORAGE_READ_CHAR_UUID)
    except Exception as exc:
        logger.debug("Storage read characteristic unavailable — skipping offline drain: %s", exc)
        return 0

    if len(meta_bytes) < 8:
        logger.debug("Storage meta too short (%d bytes) — skipping offline drain", len(meta_bytes))
        return 0

    _total_bytes, file_count, _free_bytes, _flags = struct.unpack_from('<IIII', meta_bytes, 0)
    if file_count == 0:
        logger.info("No offline audio files on pin — skipping drain")
        return 0

    logger.info("Offline drain starting: %d file(s) found on pin", file_count)

    # ── 2. Shared notification plumbing ───────────────────────────────────────
    # We use a single asyncio.Queue to ferry raw notification bytes from the
    # sync BLE callback into the async protocol state machine below.
    _notif_queue: asyncio.Queue[bytes] = asyncio.Queue()

    def _on_storage_notif(_handle: int, data: bytearray) -> None:
        _notif_queue.put_nowait(bytes(data))

    await client.start_notify(STORAGE_WRITE_CHAR_UUID, _on_storage_notif)

    frames_queued = 0

    try:
        # ── 3. CMD_LIST_FILES ─────────────────────────────────────────────────
        await client.write_gatt_char(STORAGE_WRITE_CHAR_UUID, bytes([CMD_LIST_FILES]), response=True)
        try:
            file_list_notif = await asyncio.wait_for(_notif_queue.get(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Timed out waiting for file list — aborting offline drain")
            return 0

        # Parse: [count:1][ts:4 BE][sz:4 BE] * count
        count_from_list = file_list_notif[0] if file_list_notif else 0
        if count_from_list == 0:
            logger.info("File list reports 0 files — nothing to drain")
            return 0

        # Gather (timestamp_hex, size) for each file (informational only).
        files_meta = []
        for i in range(count_from_list):
            offset = 1 + i * 8
            if offset + 8 > len(file_list_notif):
                break
            ts_be, sz_be = struct.unpack_from('>II', file_list_notif, offset)
            files_meta.append((ts_be, sz_be))
            logger.debug("  file[%d]: ts=0x%08X  size=%d bytes", i, ts_be, sz_be)

        # ── 4. Read each file ─────────────────────────────────────────────────
        for file_index in range(len(files_meta)):
            ts_hex, expected_size = files_meta[file_index]
            logger.info(
                "Downloading offline file %d/%d (ts=0x%08X, ~%d bytes) …",
                file_index + 1,
                len(files_meta),
                ts_hex,
                expected_size,
            )

            # CMD_READ_FILE: [0x11][index:1][offset:4 BE]
            cmd = struct.pack('>BBi', CMD_READ_FILE, file_index, 0)
            await client.write_gatt_char(STORAGE_WRITE_CHAR_UUID, cmd, response=True)

            # Wait for 1-byte ack (0 = ok)
            try:
                ack = await asyncio.wait_for(_notif_queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Timed out waiting for ack for file %d — skipping", file_index)
                continue
            if len(ack) == 1 and ack[0] != 0:
                logger.warning("File %d: ack error byte=%d — skipping", file_index, ack[0])
                continue

            # Receive data and done notifications.
            file_frames = 0
            while True:
                try:
                    notif = await asyncio.wait_for(_notif_queue.get(), timeout=10.0)
                except asyncio.TimeoutError:
                    logger.warning("Timed out receiving data for file %d — abandoning", file_index)
                    break

                # Done sentinel: single byte 0x64
                if len(notif) == 1 and notif[0] == _DONE_BYTE:
                    logger.info(
                        "File %d complete — %d %s frames queued",
                        file_index,
                        file_frames,
                        "Opus" if not decode_opus else "PCM",
                    )
                    break

                # Strip 4-byte timestamp prefix, then parse packed audio.
                if len(notif) <= _TIMESTAMP_PREFIX:
                    continue
                audio_chunk = notif[_TIMESTAMP_PREFIX:]

                for opus_frame in _parse_audio_chunk(audio_chunk):
                    if opus_sink is not None:
                        opus_sink(opus_frame)

                    if decode_opus:
                        try:
                            payload = decoder.decode(opus_frame, _OPUS_FRAME_SAMPLES, decode_fec=False)
                        except Exception as exc:
                            logger.debug("Opus decode error (file %d): %s", file_index, exc)
                            continue
                        if pcm_sink is not None:
                            pcm_sink.write(payload)
                    else:
                        payload = opus_frame

                    file_frames += 1
                    frames_queued += 1
                    try:
                        await asyncio.wait_for(send_queue.put(payload), timeout=5.0)
                    except asyncio.TimeoutError:
                        logger.warning(
                            "Offline drain: send queue stalled for 5s (file %d) — "
                            "WebSocket may have dropped. Aborting drain.",
                            file_index,
                        )
                        return frames_queued
                    except Exception:
                        logger.exception("Failed to queue offline frame (file %d)", file_index)

    finally:
        with contextlib.suppress(Exception):
            await client.stop_notify(STORAGE_WRITE_CHAR_UUID)

    logger.info(
        "Offline drain complete — %d total %s frames queued",
        frames_queued,
        "PCM" if decode_opus else "Opus",
    )
    return frames_queued
