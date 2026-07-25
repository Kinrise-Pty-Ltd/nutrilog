"""iPhone Health integration.

Apple doesn't offer a cloud API for HealthKit, so there's no OAuth-style
pull like Oura. Instead this exposes a bearer-token ingest endpoint that a
device-side automation pushes daily metrics to on a schedule — either an
Apple Shortcuts automation (recommended: we control the exact JSON shape),
or the "Health Auto Export" iOS app pointed at the same URL.
"""
import hashlib
import json
import secrets
import uuid
from datetime import date, timedelta

from db import get_db

FIELDS = [
    'steps', 'active_energy_kcal', 'resting_energy_kcal',
    'exercise_minutes', 'weight_kg', 'resting_hr', 'sleep_minutes',
]


def get_or_create_token(user_id):
    with get_db() as db:
        row = db.query_one("SELECT api_token FROM iphone_health_tokens WHERE user_id=?", (user_id,))
        if row:
            return row['api_token']
        token = secrets.token_urlsafe(32)
        db.execute(
            "INSERT INTO iphone_health_tokens (user_id, api_token) VALUES (?,?)",
            (user_id, token)
        )
        return token


def regenerate_token(user_id):
    token = secrets.token_urlsafe(32)
    with get_db() as db:
        db.execute("DELETE FROM iphone_health_tokens WHERE user_id=?", (user_id,))
        db.execute(
            "INSERT INTO iphone_health_tokens (user_id, api_token) VALUES (?,?)",
            (user_id, token)
        )
    return token


def user_id_for_token(token):
    if not token:
        return None
    with get_db() as db:
        row = db.query_one("SELECT user_id FROM iphone_health_tokens WHERE api_token=?", (token,))
        return row['user_id'] if row else None


def is_connected(user_id):
    with get_db() as db:
        return db.query_one(
            "SELECT id FROM iphone_health_daily WHERE user_id=? AND is_demo=0", (user_id,)
        ) is not None


def _one_day(payload):
    day = payload.get('date')
    if not day:
        raise ValueError('Each day entry needs a "date" (YYYY-MM-DD)')
    return day, {k: payload.get(k) for k in FIELDS}


def ingest(user_id, payload):
    """Accepts either a single day object or {"days": [ ... ]}."""
    entries = payload['days'] if isinstance(payload, dict) and 'days' in payload else [payload]

    with get_db() as db:
        for entry in entries:
            day, values = _one_day(entry)
            db.execute("DELETE FROM iphone_health_daily WHERE user_id=? AND date=?", (user_id, day))
            db.execute(
                """INSERT INTO iphone_health_daily
                   (id, user_id, date, steps, active_energy_kcal, resting_energy_kcal,
                    exercise_minutes, weight_kg, resting_hr, sleep_minutes, raw_json, is_demo)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,0)""",
                (str(uuid.uuid4()), user_id, day, values['steps'], values['active_energy_kcal'],
                 values['resting_energy_kcal'], values['exercise_minutes'], values['weight_kg'],
                 values['resting_hr'], values['sleep_minutes'], json.dumps(entry))
            )
    return len(entries)


def _demo_day(user_id, day):
    seed = int(hashlib.sha256(f'health:{user_id}:{day.isoformat()}'.encode()).hexdigest()[:8], 16)

    def pick(lo, hi, salt):
        return lo + (seed ^ salt) % (hi - lo + 1)

    return {
        'date': day.isoformat(),
        'steps': pick(4000, 13000, 1),
        'active_energy_kcal': pick(300, 900, 2),
        'resting_energy_kcal': pick(1500, 2000, 3),
        'exercise_minutes': pick(10, 60, 4),
        'weight_kg': round(78 + (pick(0, 40, 5) - 20) / 10, 1),
        'resting_hr': pick(52, 68, 6),
        'sleep_minutes': pick(360, 480, 7),
        'is_demo': True,
    }


def demo_summary(user_id, days=30):
    today = date.today()
    return [_demo_day(user_id, today - timedelta(days=i)) for i in range(days - 1, -1, -1)]


def get_summary(user_id, days=30):
    if is_connected(user_id):
        with get_db() as db:
            rows = db.query(
                """SELECT date, steps, active_energy_kcal, resting_energy_kcal,
                   exercise_minutes, weight_kg, resting_hr, sleep_minutes, 0 as is_demo
                   FROM iphone_health_daily
                   WHERE user_id=? AND date >= ?
                   ORDER BY date""",
                (user_id, (date.today() - timedelta(days=days - 1)).isoformat())
            )
        if rows:
            return rows, False
    return demo_summary(user_id, days), True
