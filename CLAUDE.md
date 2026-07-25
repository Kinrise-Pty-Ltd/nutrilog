# CLAUDE.md

Guidance for AI assistants (and anyone else) working in this repo. For what
the app does, see [README.md](README.md). For infrastructure/credentials/
current status, see [HANDOVER.md](HANDOVER.md).

## The big things to not get wrong

1. **Production runs under gunicorn, not `python app.py`.** `startup.sh` /
   the App Service startup command runs `gunicorn app:app`, which *imports*
   `app.py` as a module — it never executes the `if __name__ == '__main__':`
   block. Anything that must run in production (like `init_db()`) has to
   happen at **module level**, not inside that guard. This has already bitten
   this project once.

2. **Test schema migrations against a database that already has the *prior*
   schema, not just a fresh one.** `db.py`'s `CREATE TABLE IF NOT EXISTS` is
   a no-op on a table that already exists — so a new column added to a
   `CREATE TABLE` statement in `sql/schema_*.sql` will never actually reach
   an existing database. New columns must *also* be registered in
   `db.py`'s `_migrate_columns()` dict, and any new index on a new column
   must be created via `_ensure_index()` **after** the column migration runs
   — never as a raw `CREATE INDEX` in the schema SQL files, because that
   runs unconditionally *before* `_migrate_columns()` and will crash the app
   on any database where the table predates the new column. This exact
   mistake took production down once (barcode column/index, July 2026) — the
   bug only appeared against the real database, not fresh local ones, because
   local testing always used a freshly-created SQLite file.

3. **Before switching git branches, commit or stash first.** `git checkout`
   silently discards uncommitted changes with no warning in this environment
   — this has happened twice in this project's history, losing work that had
   to be redone. Always `git add && git commit` (even a throwaway WIP commit)
   before any branch switch, then continue.

4. **On Windows, kill stray Python processes before testing.** Flask's dev
   server (`python app.py`) run repeatedly across a session leaves multiple
   processes bound to port 5000, and `pkill -f app.py` doesn't reliably match
   them on Windows/Git Bash. Use `taskkill //F //IM python.exe` before
   starting a fresh test run if you get unexplained stale behavior (e.g. a
   config change not taking effect).

## Architecture

- **No build step.** Every `public/*.html` file is a fully self-contained
  page — inline `<style>`, inline `<script>`, no bundler, no shared JS/CSS
  file (there's no mechanism to share one). When changing something
  cross-cutting (the theme toggle, the bottom nav, the KinGroup footer),
  it has to be edited in every page that has it. Grep for the pattern
  first to find all copies.
- **Dual database backend** (`db.py`): SQLite for local dev, Azure SQL in
  production, selected by whether `AZURE_SQL_CONNECTION_STRING` is set.
  Both are queried with `?` placeholders (pyodbc and sqlite3 both accept
  this), so almost all query code is backend-agnostic — the exceptions are
  `LIMIT`/`TOP` (see `get_log_history` in `app.py` for the pattern) and
  schema DDL (two separate `sql/schema_*.sql` files).
- **Auth**: production sits behind Azure App Service Easy Auth (Entra ID),
  which injects `X-MS-CLIENT-PRINCIPAL-*` headers on every request.
  `auth.py`'s `load_current_user()` reads those, resolving/auto-provisioning
  a `users` row. Locally (no Easy Auth in front of the dev server), it falls
  back to a single `DEV_USER_EMAIL`. The `food_log`, Oura, and Health tables
  are scoped per-user; `categories`/`food_items` (the food catalog) are
  intentionally global/shared, managed centrally via Admin.
- **The `/api/health/ingest` and `/api/mcp` routes are the two exceptions**
  to "every route sits behind the same auth": `health/ingest` is called by
  an unattended device automation (not a browser), authenticated by its own
  per-user bearer token instead of an Easy Auth session — see the special
  case at the top of `attach_user()` in `app.py`. `/api/mcp` *is* behind
  the normal Easy Auth gate (nothing special needed there — Copilot Studio
  presents an Entra ID token for the signed-in user, same as a browser would).
- **Third-party API integrations degrade gracefully when unconfigured**:
  Vision, Oura, and Health all check `is_configured()`/`is_connected()` and
  either hide their UI affordance or return demo data rather than erroring.
  Preserve this pattern for any new integration — don't make local dev or a
  partially-configured deployment hard-fail on a missing external credential.

## Conventions

- Comments explain *why*, not *what* — see the top-level instructions this
  assistant follows. Don't add narration comments to obvious code.
- New Oura/Health metrics: if a value isn't a genuine field from the
  provider's API, say so in both a code comment and the UI (see `oura.py`'s
  module docstring and the "approximated" captions in `public/oura.html`).
  Don't present a heuristic or approximation as an official metric.
- When adding a new `/api/*` endpoint, it's automatically covered by the
  existing Easy Auth gate (anything under `/api/` requires `g.user`) unless
  you add a special case in `attach_user()` — do that only for genuinely
  non-browser, non-session callers (like the health ingest token pattern),
  and make sure it's also excluded from Easy Auth's platform-level
  `globalValidation.excludedPaths` if it needs to work in production before
  a session exists.
- Deploy is via PR → merge to `main` → GitHub Actions (no manual deploy
  step). Verify locally first; don't push straight to `main`.
