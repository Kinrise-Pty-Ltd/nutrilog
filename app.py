from flask import Flask, jsonify, request, send_from_directory
import sqlite3
import uuid
from datetime import datetime, date
import os

app = Flask(__name__, static_folder='public')
DB_PATH = os.path.join(os.path.dirname(__file__), 'nutrilog.db')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript("""
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
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (category_id) REFERENCES categories(id)
            );

            CREATE TABLE IF NOT EXISTS food_log (
                id TEXT PRIMARY KEY,
                food_item_id TEXT NOT NULL,
                meal_slot TEXT NOT NULL,
                log_date TEXT NOT NULL,
                quantity REAL DEFAULT 1.0,
                calories_actual INTEGER,
                logged_at TEXT DEFAULT (datetime('now')),
                notes TEXT,
                FOREIGN KEY (food_item_id) REFERENCES food_items(id)
            );
        """)

        # Seed default categories if empty
        existing = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        if existing == 0:
            defaults = [
                (str(uuid.uuid4()), 'Breakfast', '🌅', 1),
                (str(uuid.uuid4()), 'Morning Tea', '☕', 2),
                (str(uuid.uuid4()), 'Lunch', '🥗', 3),
                (str(uuid.uuid4()), 'Afternoon Tea', '🍵', 4),
                (str(uuid.uuid4()), 'Dinner', '🍽️', 5),
                (str(uuid.uuid4()), 'Drinks', '💧', 6),
                (str(uuid.uuid4()), 'Snacks', '🍎', 7),
            ]
            conn.executemany(
                "INSERT INTO categories (id, name, icon, sort_order) VALUES (?,?,?,?)",
                defaults
            )

            # Seed some starter food items
            cat_rows = conn.execute("SELECT id, name FROM categories").fetchall()
            cat_map = {r['name']: r['id'] for r in cat_rows}

            starter_items = [
                # Breakfast
                (str(uuid.uuid4()), cat_map['Breakfast'], 'Rolled Oats / Porridge', '40', 'g', 150, 5, 27, 3, None),
                (str(uuid.uuid4()), cat_map['Breakfast'], 'Weet-Bix (2)', '30', 'g', 130, 4, 25, 1, None),
                (str(uuid.uuid4()), cat_map['Breakfast'], 'Granola / Muesli', '45', 'g', 200, 5, 32, 6, None),
                (str(uuid.uuid4()), cat_map['Breakfast'], 'Whole Eggs (2)', '120', 'g', 155, 13, 1, 11, None),
                (str(uuid.uuid4()), cat_map['Breakfast'], 'Greek Yoghurt', '150', 'g', 130, 15, 8, 3, None),
                (str(uuid.uuid4()), cat_map['Breakfast'], 'Wholegrain Toast (2)', '60', 'g', 160, 6, 28, 2, None),
                (str(uuid.uuid4()), cat_map['Breakfast'], 'Avocado (half)', '75', 'g', 120, 1, 6, 11, None),
                # Morning Tea
                (str(uuid.uuid4()), cat_map['Morning Tea'], 'Banana', '120', 'g', 105, 1, 27, 0, None),
                (str(uuid.uuid4()), cat_map['Morning Tea'], 'Apple', '182', 'g', 95, 0, 25, 0, None),
                (str(uuid.uuid4()), cat_map['Morning Tea'], 'Bliss Ball', '35', 'g', 150, 4, 16, 9, None),
                (str(uuid.uuid4()), cat_map['Morning Tea'], 'Protein Bar', '60', 'g', 220, 20, 20, 7, None),
                # Lunch
                (str(uuid.uuid4()), cat_map['Lunch'], 'Chicken & Salad', '300', 'g', 350, 35, 15, 10, None),
                (str(uuid.uuid4()), cat_map['Lunch'], 'Tuna Wrap', '200', 'g', 380, 28, 40, 8, None),
                (str(uuid.uuid4()), cat_map['Lunch'], 'Soup (vegetable)', '350', 'ml', 180, 6, 28, 4, None),
                (str(uuid.uuid4()), cat_map['Lunch'], 'Sushi (6 pieces)', '200', 'g', 310, 12, 55, 5, None),
                (str(uuid.uuid4()), cat_map['Lunch'], 'Caesar Salad', '250', 'g', 320, 12, 18, 22, None),
                # Afternoon Tea
                (str(uuid.uuid4()), cat_map['Afternoon Tea'], 'Rice Cakes (2)', '20', 'g', 70, 1, 14, 1, None),
                (str(uuid.uuid4()), cat_map['Afternoon Tea'], 'Hummus & Carrots', '100', 'g', 140, 5, 14, 8, None),
                (str(uuid.uuid4()), cat_map['Afternoon Tea'], 'Nuts (mixed, small handful)', '30', 'g', 180, 5, 6, 16, None),
                # Dinner
                (str(uuid.uuid4()), cat_map['Dinner'], 'Grilled Salmon', '180', 'g', 360, 40, 0, 20, None),
                (str(uuid.uuid4()), cat_map['Dinner'], 'Chicken Breast', '180', 'g', 280, 42, 0, 6, None),
                (str(uuid.uuid4()), cat_map['Dinner'], 'Beef Stir-fry', '350', 'g', 520, 38, 40, 16, None),
                (str(uuid.uuid4()), cat_map['Dinner'], 'Pasta Bolognese', '400', 'g', 620, 30, 70, 18, None),
                (str(uuid.uuid4()), cat_map['Dinner'], 'Roast Vegetables', '200', 'g', 160, 4, 30, 5, None),
                (str(uuid.uuid4()), cat_map['Dinner'], 'Brown Rice', '180', 'g', 220, 5, 46, 2, None),
                # Drinks
                (str(uuid.uuid4()), cat_map['Drinks'], 'Water', '250', 'ml', 0, 0, 0, 0, None),
                (str(uuid.uuid4()), cat_map['Drinks'], 'Black Coffee', '250', 'ml', 5, 0, 1, 0, None),
                (str(uuid.uuid4()), cat_map['Drinks'], 'Flat White', '250', 'ml', 120, 8, 10, 6, None),
                (str(uuid.uuid4()), cat_map['Drinks'], 'Green Tea', '250', 'ml', 2, 0, 0, 0, None),
                (str(uuid.uuid4()), cat_map['Drinks'], 'Protein Shake', '350', 'ml', 220, 25, 20, 4, None),
                (str(uuid.uuid4()), cat_map['Drinks'], 'Orange Juice', '250', 'ml', 115, 2, 26, 0, None),
                # Snacks
                (str(uuid.uuid4()), cat_map['Snacks'], 'Dark Chocolate (2 squares)', '20', 'g', 115, 1, 12, 7, None),
                (str(uuid.uuid4()), cat_map['Snacks'], 'Cheese & Crackers', '60', 'g', 230, 9, 20, 13, None),
                (str(uuid.uuid4()), cat_map['Snacks'], 'Corn Chips (small bag)', '40', 'g', 200, 2, 26, 10, None),
                (str(uuid.uuid4()), cat_map['Snacks'], 'Popcorn (air-popped)', '30', 'g', 110, 3, 22, 1, None),
            ]
            conn.executemany(
                "INSERT INTO food_items (id, category_id, name, serving_size, serving_unit, calories, protein_g, carbs_g, fat_g, notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
                starter_items
            )


# ── STATIC FILES ──────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('public', 'index.html')

@app.route('/admin')
def admin():
    return send_from_directory('public', 'admin.html')

@app.route('/public/<path:filename>')
def static_files(filename):
    return send_from_directory('public', filename)


# ── CATEGORIES API ────────────────────────────────────────────────────────────

@app.route('/api/categories', methods=['GET'])
def get_categories():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM categories ORDER BY sort_order, name"
        ).fetchall()
        return jsonify([dict(r) for r in rows])


@app.route('/api/categories', methods=['POST'])
def create_category():
    data = request.json
    if not data.get('name'):
        return jsonify({'error': 'Name required'}), 400
    with get_db() as conn:
        max_order = conn.execute("SELECT COALESCE(MAX(sort_order),0) FROM categories").fetchone()[0]
        cat_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO categories (id, name, icon, sort_order) VALUES (?,?,?,?)",
            (cat_id, data['name'], data.get('icon', '🍽️'), max_order + 1)
        )
        row = conn.execute("SELECT * FROM categories WHERE id=?", (cat_id,)).fetchone()
        return jsonify(dict(row)), 201


@app.route('/api/categories/<cat_id>', methods=['PUT'])
def update_category(cat_id):
    data = request.json
    with get_db() as conn:
        conn.execute(
            "UPDATE categories SET name=?, icon=?, sort_order=? WHERE id=?",
            (data['name'], data.get('icon', '🍽️'), data.get('sort_order', 0), cat_id)
        )
        row = conn.execute("SELECT * FROM categories WHERE id=?", (cat_id,)).fetchone()
        return jsonify(dict(row))


@app.route('/api/categories/<cat_id>', methods=['DELETE'])
def delete_category(cat_id):
    with get_db() as conn:
        item_count = conn.execute(
            "SELECT COUNT(*) FROM food_items WHERE category_id=?", (cat_id,)
        ).fetchone()[0]
        if item_count > 0:
            return jsonify({'error': f'Cannot delete: {item_count} food items in this category. Remove items first.'}), 400
        conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))
        return jsonify({'deleted': True})


# ── FOOD ITEMS API ────────────────────────────────────────────────────────────

@app.route('/api/food-items', methods=['GET'])
def get_food_items():
    category_id = request.args.get('category_id')
    with get_db() as conn:
        if category_id:
            rows = conn.execute(
                """SELECT fi.*, c.name as category_name, c.icon as category_icon 
                   FROM food_items fi JOIN categories c ON fi.category_id=c.id
                   WHERE fi.category_id=? ORDER BY fi.name""",
                (category_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT fi.*, c.name as category_name, c.icon as category_icon 
                   FROM food_items fi JOIN categories c ON fi.category_id=c.id
                   ORDER BY c.sort_order, fi.name"""
            ).fetchall()
        return jsonify([dict(r) for r in rows])


@app.route('/api/food-items', methods=['POST'])
def create_food_item():
    data = request.json
    required = ['category_id', 'name', 'serving_size', 'calories']
    for f in required:
        if not data.get(f) and data.get(f) != 0:
            return jsonify({'error': f'{f} is required'}), 400
    item_id = str(uuid.uuid4())
    with get_db() as conn:
        conn.execute(
            """INSERT INTO food_items (id, category_id, name, serving_size, serving_unit, calories, protein_g, carbs_g, fat_g, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (item_id, data['category_id'], data['name'], str(data['serving_size']),
             data.get('serving_unit', 'g'), int(data['calories']),
             float(data.get('protein_g', 0)), float(data.get('carbs_g', 0)),
             float(data.get('fat_g', 0)), data.get('notes'))
        )
        row = conn.execute(
            """SELECT fi.*, c.name as category_name FROM food_items fi 
               JOIN categories c ON fi.category_id=c.id WHERE fi.id=?""",
            (item_id,)
        ).fetchone()
        return jsonify(dict(row)), 201


@app.route('/api/food-items/<item_id>', methods=['PUT'])
def update_food_item(item_id):
    data = request.json
    with get_db() as conn:
        conn.execute(
            """UPDATE food_items SET category_id=?, name=?, serving_size=?, serving_unit=?,
               calories=?, protein_g=?, carbs_g=?, fat_g=?, notes=? WHERE id=?""",
            (data['category_id'], data['name'], str(data['serving_size']),
             data.get('serving_unit', 'g'), int(data['calories']),
             float(data.get('protein_g', 0)), float(data.get('carbs_g', 0)),
             float(data.get('fat_g', 0)), data.get('notes'), item_id)
        )
        row = conn.execute(
            """SELECT fi.*, c.name as category_name FROM food_items fi 
               JOIN categories c ON fi.category_id=c.id WHERE fi.id=?""",
            (item_id,)
        ).fetchone()
        return jsonify(dict(row))


@app.route('/api/food-items/<item_id>', methods=['DELETE'])
def delete_food_item(item_id):
    with get_db() as conn:
        conn.execute("DELETE FROM food_items WHERE id=?", (item_id,))
        return jsonify({'deleted': True})


# ── FOOD LOG API ──────────────────────────────────────────────────────────────

@app.route('/api/log', methods=['GET'])
def get_log():
    log_date = request.args.get('date', date.today().isoformat())
    with get_db() as conn:
        rows = conn.execute(
            """SELECT fl.*, fi.name as food_name, fi.serving_size, fi.serving_unit,
               fi.calories as item_calories, fi.protein_g, fi.carbs_g, fi.fat_g,
               c.name as category_name, c.icon as category_icon
               FROM food_log fl
               JOIN food_items fi ON fl.food_item_id=fi.id
               JOIN categories c ON fi.category_id=c.id
               WHERE fl.log_date=?
               ORDER BY c.sort_order, fl.logged_at""",
            (log_date,)
        ).fetchall()
        return jsonify([dict(r) for r in rows])


@app.route('/api/log', methods=['POST'])
def add_log_entry():
    data = request.json
    log_id = str(uuid.uuid4())
    log_date = data.get('log_date', date.today().isoformat())
    quantity = float(data.get('quantity', 1.0))

    with get_db() as conn:
        item = conn.execute(
            "SELECT calories FROM food_items WHERE id=?", (data['food_item_id'],)
        ).fetchone()
        if not item:
            return jsonify({'error': 'Food item not found'}), 404

        calories_actual = int(item['calories'] * quantity)
        conn.execute(
            """INSERT INTO food_log (id, food_item_id, meal_slot, log_date, quantity, calories_actual, notes)
               VALUES (?,?,?,?,?,?,?)""",
            (log_id, data['food_item_id'], data['meal_slot'], log_date,
             quantity, calories_actual, data.get('notes'))
        )
        row = conn.execute(
            """SELECT fl.*, fi.name as food_name, fi.serving_size, fi.serving_unit,
               c.name as category_name, c.icon as category_icon
               FROM food_log fl JOIN food_items fi ON fl.food_item_id=fi.id
               JOIN categories c ON fi.category_id=c.id
               WHERE fl.id=?""",
            (log_id,)
        ).fetchone()
        return jsonify(dict(row)), 201


@app.route('/api/log/<entry_id>', methods=['DELETE'])
def delete_log_entry(entry_id):
    with get_db() as conn:
        conn.execute("DELETE FROM food_log WHERE id=?", (entry_id,))
        return jsonify({'deleted': True})


@app.route('/api/log/summary', methods=['GET'])
def get_log_summary():
    log_date = request.args.get('date', date.today().isoformat())
    with get_db() as conn:
        totals = conn.execute(
            """SELECT 
               SUM(fl.calories_actual) as total_calories,
               SUM(fi.protein_g * fl.quantity) as total_protein,
               SUM(fi.carbs_g * fl.quantity) as total_carbs,
               SUM(fi.fat_g * fl.quantity) as total_fat,
               COUNT(*) as entry_count
               FROM food_log fl JOIN food_items fi ON fl.food_item_id=fi.id
               WHERE fl.log_date=?""",
            (log_date,)
        ).fetchone()

        by_slot = conn.execute(
            """SELECT fl.meal_slot, SUM(fl.calories_actual) as calories, COUNT(*) as items
               FROM food_log fl WHERE fl.log_date=?
               GROUP BY fl.meal_slot""",
            (log_date,)
        ).fetchall()

        return jsonify({
            'date': log_date,
            'totals': dict(totals) if totals else {},
            'by_slot': [dict(r) for r in by_slot]
        })


@app.route('/api/log/history', methods=['GET'])
def get_log_history():
    days = int(request.args.get('days', 7))
    with get_db() as conn:
        rows = conn.execute(
            """SELECT log_date, SUM(calories_actual) as total_calories, COUNT(*) as entries
               FROM food_log
               GROUP BY log_date
               ORDER BY log_date DESC
               LIMIT ?""",
            (days,)
        ).fetchall()
        return jsonify([dict(r) for r in rows])


# ── EXPORT API (for AI use) ───────────────────────────────────────────────────

@app.route('/api/export', methods=['GET'])
def export_all():
    """Full database export for AI analysis"""
    with get_db() as conn:
        categories = [dict(r) for r in conn.execute("SELECT * FROM categories ORDER BY sort_order").fetchall()]
        food_items = [dict(r) for r in conn.execute("SELECT * FROM food_items ORDER BY category_id, name").fetchall()]
        food_log = [dict(r) for r in conn.execute("SELECT * FROM food_log ORDER BY log_date, logged_at").fetchall()]
        return jsonify({
            'exported_at': datetime.utcnow().isoformat(),
            'categories': categories,
            'food_items': food_items,
            'food_log': food_log
        })


if __name__ == '__main__':
    init_db()
    print("NutriLog running on http://localhost:5000")
    print("Admin panel at http://localhost:5000/admin")
    app.run(debug=True, port=5000)
