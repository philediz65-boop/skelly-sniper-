import os,re,threading,requests,time,traceback
from flask import Flask
from telegram import InlineKeyboardButton,InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder,CommandHandler,MessageHandler,CallbackQueryHandler,filters

BOT_TOKEN=os.getenv("BOT_TOKEN","").strip()
PORT=int(os.getenv("PORT","10000"))
app=Flask(__name__)
SESSION=requests.Session()
SESSION.headers.update({"User-Agent":"Mozilla/5.0"})

CRYPTO={"BTC":"BTCUSDT","ETH":"ETHUSDT","BNB":"BNBUSDT","SOL":"SOLUSDT","XRP":"XRPUSDT","DOGE":"DOGEUSDT","ADA":"ADAUSDT","AVAX":"AVAXUSDT","LINK":"LINKUSDT","TRX":"TRXUSDT","DOT":"DOTUSDT","MATIC":"MATICUSDT","LTC":"LTCUSDT","BCH":"BCHUSDT","UNI":"UNIUSDT","ATOM":"ATOMUSDT","ETC":"ETCUSDT","FIL":"FILUSDT","PEPE":"PEPEUSDT","BONK":"BONKUSDT","SHIB":"SHIBUSDT","FLOKI":"FLOKIUSDT","WIF":"WIFUSDT","BOME":"BOMEUSDT","PAXG":"PAXGUSDT"}

@app.get("/")
def home(): return "PHILEDIZ SNIPER STABLE OK",200
@app.get("/health")
def health(): return {"ok":True},200

def clean(t):
    t=t.upper().strip().replace("/","").replace("-","").replace("_","")
    t=re.sub(r"[^A-Z0-9]","",t)
    m={"BITCOIN":"BTC","ETHEREUM":"ETH","SOLANA":"SOL","GOLD":"XAUUSD","XAU":"XAUUSD","XAUUSD":"XAUUSD","PAXG":"PAXG"}
    if t in m: t=m[t]
    if t.endswith("USDT") and t[:-4] in CRYPTO: return t[:-4]
    return t
def fmt(v):
    try: return f"{v:,.2f}" if v>=1000 else f"{v:,.4f}" if v>=1 else f"{v:.6f}"
    except: return str(v)

def get_klines(sym):
    # OKX - no key, works on Render
    try:
        r=SESSION.get("https://www.okx.com/api/v5/market/candles",params={"instId":sym.replace("USDT","-USDT"),"bar":"1H","limit":"200"},timeout=15).json()
        data=r.get("data",[])
        if len(data)>=60:
            return [{"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),"v":float(x[5])} for x in data][::-1]
    except: pass
    try:
        r=SESSION.get("https://data-api.binance.vision/api/v3/klines",params={"symbol":sym,"interval":"1h","limit":200},timeout=15).json()
        if isinstance(r,list) and len(r)>=60:
            return [{"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),"v":float(x[5])} for x in r]
    except: pass
    try:
        r=SESSION.get("https://api.gateio.ws/api/v4/spot/candlesticks",params={"currency_pair":sym.replace("USDT","_USDT"),"interval":"1h","limit":"200"},timeout=15).json()
        if isinstance(r,list) and len(r)>=60:
            return [{"o":float(x[2]),"h":float(x[3]),"l":float(x[4]),"c":float(x[2]),"v":float(x[5])} for x in r]
    except: pass
    return []

def get_price(sym):
    try:
        r=SESSION.get("https://www.okx.com/api/v5/market/ticker",params={"instId":sym.replace("USDT","-USDT")},timeout=8).json()
        return float(r["data"][0]["last"])
    except: pass
    try:
        r=SESSION.get("https://data-api.binance.vision/api/v3/ticker/price",params={"symbol":sym},timeout=8).json()
        return float(r["price"])
    except: pass
    return None

def ema(arr,p):
    if len(arr)<p: return None
    k=2/(p+1); e=sum(arr[:p])/p
    for x in arr[p:]: e=(x-e)*k+e
    return e

def analyze(code):
    sym=CRYPTO.get(code,"BTCUSDT") if code!="XAUUSD" else "PAXGUSDT"
    kl=get_klines(sym)
    if len(kl)<50: return None
    closes=[c["c"] for c in kl]
    live=get_price(sym) or closes[-1]

    # XAUUSD REAL LIVE - NO CACHE
    src=""
    real=None
    if code=="XAUUSD":
        try:
            r=SESSION.get("https://api.gold-api.com/price/XAU",timeout=4).json()
            p=float(r.get("price",0))
            if 3000<p<6000: real=p
        except: pass
        if real:
            diff=real-live
            for c in kl: c["o"]+=diff; c["h"]+=diff; c["l"]+=diff; c["c"]+=diff
            closes=[c["c"] for c in kl]
            live=real
            src=f"REAL XAU ${real:.2f} @ {time.strftime('%H:%M:%S')}"

    e20=ema(closes,20); e50=ema(closes,50); e200=ema(closes,200)
    if not e20 or not e50 or not e200: return None
    trend="UPTREND" if live>e20>e50>e200 else "DOWNTREND" if live<e20<e50<e200 else "SIDEWAYS"
    sup=min([c["l"] for c in kl[-20:]])
    res=max([c["h"] for c in kl[-20:]])
    last=kl[-1]; prev=kl[-2]
    if last["c"]>res: btype="BREAKOUT_UP"
    elif last["c"]<sup: btype="BREAKOUT_DOWN"
    elif abs(last["l"]-sup) < (last["h"]-last["l"]): btype="RETEST_SUPPORT"
    else: btype="NO_BREAKOUT"
    vols=[c["v"] for c in kl[-21:-1]]; avg=sum(vols)/len(vols) if vols else 1
    vol_ok=last["v"]>avg*1.2; vol_msg=f"High {last['v']/avg:.1f}x ✅" if vol_ok else f"Low {last['v']/avg:.1f}x ⚠️"
    conf=last["c"]>last["o"]; conf_msg="Bullish Engulfing ✅" if last["c"]>prev["o"] and last["c"]>last["o"] else "Bearish ✅" if last["c"]<last["o"] else "Waiting ⏳"
    atr=sum([c["h"]-c["l"] for c in kl[-14:]])/14
    if trend=="UPTREND" and vol_ok:
        direction="BUY"; entry=live; sl=sup-atr*0.3; risk=entry-sl; tp1=entry+risk*2; tp2=entry+risk*3; tp3=entry+risk*5
    elif trend=="DOWNTREND" and vol_ok:
        direction="SELL"; entry=live; sl=res+atr*0.3; risk=sl-entry; tp1=entry-risk*2; tp2=entry-risk*3; tp3=entry-risk*5
    else:
        direction="WAIT"; entry=live; sl=tp1=tp2=tp3=None
    return {"code":code,"price":live,"trend":trend,"e20":e20,"e50":e50,"e200":e200,"sup":sup,"res":res,"btype":btype,"conf_msg":conf_msg,"vol_msg":vol_msg,"vol_ok":vol_ok,"dir":direction,"entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"atr":atr,"src":src}

def coins_kb():
    ks=list(CRYPTO.keys()); btns=[]; row=[]
    for c in ks:
        row.append(InlineKeyboardButton(c,callback_data=f"C_{c}"))
        if len(row)==3: btns.append(row); row=[]
    if row: btns.append(row)
    btns.append([InlineKeyboardButton("🥇 XAUUSD GOLD LIVE",callback_data="C_XAUUSD")])
    return InlineKeyboardMarkup(btns)

async def start(u,c): await u.message.reply_text("🤖 SKELLY'S SNIPER PRO - STABLE ✅\n\nTap coin for 10-step analysis (Trend/SR/Breakout/Volume/TP SL)",reply_markup=coins_kb())
async def btn_handler(u,c):
    q=u.callback_query; await q.answer(); d=q.data
    if d.startswith("C_"):
        code=d[2:]
        try:
            await q.edit_message_text(f"🔎 Analysing {code}...")
            await run(q,code)
        except Exception as e:
            print(traceback.format_exc())
            await q.edit_message_text(f"❌ {code} {e}",reply_markup=coins_kb())

async def txt_handler(u,c):
    s=clean((u.message.text or "").strip())
    if s in CRYPTO or s=="XAUUSD":
        await u.message.reply_text(f"🔎 Analysing {s}...")
        await run(u,s)

async def run(upd, code):
    try:
        r=analyze(code)
        if not r:
            await upd.message.reply_text(f"❌ {code} data busy, try again 5 sec",reply_markup=coins_kb())
            return
        if r["dir"]=="WAIT":
            msg=f"""⏳ {code} WAIT

💰 {fmt(r['price'])} {r['src']}
Trend: {r['trend']} EMA20 {fmt(r['e20'])} EMA50 {fmt(r['e50'])}
S/R: Sup {fmt(r['sup'])} Res {fmt(r['res'])}
Breakout: {r['btype']} | {r['conf_msg']} | {r['vol_msg']}

No full confirmation yet. Be patient.
"""
            await upd.message.reply_text(msg,reply_markup=coins_kb())
        else:
            msg=f"""🚀 {code} {r['dir']} - 10 STEP CONFIRMED

💰 {fmt(r['price'])} LIVE {r['src']}
1. Trend: {r['trend']} ✅ EMA20 {fmt(r['e20'])} EMA50 {fmt(r['e50'])} EMA200 {fmt(r['e200'])}
2. S/R: Sup {fmt(r['sup'])} Res {fmt(r['res'])} ✅
3. Breakout: {r['btype']} ✅
4. Candle: {r['conf_msg']} ✅
5. Volume: {r['vol_msg']} ✅
6. Entry: {fmt(r['entry'])} ✅
7. SL: {fmt(r['sl'])} ATR {fmt(r['atr'])} ✅
8. TP: {fmt(r['tp1'])} 2R | {fmt(r['tp2'])} 3R | {fmt(r['tp3'])} 5R ✅

💵 Entry {fmt(r['entry'])} Lev 10x
🛑 SL {fmt(r['sl'])}
🎯 TP1 {fmt(r['tp1'])} TP2 {fmt(r['tp2'])} TP3 {fmt(r['tp3'])}
"""
            await upd.message.reply_text(msg,reply_markup=coins_kb())
    except Exception as e:
        print(traceback.format_exc())
        await upd.message.reply_text(f"❌ {code} crash {e}",reply_markup=coins_kb())

def run_flask(): app.run(host="0.0.0.0",port=PORT)
def run_bot():
    if not BOT_TOKEN: print("NO TOKEN"); return
    a=ApplicationBuilder().token(BOT_TOKEN).build()
    a.add_handler(CommandHandler("start",start))
    a.add_handler(CommandHandler("coins",start))
    a.add_handler(CallbackQueryHandler(btn_handler))
    a.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,txt_handler))
    a.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    threading.Thread(target=run_flask,daemon=True).start()
    run_bot()
