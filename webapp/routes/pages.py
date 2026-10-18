"""The page itself and its static files."""
from __future__ import annotations

from flask import Blueprint, jsonify, send_from_directory

from webapp.common import STATIC
from webapp.version import VERSION

bp = Blueprint("pages", __name__)


@bp.route("/api/version")
def api_version():
    return jsonify({"version": VERSION})


@bp.route("/")
def index():
    return send_from_directory(STATIC, "editor.html")


@bp.route("/static/<path:name>")
def static_file(name):
    return send_from_directory(STATIC, name)
