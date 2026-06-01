from flask import Flask, request, jsonify
import requests
import json
import os
from datetime import datetime
import pytz

app = Flask(__name__)

# ── Telegram config ──────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8942691723:AAEzwjFcYyxwwmcKeVwcfTjooPJlBgdLpZU")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "916243970")

# ── Signal log file ──────────────────────────────────────────────
LOG_FILE = "signals.json"

def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

def log_signal(data: dict):
    signals = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, "r") as f:
                signals = json.load(f)
        except:
            signals = []
    signals.append(data)
    with open(LOG_FILE, "w") as f:
        json.dump(signals, f, indent=2)

def format_message(data: dict) -> str:
    action = data.get("action", "").upper()
    symbol = data.get("symbol", "")
    entry  = data.get("entry", "")
    sl     = data.get("sl", "")
    tp     = data.get("tp", "")
    tf     = data.get("timeframe", "1M")

    cst = pytz.timezone("America/Chicago")
    now = datetime.now(cst).strftime("%I:%M %p CST")

    emoji  = "🟢" if action == "BUY" else "🔴"
    action_label = "COMPRA" if action == "BUY" else "VENTA"

    # TP ratio label
    ratio = "1:2" if "NQ" in symbol.upper() else "1:1"

    lines = [
        f"{emoji} <b>{action_label} — {symbol}</b>",
        f"",
        f"💰 Entry:  <code>{entry}</code>",
        f"🛑 SL:     <code>{sl}</code>",
        f"🎯 TP:     <code>{tp}</code>  ({ratio})",
        f"⏱ TF:     {tf}",
        f"🕐 Hora:   {now}",
    ]
    return "\n".join(lines)

# ── Webhook endpoint ─────────────────────────────────────────────
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "No JSON received"}), 400

        print(f"[SIGNAL] {json.dumps(data)}")

        # Add timestamp
        cst = pytz.timezone("America/Chicago")
        data["timestamp"] = datetime.now(cst).isoformat()

        # Log signal
        log_signal(data)

        # Send Telegram
        message = format_message(data)
        ok = send_telegram(message)

        return jsonify({"ok": ok, "received": data}), 200

    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({"error": str(e)}), 500

# ── Signals history endpoint ─────────────────────────────────────
@app.route("/signals", methods=["GET"])
def get_signals():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            return jsonify(json.load(f))
    return jsonify([])

# ── Health check ─────────────────────────────────────────────────
@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "online", "service": "Julio Trading Alerts"})

# ── Dashboard ────────────────────────────────────────────────────
@app.route("/dashboard", methods=["GET"])
def dashboard():
    with open("dashboard.html", "r") as f:
        return f.read(), 200, {"Content-Type": "text/html"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
