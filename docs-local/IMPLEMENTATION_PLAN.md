# Implementation Plan — Remaining Work

Catalog of every unimplemented item found across the project documentation.
Items that already have a detailed implementation plan elsewhere are listed with a reference only.
Items without any existing plan have plan details written inline below.

---

## Items With Existing Plans (reference only)

| Area | Status | Plan location |
|------|--------|---------------|
| Post-processing pipeline — auto summarization, memory extraction, action items (A.1–A.3) | Not implemented | `backend/LOCAL_IMPLEMENTATION_PLAN.md §A.1–A.3` |
| Goal extraction + Goals router (A.4) | Not implemented | `backend/LOCAL_IMPLEMENTATION_PLAN.md §A.4` |
| Daily / weekly summaries via APScheduler (A.5) | Not implemented | `backend/LOCAL_IMPLEMENTATION_PLAN.md §A.5` |
| Real-time WebSocket events for new memories and action items (B.1, B.3) | Not wired | `backend/LOCAL_IMPLEMENTATION_PLAN.md §B` |
| Unified semantic search endpoint `POST /v1/search` (C) | Not implemented | `backend/LOCAL_IMPLEMENTATION_PLAN.md §C` |
| Conversation silence timeout watchdog (D) | Param accepted, not used | `backend/LOCAL_IMPLEMENTATION_PLAN.md §D` |
| Local TTS via Piper / macOS `say` + `get_tts_provider()` in `providers.py` (E) | 501 stub only | `backend/LOCAL_IMPLEMENTATION_PLAN.md §E` |
| Full RAG chat with Ollama tool calling (F) | Pass-through only | `backend/LOCAL_IMPLEMENTATION_PLAN.md §F` |
| SearXNG web search integration (G) | Not implemented | `backend/LOCAL_IMPLEMENTATION_PLAN.md §G` |
| Local audio backup to disk / S3 (H) | Not implemented | `backend/LOCAL_IMPLEMENTATION_PLAN.md §H` |
| Local persistent agent — AgentSession model + WebSocket (I) | Not implemented | `backend/LOCAL_IMPLEMENTATION_PLAN.md §I` |
| Custom personas — Persona model + CRUD router (J) | Not implemented | `backend/LOCAL_IMPLEMENTATION_PLAN.md §J` |
| External integrations — CalDAV calendar, IMAP email (K) | Not implemented | `backend/LOCAL_IMPLEMENTATION_PLAN.md §K` |
| Speaker diarization — post-session via pyannote (L) | Disabled (`ENABLE_DIARIZATION=false`) | `backend/LOCAL_IMPLEMENTATION_PLAN.md §L` |
| `main.py` full cloud-to-local cutover (§3.1–§3.13) | Not started | `MIGRATION_STATUS.md §3` |
| macOS Desktop `OMI_PYTHON_API_URL` setup | Not persisted | `PIN_LOCAL_GUIDE.md §4.2` — export in `~/.zshrc` |
| iOS Flutter app local URL (`API_BASE_URL` in `.dev.env`) | Requires custom build | `PIN_LOCAL_GUIDE.md §5` and `RUNBOOK.md §10.3` |
| iOS ATS exception for plain HTTP | Workaround only | `PIN_LOCAL_GUIDE.md §5.6` and `RUNBOOK.md §10.7` |
| Redis local instance | Not running | One-liner: `docker run -d --name omi-redis -p 6379:6379 redis` + set `REDIS_DB_HOST=localhost` in `.env` |
| Bootstrap admin account | Env vars commented out in `.env` | Uncomment `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` in `.env`, or use Admin UI "Register first account" flow |

---

## Items Without Existing Plans

The items below appear in the documentation as needed or unimplemented but have no technical plan written anywhere.

---

### PLAN-1 — HTTPS / TLS for LAN Deployment

**Why this matters:**
- iOS App Transport Security (ATS) blocks plain HTTP from the iOS app to the local backend. The current workaround is a `NSExceptionAllowsInsecureHTTPLoads` ATS exception — a per-IP override that breaks if the server IP changes.
- LAN connections between iOS/Desktop and the backend are unencrypted.
- Some iOS OS-level features (webhooks, certain audio APIs) require HTTPS.

**Recommended approach: Caddy reverse proxy** (handles TLS cert issuance automatically via its built-in CA)

```bash
# 1. Install
brew install caddy

# 2. Create Caddyfile in the project root
cat > Caddyfile <<'EOF'
omi.local {
  tls internal
  reverse_proxy localhost:8088
}
EOF

# 3. Add hostname to /etc/hosts (once)
echo "127.0.0.1 omi.local" | sudo tee -a /etc/hosts

# 4. Trust Caddy's local CA on this Mac (once; prompts for sudo)
caddy trust

# 5. Add Caddy's CA cert to iOS Simulator / device
#    On iOS device: email the cert from ~/.local/share/caddy/pki/authorities/local/root.crt
#    then install via Settings → General → VPN & Device Management

# 6. Start Caddy alongside the backend
caddy run --config Caddyfile &
```

After setup, update URLs:
- `OMI_PYTHON_API_URL=https://omi.local/` (Desktop)
- `API_BASE_URL=https://omi.local/` in `app/.dev.env` (iOS)
- Remove `NSExceptionAllowsInsecureHTTPLoads` from `ios/Runner/Info.plist` — no longer needed

**Alternative: ngrok** (useful when testing with a real iPhone without building from source)

```bash
brew install ngrok
ngrok http 8088
# Set the printed https URL as API_BASE_URL and OMI_PYTHON_API_URL
# Note: URL changes on each restart unless you have a paid reserved domain
```

**Files to update after implementing:**
- `RUNBOOK.md` — add HTTPS section under §3 or §10
- `PIN_LOCAL_GUIDE.md §5.6` — replace ATS exception workaround with Caddy / ngrok path
- `SETUP_FROM_SCRATCH.md` — add `brew install caddy` to optional prerequisites
- `start_local.sh` — optionally add `caddy run --config Caddyfile &` before uvicorn

---

### PLAN-2 — PostgreSQL End-to-End Validation

**Status:** `DB_PROVIDER=postgres` is wired in `providers.py` and `database/sql/db.py` reads `SQL_URL`. The SQLAlchemy ORM models are standard SQL (no SQLite-specific types). But this has never been tested end-to-end. `COMPLETED_UPDATES.md §15` lists it as unvalidated.

**Steps:**

```bash
# 1. Start a local Postgres container
docker run -d --name omi-postgres \
  -e POSTGRES_USER=omi -e POSTGRES_PASSWORD=omi -e POSTGRES_DB=omi \
  -p 5432:5432 postgres:16

# 2. Install the psycopg2 driver
pip install psycopg2-binary
# Add to requirements.txt: psycopg2-binary>=2.9  (comment out by default like other optional deps)

# 3. Configure
export DB_PROVIDER=postgres
export SQL_URL=postgresql+psycopg2://omi:omi@localhost:5432/omi

# 4. Start backend and run full smoke test
cd backend
conda activate omilocal
uvicorn main_local:app --port 8088
```

**What to validate:**
- `JSON` column type round-trips correctly (SQLAlchemy handles this via `JSONB` on Postgres)
- `DateTime(timezone=True)` stores and retrieves correctly (Postgres has native tz support)
- Concurrent write scenarios (run two simultaneous `POST /v1/conversations` requests)
- Cascade deletes still work (`DELETE /v1/admin/users/{id}` should remove all related rows)
- Schema auto-init (`init_db()` in `local_bootstrap.py`) creates tables correctly via `CREATE TABLE IF NOT EXISTS`

**Files to update after validating:**
- `COMPLETED_UPDATES.md §15` — move Postgres from "not validated" to done
- `requirements.txt` — add commented-out `psycopg2-binary>=2.9` line
- `RUNBOOK.md` — add a "Using PostgreSQL instead of SQLite" note under §3 configuration

---

### PLAN-3 — `/docs` Swagger UI Access Control

**Status:** Swagger UI at `/docs` (and `/redoc`, `/openapi.json`) is publicly accessible with no authentication. Acceptable on a trusted LAN; not acceptable if the backend is ever exposed to the internet or a shared network. `COMPLETED_UPDATES.md §15` notes this with no fix plan.

**Implementation (Option A — env-var key, no new dependencies):**

Add to `backend/main_local.py` after the CORS middleware:

```python
_DOCS_API_KEY = os.environ.get("DOCS_API_KEY", "")
if _DOCS_API_KEY:
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.middleware("http")
    async def _protect_docs(request: Request, call_next):
        if request.url.path in ("/docs", "/redoc", "/openapi.json"):
            key = (request.headers.get("x-docs-key")
                   or request.query_params.get("key", ""))
            if key != _DOCS_API_KEY:
                return JSONResponse(status_code=401,
                                    content={"detail": "docs require ?key=<DOCS_API_KEY>"})
        return await call_next(request)
```

Access docs at: `http://localhost:8088/docs?key=<your-key>`

**Config env var:** `DOCS_API_KEY` — if unset (default), `/docs` is publicly accessible (current behavior unchanged). If set, `/docs` requires the key.

**Files to update:**
- `backend/main_local.py` — add the middleware above
- `backend/.env.template` — add `DOCS_API_KEY=` (commented out, blank = disabled) with a note
- `RUNBOOK.md` — document the env var in §3.2

---

### PLAN-4 — Fix Documentation Inaccuracy in `LOCAL_CAPABILITIES.md`

**Issue:** `backend/LOCAL_CAPABILITIES.md` line 191, under the "Not Available" table, reads:

> "Goal tracking — Endpoint stubs exist in `routers_local/` but the LLM extraction pipeline is not wired."

This is **incorrect**. There are no goal stubs in `routers_local/` — no `goals.py` file exists and no `Goal` ORM model exists in `database/sql/models.py`. Both the router stubs and the LLM pipeline are entirely unimplemented.

**Fix:** Edit `backend/LOCAL_CAPABILITIES.md` line 191:

```diff
-| **Goal tracking** | Endpoint stubs exist in `routers_local/` but the LLM extraction pipeline is not wired. |
+| **Goal tracking** | Not implemented. No router or database model exists. Full implementation plan: `LOCAL_IMPLEMENTATION_PLAN.md §A.4`. |
```

---

## Implementation Priority

| # | Plan | Effort | Impact |
|---|------|--------|--------|
| 4 | Fix `LOCAL_CAPABILITIES.md` doc inaccuracy | Trivial (1 line) | Documentation accuracy |
| ~~3~~ | ~~`/docs` access control via `DOCS_API_KEY`~~ | ~~Small~~| ✅ Done |
| 1 | HTTPS / TLS via Caddy | Medium (setup + doc updates) | Unblocks iOS without ATS exceptions |
| 2 | PostgreSQL end-to-end validation | Small (test run + doc update) | Confirms multi-user / concurrent-write path |

Feature work (Groups A–L) priority is documented separately in `backend/LOCAL_IMPLEMENTATION_PLAN.md §Implementation Order Recommendation`.
