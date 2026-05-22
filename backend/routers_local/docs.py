"""Admin docs — .env.reference metadata and markdown file viewer.

Endpoints:
  GET /v1/admin/config/meta          — parse .env.reference → {KEY: {description, default}}
  GET /v1/admin/docs                 — curated list of project markdown files
  GET /v1/admin/docs/content?path=  — raw content of a catalogued file
"""

import os
import re
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.params import Query as QueryParam

from auth.router_dep import get_current_user_id_local

router = APIRouter(prefix="/v1/admin", tags=["docs"])

# ── Path resolution ────────────────────────────────────────────────────────────
# This file lives at backend/routers_local/docs.py
# backend/ is two dirname() calls up from __file__
# fork root (where docs-local/ and README-LOCAL.md live) is one more level up

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CODE_ROOT = os.path.normpath(os.path.join(_BACKEND_DIR, ".."))


def _code(rel: str) -> str:
    return os.path.normpath(os.path.join(_CODE_ROOT, rel))


# ── .env.reference parser ──────────────────────────────────────────────────────

def _parse_reference() -> Dict[str, dict]:
    """Parse .env.reference into {KEY: {description, default}}.

    Format:
        KEY=default_value
        # Description line(s)
        #   option — explanation
    """
    path = os.path.join(_BACKEND_DIR, ".env.reference")
    result: Dict[str, dict] = {}

    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = [l.rstrip("\n") for l in fh]
    except FileNotFoundError:
        return result

    i = 0
    while i < len(lines):
        line = lines[i]

        # Skip blanks and section separators
        if not line or re.match(r"^# =+", line):
            i += 1
            continue

        # Skip standalone comment lines between KEY blocks
        if line.startswith("#"):
            i += 1
            continue

        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if not m:
            i += 1
            continue

        key = m.group(1)
        default = m.group(2)
        i += 1

        # Collect comment lines that immediately follow
        desc_parts: List[str] = []
        while i < len(lines):
            l = lines[i]
            if l.startswith("#") and not re.match(r"^# =+", l):
                desc_parts.append(l[1:].lstrip(" "))
                i += 1
            elif not l:
                i += 1
                break
            else:
                break

        result[key] = {
            "default": default,
            "description": "\n".join(desc_parts).strip(),
        }

    return result


@router.get("/config/meta")
def get_config_meta(_uid: str = Depends(get_current_user_id_local)) -> dict:
    return _parse_reference()


# ── Markdown file catalog ──────────────────────────────────────────────────────
# Paths are relative to _CODE_ROOT (= fork root, where docs-local/ and README-LOCAL.md live)

_CURATED_DOCS = [
    ("Local Setup", [
        ("docs-local/LOCAL_CAPABILITIES.md",         "Local Capabilities"),
        ("docs-local/RUNBOOK.md",                    "Local Runbook"),
        ("docs-local/CLOUD_DEPENDENCY_AUDIT.md",     "Cloud Dependency Audit"),
        ("backend/PIN_LOCAL_AUDIO_SETUP.md",         "Pin Local Audio Setup"),
        ("docs-local/PIN_BRIDGE_AUDIT.md",           "Pin Bridge Audit"),
        ("docs-local/FORK_AND_MERGE_GUIDE.md",       "Fork & Merge Guide"),
        ("docs-local/UPSTREAM_SYNC_GUIDE.md",        "Upstream Sync Guide"),
        ("README-LOCAL.md",                          "Local README"),
        ("backend/CLAUDE.md",                        "Backend Dev Guide"),
        ("backend/README.md",                        "Backend README"),
        ("backend/.env.reference",                   ".env Reference"),
    ]),
    ("Project", [
        ("README.md",                                "Project README"),
        ("CLAUDE.md",                                "Claude Dev Guide"),
        ("AGENTS.md",                                "Agent Architecture"),
    ]),
    ("App (Flutter)", [
        ("app/README.md",                            "App README"),
        ("app/CLAUDE.md",                            "App Dev Guide"),
    ]),
    ("Desktop (macOS)", [
        ("Desktop/README.md",                        "Desktop README"),
        ("Desktop/CLAUDE.md",                        "Desktop Dev Guide"),
        ("Desktop/PLAN.md",                          "Desktop Plan"),
    ]),
    ("Firmware", [
        ("omi/firmware/BUILD_AND_OTA_FLASH.md",      "Build & Flash Guide"),
        ("omi/firmware/omi/README.md",               "Firmware README"),
    ]),
]

# Build an allowlist set once for fast lookup
_ALLOWED_PATHS = frozenset(p for _, files in _CURATED_DOCS for p, _ in files)


@router.get("/docs")
def list_docs(_uid: str = Depends(get_current_user_id_local)) -> list:
    result = []
    for section, files in _CURATED_DOCS:
        entries = [
            {"path": rel, "title": title, "exists": os.path.isfile(_code(rel))}
            for rel, title in files
        ]
        result.append({"section": section, "files": entries})
    return result


@router.get("/docs/content")
def get_doc_content(
    path: str = QueryParam(..., description="Path relative to project root (must be in catalog)"),
    _uid: str = Depends(get_current_user_id_local),
) -> dict:
    # Normalise separators and strip leading slashes
    clean = path.replace("\\", "/").lstrip("/")

    if clean not in _ALLOWED_PATHS:
        raise HTTPException(status_code=400, detail="Path not in catalog")

    abs_path = _code(clean)

    try:
        with open(abs_path, "r", encoding="utf-8") as fh:
            content = fh.read()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"path": clean, "content": content}
