CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    entra_oid TEXT UNIQUE,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS categories (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    icon TEXT DEFAULT '🍽️',
    sort_order INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS food_items (
    id TEXT PRIMARY KEY,
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
    FOREIGN KEY (category_id) REFERENCES categories(id)
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

CREATE INDEX IF NOT EXISTS idx_food_log_user_date ON food_log(user_id, log_date);
CREATE INDEX IF NOT EXISTS idx_oura_daily_user_date ON oura_daily(user_id, date);
CREATE INDEX IF NOT EXISTS idx_iphone_health_user_date ON iphone_health_daily(user_id, date);
