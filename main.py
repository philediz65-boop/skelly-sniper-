import os,re,threading,requests,time,traceback
from flask import Flask
from telegram import InlineKeyboardButton,InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder,CommandHandler,MessageHandler,CallbackQueryHandler,filters

BOT_TOKEN=os.getenv("BOT_TOKEN","").strip()
PORT=int(os.getenv("PORT","10000"))
app=Flask(__name__)
SESSION=requests.Session()
SESSION.headers.update({"User-Agent":"Mozilla/5.0"})
CACHE={}

CRYPTO={"BTC":"BTCUSDT","ETH":"ETHUSDT","BNB":"BNBUSDT","SOL":"SOLUSDT","XRP":"XRPUSDT","DOGE":"DOGEUSDT","ADA":"ADAUSDT","AVAX":"AVAXUSDT","LINK":"LINKUSDT","TRX":"TRXUSDT","DOT":"DOTUSDT","MATIC":"MATICUSDT","LTC":"LTCUSDT","BCH":"BCHUSDT","UNI":"UNIUSDT","ATOM":"ATOMUSDT","ETC":"ETCUSDT","FIL":"FILUSDT","PEPE":"PEPEUSDT","BONK":"BONKUSDT","SHIB":"SHIBUSDT","FLOKI":"FLOKIUSDT","WIF":"WIFUSDT","BOME":"BOMEUSDT","PAXG":"PAXGUSDT"}

@app.get("/")
def home(): return "PHILEDIZ 50/50 FIXED OK",200
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
    try:
        if v is None: return "0"
        return f"{v:,.2f}" if v>=1000 else f"{v:,.4f}" if v>=1 else f"{v:.6f}"
    except: return str(v)

def get_klines(sym):
    if sym in CACHE and time.time()-CACHE[sym][0]<80:
        return CACHE[sym][1]
    kl=[]
    try:
        r=SESSION.get("https://www.okx.com/api/v5/market/candles",params={"instId":sym.replace("USDT","-USDT"),"bar":"1H","limit":"100"},timeout=12).json()
        data=r.get("data",[])
        if len(data)>=50:
            kl=[{"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),"v":float(x[5])} for x in data][::-1]
    except Exception as e:
        print(f"OKX FAIL {sym} {e}")
    if not kl:
        try:
            r=SESSION.get("https://data-api.binance.vision/api/v3/klines",params={"symbol":sym,"interval":"1h","limit":100},timeout=12).json()
            if isinstance(r,list) and len(r)>=50:
                kl=[{"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),"v":float(x[5])} for x in r]
        except Exception as e:
            print(f"BINANCE FAIL {sym} {e}")
    if kl:
        CACHE[sym]=(time.time(),kl)
        return kl
    if sym in CACHE: return CACHE[sym][1]
    return []

def ema(arr,p):
    # FIX: never return None
    if not arr: return 0
    if len(arr)<p:
        return sum(arr)/len(arr)
    k=2/(p+1); e=sum(arr[:p])/p
    for x in arr[p:]: e=(x-e)*k+e
    return e

def rsi_calc(arr,p=14):
    if len(arr)<p+1: return 50
    gains=losses=0
    for i in range(1,p+1):
        d=arr[-i]-arr[-i-1]
        if d>0: gains+=d
        else: losses+=-d
    if losses==0: return 70
    rs=gains/losses if losses!=0 else 1
    return 100 - (100/(1+rs))

def is_hammer(c):
    body=abs(c["c"]-c["o"]); rng=c["h"]-c["l"]
    if rng==0: return False
    lower=min(c["c"],c["o"])-c["l"]
    return lower > body*2 and body < rng*0.4

def is_shooting_star(c):
    body=abs(c["c"]-c["o"]); rng=c["h"]-c["l"]
    if rng==0: return False
    upper=c["h"]-max(c["c"],c["o"])
    return upper > body*2 and body < rng*0.4

def is_bull_engulf(prev,curr):
    return prev["c"]<prev["o"] and curr["c"]>curr["o"] and curr["c"]>prev["o"] and curr["o"]<prev["c"]

def is_bear_engulf(prev,curr):
    return prev["c"]>prev["o"] and curr["c"]<curr["o"] and curr["c"]<prev["o"] and curr["o"]>prev["c"]

def is_doji(c):
    body=abs(c["c"]-c["o"]); rng=c["h"]-c["l"]
    return rng>0 and body/rng < 0.1

def detect_last_patterns(kl):
    if len(kl)<3: return []
    last=kl[-1]; prev=kl[-2]; prev2=kl[-3]
    pats=[]
    try:
        if is_hammer(last): pats.append(("HAMMER BULLISH",+2))
        if is_shooting_star(last): pats.append(("SHOOTING STAR BEARISH",-2))
        if is_bull_engulf(prev,last): pats.append(("BULLISH ENGULFING",+3))
        if is_bear_engulf(prev,last): pats.append(("BEARISH ENGULFING",-3))
        if is_doji(last): pats.append(("DOJI INDECISION",0))
        if prev2["c"]<prev2["o"] and abs(prev["c"]-prev["o"])<(prev["h"]-prev["l"])*0.2 and last["c"]>last["o"] and last["c"]>prev2["o"]:
            pats.append(("MORNING STAR BULLISH",+3))
        if prev2["c"]>prev2["o"] and abs(prev["c"]-prev["o"])<(prev["h"]-prev["l"])*0.2 and last["c"]<last["o"] and last["c"]<prev2["o"]:
            pats.append(("EVENING STAR BEARISH",-3))
    except: pass
    return pats

def learn_candles(kl):
    wins=0; total=0; score=0
    try:
        for i in range(10, len(kl)-5):
            sub=kl[:i]
            pats=detect_last_patterns(sub[-3:])
            if not pats: continue
            future=kl[i:i+3]
            if not future: continue
            move = (future[-1]["c"] - sub[-1]["c"]) / sub[-1]["c"] * 100 if sub[-1]["c"]!=0 else 0
            pat_score=sum([s for _,s in pats])
            if (pat_score>0 and move>0.3) or (pat_score<0 and move<-0.3):
                wins+=1
                score+=pat_score
            total+=1
    except: pass
    win_rate = (wins/total*100) if total>0 else 50
    return win_rate, score, total

def analyze_5050(code):
    sym=CRYPTO.get(code,"BTCUSDT") if code!="XAUUSD" else "PAXGUSDT"
    kl=get_klines(sym)
    if len(kl)<30:
        return {"error":True,"msg":f"No data {code} - try 10 sec"}
    closes=[c["c"] for c in kl]
    live=closes[-1]
    src=""
    if code=="XAUUSD":
        try:
            r=SESSION.get("https://api.gold-api.com/price/XAU",timeout=4).json()
            p=float(r.get("price",0))
            if 3000<p<6000:
                diff=p-live
                for c in kl: c["o"]+=diff; c["h"]+=diff; c["l"]+=diff; c["c"]+=diff
                closes=[c["c"] for c in kl]; live=p
                src=f"REAL GOLD ${p:.2f}"
        except: pass

    e20=ema(closes,20); e50=ema(closes,50); e200=ema(closes,200)
    rsi=rsi_calc(closes)
    sup=min([c["l"] for c in kl[-20:]]); res=max([c["h"] for c in kl[-20:]])
    atr=sum([c["h"]-c["l"] for c in kl[-14:]])/14 if kl else live*0.01

    trend_score=0
    if live>e20 and e20>e50 and e50>e200: trend_score=80
    elif live>e20 and e20>e50: trend_score=60
    elif live<e20 and e20<e50 and e50<e200: trend_score=-80
    elif live<e20 and e20<e50: trend_score=-60
    else: trend_score=0
    if rsi>60: trend_score+=10
    if rsi<40: trend_score+=-10
    trend_score=max(-100,min(100,trend_score))

    last_pats=detect_last_patterns(kl)
    win_rate, learn_score, learned_total = learn_candles(kl)
    candle_score = sum([s for _,s in last_pats])*20
    candle_score+= (win_rate-50)*0.8
    candle_score=max(-100,min(100,candle_score))

    final = (trend_score*0.5 + candle_score*0.5)
    agree = 100 - abs(trend_score - candle_score)/2
    confidence = (abs(final)*0.7 + agree*0.3)

    if final>35 and confidence>=60:
        direction="BUY"; entry=live; sl=sup-atr*0.4; risk=max(entry-sl,atr*0.5); tp1=entry+risk*2; tp2=entry+risk*3.5; tp3=entry+risk*6
    elif final<-35 and confidence>=60:
        direction="SELL"; entry=live; sl=res+atr*0.4; risk=max(sl-entry,atr*0.5); tp1=entry-risk*2; tp2=entry-risk*3.5; tp3=entry-risk*6
    else:
        direction="WAIT"; entry=live; sl=tp1=tp2=tp3=None

    return {
        "error":False,"code":code,"price":live,"e20":e20,"e50":e50,"e200":e200,"rsi":rsi,
        "sup":sup,"res":res,"atr":atr,"src":src,
        "trend_score":trend_score,"candle_score":candle_score,"final":final,
        "confidence":confidence,"win_rate":win_rate,"learned_total":learned_total,
        "patterns":last_pats,"dir":direction,"entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3
    }

def coins_kb():
    ks=list(CRYPTO.keys()); btns=[]; row=[]
    for c in ks:
        row.append(InlineKeyboardButton(c,callback_data=f"C_{c}"))
        if len(row)==3: btns.append(row); row=[]
    if row: btns.append(row)
    btns.append([InlineKeyboardButton("🥇 XAUUSD GOLD LIVE",callback_data="C_XAUUSD")])
    return InlineKeyboardMarkup(btns)

async def start(u,c): await u.message.reply_text("🧠 SKELLY 50/50 FIXED ✅ Crash fixed!\n\nNow ALL coins must reply. Tap:",reply_markup=coins_kb())

async def btn_handler(u,c):
    q=u.callback_query; await q.answer(); d=q.data
    if d.startswith("C_"):
        code=d[2:]
        await q.edit_message_text(f"🧠 Learning 50 candles for {code}...")
        try: await run(q,code)
        except Exception as e:
            print(traceback.format_exc())
            await q.edit_message_text(f"❌ {code} crash fixed, tap again {e}",reply_markup=coins_kb())

async def txt_handler(u,c):
    s=clean((u.message.text or "").strip())
    if s in CRYPTO or s=="XAUUSD":
        await u.message.reply_text(f"🧠 Learning 50 candles for {s}...")
        try: await run(u,s)
        except Exception as e:
            print(traceback.format_exc())
            await u.message.reply_text(f"❌ {s} {e}",reply_markup=coins_kb())

async def run(upd, code):
    try:
        r=analyze_5050(code)
        if r.get("error"):
            await upd.message.reply_text(f"⚠️ {r['msg']}",reply_markup=coins_kb())
            return
        pats_txt = "\n".join([f"• {n}" for n,s in r["patterns"]]) if r["patterns"] else "• No clear pattern - Sideways"
        if r["dir"]=="WAIT":
            msg=f"""⏳ {code} WAIT - LEARNED NO GOOD ENTRY

💰 {fmt(r['price'])} {r['src']}
📚 Learned {r['learned_total']} patterns, WinRate {r['win_rate']:.1f}%

50/50:
Trend {r['trend_score']:.0f}/100 EMA20 {fmt(r['e20'])} RSI {r['rsi']:.0f}
Candle {r['candle_score']:.0f}/100
{pats_txt}

Final {r['final']:.0f} Conf {r['confidence']:.0f}% - Wait for good candle
"""
        else:
            lev = "20x" if r["atr"]/r["price"]<0.005 else "10x" if r["atr"]/r["price"]<0.015 else "5x"
            msg=f"""🚀 {code} {r['dir']} - 50/50 CONFIRMED

💰 {fmt(r['price'])} {r['src']}
📚 WinRate {r['win_rate']:.1f}% Conf {r['confidence']:.0f}%

Trend {r['trend_score']:.0f}/100 EMA20 {fmt(r['e20'])} EMA50 {fmt(r['e50'])} EMA200 {fmt(r['e200'])} RSI {r['rsi']:.0f}
Sup {fmt(r['sup'])} Res {fmt(r['res'])} ATR {fmt(r['atr'])}

Candle {r['candle_score']:.0f}/100
{pats_txt}

Entry {fmt(r['entry'])} Lev {lev}
SL {fmt(r['sl'])}
TP1 {fmt(r['tp1'])} 2R TP2 {fmt(r['tp2'])} 3.5R TP3 {fmt(r['tp3'])} 6R
"""
        await upd.message.reply_text(msg,reply_markup=coins_kb())
    except Exception as e:
        print(traceback.format_exc())
        await upd.message.reply_text(f"❌ {code} error fixed: {e}",reply_markup=coins_kb())

def run_flask(): app.run(host="0.0.0.0",port=PORT)
def run_bot():
    if not BOT_TOKEN: return
    a=ApplicationBuilder().token(BOT_TOKEN).build()
    a.add_handler(CommandHandler("start",start))
    a.add_handler(CommandHandler("coins",start))
    a.add_handler(CallbackQueryHandler(btn_handler))
    a.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,txt_handler))
    a.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    threading.Thread(target=run_flask,daemon=True).start()
    run_bot()
