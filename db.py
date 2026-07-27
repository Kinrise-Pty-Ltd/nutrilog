"""Database access layer.

Two backends, selected by the presence of AZURE_SQL_CONNECTION_STRING:
  - sqlite (default): local file nutrilog.db, used for local development.
  - mssql: Azure SQL via pyodbc, used in production.

Both backends are queried with '?' placeholders (pyodbc's ODBC driver and
sqlite3 both accept this), so almost all query code is backend-agnostic.
"""
import os
import sqlite3
import uuid
from datetime import date

BACKEND = 'mssql' if os.environ.get('AZURE_SQL_CONNECTION_STRING') else 'sqlite'

SQLITE_PATH = os.path.join(os.path.dirname(__file__), 'nutrilog.db')
SCHEMA_DIR = os.path.join(os.path.dirname(__file__), 'sql')

if BACKEND == 'mssql':
    import pyodbc


class Db:
    def __init__(self, conn):
        self.conn = conn
        self.backend = BACKEND

    def execute(self, sql, params=()):
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return cur

    def query(self, sql, params=()):
        cur = self.execute(sql, params)
        if not cur.description:
            return []
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def query_one(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.conn.commit()
        self.close()


def get_db():
    if BACKEND == 'mssql':
        conn = pyodbc.connect(os.environ['AZURE_SQL_CONNECTION_STRING'])
    else:
        conn = sqlite3.connect(SQLITE_PATH)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
    return Db(conn)


def insert_food_log_entry(user_id, food_item_id, meal_slot, quantity, log_date=None, notes=None):
    """Shared by the /api/log POST route and the Mirror integration's voice
    logging — one insert path, not two. Raises ValueError if the item (or
    the meal_slot category) doesn't belong to this user."""
    log_date = log_date or date.today().isoformat()
    with get_db() as db:
        item = db.query_one(
            "SELECT calories FROM food_items WHERE id=? AND user_id=?", (food_item_id, user_id)
        )
        if not item:
            raise ValueError('Food item not found')

        log_id = str(uuid.uuid4())
        calories_actual = int(item['calories'] * quantity)
        db.execute(
            """INSERT INTO food_log (id, user_id, food_item_id, meal_slot, log_date, quantity, calories_actual, notes)
               VALUES (?,?,?,?,?,?,?,?)""",
            (log_id, user_id, food_item_id, meal_slot, log_date, quantity, calories_actual, notes)
        )
        row = db.query_one(
            """SELECT fl.*, fi.name as food_name, fi.serving_size, fi.serving_unit,
               c.name as category_name, c.icon as category_icon
               FROM food_log fl JOIN food_items fi ON fl.food_item_id=fi.id
               JOIN categories c ON fl.meal_slot=c.id
               WHERE fl.id=?""",
            (log_id,)
        )
        return row


def init_db():
    schema_file = 'schema_mssql.sql' if BACKEND == 'mssql' else 'schema_sqlite.sql'
    with open(os.path.join(SCHEMA_DIR, schema_file), encoding='utf-8') as f:
        script = f.read()

    with get_db() as db:
        if BACKEND == 'mssql':
            for statement in script.split(';\nGO'):
                statement = statement.strip()
                if statement:
                    db.execute(statement)
        else:
            db.conn.executescript(script)

    _migrate_columns('oura_daily', OURA_DAILY_NEW_COLUMNS)
    _migrate_columns('food_items', FOOD_ITEMS_NEW_COLUMNS)
    _migrate_columns('iphone_health_daily', IPHONE_HEALTH_NEW_COLUMNS)
    _ensure_index('idx_food_items_barcode', 'food_items', 'barcode')
    _migrate_catalog_to_per_user()
    _ensure_index('idx_categories_user', 'categories', 'user_id')
    _ensure_index('idx_food_items_user', 'food_items', 'user_id')


# Columns added after the initial oura_daily CREATE TABLE shipped. New
# columns must be added here (not just the schema_*.sql files) so they also
# land on databases that already have the table — CREATE TABLE IF NOT EXISTS
# is a no-op once the table exists.
OURA_DAILY_NEW_COLUMNS = {
    'hrv_ms': {'sqlite': 'REAL', 'mssql': 'FLOAT'},
    'sleep_efficiency': {'sqlite': 'INTEGER', 'mssql': 'INT'},
    'deep_sleep_minutes': {'sqlite': 'INTEGER', 'mssql': 'INT'},
    'rem_sleep_minutes': {'sqlite': 'INTEGER', 'mssql': 'INT'},
    'temperature_deviation': {'sqlite': 'REAL', 'mssql': 'FLOAT'},
    'spo2_percent': {'sqlite': 'REAL', 'mssql': 'FLOAT'},
    'respiratory_rate': {'sqlite': 'REAL', 'mssql': 'FLOAT'},
    'physical_recovery_score': {'sqlite': 'INTEGER', 'mssql': 'INT'},
    'cognitive_recovery_score': {'sqlite': 'INTEGER', 'mssql': 'INT'},
    'illness_risk_score': {'sqlite': 'INTEGER', 'mssql': 'INT'},
}

FOOD_ITEMS_NEW_COLUMNS = {
    'barcode': {'sqlite': 'TEXT', 'mssql': 'NVARCHAR(64)'},
}

IPHONE_HEALTH_NEW_COLUMNS = {
    'spo2_percent': {'sqlite': 'REAL', 'mssql': 'FLOAT'},
    'hrv_ms': {'sqlite': 'REAL', 'mssql': 'FLOAT'},
    'body_fat_percent': {'sqlite': 'REAL', 'mssql': 'FLOAT'},
    'vo2_max': {'sqlite': 'REAL', 'mssql': 'FLOAT'},
    'distance_km': {'sqlite': 'REAL', 'mssql': 'FLOAT'},
    'flights_climbed': {'sqlite': 'INTEGER', 'mssql': 'INT'},
    'mindful_minutes': {'sqlite': 'INTEGER', 'mssql': 'INT'},
    'water_ml': {'sqlite': 'INTEGER', 'mssql': 'INT'},
}


def _migrate_columns(table, columns):
    with get_db() as db:
        if BACKEND == 'mssql':
            existing = {r['COLUMN_NAME'].lower() for r in db.query(
                "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME=?", (table,)
            )}
        else:
            existing = {r['name'].lower() for r in db.query(f"PRAGMA table_info({table})")}

        for col, types in columns.items():
            if col.lower() in existing:
                continue
            col_type = types[BACKEND]
            db.execute(f"ALTER TABLE {table} ADD {col} {col_type} NULL"
                       if BACKEND == 'mssql' else
                       f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")


def _ensure_index(name, table, column):
    """Must run after _migrate_columns for that table/column — creating an
    index on a column before it exists (e.g. via the schema_*.sql script,
    which runs before any migration on a database where the table already
    existed) fails outright rather than being a harmless no-op."""
    with get_db() as db:
        if BACKEND == 'mssql':
            exists = db.query_one("SELECT 1 AS x FROM sys.indexes WHERE name=?", (name,))
        else:
            exists = db.query_one("SELECT 1 AS x FROM sqlite_master WHERE type='index' AND name=?", (name,))
        if not exists:
            db.execute(f"CREATE INDEX {name} ON {table}({column})")


def _migrate_catalog_to_per_user():
    """One-time structural migration: categories/food_items used to be one
    global, shared catalog (no user_id, and categories.name was globally
    UNIQUE). Splitting it per-user means (a) adding user_id, (b) dropping
    that UNIQUE(name) constraint (two users both having "Breakfast" is
    normal), and (c) cloning the existing shared rows into a private copy
    per existing user, remapping each user's own food_log rows to point at
    their clone rather than the shared originals. Idempotent: no-ops if
    categories already has a user_id column (true for both a fresh install,
    whose schema already includes it, and a database this has already run
    against once).

    Guarded by an sp_getapplock (mssql) so two gunicorn worker processes
    starting at the same moment can't both observe "not migrated yet"
    and both clone the catalog — this previously happened in production
    and duplicated every user's categories/food_items (fixed here; see
    the one-off cleanup this fix shipped alongside)."""
    with get_db() as db:
        if BACKEND == 'mssql':
            # Exclusive, session-scoped: blocks a second worker here until
            # the first one's migration (below) has committed and this
            # connection closes, at which point the lock auto-releases.
            lock = db.query_one(
                "DECLARE @r INT; "
                "EXEC @r = sp_getapplock @Resource='nutrilog_catalog_per_user_migration', "
                "@LockMode='Exclusive', @LockOwner='Session', @LockTimeout=60000; "
                "SELECT @r AS result"
            )
            if not lock or lock['result'] < 0:
                raise RuntimeError('Could not acquire catalog-migration lock (sp_getapplock)')

        if BACKEND == 'mssql':
            has_user_id = db.query_one(
                "SELECT 1 AS x FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='categories' AND COLUMN_NAME='user_id'"
            )
        else:
            has_user_id = 'user_id' in {r['name'].lower() for r in db.query("PRAGMA table_info(categories)")}
        if has_user_id:
            return  # already migrated — lock (if held) releases when this connection closes

        if BACKEND == 'mssql':
            db.execute("""
                DECLARE @c NVARCHAR(256);
                SELECT @c = kc.name FROM sys.key_constraints kc
                JOIN sys.tables t ON kc.parent_object_id = t.object_id
                WHERE t.name = 'categories' AND kc.type = 'UQ';
                IF @c IS NOT NULL EXEC('ALTER TABLE dbo.categories DROP CONSTRAINT ' + @c);
            """)
            db.execute("ALTER TABLE dbo.categories ADD user_id NVARCHAR(64) NULL")
            db.execute("ALTER TABLE dbo.food_items ADD user_id NVARCHAR(64) NULL")
        else:
            # SQLite can't drop an inline UNIQUE constraint or add a NOT NULL
            # column with no default via ALTER TABLE — rebuild both tables.
            # FK checks must be off for this: renaming categories updates
            # food_items' foreign key to point at categories_legacy, which
            # then blocks dropping categories_legacy while food_items (not
            # yet rebuilt itself) still references it. Must be the first
            # statement on this connection — SQLite ignores the pragma once
            # a transaction is already open.
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("ALTER TABLE categories RENAME TO categories_legacy")
            db.execute("""CREATE TABLE categories (
                id TEXT PRIMARY KEY,
                user_id TEXT,
                name TEXT NOT NULL,
                icon TEXT DEFAULT '🍽️',
                sort_order INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            )""")
            db.execute("""INSERT INTO categories (id, user_id, name, icon, sort_order, created_at)
                SELECT id, NULL, name, icon, sort_order, created_at FROM categories_legacy""")
            db.execute("DROP TABLE categories_legacy")

            db.execute("ALTER TABLE food_items RENAME TO food_items_legacy")
            db.execute("""CREATE TABLE food_items (
                id TEXT PRIMARY KEY,
                user_id TEXT,
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
            )""")
            db.execute("""INSERT INTO food_items (id, user_id, category_id, name, serving_size, serving_unit,
                calories, protein_g, carbs_g, fat_g, notes, barcode, created_at)
                SELECT id, NULL, category_id, name, serving_size, serving_unit, calories, protein_g, carbs_g,
                       fat_g, notes, barcode, created_at FROM food_items_legacy""")
            db.execute("DROP TABLE food_items_legacy")

        legacy_categories = db.query("SELECT * FROM categories WHERE user_id IS NULL")
        legacy_food_items = db.query("SELECT * FROM food_items WHERE user_id IS NULL")
        users = db.query("SELECT id FROM users")

        for user in users:
            uid = user['id']
            cat_id_map = {}
            for cat in legacy_categories:
                new_id = str(uuid.uuid4())
                cat_id_map[cat['id']] = new_id
                db.execute(
                    "INSERT INTO categories (id, user_id, name, icon, sort_order, created_at) VALUES (?,?,?,?,?,?)",
                    (new_id, uid, cat['name'], cat['icon'], cat['sort_order'], cat['created_at'])
                )

            item_id_map = {}
            for item in legacy_food_items:
                new_cat_id = cat_id_map.get(item['category_id'])
                if not new_cat_id:
                    continue  # orphaned item with no matching category — nothing sane to clone it under
                new_id = str(uuid.uuid4())
                item_id_map[item['id']] = new_id
                db.execute(
                    """INSERT INTO food_items (id, user_id, category_id, name, serving_size, serving_unit,
                       calories, protein_g, carbs_g, fat_g, notes, barcode, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (new_id, uid, new_cat_id, item['name'], item['serving_size'], item['serving_unit'],
                     item['calories'], item['protein_g'], item['carbs_g'], item['fat_g'], item['notes'],
                     item['barcode'], item['created_at'])
                )

            # Point this user's own log history at their new private clones —
            # the shared originals stay behind (user_id IS NULL) rather than
            # being deleted; every catalog query filters by user_id, so they
            # simply stop being visible instead of risking a destructive DELETE.
            for old_item_id, new_item_id in item_id_map.items():
                db.execute(
                    "UPDATE food_log SET food_item_id=? WHERE user_id=? AND food_item_id=?",
                    (new_item_id, uid, old_item_id)
                )


def seed_user_catalog(user_id):
    """Gives a newly-created user their own starter catalog (same defaults
    every user has historically started with). Called from auth.py right
    after a new users row is inserted — not from init_db(), since the
    catalog is per-user now, not a one-time global seed."""
    with get_db() as db:
        existing = db.query_one("SELECT COUNT(*) AS n FROM categories WHERE user_id=?", (user_id,))['n']
        if existing:
            return

        defaults = [
            (str(uuid.uuid4()), 'Breakfast', '🌅', 1),
            (str(uuid.uuid4()), 'Morning Tea', '☕', 2),
            (str(uuid.uuid4()), 'Lunch', '🥗', 3),
            (str(uuid.uuid4()), 'Afternoon Tea', '🍵', 4),
            (str(uuid.uuid4()), 'Dinner', '🍽️', 5),
            (str(uuid.uuid4()), 'Drinks', '💧', 6),
            (str(uuid.uuid4()), 'Snacks', '🍎', 7),
        ]
        for cat_id, name, icon, order in defaults:
            db.execute(
                "INSERT INTO categories (id, user_id, name, icon, sort_order) VALUES (?,?,?,?,?)",
                (cat_id, user_id, name, icon, order)
            )

        cat_map = {name: cat_id for cat_id, name, icon, order in defaults}

        starter_items = [
            (cat_map['Breakfast'], 'Rolled Oats / Porridge', '40', 'g', 150, 5, 27, 3),
            (cat_map['Breakfast'], 'Weet-Bix (2)', '30', 'g', 130, 4, 25, 1),
            (cat_map['Breakfast'], 'Granola / Muesli', '45', 'g', 200, 5, 32, 6),
            (cat_map['Breakfast'], 'Whole Eggs (2)', '120', 'g', 155, 13, 1, 11),
            (cat_map['Breakfast'], 'Greek Yoghurt', '150', 'g', 130, 15, 8, 3),
            (cat_map['Breakfast'], 'Wholegrain Toast (2)', '60', 'g', 160, 6, 28, 2),
            (cat_map['Breakfast'], 'Avocado (half)', '75', 'g', 120, 1, 6, 11),
            (cat_map['Morning Tea'], 'Banana', '120', 'g', 105, 1, 27, 0),
            (cat_map['Morning Tea'], 'Apple', '182', 'g', 95, 0, 25, 0),
            (cat_map['Morning Tea'], 'Bliss Ball', '35', 'g', 150, 4, 16, 9),
            (cat_map['Morning Tea'], 'Protein Bar', '60', 'g', 220, 20, 20, 7),
            (cat_map['Lunch'], 'Chicken & Salad', '300', 'g', 350, 35, 15, 10),
            (cat_map['Lunch'], 'Tuna Wrap', '200', 'g', 380, 28, 40, 8),
            (cat_map['Lunch'], 'Soup (vegetable)', '350', 'ml', 180, 6, 28, 4),
            (cat_map['Lunch'], 'Sushi (6 pieces)', '200', 'g', 310, 12, 55, 5),
            (cat_map['Lunch'], 'Caesar Salad', '250', 'g', 320, 12, 18, 22),
            (cat_map['Afternoon Tea'], 'Rice Cakes (2)', '20', 'g', 70, 1, 14, 1),
            (cat_map['Afternoon Tea'], 'Hummus & Carrots', '100', 'g', 140, 5, 14, 8),
            (cat_map['Afternoon Tea'], 'Nuts (mixed, small handful)', '30', 'g', 180, 5, 6, 16),
            (cat_map['Dinner'], 'Grilled Salmon', '180', 'g', 360, 40, 0, 20),
            (cat_map['Dinner'], 'Chicken Breast', '180', 'g', 280, 42, 0, 6),
            (cat_map['Dinner'], 'Beef Stir-fry', '350', 'g', 520, 38, 40, 16),
            (cat_map['Dinner'], 'Pasta Bolognese', '400', 'g', 620, 30, 70, 18),
            (cat_map['Dinner'], 'Roast Vegetables', '200', 'g', 160, 4, 30, 5),
            (cat_map['Dinner'], 'Brown Rice', '180', 'g', 220, 5, 46, 2),
            (cat_map['Drinks'], 'Water', '250', 'ml', 0, 0, 0, 0),
            (cat_map['Drinks'], 'Black Coffee', '250', 'ml', 5, 0, 1, 0),
            (cat_map['Drinks'], 'Flat White', '250', 'ml', 120, 8, 10, 6),
            (cat_map['Drinks'], 'Green Tea', '250', 'ml', 2, 0, 0, 0),
            (cat_map['Drinks'], 'Protein Shake', '350', 'ml', 220, 25, 20, 4),
            (cat_map['Drinks'], 'Orange Juice', '250', 'ml', 115, 2, 26, 0),
            (cat_map['Snacks'], 'Dark Chocolate (2 squares)', '20', 'g', 115, 1, 12, 7),
            (cat_map['Snacks'], 'Cheese & Crackers', '60', 'g', 230, 9, 20, 13),
            (cat_map['Snacks'], 'Corn Chips (small bag)', '40', 'g', 200, 2, 26, 10),
            (cat_map['Snacks'], 'Popcorn (air-popped)', '30', 'g', 110, 3, 22, 1),
        ]
        for cat_id, name, size, unit, cals, p, c, f in starter_items:
            db.execute(
                """INSERT INTO food_items
                   (id, user_id, category_id, name, serving_size, serving_unit, calories, protein_g, carbs_g, fat_g)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), user_id, cat_id, name, size, unit, cals, p, c, f)
            )
