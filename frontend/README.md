# Frontend

React + TypeScript + Vite frontend for the Blockchain-Enabled Secure
Question Paper Distribution Framework. (Originally scoped as the "Phase 6A
foundation"; the portals below were added in Phases 6B, 6C, 6D, 6F, 6G and
6H. `../PROJECT_STATE.md` has the history.)

**What is implemented (see `src/routes/`):**

- Login and verification-code entry (authenticator app) with protected, role-based routing, and an **authenticator enrollment page** (`/enroll`: username + password + one-time enrollment code, QR / setup key shown once, confirm with a code, then sign in). Phase 7A.
- **Admin portal** (`/admin`): dashboard, papers list (registration status
  and server-computed release state shown separately), paper upload, paper
  detail (authorize/revoke centres, reschedule while locked, release
  schedule history), examination centres, audit logs, security events.
- **Examination Centre portal** (`/exam-centre`): authorized papers with the
  server-reported release state, paper detail/status, and retrieval of a
  released paper.

**Not implemented:** examination-session security UI, evaluation and
feedback screens, analytics. Release state is always taken from the backend
(`lock_status`); the browser clock is used only for an informational
countdown and never decides access. A centre that requests a paper it may
not access sees the same generic "not found" as for an unknown paper.

## Prerequisites

- Node.js 20+ and npm (tested with Node 22 / npm 10)
- The backend running locally (see `backend/README.md` or
  `PROJECT_STATE.md`) — by default at `http://localhost:8000`

## Setup

```bash
cd frontend
npm install
cp .env.example .env.local
# Edit .env.local if your backend is not at the default URL.
```

`.env.local` must define:

```
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

This must match the backend's `API_V1_PREFIX` (default `/api/v1`,
see `backend/app/config.py`).

## Running the dev server

```bash
npm run dev
```

Opens at `http://localhost:3000` by default. The backend's CORS
configuration (`backend/.env` → `CORS_ORIGINS`) already allows
`http://localhost:3000` by default — no backend change is required for
the standard setup.

## Type checking

```bash
npm run typecheck
```

## Running tests

```bash
npm test
```

Uses Vitest + React Testing Library. Tests mock `fetch` — no backend
needs to be running to execute the test suite.

## Production build

```bash
npm run build
```

Type-checks (`tsc -b`) and then builds to `dist/`. Preview the built
app with:

```bash
npm run preview
```

## Authentication flow implemented

1. `POST /auth/login` (username + password) → `{ otp_required, pre_auth_token }`
2. `POST /auth/otp/verify` (pre_auth_token + otp_code) → `{ access_token, token_type, role }`
3. `GET /auth/me` → canonical current-user identity (called on session
   restore and immediately after OTP verification)
4. `POST /auth/logout` → revokes the session server-side

The access token is stored in `sessionStorage` (cleared when the tab
closes) — see `src/contexts/AuthContext.tsx` for the full rationale
and known limitations.

## Security notes

- Only variables prefixed with `VITE_` are ever exposed to the browser
  bundle. Never put secrets, database credentials, JWT signing keys,
  or Fabric certificates in any frontend `.env*` file.
- `.env` / `.env.local` are git-ignored; only `.env.example` is
  committed.
- Passwords and OTP codes are never logged or persisted anywhere in
  the frontend.
- Role information used for **routing** (which page to show) comes
  from the backend's own responses/`/auth/me`. This is a UX
  convenience only — the backend independently enforces RBAC on every
  request, and remains the sole authorization authority.

## Project structure

```
src/
├── api/            Centralized fetch client + typed endpoint functions
├── components/     Reusable UI (common/) and layout (layout/) components
├── contexts/        AuthContext (the authentication state machine)
├── hooks/          useAuth()
├── pages/          auth/ (Login, OTP), placeholder/ (Admin, Exam Centre), errors/ (404, 403)
├── routes/         AppRoutes, ProtectedRoute
├── types/          auth.ts, api.ts (mirrors backend schemas exactly)
├── test/           test setup + shared test helpers
├── App.tsx, main.tsx, index.css
```
