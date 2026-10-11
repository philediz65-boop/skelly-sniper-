import os,re,threading,requests,time,traceback,io
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
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
def home(): return "SKELLY 50/50 + PHOTO + RISK OK",200
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
        return f"{v:,.2f}" if v>=1000 else f"{v:,.4f}" if v>=1 else f"{v:.8f}"
    except: return str(v)

def get_klines(sym):
    if sym in CACHE and time.time()-CACHE[sym][0]<60:
        return CACHE[sym][1]
    kl=[]
    try:
        r=SESSION.get("https://www.okx.com/api/v5/market/candles",params={"instId":sym.replace("USDT","-USDT"),"bar":"1H","limit":"100"},timeout=12).json()
        data=r.get("data",[])
        if len(data)>=60:
            kl=[{"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),"v":float(x[5])} for x in data][::-1]
    except: pass
    if not kl:
        try:
            r=SESSION.get("https://data-api.binance.vision/api/v3/klines",params={"symbol":sym,"interval":"1h","limit":100},timeout=12).json()
            if isinstance(r,list) and len(r)>=60:
                kl=[{"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),"v":float(x[5])} for x in r]
        except: pass
    if kl:
        CACHE[sym]=(time.time(),kl)
        return kl
    if sym in CACHE: return CACHE[sym][1]
    return []

def ema(arr,p):
    if not arr: return 0
    if len(arr)<p: return sum(arr)/len(arr)
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
    if losses==0: return 75 if gains>0 else 50
    rs=gains/losses if losses!=0 else 1
    return 100 - (100/(1+rs))

def detect_patterns_scored(kl):
    if len(kl)<3: return [],0
    last=kl[-1]; prev=kl[-2]; prev2=kl[-3]
    pats=[]; score=0
    body=abs(last["c"]-last["o"]); rng=last["h"]-last["l"]
    if rng>0 and (min(last["c"],last["o"])-last["l"]) > body*2 and body < rng*0.45:
        pats.append("HAMMER BULLISH 🟢"); score+=30
    if rng>0 and (last["h"]-max(last["c"],last["o"])) > body*2 and body < rng*0.45:
        pats.append("SHOOTING STAR BEARISH 🔴"); score-=30
    if prev["c"]<prev["o"] and last["c"]>last["o"] and last["c"]>prev["o"] and last["o"]<prev["c"]:
        pats.append("BULLISH ENGULFING 🟢"); score+=40
    if prev["c"]>prev["o"] and last["c"]<last["o"] and last["c"]<prev["o"] and last["o"]>prev["c"]:
        pats.append("BEARISH ENGULFING 🔴"); score-=40
    if rng>0 and body/rng < 0.1:
        pats.append("DOJI - REVERSAL SOON ⚪")
    if prev2["c"]<prev2["o"] and last["c"]>last["o"] and last["c"]>prev2["o"]:
        pats.append("MORNING STAR BULLISH 🟢"); score+=35
    if prev2["c"]>prev2["o"] and last["c"]<last["o"] and last["c"]<prev2["o"]:
        pats.append("EVENING STAR BEARISH 🔴"); score-=35
    if last["c"]>prev["c"] and prev["c"]>prev2["c"]:
        pats.append("3 GREEN CANDLES - BULL MOMENTUM 🟢"); score+=15
    if last["c"]<prev["c"] and prev["c"]<prev2["c"]:
        pats.append("3 RED CANDLES - BEAR MOMENTUM 🔴"); score-=15
    if not pats:
        if last["c"]>last["o"]: pats.append("BULLISH CANDLE 🟢"); score+=10
        else: pats.append("BEARISH CANDLE 🔴"); score-=10
    return pats, max(-100,min(100,score))

def analyze_balanced(code):
    sym=CRYPTO.get(code,"BTCUSDT") if code!="XAUUSD" else "PAXGUSDT"
    kl=get_klines(sym)
    if len(kl)<40: return {"error":True,"msg":f"No data {code}"}
    closes=[c["c"] for c in kl]
    live=closes[-1]
    src="1H BINANCE/OKX LIVE"
    if code=="XAUUSD":
        try:
            r=SESSION.get("https://api.gold-api.com/price/XAU",timeout=4).json()
            p=float(r.get("price",0))
            if 3000<p<6000:
                diff=p-live
                for c in kl: c["o"]+=diff; c["h"]+=diff; c["l"]+=diff; c["c"]+=diff
                closes=[c["c"] for c in kl]; live=p
                src=f"REAL GOLD LIVE ${p:.2f}"
        except: pass
    e20=ema(closes,20); e50=ema(closes,50); e200=ema(closes,200)
    rsi=rsi_calc(closes)
    sup=min([c["l"] for c in kl[-20:]]); res=max([c["h"] for c in kl[-20:]])
    atr=sum([c["h"]-c["l"] for c in kl[-14:]])/14 if kl else live*0.01
    if live>e20>e50>e200: t_score=80
    elif live>e20>e50: t_score=50
    elif live>e50: t_score=20
    elif live<e20<e50<e200: t_score=-80
    elif live<e20<e50: t_score=-50
    else: t_score=-20 if live<e50 else 20
    if rsi>75: t_score-=30
    elif rsi>68: t_score-=15
    elif rsi<25: t_score+=30
    elif rsi<32: t_score+=15
    dist_res=(res-live)/live*100 if live!=0 else 0
    dist_sup=(live-sup)/live*100 if live!=0 else 0
    if dist_res<0.8: t_score-=20
    if dist_sup<0.8: t_score+=20
    t_score=max(-100,min(100,t_score))
    pats, c_score = detect_patterns_scored(kl)
    final = (t_score*0.5 + c_score*0.5)
    if final>=5:
        direction="BUY"; entry=live; sl=sup-atr*0.3; risk=max(entry-sl,atr*0.5); tp1=entry+risk*2; tp2=entry+risk*3.5; tp3=entry+risk*6
    else:
        direction="SELL"; entry=live; sl=res+atr*0.3; risk=max(sl-entry,atr*0.5); tp1=entry-risk*2; tp2=entry-risk*3.5; tp3=entry-risk*6
    atr_pct=atr/live*100 if live!=0 else 1
    if atr_pct<0.5: lev="20x-25x (Low Vol)"
    elif atr_pct<1.2: lev="10x-15x (Normal)"
    else: lev="5x-7x (High Vol)"
    conf = 60 + abs(final)*0.35
    conf = min(92, max(62, conf))
    trend_txt = "STRONG UPTREND 🚀" if t_score>60 else "UPTREND 📈" if t_score>15 else "STRONG DOWNTREND 📉" if t_score<-60 else "DOWNTREND 📉" if t_score<-15 else "SIDEWAYS ↔️"
    return {"error":False,"code":code,"price":live,"src":src,"trend":trend_txt,"e20":e20,"e50":e50,"e200":e200,"rsi":rsi,"sup":sup,"res":res,"atr":atr,"t_score":t_score,"c_score":c_score,"final":final,"pats":pats,"dir":direction,"entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"lev":lev,"conf":conf,"kl":kl}

def generate_chart_image(symbol, direction, entry, sl, tp1, tp3, kl):
    try:
        closes=[c["c"] for c in kl[-80:]]
        fig, ax=plt.subplots(figsize=(10,5.2), facecolor='white')
        ax.plot(closes, color='black', linewidth=1)
        ax.axhline(entry, color='#2962FF', linewidth=1.8)
        ax.axhline(sl, color='black', linewidth=1.2)
        ax.axhline(tp3, color='black', linewidth=1.2)
        last_x=len(closes)-1
        ax.text(last_x+0.5, entry, ' ENTRY ', backgroundcolor='#2962FF', color='white', weight='bold', fontsize=9, va='center')
        ax.text(last_x+0.5, sl, ' SL ', backgroundcolor='black', color='white', fontsize=8, va='center')
        ax.text(last_x+0.5, tp3, ' TP3 ', backgroundcolor='black', color='white', fontsize=8, va='center')
        ax.fill_between([last_x-15, last_x+1], entry*0.999, entry*1.001, color='#2962FF', alpha=0.18)
        x_arrow=last_x-7
        ax.annotate('', xy=(x_arrow+1, tp3), xytext=(x_arrow, entry), arrowprops=dict(facecolor='black', edgecolor='black', width=2.5, headwidth=10, headlength=8))
        pair=f"{symbol}USDT" if symbol!="XAUUSD" else "XAUUSD"
        lev_text="15x Safe" if symbol!="XAUUSD" else "20x Safe"
        ax.set_title(f"{pair} SMC | {direction} | Lev {lev_text} | {pair} - 1H", loc='left', fontsize=10, fontweight='bold')
        ax.grid(True, alpha=0.12)
        plt.tight_layout()
        buf=io.BytesIO()
        plt.savefig(buf, format='png', dpi=150)
        buf.seek(0)
        plt.close(fig)
        buf.name=f"{symbol}.png"
        return buf
    except Exception as e:
        print(f"chart error {e}")
        return None

def get_risk_calculator_text(entry, sl, tp1, tp2, tp3, lev_str, direction):
    try:
        lev_num=20 if "20" in lev_str else 15 if "15" in lev_str else 10 if "10" in lev_str else 7
        if direction=="BUY":
            sl_pct=(sl-entry)/entry*100*lev_num
            tp1_pct=(tp1-entry)/entry*100*lev_num
            tp2_pct=(tp2-entry)/entry*100*lev_num
            tp3_pct=(tp3-entry)/entry*100*lev_num
        else:
            sl_pct=(sl-entry)/entry*100*lev_num
            tp1_pct=(entry-tp1)/entry*100*lev_num
            tp2_pct=(entry-tp2)/entry*100*lev_num
            tp3_pct=(entry-tp3)/entry*100*lev_num
        def m(pct,bal): return bal*pct/100
        return f"""

💵 RISK CALCULATOR (Lev {lev_num}x):
⛔ SL {sl_pct:.2f}%:
 $10 -> ${m(sl_pct,10):.2f} | $100 -> ${m(sl_pct,100):.2f} | $1000 -> ${m(sl_pct,1000):.2f}
🎯 TP1 +{abs(tp1_pct):.2f}%: $100 -> +${abs(m(tp1_pct,100)):.2f} | $1000 -> +${abs(m(tp1_pct,1000)):.2f}
🎯 TP2 +{abs(tp2_pct):.2f}%: $100 -> +${abs(m(tp2_pct,100)):.2f}
🚀 TP3 +{abs(tp3_pct):.2f}% MOON: $100 -> +${abs(m(tp3_pct,100)):.2f} | $1000 -> +${abs(m(tp3_pct,1000)):.2f}
⚠️ Use 1-2% risk per trade!
"""
    except:
        return ""

def coins_kb():
    ks=list(CRYPTO.keys()); btns=[]; row=[]
    for c in ks:
        row.append(InlineKeyboardButton(c,callback_data=f"C_{c}"))
        if len(row)==3: btns.append(row); row=[]
    if row: btns.append(row)
    btns.append([InlineKeyboardButton("🥇 XAUUSD GOLD LIVE",callback_data="C_XAUUSD")])
    return InlineKeyboardMarkup(btns)

async def start(u,c):
    await u.message.reply_text("✅ 50/50 BALANCED - BUY & SELL BOTH WILL SHOW ✅\n\nTrend 50% + Candle 50% = Real BUY/SELL\n📸 Chart + Risk Calculator Added ✅\n\nTap:",reply_markup=coins_kb())

async def btn_handler(u,c):
    q=u.callback_query
    await q.answer()
    d=q.data
    if d.startswith("C_"):
        code=d[2:]
        await q.edit_message_text(f"📊 1H Balanced 50/50 Analysis for {code}...")
        try:
            await run(q,code,c)
        except Exception as e:
            print(traceback.format_exc())
            try:
                await q.edit_message_text(f"❌ {code} {e}",reply_markup=coins_kb())
            except: pass

async def txt_handler(u,c):
    s=clean((u.message.text or "").strip())
    if s in CRYPTO or s=="XAUUSD":
        await u.message.reply_text(f"📊 1H Balanced 50/50 Analysis for {s}...")
        await run(u,s,c)

async def run(upd, code, context):
    try:
        r=analyze_balanced(code)
        if r.get("error"):
            await upd.message.reply_text(f"⚠️ {r['msg']}",reply_markup=coins_kb())
            return
        pats_txt="\n".join([f"• {p}" for p in r["pats"]])
        risk_txt=get_risk_calculator_text(r["entry"], r["sl"], r["tp1"], r["tp2"], r["tp3"], r["lev"], r["dir"])
        msg=f"""{"🟢" if r['dir']=="BUY" else "🔴"} {r['code']} {r['dir']} SIGNAL - 1H TIMEFRAME

💰 Price: {fmt(r['price'])} | {r['src']}
⏰ TF: 1 HOUR | Confidence: {r['conf']:.0f}%

📊 1H 50/50 ANALYSIS:
Trend: {r['trend']} ({r['t_score']:.0f}/100)
EMA20 {fmt(r['e20'])} | EMA50 {fmt(r['e50'])} | EMA200 {fmt(r['e200'])}
RSI {r['rsi']:.0f} | ATR {fmt(r['atr'])}
Support {fmt(r['sup'])} | Resistance {fmt(r['res'])}

🕯️ CANDLE SCORE (50%): {r['c_score']:.0f}/100
{pats_txt}

⚖️ FINAL 50/50: Trend {r['t_score']:.0f} + Candle {r['c_score']:.0f} = {r['final']:.0f} → {r['dir']}

💵 PERFECT ENTRY:
Direction: {r['dir']}
Entry: {fmt(r['entry'])}
Leverage: {r['lev']}

🛑 SL: {fmt(r['sl'])}
🎯 TP1: {fmt(r['tp1'])} (2R)
🎯 TP2: {fmt(r['tp2'])} (3.5R)
🎯 TP3: {fmt(r['tp3'])} (6R)
{risk_txt}
"""
        try:
            chart_buf=generate_chart_image(r['code'], r['dir'], r['entry'], r['sl'], r['tp1'], r['tp3'], r['kl'])
            if chart_buf:
                await context.bot.send_photo(chat_id=upd.message.chat.id, photo=chart_buf, caption=msg, reply_markup=coins_kb())
                return
        except Exception as e:
            print(f"Chart send failed {e}")

        await upd.message.reply_text(msg,reply_markup=coins_kb())

    except Exception as e:
        print(traceback.format_exc())
        try:
            await upd.message.reply_text(f"❌ {code} {e}",reply_markup=coins_kb())
        except: pass

def run_flask():
    app.run(host="0.0.0.0",port=PORT)

def run_bot():
    if not BOT_TOKEN:
        print("No BOT_TOKEN")
        return
    a=ApplicationBuilder().token(BOT_TOKEN).build()
    a.add_handler(CommandHandler("start",start))
    a.add_handler(CommandHandler("coins",start))
    a.add_handler(CallbackQueryHandler(btn_handler))
    a.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,txt_handler))
    print("Bot starting...")
    a.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    threading.Thread(target=run_flask,daemon=True).start()
    run_bot()
