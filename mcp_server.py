"""A minimal MCP (Model Context Protocol) server, hand-rolled as plain JSON-RPC
over a single Flask route rather than using the official `mcp` SDK's built-in
HTTP server — that server is Starlette/ASGI-based, which doesn't mount into
this app's existing WSGI/gunicorn deployment. Implements just enough of the
Streamable HTTP transport (2025-03-26) for tool-calling clients like Copilot
Studio: `initialize`, `tools/list`, `tools/call`, and no-op notification
handling. No SSE / server-initiated streaming — every tool here is a quick,
synchronous data lookup, so a single JSON response per request is sufficient
(and is explicitly spec-valid, not a shortcut).

Mounted at /api/mcp, so it's covered by the same before_request Easy Auth
user-resolution as every other /api/* route — no separate auth code needed
here. Whoever is authenticated (via Entra ID token or browser session) only
ever sees their own data, same as the rest of the app.
"""
import json
from datetime import date

from db import get_db
import health
import oura

PROTOCOL_VERSION = '2025-03-26'
SERVER_INFO = {'name': 'nutrilog-mcp', 'version': '1.0.0'}


def _daily_summary(user_id, args):
    log_date = args.get('date') or date.today().isoformat()
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
        by_slot = db.query(
            """SELECT c.name as meal, SUM(fl.calories_actual) as calories, COUNT(*) as items
               FROM food_log fl
               JOIN food_items fi ON fl.food_item_id=fi.id
               JOIN categories c ON fi.category_id=c.id
               WHERE fl.log_date=? AND fl.user_id=?
               GROUP BY c.name""",
            (log_date, user_id)
        )
    return {'date': log_date, 'totals': totals or {}, 'by_meal': by_slot}


def _log_history(user_id, args):
    days = int(args.get('days', 7))
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


def _oura_summary(user_id, args):
    days = int(args.get('days', 30))
    rows, is_demo = oura.get_summary(user_id, days)
    return {'days': rows, 'demo': is_demo,
            'note': 'demo=true means Oura is not connected yet; this is placeholder data' if is_demo else None}


def _health_summary(user_id, args):
    days = int(args.get('days', 30))
    rows, is_demo = health.get_summary(user_id, days)
    return {'days': rows, 'demo': is_demo,
            'note': 'demo=true means the iPhone Health automation is not connected yet; this is placeholder data' if is_demo else None}


TOOLS = [
    {
        'name': 'get_daily_nutrition_summary',
        'description': "Get the signed-in user's logged calories, macros, and meal breakdown for a given day (defaults to today).",
        'inputSchema': {
            'type': 'object',
            'properties': {'date': {'type': 'string', 'description': 'YYYY-MM-DD, defaults to today'}},
        },
        'handler': _daily_summary,
    },
    {
        'name': 'get_nutrition_log_history',
        'description': "Get the signed-in user's daily calorie totals over the last N days (defaults to 7).",
        'inputSchema': {
            'type': 'object',
            'properties': {'days': {'type': 'integer', 'description': 'Number of days to look back, defaults to 7'}},
        },
        'handler': _log_history,
    },
    {
        'name': 'get_oura_trends',
        'description': "Get the signed-in user's Oura Ring trends (readiness, sleep, HRV, recovery, etc.) over the last N days. Returns demo data if Oura isn't connected yet.",
        'inputSchema': {
            'type': 'object',
            'properties': {'days': {'type': 'integer', 'description': 'Number of days to look back, defaults to 30'}},
        },
        'handler': _oura_summary,
    },
    {
        'name': 'get_iphone_health_trends',
        'description': "Get the signed-in user's iPhone Health trends (steps, active energy, weight, sleep) over the last N days. Returns demo data if not connected yet.",
        'inputSchema': {
            'type': 'object',
            'properties': {'days': {'type': 'integer', 'description': 'Number of days to look back, defaults to 30'}},
        },
        'handler': _health_summary,
    },
]
TOOLS_BY_NAME = {t['name']: t for t in TOOLS}


def _error(request_id, code, message):
    return {'jsonrpc': '2.0', 'id': request_id, 'error': {'code': code, 'message': message}}


def _result(request_id, result):
    return {'jsonrpc': '2.0', 'id': request_id, 'result': result}


def handle_message(user_id, message):
    """Handles one JSON-RPC message. Returns (response_dict_or_None, http_status).
    None means "notification, no response body" (still 202)."""
    if not isinstance(message, dict) or message.get('jsonrpc') != '2.0':
        return _error(message.get('id') if isinstance(message, dict) else None, -32600, 'Invalid Request'), 400

    method = message.get('method')
    request_id = message.get('id')
    params = message.get('params') or {}
    is_notification = 'id' not in message

    if method == 'initialize':
        result = {
            'protocolVersion': PROTOCOL_VERSION,
            'capabilities': {'tools': {}},
            'serverInfo': SERVER_INFO,
        }
        return _result(request_id, result), 200

    if method == 'notifications/initialized':
        return None, 202

    if method == 'tools/list':
        tools = [{'name': t['name'], 'description': t['description'], 'inputSchema': t['inputSchema']} for t in TOOLS]
        return _result(request_id, {'tools': tools}), 200

    if method == 'tools/call':
        tool_name = params.get('name')
        tool = TOOLS_BY_NAME.get(tool_name)
        if not tool:
            return _error(request_id, -32602, f'Unknown tool: {tool_name}'), 200
        try:
            data = tool['handler'](user_id, params.get('arguments') or {})
            content = [{'type': 'text', 'text': json.dumps(data, indent=2, default=str)}]
            return _result(request_id, {'content': content, 'isError': False}), 200
        except Exception as e:
            content = [{'type': 'text', 'text': f'Tool error: {e}'}]
            return _result(request_id, {'content': content, 'isError': True}), 200

    if is_notification:
        return None, 202

    return _error(request_id, -32601, f'Method not found: {method}'), 200
