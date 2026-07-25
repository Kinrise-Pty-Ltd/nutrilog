"""Resolves the current user from Azure App Service Easy Auth headers.

In production, App Service Authentication (Easy Auth) sits in front of every
request and injects X-MS-CLIENT-PRINCIPAL-* headers once a user has signed
in via Entra ID. Locally (no Easy Auth in front of the dev server), we fall
back to a single DEV_USER_EMAIL so the app is still usable for development.
"""
import os
import uuid

from flask import request

from db import get_db, seed_user_catalog

DEV_USER_EMAIL = os.environ.get('DEV_USER_EMAIL', 'dev@localhost')
DEV_USER_NAME = os.environ.get('DEV_USER_NAME', 'Dev User')


def get_identity():
    """Returns (entra_oid, email, display_name) for the caller."""
    principal_id = request.headers.get('X-MS-CLIENT-PRINCIPAL-ID')
    principal_name = request.headers.get('X-MS-CLIENT-PRINCIPAL-NAME')
    if principal_id and principal_name:
        display_name = request.headers.get('X-MS-CLIENT-PRINCIPAL-DISPLAYNAME') or principal_name
        return principal_id, principal_name, display_name
    return None, DEV_USER_EMAIL, DEV_USER_NAME


def load_current_user():
    """Resolves (auto-provisioning if needed) the users row for this request."""
    oid, email, display_name = get_identity()
    if not email:
        return None

    with get_db() as db:
        user = None
        if oid:
            user = db.query_one("SELECT * FROM users WHERE entra_oid=?", (oid,))
        if not user:
            user = db.query_one("SELECT * FROM users WHERE email=?", (email,))
            if user and oid and not user.get('entra_oid'):
                db.execute("UPDATE users SET entra_oid=? WHERE id=?", (oid, user['id']))
                user['entra_oid'] = oid
        is_new = not user
        if is_new:
            new_id = str(uuid.uuid4())
            db.execute(
                "INSERT INTO users (id, entra_oid, email, display_name) VALUES (?,?,?,?)",
                (new_id, oid, email, display_name)
            )
            user = db.query_one("SELECT * FROM users WHERE id=?", (new_id,))

    if is_new:
        seed_user_catalog(user['id'])  # own connection — outside the `with` above
    return user
