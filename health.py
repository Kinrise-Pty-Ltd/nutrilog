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

# Health Auto Export's REST API export has its own fixed JSON shape
# ({"data": {"metrics": [{"name": ..., "data": [{"date": ..., "qty": ...}]}]}})
# unlike a Shortcuts automation, where you build the request body yourself
# and can match our flat shape directly. Metric names are HealthKit
# identifiers in snake_case; a few historical aliases are included
# defensively since exact naming has varied across app versions.
HEALTH_AUTO_EXPORT_METRIC_FIELDS = {
    'step_count': 'steps',
    'steps': 'steps',
    'active_energy': 'active_energy_kcal',
    'active_energy_burned': 'active_energy_kcal',
    'basal_energy_burned': 'resting_energy_kcal',
    'resting_energy': 'resting_energy_kcal',
    'apple_exercise_time': 'exercise_minutes',
    'exercise_time': 'exercise_minutes',
    'weight_body_mass': 'weight_kg',
    'body_mass': 'weight_kg',
    'weight': 'weight_kg',
    'resting_heart_rate': 'resting_hr',
    'heart_rate_resting': 'resting_hr',
}
HEALTH_AUTO_EXPORT_SLEEP_METRICS = {'sleep_analysis', 'sleep'}


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


def _is_health_auto_export_payload(payload):
    return (
        isinstance(payload, dict)
        and isinstance(payload.get('data'), dict)
        and isinstance(payload['data'].get('metrics'), list)
    )


def _parse_health_auto_export(payload):
    """Converts Health Auto Export's {"data": {"metrics": [...]}} shape into
    our internal per-day dicts, merging every metric that falls on the same
    date into one record."""
    by_date = {}
    unrecognized = set()

    for metric in payload['data']['metrics']:
        name = (metric.get('name') or '').strip().lower()
        is_sleep = name in HEALTH_AUTO_EXPORT_SLEEP_METRICS
        field = HEALTH_AUTO_EXPORT_METRIC_FIELDS.get(name)
        if not field and not is_sleep:
            if name:
                unrecognized.add(name)
            continue

        for point in metric.get('data') or []:
            raw_date = point.get('date') or point.get('startDate') or point.get('sleepStart')
            if not raw_date:
                continue
            day = raw_date[:10]  # "2026-07-26 00:00:00 +1000" / "2026-07-26T00:00:00+10:00" -> "2026-07-26"
            record = by_date.setdefault(day, {'date': day})

            if is_sleep:
                asleep = point.get('asleep')
                if asleep is None:
                    asleep = point.get('value')
                if asleep is not None:
                    # HAE has historically reported hours asleep as a decimal
                    # (e.g. 7.4), not minutes — treat anything <=24 as hours.
                    record['sleep_minutes'] = round(asleep * 60 if asleep <= 24 else asleep)
            else:
                qty = point.get('qty')
                if qty is not None:
                    record[field] = round(qty, 1) if field == 'weight_kg' else round(qty)

    if unrecognized:
        print(f'[health.ingest] Unrecognized Health Auto Export metric name(s): {sorted(unrecognized)}')

    return list(by_date.values())


def ingest(user_id, payload):
    """Accepts a single day object, {"days": [...]} (NutriLog's own flat
    shape — e.g. a Shortcuts automation you build yourself), or Health Auto
    Export's own REST API export shape ({"data": {"metrics": [...]}})."""
    if _is_health_auto_export_payload(payload):
        entries = _parse_health_auto_export(payload)
        if not entries:
            print(f'[health.ingest] Health Auto Export payload produced no usable day entries: {json.dumps(payload)[:2000]}')
            raise ValueError('No recognizable health metrics found in that Health Auto Export payload')
    else:
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
