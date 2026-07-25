"""Database access layer.

Two backends, selected by the presence of AZURE_SQL_CONNECTION_STRING:
  - sqlite (default): local file nutrilog.db, used for local development.
  - mssql: Azure SQL via pyodbc, used in production.

Both backends are queried with '?' placeholders (pyodbc's ODBC driver and
sqlite3 both accept this), so almost all query code is backend-agnostic.
"""
import os
import sqlite3

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
    _seed_defaults()


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


def _seed_defaults():
    import uuid
    with get_db() as db:
        existing = db.query_one("SELECT COUNT(*) AS n FROM categories")['n']
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
                "INSERT INTO categories (id, name, icon, sort_order) VALUES (?,?,?,?)",
                (cat_id, name, icon, order)
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
                   (id, category_id, name, serving_size, serving_unit, calories, protein_g, carbs_g, fat_g)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), cat_id, name, size, unit, cals, p, c, f)
            )
