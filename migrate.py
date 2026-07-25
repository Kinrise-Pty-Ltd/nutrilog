"""One-off migration: local SQLite nutrilog.db -> Azure SQL.

Copies categories and food_items as-is, pre-seeds a users row for Ruffy
(matched by email on his first real Easy Auth login, which fills in his
entra_oid), and carries over any existing food_log rows attributed to him.

Usage:
    AZURE_SQL_CONNECTION_STRING="..." python migrate.py path/to/source_nutrilog.db

Run this against the *live* production SQLite file (pulled from the
current nutrilog-app deployment), not an old local snapshot — pull the
latest nutrilog.db from the App Service before running, since it may have
more logged history than any local copy.
"""
import sys
import sqlite3
import uuid

import db as db_module
from db import get_db, init_db

RUFFY_EMAIL = 'ruffy@kingroup.com.au'
RUFFY_NAME = 'Ruffy'


def main():
    if len(sys.argv) != 2:
        print('Usage: python migrate.py path/to/source_nutrilog.db')
        sys.exit(1)
    source_path = sys.argv[1]

    if db_module.BACKEND != 'mssql':
        print('AZURE_SQL_CONNECTION_STRING is not set — refusing to run '
              '(this script writes to the mssql backend only).')
        sys.exit(1)

    src = sqlite3.connect(source_path)
    src.row_factory = sqlite3.Row

    print('Ensuring Azure SQL schema exists...')
    init_db()  # also seeds the default catalog if the target DB is empty

    with get_db() as dest:
        # Wipe the placeholder catalog seeded by init_db() so we don't end up
        # with duplicates alongside the real data copied from source.
        dest.execute("DELETE FROM food_items")
        dest.execute("DELETE FROM categories")

        print('Copying categories...')
        for row in src.execute("SELECT * FROM categories"):
            dest.execute(
                "INSERT INTO categories (id, name, icon, sort_order, created_at) VALUES (?,?,?,?,?)",
                (row['id'], row['name'], row['icon'], row['sort_order'], row['created_at'])
            )

        print('Copying food_items...')
        for row in src.execute("SELECT * FROM food_items"):
            dest.execute(
                """INSERT INTO food_items
                   (id, category_id, name, serving_size, serving_unit, calories,
                    protein_g, carbs_g, fat_g, notes, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (row['id'], row['category_id'], row['name'], row['serving_size'],
                 row['serving_unit'], row['calories'], row['protein_g'], row['carbs_g'],
                 row['fat_g'], row['notes'], row['created_at'])
            )

        print(f'Pre-seeding user row for {RUFFY_EMAIL}...')
        ruffy = dest.query_one("SELECT * FROM users WHERE email=?", (RUFFY_EMAIL,))
        if not ruffy:
            ruffy_id = str(uuid.uuid4())
            dest.execute(
                "INSERT INTO users (id, entra_oid, email, display_name) VALUES (?,NULL,?,?)",
                (ruffy_id, RUFFY_EMAIL, RUFFY_NAME)
            )
        else:
            ruffy_id = ruffy['id']

        print('Copying food_log (attributed to Ruffy)...')
        log_count = 0
        for row in src.execute("SELECT * FROM food_log"):
            dest.execute(
                """INSERT INTO food_log
                   (id, user_id, food_item_id, meal_slot, log_date, quantity,
                    calories_actual, logged_at, notes)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (row['id'], ruffy_id, row['food_item_id'], row['meal_slot'], row['log_date'],
                 row['quantity'], row['calories_actual'], row['logged_at'], row['notes'])
            )
            log_count += 1

    src.close()
    print(f'Done. Migrated food_log entries: {log_count}')


if __name__ == '__main__':
    main()
