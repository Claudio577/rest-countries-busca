from flask import Flask, jsonify, send_from_directory
import os

APP_DIR = os.path.dirname(__file__)
app = Flask(__name__, static_folder="public", static_url_path="")

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

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
