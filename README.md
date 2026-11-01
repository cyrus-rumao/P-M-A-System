# P-M-A-System

P-M-A-System is a workspace-based project and task management application. Users
can register or sign in with Google, create and join workspaces, invite members,
manage workspace roles, create projects, and track project tasks with statuses,
priorities, assignees, due dates, filters, pagination, and analytics.

The repository contains:

- `client/`: the React 18 + TypeScript + Vite web application.
- `backend/`: the primary Node.js + Express + TypeScript API.
- `python backend/`: a FastAPI implementation of the same API concepts and
  MongoDB collections.

The React client is wired to whichever backend is exposed through
`VITE_API_BASE_URL`. The TypeScript backend is the default implementation
described below; the Python backend can be run as an alternative service.

## Architecture

```text
Browser
  │
  │ React routes, React Query, Axios, signed session cookie
  ▼
HTTP API (/api)
  ├─ backend/          Express + Passport + Mongoose
  └─ python backend/   FastAPI + Authlib + Motor
  │
  ▼
MongoDB
  ├─ users
  ├─ accounts
  ├─ workspaces
  ├─ members
  ├─ roles
  ├─ projects
  └─ tasks
```

Both backends use cookie-based sessions, MongoDB, local bcrypt authentication,
and Google OAuth. The Python service additionally has an optional Redis
connection hook; Redis is not used by the current Express endpoints.

## End-to-end system flow

### 1. Startup

1. The browser loads the Vite bundle from `client/`.
2. The selected API starts and loads environment variables.
3. The Express service creates JSON/urlencoded middleware, a signed
   `cookie-session`, Passport, and CORS middleware, then connects to MongoDB.
4. The FastAPI service creates its session and CORS middleware and uses its
   lifespan handler to ping MongoDB and optionally Redis.
5. The backend mounts routes below `BASE_PATH`, which defaults to `/api`.

### 2. Authentication

1. The client starts at `/` and `AuthRoute` requests `/api/user/current`.
2. If there is no valid session, the user sees the sign-in page.
3. Email registration calls `POST /api/auth/register`. The backend hashes the
   password, creates an `accounts` record, creates a default workspace, adds
   the user as its owner, and sets the current workspace.
4. Email login calls `POST /api/auth/login`. A valid login writes the user ID
   into the signed session cookie.
5. Google login redirects to the backend OAuth endpoint. Passport/Authlib
   resolves the Google profile, creates or finds the user and account, creates
   a default workspace for a new user, and redirects back to the client.
6. The client loads the authenticated user and redirects to
   `/workspace/:workspaceId`. Invalid or expired sessions return to `/`.

### 3. Workspace and permission flow

1. `AuthProvider` loads the current user and the workspace from the URL.
2. The backend checks membership for workspace-scoped requests.
3. A member's role (`OWNER`, `ADMIN`, or `MEMBER`) determines permissions.
4. The sidebar, page actions, and `PermissionGuard` hide or block actions the
   current role cannot perform.
5. Users can create workspaces, switch between them, update settings, invite
   members with an invite code, change member roles, and delete workspaces.

### 4. Project and task flow

1. The dashboard requests workspace analytics, recent projects, recent tasks,
   and recent members.
2. Creating or editing a project sends a mutation through `client/src/lib/api.ts`
   to the project controller/service, which validates membership and
   permissions before changing MongoDB.
3. Project details request project analytics and the task table.
4. Task mutations carry workspace and project IDs. The task service validates
   status, priority, assignment, and access before saving.
5. Task lists support keyword, project, assignee, priority, status, due-date,
   page-number, and page-size filters.
6. React Query invalidates/refetches affected queries so the dashboard and tables
   reflect the new state without a full page reload.

### 5. Error and logout flow

The API returns structured errors through the Express error middleware or the
FastAPI exception handler. The Axios response interceptor treats a 401 as an
expired session. Logout clears the server-side session cookie and the client
returns to the authentication route.

## Local development

### Prerequisites

- Node.js and npm
- Python 3.11+ (only if using the FastAPI implementation)
- MongoDB
- Google OAuth credentials (optional unless Google sign-in is required)

### Run the primary TypeScript stack

Create `backend/.env` with values similar to:

```env
NODE_ENV=development
PORT=5000
BASE_PATH=/api
MONGO_URI=mongodb://127.0.0.1:27017/pma
SESSION_SECRET=replace-with-a-long-random-value
SESSION_EXPIRES_IN=1d
FRONTEND_ORIGIN=http://localhost:5173
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_CALLBACK_URL=http://localhost:5000/api/auth/google/callback
FRONTEND_GOOGLE_CALLBACK_URL=http://localhost:5173/google/oauth/callback
```

Start the API:

```bash
cd backend
npm install
npm run dev
```

Seed the role records before using role-based features:

```bash
cd backend
npm run seed
```

Start the web application in a second terminal:

```bash
cd client
npm install
printf 'VITE_API_BASE_URL=http://localhost:5000/api\n' > .env.local
npm run dev
```

Production-style commands are `npm run build && npm start` in `backend`, and
`npm run build` followed by `npm run preview` in `client`.

### Run the FastAPI implementation

```bash
cd "python backend"
cp .env.example .env
# Set MONGO_URI and SESSION_SECRET in .env
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Point the client at `http://localhost:8000/api` instead of the Express API.
`seed.py` creates the `OWNER`, `ADMIN`, and `MEMBER` role documents:

```bash
cd "python backend"
python seed.py
```

## API surface

All authenticated resource routes are prefixed with `/api` by default.

| Area | Routes |
|---|---|
| Auth | `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/google`, `GET /auth/google/callback` |
| User | `GET /user/current` |
| Workspaces | `POST /workspace/create/new`, `GET /workspace/all`, `GET /workspace/:workspaceId`, `GET /workspace/members/:workspaceId`, `GET /workspace/analytics/:workspaceId`, `PUT /workspace/update/:workspaceId`, `PUT /workspace/change/member/role/:workspaceId`, `DELETE /workspace/delete/:workspaceId` |
| Members | `POST /member/workspace/:inviteCode/join` |
| Projects | `POST /project/workspace/:workspaceId/create`, `GET /project/workspace/:workspaceId/all`, `GET /project/:projectId/workspace/:workspaceId`, `GET /project/:projectId/workspace/:workspaceId/analytics`, `PUT /project/:projectId/workspace/:workspaceId/update`, `DELETE /project/:projectId/workspace/:workspaceId/delete` |
| Tasks | `POST /task/project/:projectId/workspace/:workspaceId/create`, `GET /task/workspace/:workspaceId/all`, `GET /task/:id/project/:projectId/workspace/:workspaceId`, `PUT /task/:id/project/:projectId/workspace/:workspaceId/update`, `DELETE /task/:id/workspace/:workspaceId/delete` |

## Repository file guide

### Root and project configuration

| Path | Responsibility |
|---|---|
| `.gitignore` | Shared ignored files. |
| `.eslintignore` | Shared ESLint exclusions. |
| `.vscode/settings.json` | Editor settings. |
| `backend/package.json` | API scripts and runtime/build dependencies. |
| `backend/package-lock.json` | Locked API dependency versions. |
| `backend/tsconfig.json` | Strict TypeScript compiler settings and `dist` output. |
| `client/package.json` | Frontend scripts and UI/data dependencies. |
| `client/package-lock.json` | Locked frontend dependency versions. |
| `client/vite.config.ts` | Vite React plugin and `@` source alias. |
| `client/tsconfig*.json` | Frontend TypeScript, browser, and Node/Vite settings. |
| `client/eslint.config.js` | Frontend lint rules. |
| `client/tailwind.config.js` | Tailwind theme and content configuration. |
| `client/postcss.config.js` | PostCSS/Tailwind processing. |
| `client/components.json` | UI component generator configuration. |
| `client/index.html` | Browser HTML entry point. |

### TypeScript backend

#### Startup, configuration, and middleware

| Path | Responsibility |
|---|---|
| `backend/src/index.ts` | Creates Express, installs middleware, mounts routes, connects MongoDB, and listens on `PORT`. |
| `backend/src/config/app.config.ts` | Reads API, database, session, OAuth, and frontend environment variables. |
| `backend/src/config/database.config.ts` | Opens the Mongoose MongoDB connection. |
| `backend/src/config/http.config.ts` | Shared HTTP status constants and status type. |
| `backend/src/config/passport.config.ts` | Configures Google and local Passport strategies and session serialization. |
| `backend/src/middlewares/asyncHandler.middleware.ts` | Forwards rejected async controller promises to Express error handling. |
| `backend/src/middlewares/errorHandler.middleware.ts` | Converts application errors into API responses. |
| `backend/src/middlewares/isAuthenticated.middleware.ts` | Rejects requests without an authenticated Passport session. |
| `backend/src/@types/index.d.ts` | Extends Express's user type with the application user document. |

#### Routes and controllers

Each route file maps HTTP paths to a controller. Controllers translate HTTP
input/output and delegate business rules to services.

| Path | Responsibility |
|---|---|
| `backend/src/routes/auth.route.ts` / `controllers/auth.controller.ts` | Registration, local login, logout, and Google OAuth callback. |
| `backend/src/routes/user.route.ts` / `controllers/user.controller.ts` | Current authenticated user. |
| `backend/src/routes/workspace.route.ts` / `controllers/workspace.controller.ts` | Workspace CRUD, members, role changes, and analytics. |
| `backend/src/routes/member.route.ts` / `controllers/member.controller.ts` | Joining a workspace from an invite code. |
| `backend/src/routes/project.route.ts` / `controllers/project.controller.ts` | Project CRUD, listing, and analytics. |
| `backend/src/routes/task.route.ts` / `controllers/task.controller.ts` | Task CRUD and filtered task listing. |

#### Services, models, validation, and utilities

| Path | Responsibility |
|---|---|
| `backend/src/services/auth.service.ts` | Creates accounts, verifies passwords, resolves OAuth users, and builds sessions. |
| `backend/src/services/user.service.ts` | Reads the current user. |
| `backend/src/services/workspace.service.ts` | Workspace membership, lifecycle, roles, and analytics. |
| `backend/src/services/member.service.ts` | Invite-code membership and role lookup. |
| `backend/src/services/project.service.ts` | Project persistence and project analytics. |
| `backend/src/services/task.service.ts` | Task persistence, filters, pagination, and task analytics data. |
| `backend/src/models/user.model.ts` | User schema and password-safe serialization. |
| `backend/src/models/account.model.ts` | Provider-specific login account schema. |
| `backend/src/models/workspace.model.ts` | Workspace schema. |
| `backend/src/models/member.model.ts` | User-to-workspace membership schema. |
| `backend/src/models/roles-permission.model.ts` | Workspace role and permission schema. |
| `backend/src/models/project.model.ts` | Project schema. |
| `backend/src/models/task.model.ts` | Task schema and task fields. |
| `backend/src/enums/account-provider.enum.ts` | Email and Google provider values. |
| `backend/src/enums/error-code.enum.ts` | Stable API error codes. |
| `backend/src/enums/role.enum.ts` | Owner, admin, and member roles. |
| `backend/src/enums/task.enum.ts` | Task statuses and priorities. |
| `backend/src/validation/auth.validation.ts` | Authentication request validation. |
| `backend/src/validation/workspace.validation.ts` | Workspace request validation. |
| `backend/src/validation/project.validation.ts` | Project request validation. |
| `backend/src/validation/task.validation.ts` | Task request validation. |
| `backend/src/seeders/role.seeder.ts` | Seeds default roles and permissions. |
| `backend/src/utils/appError.ts` | Typed application errors. |
| `backend/src/utils/bcrypt.ts` | Password hashing and comparison helpers. |
| `backend/src/utils/get-env.ts` | Required/default environment variable access. |
| `backend/src/utils/role-permission.ts` | Permission definitions and role checks. |
| `backend/src/utils/roleGuard.ts` | Authorization guard helpers. |
| `backend/src/utils/uuid.ts` | UUID generation helper. |

### React client

| Path/group | Responsibility |
|---|---|
| `client/src/main.tsx`, `App.tsx`, `index.css` | React bootstrap, providers, root component, and global styles. |
| `client/src/routes/` | Public, protected, invite, authentication, and not-found route composition. |
| `client/src/layout/` | Base public layout and authenticated sidebar/header application layout. |
| `client/src/context/` | React Query defaults and authenticated user/workspace context. |
| `client/src/lib/api.ts` | Typed Axios functions for auth, workspace, member, project, and task requests. |
| `client/src/lib/axios-client.ts` | Axios instance, API base URL, cookies, and unauthorized handling. |
| `client/src/lib/base-url.ts`, `helper.ts`, `utils.ts` | Shared URL and UI utility helpers. |
| `client/src/hooks/api/` | React Query hooks for authentication, workspaces, members, and projects. |
| `client/src/hooks/` | Dialog state, workspace ID, permissions, filters, mobile layout, and toast hooks. |
| `client/src/hoc/with-permission.tsx` | Permission-aware component wrapper. |
| `client/src/types/` | API response/payload and custom error TypeScript types. |
| `client/src/constant/` | Shared client constants. |
| `client/src/page/auth/` | Sign-in, sign-up, and Google OAuth failure screens. |
| `client/src/page/invite/InviteUser.tsx` | Invite-link acceptance and workspace joining screen. |
| `client/src/page/workspace/` | Dashboard, tasks, members, project details, and settings screens. |
| `client/src/components/asidebar/` | Workspace switcher, navigation, project navigation, and logout UI. |
| `client/src/components/auth/` | Google OAuth sign-in/sign-up button. |
| `client/src/components/workspace/` | Workspace, member, project, task, analytics, dialog, form, and settings features. |
| `client/src/components/ui/` | Reusable Radix/Tailwind UI primitives: buttons, forms, tables, dialogs, menus, tabs, pagination, toasts, and layout controls. |
| `client/src/components/resuable/`, `confirm-dialog/`, `skeleton-loaders/` | Permission/confirmation helpers and loading states. |
| `client/src/components/header.tsx`, `logo/`, `emoji-picker/` | Shared application chrome and project/workspace visual controls. |
| `client/public/` and `client/src/assets/` | Static images and starter assets. |

The many files under `client/src/components/ui/` are intentionally thin,
reusable presentation primitives. Feature behavior lives in the workspace
components, pages, hooks, and API module; the UI primitives do not access the
backend directly.

### Python backend

| Path | Responsibility |
|---|---|
| `python backend/main.py` | FastAPI application, CORS/session middleware, OAuth, Pydantic models, authorization, and all API handlers in one module. |
| `python backend/config.py` | Cached environment-backed settings. |
| `python backend/db.py` | MongoDB/optional Redis lifecycle, database accessor, and UTC timestamp helper. |
| `python backend/seed.py` | Seeds role documents using the FastAPI permission map. |
| `python backend/requirements.txt` | Python runtime dependencies. |
| `python backend/.env.example` | FastAPI environment variable template. |
| `python backend/README.md` | Short Python-service setup notes. |

## Useful commands

```bash
# TypeScript API
cd backend && npm run dev
cd backend && npm run seed
cd backend && npm run build

# React client
cd client && npm run dev
cd client && npm run lint
cd client && npm run build

# FastAPI alternative
cd "python backend" && uvicorn main:app --reload --port 8000
cd "python backend" && python seed.py
```
