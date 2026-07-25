"""Oura Ring integration: OAuth2 (Oura deprecated Personal Access Tokens in
Dec 2025 — new integrations must use OAuth2), plus a deterministic demo
dataset shown until a user actually connects their ring.

Metric provenance — worth knowing when debugging real data:
  - sleep_score, readiness_score, activity_score, steps, calories_burned,
    temperature_deviation, spo2_percent: direct fields from Oura's daily_*
    endpoints.
  - hrv_ms, sleep_efficiency, deep_sleep_minutes, rem_sleep_minutes,
    respiratory_rate: pulled from the detailed `sleep` endpoint (Oura's
    per-session data), not a daily summary endpoint.
  - resting_hr: approximated as the day's minimum heart-rate sample, since
    Oura's v2 API doesn't expose a single "resting HR" daily field.
  - physical_recovery_score: approximated from daily_resilience's
    sleep_recovery/daytime_recovery contributors — Oura doesn't expose a
    field literally called "physical recovery".
  - cognitive_recovery_score: approximated from daily_stress's recovery_high
    minutes, normalized to 0-100. Oura has no "cognitive recovery" metric;
    this is our own rough proxy.
  - illness_risk_score: NOT an Oura field at all. Computed locally from
    temperature_deviation and resting_hr deviating from the recent personal
    baseline — a simple heuristic, not a clinical or official signal.
"""
import hashlib
import os
import statistics
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
SCOPES = 'daily heartrate spo2'

DAILY_FIELDS = [
    'sleep_score', 'readiness_score', 'activity_score', 'steps', 'resting_hr',
    'total_sleep_minutes', 'calories_burned', 'hrv_ms', 'sleep_efficiency',
    'deep_sleep_minutes', 'rem_sleep_minutes', 'temperature_deviation',
    'spo2_percent', 'respiratory_rate', 'physical_recovery_score',
    'cognitive_recovery_score', 'illness_risk_score',
]


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


def _sleep_detail_by_day(headers, start, end):
    """Pulls HRV/efficiency/deep/REM/respiratory rate from the detailed sleep
    endpoint, preferring the 'long_sleep' period when a day has multiple."""
    try:
        resp = requests.get(f'{API_BASE}/sleep', headers=headers, params={
            'start_date': start.isoformat(), 'end_date': end.isoformat(),
        }, timeout=15)
        resp.raise_for_status()
        by_day = {}
        for period in resp.json().get('data', []):
            day = period.get('day')
            if not day:
                continue
            if day in by_day and period.get('type') != 'long_sleep':
                continue  # keep the long_sleep period if we already have one
            by_day[day] = {
                'hrv_ms': period.get('average_hrv'),
                'sleep_efficiency': period.get('efficiency'),
                'deep_sleep_minutes': _seconds_to_minutes(period.get('deep_sleep_duration')),
                'rem_sleep_minutes': _seconds_to_minutes(period.get('rem_sleep_duration')),
                'respiratory_rate': period.get('average_breath'),
                'total_sleep_minutes': _seconds_to_minutes(period.get('total_sleep_duration')),
            }
        return by_day
    except requests.RequestException:
        return {}


def _seconds_to_minutes(seconds):
    return round(seconds / 60) if seconds is not None else None


def _compute_illness_risk(by_date):
    """Local heuristic only — not an Oura field. Flags days where temperature
    deviation and resting HR both sit meaningfully above the window's own
    baseline, similar in spirit to (but not the same as) Oura's own illness
    insights, which aren't exposed via the public API."""
    temps = [v['temperature_deviation'] for v in by_date.values() if v.get('temperature_deviation') is not None]
    hrs = [v['resting_hr'] for v in by_date.values() if v.get('resting_hr') is not None]
    if len(temps) < 3 or len(hrs) < 3:
        for v in by_date.values():
            v['illness_risk_score'] = None
        return

    temp_baseline = statistics.median(temps)
    hr_baseline = statistics.median(hrs)

    for v in by_date.values():
        temp_dev = v.get('temperature_deviation')
        hr = v.get('resting_hr')
        if temp_dev is None or hr is None:
            v['illness_risk_score'] = None
            continue
        temp_signal = max(0.0, (temp_dev - temp_baseline)) * 40
        hr_signal = max(0, (hr - hr_baseline)) * 4
        v['illness_risk_score'] = round(min(100, temp_signal + hr_signal))


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

    def _readiness(d, row):
        d['readiness_score'] = row.get('score')
        d['temperature_deviation'] = row.get('temperature_deviation')

    _merge('daily_sleep', lambda d, row: d.__setitem__('sleep_score', row.get('score')))
    _merge('daily_readiness', _readiness)

    def _activity(d, row):
        d['activity_score'] = row.get('score')
        d['steps'] = row.get('steps')
        d['calories_burned'] = row.get('active_calories')

    _merge('daily_activity', _activity)

    def _spo2(d, row):
        d['spo2_percent'] = (row.get('spo2_percentage') or {}).get('average')

    _merge('daily_spo2', _spo2)

    def _resilience(d, row):
        contributors = row.get('contributors') or {}
        parts = [v for v in (contributors.get('sleep_recovery'), contributors.get('daytime_recovery')) if v is not None]
        d['physical_recovery_score'] = round(sum(parts) / len(parts)) if parts else None

    _merge('daily_resilience', _resilience)

    def _stress(d, row):
        recovery_minutes = row.get('recovery_high')
        d['cognitive_recovery_score'] = round(min(100, recovery_minutes / 180 * 100)) if recovery_minutes is not None else None

    _merge('daily_stress', _stress)

    resting_hr_by_day = _resting_hr_by_day(headers, start, end)
    sleep_detail_by_day = _sleep_detail_by_day(headers, start, end)

    for day, detail in sleep_detail_by_day.items():
        by_date.setdefault(day, {}).update(detail)
    for day, hr in resting_hr_by_day.items():
        by_date.setdefault(day, {})['resting_hr'] = hr

    _compute_illness_risk(by_date)

    with get_db() as db:
        results = []
        for day, vals in sorted(by_date.items()):
            row = {'date': day, 'is_demo': False}
            row.update({f: vals.get(f) for f in DAILY_FIELDS})
            results.append(row)
            db.execute("DELETE FROM oura_daily WHERE user_id=? AND date=?", (user_id, day))
            db.execute(
                f"""INSERT INTO oura_daily
                   (id, user_id, date, {', '.join(DAILY_FIELDS)}, is_demo)
                   VALUES (?,?,?,{','.join(['?'] * len(DAILY_FIELDS))},0)""",
                (str(uuid.uuid4()), user_id, day, *[row[f] for f in DAILY_FIELDS])
            )
    return results


def _demo_day(user_id, day):
    seed = int(hashlib.sha256(f'{user_id}:{day.isoformat()}'.encode()).hexdigest()[:8], 16)

    def pick(lo, hi, salt):
        return lo + (seed ^ salt) % (hi - lo + 1)

    def pick_f(lo, hi, salt, decimals=1):
        span = int((hi - lo) * (10 ** decimals))
        return round(lo + ((seed ^ salt) % (span + 1)) / (10 ** decimals), decimals)

    sleep_score = pick(65, 92, 1)
    readiness_score = pick(60, 90, 2)
    resting_hr = pick(52, 68, 5)

    return {
        'date': day.isoformat(),
        'sleep_score': sleep_score,
        'readiness_score': readiness_score,
        'activity_score': pick(55, 88, 3),
        'steps': pick(4000, 12000, 4),
        'resting_hr': resting_hr,
        'total_sleep_minutes': pick(360, 480, 6),
        'calories_burned': pick(1800, 2800, 7),
        'hrv_ms': pick_f(28, 75, 8),
        'sleep_efficiency': pick(80, 96, 9),
        'deep_sleep_minutes': pick(45, 110, 10),
        'rem_sleep_minutes': pick(60, 130, 11),
        'temperature_deviation': pick_f(-0.4, 0.5, 12, 2),
        'spo2_percent': pick_f(95.5, 98.5, 13),
        'respiratory_rate': pick_f(13.5, 17.5, 14),
        'physical_recovery_score': round((sleep_score + readiness_score) / 2) + pick(-5, 5, 15),
        'cognitive_recovery_score': pick(40, 90, 16),
        'illness_risk_score': pick(0, 12, 17),  # demo days stay "low risk"
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
