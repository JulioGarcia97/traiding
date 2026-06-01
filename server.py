from flask import Flask, request, jsonify, Response
import requests
import json
import os
from datetime import datetime, timedelta
import pytz
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

# ── Weekly scheduler ─────────────────────────────────────────────
def scheduled_weekly_report():
    with app.test_request_context():
        weekly_report()

scheduler = BackgroundScheduler(timezone="America/Chicago")
scheduler.add_job(scheduled_weekly_report, "cron", day_of_week="sun", hour=18, minute=0)
scheduler.start()

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN",   "8942691723:AAEzwjFcYyxwwmcKeVwcfTjooPJlBgdLpZU")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "916243970")
BASE_URL         = os.environ.get("BASE_URL", "https://web-production-085bf.up.railway.app")
TRADES_FILE      = "/data/trades.json"
STATE_FILE       = "/data/bot_state.json"

# ── Persistence ──────────────────────────────────────────────────

def load_trades():
    if os.path.exists(TRADES_FILE):
        try:
            with open(TRADES_FILE) as f:
                return json.load(f)
        except:
            pass
    return []

def save_trades(trades):
    with open(TRADES_FILE, "w") as f:
        json.dump(trades, f, indent=2)

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except:
            pass
    return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def is_nq(symbol: str) -> bool:
    """Detect NQ regardless of how TV sends the ticker."""
    s = symbol.upper()
    return any(x in s for x in ["NQ", "USTEC", "MNQ", "NAS100", "US100", "NASDAQ"])

# ── Telegram helpers ─────────────────────────────────────────────

def tg_post(method, payload):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.json()
    except Exception as e:
        print(f"[TG ERROR] {e}")
        return {}

def send_message(text, reply_markup=None):
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return tg_post("sendMessage", payload)

def edit_message(chat_id, message_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return tg_post("editMessageText", payload)

def answer_callback(callback_id, text=""):
    tg_post("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

def register_webhook():
    webhook_url = f"{BASE_URL}/telegram"
    tg_post("setWebhook", {"url": webhook_url})
    print(f"[TG] Webhook registered: {webhook_url}")

# ── Signal message with inline buttons ──────────────────────────

def send_signal_message(trade: dict):
    action = trade.get("action", "").upper()
    symbol = trade.get("symbol", "")
    entry  = trade.get("entry", "—")
    cst    = pytz.timezone("America/Chicago")
    now    = datetime.now(cst).strftime("%I:%M %p CST")
    emoji  = "🟢" if action == "BUY" else "🔴"
    label  = "COMPRA" if action == "BUY" else "VENTA"
    ratio  = "1:2" if is_nq(symbol) else "1:1"
    tid    = trade["id"]

    text = "\n".join([
        f"{emoji} <b>{label} — {symbol}</b>",
        f"",
        f"💰 Entry:  <code>{entry}</code>",
        f"⚖️ Ratio:  {ratio}",
        f"⏱ TF:     1M",
        f"🕐 Hora:   {now}",
        f"",
        f"📋 Responde con SL y TP:",
        f"<code>sl 21480 tp 21660</code>",
    ])

    markup = {
        "inline_keyboard": [[
            {"text": "✅ TP alcanzado", "callback_data": f"result:{tid}:win"},
            {"text": "❌ SL alcanzado", "callback_data": f"result:{tid}:loss"},
        ],[
            {"text": "⏭ No tomado",    "callback_data": f"result:{tid}:skip"},
        ]]
    }

    result = send_message(text, markup)
    # save message_id so we can edit it later
    msg_id = result.get("result", {}).get("message_id")
    if msg_id:
        state = load_state()
        state[str(tid)] = {"message_id": msg_id, "awaiting": "result"}
        save_state(state)

# ── Handle Telegram updates (bot responses) ──────────────────────

def handle_update(update: dict):
    # ── Callback query (button press) ──
    if "callback_query" in update:
        cq     = update["callback_query"]
        cq_id  = cq["id"]
        data   = cq.get("data", "")
        chat_id   = cq["message"]["chat"]["id"]
        msg_id    = cq["message"]["message_id"]

        if data.startswith("result:"):
            _, tid, result = data.split(":")
            trades = load_trades()
            labels = {"win": "✅ TP alcanzado", "loss": "❌ SL alcanzado", "skip": "⏭ No tomado"}
            for t in trades:
                if str(t["id"]) == tid:
                    t["result"] = result
                    save_trades(trades)
                    answer_callback(cq_id, labels.get(result, ""))

                    action = t.get("action","").upper()
                    symbol = t.get("symbol","")
                    entry  = t.get("entry","—")
                    sl     = t.get("sl","—") or "—"
                    tp     = t.get("tp","—") or "—"
                    emoji  = "🟢" if action=="BUY" else "🔴"

                    new_text = "\n".join([
                        f"{emoji} <b>{action} — {symbol}</b>  {labels[result]}",
                        f"",
                        f"💰 Entry: <code>{entry}</code>",
                        f"🛑 SL:    <code>{sl}</code>",
                        f"🎯 TP:    <code>{tp}</code>",
                    ])
                    edit_message(chat_id, msg_id, new_text)

                    # clean state
                    state = load_state()
                    state.pop(tid, None)
                    save_state(state)
                    return

            answer_callback(cq_id, "Trade no encontrado")
        return

    # ── Text message (SL/TP capture) ──
    if "message" in update:
        msg  = update["message"]
        text = msg.get("text", "").strip().lower()

        # parse: "sl 21480 tp 21660" or "sl <21480> tp <21660>"
        if "sl" in text and "tp" in text:
            try:
                # strip angle brackets and any extra chars, keep only digits and dots
                clean = text.replace("<","").replace(">","").replace(",",".")
                parts = clean.replace("sl", "").replace("tp", " ").split()
                parts = [p.strip() for p in parts if p.strip()]
                sl_val = parts[0]
                tp_val = parts[1]

                # validate they are numbers
                float(sl_val)
                float(tp_val)

                # find most recent pending trade
                trades = load_trades()
                for t in trades:
                    if t["result"] == "pending" and (not t.get("sl") or not t.get("tp")):
                        t["sl"] = sl_val
                        t["tp"] = tp_val
                        save_trades(trades)
                        send_message(f"✔️ SL <code>{sl_val}</code> y TP <code>{tp_val}</code> guardados para {t['symbol']} {t['action']}.\n\nAhora toca el botón de resultado.")
                        return

                send_message("No encontré un trade pendiente sin SL/TP. Verifica el journal.")
            except (IndexError, ValueError):
                send_message("Formato incorrecto. Usa:\n<code>sl 21480 tp 21660</code>")

# ── Routes ───────────────────────────────────────────────────────

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        if not data:
            return jsonify({"error": "no json"}), 400

        cst = pytz.timezone("America/Chicago")
        trade = {
            "id":     int(datetime.now().timestamp() * 1000),
            "ts":     datetime.now(cst).isoformat(),
            "symbol": data.get("symbol", ""),
            "action": data.get("action", "").upper(),
            "entry":  data.get("entry", ""),
            "sl":     "",
            "tp":     "",
            "result": "pending",
            "notes":  ""
        }

        trades = load_trades()
        trades.insert(0, trade)
        save_trades(trades)

        send_signal_message(trade)
        return jsonify({"ok": True, "id": trade["id"]}), 200

    except Exception as e:
        print(f"[ERROR] {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/telegram", methods=["POST"])
def telegram_update():
    try:
        update = request.get_json(force=True)
        if update:
            handle_update(update)
        return jsonify({"ok": True}), 200
    except Exception as e:
        print(f"[TG UPDATE ERROR] {e}")
        return jsonify({"error": str(e)}), 500

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
            "id":     int(datetime.now().timestamp() * 1000),
            "ts":     body.get("ts", datetime.now(cst).isoformat()),
            "symbol": body.get("symbol", ""),
            "action": body.get("action", "").upper(),
            "entry":  body.get("entry", ""),
            "sl":     body.get("sl", ""),
            "tp":     body.get("tp", ""),
            "result": body.get("result", "pending"),
            "notes":  body.get("notes", "")
        }
        trades = load_trades()
        trades.insert(0, trade)
        save_trades(trades)
        return jsonify({"ok": True, "trade": trade}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Weekly report ────────────────────────────────────────────────

@app.route("/report/weekly", methods=["GET"])
def weekly_report():
    try:
        cst    = pytz.timezone("America/Chicago")
        now    = datetime.now(cst)
        week_ago = now - timedelta(days=7)
        trades = load_trades()

        week_trades = [t for t in trades if datetime.fromisoformat(t["ts"]) >= week_ago]
        done   = [t for t in week_trades if t["result"] in ("win","loss")]
        wins   = [t for t in done if t["result"] == "win"]
        losses = [t for t in done if t["result"] == "loss"]
        wr     = round(len(wins)/len(done)*100) if done else 0

        nq_done   = [t for t in done if is_nq(t.get("symbol",""))]
        gold_done = [t for t in done if "XAU" in t.get("symbol","") or "GC" in t.get("symbol","")]
        nq_wr     = round(len([t for t in nq_done   if t["result"]=="win"])/len(nq_done)*100)   if nq_done   else 0
        gold_wr   = round(len([t for t in gold_done if t["result"]=="win"])/len(gold_done)*100) if gold_done else 0

        # best hour
        hour_wins = {}
        for t in done:
            h = datetime.fromisoformat(t["ts"]).hour
            if h not in hour_wins:
                hour_wins[h] = {"w":0,"n":0}
            hour_wins[h]["n"] += 1
            if t["result"] == "win":
                hour_wins[h]["w"] += 1
        best_hour = max(hour_wins, key=lambda h: hour_wins[h]["w"]/hour_wins[h]["n"] if hour_wins[h]["n"]>=2 else 0) if hour_wins else None
        best_hour_str = f"{best_hour}:00–{best_hour+1}:00 CST" if best_hour is not None else "—"

        week_str = now.strftime("%d %b %Y")
        text = "\n".join([
            f"📊 <b>Reporte Semanal — {week_str}</b>",
            f"",
            f"📈 Señales totales:  <b>{len(week_trades)}</b>",
            f"✅ Ganados:          <b>{len(wins)}</b>",
            f"❌ Perdidos:         <b>{len(losses)}</b>",
            f"🎯 Win rate:         <b>{wr}%</b>",
            f"",
            f"⚡ NQ win rate:      <b>{nq_wr}%</b>  ({len(nq_done)} trades)",
            f"🥇 Gold win rate:    <b>{gold_wr}%</b>  ({len(gold_done)} trades)",
            f"",
            f"⏰ Mejor hora:       <b>{best_hour_str}</b>",
            f"",
            f"<a href='{BASE_URL}/journal'>Ver journal completo</a>",
        ])

        send_message(text)
        return jsonify({"ok": True, "sent": True}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/journal", methods=["GET"])
def journal():
    with open("journal.html") as f:
        return Response(f.read(), mimetype="text/html")

@app.route("/", methods=["GET"])
def health():
    register_webhook()
    return jsonify({"status": "online", "service": "Julio Trading Alerts"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
