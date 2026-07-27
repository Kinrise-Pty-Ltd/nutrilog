IF OBJECT_ID('dbo.users', 'U') IS NULL
CREATE TABLE dbo.users (
    id NVARCHAR(64) PRIMARY KEY,
    entra_oid NVARCHAR(64) UNIQUE NULL,
    email NVARCHAR(256) NOT NULL UNIQUE,
    display_name NVARCHAR(256) NULL,
    created_at DATETIME2 DEFAULT SYSUTCDATETIME()
);
GO

-- categories/food_items are per-user (each user gets their own catalog,
-- seeded with the same starter set on account creation) — see
-- db.py's _migrate_catalog_to_per_user() for how the previously-shared
-- catalog gets split, and CLAUDE.md for why `name` isn't UNIQUE here
-- (two users both having a "Breakfast" category is expected).
IF OBJECT_ID('dbo.categories', 'U') IS NULL
CREATE TABLE dbo.categories (
    id NVARCHAR(64) PRIMARY KEY,
    user_id NVARCHAR(64) NOT NULL,
    name NVARCHAR(200) NOT NULL,
    icon NVARCHAR(16) DEFAULT N'🍽️',
    sort_order INT DEFAULT 0,
    created_at DATETIME2 DEFAULT SYSUTCDATETIME(),
    FOREIGN KEY (user_id) REFERENCES dbo.users(id)
);
GO

IF OBJECT_ID('dbo.food_items', 'U') IS NULL
CREATE TABLE dbo.food_items (
    id NVARCHAR(64) PRIMARY KEY,
    user_id NVARCHAR(64) NOT NULL,
    category_id NVARCHAR(64) NOT NULL,
    name NVARCHAR(300) NOT NULL,
    serving_size NVARCHAR(50) NOT NULL,
    serving_unit NVARCHAR(20) DEFAULT 'g',
    calories INT NOT NULL,
    protein_g FLOAT DEFAULT 0,
    carbs_g FLOAT DEFAULT 0,
    fat_g FLOAT DEFAULT 0,
    notes NVARCHAR(1000) NULL,
    barcode NVARCHAR(64) NULL,
    created_at DATETIME2 DEFAULT SYSUTCDATETIME(),
    FOREIGN KEY (category_id) REFERENCES dbo.categories(id),
    FOREIGN KEY (user_id) REFERENCES dbo.users(id)
);
GO

IF OBJECT_ID('dbo.food_log', 'U') IS NULL
CREATE TABLE dbo.food_log (
    id NVARCHAR(64) PRIMARY KEY,
    user_id NVARCHAR(64) NOT NULL,
    food_item_id NVARCHAR(64) NOT NULL,
    meal_slot NVARCHAR(64) NOT NULL,
    log_date NVARCHAR(10) NOT NULL,
    quantity FLOAT DEFAULT 1.0,
    calories_actual INT,
    logged_at DATETIME2 DEFAULT SYSUTCDATETIME(),
    notes NVARCHAR(1000) NULL,
    FOREIGN KEY (food_item_id) REFERENCES dbo.food_items(id),
    FOREIGN KEY (user_id) REFERENCES dbo.users(id)
);
GO

IF OBJECT_ID('dbo.oura_tokens', 'U') IS NULL
CREATE TABLE dbo.oura_tokens (
    user_id NVARCHAR(64) PRIMARY KEY,
    access_token NVARCHAR(2000) NOT NULL,
    refresh_token NVARCHAR(2000) NOT NULL,
    expires_at DATETIME2 NOT NULL,
    scope NVARCHAR(200) NULL,
    connected_at DATETIME2 DEFAULT SYSUTCDATETIME(),
    FOREIGN KEY (user_id) REFERENCES dbo.users(id)
);
GO

IF OBJECT_ID('dbo.oura_daily', 'U') IS NULL
CREATE TABLE dbo.oura_daily (
    id NVARCHAR(64) PRIMARY KEY,
    user_id NVARCHAR(64) NOT NULL,
    date NVARCHAR(10) NOT NULL,
    sleep_score INT NULL,
    readiness_score INT NULL,
    activity_score INT NULL,
    steps INT NULL,
    resting_hr INT NULL,
    total_sleep_minutes INT NULL,
    calories_burned INT NULL,
    hrv_ms FLOAT NULL,
    sleep_efficiency INT NULL,
    deep_sleep_minutes INT NULL,
    rem_sleep_minutes INT NULL,
    temperature_deviation FLOAT NULL,
    spo2_percent FLOAT NULL,
    respiratory_rate FLOAT NULL,
    physical_recovery_score INT NULL,
    cognitive_recovery_score INT NULL,
    illness_risk_score INT NULL,
    raw_json NVARCHAR(MAX) NULL,
    is_demo BIT DEFAULT 0,
    synced_at DATETIME2 DEFAULT SYSUTCDATETIME(),
    FOREIGN KEY (user_id) REFERENCES dbo.users(id),
    CONSTRAINT UQ_oura_daily_user_date UNIQUE (user_id, date)
);
GO

IF OBJECT_ID('dbo.iphone_health_tokens', 'U') IS NULL
CREATE TABLE dbo.iphone_health_tokens (
    user_id NVARCHAR(64) PRIMARY KEY,
    api_token NVARCHAR(128) NOT NULL UNIQUE,
    created_at DATETIME2 DEFAULT SYSUTCDATETIME(),
    FOREIGN KEY (user_id) REFERENCES dbo.users(id)
);
GO

IF OBJECT_ID('dbo.mirror_api_tokens', 'U') IS NULL
CREATE TABLE dbo.mirror_api_tokens (
    user_id NVARCHAR(64) PRIMARY KEY,
    api_token NVARCHAR(128) NOT NULL UNIQUE,
    created_at DATETIME2 DEFAULT SYSUTCDATETIME(),
    FOREIGN KEY (user_id) REFERENCES dbo.users(id)
);
GO

IF OBJECT_ID('dbo.iphone_health_daily', 'U') IS NULL
CREATE TABLE dbo.iphone_health_daily (
    id NVARCHAR(64) PRIMARY KEY,
    user_id NVARCHAR(64) NOT NULL,
    date NVARCHAR(10) NOT NULL,
    steps INT NULL,
    active_energy_kcal INT NULL,
    resting_energy_kcal INT NULL,
    exercise_minutes INT NULL,
    weight_kg FLOAT NULL,
    resting_hr INT NULL,
    sleep_minutes INT NULL,
    spo2_percent FLOAT NULL,
    hrv_ms FLOAT NULL,
    body_fat_percent FLOAT NULL,
    vo2_max FLOAT NULL,
    distance_km FLOAT NULL,
    flights_climbed INT NULL,
    mindful_minutes INT NULL,
    water_ml INT NULL,
    raw_json NVARCHAR(MAX) NULL,
    is_demo BIT DEFAULT 0,
    synced_at DATETIME2 DEFAULT SYSUTCDATETIME(),
    FOREIGN KEY (user_id) REFERENCES dbo.users(id),
    CONSTRAINT UQ_iphone_health_user_date UNIQUE (user_id, date)
);
GO

-- Which OPTIONAL health measures (beyond the always-shown core four —
-- steps, active energy, weight, sleep) a user has chosen to see on their
-- Health page. See health.py's METRIC_CATALOG for the full supported set.
IF OBJECT_ID('dbo.iphone_health_user_metrics', 'U') IS NULL
CREATE TABLE dbo.iphone_health_user_metrics (
    user_id NVARCHAR(64) NOT NULL,
    metric_key NVARCHAR(64) NOT NULL,
    added_at DATETIME2 DEFAULT SYSUTCDATETIME(),
    CONSTRAINT PK_iphone_health_user_metrics PRIMARY KEY (user_id, metric_key),
    FOREIGN KEY (user_id) REFERENCES dbo.users(id)
);
GO

-- Self-service delegation: an owner grants their own account's data/config
-- access to another Entra-assigned user by email (matched at act-as time,
-- not at grant time, so it works even before the delegate has ever signed
-- in). See app.py's /api/delegates* and /api/act-as routes.
IF OBJECT_ID('dbo.user_delegates', 'U') IS NULL
CREATE TABLE dbo.user_delegates (
    id NVARCHAR(64) PRIMARY KEY,
    owner_user_id NVARCHAR(64) NOT NULL,
    delegate_email NVARCHAR(256) NOT NULL,
    created_at DATETIME2 DEFAULT SYSUTCDATETIME(),
    FOREIGN KEY (owner_user_id) REFERENCES dbo.users(id),
    CONSTRAINT UQ_user_delegates_owner_email UNIQUE (owner_user_id, delegate_email)
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'idx_food_log_user_date')
CREATE INDEX idx_food_log_user_date ON dbo.food_log(user_id, log_date);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'idx_oura_daily_user_date')
CREATE INDEX idx_oura_daily_user_date ON dbo.oura_daily(user_id, date);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'idx_iphone_health_user_date')
CREATE INDEX idx_iphone_health_user_date ON dbo.iphone_health_daily(user_id, date);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'idx_user_delegates_email')
CREATE INDEX idx_user_delegates_email ON dbo.user_delegates(delegate_email);
GO

-- idx_categories_user / idx_food_items_user are NOT declared here on purpose:
-- user_id is a new column on tables that already exist in production, so
-- (per CLAUDE.md) their index must be created via _ensure_index() in db.py
-- *after* the column migration runs, not as a raw CREATE INDEX here — this
-- script runs unconditionally before that migration on any database where
-- categories/food_items predate this change.
