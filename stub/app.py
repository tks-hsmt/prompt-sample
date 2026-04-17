import json
import logging
import sys
from flask import Flask, request, jsonify

# ── ロギング設定 ────────────────────────────────────────────
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("notifier-stub")

app = Flask(__name__)


# ── 共通ハンドラ ────────────────────────────────────────────
def handle(path: str):
    log_headers = {
        "Content-Type": request.headers.get("Content-Type", ""),
        "Authorization": request.headers.get("Authorization", ""),
    }
    try:
        body = request.get_json(force=True, silent=True) or {}
    except Exception:
        body = {}

    logger.info(
        "RECEIVED | path=%s | headers=%s | body=%s",
        path,
        json.dumps(log_headers, ensure_ascii=False),
        json.dumps(body, ensure_ascii=False),
    )
    return jsonify({"status": "accepted"}), 202


# ── エンドポイント ──────────────────────────────────────────
@app.post("/trap")
def trap():
    return handle("/trap")


@app.post("/syslog")
def syslog_ep():
    return handle("/syslog")


@app.post("/ipcrx")
def ipcrx():
    return handle("/ipcrx")


# ── 起動 ────────────────────────────────────────────────────
if __name__ == "__main__":
    logger.info("com-notifier stub starting on :8080")
    app.run(host="0.0.0.0", port=8080)
