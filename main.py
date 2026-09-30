import os
import re
import math
import threading
import time
from typing import Optional, List, Dict, Tuple

import requests
from flask import Flask
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ============================================================
# PHILEDIZ V2 - NEW CLEAN BUILD
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "10000"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set")

app = Flask(__name__)

# Supported Bybit USDT perpetual symbols
CRYPTO = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "BNB": "BNBUSDT",
    "SOL": "SOLUSDT",
    "XRP": "XRPUSDT",
    "DOGE": "DOGEUSDT",
    "ADA": "ADAUSDT",
    "AVAX": "AVAXUSDT",
    "LINK": "LINKUSDT",
    "TRX": "TRXUSDT",
}

BYBIT_BASES = [
    "https://api.bybit.com",
    "https://api.bytick.com",
]

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "PHILEDIZ-V2/1.0",
    "Accept": "application/json",
})

# ============================================================
# WEB SERVER
# ============================================================

@app.get("/")
def home():
    return "PHILEDIZ V2 is online", 200


@app.get("/health")
def health():
    return {"status": "ok", "bot": "PHILEDIZ V2"}, 200


# ============================================================
# HELPERS
# ============================================================

def clean_symbol(text: str) -> str:
    text = text.upper().strip()
    text = text.replace("/", "").replace("-", "").replace("_", "")
    text = re.sub(r"[^A-Z0-9]", "", text)

    aliases = {
        "BITCOIN": "BTC",
        "ETHEREUM": "ETH",
        "BINANCECOIN": "BNB",
        "SOLANA": "SOL",
        "RIPPLE": "XRP",
        "DOGECOIN": "DOGE",
        "CARDANO": "ADA",
        "AVALANCHE": "AVAX",
        "CHAINLINK": "LINK",
        "TRON": "TRX",
    }

    if text in aliases:
        text = aliases[text]

    if text.endswith("USDT") and text[:-4] in CRYPTO:
        return text[:-4]

    return text


def fmt_price(value: float) -> str:
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 100:
        return f"{value:,.3f}"
    if value >= 1:
        return f"{value:,.4f}"
    if value >= 0.01:
        return f"{value:,.5f}"
    return f"{value:,.8f}"


def bybit_get(path: str, params: dict) -> Optional[dict]:
    """
    Public Bybit request. No API key is required for these market-data
    endpoints. Every failure is printed so Render logs show the real cause.
    """
    last_error = None

    for base in BYBIT_BASES:
        url = base + path
        try:
            r = SESSION.get(url, params=params, timeout=(5, 15))

            print(
                f"BYBIT HTTP {r.status_code} "
                f"{path} params={params}"
            )

            if r.status_code != 200:
                print(f"BYBIT BODY: {r.text[:500]}")
                last_error = f"HTTP {r.status_code}"
                continue

            data = r.json()

            if data.get("retCode") != 0:
                print(
                    f"BYBIT API ERROR: "
                    f"retCode={data.get('retCode')} "
                    f"retMsg={data.get('retMsg')}"
                )
                last_error = (
                    f"{data.get('retCode')}: {data.get('retMsg')}"
                )
                continue

            return data

        except Exception as exc:
            last_error = repr(exc)
            print(f"BYBIT REQUEST FAILED: {url} -> {exc}")

    print(f"BYBIT ALL ENDPOINTS FAILED: {last_error}")
    return None


# ============================================================
# BYBIT MARKET DATA
# ============================================================

def get_bybit_klines(symbol: str, interval: str = "15", limit: int = 200):
    data = bybit_get(
        "/v5/market/kline",
        {
            "category": "linear",
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        },
    )

    if not data:
        return []

    rows = data.get("result", {}).get("list", [])

    candles = []

    for row in rows:
        try:
            candles.append({
                "time": int(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            })
        except (ValueError, TypeError, IndexError):
            continue

    # Bybit returns newest first. Analysis needs oldest first.
    candles.reverse()

    print(f"BYBIT KLINES OK: {symbol}, candles={len(candles)}")
    return candles


def get_bybit_price(symbol: str) -> Optional[float]:
    data = bybit_get(
        "/v5/market/tickers",
        {
            "category": "linear",
            "symbol": symbol,
        },
    )

    if not data:
        return None

    rows = data.get("result", {}).get("list", [])

    if not rows:
        print(f"BYBIT TICKER EMPTY: {symbol}")
        return None

    try:
        price = float(rows[0]["lastPrice"])
        print(f"BYBIT LIVE PRICE: {symbol} = {price}")
        return price
    except (KeyError, ValueError, TypeError):
        print(f"BYBIT TICKER PARSE ERROR: {rows[:1]}")
        return None


def get_real_leverage(symbol: str) -> Optional[float]:
    data = bybit_get(
        "/v5/market/instruments-info",
        {
            "category": "linear",
            "symbol": symbol,
        },
    )

    if not data:
        return None

    rows = data.get("result", {}).get("list", [])

    if not rows:
        print(f"BYBIT INSTRUMENT EMPTY: {symbol}")
        return None

    try:
        leverage = float(rows[0]["leverageFilter"]["maxLeverage"])
        print(f"BYBIT MAX LEVERAGE: {symbol} = {leverage}x")
        return leverage
    except (KeyError, ValueError, TypeError) as exc:
        print(f"BYBIT LEVERAGE PARSE ERROR: {exc}")
        return None


# ============================================================
# INDICATORS
# ============================================================

def ema(values: List[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None

    multiplier = 2.0 / (period + 1.0)
    result = sum(values[:period]) / period

    for price in values[period:]:
        result = (price - result) * multiplier + result

    return result


def ema_series(values: List[float], period: int) -> List[Optional[float]]:
    if len(values) < period:
        return [None] * len(values)

    result = [None] * len(values)
    current = sum(values[:period]) / period
    result[period - 1] = current

    multiplier = 2.0 / (period + 1.0)

    for i in range(period, len(values)):
        current = (values[i] - current) * multiplier + current
        result[i] = current

    return result


def rsi(values: List[float], period: int = 14) -> Optional[float]:
    if len(values) <= period:
        return None

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(candles: List[dict], period: int = 14) -> Optional[float]:
    if len(candles) <= period:
        return None

    trs = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous = candles[i - 1]

        tr = max(
            current["high"] - current["low"],
            abs(current["high"] - previous["close"]),
            abs(current["low"] - previous["close"]),
        )
        trs.append(tr)

    if len(trs) < period:
        return None

    value = sum(trs[:period]) / period

    for tr in trs[period:]:
        value = ((value * (period - 1)) + tr) / period

    return value


# ============================================================
# ANALYSIS
# ============================================================

def support_resistance(candles: List[dict], lookback: int = 50):
    sample = candles[-lookback:]
    support = min(c["low"] for c in sample)
    resistance = max(c["high"] for c in sample)
    return support, resistance


def analyze_crypto(symbol_code: str) -> Optional[dict]:
    symbol = CRYPTO.get(symbol_code)

    if not symbol:
        return None

    candles = get_bybit_klines(symbol, "15", 200)

    if len(candles) < 60:
        print(
            f"NOT ENOUGH BYBIT CANDLES: "
            f"{symbol}, received={len(candles)}"
        )
        return None

    closes = [c["close"] for c in candles]

    # Use Bybit ticker as the live price.
    live_price = get_bybit_price(symbol)

    # If ticker temporarily fails, use the newest candle close.
    # This is still real Bybit market data, not an invented value.
    if live_price is None:
        live_price = candles[-1]["close"]
        print(
            f"BYBIT TICKER UNAVAILABLE: "
            f"using latest Bybit candle close {live_price}"
        )

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    rsi14 = rsi(closes, 14)
    atr14 = atr(candles, 14)

    if None in (ema20, ema50, rsi14, atr14):
        print(f"INDICATOR CALCULATION FAILED: {symbol}")
        return None

    support, resistance = support_resistance(candles)

    # Recent momentum over the last 5 candles.
    momentum_pct = (
        (closes[-1] - closes[-6]) / closes[-6] * 100
        if len(closes) >= 6 and closes[-6] != 0
        else 0.0
    )

    score = 0

    if live_price > ema20:
        score += 1
    else:
        score -= 1

    if ema20 > ema50:
        score += 1
    else:
        score -= 1

    if rsi14 >= 55:
        score += 1
    elif rsi14 <= 45:
        score -= 1

    if momentum_pct > 0:
        score += 1
    elif momentum_pct < 0:
        score -= 1

    if score >= 2:
        direction = "BUY"
    elif score <= -2:
        direction = "SELL"
    else:
        direction = "WAIT"

    # Risk levels are based on ATR and are NOT presented as guaranteed outcomes.
    if direction == "BUY":
        sl = live_price - (1.5 * atr14)
        tp1 = live_price + (1.5 * atr14)
        tp2 = live_price + (2.5 * atr14)
    elif direction == "SELL":
        sl = live_price + (1.5 * atr14)
        tp1 = live_price - (1.5 * atr14)
        tp2 = live_price - (2.5 * atr14)
    else:
        sl = tp1 = tp2 = None

    leverage = get_real_leverage(symbol)

    return {
        "symbol": symbol_code,
        "pair": symbol,
        "price": live_price,
        "ema20": ema20,
        "ema50": ema50,
        "rsi": rsi14,
        "atr": atr14,
        "support": support,
        "resistance": resistance,
        "momentum": momentum_pct,
        "score": score,
        "direction": direction,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "leverage": leverage,
        "timeframe": "15M",
        "source": "Bybit Linear",
    }


# ============================================================
# XAUUSD
# ============================================================

def get_xauusd() -> Optional[dict]:
    """
    Yahoo Finance public chart endpoint for XAUUSD=X.
    If unavailable, PHILEDIZ reports that honestly.
    """
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/XAUUSD=X"
        params = {
            "range": "5d",
            "interval": "15m",
        }

        r = SESSION.get(url, params=params, timeout=(5, 15))
        print(f"YAHOO XAUUSD HTTP {r.status_code}")

        if r.status_code != 200:
            print(f"YAHOO XAUUSD BODY: {r.text[:300]}")
            return None

        data = r.json()
        result = data["chart"]["result"][0]

        quote = result["indicators"]["quote"][0]
        closes = quote.get("close", [])
        highs = quote.get("high", [])
        lows = quote.get("low", [])

        candles = []

        for h, l, c in zip(highs, lows, closes):
            if h is None or l is None or c is None:
                continue
            candles.append({
                "high": float(h),
                "low": float(l),
                "close": float(c),
            })

        if len(candles) < 60:
            print(f"XAUUSD NOT ENOUGH DATA: {len(candles)}")
            return None

        close_values = [c["close"] for c in candles]
        price = close_values[-1]

        ema20 = ema(close_values, 20)
        ema50 = ema(close_values, 50)
        rsi14 = rsi(close_values, 14)

        if ema20 is None or ema50 is None or rsi14 is None:
            return None

        support = min(c["low"] for c in candles[-50:])
        resistance = max(c["high"] for c in candles[-50:])

        score = 0
        score += 1 if price > ema20 else -1
        score += 1 if ema20 > ema50 else -1
        score += 1 if rsi14 >= 55 else (-1 if rsi14 <= 45 else 0)

        direction = "BUY" if score >= 2 else ("SELL" if score <= -2 else "WAIT")

        return {
            "symbol": "XAUUSD",
            "pair": "XAUUSD",
            "price": price,
            "ema20": ema20,
            "ema50": ema50,
            "rsi": rsi14,
            "support": support,
            "resistance": resistance,
            "direction": direction,
            "timeframe": "15M",
            "source": "Yahoo Finance",
        }

    except Exception as exc:
        print(f"XAUUSD REQUEST FAILED: {exc}")
        return None


# ============================================================
# TELEGRAM FORMAT
# ============================================================

def crypto_message(a: dict) -> str:
    lev = (
        f"{a['leverage']:g}x"
        if a["leverage"] is not None
        else "Unavailable"
    )

    lines = [
        "🤖 PHILEDIZ V2 ANALYSIS",
        "",
        f"🪙 Pair: {a['pair']}",
        f"⏱ Timeframe: {a['timeframe']}",
        f"💰 Live Price: {fmt_price(a['price'])}",
        f"📡 Data: {a['source']}",
        "",
        "📊 INDICATORS",
        f"RSI14: {a['rsi']:.2f}",
        f"EMA20: {fmt_price(a['ema20'])}",
        f"EMA50: {fmt_price(a['ema50'])}",
        f"ATR14: {fmt_price(a['atr'])}",
        f"Momentum: {a['momentum']:+.2f}%",
        "",
        "📍 LEVELS",
        f"Support: {fmt_price(a['support'])}",
        f"Resistance: {fmt_price(a['resistance'])}",
        "",
        f"⚡ Max Bybit Leverage: {lev}",
        "",
        f"📌 PHILEDIZ SETUP: {a['direction']}",
        f"🧮 Signal Score: {a['score']}/4",
    ]

    if a["direction"] != "WAIT":
        lines += [
            "",
            f"🛑 SL: {fmt_price(a['sl'])}",
            f"🎯 TP1: {fmt_price(a['tp1'])}",
            f"🎯 TP2: {fmt_price(a['tp2'])}",
        ]

    lines += [
        "",
        "⚠️ Levels are analytical estimates, not guarantees.",
        "Always verify the live price before placing a trade.",
    ]

    return "\n".join(lines)


def xau_message(a: dict) -> str:
    return "\n".join([
        "🤖 PHILEDIZ V2 ANALYSIS",
        "",
        "🥇 Pair: XAUUSD",
        f"⏱ Timeframe: {a['timeframe']}",
        f"💰 Live Price: {fmt_price(a['price'])}",
        f"📡 Data: {a['source']}",
        "",
        "📊 INDICATORS",
        f"RSI14: {a['rsi']:.2f}",
        f"EMA20: {fmt_price(a['ema20'])}",
        f"EMA50: {fmt_price(a['ema50'])}",
        "",
        "📍 LEVELS",
        f"Support: {fmt_price(a['support'])}",
        f"Resistance: {fmt_price(a['resistance'])}",
        "",
        f"📌 PHILEDIZ SETUP: {a['direction']}",
        "",
        "⚠️ XAUUSD data depends on the public Yahoo Finance feed.",
        "Always verify the broker's live price before trading.",
    ])


# ============================================================
# TELEGRAM HANDLERS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 PHILEDIZ V2 is online!\n\n"
        "Send:\n"
        "/analyze BTC\n"
        "/analyze ETH\n"
        "/analyze XAUUSD\n\n"
        "You can also send a symbol directly, e.g. BTC."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 PHILEDIZ V2\n\n"
        "Commands:\n"
        "/start - Start the bot\n"
        "/help - Show help\n"
        "/analyze BTC - Analyze BTC\n"
        "/analyze ETH - Analyze ETH\n"
        "/analyze XAUUSD - Analyze gold\n\n"
        "Supported crypto:\n"
        + ", ".join(CRYPTO.keys())
        + "\n\n"
        "No API key is required for Bybit public market data."
    )


async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Please provide a symbol.\n\n"
            "Example:\n"
            "/analyze BTC\n"
            "/analyze ETH\n"
            "/analyze XAUUSD"
        )
        return

    symbol = clean_symbol(context.args[0])
    await run_analysis(update, symbol)


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    if not text:
        return

    # Only treat a simple symbol as an analysis request.
    if len(text.split()) == 1:
        symbol = clean_symbol(text)

        if symbol in CRYPTO or symbol == "XAUUSD":
            await run_analysis(update, symbol)
            return

    await update.message.reply_text(
        "Send a supported symbol, for example:\n"
        "BTC\nETH\nSOL\nXAUUSD\n\n"
        "Or use /analyze BTC"
    )


async def run_analysis(update: Update, symbol: str):
    await update.message.reply_text(
        f"🔎 PHILEDIZ is checking live {symbol} market data..."
    )

    if symbol == "XAUUSD":
        result = get_xauusd()

        if result:
            await update.message.reply_text(xau_message(result))
        else:
            await update.message.reply_text(
                "❌ PHILEDIZ could not obtain usable live XAUUSD data.\n\n"
                "No price or analysis has been invented."
            )
        return

    result = analyze_crypto(symbol)

    if result:
        await update.message.reply_text(crypto_message(result))
    else:
        await update.message.reply_text(
            "❌ PHILEDIZ could not obtain usable live Bybit market data.\n\n"
            "No price or analysis has been invented.\n\n"
            "If this happens again, check the Render logs. "
            "The new version prints the exact Bybit HTTP/API error."
        )


# ============================================================
# START TELEGRAM
# ============================================================

def run_flask():
    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False,
    )


def run_bot():
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("analyze", analyze_command))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler)
    )

    print("========================================")
    print("🤖 PHILEDIZ V2 starting...")
    print("📊 Live Bybit market analysis enabled")
    print("📈 RSI14 enabled")
    print("📈 EMA20 enabled")
    print("📉 EMA50 enabled")
    print("〽️ ATR14 enabled")
    print("🟦 Support/Resistance enabled")
    print("⚡ Real Bybit max leverage enabled")
    print("🥇 XAUUSD enabled")
    print("🌐 Render web server enabled")
    print("========================================")

    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True,
    )
    flask_thread.start()

    run_bot()
