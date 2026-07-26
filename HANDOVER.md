# HANDOVER.md

Project status and infrastructure map as of **27 July 2026**. This is a
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
the allow-list. Only assigned users can sign in at all. Originally just
`ruffy@kingroup.com.au` and `admin_mwebb@kingroup.com.au`, but the `users`
table now has 5 distinct signed-in accounts (including what look like
domain-separated variants of the admin's own identity) — the current
Entra allow-list wasn't re-checked as part of this snapshot, so treat the
exact membership as **unverified**, not just these two. **Adding a new user
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
explicitly disabled), `unauthenticatedClientAction: RedirectToLoginPage`.

**`excludedPaths`** (bypasses the login gate entirely for these — everything
else, including every page route and all of `/api/*`, still requires an
Entra sign-in):
- `/api/health/ingest` — Health Auto Export's bearer-token ingest, see CLAUDE.md
- `/public/favicon/apple-touch-icon.png`, `favicon.ico`, `favicon-16x16.png`,
  `favicon-32x32.png`, `android-chrome-192x192.png`, `android-chrome-512x512.png`,
  `site.webmanifest`, and `/public/assets/NutriLog.png` — added 27 July so
  iOS can actually fetch the touch icon when a user taps "Add to Home
  Screen". Before this, the icon request got redirected to the Microsoft
  login page instead of the image, so iOS silently fell back to a
  generated letter icon. **Confirmed fixed and working** (real device test).
  Each file is listed individually — `az webapp auth update`'s
  `excludedPaths` does **not** support a `/public/*`-style wildcard prefix in
  practice (tried it first; requests still redirected to login even after
  the config saved correctly). Any new static asset added under `/public/`
  that needs to load before login has to be added to this list by exact
  path.

HTTPS-only is enabled on the App Service.

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
| Per-user food catalog + delegate ("act as") access | ✅ Live — see below |
| Voice logging, move-entry-between-meals, quick-add-new-food | ✅ Live |
| Azure AI Vision food recognition | ✅ Live (tags + caption, two-region setup) |
| iPhone Health (core: steps/active energy/weight/sleep) | ✅ Live — Ruffy has Health Auto Export sending real data |
| iPhone Health (optional measures: SpO2, HRV, body fat, VO2 max, distance, flights, mindful minutes, water) | ✅ Live, but **exact Health Auto Export field-name/unit mapping for these hasn't been confirmed against a real export** — check `az webapp log tail` for "Unrecognized Health Auto Export metric name(s)" if a newly-added one doesn't show data |
| Oura Ring | ⚠️ **Blocked** — Ruffy needs to register an OAuth app at cloud.ouraring.com ("My Applications", redirect URI `https://nutrilog-app.azurewebsites.net/api/oura/callback`) and send the client ID/secret. Shows demo data until then. |
| MCP server (`/api/mcp`) | ✅ Deployed and verified working standalone |
| Copilot Studio connection | 🔧 **In progress** — see below |
| Favicons + NutriLog logo | ✅ Live — added by a colleague (Riley Webb) via a PR outside this session's direct work; header text ("NutriLog" wordmark) was later removed in favour of just the enlarged (doubled, 27 July) logo image. "Add to Home Screen" icon confirmed working on a real iPhone as of 27 July (see Easy Auth section — needed an `excludedPaths` fix). |

### Per-user catalog + delegate access

`categories`/`food_items` used to be one shared catalog across every user
(deliberately, for a 2-user app). They're now **per-user**: each user has
their own private catalog (existing users' catalogs were split via a
one-time migration that clones the shared rows and remaps food_log history
— nothing was deleted, the shared originals are just orphaned/invisible
now), and a stored-XSS fix was applied alongside it (see
`SECURITY_REVIEW.md`).

**Delegated access**: an owner can grant another Entra-assigned user full
access to their own account (data + config) by email, self-service, from
Admin's "Delegate Access" section — built for **Ruffy's executive
assistant**. Before she can use it: **she needs her own KinGroup (Entra)
account assigned in the "NutriLog App Service Auth" Enterprise Application**
(same allow-list step as any other user — see the Entra section above), and
Ruffy needs to grant her access once from his own Admin page after that —
not confirmed yet whether this has actually happened.

The migration itself is deployed and was verified against a
locally-reconstructed copy of production's pre-migration schema+data shape
before shipping; a follow-up PR hardened it with an `sp_getapplock` (mssql)
against a theoretical race between this app's two gunicorn workers both
running the one-time migration simultaneously on first deploy (see
CLAUDE.md gotcha #6) — investigated after a duplication report that turned
out to be unrelated (multiple real sign-ins, not a bug), but the race was
real and worth closing regardless.

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

## Recent work (26 July)

- **HTTPS bug fix**: Azure's `httpsOnly` App Service setting was already
  correctly enforced, but `request.url_root` (used to build the iPhone
  Health ingest URL shown in Admin) was reporting `http://` even on the
  live site, because Flask wasn't trusting Azure's `X-Forwarded-Proto`
  header. Fixed with `ProxyFix` (see CLAUDE.md gotcha #7).
- **Health Auto Export support**: the app was built assuming a Shortcuts-
  style flat JSON body; Health Auto Export sends its own fixed
  metrics-grouped shape instead. Added a converter for it (see CLAUDE.md).
  A related Bearer-token-parsing bug (exact-case "Bearer " match) was also
  fixed — real-world apps that require typing the header in by hand aren't
  consistent about casing/spacing.
- **iPhone Health optional metrics**: beyond the always-shown core four,
  users can now add/remove individual extra measures (resting energy,
  exercise minutes, resting HR, SpO2, HRV, body fat %, VO2 max, distance,
  flights climbed, mindful minutes, water intake) from Admin. See CLAUDE.md
  for the field-naming caveat on the newer ones.
- **Health page**: added a 7/30/90-day range selector and interactive
  chart details (tap/hover any sparkline for the exact date+value, plus an
  always-visible low/high caption).
- **Voice logging, move-entry, quick-add-new-food**: added to the main log
  page — see README.md for what each does.

## Recent work (27 July)

- **Data-isolation review**: prompted by a user report of possibly seeing
  another user's data. Audited every query touching food_log, categories,
  food_items, delegate ("act as") access, Oura, Health, and the MCP tools —
  all correctly scoped by the signed-in user, re-validated per request. One
  real gap found and fixed: `POST /api/log` looked up the referenced food
  item by id alone with no ownership check, so a forged/foreign item id
  would have surfaced another user's private food item's name/macros
  into your log instead of 404ing. No root cause was confirmed for the
  original report itself — the most likely explanation is Delegate Access
  (a live grant would legitimately show another account's data through the
  account switcher), not a bug.
- **Logo doubled** across all 5 pages (42px → 84px; Admin 34px → 68px,
  since its busier header — logo + 4 nav links + theme toggle — would
  otherwise overflow horizontally at mobile widths; its header/nav now wrap
  onto a second row instead of clipping).
- **"Add to Home Screen" icon fix**: see the Easy Auth section above —
  `excludedPaths` needed the icon/manifest files added by exact path
  (wildcard doesn't work). Confirmed fixed on a real device.

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
