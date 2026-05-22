# Upstream Sync Guide — Keeping Your OMI Fork Up to Date

**Upstream project:** https://github.com/BasedHardware/omi/

---

## Part 1 — Core Concepts (Plain English)

### What is a fork?

A fork is your own independent copy of someone else's project. You make changes to it
freely. The original project ("upstream") keeps evolving independently. The challenge is
periodically absorbing useful changes from upstream without overwriting your own work.

### What is an upstream remote?

Git can track multiple copies of a repository at once, each called a "remote." By default
you have one remote called `origin` — that's your own copy. An "upstream remote" is a
second pointer added to the original BasedHardware/omi repository. You never push to it,
you only pull from it. Your local machine can see both, compare them, and cherry-pick
what you want.

### The mental model

```
BasedHardware/omi  (upstream) — they keep shipping features, bug fixes
        ↓  you periodically pull from here
your fork/local    (origin)   — your local-only build lives here
```

### Merging vs rebasing (simplified)

- **Merge** — takes upstream changes and combines them with yours, creating a "merge
  commit." Safe, preserves history.
- **Rebase** — replays your commits on top of the latest upstream code, as if you had
  written them after the upstream changes. Cleaner history but riskier if the base code
  changed significantly.

For a fork this different from upstream, **merging** is the safer choice.

---

## Part 2 — Full Audit of Changes Made to This Project

This section catalogs every modification made to create the local-only build. Each item
is rated for conflict risk when pulling upstream updates.

Risk scale:
- **GREEN** — no conflict possible (new files/directories upstream doesn't have)
- **YELLOW** — possible conflict (shared file that both sides may change)
- **RED** — high conflict (frequently updated file with substantial in-place edits)

---

### 2.1 Backend (`backend/`)

#### GREEN — Purely additive, no upstream equivalent

New files and directories that do not exist in the upstream repository. Upstream can
never conflict with them.

| Path | What it is |
|------|-----------|
| `main_local.py` | Local-only FastAPI entry point |
| `local_bootstrap.py` | Startup initialiser (SQLite schema, Qdrant setup) |
| `start_local.sh` | Full-stack launcher (Qdrant + Ollama + FastAPI) |
| `stop_local.sh` | Counterpart stopper |
| `env.local.template` | Local-only env vars (provider selection, JWT, SQLite path) |
| `.env.local.example` | Fully-filled example for reference |
| `.env.reference` | Every env variable documented with description and default |
| `requirements-local.txt` | Local-only Python dependencies |
| `routers_local/` | 21 local-only routers (entirely separate from `routers/`) |
| `database/sql/` | SQLite persistence layer (models, engine, repository) |
| `database/vector_db_qdrant.py` | Qdrant vector storage implementation |
| `database/vector_db_base.py` | Abstract base for vector DB providers |
| `providers.py` | Runtime provider resolver (which STT/LLM/DB backend is active) |
| `feature_flags.py` | Local feature gating |
| `auth/local_auth.py` | Local JWT/token verification (no Firebase) |
| `auth/router_dep.py` | FastAPI dependency that calls `local_auth` |
| `admin_local/` | Local admin UI (separate from upstream's `admin/`) |
| `utils/llm/post_process.py` | LLM post-processing utilities |
| `PIN_LOCAL_AUDIO_SETUP.md` | Pin audio setup guide |

---

#### YELLOW — Shared files with minor additions

These files exist in the upstream repository and were lightly extended. Conflicts are
possible but manageable because the local additions are small and clearly marked.

| Path | What changed locally | Conflict exposure |
|------|----------------------|-------------------|
| `events/router.py` | Routes to local WebSocket manager or upstream broadcaster | Low — interface unlikely to change |

**Note:** `database/vector_db_qdrant.py`, `providers.py`, and `feature_flags.py` were
previously classified as YELLOW but are entirely new files (marked
`# ── LOCAL ONLY —`). They are GREEN.

---

#### Previously RED — Now resolved

These three files were the highest-conflict items and have been refactored to eliminate
the conflict surface:

| File | Previous risk | What was done | Current risk |
|------|--------------|---------------|-------------|
| `admin/index.html` | RED (local UI additions) | `admin_local/index.html` created; `main_local.py` serves it instead. `admin/index.html` now tracks upstream cleanly. | GREEN |
| `.env.template` | RED (local provider vars) | All local provider vars moved to `env.local.template`. Only a warning comment above `ENCRYPTION_SECRET` remains. | YELLOW/low |
| `requirements.txt` | YELLOW (comment block) | Comment block removed. Local deps are in `requirements-local.txt`. | GREEN |

---

### 2.2 App (`app/`)

#### GREEN — Purely additive

| Path | What it is |
|------|-----------|
| `lib/local/` | All local auth Flutter files |
| `.dev.env.example` | Local dev env example |

#### YELLOW — Shared files with local additions

| Path | What changed locally | Conflict exposure |
|------|----------------------|-------------------|
| `lib/main.dart` | Local JWT session restore on startup; `// ── LOCAL ONLY ──` markers | Medium — top-level init changes with new features |
| `lib/providers/auth_provider.dart` | Local auth fallback; `// ── LOCAL ONLY ──` markers | Medium — auth flow changes |
| `lib/services/auth_service.dart` | Local auth service reference; `// ── LOCAL ONLY ──` markers | Medium |
| `lib/env/env.dart` | `localAuthEnabled` field added | Low — rarely restructured |
| `ios/Runner/Info.plist` | `NSAllowsLocalNetworking` ATS key added | Low — plist rarely touched |

**Resolving conflicts in these files:** Look for `// ── LOCAL ONLY ──` markers. During a
merge conflict, keep both sides — upstream changes plus your LOCAL ONLY block.

---

### 2.3 Desktop App (`desktop/`)

#### GREEN — New local-only files

| Path | What it is |
|------|-----------|
| `run-local.sh` | Local wrapper script (sets `OMI_ADHOC_SIGN`, `_LOCAL_HOST`, calls `run.sh`) |
| `scripts/patch-for-local-build.sh` | One-time compiler patch for CommandLineTools-only machines |
| `.env.app` | Local machine config (gitignored) |

#### YELLOW — `run.sh`

`run.sh` was previously a RED item (hardcoded LAN IP throughout, Sparkle path hacked,
ContentsquareCore removed, `#Preview` lines stripped). All these issues are now resolved:

- **LAN IP hardcoding:** `run.sh` now reads `_LOCAL_HOST="${LOCAL_MACHINE_HOST:-localhost}"`.
  All seven previous hardcoded-IP occurrences use this variable.
- **Compiler patches:** Moved to `scripts/patch-for-local-build.sh` (run once by user).
- **Ad-hoc signing:** `run-local.sh` sets `OMI_ADHOC_SIGN` before calling `run.sh`.

`run.sh` now has a small amount of local-mode logic (the `_LOCAL_HOST` variable, `--yolo`
mode reading it). Upstream occasionally changes `run.sh`; these small additions will
likely conflict but are easy to re-apply. **Current risk: YELLOW/low.**

---

### 2.4 Pin Bridge (`pin_bridge/`)

Not part of the upstream `omi/` directory — lives at `pin_bridge/` at the project root.

#### GREEN — New files

| Path | What it is |
|------|-----------|
| `pin_bridge/requirements-thin.txt` | Dependencies without `opuslib` |
| `pin_bridge/requirements-full.txt` | Dependencies with `opuslib` (local decoding) |
| `pin_bridge/pin_offline_drain.py` | Offline audio drain module |

#### YELLOW — `pin_bridge/pin_bridge.py`

Significant feature additions:
- `--thin` mode: sends raw Opus frames instead of decoded PCM
- Offline drain support: replays stored frames on reconnect

`pin_bridge/requirements.txt` has no local comment block — it is clean.

---

### 2.5 Project Root and Docs

All files added at the project root or inside `docs-local/` are purely additive.
Upstream places its docs inside `omi/`; none of these paths conflict.

| Path | Status |
|------|--------|
| `docs-local/` | All local documentation — GREEN |
| `setup-clients.sh` | One-command client setup script — GREEN |
| `README-LOCAL.md` | Local-build README — GREEN |
| `scripts/sync-local-ip.sh` | LAN IP sync helper — GREEN |

**Note:** All documentation files previously listed here as "project root" files have
been moved into `docs-local/`.

---

## Part 3 — Conflict Surface Reduction Status

All high-risk items have been addressed. No further refactoring is needed before
connecting to upstream.

| Item | Status | Outcome |
|------|--------|---------|
| `admin/index-local.html` separation | **Done** | `admin_local/` created; `main_local.py` mounts it. `admin/index.html` tracks upstream. |
| `env.local.template` split | **Done** | All local provider vars in `env.local.template`. `.env.template` is near-upstream. |
| `run-local.sh` wrapper | **Done** | `run-local.sh` + `scripts/patch-for-local-build.sh` exist. `run.sh` is close to upstream. |
| `requirements.txt` clean | **Done** | No local comment block. `requirements-local.txt` handles local deps. |
| `// ── LOCAL ONLY ──` markers | **Done** | All Flutter app additions are wrapped; `providers.py`, `feature_flags.py`, `vector_db_qdrant.py` are entirely new LOCAL ONLY files. |
| `omi_local.db` in `.gitignore` | **Done** | Runtime database never committed. |
| `env_backups/` in `.gitignore` | **Done** | Backup env files never committed. |
| Hardcoded LAN IPs | **Done** | All 20 instances replaced with `_LOCAL_HOST` / `LOCAL_MACHINE_HOST` variables. See `HARDCODED_IP_AUDIT.md`. |

---

## Part 4 — How to Set Up the Upstream Connection

See `FORK_AND_MERGE_GUIDE.md` for full step-by-step instructions. Quick summary:

```bash
# Add the upstream repository as a second remote
git remote add upstream https://github.com/BasedHardware/omi.git

# Download all upstream history
git fetch upstream

# See what differs between your main branch and theirs
git diff main upstream/main --stat
```

With the conflict surface reduced, only intentional local files should appear in the diff
for the YELLOW items. The GREEN files will not appear at all.

---

## Part 5 — Ongoing Sync Workflow

When you want to pull in upstream improvements:

```bash
# Fetch latest upstream changes
git fetch upstream

# See what changed since your last sync
git log upstream/main ^main --oneline

# Option A — Merge everything (safer, creates a merge commit)
git merge upstream/main

# Option B — Cherry-pick a specific commit you want
git cherry-pick <commit-hash>
```

After merging, resolve any conflicts. With the refactoring done:
- **GREEN files** merge automatically with no conflict
- **YELLOW files** show conflicts only in the `# ── LOCAL ONLY ──` or `_LOCAL_HOST`
  blocks, which are easy to keep
- The former **RED files** (`admin/index.html`, `.env.template`, `requirements.txt`) are
  now clean and accept upstream changes without conflict

---

## Part 6 — Files That Should Be in `.gitignore`

These local files should never be committed to a fork:

```
# Local database
backend/omi_local.db
backend/omi_local.db-shm
backend/omi_local.db-wal

# Local environment
backend/.env
backend/env_backups/

# Python cache
**/__pycache__/
**/*.pyc

# macOS artifacts
**/.DS_Store

# Scratch directories
backend/_temp/
backend/_segments/
backend/_speech_profiles/
backend/_samples/
```

All of these are already covered by `.gitignore`.

---

## Summary Table

| Area | Risk | Notes |
|------|------|-------|
| `routers_local/` | GREEN | Tracks independently |
| `database/sql/` | GREEN | Tracks independently |
| `database/vector_db_qdrant.py` | GREEN | New LOCAL ONLY file |
| `providers.py` | GREEN | New LOCAL ONLY file |
| `feature_flags.py` | GREEN | New LOCAL ONLY file |
| `admin_local/` | GREEN | Separate from `admin/`; tracks independently |
| `main_local.py` | GREEN | Tracks independently |
| `auth/local_auth.py` | GREEN | Tracks independently |
| `admin/index.html` | GREEN | No local edits; tracks upstream |
| `.env.template` | YELLOW/low | One comment line; minimal conflict surface |
| `requirements.txt` | GREEN | No local additions |
| `run.sh` | YELLOW/low | `_LOCAL_HOST` variable; easy to re-apply |
| `pin_bridge.py` | YELLOW | Local feature additions; consider upstream PR |
| `lib/main.dart` | YELLOW | `LOCAL ONLY` markers make conflicts easy to resolve |
| `lib/providers/auth_provider.dart` | YELLOW | `LOCAL ONLY` markers |
| `events/router.py` | YELLOW/low | Small addition |
| `Root .md files / docs-local/` | GREEN | Tracks independently |
