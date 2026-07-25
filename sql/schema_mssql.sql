IF OBJECT_ID('dbo.users', 'U') IS NULL
CREATE TABLE dbo.users (
    id NVARCHAR(64) PRIMARY KEY,
    entra_oid NVARCHAR(64) UNIQUE NULL,
    email NVARCHAR(256) NOT NULL UNIQUE,
    display_name NVARCHAR(256) NULL,
    created_at DATETIME2 DEFAULT SYSUTCDATETIME()
);
GO

IF OBJECT_ID('dbo.categories', 'U') IS NULL
CREATE TABLE dbo.categories (
    id NVARCHAR(64) PRIMARY KEY,
    name NVARCHAR(200) NOT NULL UNIQUE,
    icon NVARCHAR(16) DEFAULT N'🍽️',
    sort_order INT DEFAULT 0,
    created_at DATETIME2 DEFAULT SYSUTCDATETIME()
);
GO

IF OBJECT_ID('dbo.food_items', 'U') IS NULL
CREATE TABLE dbo.food_items (
    id NVARCHAR(64) PRIMARY KEY,
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
    FOREIGN KEY (category_id) REFERENCES dbo.categories(id)
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
    raw_json NVARCHAR(MAX) NULL,
    is_demo BIT DEFAULT 0,
    synced_at DATETIME2 DEFAULT SYSUTCDATETIME(),
    FOREIGN KEY (user_id) REFERENCES dbo.users(id),
    CONSTRAINT UQ_iphone_health_user_date UNIQUE (user_id, date)
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'idx_food_items_barcode')
CREATE INDEX idx_food_items_barcode ON dbo.food_items(barcode);
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
