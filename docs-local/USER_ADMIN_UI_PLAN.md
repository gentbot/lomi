# User Management Web UI — Implementation Plan

A lightweight, dependency-free browser-based admin panel for managing local backend users.
No frameworks. No build step. Basic HTML + CSS + JS served directly from the project.

---

## 1. Current API surface — what already exists

| Endpoint | Method | Auth | Input | Output | Notes |
|----------|--------|------|-------|--------|-------|
| `/v1/auth/register` | POST | none | `{email, password}` | `{id, email}` | 400 if email taken |
| `/v1/auth/login` | POST | none | `{email, password}` | `{access_token, token_type}` | 401 if wrong creds |
| `/v1/auth/me` | GET | Bearer | — | `{user_id}` | Returns UUID or `fb_<uid>` |

That is the **complete** existing user management surface. Everything else that the UI needs
(list users, update, delete, change password) does not exist yet and must be added.

---

## 2. Backend gaps and what must be added

### 2.1 New repository functions (`database/sql/repository.py`)

Four functions to add, each using `session_scope()`:

| Function | Signature | What it does |
|----------|-----------|--------------|
| `list_all_users` | `() → List[Dict]` | SELECT id, email, display_name, created_at, updated_at ORDER BY created_at DESC |
| `update_user` | `(user_id, *, email=None, display_name=None) → Optional[Dict]` | UPDATE users SET …; return None if user not found; raise IntegrityError if email already taken |
| `update_user_password` | `(user_id, new_password_hash) → bool` | UPDATE users SET password_hash=…; return False if user not found |
| `delete_user` | `(user_id) → bool` | DELETE FROM users WHERE id=…; SQLAlchemy cascade deletes conversations, memories, action_items automatically (cascade="all, delete-orphan" is already set on all relationships) |

None of these require schema changes — the User model already has `display_name`, `email`, `password_hash`, `created_at`.

### 2.2 New admin router (`routers_local/admin.py`)

New file, prefix `/v1/admin`, all endpoints require `Depends(get_current_user_id_local)`.

There is no RBAC system. Any valid JWT grants admin access — acceptable for a local-only setup where the operator controls the machine. Document this clearly in the UI.

| Method | Path | Request body | Response | Error cases |
|--------|------|--------------|----------|-------------|
| GET | `/v1/admin/users` | — | `[{id, email, display_name, created_at}]` | 401 if not authed |
| GET | `/v1/admin/users/{user_id}` | — | `{id, email, display_name, created_at, updated_at}` | 404 if not found |
| PATCH | `/v1/admin/users/{user_id}` | `{email?, display_name?}` | updated user dict | 404, 400 (email taken) |
| POST | `/v1/admin/users/{user_id}/password` | `{new_password}` | `{ok: true}` | 404, 400 (too short) |
| DELETE | `/v1/admin/users/{user_id}` | — | `{ok: true}` | 404, 400 (self-delete) |

**Self-delete guard:** `DELETE` must check `user_id == current_user_id` and return HTTP 400 with `{"detail": "Cannot delete your own account while logged in."}`.

**Password validation:** minimum 8 characters enforced in the endpoint (not only client-side).

### 2.3 Change-own-password endpoint (extend `routers_local/auth.py`)

| Method | Path | Request body | Response | Error cases |
|--------|------|--------------|----------|-------------|
| POST | `/v1/auth/change-password` | `{current_password, new_password}` | `{ok: true}` | 401 wrong current, 400 too short |

Requires `Depends(get_current_user_id_local)`. Must verify current_password with `_verify_password()` before updating. Returns 401 (not 400) when current password is wrong — same status as `/login` for consistency.

### 2.4 Register `admin` router in `main_local.py`

```python
from routers_local import admin as local_admin_router
app.include_router(local_admin_router.router)
```

### 2.5 Serve the static admin file from FastAPI

Add to `main_local.py` after all router registrations:

```python
from fastapi.staticfiles import StaticFiles
import os
_admin_dir = os.path.join(os.path.dirname(__file__), "admin")
if os.path.isdir(_admin_dir):
    app.mount("/admin", StaticFiles(directory=_admin_dir, html=True), name="admin")
```

`aiofiles` is already a transitive dependency so `StaticFiles` works without new installs.
The admin UI is then available at `http://127.0.0.1:8088/admin/`.

> **Alternative (no FastAPI change):** Run `python -m http.server 8089 --directory backend/admin`
> from the backend directory. The JS calls `localhost:8088`; CORS is already `allow_origins=["*"]`.
> This works but requires a second terminal. The static-mount approach is preferred.

---

## 3. Frontend file structure

```
backend/
  admin/
    index.html      ← single file; all CSS and JS are inline (no external deps)
  routers_local/
    admin.py        ← new router (to be written)
  main_local.py     ← add admin router + static mount
  database/sql/
    repository.py   ← add 4 new functions
```

`index.html` is a single self-contained file. No external stylesheet links, no `<script src>` tags
pointing outside localhost. The file is ~400–600 lines of plain HTML/CSS/JS.

---

## 4. UI screens and component map

The page has **one URL** (`/admin/`). Views are `<section>` elements toggled with `display: none /
block`. There is no client-side router — JS simply calls `showView(id)`.

```
index.html
├── #notification-bar        ← global error/success banner (fixed top)
├── #view-login              ← shown when no token in sessionStorage
│   ├── email input
│   ├── password input
│   ├── "Sign In" button
│   └── "Register first account" link → #view-register
├── #view-register           ← create first account / accessible via link
│   ├── email input
│   ├── password input
│   ├── confirm password input
│   ├── "Create Account" button
│   └── "Back to Sign In" link
├── #view-users              ← main view, shown when token exists
│   ├── header bar
│   │   ├── "Omi User Admin" title
│   │   ├── "New User" button → opens #modal-create
│   │   ├── "Change My Password" button → opens #modal-change-pw
│   │   └── "Sign Out" button → clears token, shows #view-login
│   ├── #user-table          ← <table> populated by JS
│   │   ├── columns: Email | Display Name | ID (truncated) | Created | Actions
│   │   └── per-row actions: "Edit" | "Reset PW" | "Delete"
│   └── #empty-state         ← shown when table has 0 rows
├── #modal-create            ← create new user
│   ├── email, password, confirm password
│   └── buttons: "Create" | "Cancel"
├── #modal-edit              ← edit email / display name
│   ├── email, display_name
│   └── buttons: "Save" | "Cancel"
├── #modal-reset-pw          ← admin set new password for any user
│   ├── new password, confirm new password
│   └── buttons: "Reset Password" | "Cancel"
├── #modal-change-pw         ← change own password
│   ├── current password, new password, confirm new password
│   └── buttons: "Change Password" | "Cancel"
└── #modal-confirm-delete    ← delete confirmation
    ├── "Delete {email}? This also deletes all their conversations, memories, and action items."
    └── buttons: "Delete" (red) | "Cancel"
```

---

## 5. State management

No framework. State lives in three JS variables:

```js
let token = sessionStorage.getItem('omi_admin_token') || null;
let currentUserId = sessionStorage.getItem('omi_admin_uid') || null;
let editingUserId = null;  // which user the open modal is targeting
```

On page load:
1. If `token` is set → call `GET /v1/auth/me` to verify it is still valid.
   - 200 → show `#view-users`, load user list.
   - 401 → clear token, show `#view-login`.
   - Network error → show `#view-login` with connectivity warning.
2. If `token` is null → show `#view-login`.

`currentUserId` is stored so the UI can disable the Delete button on the logged-in user's own row.

Token is stored in `sessionStorage` (cleared on tab/window close). Never `localStorage` — reduces
exposure on a shared machine.

---

## 6. API call layer

One helper function wraps every `fetch` call:

```js
async function api(method, path, body = null) {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = 'Bearer ' + token;
  const opts = { method, headers };
  if (body) opts.body = JSON.stringify(body);

  let res;
  try {
    res = await fetch('http://127.0.0.1:8088' + path, opts);
  } catch (e) {
    // Network-level failure (server not running, CORS error, etc.)
    throw { status: 0, detail: 'Cannot reach the backend. Is the server running at port 8088?' };
  }

  if (res.status === 204) return {};        // no body
  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    // Normalize FastAPI error shapes: { detail: "..." } or { detail: [{msg, loc},...] }
    const detail = Array.isArray(data.detail)
      ? data.detail.map(e => e.msg).join('; ')
      : (data.detail || res.statusText);
    throw { status: res.status, detail };
  }
  return data;
}
```

All callers use `try { ... } catch (err) { showNotification(err.detail, 'error'); }`.

The 401 path is handled centrally — after any 401, clear the token and redirect to login:

```js
async function apiAuth(method, path, body = null) {
  try {
    return await api(method, path, body);
  } catch (err) {
    if (err.status === 401) {
      clearSession();
      showNotification('Session expired. Please sign in again.', 'error');
      showView('login');
    }
    throw err;
  }
}
```

---

## 7. Error states — complete catalog

### 7.1 Network / infrastructure

| Condition | HTTP status | User-visible message | Display method |
|-----------|-------------|----------------------|----------------|
| Backend not running | status 0 (fetch throws) | "Cannot reach the backend. Is the server running at port 8088?" | Error banner |
| Qdrant down (unrelated to user mgmt) | — | — | Not shown (user mgmt doesn't use Qdrant) |
| Server error | 500 | "Server error. Check the backend terminal for details." | Error banner |

### 7.2 Authentication

| Condition | HTTP status | User-visible message | Display method |
|-----------|-------------|----------------------|----------------|
| Wrong email or password on login | 401 | "Incorrect email or password." | Error banner below login form |
| Expired JWT on any request | 401 | "Session expired. Please sign in again." | Error banner; redirect to login |
| Missing token (page refresh after session) | 401 | — | Silent redirect to login |

### 7.3 Registration / user creation

| Condition | HTTP status | User-visible message | Display method |
|-----------|-------------|----------------------|----------------|
| Email already registered | 400 | "An account with this email already exists." | Error banner inside modal |
| Invalid email format (client-side) | — | "Enter a valid email address." | Inline, below email field |
| Password < 8 chars (client-side) | — | "Password must be at least 8 characters." | Inline, below password field |
| Confirm password mismatch (client-side) | — | "Passwords do not match." | Inline, below confirm field |
| Empty required field (client-side) | — | "This field is required." | Inline, below the field; field border turns red |
| Email uses `.local` TLD | 422 | "Email format not accepted. Use a standard domain (e.g. .dev, .test)." | Error banner inside modal |

### 7.4 Edit user

| Condition | HTTP status | User-visible message | Display method |
|-----------|-------------|----------------------|----------------|
| New email already taken | 400 | "That email is already used by another account." | Error banner inside modal |
| User not found (deleted by another session) | 404 | "User not found. The list may be out of date — refreshing." | Error banner; reload list |
| Invalid email format (client-side) | — | "Enter a valid email address." | Inline |

### 7.5 Password operations

| Condition | HTTP status | User-visible message | Display method |
|-----------|-------------|----------------------|----------------|
| Wrong current password (change-pw) | 401 | "Current password is incorrect." | Error banner inside modal |
| New password < 8 chars (client-side) | — | "Password must be at least 8 characters." | Inline |
| Confirm mismatch (client-side) | — | "Passwords do not match." | Inline |
| User not found (reset-pw) | 404 | "User not found." | Error banner inside modal |

### 7.6 Delete

| Condition | HTTP status | User-visible message | Display method |
|-----------|-------------|----------------------|----------------|
| Attempting to delete own account | 400 | "You cannot delete your own account while logged in." | Error banner inside modal (button is also disabled in the row) |
| User not found | 404 | "User not found. Refreshing the list." | Error banner; reload list |

### 7.7 Success states

| Action | Success message | Auto-dismiss |
|--------|----------------|--------------|
| Login | — | n/a (navigate to user list) |
| Create user | "{email} created successfully." | 3 s |
| Edit user | "User updated." | 3 s |
| Reset password | "Password reset successfully." | 3 s |
| Change own password | "Password changed." | 3 s |
| Delete user | "{email} deleted." | 3 s |

---

## 8. Notification banner design

```html
<div id="notification-bar" class="notif hidden" role="alert"></div>
```

```css
.notif {
  position: fixed; top: 0; left: 0; right: 0;
  padding: 12px 20px; font-size: 14px; font-weight: 500;
  text-align: center; z-index: 1000;
  transition: opacity 0.2s ease;
}
.notif.error   { background: #c0392b; color: #fff; }
.notif.success { background: #27ae60; color: #fff; }
.notif.hidden  { display: none; }
```

```js
let _notifTimer = null;

function showNotification(msg, type = 'error', duration = 0) {
  const el = document.getElementById('notification-bar');
  el.textContent = msg;
  el.className = 'notif ' + type;
  clearTimeout(_notifTimer);
  if (duration > 0) {
    _notifTimer = setTimeout(() => { el.className = 'notif hidden'; }, duration);
  }
}
```

- Error messages: `duration = 0` — stay until the next action replaces them.
- Success messages: `duration = 3000` — auto-dismiss after 3 s.
- Inline field errors use a `<span class="field-error">` below the input, toggled by JS.
  They clear when the user starts typing in that field (`input` event listener).

---

## 9. Visual design — CSS layout

Minimal, functional styling. No grid/flexbox libraries. Roughly 150 lines of CSS.

**Color palette:**
- Background: `#f5f5f5`
- Card/modal background: `#ffffff`
- Primary action: `#2c3e50` (buttons)
- Destructive action: `#c0392b` (delete buttons)
- Success: `#27ae60`
- Border: `#ddd`
- Text: `#333`

**Layout:**
- Login/register view: centered card, max-width 380px, box-shadow
- Users view: full-width, header bar at top (flexbox row), table below
- Table: 100% width, `border-collapse: collapse`, alternating row shading
- Modals: fixed overlay (`position:fixed, top:0, left:0, width:100%, height:100%`), centered box
- Inputs: full-width within form, padding 8px, border 1px solid #ddd, border-radius 4px
- Error state input: `border-color: #c0392b`

No media queries needed — this is an operator tool used on the Mac running the backend, always in a desktop browser. Minimum viable responsive behavior only.

---

## 10. JavaScript function map

All functions are in a single `<script>` block at the bottom of `index.html`.

```
Lifecycle
  init()                    ← DOMContentLoaded handler; verify token or show login

Navigation
  showView(name)            ← hides all views, shows #view-{name}
  openModal(id)             ← show modal overlay
  closeModal(id)            ← hide modal overlay

API
  api(method, path, body)   ← base fetch wrapper; throws {status, detail}
  apiAuth(...)              ← wraps api(); handles 401 centrally

Session
  saveSession(token, uid)   ← sessionStorage.setItem × 2
  clearSession()            ← sessionStorage.clear(); reset state vars

Login/register
  handleLogin(e)            ← validate → POST /v1/auth/login → saveSession → loadUsers
  handleRegister(e)         ← validate → POST /v1/auth/register → auto-login → loadUsers
  handleSignOut()           ← clearSession → showView('login')
  handleChangePassword(e)   ← validate → POST /v1/auth/change-password → close modal

User list
  loadUsers()               ← GET /v1/admin/users → renderUserTable
  renderUserTable(users)    ← build <tbody> rows; wire action buttons

Create / edit
  openCreateModal()         ← clear form → openModal('create')
  openEditModal(userId)     ← GET /v1/admin/users/{id} → populate form → openModal('edit')
  handleCreateUser(e)       ← validate → POST /v1/auth/register → loadUsers
  handleEditUser(e)         ← validate → PATCH /v1/admin/users/{id} → loadUsers

Password
  openResetPwModal(userId)  ← store editingUserId → openModal('reset-pw')
  handleResetPassword(e)    ← validate → POST /v1/admin/users/{id}/password → close modal

Delete
  openDeleteModal(userId)   ← store editingUserId; set email in confirm text → openModal('confirm-delete')
  handleDeleteUser()        ← DELETE /v1/admin/users/{id} → loadUsers

Validation helpers
  validateEmail(val)        ← basic regex; returns error string or null
  validatePassword(val)     ← length check; returns error string or null
  validateMatch(a, b)       ← returns error string or null
  showFieldError(id, msg)   ← set .field-error text, add red border
  clearFieldErrors(formId)  ← clear all field errors in a form
```

Total JS: approximately 300–350 lines. No classes, no modules, no bundler.

---

## 11. HTML skeleton (abbreviated)

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Omi User Admin</title>
  <style>/* ~150 lines of CSS */</style>
</head>
<body>
  <div id="notification-bar" class="notif hidden" role="alert"></div>

  <!-- Login -->
  <section id="view-login" class="hidden">
    <div class="card">
      <h1>Omi User Admin</h1>
      <form id="form-login">
        <label>Email <input type="email" id="login-email" required></label>
        <span class="field-error" id="login-email-err"></span>
        <label>Password <input type="password" id="login-password" required></label>
        <span class="field-error" id="login-password-err"></span>
        <button type="submit">Sign In</button>
      </form>
      <p><a href="#" id="link-to-register">Register first account</a></p>
    </div>
  </section>

  <!-- Register -->
  <section id="view-register" class="hidden"> ... </section>

  <!-- Users list -->
  <section id="view-users" class="hidden">
    <header class="toolbar">
      <span class="title">Omi User Admin</span>
      <button id="btn-new-user">+ New User</button>
      <button id="btn-change-pw">Change My Password</button>
      <button id="btn-sign-out" class="btn-secondary">Sign Out</button>
    </header>
    <div class="table-wrap">
      <table id="user-table">
        <thead><tr>
          <th>Email</th><th>Display Name</th><th>ID</th><th>Created</th><th>Actions</th>
        </tr></thead>
        <tbody id="user-tbody"></tbody>
      </table>
      <p id="empty-state" class="hidden">No users found.</p>
    </div>
  </section>

  <!-- Modals (create, edit, reset-pw, change-pw, confirm-delete) -->
  <!-- Each modal: <div id="modal-X" class="modal-overlay hidden"> -->
  <!--   <div class="modal-box"> ... form ... </div> -->
  <!-- </div> -->

  <script>/* ~350 lines of JS */</script>
</body>
</html>
```

---

## 12. Serving instructions (to include in RUNBOOK.md §7)

Once implemented, add this to the RUNBOOK under §7.2 or a new §7.4:

**Access the admin UI:**
```
http://127.0.0.1:8088/admin/
```
The page is served automatically when the backend is running (static mount added to `main_local.py`).

No separate server process needed. The admin UI calls the same backend on port 8088.

**First use:**
1. Open `http://127.0.0.1:8088/admin/` in a browser.
2. If no account exists yet, click "Register first account" to create one.
3. Sign in. All local users are visible in the table.

**Sign out:** Click "Sign Out". The session token is cleared from `sessionStorage` (cleared automatically when you close the tab).

---

## 13. Feasibility assessment

| Requirement | Feasible? | Notes |
|-------------|-----------|-------|
| No JS libraries | Yes | `fetch`, `sessionStorage`, DOM APIs are all that's needed |
| No CSS libraries | Yes | ~150 lines of plain CSS covers everything required |
| No build step | Yes | Single HTML file served as-is |
| No new server process | Yes | Static file mount on the existing FastAPI app |
| CORS | Yes | Already `allow_origins=["*"]` in `main_local.py` |
| JWT auth | Yes | `sessionStorage` + `Authorization: Bearer` header on every call |
| All CRUD operations | **Partially** | Register + login exist; list/update/delete/change-pw need 4 new repo functions + 1 new router file |
| Cascade delete | Yes | Already wired in SQLAlchemy models via `cascade="all, delete-orphan"` |
| Password security | Yes | Existing PBKDF2-SHA256 with 200k iterations; new endpoints reuse `_hash_password` / `_verify_password` |
| Self-delete guard | Yes | One `if` check in the DELETE endpoint; also gray out the button in JS |
| Error display | Yes | Single banner element + inline field errors — all plain DOM manipulation |
| Session expiry | Yes | Any 401 clears the token and redirects to the login view |

**One dependency to verify:** `aiofiles` must be installed for `StaticFiles`. It is a transitive
dep of `fastapi[all]` but not of plain `fastapi`. Check:
```bash
conda activate omilocal && python -c "import aiofiles; print('ok')"
```
If missing: `pip install aiofiles`. Add to `requirements.txt`.

---

## 14. Implementation order

1. Add `list_all_users`, `update_user`, `update_user_password`, `delete_user` to `repository.py`
2. Create `routers_local/admin.py` (5 endpoints)
3. Add `POST /v1/auth/change-password` to `routers_local/auth.py`
4. Register the admin router in `main_local.py`
5. Add the static mount in `main_local.py`; verify `aiofiles` is installed
6. Create `backend/admin/index.html` (login → register → user table → modals)
7. Test end-to-end: register → login → list → create → edit → reset pw → change own pw → delete
8. Add a "User Admin UI" note to RUNBOOK.md §7
