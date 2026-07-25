import os
import uuid
from datetime import date, datetime

from flask import Flask, g, jsonify, request, send_from_directory, session

import barcode
import health
import mcp_server
import oura
import vision
from auth import load_current_user
from db import get_db, init_db

app = Flask(__name__, static_folder='public')
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev-only-insecure-key')

# Runs at import time (not just `python app.py`) so it also fires under
# gunicorn, which is how this app actually runs in production (startup.sh).
# init_db() is idempotent — safe to call on every worker startup.
init_db()


@app.before_request
def attach_user():
    # This endpoint is called by an unattended device automation (Shortcuts /
    # Health Auto Export), not a logged-in browser — it authenticates via its
    # own per-user bearer token instead of an Easy Auth session, and in
    # production it must be excluded from Easy Auth's platform-level gate too.
    if request.path == '/api/health/ingest':
        auth_header = request.headers.get('Authorization', '')
        token = auth_header[7:].strip() if auth_header.startswith('Bearer ') else ''
        user_id = health.user_id_for_token(token)
        if not user_id:
            return jsonify({'error': 'Invalid or missing token'}), 401
        with get_db() as db:
            g.user = db.query_one("SELECT * FROM users WHERE id=?", (user_id,))
        g.real_user = g.user
        return

    if request.path.startswith('/api/'):
        g.real_user = load_current_user()
        if g.real_user is None:
            return jsonify({'error': 'Unauthorized'}), 401
        g.user = g.real_user

        # Delegated access ("act as"): a user can view/edit another user's
        # data + config if that owner has granted them access by email (see
        # /api/delegates*). Re-validated on every request (not just at grant
        # time) so a revoked grant takes effect immediately, and re-checked
        # against g.real_user's email specifically — never the currently
        # acted-as identity — so delegation can't be chained/escalated.
        acting_as = session.get('acting_as')
        if acting_as:
            with get_db() as db:
                owner = db.query_one(
                    "SELECT u.* FROM users u JOIN user_delegates d ON d.owner_user_id = u.id "
                    "WHERE u.id=? AND d.delegate_email=?",
                    (acting_as, g.real_user['email'])
                )
            if owner:
                g.user = owner
            else:
                session.pop('acting_as', None)


# ── STATIC FILES ──────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('public', 'index.html')


@app.route('/admin')
def admin():
    return send_from_directory('public', 'admin.html')


@app.route('/calendar')
def calendar_page():
    return send_from_directory('public', 'calendar.html')


@app.route('/oura')
def oura_page():
    return send_from_directory('public', 'oura.html')


@app.route('/health')
def health_page():
    return send_from_directory('public', 'health.html')


@app.route('/public/<path:filename>')
def static_files(filename):
    return send_from_directory('public', filename)


# ── CURRENT USER ──────────────────────────────────────────────────────────────

@app.route('/api/me', methods=['GET'])
def get_me():
    return jsonify({
        'id': g.user['id'],
        'email': g.user['email'],
        'display_name': g.user['display_name'],
        'real_email': g.real_user['email'],
        'real_display_name': g.real_user['display_name'],
        'acting_as': g.user['id'] != g.real_user['id'],
    })


# ── DELEGATED ACCESS ("act as") ────────────────────────────────────────────
# Self-service: an owner grants another Entra-assigned user (by email) full
# access to their own account's data and config — e.g. Ruffy granting his
# executive assistant access to his log/catalog/integration settings. The
# grant is matched by email at act-as time, so it works even before the
# delegate has ever signed in. Once acting-as is active, every other route
# in this file is automatically scoped to the owner via g.user (see
# attach_user() above) — nothing else needed per-route.

@app.route('/api/delegates', methods=['GET'])
def list_delegates():
    """Who has been granted access to *my* (g.user's) account."""
    with get_db() as db:
        rows = db.query(
            "SELECT id, delegate_email, created_at FROM user_delegates WHERE owner_user_id=? ORDER BY created_at",
            (g.user['id'],)
        )
    return jsonify(rows)


@app.route('/api/delegates', methods=['POST'])
def add_delegate():
    data = request.json or {}
    email = (data.get('email') or '').strip().lower()
    if not email:
        return jsonify({'error': 'email is required'}), 400
    if email == g.user['email'].lower():
        return jsonify({'error': "You can't delegate access to yourself"}), 400

    delegate_id = str(uuid.uuid4())
    with get_db() as db:
        existing = db.query_one(
            "SELECT id FROM user_delegates WHERE owner_user_id=? AND delegate_email=?",
            (g.user['id'], email)
        )
        if existing:
            return jsonify({'error': 'Already granted'}), 400
        db.execute(
            "INSERT INTO user_delegates (id, owner_user_id, delegate_email) VALUES (?,?,?)",
            (delegate_id, g.user['id'], email)
        )
    return jsonify({'id': delegate_id, 'delegate_email': email}), 201


@app.route('/api/delegates/<delegate_id>', methods=['DELETE'])
def remove_delegate(delegate_id):
    with get_db() as db:
        db.execute("DELETE FROM user_delegates WHERE id=? AND owner_user_id=?", (delegate_id, g.user['id']))
    return jsonify({'deleted': True})


@app.route('/api/delegates/accessible', methods=['GET'])
def accessible_accounts():
    """Accounts g.real_user (the actual signed-in identity, regardless of
    who they're currently acting as) has been granted access to."""
    with get_db() as db:
        rows = db.query(
            """SELECT u.id, u.email, u.display_name FROM user_delegates d
               JOIN users u ON u.id = d.owner_user_id
               WHERE d.delegate_email=?""",
            (g.real_user['email'],)
        )
    return jsonify(rows)


@app.route('/api/act-as', methods=['POST'])
def act_as():
    data = request.json or {}
    owner_id = data.get('owner_user_id')
    if not owner_id:
        session.pop('acting_as', None)
        return jsonify({'acting_as': None})

    with get_db() as db:
        valid = db.query_one(
            "SELECT u.id FROM users u JOIN user_delegates d ON d.owner_user_id = u.id "
            "WHERE u.id=? AND d.delegate_email=?",
            (owner_id, g.real_user['email'])
        )
    if not valid:
        return jsonify({'error': 'Not authorized to act as this account'}), 403

    session['acting_as'] = owner_id
    return jsonify({'acting_as': owner_id})


# ── CATEGORIES API (per-user catalog) ─────────────────────────────────────────

@app.route('/api/categories', methods=['GET'])
def get_categories():
    with get_db() as db:
        rows = db.query("SELECT * FROM categories WHERE user_id=? ORDER BY sort_order, name", (g.user['id'],))
        return jsonify(rows)


@app.route('/api/categories', methods=['POST'])
def create_category():
    data = request.json
    if not data.get('name'):
        return jsonify({'error': 'Name required'}), 400
    with get_db() as db:
        max_order = db.query_one(
            "SELECT COALESCE(MAX(sort_order),0) AS m FROM categories WHERE user_id=?", (g.user['id'],)
        )['m']
        cat_id = str(uuid.uuid4())
        db.execute(
            "INSERT INTO categories (id, user_id, name, icon, sort_order) VALUES (?,?,?,?,?)",
            (cat_id, g.user['id'], data['name'], data.get('icon', '🍽️'), max_order + 1)
        )
        row = db.query_one("SELECT * FROM categories WHERE id=?", (cat_id,))
        return jsonify(row), 201


@app.route('/api/categories/<cat_id>', methods=['PUT'])
def update_category(cat_id):
    data = request.json
    with get_db() as db:
        db.execute(
            "UPDATE categories SET name=?, icon=?, sort_order=? WHERE id=? AND user_id=?",
            (data['name'], data.get('icon', '🍽️'), data.get('sort_order', 0), cat_id, g.user['id'])
        )
        row = db.query_one("SELECT * FROM categories WHERE id=? AND user_id=?", (cat_id, g.user['id']))
        if not row:
            return jsonify({'error': 'Category not found'}), 404
        return jsonify(row)


@app.route('/api/categories/<cat_id>', methods=['DELETE'])
def delete_category(cat_id):
    with get_db() as db:
        item_count = db.query_one(
            "SELECT COUNT(*) AS n FROM food_items WHERE category_id=? AND user_id=?", (cat_id, g.user['id'])
        )['n']
        if item_count > 0:
            return jsonify({'error': f'Cannot delete: {item_count} food items in this category. Remove items first.'}), 400
        db.execute("DELETE FROM categories WHERE id=? AND user_id=?", (cat_id, g.user['id']))
        return jsonify({'deleted': True})


# ── FOOD ITEMS API (per-user catalog) ──────────────────────────────────────────

@app.route('/api/food-items', methods=['GET'])
def get_food_items():
    category_id = request.args.get('category_id')
    with get_db() as db:
        if category_id:
            rows = db.query(
                """SELECT fi.*, c.name as category_name, c.icon as category_icon
                   FROM food_items fi JOIN categories c ON fi.category_id=c.id
                   WHERE fi.category_id=? AND fi.user_id=? ORDER BY fi.name""",
                (category_id, g.user['id'])
            )
        else:
            rows = db.query(
                """SELECT fi.*, c.name as category_name, c.icon as category_icon
                   FROM food_items fi JOIN categories c ON fi.category_id=c.id
                   WHERE fi.user_id=? ORDER BY c.sort_order, fi.name""",
                (g.user['id'],)
            )
        return jsonify(rows)


@app.route('/api/food-items', methods=['POST'])
def create_food_item():
    data = request.json
    required = ['category_id', 'name', 'serving_size', 'calories']
    for f in required:
        if not data.get(f) and data.get(f) != 0:
            return jsonify({'error': f'{f} is required'}), 400

    with get_db() as db:
        category = db.query_one(
            "SELECT id FROM categories WHERE id=? AND user_id=?", (data['category_id'], g.user['id'])
        )
        if not category:
            return jsonify({'error': 'Category not found'}), 404

        item_id = str(uuid.uuid4())
        db.execute(
            """INSERT INTO food_items (id, user_id, category_id, name, serving_size, serving_unit, calories, protein_g, carbs_g, fat_g, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (item_id, g.user['id'], data['category_id'], data['name'], str(data['serving_size']),
             data.get('serving_unit', 'g'), int(data['calories']),
             float(data.get('protein_g', 0)), float(data.get('carbs_g', 0)),
             float(data.get('fat_g', 0)), data.get('notes'))
        )
        row = db.query_one(
            """SELECT fi.*, c.name as category_name FROM food_items fi
               JOIN categories c ON fi.category_id=c.id WHERE fi.id=?""",
            (item_id,)
        )
        return jsonify(row), 201


@app.route('/api/food-items/<item_id>', methods=['PUT'])
def update_food_item(item_id):
    data = request.json
    with get_db() as db:
        category = db.query_one(
            "SELECT id FROM categories WHERE id=? AND user_id=?", (data['category_id'], g.user['id'])
        )
        if not category:
            return jsonify({'error': 'Category not found'}), 404

        db.execute(
            """UPDATE food_items SET category_id=?, name=?, serving_size=?, serving_unit=?,
               calories=?, protein_g=?, carbs_g=?, fat_g=?, notes=? WHERE id=? AND user_id=?""",
            (data['category_id'], data['name'], str(data['serving_size']),
             data.get('serving_unit', 'g'), int(data['calories']),
             float(data.get('protein_g', 0)), float(data.get('carbs_g', 0)),
             float(data.get('fat_g', 0)), data.get('notes'), item_id, g.user['id'])
        )
        row = db.query_one(
            """SELECT fi.*, c.name as category_name FROM food_items fi
               JOIN categories c ON fi.category_id=c.id WHERE fi.id=? AND fi.user_id=?""",
            (item_id, g.user['id'])
        )
        if not row:
            return jsonify({'error': 'Food item not found'}), 404
        return jsonify(row)


@app.route('/api/food-items/<item_id>', methods=['DELETE'])
def delete_food_item(item_id):
    with get_db() as db:
        db.execute("DELETE FROM food_items WHERE id=? AND user_id=?", (item_id, g.user['id']))
        return jsonify({'deleted': True})


# ── FOOD LOG API (scoped to the signed-in user) ───────────────────────────────

@app.route('/api/log', methods=['GET'])
def get_log():
    log_date = request.args.get('date', date.today().isoformat())
    with get_db() as db:
        rows = db.query(
            """SELECT fl.*, fi.name as food_name, fi.serving_size, fi.serving_unit,
               fi.calories as item_calories, fi.protein_g, fi.carbs_g, fi.fat_g,
               c.name as category_name, c.icon as category_icon
               FROM food_log fl
               JOIN food_items fi ON fl.food_item_id=fi.id
               JOIN categories c ON fi.category_id=c.id
               WHERE fl.log_date=? AND fl.user_id=?
               ORDER BY c.sort_order, fl.logged_at""",
            (log_date, g.user['id'])
        )
        return jsonify(rows)


@app.route('/api/log', methods=['POST'])
def add_log_entry():
    data = request.json
    log_id = str(uuid.uuid4())
    log_date = data.get('log_date', date.today().isoformat())
    quantity = float(data.get('quantity', 1.0))

    with get_db() as db:
        item = db.query_one("SELECT calories FROM food_items WHERE id=?", (data['food_item_id'],))
        if not item:
            return jsonify({'error': 'Food item not found'}), 404

        calories_actual = int(item['calories'] * quantity)
        db.execute(
            """INSERT INTO food_log (id, user_id, food_item_id, meal_slot, log_date, quantity, calories_actual, notes)
               VALUES (?,?,?,?,?,?,?,?)""",
            (log_id, g.user['id'], data['food_item_id'], data['meal_slot'], log_date,
             quantity, calories_actual, data.get('notes'))
        )
        row = db.query_one(
            """SELECT fl.*, fi.name as food_name, fi.serving_size, fi.serving_unit,
               c.name as category_name, c.icon as category_icon
               FROM food_log fl JOIN food_items fi ON fl.food_item_id=fi.id
               JOIN categories c ON fi.category_id=c.id
               WHERE fl.id=?""",
            (log_id,)
        )
        return jsonify(row), 201


@app.route('/api/log/<entry_id>', methods=['DELETE'])
def delete_log_entry(entry_id):
    with get_db() as db:
        db.execute("DELETE FROM food_log WHERE id=? AND user_id=?", (entry_id, g.user['id']))
        return jsonify({'deleted': True})


@app.route('/api/log/summary', methods=['GET'])
def get_log_summary():
    log_date = request.args.get('date', date.today().isoformat())
    with get_db() as db:
        totals = db.query_one(
            """SELECT
               SUM(fl.calories_actual) as total_calories,
               SUM(fi.protein_g * fl.quantity) as total_protein,
               SUM(fi.carbs_g * fl.quantity) as total_carbs,
               SUM(fi.fat_g * fl.quantity) as total_fat,
               COUNT(*) as entry_count
               FROM food_log fl JOIN food_items fi ON fl.food_item_id=fi.id
               WHERE fl.log_date=? AND fl.user_id=?""",
            (log_date, g.user['id'])
        )

        by_slot = db.query(
            """SELECT fl.meal_slot, SUM(fl.calories_actual) as calories, COUNT(*) as items
               FROM food_log fl WHERE fl.log_date=? AND fl.user_id=?
               GROUP BY fl.meal_slot""",
            (log_date, g.user['id'])
        )

        return jsonify({
            'date': log_date,
            'totals': totals or {},
            'by_slot': by_slot
        })


@app.route('/api/log/history', methods=['GET'])
def get_log_history():
    days = int(request.args.get('days', 7))
    with get_db() as db:
        if db.backend == 'mssql':
            rows = db.query(
                """SELECT TOP (?) log_date, SUM(calories_actual) as total_calories, COUNT(*) as entries
                   FROM food_log WHERE user_id=?
                   GROUP BY log_date
                   ORDER BY log_date DESC""",
                (days, g.user['id'])
            )
        else:
            rows = db.query(
                """SELECT log_date, SUM(calories_actual) as total_calories, COUNT(*) as entries
                   FROM food_log WHERE user_id=?
                   GROUP BY log_date
                   ORDER BY log_date DESC
                   LIMIT ?""",
                (g.user['id'], days)
            )
        return jsonify(rows)


@app.route('/api/log/calendar', methods=['GET'])
def get_log_calendar():
    """Per-day totals, used by the Month/Week/List calendar views.
    Either ?month=YYYY-MM, or ?start=YYYY-MM-DD&end=YYYY-MM-DD for a week."""
    start = request.args.get('start')
    end = request.args.get('end')
    month = request.args.get('month')

    with get_db() as db:
        if start and end:
            rows = db.query(
                """SELECT log_date, SUM(calories_actual) as total_calories,
                   SUM(quantity) as total_items, COUNT(*) as entries
                   FROM food_log
                   WHERE user_id=? AND log_date BETWEEN ? AND ?
                   GROUP BY log_date
                   ORDER BY log_date""",
                (g.user['id'], start, end)
            )
            return jsonify({'start': start, 'end': end, 'days': rows})

        month = month or date.today().strftime('%Y-%m')
        rows = db.query(
            """SELECT log_date, SUM(calories_actual) as total_calories,
               SUM(quantity) as total_items, COUNT(*) as entries
               FROM food_log
               WHERE user_id=? AND log_date LIKE ?
               GROUP BY log_date
               ORDER BY log_date""",
            (g.user['id'], f'{month}-%')
        )
        return jsonify({'month': month, 'days': rows})


# ── EXPORT API (for AI use) ───────────────────────────────────────────────────

@app.route('/api/export', methods=['GET'])
def export_all():
    """Full database export for the signed-in user (for AI analysis)"""
    with get_db() as db:
        categories = db.query("SELECT * FROM categories ORDER BY sort_order")
        food_items = db.query("SELECT * FROM food_items ORDER BY category_id, name")
        food_log = db.query(
            "SELECT * FROM food_log WHERE user_id=? ORDER BY log_date, logged_at",
            (g.user['id'],)
        )
        return jsonify({
            'exported_at': datetime.utcnow().isoformat(),
            'categories': categories,
            'food_items': food_items,
            'food_log': food_log
        })


# ── FOOD RECOGNITION (camera scan) ────────────────────────────────────────────

@app.route('/api/food-recognition/status', methods=['GET'])
def food_recognition_status():
    return jsonify({'configured': vision.is_configured()})


@app.route('/api/food-recognition', methods=['POST'])
def food_recognition():
    if not vision.is_configured():
        return jsonify({'error': 'Food recognition is not configured yet'}), 503

    photo = request.files.get('photo')
    if not photo:
        return jsonify({'error': 'photo file is required'}), 400

    try:
        analysis = vision.analyze_image(photo.read())
    except Exception as e:
        return jsonify({'error': f'Vision analysis failed: {e}'}), 502

    with get_db() as db:
        category_id = request.args.get('category_id')
        if category_id:
            food_items = db.query(
                """SELECT fi.*, c.name as category_name, c.icon as category_icon
                   FROM food_items fi JOIN categories c ON fi.category_id=c.id
                   WHERE fi.category_id=? AND fi.user_id=?""",
                (category_id, g.user['id'])
            )
        else:
            food_items = db.query(
                """SELECT fi.*, c.name as category_name, c.icon as category_icon
                   FROM food_items fi JOIN categories c ON fi.category_id=c.id
                   WHERE fi.user_id=?""",
                (g.user['id'],)
            )

    suggestions = vision.match_foods(analysis['caption'], analysis['tags'], food_items)
    return jsonify({
        'caption': analysis['caption'],
        'tags': analysis['tags'],
        'suggestions': suggestions
    })


# ── BARCODE LOOKUP (packaged food) ────────────────────────────────────────────

@app.route('/api/barcode-lookup', methods=['POST'])
def barcode_lookup():
    data = request.json or {}
    code = data.get('code')
    category_id = data.get('category_id')
    if not code:
        return jsonify({'error': 'code is required'}), 400
    if not category_id:
        return jsonify({'error': 'category_id is required'}), 400

    with get_db() as db:
        existing = db.query_one(
            """SELECT fi.*, c.name as category_name, c.icon as category_icon
               FROM food_items fi JOIN categories c ON fi.category_id=c.id
               WHERE fi.barcode=? AND fi.user_id=?""",
            (code, g.user['id'])
        )
        if existing:
            return jsonify({'found': True, 'item': existing})

        category = db.query_one("SELECT id FROM categories WHERE id=? AND user_id=?", (category_id, g.user['id']))
        if not category:
            return jsonify({'error': 'Category not found'}), 404

    try:
        product = barcode.lookup(code)
    except Exception as e:
        return jsonify({'error': f'Barcode lookup failed: {e}'}), 502

    if not product:
        return jsonify({'found': False})

    item_id = str(uuid.uuid4())
    with get_db() as db:
        db.execute(
            """INSERT INTO food_items
               (id, user_id, category_id, name, serving_size, serving_unit, calories, protein_g, carbs_g, fat_g, barcode)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (item_id, g.user['id'], category_id, product['name'], product['serving_size'], product['serving_unit'],
             product['calories'], product['protein_g'], product['carbs_g'], product['fat_g'], product['barcode'])
        )
        row = db.query_one(
            """SELECT fi.*, c.name as category_name, c.icon as category_icon
               FROM food_items fi JOIN categories c ON fi.category_id=c.id WHERE fi.id=?""",
            (item_id,)
        )
    return jsonify({'found': True, 'item': row})


# ── OURA INTEGRATION ───────────────────────────────────────────────────────────

@app.route('/api/oura/status', methods=['GET'])
def oura_status():
    return jsonify({
        'configured': oura.is_configured(),
        'connected': oura.is_connected(g.user['id'])
    })


@app.route('/api/oura/authorize', methods=['GET'])
def oura_authorize():
    if not oura.is_configured():
        return jsonify({'error': 'Oura integration is not configured yet'}), 503
    from flask import redirect
    return redirect(oura.build_authorize_url(state=g.user['id']))


@app.route('/api/oura/callback', methods=['GET'])
def oura_callback():
    from flask import redirect
    code = request.args.get('code')
    state = request.args.get('state')
    if not code or state != g.user['id']:
        return redirect('/admin?oura_error=1')
    try:
        oura.exchange_code(g.user['id'], code)
    except Exception:
        return redirect('/admin?oura_error=1')
    return redirect('/admin?oura_connected=1')


@app.route('/api/oura/disconnect', methods=['DELETE'])
def oura_disconnect():
    oura.disconnect(g.user['id'])
    return jsonify({'disconnected': True})


@app.route('/api/oura/summary', methods=['GET'])
def oura_summary():
    days = int(request.args.get('days', 30))
    rows, is_demo = oura.get_summary(g.user['id'], days)
    return jsonify({'days': rows, 'demo': is_demo})


# ── IPHONE HEALTH INTEGRATION ──────────────────────────────────────────────────

@app.route('/api/health/status', methods=['GET'])
def health_status():
    return jsonify({'connected': health.is_connected(g.user['id'])})


@app.route('/api/health/token', methods=['GET'])
def health_token():
    token = health.get_or_create_token(g.user['id'])
    return jsonify({
        'token': token,
        'ingest_url': request.url_root.rstrip('/') + '/api/health/ingest'
    })


@app.route('/api/health/token/regenerate', methods=['POST'])
def health_token_regenerate():
    return jsonify({'token': health.regenerate_token(g.user['id'])})


@app.route('/api/health/summary', methods=['GET'])
def health_summary():
    days = int(request.args.get('days', 30))
    rows, is_demo = health.get_summary(g.user['id'], days)
    return jsonify({'days': rows, 'demo': is_demo})


@app.route('/api/health/ingest', methods=['POST'])
def health_ingest():
    """Called by a Shortcuts automation / Health Auto Export, authenticated
    via the per-user bearer token (see attach_user() above), not a session."""
    payload = request.get_json(silent=True)
    if not payload:
        return jsonify({'error': 'JSON body required'}), 400
    try:
        count = health.ingest(g.user['id'], payload)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'ingested': count})


# ── MCP SERVER (for Copilot Studio / other MCP clients) ───────────────────────

@app.route('/api/mcp', methods=['POST'])
def mcp_endpoint():
    """Streamable HTTP transport, single-JSON-response mode (no SSE — every
    tool here is a quick synchronous lookup). Scoped to g.user via the same
    before_request auth as every other /api/* route."""
    message = request.get_json(silent=True)
    if message is None:
        return jsonify(mcp_server._error(None, -32700, 'Parse error')), 400

    response, status = mcp_server.handle_message(g.user['id'], message)
    if response is None:
        return '', status
    return jsonify(response), status


@app.route('/api/mcp', methods=['GET'])
def mcp_endpoint_get():
    # Streamable HTTP transport allows an optional GET for server-initiated
    # SSE messages — not implemented here, every tool is request/response only.
    return jsonify({'error': 'This MCP server only supports POST (no server-initiated streaming)'}), 405


if __name__ == '__main__':
    print("NutriLog running on http://localhost:5000")
    print("Admin panel at http://localhost:5000/admin")
    app.run(debug=True, port=5000)
