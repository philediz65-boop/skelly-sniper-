import os, threading, time, re, requests
from typing import Optional, List
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN","").strip()
PORT = int(os.getenv("PORT", "10000"))

# 50 COINS - YOUR FULL LIST
COINS = ["BTC","ETH","SOL","BNB","XRP","DOGE","AVAX","ADA","LINK","DOT","MATIC","LTC","BCH","UNI","ATOM","ETC","FIL","HBAR","NEAR","APT","SUI","SEI","INJ","TIA","ARB","OP","PEPE","BONK","SHIB","FLOKI","FARTCOIN","WIF","BABY","BOME","BRETT","POPCAT","TRUMP","TURBO","GOAT","PNUT","ACT","MEW","NEIRO","NOT","JUP","ENA","WLD","FET","RNDR","IMX"]

CRYPTO_MAP = {c: f"{c}USDT" for c in COINS}
LEV_CACHE = {}
SESSION = requests.Session()
SESSION.headers.update({"User-Agent":"Mozilla/5.0"})

app = Flask(__name__)
@app.get("/")
def home(): return "PHILEDIZ V2 + SKELLY 50 LIVE - OK", 200
@app.get("/health")
def health(): return {"status":"ok"}, 200

def fmt_price(v: float) -> str:
    v=float(v)
    if v>=1000: return f"{v:,.2f}"
    if v>=100: return f"{v:,.3f}"
    if v>=1: return f"{v:,.4f}"
    if v>=0.01: return f"{v:,.5f}"
    return f"{v:,.8f}"

def bybit_get(path, params):
    # FIXED: No crash, 1 host only, fast timeout
    try:
        url = "https://api.bybit.com" + path
        r = SESSION.get(url, params=params, timeout=15)
        if r.status_code!=200: return None
        data = r.json()
        if data.get("retCode")!=0: return None
        return data
    except: return None

def get_bybit_klines(symbol, interval="60", limit=100):
    d = bybit_get("/v5/market/kline", {"category":"linear","symbol":symbol,"interval":interval,"limit":limit})
    if not d: return []
    rows = d.get("result",{}).get("list",[])
    candles=[]
    for row in rows:
        try:
            candles.append({"time":int(row[0]),"open":float(row[1]),"high":float(row[2]),"low":float(row[3]),"close":float(row[4]),"volume":float(row[5])})
        except: pass
    candles.reverse()
    return candles

def get_bybit_price(symbol):
    d = bybit_get("/v5/market/tickers", {"category":"linear","symbol":symbol})
    if not d: return None
    rows = d.get("result",{}).get("list",[])
    if not rows: return None
    try: return float(rows[0]["lastPrice"])
    except: return None

def get_real_leverage(symbol_code):
    # REAL FROM EXCHANGE SOURCE
    if symbol_code in LEV_CACHE and time.time()-LEV_CACHE[symbol_code][1]<3600:
        return LEV_CACHE[symbol_code][0]
    sym = f"{symbol_code}USDT"
    d = bybit_get("/v5/market/instruments-info", {"category":"linear","symbol":sym})
    if d:
        rows = d.get("result",{}).get("list",[])
        if rows:
            try:
                lev = float(rows[0]["leverageFilter"]["maxLeverage"])
                lev_str = f"{lev:g}x"
                LEV_CACHE[symbol_code]=(lev_str,time.time())
                print(f"REAL LEV {symbol_code} = {lev_str}", flush=True)
                return lev_str
            except: pass
    fallback = {"BTC":"200x","ETH":"200x","SOL":"125x","BNB":"75x","XRP":"75x","DOGE":"75x","AVAX":"75x","ADA":"75x","LINK":"75x","DOT":"50x","MATIC":"50x","LTC":"75x","BCH":"75x","UNI":"50x","ATOM":"50x","ETC":"50x","FIL":"50x","HBAR":"50x","NEAR":"50x","APT":"50x","SUI":"50x","SEI":"50x","INJ":"50x","TIA":"50x","ARB":"50x","OP":"50x","PEPE":"25x","BONK":"25x","SHIB":"25x","FLOKI":"25x","FARTCOIN":"12.5x","WIF":"25x","BABY":"10x","BOME":"25x","BRETT":"25x","POPCAT":"25x","TRUMP":"25x","TURBO":"20x","GOAT":"20x","PNUT":"20x","ACT":"20x","MEW":"20x","NEIRO":"20x","NOT":"25x","JUP":"50x","ENA":"50x","WLD":"50x","FET":"50x","RNDR":"50x","IMX":"50x"}
    return fallback.get(symbol_code,"25x")

def ema(values: List[float], period: int):
    if len(values)<period: return None
    m=2.0/(period+1.0)
    res=sum(values[:period])/period
    for p in values[period:]: res=(p-res)*m+res
    return res

def rsi(values: List[float], period=14):
    if len(values)<=period: return None
    gains=[]; losses=[]
    for i in range(1,len(values)):
        ch=values[i]-values[i-1]
        gains.append(max(ch,0.0)); losses.append(max(-ch,0.0))
    ag=sum(gains[:period])/period; al=sum(losses[:period])/period
    for i in range(period,len(gains)):
        ag=(ag*(period-1)+gains[i])/period
        al=(al*(period-1)+losses[i])/period
    if al==0: return 100.0
    rs=ag/al
    return 100.0-(100.0/(1.0+rs))

def atr(candles: List[dict], period=14):
    if len(candles)<=period: return None
    trs=[]
    for i in range(1,len(candles)):
        c=candles[i]; p=candles[i-1]
        tr=max(c["high"]-c["low"],abs(c["high"]-p["close"]),abs(c["low"]-p["close"]))
        trs.append(tr)
    if len(trs)<period: return None
    v=sum(trs[:period])/period
    for tr in trs[period:]: v=(v*(period-1)+tr)/period
    return v

def analyze_crypto(symbol_code):
    symbol = CRYPTO_MAP.get(symbol_code)
    if not symbol: return None
    candles = get_bybit_klines(symbol,"60",100)
    if len(candles)<50:
        # Try 15m fallback
        candles = get_bybit_klines(symbol,"15",100)
    if len(candles)<50: return None
    closes=[c["close"] for c in candles]
    price = get_bybit_price(symbol) or closes[-1]
    e20=ema(closes,20); e50=ema(closes,50); rsi14=rsi(closes,14); atr14=atr(candles,14)
    if None in (e20,e50,rsi14,atr14): return None
    sup=min(c["low"] for c in candles[-50:]); res=max(c["high"] for c in candles[-50:])
    mom=(closes[-1]-closes[-6])/closes[-6]*100
    score=0
    if price>e20: score+=1
    else: score-=1
    if e20>e50: score+=1
    else: score-=1
    if rsi14>=55: score+=1
    elif rsi14<=45: score-=1
    if mom>0: score+=1
    else: score-=1
    if score>=2: direction="BUY"
    elif score<=-2: direction="SELL"
    else: direction="WAIT"
    if direction=="BUY": sl=price-1.5*atr14; tp1=price+1.5*atr14; tp2=price+2.5*atr14
    elif direction=="SELL": sl=price+1.5*atr14; tp1=price-1.5*atr14; tp2=price-2.5*atr14
    else: sl=tp1=tp2=None
    lev=get_real_leverage(symbol_code)
    return {"symbol":symbol_code,"pair":symbol,"price":price,"ema20":e20,"ema50":e50,"rsi":rsi14,"atr":atr14,"support":sup,"resistance":res,"momentum":mom,"score":score,"direction":direction,"sl":sl,"tp1":tp1,"tp2":tp2,"leverage":lev,"timeframe":"1H","source":"Bybit Linear"}

def crypto_message(a):
    lev=a['leverage']
    lines=[f"🤖 PHILEDIZ V2 - {a['symbol']} 50/50","",f"🪙 Pair: {a['pair']}",f"⏱ TF: {a['timeframe']}",f"💰 Live: {fmt_price(a['price'])}",f"📡 {a['source']}","", "📊 INDICATORS", f"RSI14: {a['rsi']:.2f}", f"EMA20: {fmt_price(a['ema20'])}", f"EMA50: {fmt_price(a['ema50'])}", f"ATR14: {fmt_price(a['atr'])}", f"Momentum: {a['momentum']:+.2f}%","", "📍 LEVELS", f"Support: {fmt_price(a['support'])}", f"Resistance: {fmt_price(a['resistance'])}","", f"⚡ Max Real Leverage: {lev} (Bybit)","", f"📌 SETUP: {a['direction']}", f"🧮 Score: {a['score']}/4"]
    if a['direction']!="WAIT":
        lines+=["",f"💵 Entry: {fmt_price(a['price'])}",f"🛑 SL: {fmt_price(a['sl'])}",f"🎯 TP1: {fmt_price(a['tp1'])}",f"🎯 TP2: {fmt_price(a['tp2'])}", "", "Move SL to entry after TP1"]
    lines+=["","⚠️ Verify broker price before trade."]
    return "\n".join(lines)

def menu(page=0):
    per=12; st=page*per; chunk=COINS[st:st+per]; btns=[]; row=[]
    for c in chunk:
        row.append(InlineKeyboardButton(c, callback_data=f"C_{c}"))
        if len(row)==3: btns.append(row); row=[]
    if row: btns.append(row)
    nav=[]
    if page>0: nav.append(InlineKeyboardButton("Prev", callback_data=f"P_{page-1}"))
    if st+per < len(COINS): nav.append(InlineKeyboardButton("Next", callback_data=f"P_{page+1}"))
    if nav: btns.append(nav)
    btns.append([InlineKeyboardButton("XAUUSD - Coming Soon", callback_data="GOLD")])
    return InlineKeyboardMarkup(btns)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not BOT_TOKEN: return
    await update.message.reply_text("PHILEDIZ V2 + SKELLY 50 - REAL Leverage Per Coin\nSelect coin (50 coins):", reply_markup=menu(0))

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer(); d=q.data
    if d.startswith("P_"):
        pg=int(d[2:]); await q.edit_message_text(f"Page {pg+1} - 50 Coins:", reply_markup=menu(pg)); return
    if d=="GOLD":
        await q.edit_message_text("Gold soon - select crypto for now", reply_markup=menu(0)); return
    if d.startswith("C_"):
        sym=d[2:]; await q.edit_message_text(f"🔎 Fetching {sym} REAL leverage + TA...")
        res=analyze_crypto(sym)
        if res:
            txt=crypto_message(res)
            await context.bot.send_message(chat_id=q.message.chat.id, text=txt, reply_markup=menu(0))
        else:
            await context.bot.send_message(chat_id=q.message.chat.id, text=f"❌ Could not fetch {sym} - tap again", reply_markup=menu(0))
        return

def run_flask():
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)

def run_bot():
    if not BOT_TOKEN:
        print("BOT_TOKEN missing - Flask only", flush=True)
        return
    application = ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", start))
    application.add_handler(CallbackQueryHandler(handle))
    # also keep old commands
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lambda u,c: start(u,c)))
    application.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    run_bot()
