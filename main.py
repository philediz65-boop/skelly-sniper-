import os,re,threading,requests
from flask import Flask
from telegram import Update,InlineKeyboardButton,InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder,CommandHandler,MessageHandler,CallbackQueryHandler,ContextTypes,filters

BOT_TOKEN=os.getenv("BOT_TOKEN","").strip()
PORT=int(os.getenv("PORT","10000"))
app=Flask(__name__)

CRYPTO={"BTC":"BTCUSDT","ETH":"ETHUSDT","BNB":"BNBUSDT","SOL":"SOLUSDT","XRP":"XRPUSDT","DOGE":"DOGEUSDT","ADA":"ADAUSDT","AVAX":"AVAXUSDT","LINK":"LINKUSDT","TRX":"TRXUSDT","DOT":"DOTUSDT","MATIC":"MATICUSDT","LTC":"LTCUSDT","BCH":"BCHUSDT","UNI":"UNIUSDT","ATOM":"ATOMUSDT","ETC":"ETCUSDT","FIL":"FILUSDT","PEPE":"PEPEUSDT","BONK":"BONKUSDT","SHIB":"SHIBUSDT","FLOKI":"FLOKIUSDT","FARTCOIN":"FARTCOINUSDT","WIF":"WIFUSDT","BABY":"BABYUSDT","BOME":"BOMEUSDT","PAXG":"PAXGUSDT"}
SESSION=requests.Session()

@app.get("/")
def home(): return "PHILEDIZ OK",200

def clean(t):
    t=t.upper().strip().replace("/","").replace("-","").replace("_","")
    t=re.sub(r"[^A-Z0-9]","",t)
    m={"BITCOIN":"BTC","ETHEREUM":"ETH","SOLANA":"SOL","GOLD":"XAUUSD","XAU":"XAUUSD","XAUUSD":"XAUUSD","PAXG":"PAXG"}
    if t in m: t=m[t]
    if t.endswith("USDT") and t[:-4] in CRYPTO: return t[:-4]
    return t

def fmt(v):
    return f"{v:,.2f}" if v>=1000 else f"{v:,.4f}" if v>=1 else f"{v:,.6f}"

def bybit_kline(sym):
    try:
        for cat in ["linear","spot"]:
            r=SESSION.get("https://api.bybit.com/v5/market/kline",params={"category":cat,"symbol":sym,"interval":"15","limit":200},timeout=10).json()
            if r.get("retCode")!=0: continue
            rows=r.get("result",{}).get("list",[])
            if len(rows)<30: continue
            c=[]
            for row in rows:
                try: c.append({"o":float(row[1]),"h":float(row[2]),"l":float(row[3]),"c":float(row[4])})
                except: pass
            c.reverse()
            return c
    except: pass
    return []

def bybit_ticker(sym):
    try:
        for cat in ["linear","spot"]:
            r=SESSION.get("https://api.bybit.com/v5/market/tickers",params={"category":cat,"symbol":sym},timeout=8).json()
            lst=r.get("result",{}).get("list",[])
            if not lst: continue
            return float(lst[0]["lastPrice"])
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
    trs=[]
    for i in range(1,len(c)):
        trs.append(max(c[i]["h"]-c[i]["l"],abs(c[i]["h"]-c[i-1]["c"]),abs(c[i]["l"]-c[i-1]["c"])))
    return sum(trs[-14:])/14

def analyze(code):
    sym=CRYPTO.get(code)
    if not sym: return None
    kl=bybit_kline(sym)
    if len(kl)<40: return None
    closes=[x["c"] for x in kl]
    price=bybit_ticker(sym) or closes[-1]
    e20=ema(closes,20); e50=ema(closes,50); r=rsi(closes); a=atr(kl)
    if not e20 or not e50: return None
    score=(1 if price>e20 else -1)+(1 if e20>e50 else -1)+(1 if r>55 else -1 if r<45 else 0)
    direction="BUY" if score>=2 else "SELL" if score<=-2 else "WAIT"
    lev=15 if code in ["BTC","ETH"] else 10 if code in ["SOL","BNB","XRP","PAXG"] else 5
    if direction=="BUY": sl=price-1.5*a; tp1=price+1.5*a; tp2=price+2.5*a; tp3=price+4*a
    elif direction=="SELL": sl=price+1.5*a; tp1=price-1.5*a; tp2=price-2.5*a; tp3=price-4*a
    else: sl=tp1=tp2=tp3=None
    return {"code":code,"sym":sym,"price":price,"e20":e20,"e50":e50,"rsi":r,"atr":a,"dir":direction,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"lev":lev,"score":score}

def get_gold():
    real=None
    try:
        r=SESSION.get("https://api.gold-api.com/price/XAU",timeout=8)
        if r.status_code==200: real=float(r.json().get("price",0))
    except: pass
    kl=bybit_kline("PAXGUSDT")
    if len(kl)<40: return None
    closes=[x["c"] for x in kl]; paxg=closes[-1]
    price=real if real and abs(real-paxg)<300 else paxg
    e20=ema(closes,20); e50=ema(closes,50); r=rsi(closes); a=atr(kl)
    score=(1 if price>e20 else -1)+(1 if e20>e50 else -1)
    direction="BUY" if score>=1 else "SELL"
    if direction=="BUY": sl=price-1.2*a; tp1=price+1*a; tp2=price+2*a; tp3=price+3.5*a
    else: sl=price+1.2*a; tp1=price-1*a; tp2=price-2*a; tp3=price-3.5*a
    src=f"REAL XAUUSD ${price:.2f} Live" if real else f"PAXG ${price:.2f}"
    return {"price":price,"e20":e20,"e50":e50,"rsi":r,"dir":direction,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"src":src,"score":score}

def coins_kb():
    ks=list(CRYPTO.keys()); btns=[]; row=[]
    for c in ks:
        row.append(InlineKeyboardButton(c,callback_data=f"C_{c}"))
        if len(row)==3: btns.append(row); row=[]
    if row: btns.append(row)
    btns.append([InlineKeyboardButton("🥇 XAUUSD REAL",callback_data="C_XAUUSD")])
    return InlineKeyboardMarkup(btns)

def mt5_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🥇 XAUUSD REAL",callback_data="C_XAUUSD")],[InlineKeyboardButton("📋 CRYPTO",callback_data="M_COINS")]])

async def start(u,c): await u.message.reply_text("🤖 PHILEDIZ FIXED\n\n/coins → BTC ETH SOL BONK PEPE etc\n/mt5 → REAL XAUUSD $4154 + TP/SL",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 CRYPTO",callback_data="M_COINS"),InlineKeyboardButton("🥇 MT5",callback_data="M_MT5")]]))
async def coins_cmd(u,c): await u.message.reply_text("📋 SELECT COIN:",reply_markup=coins_kb())
async def mt5_cmd(u,c): await u.message.reply_text("🥇 MT5 GOLD REAL:",reply_markup=mt5_kb())
async def analyze_cmd(u,c):
    if not c.args: await u.message.reply_text("Ex: /analyze BTC",reply_markup=coins_kb()); return
    await run(u,clean(c.args[0]))
async def btn(u,c):
    q=u.callback_query; await q.answer(); d=q.data
    if d=="M_COINS": await q.edit_message_text("📋 SELECT COIN:",reply_markup=coins_kb()); return
    if d=="M_MT5": await q.edit_message_text("🥇 MT5 MENU:",reply_markup=mt5_kb()); return
    if d.startswith("C_"): await q.edit_message_text(f"🔎 {d[2:]}..."); await run(q,d[2:])
async def txt(u,c):
    t=(u.message.text or "").strip()
    if len(t.split())==1:
        s=clean(t)
        if s in CRYPTO or s=="XAUUSD": await run(u,s)

async def run(upd,sym):
    from telegram import CallbackQuery
    send=upd.message.reply_text if isinstance(upd,CallbackQuery) else upd.message.reply_text
    if not isinstance(upd,CallbackQuery): await upd.message.reply_text(f"🔎 Analyzing {sym}...")
    if sym=="XAUUSD" or sym=="PAXG":
        r=get_gold()
        if not r: await send("❌ XAUUSD unavailable"); return
        await send(f"🤖 XAUUSD REAL LIVE\n\n💰 Price: {fmt(r['price'])}\n📡 {r['src']}\n\n📌 {r['dir']} Score {r['score']}\n\n💵 Entry: {fmt(r['price'])} Lev 10x\n🛑 SL: {fmt(r['sl'])}\n🎯 TP1: {fmt(r['tp1'])}\n🎯 TP2: {fmt(r['tp2'])}\n🎯 TP3: {fmt(r['tp3'])}",reply_markup=mt5_kb())
        return
    r=analyze(sym)
    if not r: await send("❌ Data unavailable",reply_markup=coins_kb()); return
    if r["dir"]!="WAIT":
        await send(f"🤖 {r['sym']}\n💰 {fmt(r['price'])}\n📊 EMA20 {fmt(r['e20'])} EMA50 {fmt(r['e50'])} RSI {r['rsi']:.1f}\n\n📌 {r['dir']} Score {r['score']}\n\n💵 Entry: {fmt(r['price'])} Lev {r['lev']}x\n🛑 SL: {fmt(r['sl'])}\n🎯 TP1: {fmt(r['tp1'])}\n🎯 TP2: {fmt(r['tp2'])}\n🎯 TP3: {fmt(r['tp3'])}",reply_markup=coins_kb())
    else:
        await send(f"🤖 {r['sym']} WAIT Score {r['score']} Price {fmt(r['price'])}",reply_markup=coins_kb())

def run_flask(): app.run(host="0.0.0.0",port=PORT)
def run_bot():
    if not BOT_TOKEN: print("No token"); return
    a=ApplicationBuilder().token(BOT_TOKEN).build()
    a.add_handler(CommandHandler("start",start))
    a.add_handler(CommandHandler("coins",coins_cmd))
    a.add_handler(CommandHandler("mt5",mt5_cmd))
    a.add_handler(CommandHandler("analyze",analyze_cmd))
    a.add_handler(CallbackQueryHandler(btn))
    a.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,txt))
    a.run_polling()

if __name__=="__main__":
    threading.Thread(target=run_flask,daemon=True).start()
    run_bot()
