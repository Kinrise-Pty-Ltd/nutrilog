# HANDOVER.md

Project status and infrastructure map as of **25 July 2026**. This is a
point-in-time snapshot, not evergreen documentation — for that, see
[README.md](README.md) (what the app does) and [CLAUDE.md](CLAUDE.md)
(coding conventions).

## What this is

NutriLog — a food and health tracker originally built for Ruffy
(`ruffy@kingroup.com.au`), extended to multi-user. Owner/admin:
`admin_mwebb@kingroup.com.au`. Live at
**https://nutrilog-app.azurewebsites.net**.

## Azure infrastructure

Subscription: **KGRP-GENERAL-PRD-1** (`f1baa875-8498-41fd-9310-c79636ed234a`),
tenant **KinGroup** (`700f8417-d2f9-4c0a-9841-9579aaeb0581`) — a different
Azure tenant/subscription from the other Kinrise apps. Resource group:
**`nutrilog-rg`**, region **Australia East** (except one resource, noted
below).

| Resource | Name | Purpose |
|---|---|---|
| App Service Plan | `nutrilog-plan` (Linux, B1 Basic) | Hosts the app |
| App Service | `nutrilog-app` | The Flask app, Python 3.12 |
| SQL Server | `nutrilog-sql.database.windows.net` | Logical server |
| SQL Database | `nutrilog-db` (Basic tier, ~$5/mo) | Production data |
| Cognitive Services | `nutrilog-vision` (F0 free, **australiaeast**) | Food photo tags |
| Cognitive Services | `nutrilog-vision-caption` (F0 free, **southeastasia**) | Food photo captions — `caption` isn't available in australiaeast, hence the second resource in a different region |
| Managed Identity | `oidc-msi-96f4` | GitHub Actions OIDC login for deploy |

**SQL firewall**: only `AllowAzureServices` (0.0.0.0/0.0.0.0, the
Azure-services special rule) should be present. If you see any other rule
(e.g. `TempDebugAccess`), that's leftover from live debugging and should be
removed — temporary IP rules were added and removed several times during
development; double-check none were left behind.

**Cost**: SQL Basic (~$5 AUD/mo) is the only ongoing cost — both Vision
resources are on the free tier (5,000 calls/month each).

## Entra ID (Azure AD) app registration

**"NutriLog App Service Auth"** — Client ID
`90cab7eb-7eb0-4988-a355-cb3373057f60`, single-tenant (KGRP only). Serves
**two purposes** with the same registration:
1. Easy Auth relying party for the web login (redirect URI
   `https://nutrilog-app.azurewebsites.net/.auth/login/aad/callback`)
2. OAuth resource/client for the MCP server → Copilot Studio connection
   (see below)

**Enterprise Application**: "User assignment required" = **Yes** — this is
the allow-list. Only assigned users can sign in at all. Currently assigned:
`ruffy@kingroup.com.au`, `admin_mwebb@kingroup.com.au`. **Adding a new user
to NutriLog means assigning them here in Entra ID — no code or deploy
needed.**

**Client secrets** (both 2-year expiry, ~July 2028):
- `easyauth-secret` — used by Easy Auth for the web login flow, stored as
  the `MICROSOFT_PROVIDER_AUTHENTICATION_SECRET` app setting
- `copilot-studio-mcp` — dedicated secret for the Copilot Studio OAuth
  connection to `/api/mcp` (kept separate from the web login's secret for
  clean rotation)

**Redirect URIs registered** (Web platform):
- `https://nutrilog-app.azurewebsites.net/.auth/login/aad/callback` (web login)
- `https://global.consent.azure-apim.net/redirect/cr17a-5fnutrilog-2dmcp2-5f1e0b27a5ecb68f74`
  (Copilot Studio's Power Platform connector consent callback)

**Application ID URI**: `api://90cab7eb-7eb0-4988-a355-cb3373057f60`

## Easy Auth configuration

Configured via `authsettingsV2` (not the classic v1 schema): Azure AD only
(every other built-in provider — Apple/Facebook/GitHub/Google/legacy MSA —
explicitly disabled), `unauthenticatedClientAction: RedirectToLoginPage`,
**`/api/health/ingest` excluded** from the auth gate (see CLAUDE.md for
why). HTTPS-only is enabled on the App Service.

## GitHub / deployment

Repo: **[Kinrise-Pty-Ltd/nutrilog](https://github.com/Kinrise-Pty-Ltd/nutrilog)**
(recently transferred from `MikeWebbKin/nutrilog` — if you hit
`AADSTS700213`-style federated-credential errors after any future repo
transfer, update `oidc-msi-96f4`'s federated credential subject to match
the new `repo:Org/name:ref:refs/heads/main`).

Push to `main` → GitHub Actions (`.github/workflows/main_nutrilog-app.yml`)
builds and deploys automatically via OneDeploy. No manual deploy step.
**Two deploys triggered within ~1 minute of each other will collide with a
409 Conflict** — Azure only allows one deployment at a time. If that
happens, just re-run the failed workflow once the first one finishes.

## App Service application settings (names only — values live in Azure)

`AZURE_SQL_CONNECTION_STRING`, `AZURE_VISION_ENDPOINT`/`AZURE_VISION_KEY`,
`AZURE_VISION_CAPTION_ENDPOINT`/`AZURE_VISION_CAPTION_KEY`,
`MICROSOFT_PROVIDER_AUTHENTICATION_SECRET`, `FLASK_SECRET_KEY`,
`SCM_DO_BUILD_DURING_DEPLOYMENT`, `WEBSITES_ENABLE_APP_SERVICE_STORAGE`.

`DB_PATH` also exists but is **unused dead weight** — leftover from before
the Azure SQL migration, the code never reads it. Harmless, safe to remove,
never got around to it.

Not yet set (Oura still blocked — see below): `OURA_CLIENT_ID`,
`OURA_CLIENT_SECRET`, `OURA_REDIRECT_URI`.

## Feature status

| Feature | Status |
|---|---|
| Multi-user auth, calendar, camera scan, barcode scan | ✅ Live |
| Per-user food catalog + delegate ("act as") access | ✅ Built, tested locally against a simulated copy of production's current data shape — **not yet deployed**, see below |
| Azure AI Vision food recognition | ✅ Live (tags + caption, two-region setup) |
| iPhone Health | ✅ Live, but **Ruffy hasn't set up the Shortcuts automation yet** — shows demo data |
| Oura Ring | ⚠️ **Blocked** — Ruffy needs to register an OAuth app at cloud.ouraring.com ("My Applications", redirect URI `https://nutrilog-app.azurewebsites.net/api/oura/callback`) and send the client ID/secret. Shows demo data until then. |
| MCP server (`/api/mcp`) | ✅ Deployed and verified working standalone |
| Copilot Studio connection | 🔧 **In progress** — see below |

### Per-user catalog + delegate access — what's changing, and the deploy risk

`categories`/`food_items` used to be one shared catalog across every user
(deliberately, for a 2-user app). As of this work they're **per-user**:
each user gets their own private catalog (seeded with the same starter set
Ruffy originally had), and a stored-XSS fix was applied alongside it (see
`SECURITY_REVIEW.md`).

New: **delegated access** — an owner can grant another Entra-assigned user
full access to their own account (data + config) by email, self-service,
from Admin's "Delegate Access" section. This is specifically for **Ruffy's
executive assistant**, who needs access to his log/catalog/settings via the
website. Before she can use it: **she needs her own KinGroup (Entra)
account assigned in the "NutriLog App Service Auth" Enterprise Application**
(same allow-list step as any other user — see the Entra section above), and
Ruffy needs to grant her access once from his own Admin page after that.

**Deploy risk**: this includes a one-time production data migration
(`db.py`'s `_migrate_catalog_to_per_user()`) that clones the existing shared
catalog into a private copy per existing user and remaps their food_log
history to point at their own clone — the shared originals are left behind
(orphaned, not deleted) rather than risking a destructive `DROP`/`DELETE`
against production data. It also drops `categories.name`'s global `UNIQUE`
constraint (two users both having "Breakfast" is now expected). Tested
thoroughly against a locally-reconstructed copy of production's current
schema+data shape (see the session that built this for the exact test
script), including idempotency (safe to run `init_db()` twice) — but this is
the same category of change (schema migration touching an already-populated
production table) that caused the July 25 barcode outage, so: **take an
Azure SQL point-in-time-restore-eligible backup point before merging this**
(Basic tier has automatic backups, but confirm a recent restore point
exists), and watch `az webapp log tail` through the first restart after
deploy.

### Copilot Studio integration — where it's up to

Building a Copilot Studio agent connected to `/api/mcp` via manual OAuth
2.0 config (not Dynamic Discovery — the MCP server doesn't expose OAuth
metadata discovery, so Dynamic Discovery would fail):

- Authorization/Token/Refresh URL: `https://login.microsoftonline.com/700f8417-d2f9-4c0a-9841-9579aaeb0581/oauth2/v2.0/{authorize,token,token}`
- Client ID: `90cab7eb-7eb0-4988-a355-cb3373057f60`, secret: `copilot-studio-mcp` (see above)
- **Scope had to be the bare GUID form** — `90cab7eb-7eb0-4988-a355-cb3373057f60/.default`, not the `api://` URI form — because the client and the resource are the same app registration, which triggers Entra's `AADSTS90009` "app requesting a token for itself" restriction unless the resource is specified as a GUID.
- Hit and fixed `AADSTS50011` (redirect URI mismatch) by adding Copilot Studio's consent callback URL to the app registration — see redirect URIs above.
- **Not yet confirmed fully working end-to-end** (tool discovery + a real chat query hasn't been verified in this session) — pick up from here.

Once it's confirmed working: it can publish to multiple Copilot Studio
channels, including **Microsoft 365 Copilot itself** — no separate
"declarative agent" build needed for that.

## Deferred / not started

These were discussed and deliberately parked, not forgotten:

- **Weekly emailed health report** — needs decisions on scoring approach
  (rules-based vs LLM-generated feedback text), email sender (leaning Azure
  Communication Services Email over Graph, to avoid broadening the Easy
  Auth app registration's permissions), and the trigger mechanism (leaning
  an Azure Logic App on a schedule calling a new token-protected endpoint).
- **LLM-based food recognition** (Claude or GPT-4 vision) — flagged as a
  quality upgrade over Azure AI Vision's tags/caption, needs a provider and
  API key decision.

## Incident history

**25 July 2026 — production outage, ~13 minutes.** PR #5 (barcode scanning)
added a `CREATE INDEX` on a new column in the *unconditional* part of
`schema_mssql.sql`, which ran before the column-migration step that
actually adds the column — fine on a fresh database, fatal against
production's pre-existing `food_items` table. Every app startup crashed
(`pyodbc.ProgrammingError: Column 'barcode' does not exist`). Root-caused by
reproducing directly against the production database (temporary firewall
access, removed after), fixed in PR #6, verified against production before
and after the fix. Full detail and the resulting rule for future migrations
are in [CLAUDE.md](CLAUDE.md) — the short version: **always test a schema
change against a database that already has the prior schema, not just a
fresh one.**

## Access

- Azure Portal / CLI: `admin_mwebb@kingroup.com.au` (KGRP subscription)
- GitHub repo: KinGroup org, `Kinrise-Pty-Ltd/nutrilog`
- App sign-in (Easy Auth): only Entra-assigned users, see above — assign
  new users directly in Entra ID's Enterprise Applications, no deploy needed
