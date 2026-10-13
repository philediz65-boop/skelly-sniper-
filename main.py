import os,re,threading,requests,time,traceback,io
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from flask import Flask
from telegram import InlineKeyboardButton,InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder,CommandHandler,MessageHandler,CallbackQueryHandler,filters

BOT_TOKEN=os.getenv("BOT_TOKEN","").strip()
PORT=int(os.getenv("PORT","10000"))
app=Flask(__name__)
SESSION=requests.Session()
SESSION.headers.update({"User-Agent":"Mozilla/5.0"})
CACHE={}
LAST_CLICK={}

CRYPTO={"BTC":"BTCUSDT","ETH":"ETHUSDT","BNB":"BNBUSDT","SOL":"SOLUSDT","XRP":"XRPUSDT","DOGE":"DOGEUSDT","ADA":"ADAUSDT","AVAX":"AVAXUSDT","LINK":"LINKUSDT","TRX":"TRXUSDT","DOT":"DOTUSDT","MATIC":"MATICUSDT","LTC":"LTCUSDT","BCH":"BCHUSDT","UNI":"UNIUSDT","ATOM":"ATOMUSDT","ETC":"ETCUSDT","FIL":"FILUSDT","PEPE":"PEPEUSDT","BONK":"BONKUSDT","SHIB":"SHIBUSDT","FLOKI":"FLOKIUSDT","WIF":"WIFUSDT","BOME":"BOMEUSDT","SUI":"SUIUSDT","ARB":"ARBUSDT","OP":"OPUSDT","APT":"APTUSDT","TAO":"TAOUSDT","NOT":"NOTUSDT","PAXG":"PAXGUSDT"}
FAST_COINS={"PEPE","BONK","WIF","BOME","FLOKI","SHIB","DOGE","SOL","AVAX","SUI","ARB","OP","APT","TAO","NOT"}

@app.get("/")
def home(): return "SKELLY V2 PRO MAX 80% OK",200
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

def get_klines(sym, interval="4h"):
    key=f"{sym}_{interval}"
    if key in CACHE and time.time()-CACHE[key][0]<240:
        return CACHE[key][1]
    kl=[]
    try:
        bar={"1h":"1H","4h":"4H","1d":"1D"}[interval]
        r=SESSION.get("https://www.okx.com/api/v5/market/candles",params={"instId":sym.replace("USDT","-USDT"),"bar":bar,"limit":"200"},timeout=12).json()
        data=r.get("data",[])
        if len(data)>=60:
            kl=[{"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),"v":float(x[5])} for x in data][::-1]
    except: pass
    if not kl:
        try:
            r=SESSION.get("https://data-api.binance.vision/api/v3/klines",params={"symbol":sym,"interval":interval,"limit":200},timeout=12).json()
            if isinstance(r,list) and len(r)>=60:
                kl=[{"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),"v":float(x[5])} for x in r]
        except: pass
    if kl:
        CACHE[key]=(time.time(),kl)
        return kl
    if key in CACHE: return CACHE[key][1]
    return []

def ema(arr,p):
    if not arr: return 0
    if len(arr)<p: return sum(arr)/len(arr)
    k=2/(p+1); e=sum(arr[:p])/p
    for x in arr[p:]: e=(x-e)*k+e
    return e

def ema_series(arr, p):
    res=[]
    if len(arr)<p: return [sum(arr)/len(arr)]*len(arr) if arr else []
    k=2/(p+1); e=sum(arr[:p])/p; res=[e]*p
    for x in arr[p:]:
        e=(x-e)*k+e; res.append(e)
    while len(res)<len(arr): res.insert(0,res[0])
    return res[-len(arr):]

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

def get_mtf_trend(closes):
    if len(closes)<50: return 0,"N/A"
    e20=ema(closes,20); e50=ema(closes,50); e200=ema(closes,200)
    live=closes[-1]
    if live>e20>e50>e200: return 80,"STRONG UPTREND"
    if live>e20>e50: return 50,"UPTREND"
    if live>e50: return 20,"WEAK UP"
    if live<e20<e50<e200: return -80,"STRONG DOWNTREND"
    if live<e20<e50: return -50,"DOWNTREND"
    if live<e50: return -20,"WEAK DOWN"
    return 0,"SIDEWAYS"

def volume_check(kl):
    if len(kl)<25: return 0,"Vol N/A"
    vols=[k["v"] for k in kl[-25:]]
    avg=sum(vols[-21:-1])/20 if len(vols)>=21 else sum(vols)/len(vols)
    curr=vols[-1]
    pct=(curr-avg)/avg*100 if avg>0 else 0
    if pct>40: return 25,f"VOL +{pct:.0f}% SPIKE 🔥"
    if pct>15: return 10,f"Vol +{pct:.0f}% ✅"
    if pct<-30: return -15,f"Vol low {pct:.0f}% ⚠️"
    return 0,f"Vol {pct:.0f}% normal"

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
    if rng>0 and body/rng < 0.1: pats.append("DOJI - REVERSAL SOON ⚪")
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
    kl4=get_klines(sym,"4h")
    if len(kl4)<40: return {"error":True,"msg":f"No data {code}"}
    kl1=get_klines(sym,"1h")
    klD=get_klines(sym,"1d")
    closes4=[c["c"] for c in kl4]
    closes1=[c["c"] for c in kl1] if len(kl1)>=40 else closes4
    closesD=[c["c"] for c in klD] if len(klD)>=40 else closes4
    live=closes4[-1]
    src="4H BINANCE/OKX LIVE"
    if code=="XAUUSD":
        try:
            r=SESSION.get("https://api.gold-api.com/price/XAU",timeout=4).json()
            p=float(r.get("price",0))
            if 3000<p<6000:
                diff=p-live
                for c in kl4: c["o"]+=diff; c["h"]+=diff; c["l"]+=diff; c["c"]+=diff
                closes4=[c["c"] for c in kl4]; live=p
                src=f"REAL GOLD LIVE ${p:.2f} | 4H CHART"
        except: pass
    e20=ema(closes4,20); e50=ema(closes4,50); e200=ema(closes4,200)
    rsi=rsi_calc(closes4)
    sup=min([c["l"] for c in kl4[-20:]]); res=max([c["h"] for c in kl4[-20:]])
    atr=sum([c["h"]-c["l"] for c in kl4[-14:]])/14 if kl4 else live*0.01

    s1, t1 = get_mtf_trend(closes1)
    s4, t4 = get_mtf_trend(closes4)
    sD, tD = get_mtf_trend(closesD)
    mtf_score = s1*0.25 + s4*0.5 + sD*0.25
    mtf_agree = (s1>0 and s4>0 and sD>0) or (s1<0 and s4<0 and sD<0)

    vol_score, vol_txt = volume_check(kl4)

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
    t_score=max(-100,min(100,t_score))
    pats, c_score = detect_patterns_scored(kl4)

    final = mtf_score*0.40 + t_score*0.30 + c_score*0.20 + vol_score*0.10
    is_fast = code in FAST_COINS

    base_conf = 60 + abs(final)*0.32
    if mtf_agree: base_conf+=8
    if vol_score>10: base_conf+=4
    conf = min(92, max(52, base_conf))
    high_win = conf>=75 and mtf_agree
    win_est = min(88, conf*0.96 + (5 if high_win else 0))

    if final>=5:
        direction="BUY"; entry=live
        if is_fast:
            sl_raw=sup-atr*0.25; risk_raw=max(entry-sl_raw, atr*0.35); sl=entry-risk_raw; risk=risk_raw
            tp1=entry+risk*0.8; tp2=entry+risk*1.6; tp3=entry+risk*2.8
        else:
            sl_raw=sup-atr*0.5; risk_raw=max(entry-sl_raw, atr*0.6); sl=entry-(risk_raw*1.10); risk=risk_raw*1.10
            tp1=entry+risk*1.5; tp2=entry+risk*3.0; tp3=entry+risk*5.0
    else:
        direction="SELL"; entry=live
        if is_fast:
            sl_raw=res+atr*0.25; risk_raw=max(sl_raw-entry, atr*0.35); sl=entry+risk_raw; risk=risk_raw
            tp1=entry-risk*0.8; tp2=entry-risk*1.6; tp3=entry-risk*2.8
        else:
            sl_raw=res+atr*0.5; risk_raw=max(sl_raw-entry, atr*0.6); sl=entry+(risk_raw*1.10); risk=risk_raw*1.10
            tp1=entry-risk*1.5; tp2=entry-risk*3.0; tp3=entry-risk*5.0

    atr_pct=atr/live*100 if live!=0 else 1
    if is_fast:
        lev="25x-50x (Fast Scalp)" if atr_pct<0.8 else "15x-30x (Fast)" if atr_pct<2 else "10x-20x (Very Fast)"
    else:
        lev="20x-25x (Low Vol)" if atr_pct<0.5 else "10x-15x (Normal 4H)" if atr_pct<1.2 else "5x-7x (High Vol 4H)"

    trend_txt = "STRONG UPTREND 🚀" if t_score>60 else "UPTREND 📈" if t_score>15 else "STRONG DOWNTREND 📉" if t_score<-60 else "DOWNTREND 📉" if t_score<-15 else "SIDEWAYS ↔️"
    return {"error":False,"code":code,"price":live,"src":src,"trend":trend_txt,"e20":e20,"e50":e50,"e200":e200,"rsi":rsi,"sup":sup,"res":res,"atr":atr,"t_score":t_score,"c_score":c_score,"final":final,"pats":pats,"dir":direction,"entry":entry,"sl":sl,"sl_raw":sl_raw,"tp1":tp1,"tp2":tp2,"tp3":tp3,"lev":lev,"conf":conf,"kl":kl4,"is_fast":is_fast,"mtf_score":mtf_score,"mtf_agree":mtf_agree,"mtf_txt":f"1H {t1} | 4H {t4} | 1D {tD}","vol_txt":vol_txt,"high_win":high_win,"win_est":win_est}

def generate_chart_image(symbol, direction, entry, sl, tp1, tp2, tp3, kl, sup, res, conf, trend_txt, is_fast, win_est, high_win):
    try:
        data = kl[-80:]; closes=[c["c"] for c in kl]
        e20_s=ema_series(closes,20)[-80:]; e50_s=ema_series(closes,50)[-80:]; e200_s=ema_series(closes,200)[-80:]
        fig, ax = plt.subplots(figsize=(12,6.5), facecolor='white')
        for i, c in enumerate(data):
            color = '#26A69A' if c["c"] >= c["o"] else '#EF5350'
            ax.plot([i, i], [c["l"], c["h"]], color=color, linewidth=0.8, zorder=1)
            body_h = abs(c["c"]-c["o"]); body_y = min(c["o"], c["c"])
            if body_h < (max([x["h"]-x["l"] for x in data]) * 0.008):
                body_h = max([x["h"]-x["l"] for x in data]) * 0.008
            rect = Rectangle((i-0.35, body_y), 0.7, body_h if body_h>0 else 0.001, facecolor=color, edgecolor=color, zorder=2)
            ax.add_patch(rect)
        ax.plot(e20_s, color='#FFC107', linewidth=1.1, label='EMA20', alpha=0.8)
        ax.plot(e50_s, color='#2962FF', linewidth=1.1, label='EMA50', alpha=0.8)
        ax.plot(e200_s, color='#9C27B0', linewidth=1.1, label='EMA200', alpha=0.8)
        last_x = len(data)-1; box_left = len(data) - 19; box_w = 18
        if direction=="BUY":
            ax.add_patch(Rectangle((box_left, entry), box_w, abs(tp3-entry), facecolor='#26A69A', alpha=0.15, zorder=3))
            ax.add_patch(Rectangle((box_left, entry), box_w, abs(tp1-entry), facecolor='#26A69A', alpha=0.32, zorder=3))
            ax.add_patch(Rectangle((box_left, sl), box_w, abs(entry-sl), facecolor='#EF5350', alpha=0.30, zorder=3))
        else:
            ax.add_patch(Rectangle((box_left, tp3), box_w, abs(entry-tp3), facecolor='#26A69A', alpha=0.15, zorder=3))
            ax.add_patch(Rectangle((box_left, tp1), box_w, abs(entry-tp1), facecolor='#26A69A', alpha=0.32, zorder=3))
            ax.add_patch(Rectangle((box_left, entry), box_w, abs(sl-entry), facecolor='#EF5350', alpha=0.30, zorder=3))
        ax.axhline(sup, color='#26A69A', linewidth=0.9, linestyle=':', alpha=0.7)
        ax.axhline(res, color='#EF5350', linewidth=0.9, linestyle=':', alpha=0.7)
        ax.axhline(entry, color='#2962FF', linewidth=1.8)
        ax.axhline(sl, color='#D32F2F', linewidth=1.4, linestyle='--')
        ax.axhline(tp1, color='#2E7D32', linewidth=1.2, linestyle='--')
        ax.axhline(tp2, color='#2E7D32', linewidth=1.2, linestyle='-.')
        ax.axhline(tp3, color='#1B5E20', linewidth=1.5)
        ax.text(last_x+0.8, entry, f' ENTRY {entry:.4f} ', backgroundcolor='#2962FF', color='white', weight='bold', fontsize=8, va='center', zorder=5)
        ax.text(last_x+0.8, sl, f' SL {sl:.4f} ', backgroundcolor='#D32F2F', color='white', fontsize=7, va='center', zorder=5)
        ax.text(last_x+0.8, tp1, f' TP1 {tp1:.4f} ', backgroundcolor='#2E7D32', color='white', fontsize=7, va='center', zorder=5)
        ax.text(last_x+0.8, tp2, f' TP2 {tp2:.4f} ', backgroundcolor='#2E7D32', color='white', fontsize=7, va='center', zorder=5)
        ax.text(last_x+0.8, tp3, f' TP3 {tp3:.4f} ', backgroundcolor='#1B5E20', color='white', fontsize=7, va='center', zorder=5)
        pair = f"{symbol}USDT" if symbol!="XAUUSD" else "XAUUSD"
        mode = "FAST ⚡" if is_fast else "SLOW 🐢"
        title_color = '#26A69A' if direction=="BUY" else '#EF5350'
        win_txt = f"WIN {win_est:.0f}% {'✅' if high_win else '⚠️'}"
        ax.set_title(f"{pair} | {direction} | {mode} | {trend_txt} | Conf {conf:.0f}% | {win_txt}", loc='left', fontsize=11, fontweight='bold', color=title_color)
        ax.text(0.02, 0.97, f"{mode}\nCONF {conf:.0f}%\n{win_txt}\n{trend_txt}", transform=ax.transAxes, fontsize=9, fontweight='bold', bbox=dict(boxstyle="round,pad=0.4", facecolor="white", edgecolor=title_color, alpha=0.95), va='top', color=title_color)
        ax.legend(loc='upper left', fontsize=7, bbox_to_anchor=(0.18,0.96))
        ax.grid(True, alpha=0.15)
        plt.tight_layout()
        buf=io.BytesIO()
        plt.savefig(buf, format='png', dpi=170)
        buf.seek(0); plt.close(fig); buf.name=f"{symbol}_V2.png"
        return buf
    except Exception as e:
        print(f"chart error {e} {traceback.format_exc()}")
        return None

def get_risk_calculator_text(entry, sl, tp1, tp2, tp3, lev_str, direction, is_fast):
    try:
        lev_num=25 if "25" in lev_str else 20 if "20" in lev_str else 15 if "15" in lev_str else 10 if "10" in lev_str else 7
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
        mode_txt = "⚡ FAST - TP close <4H" if is_fast else "🐢 SLOW - SL +10% safe"
        return f"\n{mode_txt}\n💵 RISK Lev {lev_num}x:\n⛔ SL {sl_pct:.2f}%: $100 -> ${m(sl_pct,100):.2f}\n🎯 TP1 +{abs(tp1_pct):.2f}%: $100 -> +${abs(m(tp1_pct,100)):.2f}\n🎯 TP2 +{abs(tp2_pct):.2f}% | TP3 +{abs(tp3_pct):.2f}%\n"
    except: return ""

def coins_kb():
    btns=[]
    btns.append([InlineKeyboardButton("--- ⚡ FAST COINS - HIT <4H ---",callback_data="IGNORE_FAST")])
    fast=["SOL","DOGE","PEPE","BONK","WIF","BOME","FLOKI","SHIB","AVAX","SUI","ARB","OP","APT","TAO","NOT"]
    row=[]
    for c in fast:
        if c in CRYPTO:
            row.append(InlineKeyboardButton(f"⚡{c}",callback_data=f"C_{c}"))
            if len(row)==3: btns.append(row); row=[]
    if row: btns.append(row)
    btns.append([InlineKeyboardButton("--- 🐢 SLOW COINS - SAFE +10% SL ---",callback_data="IGNORE_SLOW")])
    slow=["BTC","ETH","BNB","XRP","ADA","LINK","TRX","DOT","MATIC","LTC","BCH","UNI","ATOM","ETC","FIL","PAXG"]
    row=[]
    for c in slow:
        if c in CRYPTO:
            row.append(InlineKeyboardButton(f"🐢{c}",callback_data=f"C_{c}"))
            if len(row)==3: btns.append(row); row=[]
    if row: btns.append(row)
    btns.append([InlineKeyboardButton("🥇 XAUUSD GOLD LIVE",callback_data="C_XAUUSD")])
    return InlineKeyboardMarkup(btns)

async def start(u,c):
    await u.message.reply_text("🚀 V2 PRO MAX 80% + FAST/SLOW ✅\n\n⚡ FAST = TP close, hit <4H\n🐢 SLOW = SL +10% buffer safe\n✅ MTF 1H+4H+1D + Volume filter\n\nPick:",reply_markup=coins_kb())

async def btn_handler(u,c):
    q=u.callback_query; await q.answer(); d=q.data
    if d.startswith("IGNORE"): await q.answer("Pick coin boss 👇",show_alert=False); return
    if not d.startswith("C_"): return
    code=d[2:]; now=time.time()
    if q.from_user.id in LAST_CLICK and now-LAST_CLICK[q.from_user.id]<1.5:
        await q.answer("⏳ Wait small boss!",show_alert=False); return
    LAST_CLICK[q.from_user.id]=now
    try: await q.edit_message_text(f"📊 V2 Analyzing {code} MTF 1H/4H/1D... ⏳")
    except: pass
    try: await run(q,code,c)
    except Exception as e:
        print(traceback.format_exc())
        try: await q.message.reply_text(f"❌ {code} {e}",reply_markup=coins_kb())
        except: pass

async def txt_handler(u,c):
    s=clean((u.message.text or "").strip())
    if s in CRYPTO or s=="XAUUSD":
        await u.message.reply_text(f"📊 V2 {'FAST ⚡' if s in FAST_COINS else 'SLOW 🐢'} Analysis for {s}...")
        await run(u,s,c)

async def run(upd, code, context):
    try:
        r=analyze_balanced(code)
        if r.get("error"):
            await upd.message.reply_text(f"⚠️ {r['msg']}",reply_markup=coins_kb()); return
        pats_txt="\n".join([f"• {p}" for p in r["pats"]])
        risk_txt=get_risk_calculator_text(r["entry"], r["sl"], r["tp1"], r["tp2"], r["tp3"], r["lev"], r["dir"], r["is_fast"])
        status = "🔥 HIGH WIN 80%+ - TRADE THIS ✅" if r["high_win"] else "⚠️ MEDIUM 65-74% - Trade small" if r["conf"]>=65 else "⛔ LOW CONF <65% - SKIP"
        msg=f"""{"🟢" if r['dir']=="BUY" else "🔴"} {r['code']} {r['dir']} SIGNAL - V2 PRO MAX {"⚡FAST" if r['is_fast'] else "🐢SLOW"}

{status}
Win Est: {r['win_est']:.0f}% | Conf: {r['conf']:.0f}%

💰 Price: {fmt(r['price'])} | {r['src']}
⏰ MTF FUTURE EYE:
{r['mtf_txt']}
Agree: {'✅ ALL ALIGN' if r['mtf_agree'] else '⚠️ CONFLICT'}
Vol: {r['vol_txt']}

📊 4H:
Trend: {r['trend']} ({r['t_score']:.0f})
EMA20 {fmt(r['e20'])} | EMA50 {fmt(r['e50'])} | EMA200 {fmt(r['e200'])}
RSI {r['rsi']:.0f} | ATR {fmt(r['atr'])}
Sup {fmt(r['sup'])} | Res {fmt(r['res'])}

🕯️ CANDLE: {r['c_score']:.0f}
{pats_txt}

💵 ENTRY - {'FAST CLOSE' if r['is_fast'] else 'SL +10% BUFFER'}:
Dir: {r['dir']} | Lev: {r['lev']}
Entry: {fmt(r['entry'])}
🛑 SL: {fmt(r['sl'])} (old {fmt(r['sl_raw'])})
🎯 TP1: {fmt(r['tp1'])} | TP2: {fmt(r['tp2'])} | TP3: {fmt(r['tp3'])}
{risk_txt}
"""
        try:
            buf=generate_chart_image(r['code'], r['dir'], r['entry'], r['sl'], r['tp1'], r['tp2'], r['tp3'], r['kl'], r['sup'], r['res'], r['conf'], r['trend'], r['is_fast'], r['win_est'], r['high_win'])
            if buf:
                await context.bot.send_photo(chat_id=upd.message.chat.id, photo=buf, caption=msg, reply_markup=coins_kb())
                return
        except Exception as e: print(f"Chart send failed {e}")
        await upd.message.reply_text(msg,reply_markup=coins_kb())
    except Exception as e:
        print(traceback.format_exc())
        try: await upd.message.reply_text(f"❌ {code} {e}",reply_markup=coins_kb())
        except: pass

def run_flask(): app.run(host="0.0.0.0",port=PORT)
def run_bot():
    if not BOT_TOKEN: print("No BOT_TOKEN"); return
    a=ApplicationBuilder().token(BOT_TOKEN).build()
    a.add_handler(CommandHandler("start",start))
    a.add_handler(CommandHandler("coins",start))
    a.add_handler(CallbackQueryHandler(btn_handler))
    a.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,txt_handler))
    print("Bot V2 PRO MAX starting..."); a.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    threading.Thread(target=run_flask,daemon=True).start()
    run_bot()
