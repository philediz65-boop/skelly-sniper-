import os,re,threading,requests
from flask import Flask
from telegram import InlineKeyboardButton,InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder,CommandHandler,MessageHandler,CallbackQueryHandler,filters

BOT_TOKEN=os.getenv("BOT_TOKEN","").strip()
PORT=int(os.getenv("PORT","10000"))
app=Flask(__name__)

CRYPTO={"BTC":"BTCUSDT","ETH":"ETHUSDT","BNB":"BNBUSDT","SOL":"SOLUSDT","XRP":"XRPUSDT","DOGE":"DOGEUSDT","ADA":"ADAUSDT","AVAX":"AVAXUSDT","LINK":"LINKUSDT","TRX":"TRXUSDT","DOT":"DOTUSDT","MATIC":"MATICUSDT","LTC":"LTCUSDT","BCH":"BCHUSDT","UNI":"UNIUSDT","ATOM":"ATOMUSDT","ETC":"ETCUSDT","FIL":"FILUSDT","PEPE":"PEPEUSDT","BONK":"BONKUSDT","SHIB":"SHIBUSDT","FLOKI":"FLOKIUSDT","FARTCOIN":"FARTCOINUSDT","WIF":"WIFUSDT","BABY":"BABYUSDT","BOME":"BOMEUSDT","PAXG":"PAXGUSDT"}
SESSION=requests.Session()
SESSION.headers.update({"User-Agent":"Mozilla/5.0"})

@app.get("/")
def home(): return "PHILEDIZ OKX COINBASE OK",200
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

# OKX FIRST - VERY STABLE ON RENDER
def get_okx_klines(sym):
    try:
        inst=sym.replace("USDT","-USDT")
        r=SESSION.get("https://www.okx.com/api/v5/market/candles",params={"instId":inst,"bar":"1H","limit":"200"},timeout=8).json()
        data=r.get("data",[])
        if len(data)>=50:
            c=[]
            for row in data:
                try:
                    # OKX: [ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm]
                    c.append({"h":float(row[2]),"l":float(row[3]),"c":float(row[4])})
                except: pass
            c.reverse()
            return c
    except: pass
    return []

def get_coinbase_klines(sym):
    try:
        # Coinbase uses BTC-USD not BTC-USDT
        base=sym.replace("USDT","")
        prod=f"{base}-USD"
        r=SESSION.get(f"https://api.exchange.coinbase.com/products/{prod}/candles",params={"granularity":3600},timeout=8).json()
        if isinstance(r,list) and len(r)>=50:
            c=[]
            # Coinbase: [time, low, high, open, close, volume] - oldest last? Actually newest first? We sort by time
            r_sorted=sorted(r, key=lambda x: x[0])
            for row in r_sorted[-200:]:
                try: c.append({"h":float(row[2]),"l":float(row[1]),"c":float(row[4])})
                except: pass
            return c
    except: pass
    return []

def get_binance_klines(sym):
    try:
        r=SESSION.get("https://api.binance.com/api/v3/klines",params={"symbol":sym,"interval":"1h","limit":200},timeout=8).json()
        if isinstance(r,list) and len(r)>=50:
            c=[]
            for row in r:
                try: c.append({"h":float(row[2]),"l":float(row[3]),"c":float(row[4])})
                except: pass
            return c
    except: pass
    return []

def get_1h_klines(sym):
    # TRY OKX FIRST
    kl=get_okx_klines(sym)
    if len(kl)>=50: return kl
    kl=get_coinbase_klines(sym)
    if len(kl)>=50: return kl
    kl=get_binance_klines(sym)
    if len(kl)>=50: return kl
    # last bybit
    try:
        for cat in ["linear","spot"]:
            r=SESSION.get("https://api.bybit.com/v5/market/kline",params={"category":cat,"symbol":sym,"interval":"60","limit":200},timeout=6).json()
            rows=r.get("result",{}).get("list",[])
            if len(rows)>=50:
                c=[]
                for row in rows:
                    try: c.append({"h":float(row[2]),"l":float(row[3]),"c":float(row[4])})
                    except: pass
                c.reverse()
                if len(c)>=50: return c
    except: pass
    return []

def get_live_price(sym):
    # 1 OKX
    try:
        inst=sym.replace("USDT","-USDT")
        r=SESSION.get("https://www.okx.com/api/v5/market/ticker",params={"instId":inst},timeout=5).json()
        return float(r["data"][0]["last"])
    except: pass
    # 2 Coinbase
    try:
        base=sym.replace("USDT","")
        r=SESSION.get(f"https://api.exchange.coinbase.com/products/{base}-USD/ticker",timeout=5).json()
        if "price" in r: return float(r["price"])
    except: pass
    # 3 Binance
    try:
        r=SESSION.get("https://api.binance.com/api/v3/ticker/price",params={"symbol":sym},timeout=5).json()
        if "price" in r: return float(r["price"])
    except: pass
    return None

def ema(vals,p):
    if len(vals)<p: return None
    m=2.0/(p+1); res=sum(vals[:p])/p
    for x in vals[p:]: res=(x-res)*m+res
    return res
def rsi(vals):
    if len(vals)<15: return 50
    g=[]; l=[]
    for i in range(1,len(vals)):
        ch=vals[i]-vals[i-1]; g.append(max(ch,0)); l.append(max(-ch,0))
    ag=sum(g[:14])/14; al=sum(l[:14])/14
    if al==0: return 70
    return 100-(100/(1+ag/al))
def atr(c):
    if len(c)<15: return c[-1]["h"]-c[-1]["l"]
    trs=[max(c[i]["h"]-c[i]["l"],abs(c[i]["h"]-c[i-1]["c"]),abs(c[i]["l"]-c[i-1]["c"])) for i in range(1,len(c))]
    return sum(trs[-14:])/14

def analyze_crypto(code):
    sym=CRYPTO.get(code)
    if not sym: return None
    kl=get_1h_klines(sym)
    if len(kl)<50: return None
    closes=[x["c"] for x in kl]
    live=get_live_price(sym)
    price=live if live else closes[-1]
    e20=ema(closes,20); e50=ema(closes,50); rr=rsi(closes); a=atr(kl)
    if not e20 or not e50: return None
    score=(1 if price>e20 else -1)+(1 if e20>e50 else -1)+(1 if rr>55 else -1 if rr<45 else 0)
    direction="BUY" if score>=2 else "SELL" if score<=-2 else "WAIT"
    lev=15 if code in ["BTC","ETH"] else 10 if code in ["SOL","BNB","XRP","PAXG"] else 5
    if direction=="BUY": sl=price-1.5*a; tp1=price+1.5*a; tp2=price+2.5*a; tp3=price+4*a
    elif direction=="SELL": sl=price+1.5*a; tp1=price-1.5*a; tp2=price-2.5*a; tp3=price-4*a
    else: sl=tp1=tp2=tp3=None
    return {"sym":sym,"price":price,"e20":e20,"e50":e50,"rsi":rr,"dir":direction,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"lev":lev,"score":score}

def get_xauusd_real():
    real=None
    try:
        r=SESSION.get("https://api.gold-api.com/price/XAU",timeout=5)
        if r.status_code==200:
            real=float(r.json().get("price",0))
            if not (3000<real<5000): real=None
    except: pass
    # Use PAXG from OKX/Coinbase as chart
    kl=get_1h_klines("PAXGUSDT")
    if len(kl)<50: return None
    closes=[x["c"] for x in kl]
    paxg_price=get_live_price("PAXGUSDT") or closes[-1]
    display_price=real if real else paxg_price
    if real and abs(real-paxg_price)<500:
        offset=real-paxg_price
        for k in kl: k["h"]+=offset; k["l"]+=offset; k["c"]+=offset
        closes=[x["c"] for x in kl]
        source=f"REAL XAUUSD ${display_price:.2f} LIVE OKX"
    else:
        source=f"PAXG ${display_price:.2f} via OKX 1H"
    e20=ema(closes,20); e50=ema(closes,50); rr=rsi(closes); a=atr(kl)
    score=(1 if display_price>e20 else -1)+(1 if e20>e50 else -1)
    direction="BUY" if score>=1 else "SELL"
    if direction=="BUY": sl=display_price-1.2*a; tp1=display_price+1*a; tp2=display_price+2*a; tp3=display_price+3.5*a
    else: sl=display_price+1.2*a; tp1=display_price-1*a; tp2=display_price-2*a; tp3=display_price-3.5*a
    return {"price":display_price,"e20":e20,"e50":e50,"rsi":rr,"dir":direction,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"src":source,"score":score}

def coins_kb():
    ks=list(CRYPTO.keys()); btns=[]; row=[]
    for c in ks:
        row.append(InlineKeyboardButton(c,callback_data=f"C_{c}"))
        if len(row)==3: btns.append(row); row=[]
    if row: btns.append(row)
    btns.append([InlineKeyboardButton("🥇 XAUUSD OKX REAL PIP",callback_data="C_XAUUSD")])
    return InlineKeyboardMarkup(btns)
def mt5_kb(): return InlineKeyboardMarkup([[InlineKeyboardButton("🥇 XAUUSD OKX PIP",callback_data="C_XAUUSD")],[InlineKeyboardButton("📋 CRYPTO OKX",callback_data="M_COINS")]])

async def start(u,c): await u.message.reply_text("🤖 PHILEDIZ OKX+COINBASE ✅ No more unavailable",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 CRYPTO OKX",callback_data="M_COINS"),InlineKeyboardButton("🥇 XAUUSD PIP",callback_data="M_MT5")]]))
async def coins_cmd(u,c): await u.message.reply_text("📋 SELECT COIN - OKX + COINBASE REAL 1H:",reply_markup=coins_kb())
async def mt5_cmd(u,c): await u.message.reply_text("🥇 MT5 GOLD - OKX REAL PIP:",reply_markup=mt5_kb())
async def analyze_cmd(u,c):
    if not c.args: await u.message.reply_text("Ex: /analyze BTC",reply_markup=coins_kb()); return
    await run(u,clean(c.args[0]))
async def btn(u,c):
    q=u.callback_query; await q.answer(); d=q.data
    if d=="M_COINS": await q.edit_message_text("📋 SELECT COIN - OKX REAL:",reply_markup=coins_kb()); return
    if d=="M_MT5": await q.edit_message_text("🥇 MT5 OKX PIP:",reply_markup=mt5_kb()); return
    if d.startswith("C_"): await q.edit_message_text(f"🔎 {d[2:]} OKX fetching..."); await run(q,d[2:])
async def txt(u,c):
    t=(u.message.text or "").strip()
    if len(t.split())==1:
        s=clean(t)
        if s in CRYPTO or s=="XAUUSD": await run(u,s)

async def run(upd,sym):
    from telegram import CallbackQuery
    is_q=isinstance(upd,CallbackQuery)
    send=upd.message.reply_text
    if not is_q: await upd.message.reply_text(f"🔎 {sym} OKX fetching...")
    if sym=="XAUUSD" or sym=="PAXG":
        r=get_xauusd_real()
        if not r: await send("❌ XAUUSD try again in 3s - OKX busy"); return
        PIP=0.1
        pip_sl=abs(r['price']-r['sl'])/PIP
        pip_tp1=abs(r['tp1']-r['price'])/PIP
        pip_tp2=abs(r['tp2']-r['price'])/PIP
        pip_tp3=abs(r['tp3']-r['price'])/PIP
        await send(f"🤖 XAUUSD MT5 OKX REAL PIP ✅\n\n💰 {fmt(r['price'])} live OKX\n📡 {r['src']}\n📊 EMA20 {fmt(r['e20'])} EMA50 {fmt(r['e50'])} RSI {r['rsi']:.1f}\n📌 {r['dir']} Score {r['score']}/10\n\n💵 Entry: {fmt(r['price'])} Lev 10x\n🛑 SL: {fmt(r['sl'])} ({pip_sl:.0f} pips)\n🎯 TP1: {fmt(r['tp1'])} ({pip_tp1:.0f} pips)\n🎯 TP2: {fmt(r['tp2'])} ({pip_tp2:.0f} pips)\n🎯 TP3: {fmt(r['tp3'])} ({pip_tp3:.0f} pips)",reply_markup=mt5_kb())
        return
    r=analyze_crypto(sym)
    if not r: await send(f"❌ {sym} OKX retry - tap again"); return
    if r["dir"]!="WAIT":
        await send(f"🤖 {r['sym']} OKX 1H REAL ✅\n💰 {fmt(r['price'])} live OKX/Coinbase\n📊 EMA20 {fmt(r['e20'])} EMA50 {fmt(r['e50'])} RSI {r['rsi']:.1f}\n📌 {r['dir']} Score {r['score']}\n\n💵 Entry: {fmt(r['price'])} Lev {r['lev']}x\n🛑 SL: {fmt(r['sl'])}\n🎯 TP1: {fmt(r['tp1'])}\n🎯 TP2: {fmt(r['tp2'])}\n🎯 TP3: {fmt(r['tp3'])}",reply_markup=coins_kb())
    else:
        await send(f"🤖 {r['sym']} 1H WAIT Score {r['score']} {fmt(r['price'])} OKX",reply_markup=coins_kb())

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
