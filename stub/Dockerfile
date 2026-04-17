# ============================================================
# com-notifier-stub Dockerfile
# Base: python:3.11-slim
# User: nobody (UID 65534) — PSS Restricted 準拠
# ============================================================

FROM python:3.11-slim

# ── 依存パッケージをインストール ────────────────────────────
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

# ── アプリを配置 ────────────────────────────────────────────
WORKDIR /app
COPY app.py /app/app.py

# ── non-root で実行（UID 65534 = nobody）───────────────────
USER 65534

EXPOSE 8080

CMD ["python", "app.py"]
