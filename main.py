import os
import time
import logging
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "10000"))

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)

log = logging.getLogger("GOD-BOT-PRO")

app = Flask(__name__)

HTTP = requests.Session()
HTTP.headers.update({
    "User-Agent": "GOD-BOT-PRO/1.0",
    "Accept": "application/json",
})

TIMEOUT = 8

EXCHANGES = {
    "binance": "https://api.binance.com",
    "bybit": "https://api.bybit.com",
    "okx": "https://www.okx.com",
}

DEFAULT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT",
    "BNBUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "AVAXUSDT", "LINKUSDT",
    "TRXUSDT", "DOTUSDT", "LTCUSDT",
    "BCHUSDT", "SUIUSDT", "APTUSDT",
    "NEARUSDT", "ETCUSDT", "UNIUSDT",
    "FILUSDT", "TONUSDT",
]

TIMEFRAMES = {
    "5m": ("5m", 300000),
    "15m": ("15m", 900000),
    "1h": ("1h", 3600000),
    "4h": ("4h", 14400000),
}


class DataError(Exception):
    pass


def normalize_symbol(raw):
    symbol = (
        raw.upper()
        .replace("/", "")
        .replace("-", "")
        .replace("_", "")
        .strip()
    )

    if not symbol.endswith("USDT"):
        symbol += "USDT"

    if (
        len(symbol) < 7
        or len(symbol) > 20
        or not symbol[:-4].isalnum()
    ):
        raise ValueError(
            "Invalid symbol. Example: BTCUSDT"
        )

    return symbol


def fetch_klines(exchange, symbol, interval="15m"):
    """Fetch public spot candles from an exchange."""

    if exchange == "binance":
        response = HTTP.get(
            EXCHANGES[exchange] + "/api/v3/klines",
            params={
                "symbol": symbol,
                "interval": interval,
                "limit": 200,
            },
            timeout=TIMEOUT,
        )

        response.raise_for_status()
        data = response.json()

        if not isinstance(data, list) or len(data) < 80:
            raise DataError("Insufficient Binance candles.")

        return [
            {
                "time": int(c[0]),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5]),
            }
            for c in data
        ]

    if exchange == "bybit":
        response = HTTP.get(
            EXCHANGES[exchange] + "/v5/market/kline",
            params={
                "category": "spot",
                "symbol": symbol,
                "interval": {
                    "5m": "5",
                    "15m": "15",
                    "1h": "60",
                    "4h": "240",
                }[interval],
                "limit": 200,
            },
            timeout=TIMEOUT,
        )

        response.raise_for_status()
        payload = response.json()

        if payload.get("retCode") != 0:
            raise DataError(
                "Bybit: " + str(payload.get("retMsg"))
            )

        data = list(
            reversed(payload.get("result", {}).get("list", []))
        )

        if len(data) < 80:
            raise DataError("Insufficient Bybit candles.")

        return [
            {
                "time": int(c[0]),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5]),
            }
            for c in data
        ]

    if exchange == "okx":
        response = HTTP.get(
            EXCHANGES[exchange] + "/api/v5/market/candles",
            params={
                "instId": symbol[:-4] + "-USDT",
                "bar": {
                    "5m": "5m",
                    "15m": "15m",
                    "1h": "1H",
                    "4h": "4H",
                }[interval],
                "limit": "200",
            },
            timeout=TIMEOUT,
        )

        response.raise_for_status()
        payload = response.json()

        if payload.get("code") != "0":
            raise DataError(
                "OKX: " + str(payload.get("msg"))
            )

        data = list(
            reversed(payload.get("data", []))
        )

        if len(data) < 80:
            raise DataError("Insufficient OKX candles.")

        return [
            {
                "time": int(c[0]),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5]),
            }
            for c in data
        ]

    raise ValueError(
        "Exchange must be binance, bybit or okx."
    )


def ema(values, period):
    result = [None] * len(values)

    if len(values) < period:
        return result

    current = sum(values[:period]) / period
    result[period - 1] = current

    alpha = 2 / (period + 1)

    for i in range(period, len(values)):
        current = (
            values[i] * alpha
            + current * (1 - alpha)
        )
        result[i] = current

    return result


def calculate_rsi(values, period=14):
    result = [None] * len(values)

    if len(values) <= period:
        return result

    gains = []
    losses = []

    for i in range(1, period + 1):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    result[period] = (
        100 if avg_loss == 0
        else 100 - 100 / (1 + avg_gain / avg_loss)
    )

    for i in range(period + 1, len(values)):
        change = values[i] - values[i - 1]

        avg_gain = (
            avg_gain * (period - 1)
            + max(change, 0)
        ) / period

        avg_loss = (
            avg_loss * (period - 1)
            + max(-change, 0)
        ) / period

        result[i] = (
            100 if avg_loss == 0
            else 100 - 100 / (1 + avg_gain / avg_loss)
        )

    return result


def calculate_atr(candles, period=14):
    ranges = []

    for i, candle in enumerate(candles):
        if i == 0:
            value = candle["high"] - candle["low"]
        else:
            previous = candles[i - 1]["close"]

            value = max(
                candle["high"] - candle["low"],
                abs(candle["high"] - previous),
                abs(candle["low"] - previous),
            )

        ranges.append(value)

    result = [None] * len(candles)

    if len(ranges) < period:
        return result

    current = sum(ranges[:period]) / period
    result[period - 1] = current

    for i in range(period, len(ranges)):
        current = (
            current * (period - 1) + ranges[i]
        ) / period

        result[i] = current

    return result


def format_price(price):
    if price >= 1000:
        return f"{price:,.2f}"

    if price >= 1:
        return f"{price:.4f}".rstrip("0").rstrip(".")

    return f"{price:.8f}".rstrip("0").rstrip(".")def analyse_market(candles, symbol, exchange, interval):
    interval_ms = TIMEFRAMES[interval][1]
    now_ms = int(time.time() * 1000)

    # Use completed candles only.
    closed = [
        c for c in candles
        if c["time"] + interval_ms <= now_ms
    ]

    if len(closed) < 80:
        raise DataError(
            "Not enough completed candles for analysis."
        )

    closes = [c["close"] for c in closed]
    highs = [c["high"] for c in closed]
    lows = [c["low"] for c in closed]
    volumes = [c["volume"] for c in closed]

    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)
    ema200 = ema(closes, 200)
    rsi_values = calculate_rsi(closes, 14)
    atr_values = calculate_atr(closed, 14)

    i = len(closed) - 1

    price = closes[i]
    rsi_now = rsi_values[i]
    atr_now = atr_values[i]

    if (
        ema20[i] is None
        or ema50[i] is None
        or rsi_now is None
        or atr_now is None
    ):
        raise DataError(
            "Indicators could not be calculated."
        )

    ema200_now = ema200[i]

    support = min(lows[-20:])
    resistance = max(highs[-20:])

    average_volume = (
        sum(volumes[-21:-1]) / len(volumes[-21:-1])
        if len(volumes) >= 21 else 0
    )

    volume_ratio = (
        volumes[-1] / average_volume
        if average_volume > 0 else 0
    )

    score = 0
    reasons = []

    if price > ema20[i]:
        score += 1
        reasons.append("Price above EMA20")
    else:
        score -= 1
        reasons.append("Price below EMA20")

    if ema20[i] > ema50[i]:
        score += 1
        reasons.append("EMA20 above EMA50")
    else:
        score -= 1
        reasons.append("EMA20 below EMA50")

    if ema200_now is not None:
        if price > ema200_now:
            score += 1
            reasons.append("Price above EMA200")
        else:
            score -= 1
            reasons.append("Price below EMA200")

    if rsi_now >= 55:
        score += 1
        reasons.append("Bullish RSI momentum")
    elif rsi_now <= 45:
        score -= 1
        reasons.append("Bearish RSI momentum")
    else:
        reasons.append("RSI is neutral")

    if volume_ratio >= 1.2:
        reasons.append("Volume above recent average")

    direction = "WAIT 🟡"
    entry = None
    stop_loss = None
    tp1 = None
    tp2 = None

    # Require multiple confirmations.
    if score >= 3 and rsi_now < 72:
        direction = "BUY / LONG 🟢"
        entry = price

        stop_loss = min(
            entry - 1.4 * atr_now,
            support - 0.15 * atr_now,
        )

        risk = entry - stop_loss

        tp1 = entry + 1.2 * risk
        tp2 = entry + 1.8 * risk

    elif score <= -3 and rsi_now > 28:
        direction = "SELL / SHORT 🔴"
        entry = price

        stop_loss = max(
            entry + 1.4 * atr_now,
            resistance + 0.15 * atr_now,
        )

        risk = stop_loss - entry

        tp1 = entry - 1.2 * risk
        tp2 = entry - 1.8 * risk

    candle_time = datetime.fromtimestamp(
        closed[-1]["time"] / 1000,
        tz=timezone.utc,
    ).strftime("%Y-%m-%d %H:%M UTC")

    return {
        "symbol": symbol,
        "exchange": exchange.upper(),
        "timeframe": interval,
        "price": price,
        "rsi": rsi_now,
        "ema20": ema20[i],
        "ema50": ema50[i],
        "ema200": ema200_now,
        "atr": atr_now,
        "support": support,
        "resistance": resistance,
        "volume_ratio": volume_ratio,
        "direction": direction,
        "entry": entry,
        "sl": stop_loss,
        "tp1": tp1,
        "tp2": tp2,
        "reasons": reasons,
        "candle_time": candle_time,
        "candles_used": len(closed),
    }


def create_report(data):
    lines = [
        "🤖 GOD BOT PRO — MARKET ANALYSIS",
        "",
        f"💱 Pair: {data['symbol']}",
        f"🏦 Exchange: {data['exchange']}",
        f"⏱ Timeframe: {data['timeframe']}",
        f"💵 Last completed-candle price: "
        f"{format_price(data['price'])}",
        f"🕒 Candle time: {data['candle_time']}",
        "",
        "📊 TECHNICAL INDICATORS",
        f"RSI (14): {data['rsi']:.2f}",
        f"EMA 20: {format_price(data['ema20'])}",
        f"EMA 50: {format_price(data['ema50'])}",
        f"EMA 200: "
        f"{format_price(data['ema200']) if data['ema200'] is not None else 'N/A'}",
        f"ATR (14): {format_price(data['atr'])}",
        f"Support: {format_price(data['support'])}",
        f"Resistance: {format_price(data['resistance'])}",
        f"Volume ratio: {data['volume_ratio']:.2f}x",
        "",
        f"📌 DECISION: {data['direction']}",
    ]

    if data["entry"] is not None:
        lines.extend([
            "",
            "🎯 TRADE LEVELS",
            f"Entry: {format_price(data['entry'])}",
            f"Stop Loss: {format_price(data['sl'])}",
            f"Take Profit 1: {format_price(data['tp1'])}",
            f"Take Profit 2: {format_price(data['tp2'])}",
            "Risk/reward: TP1 1.2R; TP2 1.8R",
        ])
    else:
        lines.append(
            "No entry issued because the setup "
            "did not meet the signal threshold."
        )

    lines.extend([
        "",
        "🧠 ANALYSIS REASONS",
        *[f"• {reason}" for reason in data["reasons"]],
        "",
        "⚠️ This is technical analysis, not a guarantee. "
        "TP or SL may not be reached within four hours. "
        "Check the current executable price before trading.",
    ])

    return "\n".join(lines)# ============================================================
# TELEGRAM COMMANDS
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = (
        "🤖 GOD BOT PRO IS ONLINE!\n\n"
        "📊 Market analysis: Binance, Bybit and OKX\n"
        "📈 Indicators: RSI, EMA20/50/200 and ATR\n"
        "🎯 Entry, Stop Loss and Take Profit estimates\n\n"
        "COMMANDS\n\n"
        "/analyze BTCUSDT\n"
        "/analyze ETHUSDT bybit 15m\n"
        "/analyze SOLUSDT okx 1h\n"
        "/analyze BTCUSDT binance 5m\n"
        "/scan\n"
        "/help\n\n"
        "Supported timeframes: 5m, 15m, 1h, 4h\n\n"
        "GOD BOT PRO analyses markets only. "
        "It does not automatically place trades."
    )

    await update.message.reply_text(message)


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await start(update, context)


async def analyze_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if not context.args:
        await update.message.reply_text(
            "Usage:\n"
            "/analyze BTCUSDT\n"
            "/analyze ETHUSDT bybit 15m\n"
            "/analyze SOLUSDT okx 1h"
        )
        return

    try:
        symbol = normalize_symbol(context.args[0])

        exchange = (
            context.args[1].lower()
            if len(context.args) > 1
            else "binance"
        )

        interval = (
            context.args[2].lower()
            if len(context.args) > 2
            else "15m"
        )

        if exchange not in EXCHANGES:
            raise ValueError(
                "Choose binance, bybit or okx."
            )

        if interval not in TIMEFRAMES:
            raise ValueError(
                "Choose 5m, 15m, 1h or 4h."
            )

    except ValueError as error:
        await update.message.reply_text(
            f"❌ {error}"
        )
        return

    progress = await update.message.reply_text(
        "⚡ GOD BOT PRO is fetching market data "
        "and calculating indicators..."
    )

    try:
        candles = fetch_klines(
            exchange,
            symbol,
            interval,
        )

        result = analyse_market(
            candles,
            symbol,
            exchange,
            interval,
        )

        report = create_report(result)

        await progress.edit_text(report)

    except (
        requests.RequestException,
        DataError,
        ValueError,
        KeyError,
    ) as error:

        log.warning(
            "Analysis failed for %s on %s: %s",
            symbol,
            exchange,
            error,
        )

        await progress.edit_text(
            "❌ MARKET DATA ERROR\n\n"
            f"Pair: {symbol}\n"
            f"Exchange: {exchange.upper()}\n"
            f"Reason: {str(error)[:250]}\n\n"
            "No price or signal has been invented. "
            "Try again or use another exchange."
        )


async def scan_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    progress = await update.message.reply_text(
        "🔎 GOD BOT PRO is scanning selected "
        "USDT pairs on Binance using the 15m timeframe..."
    )

    signals = []
    errors = 0

    for symbol in DEFAULT_SYMBOLS:

        try:
            candles = fetch_klines(
                "binance",
                symbol,
                "15m",
            )

            result = analyse_market(
                candles,
                symbol,
                "binance",
                "15m",
            )

            if result["entry"] is not None:
                signals.append(result)

        except Exception as error:
            errors += 1

            log.info(
                "Skipped %s during scan: %s",
                symbol,
                error,
            )

    if not signals:
        await progress.edit_text(
            "🔎 SCAN COMPLETED\n\n"
            "No setups met the signal conditions.\n\n"
            f"Data errors or skipped pairs: {errors}\n\n"
            "GOD BOT PRO will not force a trade."
        )
        return

    output = [
        "🤖 GOD BOT PRO — MARKET SCAN",
        "Exchange: Binance",
        "Timeframe: 15 minutes",
        "",
    ]

    for result in signals[:8]:

        output.extend([
            f"💱 {result['symbol']}",
            f"Signal: {result['direction']}",
            f"Price: {format_price(result['price'])}",
            f"RSI: {result['rsi']:.2f}",
            f"Entry: {format_price(result['entry'])}",
            f"SL: {format_price(result['sl'])}",
            f"TP1: {format_price(result['tp1'])}",
            f"TP2: {format_price(result['tp2'])}",
            "",
        ])

    output.extend([
        f"Skipped pairs: {errors}",
        "",
        "⚠️ These are estimates, not guaranteed results.",
    ])

    report = "\n".join(output)

    if len(report) > 3900:
        report = report[:3800]

    await progress.edit_text(report)


# ============================================================
# RENDER HEALTH CHECK
# ============================================================

@app.get("/")
def home():
    return "GOD BOT PRO is running.", 200


@app.get("/health")
def health():
    return {
        "status": "ok",
        "bot": "GOD BOT PRO",
    }, 200


def run_web_server():
    app.run(
        host="0.0.0.0",
        port=PORT,
        use_reloader=False,
    )


# ============================================================
# START BOT
# ============================================================

def main():

    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is missing. "
            "Add it in Render Environment Variables."
        )

    import threading

    threading.Thread(
        target=run_web_server,
        daemon=True,
    ).start()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("help", help_command)
    )

    application.add_handler(
        CommandHandler("analyze", analyze_command)
    )

    application.add_handler(
        CommandHandler("scan", scan_command)
    )

    log.info("GOD BOT PRO is starting...")

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()
