# NEXUS Forensics (SIH26189) — App Overview

## 1. What the app is

**NEXUS Forensics** is an explainable, tamper-proof investigative co-pilot built for **Smart India Hackathon problem SIH26189**.

It ingests fragmented law-enforcement data (FIR text, CDR call logs, bank transactions), resolves entities (people, phones, bank accounts, vehicles), builds a case-bound relationship graph, scores suspect risk, and logs every officer action to a hash-chained audit ledger.

Positioning: not a CCTNS/NATGRID aggregator, not an opaque Palantir-style black box — it is a **reasoning-first, India-context analytical layer** where every edge shows confidence + evidence source and every approval is human-signed + audited.

Demo case: `CAS-2026-102 — Operation Redline` (3 core suspects, shared burner phone, circular money trail).

## 2. How it works (end-to-end flow)

```
FIRs / CDRs / Bank CSVs
  -> ingestion/extract.py (regex + spaCy NER, Hindi/English)
  -> ingestion/resolve.py (anchor phone/vehicle + RapidFuzz name match)
  -> ingestion/build_graph.py -> SQLite entities/edges
  -> graph_store.py (NetworkX DiGraph) + analytics.py (PageRank, betweenness, cycles, burner clusters)
  -> risk_engine.py (ISO/IEC 27005 likelihood x consequence -> 0-100 + HIGH/MEDIUM/LOW)
  -> main.py (FastAPI) serves Dashboard / Graph / Review / Audit APIs
  -> nexusfront (React) visualizes + human-in-the-loop Approve/Reject
  -> audit_log.py appends hash-chained entry per action + anchor file
```

Key files:

- Backend entry: `main.py` — FastAPI app, CORS, rate limits, JWT deps, all `/api/v1/*` routes.
- Persistence: `database.py` — SQLite schema (`cases`, `entities`, `edges`, `evidence_sources`, `audit_log`, `users`), WAL mode.
- Graph: `graph_store.py` — `build_graph()`, `get_entities()`, `get_edges()`, `graph_analytics()`.
- Analytics: `analytics.py` — `compute_centrality()`, `circular_money_flows()`, `burner_clusters()`, `entity_signals()`.
- Risk: `risk_engine.py` — `calculate_threat_score()` with `ISO_27005_RISK_MATRIX`.
- Auth: `security.py` — `hash_password()`, `verify_password()`, `create_access_token()`, `decode_token()`, `mask_entity_pii()`, lockout guard.
- Audit: `audit_log.py` — `log_officer_action()`, `verify_audit_chain()`, `anchor_audit_chain()`, `verify_against_anchor()`.
- Seed: `seed_data.py` — `ensure_seed_data()`, `ensure_seed_users()`, `MOCK_ENTITIES`, `MOCK_EDGES`.
- Frontend shell: `nexusfront/src/App.tsx` — `AuthProvider`, `Shell` sidebar + `Switch` routing.
- API client: `nexusfront/src/lib/api.ts` — `BASE` from `VITE_API_URL`, `api.login/me/overview/graph/risk/pending/review/auditVerify/auditAnchor/logout`.

Auth flow:

1. `POST /api/v1/auth/login` (`_do_login()` in `main.py`) checks lockout, verifies bcrypt hash, returns JWT (`sub=badge_id`, `role`, `active_case`).
2. Frontend `Login.tsx` stores `{badge, role, activeCase, token}` in `localStorage` via `auth.tsx` (`AuthProvider`).
3. Subsequent calls attach `Authorization: Bearer <token>` via `headers()` in `api.ts`; backend `get_current_user()` decodes it.
4. Role drives PII masking: `lead_investigator` sees full phones, `analyst` sees `0912******10` via `mask_entity_pii()`.
5. `POST /api/v1/auth/logout` writes `SESSION_TERMINATED` + anchors ledger.

## 3. Features / sections

### 3.1 Secure Access (`/login` — `Login.tsx`)

- Badge ID + access key form, `wouter` `nav('/dashboard')` on success.
- Calls `api.login()` -> `POST /api/v1/auth/login`.
- Demo creds (dev only): `OFFICER-4402 / demo-only-change-me`, `ANALYST-101 / demo-only-change-me`.
- Errors shown in `.auth-error`; brute-force protected (10/min IP + 5-fail/5-min lockout).

### 3.2 Case Overview Dashboard (`/dashboard` — `Dashboard.tsx`)

- API: `GET /api/v1/cases/{id}/overview` (`get_case_overview()`).
- Shows `case_title`, `total_suspects`, `total_phone_numbers`, `total_bank_accounts`, `unreviewed_alerts`, `system_status`, `cpu_load_percent`, `memory_usage_percent`.
- Panels: System health + At-a-glance + link to review queue.
- Query: `useQuery(['overview', caseId])` via TanStack Query.

### 3.3 Network Graph (`/graph` — `GraphView.tsx`, core screen)

- API: `GET /api/v1/cases/{id}/graph` (`get_network_graph()` returns Cytoscape-ready `{nodes, edges}`) + `GET /api/v1/suspect/{id}/risk` per PERSON node + `GET /api/v1/cases/{id}/graph/analytics`.
- Custom SVG rendering (no Cytoscape runtime): elliptical `layout()`, `riskColor()` (red >=70, amber 40-69, green <40), node radius scaled by threat score, zoom via `viewBox`.
- Click node -> Evidence inspector shows `RiskAssessment` (threat_score/100, risk_level, contributing_factors with progress bar).
- Click edge -> shows `relation_type`, confidence %, `evidence_source`, source/target, status badge (PENDING amber / APPROVED green).
- Toolbar: zoom in/out/reset (`ZoomIn`, `ZoomOut`, `CircleDot` icons).

### 3.4 Evidence Review Queue (`/review` — `ReviewQueue.tsx`)

- API: `GET /api/v1/cases/{id}/links/pending` (`pending_links()`) with fallback to filtering `api.graph()` edges; action: `POST /api/v1/links/review` (`review_link()`).
- Lists `PENDING / PENDING_REVIEW / UNREVIEWED` links with relation, source->target, confidence, evidence.
- Approve/Reject buttons call `api.review(id, action, badge)`; on success invalidates `['pending']` + `['graph']` queries.
- Enforces `officer_badge == JWT sub`; persists `status`, `reviewer`, `reviewed_at`; returns `audit_hash`.

### 3.5 Audit Log Viewer (`/audit` — `AuditLog.tsx`)

- API: `GET /api/v1/cases/{id}/audit/verify` (`verify_case_audit()`) + `POST /api/v1/cases/{id}/audit/anchor` (lead only).
- Table: timestamp, actor, action, prev hash, current hash (truncated to 12 chars).
- Badge: `chain verified` (green `ShieldCheck`) vs `chain broken` (red `ShieldX`).
- Backend: SHA256(`timestamp|actor|action|case|prev_hash`), genesis `GENESIS_HASH`, INSERT-only table, file anchor at `CYSLOP_ANCHOR_PATH` + optional `CYSLOP_ANCHOR_URL` POST, `verify_against_anchor()` detects `APPENDED_SINCE_ANCHOR` vs `TAMPER_OR_ROLLBACK_DETECTED`.

### 3.6 App shell (`App.tsx` + `index.css`)

- Sidebar: brand `logo-full.png`, `SIH26189 MVP` chip, Main menu (Dashboard, Node Graph, Evidence Review, Audit Log), Log out button, Entity legend.
- Topbar: `Case: {activeCase} · {role}`, user pill.
- Theme: forensic dark (`--ink #170f0a`, `--text #ece1cf`, serif `Libre Baskerville` + mono `Special Elite`), Tailwind v4 + `tw-animate-css`.
- `ErrorBoundary` (`error-boundary.tsx`) catches render crashes; `QueryClient(retry:1, staleTime:15s)`.

## 4. Tech stack in detail

### Backend (`requirements.txt`, `Dockerfile`)

- `fastapi` + `uvicorn` — API server (`main.py`, v3.1.0), `CORSMiddleware` pinned to `FRONTEND_ORIGINS`, security headers (`nosniff`, `DENY`, `no-referrer`), `/healthz` + `/readyz`, docs hidden in production.
- `pydantic` — `models.py` (`EntityNode`, `EvidenceEdge`, `RiskAssessment`, `AuditLogEntry`).
- `spacy` (`en_core_web_sm`) + `rapidfuzz` — `ingestion/extract.py` NER + `ingestion/resolve.py` fuzzy matching; `scripts/seed_synthetic_data.py` + `scripts/ingest_synthetic.py` generate fixtures.
- `networkx` — `graph_store.py` `DiGraph`, `analytics.py` PageRank/betweenness/`simple_cycles`.
- `python-jose[cryptography]` + `passlib[bcrypt]` + `bcrypt==4.0.1` — JWT HS256 (`security.py`, 480-min expiry) + bcrypt hashing.
- `python-multipart` — OAuth2 `/auth/token` form support.
- `slowapi` — `Limiter(200/minute)` global + `10/minute` login.
- `httpx`, `pytest` — `tests/test_auth_audit.py` (login + audit chain test).
- `python:3.11-slim` image, `appuser (10001)`, SQLite at `/data/cyslop.db` (volume `cyslop-data`), anchor at `/data/audit_anchor.json`.

### Frontend (`nexusfront/package.json`, `vite.config.ts`, `Dockerfile`)

- `vite ^7.3.2` + `@vitejs/plugin-react ^5.0.4` + `typescript ^5.9.0` — build (`vite build` -> `dist/`), dev (`vite`), preview replaced by `nginx:alpine` with SPA fallback in production Dockerfile.
- `react 19.1.0` + `react-dom 19.1.0` — `main.tsx` `createRoot`, `App.tsx`, pages.
- `wouter ^3.3.5` — `Route`, `Switch`, `Link`, `Redirect`, `useLocation` routing.
- `@tanstack/react-query ^5.90.21` — `useQuery`/`useMutation`/`QueryClient` data layer (`api.ts`).
- `tailwindcss ^4.1.14` + `@tailwindcss/vite ^4.1.14` + `@tailwindcss/typography` + `tw-animate-css` + `clsx` + `tailwind-merge` + `class-variance-authority` — styling + `components.json` shadcn setup + 40+ `components/ui/*` primitives.
- `lucide-react`, `react-icons` — icons; `recharts`, `embla-carousel-react`, `framer-motion`, `vaul`, `cmdk`, `sonner` — charts/carousel/motion/drawers.
- `react-hook-form` + `@hookform/resolvers` + `zod` — forms/validation; `date-fns`, `react-day-picker`, `input-otp`, `next-themes` — utilities.
- `@radix-ui/*` (accordion, dialog, dropdown, popover, tabs, tooltip, etc.) — accessible UI kit.
- `VITE_API_URL` build arg (default `http://localhost:8000`) baked into `api.ts` `BASE`; `docker-compose.yml` maps `5173:80` (nginx) + `8000:8000` (uvicorn), `depends_on backend healthy`.

### Data + DevOps

- SQLite (WAL, FK on) — survives restart via Docker volume; migrate to Postgres for multi-replica.
- `docker-compose.yml` — `backend` (build `.`, `uvicorn main:app`, healthcheck via `urllib /healthz`) + `frontend` (build `./nexusfront`, `VITE_API_URL` arg).
- `.dockerignore` (root + `nexusfront/.dockerignore`) keeps contexts small (excludes `node_modules/`, `dist/`, `*.db`, `.git/`).
- Env: `.env.example` documents `CYSLOP_JWT_SECRET`, `CYSLOP_SEED_USERS=BADGE:password:role:CASE`, `CYSLOP_ENV`, `FRONTEND_ORIGINS`, `ALLOW_INSECURE_DEV`, `CYSLOP_DEMO_PASSWORD`.

## 5. API quick reference

| Method | Path | Handler | Purpose |
|---|---|---|---|
| `GET` | `/healthz`, `/readyz` | `healthz()`, `readyz()` | ops probes |
| `POST` | `/api/v1/auth/login`, `/api/v1/auth/token` | `_do_login()` | JWT login |
| `GET` | `/api/v1/auth/me` | `me()` | current user |
| `POST` | `/api/v1/auth/logout` | `logout()` | terminate + anchor |
| `GET` | `/api/v1/cases/{id}/overview` | `get_case_overview()` | dashboard metrics |
| `GET` | `/api/v1/cases/{id}/graph` | `get_network_graph()` | nodes + edges |
| `GET` | `/api/v1/cases/{id}/graph/analytics` | `get_graph_analytics()` | PageRank/betweenness/cycles |
| `POST` | `/api/v1/cases/{id}/ingest` | `ingest_case()` | synthetic ingest (lead-only in prod) |
| `GET` | `/api/v1/suspect/{id}/risk` | `get_suspect_risk()` | ISO 27005 score |
| `GET` | `/api/v1/cases/{id}/links/pending` | `pending_links()` | review queue |
| `POST` | `/api/v1/links/review` | `review_link()` | Approve/Reject |
| `GET` | `/api/v1/cases/{id}/audit/verify` | `verify_case_audit()` | ledger + integrity |
| `POST` | `/api/v1/cases/{id}/audit/anchor` | `anchor_case_audit()` | anchor head (lead-only) |
