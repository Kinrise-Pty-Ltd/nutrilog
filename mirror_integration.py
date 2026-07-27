"""Server-to-server integration for the Mirror avatar project.

Mirror's backend has no Easy Auth session of its own, so it authenticates
with a per-user bearer token instead — same design as health.py's iPhone
Health ingest token (see `mirror_api_tokens`, mirroring
`iphone_health_tokens`). Covers read access (daily summary, log entries,
history) plus voice-driven logging: matching a free-text query and meal name
against the user's own catalog and inserting a food_log row via
db.insert_food_log_entry().

Matching is deliberately conservative — a query that could refer to any of
several catalog items, or a meal that isn't clearly one of this user's own
categories, returns candidates for disambiguation instead of guessing and
writing the wrong thing.
"""
import re
import secrets
from datetime import date, datetime

from db import get_db, insert_food_log_entry


# ── Token management (mirrors health.py's get_or_create_token/etc.) ───────

def get_or_create_token(user_id):
    with get_db() as db:
        row = db.query_one("SELECT api_token FROM mirror_api_tokens WHERE user_id=?", (user_id,))
        if row:
            return row['api_token']
        token = secrets.token_urlsafe(32)
        db.execute(
            "INSERT INTO mirror_api_tokens (user_id, api_token) VALUES (?,?)",
            (user_id, token)
        )
        return token


def regenerate_token(user_id):
    token = secrets.token_urlsafe(32)
    with get_db() as db:
        db.execute("DELETE FROM mirror_api_tokens WHERE user_id=?", (user_id,))
        db.execute(
            "INSERT INTO mirror_api_tokens (user_id, api_token) VALUES (?,?)",
            (user_id, token)
        )
    return token


def user_id_for_token(token):
    if not token:
        return None
    with get_db() as db:
        row = db.query_one("SELECT user_id FROM mirror_api_tokens WHERE api_token=?", (token,))
        return row['user_id'] if row else None


# ── Read helpers (user-scoped, same shape as the equivalent MCP tools) ────

def get_daily_summary(user_id, log_date=None):
    log_date = log_date or date.today().isoformat()
    with get_db() as db:
        totals = db.query_one(
            """SELECT SUM(fl.calories_actual) as total_calories,
               SUM(fi.protein_g * fl.quantity) as total_protein,
               SUM(fi.carbs_g * fl.quantity) as total_carbs,
               SUM(fi.fat_g * fl.quantity) as total_fat,
               COUNT(*) as entry_count
               FROM food_log fl JOIN food_items fi ON fl.food_item_id=fi.id
               WHERE fl.log_date=? AND fl.user_id=?""",
            (log_date, user_id)
        )
        by_meal = db.query(
            """SELECT c.name as meal, SUM(fl.calories_actual) as calories, COUNT(*) as items
               FROM food_log fl
               JOIN categories c ON fl.meal_slot=c.id
               WHERE fl.log_date=? AND fl.user_id=?
               GROUP BY c.name""",
            (log_date, user_id)
        )
    return {'date': log_date, 'totals': totals or {}, 'by_meal': by_meal}


def get_log_entries(user_id, log_date=None):
    log_date = log_date or date.today().isoformat()
    with get_db() as db:
        rows = db.query(
            """SELECT c.name as meal, fi.name as food_name, fl.quantity,
               fi.serving_size, fi.serving_unit, fl.calories_actual,
               fi.protein_g * fl.quantity as protein_g,
               fi.carbs_g * fl.quantity as carbs_g,
               fi.fat_g * fl.quantity as fat_g, fl.notes
               FROM food_log fl
               JOIN food_items fi ON fl.food_item_id=fi.id
               JOIN categories c ON fl.meal_slot=c.id
               WHERE fl.log_date=? AND fl.user_id=?
               ORDER BY c.sort_order, fl.logged_at""",
            (log_date, user_id)
        )
    return {'date': log_date, 'entries': rows}


def get_history(user_id, days=7):
    with get_db() as db:
        if db.backend == 'mssql':
            rows = db.query(
                """SELECT TOP (?) log_date, SUM(calories_actual) as total_calories, COUNT(*) as entries
                   FROM food_log WHERE user_id=? GROUP BY log_date ORDER BY log_date DESC""",
                (days, user_id)
            )
        else:
            rows = db.query(
                """SELECT log_date, SUM(calories_actual) as total_calories, COUNT(*) as entries
                   FROM food_log WHERE user_id=? GROUP BY log_date ORDER BY log_date DESC LIMIT ?""",
                (user_id, days)
            )
    return {'days': rows}


# ── Meal resolution ─────────────────────────────────────────────────────

# Fallback time-of-day -> meal-name keywords, used only when the caller
# didn't say which meal. Matched against this user's *actual* category
# names (never assumed to exist) — a user who renamed/removed "Breakfast"
# simply won't get a time-based match and must name the meal explicitly.
_TIME_OF_DAY_KEYWORDS = [
    (0, 10, ['breakfast']),
    (10, 14, ['lunch']),
    (14, 17, ['afternoon tea', 'snack']),
    (17, 21, ['dinner']),
    (21, 24, ['snack']),
]


def _time_of_day_keywords(hour):
    for lo, hi, keywords in _TIME_OF_DAY_KEYWORDS:
        if lo <= hour < hi:
            return keywords
    return ['snack']


def resolve_meal(user_id, meal_name=None):
    """Returns the matching category id for this user, or None if nothing
    can be confidently resolved — callers must not guess a category."""
    with get_db() as db:
        categories = db.query(
            "SELECT id, name FROM categories WHERE user_id=? ORDER BY sort_order", (user_id,)
        )
    if not categories:
        return None

    candidates = [meal_name] if meal_name else _time_of_day_keywords(datetime.now().hour)
    for candidate in candidates:
        candidate_l = candidate.lower().strip()
        for cat in categories:
            name_l = cat['name'].lower()
            if candidate_l == name_l or candidate_l in name_l or name_l in candidate_l:
                return cat['id']
    return None


# ── Food matching ───────────────────────────────────────────────────────

# Digits are dropped entirely by the word regex below — a catalog item like
# "Whole Eggs (2)" has a decorative pack-size annotation, not a searchable
# word, and a spoken quantity ("two eggs") belongs in the separate `quantity`
# field, not the name match. These fillers are stripped the same way so
# "two whole eggs" still matches "Whole Eggs" cleanly.
_WORD_RE = re.compile(r"[a-z]+")
_STOPWORDS = {
    'a', 'an', 'the', 'some', 'my', 'of',
    'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten',
}


def _clean_words(text):
    """List, not set — preserves word order so prefix ("startswith") matching
    still behaves sensibly after filler words are removed."""
    return [w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS]


def _score(query, item_name):
    q_words, n_words = _clean_words(query), _clean_words(item_name)
    q, n = ' '.join(q_words), ' '.join(n_words)
    if not q or not n:
        return 0
    if q == n:
        return 100
    if n.startswith(q) or q.startswith(n):
        return 80
    q_tokens, n_tokens = set(q_words), set(n_words)
    if q_tokens.issubset(n_tokens):
        return 60 + 10 * (len(q_tokens) / len(n_tokens))
    overlap = q_tokens & n_tokens
    return 50 * (len(overlap) / len(q_tokens | n_tokens)) if overlap else 0


def match_food(user_id, query):
    """Returns (best_item_or_None, confident: bool, top_candidates: list)."""
    with get_db() as db:
        items = db.query("SELECT * FROM food_items WHERE user_id=?", (user_id,))
    if not items:
        return None, False, []

    scored = sorted(
        ((item, _score(query, item['name'])) for item in items),
        key=lambda pair: pair[1], reverse=True
    )
    top_candidates = [item for item, score in scored[:5] if score > 0]
    best_item, best_score = scored[0]
    second_score = scored[1][1] if len(scored) > 1 else 0
    confident = best_score >= 60 and (best_score - second_score) >= 15
    return (best_item if confident else None), confident, top_candidates


# ── Logging orchestration ───────────────────────────────────────────────

def log_entry(user_id, query, meal=None, quantity=1.0, log_date=None):
    """Resolves `query` + `meal` against this user's catalog and logs it if
    (and only if) both resolve confidently. A wrong write is worse than
    asking again, so an ambiguous/no match returns candidates instead."""
    log_date = log_date or date.today().isoformat()
    item, confident, candidates = match_food(user_id, query)
    category_id = resolve_meal(user_id, meal)

    if not confident or not category_id:
        with get_db() as db:
            categories = db.query("SELECT name FROM categories WHERE user_id=? ORDER BY sort_order", (user_id,))
        return {
            'matched': False,
            'query': query,
            'reason': 'no_confident_food_match' if not confident else 'meal_not_resolved',
            'candidates': [{'id': c['id'], 'name': c['name']} for c in candidates],
            'available_meals': [c['name'] for c in categories],
        }

    row = insert_food_log_entry(user_id, item['id'], category_id, quantity, log_date)
    return {'matched': True, 'entry': row}
