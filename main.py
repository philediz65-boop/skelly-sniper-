import os,re,threading,requests,time
from flask import Flask
from telegram import InlineKeyboardButton,InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder,CommandHandler,MessageHandler,CallbackQueryHandler,filters

BOT_TOKEN=os.getenv("BOT_TOKEN","").strip()
PORT=int(os.getenv("PORT","10000"))
app=Flask(__name__)
SESSION=requests.Session()
SESSION.headers.update({"User-Agent":"Mozilla/5.0"})
CACHE={}

CRYPTO={"BTC":"BTCUSDT","ETH":"ETHUSDT","BNB":"BNBUSDT","SOL":"SOLUSDT","XRP":"XRPUSDT","DOGE":"DOGEUSDT","ADA":"ADAUSDT","AVAX":"AVAXUSDT","LINK":"LINKUSDT","TRX":"TRXUSDT","DOT":"DOTUSDT","MATIC":"MATICUSDT","LTC":"LTCUSDT","BCH":"BCHUSDT","UNI":"UNIUSDT","ATOM":"ATOMUSDT","ETC":"ETCUSDT","FIL":"FILUSDT","PEPE":"PEPEUSDT","BONK":"BONKUSDT","SHIB":"SHIBUSDT","FLOKI":"FLOKIUSDT","FARTCOIN":"FARTCOINUSDT","WIF":"WIFUSDT","BABY":"BABYUSDT","BOME":"BOMEUSDT","PAXG":"PAXGUSDT"}

@app.get("/")
def home(): return "PHILEDIZ 10-STEP PLAN BOT OK",200
@app.get("/health")
def health(): return {"ok":True},200

def clean(t):
    t=t.upper().strip().replace("/","").replace("-","").replace("_","")
    t=re.sub(r"[^A-Z0-9]","",t)
    m={"BITCOIN":"BTC","ETHEREUM":"ETH","SOLANA":"SOL","GOLD":"XAUUSD","XAU":"XAUUSD","XAUUSD":"XAUUSD","PAXG":"PAXG"}
    if t in m: t=m[t]
    if t.endswith("USDT") and t[:-4] in CRYPTO: return t[:-4]
    return t
def fmt(v): return f"{v:,.2f}" if v>=1000 else f"{v:,.6f}" if v>=1 else f"{v:.4f}"

# === DATA ===
def get_klines(sym, limit=200, use_cache=True):
    if use_cache and sym in CACHE and time.time()-CACHE[sym][0]<120:
        return CACHE[sym][1]
    # OKX with volume
    try:
        inst=sym.replace("USDT","-USDT")
        r=SESSION.get("https://www.okx.com/api/v5/market/candles",params={"instId":inst,"bar":"1H","limit":str(limit)},timeout=10).json()
        data=r.get("data",[])
        if len(data)>=60:
            # OKX: [ts, o, h, l, c, vol, volCcy]
            candles=[{"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),"v":float(x[5])} for x in data]
            candles.reverse()
            if use_cache: CACHE[sym]=(time.time(),candles)
            else: return candles
            return candles
    except Exception as e:
        print(f"OKX KL FAIL {sym} {e}")
    return []

def get_price(sym):
    try:
        r=SESSION.get("https://www.okx.com/api/v5/market/ticker",params={"instId":sym.replace("USDT","-USDT")},timeout=5).json()
        return float(r["data"][0]["last"])
    except: return None

# === INDICATORS ===
def ema(arr,p):
    if len(arr)<p: return None
    k=2/(p+1); e=sum(arr[:p])/p
    for x in arr[p:]: e=(x-e)*k+e
    return e

def find_sr(candles):
    # Simple swing high/low last 50 candles
    highs=[c["h"] for c in candles[-50:]]
    lows=[c["l"] for c in candles[-50:]]
    # Resistance = max of last 20
    res=max(highs[-20:])
    sup=min(lows[-20:])
    return sup, res

def check_breakout(candles, sup, res):
    last=candles[-1]
    prev=candles[-2]
    # Breakout up
    if last["c"] > res and prev["c"] <= res:
        return "BREAKOUT_UP", res
    if last["c"] < sup and prev["c"] >= sup:
        return "BREAKOUT_DOWN", sup
    # Retest
    if abs(last["l"] - sup) < (last["h"]-last["l"])*0.3 and last["c"] > sup:
        return "RETEST_SUPPORT", sup
    if abs(last["h"] - res) < (last["h"]-last["l"])*0.3 and last["c"] < res:
        return "RETEST_RESISTANCE", res
    return "NO_BREAKOUT", None

def check_volume(candles):
    vols=[c["v"] for c in candles[-20:]]
    avg=sum(vols[:-1])/len(vols[:-1])
    last_vol=vols[-1]
    if last_vol > avg*1.5:
        return True, f"High Volume ({last_vol/avg:.1f}x avg) ✅"
    else:
        return False, f"Low Volume ({last_vol/avg:.1f}x avg) ⚠️ fake move risk"

def confirmation_candle(candles):
    last=candles[-1]
    prev=candles[-2]
    # Bullish engulfing
    if last["c"] > last["o"] and prev["c"] < prev["o"] and last["c"] > prev["o"] and last["o"] < prev["c"]:
        return True, "Bullish Engulfing ✅"
    if last["c"] < last["o"] and prev["c"] > prev["o"] and last["c"] < prev["o"] and last["o"] > prev["c"]:
        return True, "Bearish Engulfing ✅"
    if last["c"] > last["o"] and (last["h"]-last["c"]) < (last["c"]-last["o"])*0.3:
        return True, "Strong Bullish Close ✅"
    if last["c"] < last["o"] and (last["c"]-last["l"]) < (last["o"]-last["c"])*0.3:
        return True, "Strong Bearish Close ✅"
    return False, "Waiting for confirmation ⏳"

# === MAIN ANALYSIS - 10 STEPS FROM YOUR PAPER ===
def analyze_10steps(symbol_code):
    sym=CRYPTO.get(symbol_code, "BTCUSDT") if symbol_code!="XAUUSD" else "PAXGUSDT"
    kl=get_klines(sym, 200, use_cache=False)
    if len(kl)<60:
        return None
    closes=[c["c"] for c in kl]
    price=get_price(sym) or closes[-1]

    # 1. CHECK MARKET TREND
    e20=ema(closes,20); e50=ema(closes,50); e200=ema(closes,200)
    trend="UPTREND" if price>e20 and e20>e50 and e50>e200 else "DOWNTREND" if price<e20 and e20<e50 and e50<e200 else "SIDEWAYS"
    trend_ok = trend!= "SIDEWAYS"

    # 2. MARK SUPPORT & RESISTANCE
    sup, res = find_sr(kl)

    # 3. WAIT FOR CONFIRMATION CANDLE
    breakout_type, level = check_breakout(kl, sup, res)
    conf_ok, conf_msg = confirmation_candle(kl)

    # 4. CHECK VOLUME
    vol_ok, vol_msg = check_volume(kl)

    # 5,6,7 - PLAN ENTRY, SL, RISK REWARD 1:2
    atr_val = sum([c["h"]-c["l"] for c in kl[-14:]])/14
    if trend=="UPTREND" and breakout_type in ["BREAKOUT_UP","RETEST_SUPPORT"] and conf_ok and vol_ok:
        direction="BUY"
        entry=price
        sl = sup - atr_val*0.5 # logical level below support
        risk = entry - sl
        tp1 = entry + risk*2 # 2R
        tp2 = entry + risk*3
        tp3 = entry + risk*5
    elif trend=="DOWNTREND" and breakout_type in ["BREAKOUT_DOWN","RETEST_RESISTANCE"] and conf_ok and vol_ok:
        direction="SELL"
        entry=price
        sl = res + atr_val*0.5
        risk = sl - entry
        tp1 = entry - risk*2
        tp2 = entry - risk*3
        tp3 = entry - risk*5
    else:
        direction="WAIT"
        entry=price; sl=tp1=tp2=tp3=None; risk=0

    # 8. POSITION SIZE - 1-2%
    # 9,10 handled in message

    checklist = {
        "Trend Confirmed": trend_ok,
        "S/R Marked": True,
        "Volume Checked": vol_ok,
        "Entry Confirmed": conf_ok,
        "Stop Loss Set": direction!="WAIT",
        "Risk:Reward >=1:2": direction!="WAIT",
        "Stay Patient": breakout_type!="NO_BREAKOUT",
        "Follow Your Plan": direction!="WAIT" and trend_ok and vol_ok and conf_ok
    }

    return {
        "symbol":symbol_code, "price":price, "trend":trend, "e20":e20,"e50":e50,"e200":e200,
        "sup":sup,"res":res,"breakout":breakout_type,"level":level,
        "conf_msg":conf_msg,"conf_ok":conf_ok,
        "vol_msg":vol_msg,"vol_ok":vol_ok,
        "dir":direction,"entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"risk":risk,
        "checklist":checklist, "atr":atr_val
    }

def coins_kb():
    ks=list(CRYPTO.keys()); btns=[]; row=[]
    for c in ks:
        row.append(InlineKeyboardButton(c,callback_data=f"C_{c}"))
        if len(row)==3: btns.append(row); row=[]
    if row: btns.append(row)
    btns.append([InlineKeyboardButton("🥇 XAUUSD (GOLD)",callback_data="C_XAUUSD")])
    return InlineKeyboardMarkup(btns)

async def start(u,c):
    await u.message.reply_text("🤖 **PHILEDIZ 10-STEP PLAN BOT**\n\nExactly like your paper:\n1. Trend\n2. S/R\n3. Confirmation Candle\n4. Volume\n5. Entry\n6. SL\n7. 1:2 RR\n\nTap coin to analyse",reply_markup=coins_kb(),parse_mode="Markdown")

async def btn(u,c):
    q=u.callback_query; await q.answer(); d=q.data
    if d.startswith("C_"):
        code=d[2:]
        await q.edit_message_text(f"🔎 Analysing {code} with 10-step plan...")
        await run(q,code)

async def txt(u,c):
    s=clean((u.message.text or "").strip())
    if s in CRYPTO or s=="XAUUSD":
        await u.message.reply_text(f"🔎 Analysing {s}...")
        await run(u,s)

async def run(upd, code):
    r=analyze_10steps(code)
    if not r:
        await upd.message.reply_text(f"❌ {code} data busy, tap again"); return

    # Build checklist display
    chk_text=""
    for k,v in r["checklist"].items():
        chk_text+= f"{'✅' if v else '❌'} {k}\n"

    if r["dir"]=="WAIT":
        reason=[]
        if r["trend"]=="SIDEWAYS": reason.append("Market sideways, no trend")
        if not r["conf_ok"]: reason.append(f"No confirmation: {r['conf_msg']}")
        if not r["vol_ok"]: reason.append(f"{r['vol_msg']}")
        if r["breakout"]=="NO_BREAKOUT": reason.append("No breakout/retest yet")

        msg = f"""⏳ **{code} - WAIT - NO TRADE**

**1. Market Trend:** {r['trend']} { '✅' if r['trend']!='SIDEWAYS' else '❌'}
EMA20 {fmt(r['e20'])} | EMA50 {fmt(r['e50'])} | EMA200 {fmt(r['e200'])}

**2. S/R Marked:** ✅
Support: {fmt(r['sup'])}
Resistance: {fmt(r['res'])}

**3. Confirmation:** {r['conf_msg']}
Breakout: {r['breakout']}

**4. Volume:** {r['vol_msg']}

**Reasons to WAIT:**
- {chr(10)+'- '.join(reason)}

**Checklist:**
{chk_text}
"""
        await upd.message.reply_text(msg, reply_markup=coins_kb(), parse_mode="Markdown")
        return

    # BUY/SELL signal
    rr2 = abs(r['tp1']-r['entry'])/abs(r['entry']-r['sl']) if r['sl'] else 0
    msg = f"""🚀 **{code} {r['dir']} SIGNAL - 10 STEP CONFIRMED**

**1. Trend:** {r['trend']} ✅ Trade in direction of trend
**2. S/R:** Support {fmt(r['sup'])} | Resistance {fmt(r['res'])} ✅
**3. Confirmation:** {r['conf_msg']} | {r['breakout']} at {fmt(r['level']) if r['level'] else 'level'} ✅
**4. Volume:** {r['vol_msg']} ✅ High vol on breakout

**5. Entry:** {fmt(r['entry'])} - Clear entry after retest
**6. Stop Loss:** {fmt(r['sl'])} (below S/R + ATR) - Protect capital
**7. Risk:Reward 1:2+** Target {fmt(r['tp1'])} = {rr2:.1f}R ✅
   TP1 {fmt(r['tp1'])} (2R)
   TP2 {fmt(r['tp2'])} (3R)
   TP3 {fmt(r['tp3'])} (5R)

**8. Position Size:** Risk Only 1-2% Per Trade
   Risk = {fmt(abs(r['entry']-r['sl']))} | ATR {fmt(r['atr'])}

**9. Avoid Emotional:** Fear → Discipline → Success ✅
**10. Follow Plan:** Plan → Execute → Review ✅

**Checklist:**
{chk_text}
💰 Entry {fmt(r['entry'])} Lev 5x-10x
🛑 SL {fmt(r['sl'])}
🎯 TP1 {fmt(r['tp1'])} | TP2 {fmt(r['tp2'])} | TP3 {fmt(r['tp3'])}

_XAUUSD live price changes every request_
"""
    await upd.message.reply_text(msg, reply_markup=coins_kb(), parse_mode="Markdown")

def run_flask(): Flask(__name__).run(host="0.0.0.0",port=PORT) # dummy to keep old, real app defined above
def run_bot():
    if not BOT_TOKEN: return
    a=ApplicationBuilder().token(BOT_TOKEN).build()
    a.add_handler(CommandHandler("start",start))
    a.add_handler(CallbackQueryHandler(btn))
    a.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,txt))
    a.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    threading.Thread(target=lambda: app.run(host="0.0.0.0",port=PORT),daemon=True).start()
    run_bot()
