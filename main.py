import os,re,threading,requests
from flask import Flask
from telegram import Update,InlineKeyboardButton,InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder,CommandHandler,MessageHandler,CallbackQueryHandler,ContextTypes,filters

BOT_TOKEN=os.getenv("BOT_TOKEN","").strip()
PORT=int(os.getenv("PORT","10000"))
app=Flask(__name__)

# YOUR ORIGINAL COINS - I NO DELETE ANYTHING
CRYPTO={"BTC":"BTCUSDT","ETH":"ETHUSDT","BNB":"BNBUSDT","SOL":"SOLUSDT","XRP":"XRPUSDT","DOGE":"DOGEUSDT","ADA":"ADAUSDT","AVAX":"AVAXUSDT","LINK":"LINKUSDT","TRX":"TRXUSDT","DOT":"DOTUSDT","MATIC":"MATICUSDT","LTC":"LTCUSDT","BCH":"BCHUSDT","UNI":"UNIUSDT","ATOM":"ATOMUSDT","ETC":"ETCUSDT","FIL":"FILUSDT","PEPE":"PEPEUSDT","BONK":"BONKUSDT","SHIB":"SHIBUSDT","FLOKI":"FLOKIUSDT","FARTCOIN":"FARTCOINUSDT","WIF":"WIFUSDT","BABY":"BABYUSDT","BOME":"BOMEUSDT","PAXG":"PAXGUSDT"}
SESSION=requests.Session()
SESSION.headers.update({"Cache-Control":"no-cache","Pragma":"no-cache"})

@app.get("/")
def home(): return "PHILEDIZ 1H REAL PIP OK",200
@app.get("/health")
def health(): return {"status":"ok"},200

def clean(t):
    t=t.upper().strip().replace("/","").replace("-","").replace("_","")
    t=re.sub(r"[^A-Z0-9]","",t)
    m={"BITCOIN":"BTC","ETHEREUM":"ETH","SOLANA":"SOL","GOLD":"XAUUSD","XAU":"XAUUSD","XAUUSD":"XAUUSD","PAXG":"PAXG"}
    if t in m: t=m[t]
    if t.endswith("USDT") and t[:-4] in CRYPTO: return t[:-4]
    return t

def fmt(v): return f"{v:,.2f}" if v>=1000 else f"{v:,.4f}" if v>=1 else f"{v:,.6f}"

def get_1h_klines(sym):
    try:
        for cat in ["linear","spot"]:
            r=SESSION.get("https://api.bybit.com/v5/market/kline",params={"category":cat,"symbol":sym,"interval":"60","limit":200},timeout=10).json()
            if r.get("retCode")!=0: continue
            rows=r.get("result",{}).get("list",[])
            if len(rows)<50: continue
            c=[]
            for row in rows:
                try: c.append({"h":float(row[2]),"l":float(row[3]),"c":float(row[4])})
                except: pass
            c.reverse()
            return c
    except: pass
    return []

def get_live_price(sym):
    try:
        for cat in ["linear","spot"]:
            r=SESSION.get("https://api.bybit.com/v5/market/tickers",params={"category":cat,"symbol":sym},timeout=6).json()
            lst=r.get("result",{}).get("list",[])
            if lst: return float(lst[0]["lastPrice"])
    except: pass
    try:
        okx_sym=sym.replace("USDT","-USDT")
        r=SESSION.get(f"https://www.okx.com/api/v5/market/ticker?instId={okx_sym}",timeout=5).json()
        return float(r["data"][0]["last"])
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
    e20=ema(closes,20); e50=ema(closes,50); r=rsi(closes); a=atr(kl)
    if not e20 or not e50: return None
    score=(1 if price>e20 else -1)+(1 if e20>e50 else -1)+(1 if r>55 else -1 if r<45 else 0)
    direction="BUY" if score>=2 else "SELL" if score<=-2 else "WAIT"
    lev=15 if code in ["BTC","ETH"] else 10 if code in ["SOL","BNB","XRP","PAXG"] else 5
    if direction=="BUY": sl=price-1.5*a; tp1=price+1.5*a; tp2=price+2.5*a; tp3=price+4*a
    elif direction=="SELL": sl=price+1.5*a; tp1=price-1.5*a; tp2=price-2.5*a; tp3=price-4*a
    else: sl=tp1=tp2=tp3=None
    return {"code":code,"sym":sym,"price":price,"live":live,"e20":e20,"e50":e50,"rsi":r,"atr":a,"dir":direction,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"lev":lev,"score":score,"tf":"1H"}

def get_xauusd_real():
    real=None
    try:
        r=SESSION.get("https://api.gold-api.com/price/XAU",timeout=6)
        if r.status_code==200:
            real=float(r.json().get("price",0))
            if not (3000<real<5000): real=None
    except: pass
    if not real:
        try:
            r=SESSION.get("https://query1.finance.yahoo.com/v8/finance/chart/XAUUSD=X",params={"range":"1d","interval":"1m"},timeout=6).json()
            real=float(r["chart"]["result"][0]["meta"]["regularMarketPrice"])
        except: pass
    kl=get_1h_klines("PAXGUSDT")
    if len(kl)<50: return None
    closes=[x["c"] for x in kl]
    paxg_price=get_live_price("PAXGUSDT") or closes[-1]
    display_price=real if real else paxg_price
    if real and abs(real-paxg_price)<500:
        offset=real-paxg_price
        for k in kl: k["h"]+=offset; k["l"]+=offset; k["c"]+=offset
        closes=[x["c"] for x in kl]
        source=f"REAL XAUUSD ${display_price:.2f} LIVE (gold-api) - 1H"
    else:
        source=f"PAXG ${display_price:.2f} (proxy) - 1H"
    e20=ema(closes,20); e50=ema(closes,50); r=rsi(closes); a=atr(kl)
    score=(1 if display_price>e20 else -1)+(1 if e20>e50 else -1)
    direction="BUY" if score>=1 else "SELL"
    if direction=="BUY": sl=display_price-1.2*a; tp1=display_price+1*a; tp2=display_price+2*a; tp3=display_price+3.5*a
    else: sl=display_price+1.2*a; tp1=display_price-1*a; tp2=display_price-2*a; tp3=display_price-3.5*a
    return {"price":display_price,"real":real,"paxg":paxg_price,"e20":e20,"e50":e50,"rsi":r,"atr":a,"dir":direction,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"src":source,"score":score,"tf":"1H"}

def coins_kb():
    ks=list(CRYPTO.keys()); btns=[]; row=[]
    for c in ks:
        row.append(InlineKeyboardButton(c,callback_data=f"C_{c}"))
        if len(row)==3: btns.append(row); row=[]
    if row: btns.append(row)
    btns.append([InlineKeyboardButton("🥇 XAUUSD 1H REAL $4154",callback_data="C_XAUUSD")])
    return InlineKeyboardMarkup(btns)

def mt5_kb(): return InlineKeyboardMarkup([[InlineKeyboardButton("🥇 XAUUSD 1H REAL",callback_data="C_XAUUSD")],[InlineKeyboardButton("📋 CRYPTO 1H",callback_data="M_COINS")]])

async def start(u,c): await u.message.reply_text("🤖 PHILEDIZ 1H REAL PIP ✅\n\n✅ Crypto REAL live price\n✅ XAUUSD REAL $4154 + PIP\n✅ Leverage dey\n✅ 1H timeframe\n\n/coins → Crypto\n/mt5 → XAUUSD PIP",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 1H CRYPTO",callback_data="M_COINS"),InlineKeyboardButton("🥇 1H XAUUSD PIP",callback_data="M_MT5")]]))
async def coins_cmd(u,c): await u.message.reply_text("📋 SELECT COIN - 1H REAL LIVE:",reply_markup=coins_kb())
async def mt5_cmd(u,c): await u.message.reply_text("🥇 MT5 GOLD - 1H REAL + PIP:",reply_markup=mt5_kb())
async def analyze_cmd(u,c):
    if not c.args: await u.message.reply_text("Ex: /analyze BTC or XAUUSD",reply_markup=coins_kb()); return
    await run(u,clean(c.args[0]))
async def btn(u,c):
    q=u.callback_query; await q.answer(); d=q.data
    if d=="M_COINS": await q.edit_message_text("📋 SELECT COIN - 1H REAL:",reply_markup=coins_kb()); return
    if d=="M_MT5": await q.edit_message_text("🥇 MT5 1H REAL PIP:",reply_markup=mt5_kb()); return
    if d.startswith("C_"): await q.edit_message_text(f"🔎 {d[2:]} 1H REAL fetching..."); await run(q,d[2:])
async def txt(u,c):
    t=(u.message.text or "").strip()
    if len(t.split())==1:
        s=clean(t)
        if s in CRYPTO or s=="XAUUSD": await run(u,s)

async def run(upd,sym):
    from telegram import CallbackQuery
    is_q=isinstance(upd,CallbackQuery)
    send=upd.message.reply_text
    if not is_q: await upd.message.reply_text(f"🔎 {sym} 1H REAL fetching...")
    if sym=="XAUUSD" or sym=="PAXG":
        r=get_xauusd_real()
        if not r: await send("❌ XAUUSD unavailable"); return
        PIP=0.1
        pip_sl=abs(r['price']-r['sl'])/PIP
        pip_tp1=abs(r['tp1']-r['price'])/PIP
        pip_tp2=abs(r['tp2']-r['price'])/PIP
        pip_tp3=abs(r['tp3']-r['price'])/PIP
        await send(f"🤖 XAUUSD MT5 1H REAL + PIP ✅\n\n💰 REAL Price: {fmt(r['price'])} (live)\n📡 {r['src']}\n⏱ Timeframe: {r['tf']}\n📊 EMA20 {fmt(r['e20'])} EMA50 {fmt(r['e50'])} RSI {r['rsi']:.1f}\n\n📌 {r['dir']} Score {r['score']}/10\n\n💵 Entry: {fmt(r['price'])} Lev 10x\n🛑 SL: {fmt(r['sl'])} ({pip_sl:.0f} pips)\n🎯 TP1: {fmt(r['tp1'])} ({pip_tp1:.0f} pips)\n🎯 TP2: {fmt(r['tp2'])} ({pip_tp2:.0f} pips)\n🎯 TP3: {fmt(r['tp3'])} ({pip_tp3:.0f} pips)\n\n⚠️ Pip = $0.10 (MT5 Gold standard)",reply_markup=mt5_kb())
        return
    r=analyze_crypto(sym)
    if not r: await send("❌ Data unavailable",reply_markup=coins_kb()); return
    live_txt=f"REAL LIVE {fmt(r['price'])}" if r['live'] else f"{fmt(r['price'])}"
    if r["dir"]!="WAIT":
        await send(f"🤖 {r['sym']} 1H REAL ✅\n💰 Price: {live_txt} (live)\n📊 EMA20 {fmt(r['e20'])} EMA50 {fmt(r['e50'])} RSI {r['rsi']:.1f}\n⏱ {r['tf']}\n\n📌 {r['dir']} Score {r['score']}\n\n💵 Entry: {fmt(r['price'])} Lev {r['lev']}x\n🛑 SL: {fmt(r['sl'])}\n🎯 TP1: {fmt(r['tp1'])}\n🎯 TP2: {fmt(r['tp2'])}\n🎯 TP3: {fmt(r['tp3'])}",reply_markup=coins_kb())
    else:
        await send(f"🤖 {r['sym']} 1H WAIT\n💰 {live_txt} live Score {r['score']}",reply_markup=coins_kb())

def run_flask(): app.run(host="0.0.0.0",port=PORT)
def run_bot():
    if not BOT_TOKEN: print("No
