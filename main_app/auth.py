"""
Auth helpers — login_required / admin_required decorators, CSRF token, login/signup logic.
"""

import secrets
from functools import wraps
from flask import session, redirect, url_for, request, abort

import db


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return db.get_user_by_id(uid)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user or user["status"] != "active":
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user or user["status"] != "active":
            return redirect(url_for("login", next=request.path))
        if user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def get_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(16)
    return session["csrf_token"]


def validate_csrf(form_token):
    return form_token and session.get("csrf_token") and secrets.compare_digest(form_token, session["csrf_token"])
