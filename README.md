# NutriLog 🥗

A mobile-friendly, multi-user food and health tracker. Built for Ruffy,
running on Flask + Azure SQL, deployed at
[nutrilog-app.azurewebsites.net](https://nutrilog-app.azurewebsites.net).

For infrastructure details, credentials map, and current project status, see
[HANDOVER.md](HANDOVER.md). For coding conventions and architecture notes
(useful for AI assistants or anyone picking up this codebase), see
[CLAUDE.md](CLAUDE.md).

## Features

- **Food log** (`/`) — daily log across 7 meal slots, search or scan to add
  items, quantity picker with live calorie preview, daily macro totals
- **Voice logging** — tap the mic, say something like "two eggs for
  breakfast"; it detects the meal (from what you said, or the time of day),
  matches it against your catalog, and always confirms the amount before
  logging anything. Falls back to a plain text box (still works via the
  keyboard's own dictation button) on browsers without speech recognition.
- **Move a logged entry** between meals — for food logged after the fact
  under the wrong meal slot
- **Quick-add** — if a search (typed or voice) doesn't match anything in
  your catalog, add it as a new item on the spot instead of dead-ending
- **Camera food recognition** — snap a photo, matched against the food
  catalog via Azure AI Vision (tags + caption)
- **Barcode scanning** — for packaged food, scans a barcode and looks up
  exact nutrition via [Open Food Facts](https://openfoodfacts.org) (free,
  no API key)
- **Calendar** (`/calendar`) — Month / Week / List views over your log
- **Oura Ring** (`/oura`) — readiness, sleep, HRV, recovery, and more (15
  metrics); shows demo data until connected
- **iPhone Health** (`/health`) — steps, active energy, weight, sleep always
  shown, plus optional measures (resting energy, exercise minutes, resting
  HR, SpO2, HRV, body fat %, VO2 max, distance, flights climbed, mindful
  minutes, water intake) you add/remove individually from Admin. 7/30/90-day
  range selector, tap-or-hover any graph for the exact date/value. Fed by a
  Shortcuts automation or the Health Auto Export app pushing to a
  bearer-token ingest endpoint; shows demo data until connected.
- **Admin** (`/admin`) — manage your own food catalog, integrations
  (Oura, iPhone Health), and who has delegate access to your account
- **Multi-user** — each signed-in user has their own private log *and*
  catalog (new users get seeded with the same starter set Ruffy originally
  had, editable independently thereafter)
- **Delegate access** — grant someone else (e.g. an assistant) full access
  to your own account's data and config; they get an account switcher after
  signing in with their own KinGroup account. Self-service, managed from
  Admin's "Delegate Access" section. See `app.py`'s `/api/delegates*` and
  `/api/act-as` routes.
- **MCP server** (`/api/mcp`) — exposes a user's data to MCP clients (e.g. a
  Copilot Studio agent) as read-only tools
- Light/dark theme toggle

## Local development

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5000 (Log), `/admin`, `/calendar`, `/oura`, `/health`.

No Easy Auth locally — every request is treated as a single dev user
(`DEV_USER_EMAIL`, defaults to `dev@localhost`). Set it to test as a specific
user:

```bash
set DEV_USER_EMAIL=ruffy@kingroup.com.au   # Windows
python app.py
```

Local dev uses a SQLite file (`nutrilog.db`, gitignored, auto-created on
first run — delete it any time to reset to the seeded catalog). Production
uses Azure SQL instead, selected automatically by the presence of
`AZURE_SQL_CONNECTION_STRING` — see `db.py`.

Camera/barcode scanning and Oura/Health integrations degrade gracefully
(buttons hide, demo data shows) when their env vars aren't set — you don't
need real Azure Vision or Oura credentials to develop everything else.

## Architecture at a glance

Vanilla HTML/CSS/JS on the frontend (no build step, no framework — each
`public/*.html` page is self-contained) and a small set of single-purpose
Python modules on the backend:

| File | Responsibility |
|---|---|
| `app.py` | Flask routes, auth gate (`before_request`) |
| `db.py` | Dual SQLite(dev)/Azure SQL(prod) query layer + schema migrations |
| `auth.py` | Resolves the signed-in user from Easy Auth headers |
| `vision.py` | Azure AI Vision food-photo recognition |
| `barcode.py` | Open Food Facts barcode lookup |
| `oura.py` | Oura OAuth2 + data fetch/cache + demo data |
| `health.py` | iPhone Health bearer-token ingest + demo data |
| `mcp_server.py` | MCP protocol (JSON-RPC) for Copilot Studio / other clients |
| `migrate.py` | One-off SQLite → Azure SQL migration script |

## Deployment

Deployment is **automatic**: pushing to `main` on
[Kinrise-Pty-Ltd/nutrilog](https://github.com/Kinrise-Pty-Ltd/nutrilog)
triggers a GitHub Actions workflow that builds and deploys to the Azure App
Service. There's no manual deploy step — don't push to `main` directly for
anything you haven't verified locally first; open a PR instead.

Full infrastructure details (Azure resources, Entra app registration,
secrets, known issues): see [HANDOVER.md](HANDOVER.md).
