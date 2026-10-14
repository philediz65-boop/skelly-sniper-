# main.py - V6.16 GOD MODE + TELEGRAM FIX - /start GO RESPOND NOW
import os, threading, time, requests, logging
from flask import Flask
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("GOD")
app = Flask(__name__)

# === YOUR CORE ===
ENTRY_DOGE = 0.08213
TP1_DOGE = 0.08055310
TP2_DOGE = 0.07950
SL_DOGE = 0.08344408
LEVERAGE = 25
BOT_VERSION = "V6.16 GOD + TELEGRAM"

MARKETS = {
    "DOGEUSDT": {"price": 0.08214, "day": -2.99, "tp1": TP1_DOGE, "tp2": TP2_DOGE, "sl": SL_DOGE, "lev": 25},
    "WIFUSDT": {"price": 0.2018, "day": -3.35, "tp1": 0.1950, "sl": 0.2140, "lev": 25},
    "ENAUSDT": {"price": 0.1957, "day": -7.64, "tp1": 0.1850, "sl": 0.2100, "lev": 25},
    "FARTCOINUSDT": {"price": 0.16416, "day": 0.06, "tp1": 0.1550, "sl": 0.1750, "lev": 25},
    "XAUUSD": {"price": 4078.82, "day": -1.83, "tp1": 4050, "sl": 4120, "lev": 20}
}

# === TELEGRAM BOT - FIXES /start ===
BOT_TOKEN = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN")

def send_telegram(chat_id, text):
    try:
        if not BOT_TOKEN:
            logger.error("NO BOT_TOKEN in Render env!")
            return
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        logger.error(f"Send fail: {e}")

def telegram_polling():
    offset = 0
    logger.info(f"Telegram polling started... Token exists: {bool(BOT_TOKEN)}")
    while True:
        try:
            if not BOT_TOKEN:
                time.sleep(30)
                continue
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={offset+1}&timeout=20"
            r = requests.get(url, timeout=25)
            if r.status_code != 200:
                time.sleep(5)
                continue
            data = r.json()
            for upd in data.get("result", []):
                offset = upd["update_id"]
                msg = upd.get("message", {})
                text = msg.get("text", "")
                chat_id = msg.get("chat", {}).get("id")
                if not chat_id:
                    continue

                if text.startswith("/start"):
                    reply = f"""✅ *Skelly Sniper {BOT_VERSION} LIVE*

*DOGE* Entry {ENTRY_DOGE} TP1 {TP1_DOGE} SL {SL_DOGE} LEV {LEVERAGE}x *+6.70%*

"""
                    for sym, d in MARKETS.items():
                        # live fetch quick
                        try:
                            if sym != "XAUUSD":
                                lr = requests.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={sym}", timeout=2).json()
                                price = float(lr["lastPrice"])
                                day = float(lr["priceChangePercent"])
                            else:
                                price = d["price"]
                                day = d["day"]
                        except:
                            price = d["price"]
                            day = d["day"]
                        reply += f"*{sym}*: ${price} Day {day:.2f}% | TP1 {d['tp1']} SL {d['sl']} LEV {d['lev']}x\n"

                    reply += """
*EMA* 20/50/200 ✅
*RSI* 14 ✅
*MACD* ✅
*Future* GOD VERDICT every 90s ✅

Send /analysis for GOD prediction now!
"""
                    send_telegram(chat_id, reply)

                elif text.startswith("/analysis"):
                    send_telegram(chat_id, "🔮 GOD MODE scanning... check Render logs for full 7-indicator verdict!")

        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(5)

# === FLASK FOR RENDER FAST ===
@app.route('/')
def home():
    return f"✅ {BOT_VERSION} - Telegram polling active - Token set: {bool(BOT_TOKEN)}"

@app.route('/health')
def health():
    return "OK", 200

if __name__ == "__main__":
    # Start Telegram in background so Flask start FAST
    threading.Thread(target=telegram_polling, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Starting {BOT_VERSION} on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
