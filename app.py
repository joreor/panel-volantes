"""
Panel de seguimiento de repartidores (volantes) - compatible con OwnTracks HTTP mode.

Recibe los POST que envia la app movil OwnTracks a /pub y los guarda en SQLite.
Expone un panel web con mapa en vivo, rutas del dia y gestion de repartidores.
"""

import json
import math
import os
import secrets
import sqlite3
import time
import unicodedata
from datetime import datetime, timedelta, timezone

from flask import Flask, Response, g, jsonify, render_template, request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "panel.db")

TZ_OFFSET = float(os.environ.get("TZ_OFFSET", "-5"))   # America/Bogota
ONLINE_SECONDS = int(os.environ.get("ONLINE_SECONDS", "600"))
PANEL_PASSWORD = os.environ.get("PANEL_PASSWORD", "")

COLORS = [
    "#2563eb", "#16a34a", "#ea580c", "#9333ea", "#0891b2",
    "#dc2626", "#65a30d", "#c026d3", "#ca8a04", "#4f46e5",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS reps (
    username   TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    phone      TEXT,
    color      TEXT,
    token      TEXT,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS positions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT NOT NULL,
    device      TEXT,
    lat         REAL NOT NULL,
    lon         REAL NOT NULL,
    acc         REAL,
    batt        INTEGER,
    vel         REAL,
    alt         REAL,
    conn        TEXT,
    tid         TEXT,
    tst         INTEGER NOT NULL,
    received_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pos_user_tst ON positions(username, tst);
CREATE INDEX IF NOT EXISTS idx_pos_tst ON positions(tst);
"""

app = Flask(__name__)


# --------------------------------------------------------------------------
# Base de datos
# --------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.executescript(SCHEMA)
    con.commit()
    con.close()


def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = "".join(c for c in text.lower() if c.isalnum())
    return text[:20] or "rep"


def pick_color(username):
    total = sum(ord(c) for c in username)
    return COLORS[total % len(COLORS)]


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------

def haversine(a, b):
    """Distancia en metros entre dos (lat, lon)."""
    r = 6371000.0
    lat1, lon1 = a
    lat2, lon2 = b
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def now_ts():
    return int(time.time())


def today_local():
    return (datetime.now(timezone.utc) + timedelta(hours=TZ_OFFSET)).strftime("%Y-%m-%d")


def day_bounds(day):
    dt = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    start = int(dt.timestamp() - TZ_OFFSET * 3600)
    return start, start + 86400


@app.before_request
def require_auth():
    if not PANEL_PASSWORD:
        return None
    if request.path.startswith("/pub"):
        return None
    if request.path == "/health":
        return None
    auth = request.authorization
    if auth and auth.username == "admin" and auth.password == PANEL_PASSWORD:
        return None
    return Response(
        "Acceso restringido", 401, {"WWW-Authenticate": 'Basic realm="Panel volantes"'}
    )


# --------------------------------------------------------------------------
# Recepcion de ubicaciones (endpoint que usa la app OwnTracks)
# --------------------------------------------------------------------------

@app.post("/pub")
@app.post("/pub/")
@app.post("/pub/<token>")
def publish(token=None):
    raw = request.get_data(cache=False, as_text=True)
    if not raw or not raw.strip():
        return jsonify({"ok": True, "ignored": "payload vacio"})

    try:
        data = json.loads(raw)
    except ValueError:
        return jsonify({"ok": False, "error": "json invalido"}), 400

    if not isinstance(data, dict):
        return jsonify({"ok": True, "ignored": "no es objeto"})

    if data.get("_type") != "location":
        # lwt, cmd, card, transition, etc.
        return jsonify([])

    try:
        lat = float(data["lat"])
        lon = float(data["lon"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"ok": False, "error": "falta lat/lon"}), 400

    db = get_db()

    username = (
        request.args.get("u")
        or request.headers.get("X-Limit-U")
        or data.get("username")
    )
    device = (
        request.args.get("d")
        or request.headers.get("X-Limit-D")
        or data.get("device")
        or data.get("tid")
        or "phone"
    )

    if token:
        row = db.execute("SELECT username FROM reps WHERE token = ?", (token,)).fetchone()
        if row:
            username = row["username"]

    if not username:
        username = "sin-identificar"

    username = str(username)[:40]
    device = str(device)[:40]

    # Registrar automaticamente al repartidor la primera vez que envia
    rep = db.execute("SELECT username FROM reps WHERE username = ?", (username,)).fetchone()
    if rep is None:
        db.execute(
            "INSERT INTO reps (username, name, phone, color, token, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (username, username, None, pick_color(username), secrets.token_urlsafe(8), now_ts()),
        )

    db.execute(
        "INSERT INTO positions"
        " (username, device, lat, lon, acc, batt, vel, alt, conn, tid, tst, received_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            username,
            device,
            lat,
            lon,
            data.get("acc"),
            data.get("batt"),
            data.get("vel"),
            data.get("alt"),
            data.get("conn"),
            data.get("tid"),
            int(data.get("tst") or now_ts()),
            now_ts(),
        ),
    )
    db.commit()

    return jsonify([{"_type": "card", "tid": data.get("tid", "")}])


@app.get("/health")
def health():
    return jsonify({"ok": True})


# --------------------------------------------------------------------------
# API del panel
# --------------------------------------------------------------------------

@app.get("/api/state")
def api_state():
    day = request.args.get("date") or today_local()
    try:
        start, end = day_bounds(day)
    except ValueError:
        return jsonify({"error": "fecha invalida, use YYYY-MM-DD"}), 400

    db = get_db()
    reps = [dict(r) for r in db.execute("SELECT * FROM reps ORDER BY name")]

    tracks = {}
    stats = {}
    rows = db.execute(
        "SELECT username, lat, lon, acc, tst FROM positions"
        " WHERE tst >= ? AND tst < ? ORDER BY tst",
        (start, end),
    ).fetchall()
    for row in rows:
        tracks.setdefault(row["username"], []).append([row["lat"], row["lon"]])
        st = stats.setdefault(row["username"], {"km": 0.0, "points": 0, "_prev": None})
        st["points"] += 1
        if row["acc"] is not None and row["acc"] > 150:
            continue
        cur = (row["lat"], row["lon"])
        prev = st["_prev"]
        if prev is not None:
            d = haversine(prev, cur)
            if d < 2000:  # descartar saltos irreales
                st["km"] += d
        st["_prev"] = cur

    lasts = {}
    last_rows = db.execute(
        "SELECT p.username, p.lat, p.lon, p.acc, p.batt, p.vel, p.conn, p.tst"
        " FROM positions p"
        " JOIN (SELECT username, MAX(tst) AS m FROM positions GROUP BY username) x"
        "   ON p.username = x.username AND p.tst = x.m"
        " GROUP BY p.username"
    ).fetchall()
    for row in last_rows:
        lasts[row["username"]] = {
            "lat": row["lat"],
            "lon": row["lon"],
            "acc": row["acc"],
            "batt": row["batt"],
            "vel": row["vel"],
            "conn": row["conn"],
            "tst": row["tst"],
        }

    server_ts = now_ts()
    payload = []
    for rep in reps:
        st = stats.get(rep["username"], {"km": 0.0, "points": 0})
        last = lasts.get(rep["username"])
        payload.append(
            {
                "username": rep["username"],
                "name": rep["name"],
                "phone": rep["phone"],
                "color": rep["color"] or pick_color(rep["username"]),
                "last": last,
                "online": bool(last and server_ts - last["tst"] <= ONLINE_SECONDS),
                "km": round(st["km"] / 1000.0, 2),
                "points": st["points"],
            }
        )

    return jsonify(
        {
            "day": day,
            "today": today_local(),
            "now": server_ts,
            "online_seconds": ONLINE_SECONDS,
            "host": request.host,
            "reps": payload,
            "tracks": tracks,
        }
    )


@app.post("/api/reps")
def api_add_rep():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "el nombre es obligatorio"}), 400

    db = get_db()
    base = slugify(name)
    username = base
    n = 1
    while db.execute("SELECT 1 FROM reps WHERE username = ?", (username,)).fetchone():
        n += 1
        username = f"{base}{n}"

    token = secrets.token_urlsafe(8)
    db.execute(
        "INSERT INTO reps (username, name, phone, color, token, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (username, name, (data.get("phone") or "").strip() or None, pick_color(username), token, now_ts()),
    )
    db.commit()

    return jsonify(
        {
            "username": username,
            "name": name,
            "token": token,
            "color": pick_color(username),
            "host": request.host,
        }
    ), 201


@app.delete("/api/reps/<username>")
def api_del_rep(username):
    db = get_db()
    db.execute("DELETE FROM reps WHERE username = ?", (username,))
    db.execute("DELETE FROM positions WHERE username = ?", (username,))
    db.commit()
    return jsonify({"ok": True})


@app.get("/api/history")
def api_history():
    username = request.args.get("username")
    day = request.args.get("date") or today_local()
    if not username:
        return jsonify({"error": "falta username"}), 400
    start, end = day_bounds(day)
    db = get_db()
    rows = db.execute(
        "SELECT lat, lon, tst, acc, vel FROM positions"
        " WHERE username = ? AND tst >= ? AND tst < ? ORDER BY tst",
        (username, start, end),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
else:
    init_db()
