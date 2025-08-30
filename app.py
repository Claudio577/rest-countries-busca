from flask import Flask, jsonify, request, send_from_directory
import sqlite3, requests, os

APP_DIR = os.path.dirname(__file__)
DB_PATH = os.path.join(APP_DIR, "countries.db")

app = Flask(__name__, static_folder="public", static_url_path="")

# ----------------- Helpers de banco -----------------
def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    return con

def init_db():
    con = connect()
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS countries (
        id INTEGER PRIMARY KEY,
        name_common   TEXT,
        name_official TEXT,
        cca2 TEXT, cca3 TEXT, ccn3 TEXT,
        capital TEXT,
        region TEXT, subregion TEXT,
        population INTEGER,
        area REAL,
        lat REAL, lng REAL,
        languages TEXT,
        flag_png TEXT, flag_svg TEXT
    );
    """)
    cur.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS countries_fts
    USING fts5(
        name_common, name_official, capital, region, subregion, languages,
        content='countries', content_rowid='id'
    );
    """)
    # Triggers para manter o FTS sincronizado
    cur.executescript("""
    CREATE TRIGGER IF NOT EXISTS countries_ai AFTER INSERT ON countries BEGIN
      INSERT INTO countries_fts(rowid, name_common, name_official, capital, region, subregion, languages)
      VALUES (new.id, new.name_common, new.name_official, new.capital, new.region, new.subregion, new.languages);
    END;

    CREATE TRIGGER IF NOT EXISTS countries_au AFTER UPDATE ON countries BEGIN
      INSERT INTO countries_fts(countries_fts, rowid, name_common, name_official, capital, region, subregion, languages)
      VALUES('delete', old.id, old.name_common, old.name_official, old.capital, old.region, old.subregion, old.languages);
      INSERT INTO countries_fts(rowid, name_common, name_official, capital, region, subregion, languages)
      VALUES (new.id, new.name_common, new.name_official, new.capital, new.region, new.subregion, new.languages);
    END;

    CREATE TRIGGER IF NOT EXISTS countries_ad AFTER DELETE ON countries BEGIN
      INSERT INTO countries_fts(countries_fts, rowid, name_common, name_official, capital, region, subregion, languages)
      VALUES('delete', old.id, old.name_common, old.name_official, old.capital, old.region, old.subregion, old.languages);
    END;
    """)
    con.commit()
    con.close()

def db_empty():
    con = connect()
    n = con.execute("SELECT COUNT(*) FROM countries;").fetchone()[0]
    con.close()
    return n == 0

def fetch_and_load():
    url = "https://restcountries.com/v3.1/all?fields=name,cca2,cca3,ccn3,capital,region,subregion,population,area,latlng,languages,flags"
    data = requests.get(url, timeout=60).json()
    con = connect()
    cur = con.cursor()
    cur.execute("BEGIN;")
    for r in data:
        name_common   = r.get("name", {}).get("common", "")
        name_official = r.get("name", {}).get("official", "")
        cca2          = r.get("cca2", "")
        cca3          = r.get("cca3", "")
        ccn3          = r.get("ccn3", "")
        capital_list  = r.get("capital") or []
        capital       = capital_list[0] if capital_list else ""
        region        = r.get("region", "")
        subregion     = r.get("subregion", "")
        population    = int(r.get("population") or 0)
        area          = float(r.get("area") or 0.0)
        latlng        = r.get("latlng") or []
        lat = float(latlng[0]) if len(latlng) >= 1 else None
        lng = float(latlng[1]) if len(latlng) >= 2 else None
        languages_dict = r.get("languages") or {}
        languages     = ", ".join(sorted(languages_dict.values()))
        flags         = r.get("flags") or {}
        flag_png      = flags.get("png", "")
        flag_svg      = flags.get("svg", "")

        cur.execute("""
        INSERT INTO countries(
            name_common, name_official, cca2, cca3, ccn3, capital, region, subregion,
            population, area, lat, lng, languages, flag_png, flag_svg
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (name_common, name_official, cca2, cca3, ccn3, capital, region, subregion,
              population, area, lat, lng, languages, flag_png, flag_svg))
    con.commit()
    con.close()

def ensure_data():
    init_db()
    if db_empty():
        fetch_and_load()

# ----------------- API -----------------
@app.after_request
def no_cache(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp

@app.get("/")
def index():
    return send_from_directory("public", "index.html")

@app.get("/healthz")
def health():
    return jsonify({"status": "ok"})

def build_filters(args, use_fts):
    where = []
    params = []

    region    = args.get("region")
    subregion = args.get("subregion")
    lang      = args.get("lang")
    min_pop   = args.get("min_pop", type=int)
    max_pop   = args.get("max_pop", type=int)
    min_area  = args.get("min_area", type=float)
    max_area  = args.get("max_area", type=float)

    if region:
        where.append("c.region = ?"); params.append(region)
    if subregion:
        where.append("c.subregion = ?"); params.append(subregion)
    if lang:
        where.append("c.languages LIKE ?"); params.append(f"%{lang}%")
    if min_pop is not None:
        where.append("c.population >= ?"); params.append(min_pop)
    if max_pop is not None:
        where.append("c.population <= ?"); params.append(max_pop)
    if min_area is not None:
        where.append("c.area >= ?"); params.append(min_area)
    if max_area is not None:
        where.append("c.area <= ?"); params.append(max_area)

    from_clause = "FROM countries c JOIN countries_fts f ON f.rowid = c.id" if use_fts else "FROM countries c"
    return from_clause, where, params

@app.get("/countries")
def countries():
    """
    Lista/pesquisa países.
    Params:
      q           -> texto livre (FTS: nome/capital/região/idiomas)
      region      -> ex.: 'Americas'
      subregion   -> ex.: 'South America'
      lang        -> ex.: 'Portuguese'
      min_pop/max_pop, min_area/max_area
      sort        -> name|population|area (default name)
      order       -> asc|desc (default asc)
      limit/offset (default 25/0; máx 100)
    """
    q = request.args.get("q", "").strip()
    use_fts = bool(q)

    sort = request.args.get("sort", "name")
    order = request.args.get("order", "asc")
    sort_map = {"name": "c.name_common", "population": "c.population", "area": "c.area"}
    sort_col = sort_map.get(sort, "c.name_common")
    order_sql = "DESC" if order.lower() == "desc" else "ASC"

    limit = min(max(request.args.get("limit", default=25, type=int), 1), 100)
    offset = max(request.args.get("offset", default=0, type=int), 0)

    from_clause, where, params = build_filters(request.args, use_fts)

    if use_fts:
        q_token = q.replace('"', "").replace("'", "").strip()
        if q_token and not any(ch in q_token for ch in ('*', '"', ' ')):
            q_token = q_token + "*"
        where.insert(0, "countries_fts MATCH ?")
        params.insert(0, q_token)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sql_base = f"SELECT c.* {from_clause} {where_sql}"

    con = connect()
    total = con.execute(f"SELECT COUNT(*) FROM ({sql_base})", params).fetchone()[0]
    sql = f"{sql_base} ORDER BY {sort_col} {order_sql} LIMIT ? OFFSET ?"
    rows = con.execute(sql, (*params, limit, offset)).fetchall()
    con.close()

    items = [dict(r) for r in rows]
    return jsonify({"total": total, "limit": limit, "offset": offset, "items": items})

if __name__ == "__main__":
    ensure_data()
    app.run(host="127.0.0.1", port=5000, debug=True)
