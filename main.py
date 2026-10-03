import os,re,threading,requests,time
from flask import Flask
from telegram import InlineKeyboardButton,InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder,CommandHandler,MessageHandler,CallbackQueryHandler,filters

BOT_TOKEN=os.getenv("BOT_TOKEN","").strip()
PORT=int(os.getenv("PORT","10000"))
app=Flask(__name__)

CRYPTO={"BTC":"BTCUSDT","ETH":"ETHUSDT","BNB":"BNBUSDT","SOL":"SOLUSDT","XRP":"XRPUSDT","DOGE":"DOGEUSDT","ADA":"ADAUSDT","AVAX":"AVAXUSDT","LINK":"LINKUSDT","TRX":"TRXUSDT","DOT":"DOTUSDT","MATIC":"MATICUSDT","LTC":"LTCUSDT","BCH":"BCHUSDT","UNI":"UNIUSDT","ATOM":"ATOMUSDT","ETC":"ETCUSDT","FIL":"FILUSDT","PEPE":"PEPEUSDT","BONK":"BONKUSDT","SHIB":"SHIBUSDT","FLOKI":"FLOKIUSDT","FARTCOIN":"FARTCOINUSDT","WIF":"WIFUSDT","BABY":"BABYUSDT","BOME":"BOMEUSDT","PAXG":"PAXGUSDT"}
SESSION=requests.Session()
SESSION.headers.update({"User-Agent":"Mozilla/5.0"})
CACHE={}

@app.get("/")
def home(): return "PHILEDIZ CACHE FIX OK",200
@app.get("/health")
def health(): return {"ok":True},200

def clean(t):
    t=t.upper().strip().replace("/","").replace("-","").replace("_","")
    t=re.sub(r"[^A-Z0-9]","",t)
    m={"BITCOIN":"BTC","ETHEREUM":"ETH","SOLANA":"SOL","GOLD":"XAUUSD","XAU":"XAUUSD","XAUUSD":"XAUUSD","PAXG":"PAXG"}
    if t in m: t=m[t]
    if t.endswith("USDT") and t[:-4] in CRYPTO: return t[:-4]
    return t
def fmt(v): return f"{v:,.2f}" if v>=1000 else f"{v:,.4f}" if v>=1 else f"{v:,.6f}"

def get_klines(sym):
    # cache 3 mins
    if sym in CACHE and time.time()-CACHE[sym][0]<180:
        return CACHE[sym][1]

    # For memecoins use Gate first (fastest for BONK,FARTCOIN,WIF,BABY)
    MEME=["BONKUSDT","FARTCOINUSDT","WIFUSDT","BABYUSDT","BOMEUSDT","PEPEUSDT","FLOKIUSDT","SHIBUSDT"]

    def try_gate():
        try:
            pair=sym.replace("USDT","_USDT")
            r=SESSION.get(f"https://api.gateio.ws/api/v4/spot/candlesticks",params={"currency_pair":pair,"interval":"1h","limit":"200"},timeout=4).json()
            if isinstance(r,list) and len(r)>=50:
                kl=[{"h":float(x[3]),"l":float(x[4]),"c":float(x[2])} for x in r]
                return kl
        except: pass
        return []

    def try_binance_vision():
        try:
            # This domain works on Render when binance.com is blocked
            r=SESSION.get("https://data-api.binance.vision/api/v3/klines",params={"symbol":sym,"interval":"1h","limit":200},timeout=4).json()
            if isinstance(r,list) and len(r)>=50:
                return [{"h":float(x[2]),"l":float(x[3]),"c":float(x[4])} for x in r]
        except: pass
        return []

    def try_okx():
        try:
            inst=sym.replace("USDT","-USDT")
            r=SESSION.get("https://www.okx.com/api/v5/market/candles",params={"instId":inst,"bar":"1H","limit":"200"},timeout=4).json()
            data=r.get("data",[])
            if len(data)>=50:
                c=[{"h":float(row[2]),"l":float(row[3]),"c":float(row[4])} for row in data]
                c.reverse()
                return c
        except: pass
        return []

    kl=[]
    if sym in MEME:
        kl=try_gate()
        if len(kl)<50: kl=try_binance_vision()
        if len(kl)<50: kl=try_okx()
    else:
        kl=try_binance_vision()
        if len(kl)<50: kl=try_okx()
        if len(kl)<50: kl=try_gate()

    if len(kl)>=50:
        CACHE[sym]=(time.time(),kl)
    return kl

def get_price(sym):
    try:
        r=SESSION.get("https://data-api.binance.vision/api/v3/ticker/price",params={"symbol":sym},timeout=3).json()
        if "price" in r: return float(r["price"])
    except: pass
    try:
        inst=sym.replace("USDT","-USDT")
        r=SESSION.get("https://www.okx.com/api/v5/market/ticker",params={"instId":inst},timeout=3).json()
        return float(r["data"][0]["last"])
    except: pass
    try:
        pair=sym.replace("USDT","_USDT")
        r=SESSION.get(f"https://api.gateio.ws/api/v4/spot/tickers",params={"currency_pair":pair},timeout=3).json()
        if isinstance(r,list) and r: return float(r[0]["last"])
    except: pass
    return None

def ema(v,p):
    if len(v)<p: return None
    m=2/(p+1); res=sum(v[:p])/p
    for x in v[p:]: res=(x-res)*m+res
    return res
def rsi(v):
    if len(v)<15: return 50
    g=[];l=[]
    for i in range(1,len(v)):
        ch=v[i]-v[i-1]; g.append(max(ch,0)); l.append(max(-ch,0))
    ag=sum(g[:14])/14; al=sum(l[:14])/14
    if al==0: return 70
    return 100-(100/(1+ag/al))
def atr(c):
    if len(c)<15: return c[-1]["h"]-c[-1]["l"]
    trs=[max(c[i]["h"]-c[i]["l"],abs(c[i]["h"]-c[i-1]["c"]),abs(c[i]["l"]-c[i-1]["c"])) for i in range(1,len(c))]
    return sum(trs[-14:])/14

def analyze(code):
    sym=CRYPTO.get(code)
    kl=get_klines(sym)
    if len(kl)<50: return None
    closes=[x["c"] for x in kl]
    live=get_price(sym)
    price=live if live else closes[-1]
    e20=ema(closes,20); e50=ema(closes,50); rr=rsi(closes); a=atr(kl)
    if not e20 or not e50: return None
    score=(1 if price>e20 else -1)+(1 if e20>e50 else -1)+(1 if rr>55 else -1 if rr<45 else 0)
    d="BUY" if score>=2 else "SELL" if score<=-2 else "WAIT"
    lev=15 if code in ["BTC","ETH"] else 10 if code in ["SOL","BNB","XRP","PAXG"] else 5
    if d=="BUY": sl=price-1.5*a; tp1=price+1.5*a; tp2=price+2.5*a; tp3=price+4*a
    elif d=="SELL": sl=price+1.5*a; tp1=price-1.5*a; tp2=price-2.5*a; tp3=price-4*a
    else: sl=tp1=tp2=tp3=None
    return {"sym":sym,"price":price,"e20":e20,"e50":e50,"rsi":rr,"dir":d,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"lev":lev,"score":score}

def get_xau():
    real=None
    try:
        r=SESSION.get("https://api.gold-api.com/price/XAU",timeout=3)
        if r.status_code==200:
            real=float(r.json().get("price",0))
            if not (3000<real<5000): real=None
    except: pass
    kl=get_klines("PAXGUSDT")
    if len(kl)<50: return None
    closes=[x["c"] for x in kl]
    paxg=get_price("PAXGUSDT") or closes[-1]
    price=real if real else paxg
    if real and abs(real-paxg)<500:
        off=real-paxg
        for k in kl: k["h"]+=off; k["l"]+=off; k["c"]+=off
        closes=[x["c"] for x in kl]
        src=f"REAL XAUUSD ${price:.2f} LIVE"
    else:
        src=f"PAXG ${price:.2f} via Gate/Binance Vision"
    e20=ema(closes,20); e50=ema(closes,50); rr=rsi(closes); a=atr(kl)
    score=(1 if price>e20 else -1)+(1 if e20>e50 else -1)
    d="BUY" if score>=1 else "SELL"
    if d=="BUY": sl=price-1.2*a; tp1=price+1*a; tp2=price+2*a; tp3=price+3.5*a
    else: sl=price+1.2*a; tp1=price-1*a; tp2=price-2*a; tp3=price-3.5*a
    return {"price":price,"e20":e20,"e50":e50,"rsi":rr,"dir":d,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"src":src,"score":score}

def coins_kb():
    ks=list(CRYPTO.keys()); btns=[]; row=[]
    for c in ks:
        row.append(InlineKeyboardButton(c,callback_data=f"C_{c}"))
        if len(row)==3: btns.append(row); row=[]
    if row: btns.append(row)
    btns.append([InlineKeyboardButton("🥇 XAUUSD REAL PIP",callback_data="C_XAUUSD")])
    return InlineKeyboardMarkup(btns)
def mt5_kb(): return InlineKeyboardMarkup([[InlineKeyboardButton("🥇 XAUUSD REAL PIP",callback_data="C_XAUUSD")],[InlineKeyboardButton("📋 CRYPTO ALL",callback_data="M_COINS")]])

async def start(u,c): await u.message.reply_text("🤖 PHILEDIZ FIXED ✅ All coins now work (Vision API)",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 CRYPTO",callback_data="M_COINS"),InlineKeyboardButton("🥇 XAUUSD PIP",callback_data="M_MT5")]]))
async def coins_cmd(u,c): await u.message.reply_text("📋 SELECT COIN - FIXED ALL:",reply_markup=coins_kb())
async def mt5_cmd(u,c): await u.message.reply_text("🥇 MT5 GOLD:",reply_markup=mt5_kb())
async def analyze_cmd(u,c):
    if not c.args: await u.message.reply_text("Ex: /analyze BTC",reply_markup=coins_kb()); return
    await run(u,clean(c.args[0]))
async def btn(u,c):
    q=u.callback_query; await q.answer(); d=q.data
    if d=="M_COINS": await q.edit_message_text("📋 SELECT COIN - ALL WORKING NOW:",reply_markup=coins_kb()); return
    if d=="M_MT5": await q.edit_message_text("🥇 MT5 PIP:",reply_markup=mt5_kb()); return
    if d.startswith("C_"):
        code=d[2:]
        await q.edit_message_text(f"🔎 {code} fast fetching...")
        await run(q,code)

async def txt(u,c):
    t=(u.message.text or "").strip()
    if len(t.split())==1:
        s=clean(t)
        if s in CRYPTO or s=="XAUUSD": await run(u,s)

async def run(upd,sym):
    from telegram import CallbackQuery
    is_q=isinstance(upd,CallbackQuery)
    send=upd.message.reply_text
    if not is_q: await upd.message.reply_text(f"🔎 {sym} fast fetching...")
    if sym=="XAUUSD" or sym=="PAXG":
        r=get_xau()
        if not r: await send("❌ XAUUSD retry 3 sec"); return
        PIP=0.1
        p_sl=abs(r['price']-r['sl'])/PIP; p1=abs(r['tp1']-r['price'])/PIP; p2=abs(r['tp2']-r['price'])/PIP; p3=abs(r['tp3']-r['price'])/PIP
        await send(f"🤖 XAUUSD MT5 1H REAL PIP ✅\n\n💰 {fmt(r['price'])} live\n📡 {r['src']}\n📊 EMA20 {fmt(r['e20'])} EMA50 {fmt(r['e50'])} RSI {r['rsi']:.1f}\n📌 {r['dir']} Score {r['score']}/10\n\n💵 Entry: {fmt(r['price'])} Lev 10x\n🛑 SL: {fmt(r['sl'])} ({p_sl:.0f} pips)\n🎯 TP1: {fmt(r['tp1'])} ({p1:.0f} pips)\n🎯 TP2: {fmt(r['tp2'])} ({p2:.0f} pips)\n🎯 TP3: {fmt(r['tp3'])} ({p3:.0f} pips)",reply_markup=mt5_kb())
        return
    r=analyze(sym)
    if not r: await send(f"❌ {sym} busy - tap again, Render free tier wake up"); return
    if r["dir"]!="WAIT":
        await send(f"🤖 {r['sym']} 1H REAL ✅\n💰 {fmt(r['price'])} live Vision/Gate\n📊 EMA20 {fmt(r['e20'])} EMA50 {fmt(r['e50'])} RSI {r['rsi']:.1f}\n📌 {r['dir']} Score {r['score']}\n\n💵 Entry: {fmt(r['price'])} Lev {r['lev']}x\n🛑 SL: {fmt(r['sl'])}\n🎯 TP1: {fmt(r['tp1'])}\n🎯 TP2: {fmt(r['tp2'])}\n🎯 TP3: {fmt(r['tp3'])}",reply_markup=coins_kb())
    else:
        await send(f"🤖 {r['sym']} 1H WAIT Score {r['score']} {fmt(r['price'])}",reply_markup=coins_kb())

def run_flask(): app.run(host="0.0.0.0",port=PORT)
def run_bot():
    if not BOT_TOKEN: print("No BOT_TOKEN"); return
    a=ApplicationBuilder().token(BOT_TOKEN).build()
    a.add_handler(CommandHandler("start",start))
    a.add_handler(CommandHandler("coins",coins_cmd))
    a.add_handler(CommandHandler("mt5",mt5_cmd))
    a.add_handler(CommandHandler("analyze",analyze_cmd))
    a.add_handler(CallbackQueryHandler(btn))
    a.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,txt))
    a.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    threading.Thread(target=run_flask,daemon=True).start()
    run_bot()
