import os
import re
import threading
from typing import Optional, List

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
# PHILEDIZ V2
# LIVE BYBIT MARKET ANALYSIS
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "10000"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set")

app = Flask(__name__)

# ============================================================
# SUPPORTED CRYPTO
# ============================================================

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

# Official/public Bybit API hosts.
BYBIT_BASES = [
    "https://api.bybit.com",
    "https://api.bytick.com",
]

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 PHILEDIZ-V2",
    "Accept": "application/json",
    "Connection": "close",
})


# ============================================================
# WEB SERVER
# ============================================================

@app.get("/")
def home():
    return "PHILEDIZ V2 is online", 200


@app.get("/health")
def health():
    return {
        "status": "ok",
        "bot": "PHILEDIZ V2",
        "market_data": "Bybit public API",
    }, 200


# ============================================================
# SYMBOL HELPERS
# ============================================================

def clean_symbol(text: str) -> str:
    text = text.upper().strip()

    text = (
        text.replace("/", "")
        .replace("-", "")
        .replace("_", "")
    )

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


# ============================================================
# BYBIT CONNECTION
# ============================================================

def bybit_get(path: str, params: dict) -> Optional[dict]:
    """
    Public Bybit request.

    No API key is required for public market-data endpoints.
    Every important failure is printed to Render logs.
    """

    print("")
    print("========================================")
    print("🔎 BYBIT REQUEST")
    print(f"PATH: {path}")
    print(f"PARAMS: {params}")
    print("========================================", flush=True)

    last_error = "Unknown error"

    for base in BYBIT_BASES:

        url = base + path

        print(
            f"🌐 Trying Bybit host: {base}",
            flush=True
        )

        try:
            response = SESSION.get(
                url,
                params=params,
                timeout=(10, 30),
                allow_redirects=True,
            )

            print(
                f"📡 BYBIT HTTP STATUS: {response.status_code}",
                flush=True
            )

            print(
                f"📡 FINAL URL: {response.url}",
                flush=True
            )

            if response.status_code != 200:
                body = response.text[:1000]

                print(
                    f"❌ BYBIT HTTP ERROR {response.status_code}",
                    flush=True
                )

                print(
                    f"BODY: {body}",
                    flush=True
                )

                last_error = (
                    f"HTTP {response.status_code}: {body}"
                )

                continue

            try:
                data = response.json()
            except Exception as exc:
                print(
                    f"❌ BYBIT JSON ERROR: {repr(exc)}",
                    flush=True
                )

                print(
                    f"RAW BODY: {response.text[:1000]}",
                    flush=True
                )

                last_error = f"JSON error: {repr(exc)}"
                continue

            print(
                f"📦 BYBIT RETCODE: {data.get('retCode')}",
                flush=True
            )

            print(
                f"📦 BYBIT RETMSG: {data.get('retMsg')}",
                flush=True
            )

            if data.get("retCode") != 0:

                print(
                    "❌ BYBIT API ERROR",
                    flush=True
                )

                last_error = (
                    f"retCode={data.get('retCode')} "
                    f"retMsg={data.get('retMsg')}"
                )

                continue

            print(
                "✅ BYBIT REQUEST SUCCESS",
                flush=True
            )

            return data

        except requests.exceptions.Timeout as exc:

            print(
                f"❌ BYBIT TIMEOUT: {repr(exc)}",
                flush=True
            )

            last_error = f"Timeout: {repr(exc)}"

        except requests.exceptions.ConnectionError as exc:

            print(
                f"❌ BYBIT CONNECTION ERROR: {repr(exc)}",
                flush=True
            )

            last_error = f"Connection error: {repr(exc)}"

        except requests.exceptions.RequestException as exc:

            print(
                f"❌ BYBIT REQUEST ERROR: {repr(exc)}",
                flush=True
            )

            last_error = f"Request error: {repr(exc)}"

        except Exception as exc:

            print(
                f"❌ BYBIT UNKNOWN ERROR: {repr(exc)}",
                flush=True
            )

            last_error = repr(exc)

    print("")
    print("❌ ALL BYBIT HOSTS FAILED")
    print(f"FINAL BYBIT ERROR: {last_error}")
    print("", flush=True)

    return None


# ============================================================
# BYBIT CONNECTION TEST
# ============================================================

def test_bybit_connection() -> str:

    print("")
    print("========================================")
    print("🧪 TESTING BYBIT CONNECTION")
    print("========================================", flush=True)

    data = bybit_get(
        "/v5/market/time",
        {}
    )

    if data:

        server_time = (
            data.get("result", {})
            .get("timeNano")
        )

        return (
            "✅ BYBIT CONNECTION WORKS\n\n"
            f"Server time: {server_time or 'received'}"
        )

    return (
        "❌ BYBIT CONNECTION FAILED\n\n"
        "Check Render logs for the exact "
        "HTTP, DNS, timeout, or API error."
    )


# ============================================================
# MARKET DATA
# ============================================================

def get_bybit_klines(
    symbol: str,
    interval: str = "15",
    limit: int = 200
):

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

    result = data.get("result", {})
    rows = result.get("list", [])

    if not rows:

        print(
            f"❌ BYBIT KLINE EMPTY: {symbol}",
            flush=True
        )

        print(
            f"RESULT: {result}",
            flush=True
        )

        return []

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

        except (
            ValueError,
            TypeError,
            IndexError
        ) as exc:

            print(
                f"❌ KLINE PARSE ERROR: {repr(exc)}",
                flush=True
            )

    candles.reverse()

    print(
        f"✅ BYBIT KLINES: {symbol} = {len(candles)} candles",
        flush=True
    )

    return candles


def get_bybit_price(symbol: str) -> Optional[float]:

    data = bybit_get(
        "/v5/market/tickers",
        {
            "category": "linear
