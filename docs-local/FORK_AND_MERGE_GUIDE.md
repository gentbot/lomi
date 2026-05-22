# Fork and Merge Guide — Connecting This Project to Upstream

This guide covers how to turn the current local project into a proper fork of
`BasedHardware/omi` that can receive upstream updates going forward.

**Upstream:** https://github.com/BasedHardware/omi

---

## Path Alignment Prerequisite

For either option below to work, **the git root must be at the `omi/` level** — the
same level as upstream's root. At that level, `backend/`, `app/`, `docs-local/`,
`pin_bridge/`, etc. all sit at the top of the tree, matching upstream exactly.

`code/` (the parent directory) is just a local filesystem container; it has no
upstream equivalent and its git history is not part of the fork.

**Check your git root:**

```bash
git rev-parse --show-toplevel
```

If it returns the `omi/` path (e.g., `.../code/omi`), you're ready for either option.

If it returns the `code/` path (e.g., `.../code`), establish a git root at `omi/`
before proceeding:

```bash
cd omi
git init
git add -A
git commit -m "feat: initial local build — all files"
```

This creates a clean history with all local additions already in place. The `code/`
parent directory keeps no git state of its own.

---

## Option A — Quick Path (Recommended)

Keep your current git history, push it to a GitHub fork, then do one
`--allow-unrelated-histories` merge to connect the two histories. Conflict count is
higher up front but manageable; afterward all future syncs are normal merges.

### Step 1 — Create the fork on GitHub

1. Go to https://github.com/BasedHardware/omi
2. Click **Fork** → choose your GitHub account → **Create fork**
3. Your fork URL will be `https://github.com/<your-username>/omi`

Do NOT clone the fork yet. Your local project already exists.

### Step 2 — Add remotes

```bash
# Point origin at your new GitHub fork
git remote add origin https://github.com/<your-username>/omi.git

# Point upstream at BasedHardware's repo (read-only, never push here)
git remote add upstream https://github.com/BasedHardware/omi.git

# Verify
git remote -v
# origin    https://github.com/<your-username>/omi.git  (fetch)
# origin    https://github.com/<your-username>/omi.git  (push)
# upstream  https://github.com/BasedHardware/omi.git    (fetch)
# upstream  https://github.com/BasedHardware/omi.git    (push)
```

### Step 3 — Push your current project to the fork

```bash
git push -u origin main
```

If the fork's default branch is already initialised and you get a non-fast-forward
error (the fork created a default README), force the first push:

```bash
git push -u origin main --force
```

### Step 4 — Fetch upstream and do the initial merge

```bash
# Download all upstream history (no files change yet)
git fetch upstream

# Preview what you're about to merge
git log upstream/main --oneline | head -20

# First merge — --allow-unrelated-histories is only needed this once
git merge upstream/main --allow-unrelated-histories -m "chore: merge upstream BasedHardware/omi history"
```

This opens a conflict resolution session. See the **Conflict Zones** section below for
exactly which files will conflict and how to resolve each one.

### Step 5 — Push the merged result

```bash
git push origin main
```

After this, the two histories are permanently connected. All future upstream syncs are
normal merges with no special flags needed.

---

## Option B — Clean History (More Work)

Fork `BasedHardware/omi` on GitHub, clone it fresh, then copy all local additions
on top. This gives a clean public commit history at the cost of manually re-applying
every local change.

```bash
# 1. Fork on GitHub (same as Option A Step 1)

# 2. Clone your fork fresh into a new directory
git clone https://github.com/<your-username>/omi.git omi-fork
cd omi-fork

# 3. Add upstream
git remote add upstream https://github.com/BasedHardware/omi.git
git fetch upstream
git merge upstream/main   # trivial — fork IS upstream at this point

# 4. Copy local additions (all paths relative to omi/ root)
OLD_REPO=/path/to/current/omi   # adjust to your machine

cp -r "$OLD_REPO/docs-local"                     ./docs-local
cp -r "$OLD_REPO/pin_bridge"                     ./pin_bridge
cp    "$OLD_REPO/scripts/sync-local-ip.sh"       ./scripts/sync-local-ip.sh
cp    "$OLD_REPO/setup-clients.sh"               ./setup-clients.sh
cp    "$OLD_REPO/README-LOCAL.md"                ./README-LOCAL.md

cp -r "$OLD_REPO/backend/routers_local"              ./backend/routers_local
cp -r "$OLD_REPO/backend/database/sql"               ./backend/database/sql
cp -r "$OLD_REPO/backend/admin_local"                ./backend/admin_local
cp    "$OLD_REPO/backend/main_local.py"              ./backend/main_local.py
cp    "$OLD_REPO/backend/start_local.sh"             ./backend/start_local.sh
cp    "$OLD_REPO/backend/local_bootstrap.py"         ./backend/local_bootstrap.py
cp    "$OLD_REPO/backend/env.local.template"         ./backend/env.local.template
cp    "$OLD_REPO/backend/.env.local.example"         ./backend/.env.local.example
cp    "$OLD_REPO/backend/.env.reference"             ./backend/.env.reference
cp    "$OLD_REPO/backend/requirements-local.txt"     ./backend/requirements-local.txt
cp    "$OLD_REPO/backend/PIN_LOCAL_AUDIO_SETUP.md"   ./backend/PIN_LOCAL_AUDIO_SETUP.md
cp    "$OLD_REPO/backend/feature_flags.py"           ./backend/feature_flags.py
cp    "$OLD_REPO/backend/providers.py"               ./backend/providers.py

# vector_db.py becomes a dispatcher — overwrites upstream's Pinecone-only version
cp    "$OLD_REPO/backend/database/vector_db.py"          ./backend/database/vector_db.py
cp    "$OLD_REPO/backend/database/vector_db_pinecone.py" ./backend/database/vector_db_pinecone.py
cp    "$OLD_REPO/backend/database/vector_db_qdrant.py"   ./backend/database/vector_db_qdrant.py
cp    "$OLD_REPO/backend/database/vector_db_base.py"     ./backend/database/vector_db_base.py

cp    "$OLD_REPO/backend/utils/llm/post_process.py"  ./backend/utils/llm/post_process.py
cp    "$OLD_REPO/backend/utils/llm/router.py"        ./backend/utils/llm/router.py
# Copy the entire embeddings/ directory — includes local_embeddings.py, openai_embeddings.py,
# router.py (provider dispatcher), and __init__.py. router.py overwrites upstream if present.
cp -r "$OLD_REPO/backend/utils/embeddings"           ./backend/utils/embeddings
# Local STT provider implementations (Whisper streaming + pre-recorded) and VAD
cp -r "$OLD_REPO/backend/utils/stt/providers"        ./backend/utils/stt/providers
cp    "$OLD_REPO/backend/utils/stt/local_vad.py"     ./backend/utils/stt/local_vad.py
# WebSocket event broadcaster (replaces Pusher when EVENT_PROVIDER=websocket)
cp -r "$OLD_REPO/backend/events"                     ./backend/events

cp    "$OLD_REPO/backend/.gitignore"                 ./backend/.gitignore

cp    "$OLD_REPO/backend/scripts/local_smoke.py"    ./backend/scripts/local_smoke.py
cp    "$OLD_REPO/backend/auth/local_auth.py"        ./backend/auth/local_auth.py
cp    "$OLD_REPO/backend/auth/router_dep.py"        ./backend/auth/router_dep.py

cp -r "$OLD_REPO/app/lib/local"                  ./app/lib/local
cp    "$OLD_REPO/app/.dev.env.example"           ./app/.dev.env.example

# Re-apply edits to shared upstream files (see Conflict Zones below):
#   app/lib/main.dart
#   app/lib/providers/auth_provider.dart
#   app/lib/services/auth_service.dart
#   app/lib/backend/http/shared.dart
#   app/lib/env/env.dart
#   app/lib/env/prod_env.dart
#   app/lib/env/dev_env.dart
#   app/lib/pages/onboarding/auth.dart
#   app/ios/Runner/Info.plist
#   backend/.env.template

# 5. Commit and push
git add -A
git commit -m "feat: add local-only backend, pin bridge, and desktop support"
git push -u origin main
```

Option B is only worth doing if you want a clean public commit history. For private
or personal use, Option A is equivalent in functionality and much less work.

---

## Conflict Zones — What Will Need Manual Resolution

These are the upstream-tracked files that were modified locally. The detailed audit
is in `docs-local/UPSTREAM_SYNC_GUIDE.md`; this table gives the fast reference.

### High conflict risk (resolve carefully)

| File | What you changed | Upstream change frequency |
|------|-----------------|--------------------------|
| `app/lib/main.dart` | Added local JWT session restore on startup | Medium — top-level init changes with new features |
| `app/lib/providers/auth_provider.dart` | Added local auth fallback | Medium — auth flow changes |
| `app/lib/services/auth_service.dart` | Added local auth service reference | Medium |
| `app/lib/backend/http/shared.dart` | Added local JWT bypass in shared HTTP client | Medium — auth/HTTP changes |
| `app/lib/pages/onboarding/auth.dart` | Added local email/password sign-in block | Medium — onboarding changes with new features |
| `app/ios/Runner/Info.plist` | Added `NSAllowsLocalNetworking` ATS key | Low — plist rarely touched |
| `backend/requirements.txt` | No local additions — tracks upstream directly | High — packages added/removed regularly |

**For `main.dart`, `auth_provider.dart`, `auth_service.dart`:** Local changes are
wrapped in `// ── LOCAL ONLY ──` markers which makes them easy to identify and
re-apply. During a conflict, keep both sides (upstream changes + LOCAL ONLY block).

**For `requirements.txt`:** All local-only packages live in `requirements-local.txt`.
`requirements.txt` tracks upstream exactly — conflicts here are upstream-vs-upstream
only. Accept upstream's version. See the **Python Dependencies** section below for
the full breakdown.

### Low conflict risk (usually auto-merges)

| File | What you changed | Why it's low risk |
|------|-----------------|------------------|
| `backend/.env.template` | Added `ENCRYPTION_SECRET` warning comment | Upstream adds new keys but rarely changes existing comment lines |
| `app/lib/env/env.dart` | Added `localAuthEnabled` field | Upstream rarely restructures this env file |
| `app/lib/env/prod_env.dart` | Added `localAuthEnabled = false` | Same as above |
| `app/lib/env/dev_env.dart` | Added `localAuthEnabled` field | Same as above |

**For `.env.template`:** The only local change is a comment added above
`ENCRYPTION_SECRET`. When upstream adds new keys, accept the upstream additions and
keep the comment. All local provider selection (`STT_PROVIDER=local`, etc.) lives
entirely in `env.local.template` and does not appear in this file.

**For `admin/index.html`:** `main_local.py` serves `admin_local/index.html` instead.
You can accept upstream's version wholesale — no local edits to preserve.

### No conflict possible (purely additive, unknown to upstream)

Everything in these paths is safe by definition — upstream has no equivalent:

- `docs-local/` — all local documentation
- `pin_bridge/` — BLE bridge, entire directory
- `scripts/sync-local-ip.sh` — new file alongside existing upstream scripts
- `setup-clients.sh` — one-command client config setup
- `README-LOCAL.md` — local README
- `backend/routers_local/` — entire directory
- `backend/database/sql/` — SQLite persistence layer, entire directory
- `backend/database/vector_db_qdrant.py` — Qdrant vector store implementation
- `backend/database/vector_db_pinecone.py` — upstream's `vector_db.py` extracted to its own module
- `backend/database/vector_db_base.py` — shared vector DB base contract
- `backend/admin_local/` — local admin UI (distinct from upstream `admin/`)
- `backend/main_local.py` — local entry point
- `backend/start_local.sh` — local boot script
- `backend/local_bootstrap.py` — local startup helper (Qdrant health probe, SQLite init)
- `backend/feature_flags.py` — local feature gating
- `backend/providers.py` — local provider resolver
- `backend/utils/llm/post_process.py` — local conversation post-processing pipeline
- `backend/utils/llm/router.py` — LLM provider dispatcher (Ollama/OpenAI router)
- `backend/utils/stt/providers/` — local STT provider implementations (Whisper streaming + pre-recorded)
- `backend/utils/stt/local_vad.py` — local VAD implementation
- `backend/events/` — WebSocket event broadcaster; replaces Pusher when `EVENT_PROVIDER=websocket`
- `backend/utils/embeddings/local_embeddings.py` — sentence-transformers embeddings implementation
- `backend/scripts/local_smoke.py` — end-to-end smoke test for the local provider stack
- `backend/env.local.template` — local provider vars
- `backend/.env.local.example` — local env example
- `backend/.env.reference` — documented env reference
- `backend/requirements-local.txt` — local Python deps
- `backend/PIN_LOCAL_AUDIO_SETUP.md`
- `backend/auth/local_auth.py`, `backend/auth/router_dep.py`
- `backend/.gitignore` — ignores `omi_local.db`, `omi_local.db-shm/wal`, `env_backups/`
- `backend/utils/embeddings/` — entire directory (local dispatcher + local and OpenAI adapters)
- `app/lib/local/` — all local auth Flutter files
- `app/.dev.env.example`

Two files replace their upstream equivalents wholesale. For **Option B** they are
simply overwritten by the `cp` commands above. For **Option A** they will appear as
merge conflicts — keep the local version in both cases:

- `backend/database/vector_db.py` — upstream has Pinecone only; keep our Qdrant/Pinecone dispatcher
- `backend/utils/embeddings/router.py` — keep our provider dispatcher (if upstream has this file)

---

## Ongoing Sync Workflow (After Initial Setup)

Once the fork exists and the histories are connected, syncing upstream is
straightforward:

```bash
# Fetch latest upstream changes
git fetch upstream

# Preview what changed since your last sync
git log upstream/main ^main --oneline

# Merge upstream into your main branch
git merge upstream/main

# Resolve any conflicts (see zones above), then:
git push origin main
```

**Recommended cadence:** Monthly, or when upstream ships a significant feature or
security fix. Check upstream releases at:
https://github.com/BasedHardware/omi/releases

**Before every sync:**
1. Make sure your working tree is clean (`git status`)
2. Run the local backend to confirm it works before the merge
3. After the merge, run it again to confirm nothing broke

---

## Conflict Surface Status

The following measures are already in place to minimise merge conflicts on every
future upstream sync. No further action needed — this is for reference.

| Measure | Status | How it helps |
|---------|--------|-------------|
| `env.local.template` created | Done | All local provider vars live here. `.env.template` tracks upstream exactly. |
| `admin_local/index.html` serves the local admin UI | Done | `main_local.py` mounts `admin_local/` first. `admin/index.html` accepts upstream wholesale. |
| `requirements-local.txt` for local deps | Done | All local-only packages are in `requirements-local.txt`. `requirements.txt` tracks upstream exactly — `qdrant-client` (previously added locally) has been removed. |
| `backend/.gitignore` created | Done | Ignores `omi_local.db`, WAL files, and `env_backups/` at the fork level — not dependent on the outer `code/.gitignore`. |
| `// ── LOCAL ONLY ──` markers in Flutter files | Done | Local auth additions are clearly delimited for conflict resolution. |

---

## Checking `.gitignore` Health Before Pushing

`backend/.gitignore` must be present before pushing — it prevents the runtime
database and env backups from ever being committed. Verify it exists:

```bash
cat backend/.gitignore
# Expected: omi_local.db, omi_local.db-shm, omi_local.db-wal, env_backups/
```

Then verify nothing sensitive is already tracked:

```bash
# Should show nothing sensitive
git ls-files | grep -E '\.env$|\.db$|omi_local\.db|env_backups|\.env\.local'
```

Expected output: nothing. The only env-related tracked files should be
`.env.template`, `env.local.template`, and `.env.local.example` (templates, not
files with real values). The `.db` files and `env_backups/` should not appear.

If they do appear:

```bash
git rm --cached backend/omi_local.db
git rm --cached -r backend/env_backups/
# Add the paths to .gitignore if not already there
git commit -m "chore: remove runtime artifacts from tracking"
```

---

## Python Dependencies

The local provider stack replaces five cloud services with local packages. All of
them live in `requirements-local.txt` and are installed on top of `requirements.txt`:

```bash
pip install -r requirements.txt -r requirements-local.txt
```

Full provider mapping is in `docs-local/CLOUD_DEPENDENCY_AUDIT.md §1`. The
packages that correspond to each swap:

| Cloud service | Local replacement | Package in requirements-local.txt | Provider switch |
|---|---|---|---|
| Deepgram (STT) | faster-whisper | `faster-whisper>=1.0,<2` | `STT_PROVIDER=local` |
| OpenAI embeddings | sentence-transformers | `sentence-transformers>=2.7,<3` | `EMBEDDINGS_PROVIDER=local` |
| Pinecone (vector DB) | Qdrant (Docker) | `qdrant-client>=1.9,<2` | `VECTOR_DB_PROVIDER=qdrant` |
| Google Firestore | SQLite via SQLAlchemy | `SQLAlchemy>=2.0,<3` | `DB_PROVIDER=sqlite` |
| Firebase Auth | Local JWT (PyJWT) | `PyJWT>=2.8,<3` | `AUTH_PROVIDER=local` |

`opuslib` (used by the pin bridge and listen router for Opus decoding) is an upstream
dep already pinned in `requirements.txt` — no local addition needed.

### Packages in requirements-local.txt that are already in requirements.txt

The following entries are redundant — `requirements.txt` pins them already. They are
kept in `requirements-local.txt` for self-documentation so the local stack's deps are
visible in one place, and as a safety net if a future upstream sync removes them.

| Package | requirements.txt pin | requirements-local.txt spec |
|---|---|---|
| `SQLAlchemy` | `2.0.32` | `>=2.0,<3` |
| `PyJWT` | `2.12.0` | `>=2.8,<3` |
| `numpy` | `1.26.4` | `>=1.26,<2` (torch ABI compat) |
| `httpx` | `0.28.0` | `>=0.27` |

### qdrant-client was removed from requirements.txt

`qdrant-client==1.11.0` was previously added directly to `requirements.txt` — only
local-only code uses it (`providers.py`, `vector_db_qdrant.py`, `local_bootstrap.py`,
`post_process.py`). It has been removed from `requirements.txt` so that file tracks
upstream exactly. It remains in `requirements-local.txt` as intended.

### Optional dependency

`torch` for Silero VAD is commented out in `requirements-local.txt`. Omit it to skip
the ~2 GB install and use the default RMS-energy VAD instead.

---

## Quick Reference

| Task | Command |
|------|---------|
| Check git root | `git rev-parse --show-toplevel` |
| Add fork remote | `git remote add origin https://github.com/<you>/omi.git` |
| Add upstream remote | `git remote add upstream https://github.com/BasedHardware/omi.git` |
| Initial push to fork | `git push -u origin main` |
| First merge (unrelated) | `git merge upstream/main --allow-unrelated-histories` |
| Normal sync | `git fetch upstream && git merge upstream/main` |
| Preview incoming changes | `git log upstream/main ^main --oneline` |
| See conflict surface | `git diff main upstream/main --stat` |
| Abort a bad merge | `git merge --abort` |
