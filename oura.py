"""Oura Ring integration: OAuth2 (Oura deprecated Personal Access Tokens in
Dec 2025 — new integrations must use OAuth2), plus a deterministic demo
dataset shown until a user actually connects their ring.
"""
import hashlib
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

from db import get_db

AUTH_URL = 'https://cloud.ouraring.com/oauth/authorize'
TOKEN_URL = 'https://api.ouraring.com/oauth/token'
API_BASE = 'https://api.ouraring.com/v2/usercollection'

CLIENT_ID = os.environ.get('OURA_CLIENT_ID')
CLIENT_SECRET = os.environ.get('OURA_CLIENT_SECRET')
REDIRECT_URI = os.environ.get('OURA_REDIRECT_URI')
SCOPES = 'daily heartrate'


def is_configured():
    return bool(CLIENT_ID and CLIENT_SECRET and REDIRECT_URI)


def build_authorize_url(state):
    params = {
        'response_type': 'code',
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'scope': SCOPES,
        'state': state,
    }
    return f'{AUTH_URL}?{urlencode(params)}'


def _save_tokens(user_id, token_data):
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=token_data['expires_in'])).isoformat()
    with get_db() as db:
        db.execute("DELETE FROM oura_tokens WHERE user_id=?", (user_id,))
        db.execute(
            """INSERT INTO oura_tokens (user_id, access_token, refresh_token, expires_at, scope)
               VALUES (?,?,?,?,?)""",
            (user_id, token_data['access_token'], token_data['refresh_token'],
             expires_at, token_data.get('scope', SCOPES))
        )


def exchange_code(user_id, code):
    resp = requests.post(TOKEN_URL, data={
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': REDIRECT_URI,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
    }, timeout=15)
    resp.raise_for_status()
    _save_tokens(user_id, resp.json())


def _refresh(user_id, refresh_token_value):
    resp = requests.post(TOKEN_URL, data={
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token_value,
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
    }, timeout=15)
    resp.raise_for_status()
    token_data = resp.json()
    _save_tokens(user_id, token_data)
    return token_data['access_token']


def is_connected(user_id):
    with get_db() as db:
        return db.query_one("SELECT user_id FROM oura_tokens WHERE user_id=?", (user_id,)) is not None


def disconnect(user_id):
    with get_db() as db:
        db.execute("DELETE FROM oura_tokens WHERE user_id=?", (user_id,))


def _get_valid_access_token(user_id):
    with get_db() as db:
        row = db.query_one("SELECT * FROM oura_tokens WHERE user_id=?", (user_id,))
    if not row:
        return None
    expires_at = datetime.fromisoformat(row['expires_at'])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at > datetime.now(timezone.utc) + timedelta(minutes=2):
        return row['access_token']
    return _refresh(user_id, row['refresh_token'])


def _resting_hr_by_day(headers, start, end):
    """Approximates daily resting HR as the minimum bpm sample recorded that day."""
    try:
        resp = requests.get(f'{API_BASE}/heartrate', headers=headers, params={
            'start_datetime': f'{start.isoformat()}T00:00:00-00:00',
            'end_datetime': f'{end.isoformat()}T23:59:59-00:00',
        }, timeout=15)
        resp.raise_for_status()
        by_day = {}
        for sample in resp.json().get('data', []):
            day = sample['timestamp'][:10]
            bpm = sample.get('bpm')
            if bpm is None:
                continue
            by_day[day] = min(bpm, by_day.get(day, bpm))
        return by_day
    except requests.RequestException:
        return {}


def fetch_live_summary(user_id, days=30):
    """Live-fetches from Oura v2 and caches into oura_daily. Returns the day rows."""
    token = _get_valid_access_token(user_id)
    if not token:
        return None

    end = date.today()
    start = end - timedelta(days=days - 1)
    headers = {'Authorization': f'Bearer {token}'}
    params = {'start_date': start.isoformat(), 'end_date': end.isoformat()}

    by_date = {}

    def _merge(endpoint, mapper):
        try:
            resp = requests.get(f'{API_BASE}/{endpoint}', headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            for row in resp.json().get('data', []):
                mapper(by_date.setdefault(row['day'], {}), row)
        except requests.RequestException:
            pass

    _merge('daily_sleep', lambda d, row: d.__setitem__('sleep_score', row.get('score')))
    _merge('daily_readiness', lambda d, row: d.__setitem__('readiness_score', row.get('score')))

    def _activity(d, row):
        d['activity_score'] = row.get('score')
        d['steps'] = row.get('steps')
        d['calories_burned'] = row.get('active_calories')

    _merge('daily_activity', _activity)

    resting_hr_by_day = _resting_hr_by_day(headers, start, end)

    with get_db() as db:
        results = []
        for day, vals in sorted(by_date.items()):
            row = {
                'date': day,
                'sleep_score': vals.get('sleep_score'),
                'readiness_score': vals.get('readiness_score'),
                'activity_score': vals.get('activity_score'),
                'steps': vals.get('steps'),
                'resting_hr': resting_hr_by_day.get(day),
                'total_sleep_minutes': None,
                'calories_burned': vals.get('calories_burned'),
                'is_demo': False,
            }
            results.append(row)
            db.execute("DELETE FROM oura_daily WHERE user_id=? AND date=?", (user_id, day))
            db.execute(
                """INSERT INTO oura_daily
                   (id, user_id, date, sleep_score, readiness_score, activity_score,
                    steps, resting_hr, total_sleep_minutes, calories_burned, is_demo)
                   VALUES (?,?,?,?,?,?,?,?,?,?,0)""",
                (str(uuid.uuid4()), user_id, day, row['sleep_score'], row['readiness_score'],
                 row['activity_score'], row['steps'], row['resting_hr'],
                 row['total_sleep_minutes'], row['calories_burned'])
            )
    return results


def _demo_day(user_id, day):
    seed = int(hashlib.sha256(f'{user_id}:{day.isoformat()}'.encode()).hexdigest()[:8], 16)

    def pick(lo, hi, salt):
        return lo + (seed ^ salt) % (hi - lo + 1)

    return {
        'date': day.isoformat(),
        'sleep_score': pick(65, 92, 1),
        'readiness_score': pick(60, 90, 2),
        'activity_score': pick(55, 88, 3),
        'steps': pick(4000, 12000, 4),
        'resting_hr': pick(52, 68, 5),
        'total_sleep_minutes': pick(360, 480, 6),
        'calories_burned': pick(1800, 2800, 7),
        'is_demo': True,
    }


def demo_summary(user_id, days=30):
    today = date.today()
    return [_demo_day(user_id, today - timedelta(days=i)) for i in range(days - 1, -1, -1)]


def get_summary(user_id, days=30):
    """Live data if connected, otherwise the demo dataset (flagged is_demo)."""
    if is_connected(user_id):
        live = fetch_live_summary(user_id, days)
        if live:
            return live, False
    return demo_summary(user_id, days), True
