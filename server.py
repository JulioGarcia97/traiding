from flask import Flask, request, jsonify, Response
import requests
import json
import os
from datetime import datetime
import pytz

app = Flask(__name__)

TELEGRAM_TOKEN  = os.environ.get("TELEGRAM_TOKEN",  "8942691723:AAEzwjFcYyxwwmcKeVwcfTjooPJlBgdLpZU")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "916243970")
TRADES_FILE = "trades.json"

# ── Helpers ──────────────────────────────────────────────────────

def load_trades():
    if os.path.exists(TRADES_FILE):
        try:
            with open(TRADES_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return []

def save_trades(trades):
    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=2)

def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

def format_message(trade: dict) -> str:
    action = trade.get("action", "").upper()
    symbol = trade.get("symbol", "")
    entry  = trade.get("entry", "—")
    cst    = pytz.timezone("America/Chicago")
    now    = datetime.now(cst).strftime("%I:%M %p CST")
    emoji  = "🟢" if action == "BUY" else "🔴"
    label  = "COMPRA" if action == "BUY" else "VENTA"
    ratio  = "1:2" if "NQ" in symbol.upper() else "1:1"
    tid    = trade.get("id", "")
    journal_url = f"https://web-production-085bf.up.railway.app/journal"
    return "\n".join([
        f"{emoji} <b>{label} — {symbol}</b>",
        f"",
        f"💰 Entry:  <code>{entry}</code>",
        f"⚖️ Ratio:  {ratio}",
        f"⏱ TF:     1M",
        f"🕐 Hora:   {now}",
        f"",
        f"📋 <a href='{journal_url}'>Registrar SL / TP / Resultado</a>",
    ])

# ── Webhook — recibe señal de TradingView ────────────────────────

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "no json"}), 400

        cst = pytz.timezone("America/Chicago")
        trade = {
            "id":        int(datetime.now().timestamp() * 1000),
            "ts":        datetime.now(cst).isoformat(),
            "symbol":    data.get("symbol", ""),
            "action":    data.get("action", "").upper(),
            "entry":     data.get("entry", ""),
            "sl":        "",
            "tp":        "",
            "result":    "pending",
            "notes":     ""
        }

        trades = load_trades()
        trades.insert(0, trade)
        save_trades(trades)

        send_telegram(format_message(trade))
        return jsonify({"ok": True, "id": trade["id"]}), 200

    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({"error": str(e)}), 500

# ── API trades ───────────────────────────────────────────────────

@app.route("/trades", methods=["GET"])
def get_trades():
    return jsonify(load_trades())

@app.route("/trades/<int:trade_id>", methods=["PATCH"])
def update_trade(trade_id):
    try:
        trades = load_trades()
        body   = request.get_json(force=True) or {}
        for t in trades:
            if t["id"] == trade_id:
                for field in ["sl", "tp", "result", "notes"]:
                    if field in body:
                        t[field] = body[field]
                save_trades(trades)
                return jsonify({"ok": True, "trade": t})
        return jsonify({"error": "not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/trades/<int:trade_id>", methods=["DELETE"])
def delete_trade(trade_id):
    trades = load_trades()
    trades = [t for t in trades if t["id"] != trade_id]
    save_trades(trades)
    return jsonify({"ok": True})

@app.route("/trades", methods=["POST"])
def add_trade():
    try:
        body = request.get_json(force=True) or {}
        cst  = pytz.timezone("America/Chicago")
        trade = {
            "id":       int(datetime.now().timestamp() * 1000),
            "ts":       body.get("ts", datetime.now(cst).isoformat()),
            "symbol":   body.get("symbol", ""),
            "action":   body.get("action", "").upper(),
            "entry":    body.get("entry", ""),
            "sl":       body.get("sl", ""),
            "tp":       body.get("tp", ""),
            "result":   body.get("result", "pending"),
            "notes":    body.get("notes", "")
        }
        trades = load_trades()
        trades.insert(0, trade)
        save_trades(trades)
        return jsonify({"ok": True, "trade": trade}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Journal UI ───────────────────────────────────────────────────

@app.route("/journal", methods=["GET"])
def journal():
    with open("journal.html", "r") as f:
        return Response(f.read(), mimetype="text/html")

# ── Health ───────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "online", "service": "Julio Trading Alerts"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
