"""Read and write configuration from .env files.

Three files are managed:
  backend  — omi/backend/.env           (this server; takes effect on restart)
  desktop  — omi/Desktop/Backend-Rust/.env  (Desktop app; re-run ./run.sh after)
  ios      — omi/app/.dev.env           (iOS app; rebuild after)

All endpoints require a valid Bearer token.
Sensitive values are masked in GET responses — the mask token is never written back.

Before every write the current file is copied to
  backend/env_backups/<YYYYMMDD-HHMMSS>-<purpose>.env.txt
so any accidental change is trivially reversible.
"""

import os
import re
import shutil
import tempfile
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth.router_dep import get_current_user_id_local

router = APIRouter(prefix="/v1/admin/config", tags=["config"])

# ── Path resolution ───────────────────────────────────────────────────────────

# This file lives at backend/routers_local/config.py
# backend/ is two dirname() calls up from __file__
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _abs(relative_to_backend: str) -> str:
    return os.path.normpath(os.path.join(_BACKEND_DIR, relative_to_backend))


_FILE_PATHS: Dict[str, str] = {
    "backend": _abs(".env"),
    "desktop": _abs("../Desktop/Backend-Rust/.env"),
    "ios":     _abs("../app/.dev.env"),
}

_TEMPLATE_PATHS: Dict[str, str] = {
    "desktop": _abs("../Desktop/.env.example"),
    "ios":     _abs("../app/.env.template"),
}

# Human-readable purpose labels used in backup filenames
_BACKUP_PURPOSES: Dict[str, str] = {
    "backend": "backend",
    "desktop": "desktopapp",
    "ios":     "mobileios",
}

_BACKUP_DIR = _abs("env_backups")

# ── Sensitive field masking ───────────────────────────────────────────────────

_SENSITIVE_SUBSTRINGS = frozenset([
    "SECRET", "PASSWORD", "API_KEY", "_KEY", "TOKEN",
    "PRIVATE_KEY", "ACCOUNT_SID", "CLIENT_SECRET", "AUTH_TOKEN",
    "ENCRYPTION", "WEBHOOK",
])
MASK = "••••••••"  # returned by GET; never written back


def _is_sensitive(key: str) -> bool:
    ku = key.upper()
    return any(s in ku for s in _SENSITIVE_SUBSTRINGS)


# ── .env file parser / writer ─────────────────────────────────────────────────

def _parse(path: str) -> List[dict]:
    """Parse an .env file into a list of line records (preserving comments/blanks)."""
    records: List[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.rstrip("\n")
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    records.append({"type": "other", "raw": line})
                    continue
                m = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)$', line)
                if m:
                    val = m.group(2)
                    # Strip surrounding single or double quotes
                    if (val.startswith("'") and val.endswith("'") and len(val) >= 2) or \
                       (val.startswith('"') and val.endswith('"') and len(val) >= 2):
                        val = val[1:-1]
                    records.append({"type": "kv", "key": m.group(1), "value": val, "raw": line})
                else:
                    records.append({"type": "other", "raw": line})
    except FileNotFoundError:
        pass
    return records


def _sanitize_value(val: str) -> str:
    """Strip characters that would corrupt a .env file line."""
    # Newlines would split a single key=value into multiple lines.
    # Carriage returns cause similar problems.
    return val.replace("\r", "").replace("\n", "")


def _needs_quoting(val: str) -> bool:
    """Return True if the value should be double-quoted when written."""
    # Quote if value contains spaces, #, $, or leading/trailing whitespace
    return bool(re.search(r'[\s#$]', val) or val != val.strip())


def _write(path: str, records: List[dict], updates: Dict[str, str]) -> None:
    """Update key=value lines in-place, append new keys at the end.

    Safety guarantees:
    - Values are sanitised (newlines stripped) to prevent line injection.
    - Values containing spaces, #, or $ are re-quoted so the file stays
      parseable by bash ``source`` as well as python-dotenv.
    - The write is atomic: content goes to a sibling temp file first, then
      os.replace() renames it over the target in a single syscall.
    """
    updated: set = set()
    out_lines: List[str] = []

    for rec in records:
        if rec["type"] == "kv" and rec["key"] in updates:
            safe_val = _sanitize_value(updates[rec["key"]])
            if _needs_quoting(safe_val):
                # Escape any embedded double-quotes, then wrap
                safe_val = '"' + safe_val.replace('"', '\\"') + '"'
            out_lines.append(f'{rec["key"]}={safe_val}')
            updated.add(rec["key"])
        else:
            out_lines.append(rec["raw"])

    for key, val in updates.items():
        if key not in updated:
            safe_val = _sanitize_value(val)
            if _needs_quoting(safe_val):
                safe_val = '"' + safe_val.replace('"', '\\"') + '"'
            out_lines.append(f"{key}={safe_val}")

    target_dir = os.path.dirname(path)
    os.makedirs(target_dir, exist_ok=True)

    # Atomic write: write to a temp file in the same directory, then rename.
    # os.replace() is atomic on POSIX; on Windows it's as close as we can get.
    fd, tmp_path = tempfile.mkstemp(dir=target_dir, prefix=".env_tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("\n".join(out_lines))
            if out_lines:
                fh.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _backup(target: str, abs_path: str) -> Optional[str]:
    """Copy the current .env file to env_backups/ before overwriting.

    Filename format: YYYYMMDD-HHMMSS-<purpose>.env.txt
    Returns the backup path, or None if the source file did not exist.
    """
    if not os.path.isfile(abs_path):
        return None

    os.makedirs(_BACKUP_DIR, exist_ok=True)

    purpose   = _BACKUP_PURPOSES.get(target, target)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name      = f"{timestamp}-{purpose}.env.txt"
    dest      = os.path.join(_BACKUP_DIR, name)

    shutil.copy2(abs_path, dest)
    return dest


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("")
def get_config(_uid: str = Depends(get_current_user_id_local)) -> dict:
    result: dict = {}
    for target, abs_path in _FILE_PATHS.items():
        exists  = os.path.isfile(abs_path)
        records = _parse(abs_path)

        # If desktop/ios file missing, seed visible defaults from template
        if not records and target in _TEMPLATE_PATHS:
            records = _parse(_TEMPLATE_PATHS[target])

        values: Dict[str, str] = {}
        for rec in records:
            if rec["type"] == "kv":
                val = rec["value"]
                if _is_sensitive(rec["key"]) and val:
                    val = MASK
                values[rec["key"]] = val

        result[target] = {"exists": exists, "path": abs_path, "values": values}
    return result


class ConfigUpdateRequest(BaseModel):
    target: str
    updates: Dict[str, str]


@router.post("")
def update_config(
    req: ConfigUpdateRequest,
    _uid: str = Depends(get_current_user_id_local),
) -> dict:
    if req.target not in _FILE_PATHS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown target '{req.target}'. Must be one of: {list(_FILE_PATHS)}",
        )

    # Never write the mask value back — skip those fields
    clean = {k: v for k, v in req.updates.items() if v != MASK and v is not None}
    if not clean:
        return {"ok": True, "written": 0, "backup": None}

    abs_path = _FILE_PATHS[req.target]

    # Back up the current file before doing anything
    backup_path = _backup(req.target, abs_path)

    records = _parse(abs_path)

    # Seed from template when creating the file for the first time
    if not records and req.target in _TEMPLATE_PATHS:
        records = _parse(_TEMPLATE_PATHS[req.target])

    try:
        _write(abs_path, records, clean)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Write failed: {exc}")

    return {
        "ok":      True,
        "written": len(clean),
        "path":    abs_path,
        "backup":  backup_path,
    }


@router.get("/backups")
def list_backups(_uid: str = Depends(get_current_user_id_local)) -> dict:
    """List all .env backup files in env_backups/."""
    if not os.path.isdir(_BACKUP_DIR):
        return {"backups": [], "dir": _BACKUP_DIR}

    files = sorted(
        f for f in os.listdir(_BACKUP_DIR)
        if f.endswith(".env.txt")
    )
    return {
        "backups": [{"name": f, "path": os.path.join(_BACKUP_DIR, f)} for f in files],
        "dir": _BACKUP_DIR,
    }
