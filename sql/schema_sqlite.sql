CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    entra_oid TEXT UNIQUE,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- categories/food_items are per-user (each user gets their own catalog,
-- seeded with the same starter set on account creation) — see
-- db.py's _migrate_catalog_to_per_user() for how existing shared-catalog
-- installs get split, and CLAUDE.md for why `name` isn't UNIQUE here
-- (two users both having a "Breakfast" category is expected).
CREATE TABLE IF NOT EXISTS categories (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    icon TEXT DEFAULT '🍽️',
    sort_order INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS food_items (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    category_id TEXT NOT NULL,
    name TEXT NOT NULL,
    serving_size TEXT NOT NULL,
    serving_unit TEXT DEFAULT 'g',
    calories INTEGER NOT NULL,
    protein_g REAL DEFAULT 0,
    carbs_g REAL DEFAULT 0,
    fat_g REAL DEFAULT 0,
    notes TEXT,
    barcode TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (category_id) REFERENCES categories(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS food_log (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    food_item_id TEXT NOT NULL,
    meal_slot TEXT NOT NULL,
    log_date TEXT NOT NULL,
    quantity REAL DEFAULT 1.0,
    calories_actual INTEGER,
    logged_at TEXT DEFAULT (datetime('now')),
    notes TEXT,
    FOREIGN KEY (food_item_id) REFERENCES food_items(id),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS oura_tokens (
    user_id TEXT PRIMARY KEY,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    scope TEXT,
    connected_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS oura_daily (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,
    sleep_score INTEGER,
    readiness_score INTEGER,
    activity_score INTEGER,
    steps INTEGER,
    resting_hr INTEGER,
    total_sleep_minutes INTEGER,
    calories_burned INTEGER,
    hrv_ms REAL,
    sleep_efficiency INTEGER,
    deep_sleep_minutes INTEGER,
    rem_sleep_minutes INTEGER,
    temperature_deviation REAL,
    spo2_percent REAL,
    respiratory_rate REAL,
    physical_recovery_score INTEGER,
    cognitive_recovery_score INTEGER,
    illness_risk_score INTEGER,
    raw_json TEXT,
    is_demo INTEGER DEFAULT 0,
    synced_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE (user_id, date)
);

CREATE TABLE IF NOT EXISTS iphone_health_tokens (
    user_id TEXT PRIMARY KEY,
    api_token TEXT NOT NULL UNIQUE,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS iphone_health_daily (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    date TEXT NOT NULL,
    steps INTEGER,
    active_energy_kcal INTEGER,
    resting_energy_kcal INTEGER,
    exercise_minutes INTEGER,
    weight_kg REAL,
    resting_hr INTEGER,
    sleep_minutes INTEGER,
    raw_json TEXT,
    is_demo INTEGER DEFAULT 0,
    synced_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE (user_id, date)
);

-- Self-service delegation: an owner grants their own account's data/config
-- access to another Entra-assigned user by email (matched at act-as time,
-- not at grant time, so it works even before the delegate has ever signed
-- in). See app.py's /api/delegates* and /api/act-as routes.
CREATE TABLE IF NOT EXISTS user_delegates (
    id TEXT PRIMARY KEY,
    owner_user_id TEXT NOT NULL,
    delegate_email TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (owner_user_id) REFERENCES users(id),
    UNIQUE (owner_user_id, delegate_email)
);

CREATE INDEX IF NOT EXISTS idx_food_log_user_date ON food_log(user_id, log_date);
CREATE INDEX IF NOT EXISTS idx_oura_daily_user_date ON oura_daily(user_id, date);
CREATE INDEX IF NOT EXISTS idx_iphone_health_user_date ON iphone_health_daily(user_id, date);
CREATE INDEX IF NOT EXISTS idx_user_delegates_email ON user_delegates(delegate_email);

-- idx_categories_user / idx_food_items_user are NOT declared here on purpose:
-- user_id is a new column on tables that already exist in production, so
-- (per CLAUDE.md) their index must be created via _ensure_index() in db.py
-- *after* the column migration runs, not as a raw CREATE INDEX here — this
-- script runs unconditionally before that migration on any database where
-- categories/food_items predate this change.
