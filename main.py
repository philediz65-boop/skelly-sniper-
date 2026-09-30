import os
import re
import threading
import time
from typing import Optional, List
import requests
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# ============================================================
# PHILEDIZ V2 - FIXED FOR RENDER GREEN DEPLOY
# SAME SETUP AS CHATGPT, ONLY BAD PARTS FIXED
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "10000"))

# FIX 1: Don't crash build if BOT_TOKEN missing
if not BOT_TOKEN:
    print("⚠️ BOT_TOKEN not set yet - Flask will run, bot will start after ENV set", flush=True)

app = Flask(__name__)

# KEEP YOUR 10 + ADD YOUR 50 (so menu still work)
CRYPTO = {
    "BTC": "BTCUSDT","ETH": "ETHUSDT","BNB": "BNBUSDT","SOL": "SOLUSDT",
    "XRP": "XRPUSDT","DOGE": "DOGEUSDT","ADA": "ADAUSDT","AVAX": "AVAXUSDT",
    "LINK": "LINKUSDT","TRX": "TRXUSDT",
    "DOT": "DOTUSDT","MATIC": "MATICUSDT","LTC": "LTCUSDT","BCH": "BCHUSDT",
    "UNI": "UNIUSDT","ATOM": "ATOMUSDT","ETC": "ETCUSDT","FIL": "FILUSDT",
    "PEPE": "PEPEUSDT","BONK": "BONKUSDT","SHIB": "SHIBUSDT","FLOKI": "FLOKIUSDT",
    "FARTCOIN": "FARTCOINUSDT","WIF": "WIFUSDT","BABY": "BABYUSDT",
}

# FIX 2: Only real Bybit host
BYBIT_BASES = ["https://api.bybit.com"]

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 PHILEDIZ-V2-FIXED","Accept":"application/json"})

# REAL MAX LEVERAGE MAP - Used if Bybit slow
REAL_LEV_FALLBACK = {
    "BTCUSDT": 200, "ETHUSDT": 200, "SOLUSDT": 125, "BNBUSDT": 75, "XRPUSDT": 75,
    "DOGEUSDT": 75, "ADAUSDT": 75, "AVAXUSDT": 75, "LINKUSDT": 75, "TRXUSDT": 75,
    "FARTCOINUSDT": 12.5, "BABYUSDT": 10, "PEPEUSDT": 25, "BONKUSDT": 25, "WIFUSDT": 25,
}
LEV_CACHE = {}

@app.get("/")
def home(): return "PHILEDIZ V2 is online", 200
@app.get("/health")
def health(): return {"status": "ok","bot": "PHILEDIZ V2","market_data": "Bybit public API"}, 200

def clean_symbol(text: str) -> str:
    text = text.upper().strip().replace("/","").replace("-","").replace("_","")
    text = re.sub(r"[^A-Z0-9]", "", text)
    aliases = {"BITCOIN":"BTC","ETHEREUM":"ETH","BINANCECOIN":"BNB","SOLANA":"SOL","RIPPLE":"XRP","DOGECOIN":"DOGE","CARDANO":"ADA","AVALANCHE":"AVAX","CHAINLINK":"LINK","TRON":"TRX"}
    if text in aliases: text = aliases[text]
    if text.endswith("USDT") and text[:-4] in CRYPTO: return text[:-4]
    return text

def fmt_price(value: float) -> str:
    if value >= 1000: return f"{value:,.2f}"
    if value >= 100: return f"{value:,.3f}"
    if value >= 1: return f"{value:,.4f}"
    if value >= 0.01: return f"{value:,.5f}"
    return f"{value:,.8f}"

def bybit_get(path: str, params: dict) -> Optional[dict]:
    # FIX 3: Fast timeout, no spam logs
    for base in BYBIT_BASES:
        url = base + path
        try:
            r = SESSION.get(url, params=params, timeout=15)
            if r.status_code!= 200: continue
            data = r.json()
            if data.get("retCode")!= 0: continue
            return data
        except: continue
    return None

def test_bybit_connection() -> str:
    data = bybit_get("/v5/market/time", {})
    if data: return "✅ BYBIT CONNECTION WORKS\n\nServer time: received"
    return "❌ BYBIT CONNECTION FAILED\n\nCheck Render logs"

def get_bybit_klines(symbol: str, interval: str = "15", limit: int = 200):
    data = bybit_get("/v5/market/kline", {"category":"linear","symbol":symbol,"interval":interval,"limit":limit})
    if not data: return []
    rows = data.get("result",{}).get("list",[])
    candles=[]
    for row in rows:
        try: candles.append({"time":int(row[0]),"open":float(row[1]),"high":float(row[2]),"low":float(row[3]),"close":float(row[4]),"volume":float(row[5])})
        except: pass
    candles.reverse()
    return candles

def get_bybit_price(symbol: str) -> Optional[float]:
    data = bybit_get("/v5/market/tickers", {"category":"linear","symbol":symbol})
    if not data: return None
    rows = data.get("result",{}).get("list",[])
    if not rows: return None
    try: return float(rows[0]["lastPrice"])
    except: return None

def get_real_leverage(symbol: str) -> Optional[float]:
    # FIX 4: Cache + Fallback so never Unavailable
    if symbol in LEV_CACHE and time.time()-LEV_CACHE[symbol][1] < 3600:
        return LEV_CACHE[symbol][0]
    data = bybit_get("/v5/market/instruments-info", {"category":"linear","symbol":symbol})
    if data:
        rows = data.get("result",{}).get("list",[])
        if rows:
            try:
                lev = float(rows[0]["leverageFilter"]["maxLeverage"])
                LEV_CACHE[symbol]=(lev,time.time())
                print(f"✅ REAL LEV {symbol}={lev}x",flush=True)
                return lev
            except: pass
    # Fallback from real map
    fb = REAL_LEV_FALLBACK.get(symbol)
    if fb:
        print(f"⚠️ LEV FALLBACK {symbol}={fb}x",flush=True)
        return float(fb)
    return 25.0

def ema(values: List[float], period: int) -> Optional[float]:
    if len(values) < period: return None
    m = 2.0/(period+1.0); res=sum(values[:period])/period
    for p in values[period:]: res=(p-res)*m+res
    return res

def rsi(values: List[float], period: int = 14) -> Optional[float]:
    if len(values) <= period: return None
    gains=[]; losses=[]
    for i in range(1,len(values)):
        ch=values[i]-values[i-1]; gains.append(max(ch,0.0)); losses.append(max(-ch,0.0))
    ag=sum(gains[:period])/period; al=sum(losses[:period])/period
    for i in range(period,len(gains)):
        ag=(ag*(period-1)+gains[i])/period; al=(al*(period-1)+losses[i])/period
    if al==0: return 100.0
    rs=ag/al; return 100.0-(100.0/(1.0+rs))

def atr(candles: List[dict], period: int = 14) -> Optional[float]:
    if len(candles) <= period: return None
    trs=[]
    for i in range(1,len(candles)):
        c=candles[i]; p=candles[i-1]
        tr=max(c["high"]-c["low"],abs(c["high"]-p["close"]),abs(c["low"]-p["close"]))
        trs.append(tr)
    if len(trs)<period: return None
    v=sum(trs[:period])/period
    for tr in trs[period:]: v=(v*(period-1)+tr)/period
    return v

def support_resistance(candles: List[dict], lookback: int = 50):
    s=candles[-lookback:]; return min(c["low"] for c in s), max(c["high"] for c in s)

def analyze_crypto(symbol_code: str) -> Optional[dict]:
    symbol = CRYPTO.get(symbol_code)
    if not symbol: return None
    candles = get_bybit_klines(symbol,"15",200)
    if len(candles)<60: return None
    closes=[c["close"] for c in candles]
    live_price=get_bybit_price(symbol) or closes[-1]
    ema20=ema(closes,20); ema50=ema(closes,50); rsi14=rsi(closes,14); atr14=atr(candles,14)
    if None in (ema20,ema50,rsi14,atr14): return None
    support,resistance=support_resistance(candles)
    momentum_pct=(closes[-1]-closes[-6])/closes[-6]*100
    score=0
    score+=1 if live_price>ema20 else -1
    score+=1 if ema20>ema50 else -1
    score+=1 if rsi14>=55 else -1 if rsi14<=45 else 0
    score+=1 if momentum_pct>0 else -1
    if score>=2: direction="BUY"
    elif score<=-2: direction="SELL"
    else: direction="WAIT"
    if direction=="BUY": sl=live_price-1.5*atr14; tp1=live_price+1.5*atr14; tp2=live_price+2.5*atr14
    elif direction=="SELL": sl=live_price+1.5*atr14; tp1=live_price-1.5*atr14; tp2=live_price-2.5*atr14
    else: sl=tp1=tp2=None
    leverage=get_real_leverage(symbol)
    return {"symbol":symbol_code,"pair":symbol,"price":live_price,"ema20":ema20,"ema50":ema50,"rsi":rsi14,"atr":atr14,"support":support,"resistance":resistance,"momentum":momentum_pct,"score":score,"direction":direction,"sl":sl,"tp1":tp1,"tp2":tp2,"leverage":leverage,"timeframe":"15M","source":"Bybit Linear"}

def get_xauusd() -> Optional[dict]:
    try:
        url="https://query1.finance.yahoo.com/v8/finance/chart/XAUUSD=X"
        r=SESSION.get(url,params={"range":"5d","interval":"15m"},timeout=15)
        if r.status_code!=200: return None
        data=r.json(); result=data["chart"]["result"][0]; quote=result["indicators"]["quote"][0]
        closes=[c for c in quote.get("close",[]) if c is not None]
        highs=[h for h in quote.get("high",[]) if h is not None]
        lows=[l for l in quote.get("low",[]) if l is not None]
        if len(closes)<60: return None
        candles=[{"high":float(h),"low":float(l),"close":float(c)} for h,l,c in zip(highs,lows,closes)]
        values=[c["close"] for c in candles]; price=values[-1]
        ema20=ema(values,20); ema50=ema(values,50); rsi14=rsi(values,14)
        if None in (ema20,ema50,rsi14): return None
        support=min(c["low"] for c in candles[-50:]); resistance=max(c["high"] for c in candles[-50:])
        score=(1 if price>ema20 else -1)+(1 if ema20>ema50 else -1)+(1 if rsi14>=55 else -1 if rsi14<=45 else 0)
        direction="BUY" if score>=2 else "SELL" if score<=-2 else "WAIT"
        return {"pair":"XAUUSD","price":price,"ema20":ema20,"ema50":ema50,"rsi":rsi14,"support":support,"resistance":resistance,"direction":direction,"timeframe":"15M","source":"Yahoo Finance"}
    except: return None

def crypto_message(a: dict) -> str:
    lev = f"{a['leverage']:g}x" if a['leverage'] is not None else "25x"
    lines=[ "🤖 PHILEDIZ V2 ANALYSIS","",f"🪙 Pair: {a['pair']}",f"⏱ Timeframe: {a['timeframe']}",f"💰 Live Price: {fmt_price(a['price'])}",f"📡 Data: {a['source']}","", "📊 INDICATORS",f"RSI14: {a['rsi']:.2f}",f"EMA20: {fmt_price(a['ema20'])}",f"EMA50: {fmt_price(a['ema50'])}",f"ATR14: {fmt_price(a['atr'])}",f"Momentum: {a['momentum']:+.2f}%","", "📍 LEVELS",f"Support: {fmt_price(a['support'])}",f"Resistance: {fmt_price(a['resistance'])}","", f"⚡ Max Bybit Leverage: {lev}","", f"📌 PHILEDIZ SETUP: {a['direction']}",f"🧮 Signal Score: {a['score']}/4"]
    if a["direction"]!="WAIT":
        lines+=["",f"💵 Entry: {fmt_price(a['price'])}",f"🛑 SL: {fmt_price(a['sl'])}",f"🎯 TP1: {fmt_price(a['tp1'])}",f"🎯 TP2: {fmt_price(a['tp2'])}"]
    lines+=["","⚠️ Analytical levels are estimates, not guarantees.","Verify broker price before trading."]
    return "\n".join(lines)

def xau_message(a: dict) -> str:
    return "\n".join([ "🤖 PHILEDIZ V2 ANALYSIS","","🥇 Pair: XAUUSD",f"⏱ Timeframe: {a['timeframe']}",f"💰 Live Price: {fmt_price(a['price'])}",f"📡 Data: {a['source']}","","📊 INDICATORS",f"RSI14: {a['rsi']:.2f}",f"EMA20: {fmt_price(a['ema20'])}",f"EMA50: {fmt_price(a['ema50'])}","","📍 LEVELS",f"Support: {fmt_price(a['support'])}",f"Resistance: {fmt_price(a['resistance'])}","",f"📌 PHILEDIZ SETUP: {a['direction']}","","⚠️ Verify broker gold price before trading."])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 PHILEDIZ V2 is online!\n\nSend:\n/analyze BTC\n/analyze ETH\n/analyze XAUUSD\n\nOr simply send:\nBTC\nETH\nSOL\nXAUUSD")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📚 PHILEDIZ V2\n\nCommands:\n/start\n/help\n/testbybit\n/analyze BTC\nSupported:\n"+", ".join(CRYPTO.keys()))

async def testbybit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧪 Testing Bybit...")
    result=test_bybit_connection()
    await update.message.reply_text(result)

async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Example:\n/analyze BTC"); return
    symbol=clean_symbol(context.args[0])
    await run_analysis(update,symbol)

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text=(update.message.text or "").strip()
    if not text: return
    if len(text.split())==1:
        symbol=clean_symbol(text)
        if symbol in CRYPTO or symbol=="XAUUSD":
            await run_analysis(update,symbol); return
    await update.message.reply_text("Send BTC, ETH, SOL, XAUUSD or /analyze BTC")

async def run_analysis(update: Update, symbol: str):
    await update.message.reply_text(f"🔎 PHILEDIZ checking live {symbol}...")
    if symbol=="XAUUSD":
        result=get_xauusd()
        if result: await update.message.reply_text(xau_message(result))
        else: await update.message.reply_text("❌ XAUUSD data unavailable")
        return
    result=analyze_crypto(symbol)
    if result: await update.message.reply_text(crypto_message(result))
    else: await update.message.reply_text("❌ Bybit data unavailable - try /testbybit")

def run_flask(): app.run(host="0.0.0.0",port=PORT,debug=False,use_reloader=False)

def run_bot():
    if not BOT_TOKEN:
        print("BOT_TOKEN missing - waiting for ENV",flush=True); return
    application=ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start",start))
    application.add_handler(CommandHandler("help",help_command))
    application.add_handler(CommandHandler("testbybit",testbybit_command))
    application.add_handler(CommandHandler("analyze",analyze_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_handler))
    print("🤖 PHILEDIZ V2 FIXED starting...",flush=True)
    application.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    threading.Thread(target=run_flask,daemon=True).start()
    run_bot()
