import os,re,threading,requests,time,traceback,io,json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from flask import Flask
from telegram import InlineKeyboardButton,InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder,CommandHandler,MessageHandler,CallbackQueryHandler,filters
from datetime import datetime, date

BOT_TOKEN=os.getenv("BOT_TOKEN","").strip()
PORT=int(os.getenv("PORT","10000"))
app=Flask(__name__)
SESSION=requests.Session()
SESSION.headers.update({"User-Agent":"Mozilla/5.0"})
CACHE={}; LAST_CLICK={}
ACTIVE_FILE="/tmp/active_trade_v4.json"; DAILY_FILE="/tmp/daily_stats_v4.json"; CHAT_FILE="/tmp/last_chat_id.json"

def load_json(p,d):
    try:
        if os.path.exists(p):
            with open(p,'r') as f: return json.load(f)
    except: pass
    return d
def save_json(p,data):
    try:
        with open(p,'w') as f: json.dump(f,data)
    except: pass
def get_daily():
    d=load_json(DAILY_FILE,{}); today=str(date.today())
    if d.get("date")!=today: d={"date":today,"wins":0,"losses":0,"trades":0,"pnl":0.0,"history":[]}; save_json(DAILY_FILE,d)
    return d
def update_daily(result,pnl,coin=""):
    d=get_daily(); d["trades"]+=1
    if result=="WIN": d["wins"]+=1
    else: d["losses"]+=1
    d["pnl"]+=pnl; d["history"].append({"time":str(datetime.now())[:16],"coin":coin,"result":result,"pnl":pnl}); save_json(DAILY_FILE,d); return d
def get_active(): return load_json(ACTIVE_FILE,{})
def set_active(data): save_json(ACTIVE_FILE,data)
def clear_active(): save_json(ACTIVE_FILE,{})
def save_chat_id(cid): save_json(CHAT_FILE,{"chat_id":cid})
def get_chat_id(): return load_json(CHAT_FILE,{}).get("chat_id")
def send_telegram_alert(text):
    cid=get_chat_id()
    if not cid or not BOT_TOKEN: return
    try: SESSION.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",json={"chat_id":cid,"text":text},timeout=5)
    except: pass

CRYPTO={"BTC":"BTCUSDT","ETH":"ETHUSDT","BNB":"BNBUSDT","SOL":"SOLUSDT","XRP":"XRPUSDT","DOGE":"DOGEUSDT","ADA":"ADAUSDT","AVAX":"AVAXUSDT","LINK":"LINKUSDT","TRX":"TRXUSDT","DOT":"DOTUSDT","MATIC":"MATICUSDT","LTC":"LTCUSDT","BCH":"BCHUSDT","UNI":"UNIUSDT","ATOM":"ATOMUSDT","ETC":"ETCUSDT","FIL":"FILUSDT","PEPE":"PEPEUSDT","BONK":"BONKUSDT","SHIB":"SHIBUSDT","FLOKI":"FLOKIUSDT","WIF":"WIFUSDT","BOME":"BOMEUSDT","SUI":"SUIUSDT","ARB":"ARBUSDT","OP":"OPUSDT","APT":"APTUSDT","TAO":"TAOUSDT","NOT":"NOTUSDT","PAXG":"PAXGUSDT"}
FAST_COINS={"PEPE","BONK","WIF","BOME","FLOKI","SHIB","DOGE","SOL","AVAX","SUI","ARB","OP","APT","TAO","NOT"}

@app.get("/")
def home(): return "SKELLY V4 MASTER FOCUS FINAL - ALL FEATURES + MASTER OK",200
@app.get("/health")
def health(): return {"ok":True},200

def clean(t):
    t=t.upper().strip().replace("/","").replace("-","").replace("_",""); t=re.sub(r"[^A-Z0-9]","",t)
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
    if key in CACHE and time.time()-CACHE[key][0]<180: return CACHE[key][1]
    kl=[]
    try:
        bar_map={"15m":"15m","1h":"1H","4h":"4H","1d":"1D"}
        r=SESSION.get("https://www.okx.com/api/v5/market/candles",params={"instId":sym.replace("USDT","-USDT"),"bar":bar_map.get(interval,"4H"),"limit":"200"},timeout=10).json()
        data=r.get("data",[])
        if len(data)>=50: kl=[{"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),"v":float(x[5])} for x in data][::-1]
    except: pass
    if not kl:
        try:
            r=SESSION.get("https://data-api.binance.vision/api/v3/klines",params={"symbol":sym,"interval":interval,"limit":200},timeout=10).json()
            if isinstance(r,list) and len(r)>=50: kl=[{"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),"v":float(x[5])} for x in r]
        except: pass
    if kl: CACHE[key]=(time.time(),kl); return kl
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
def adx_calc(kl, period=14):
    try:
        if len(kl)<period*2: return 15
        highs=[k["h"] for k in kl]; lows=[k["l"] for k in kl]; closes=[k["c"] for k in kl]
        tr=[]; plus_dm=[]; minus_dm=[]
        for i in range(1,len(kl)):
            hl=highs[i]-lows[i]; hc=abs(highs[i]-closes[i-1]); lc=abs(lows[i]-closes[i-1])
            tr.append(max(hl,hc,lc))
            up=highs[i]-highs[i-1]; down=lows[i-1]-lows[i]
            plus_dm.append(up if up>down and up>0 else 0)
            minus_dm.append(down if down>up and down>0 else 0)
        atr=sum(tr[-period:])/period
        plus_di=100*(sum(plus_dm[-period:])/period)/atr if atr!=0 else 0
        minus_di=100*(sum(minus_dm[-period:])/period)/atr if atr!=0 else 0
        dx=100*abs(plus_di-minus_di)/(plus_di+minus_di) if (plus_di+minus_di)!=0 else 0
        return dx
    except: return 18
def get_mtf_trend(closes):
    if len(closes)<50: return 0,"N/A"
    e20=ema(closes,20); e50=ema(closes,50); e200=ema(closes,200); live=closes[-1]
    if live>e20>e50>e200: return 80,"STRONG UPTREND"
    if live>e20>e50: return 50,"UPTREND"
    if live>e50: return 20,"WEAK UP"
    if live<e20<e50<e200: return -80,"STRONG DOWNTREND"
    if live<e20<e50: return -50,"DOWNTREND"
    if live<e50: return -20,"WEAK DOWN"
    return 0,"SIDEWAYS"
def volume_check(kl):
    if len(kl)<25: return 0,"Vol N/A"
    vols=[k["v"] for k in kl[-25:]]; avg=sum(vols[-21:-1])/20 if len(vols)>=21 else sum(vols)/len(vols)
    curr=vols[-1]; pct=(curr-avg)/avg*100 if avg>0 else 0
    if pct>40: return 25,f"VOL +{pct:.0f}% SPIKE 🔥"
    if pct>15: return 10,f"Vol +{pct:.0f}% ✅"
    if pct<-50: return -25,f"Vol low {pct:.0f}% ❌ NO TRADE"
    if pct<-25: return -15,f"Vol low {pct:.0f}% ⚠️ LOW"
    return 0,f"Vol {pct:.0f}% normal"
def detect_patterns_scored(kl):
    if len(kl)<3: return [],0
    last=kl[-1]; prev=kl[-2]; prev2=kl[-3]; pats=[]; score=0
    body=abs(last["c"]-last["o"]); rng=last["h"]-last["l"]
    if rng>0 and (min(last["c"],last["o"])-last["l"]) > body*2 and body < rng*0.45: pats.append("HAMMER BULLISH 🟢"); score+=30
    if rng>0 and (last["h"]-max(last["c"],last["o"])) > body*2 and body < rng*0.45: pats.append("SHOOTING STAR BEARISH 🔴"); score-=30
    if prev["c"]<prev["o"] and last["c"]>last["o"] and last["c"]>prev["o"] and last["o"]<prev["c"]: pats.append("BULLISH ENGULFING 🟢"); score+=40
    if prev["c"]>prev["o"] and last["c"]<last["o"] and last["c"]<prev["o"] and last["o"]>prev["c"]: pats.append("BEARISH ENGULFING 🔴"); score-=40
    if rng>0 and body/rng < 0.1: pats.append("DOJI - REVERSAL SOON ⚪")
    if prev2["c"]<prev2["o"] and last["c"]>last["o"] and last["c"]>prev2["o"]: pats.append("MORNING STAR BULLISH 🟢"); score+=35
    if prev2["c"]>prev2["o"] and last["c"]<last["o"] and last["c"]<prev2["o"]: pats.append("EVENING STAR BEARISH 🔴"); score-=35
    if last["c"]>prev["c"] and prev["c"]>prev2["c"]: pats.append("3 GREEN CANDLES - BULL MOMENTUM 🟢"); score+=15
    if last["c"]<prev["c"] and prev["c"]<prev2["c"]: pats.append("3 RED CANDLES - BEAR MOMENTUM 🔴"); score-=15
    if not pats:
        if last["c"]>last["o"]: pats.append("BULLISH CANDLE 🟢"); score+=10
        else: pats.append("BEARISH CANDLE 🔴"); score-=10
    return pats, max(-100,min(100,score))

def analyze_balanced(code, btc_trend_score=0, use_15m_fallback=False):
    sym=CRYPTO.get(code,"BTCUSDT") if code!="XAUUSD" else "PAXGUSDT"
    kl4=get_klines(sym,"4h")
    if len(kl4)<40: return {"error":True,"msg":f"No data {code}"}
    kl1=get_klines(sym,"1h"); klD=get_klines(sym,"1d"); kl15=get_klines(sym,"15m") if use_15m_fallback else []
    closes4=[c["c"] for c in kl4]; closes1=[c["c"] for c in kl1] if len(kl1)>=40 else closes4; closesD=[c["c"] for c in klD] if len(klD)>=40 else closes4
    live=closes4[-1]; src="4H BINANCE/OKX LIVE"
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
    rsi=rsi_calc(closes4); sup=min([c["l"] for c in kl4[-20:]]); res=max([c["h"] for c in kl4[-20:]])
    atr=sum([c["h"]-c["l"] for c in kl4[-14:]])/14 if kl4 else live*0.01; adx=adx_calc(kl4)
    s1, t1 = get_mtf_trend(closes1); s4, t4 = get_mtf_trend(closes4); sD, tD = get_mtf_trend(closesD)
    mtf_score = s1*0.25 + s4*0.5 + sD*0.25; mtf_agree = (s1>0 and s4>0 and sD>0) or (s1<0 and s4<0 and sD<0)
    vol_score, vol_txt = volume_check(kl4)
    scalp_mode=False
    if vol_score<=-15 and len(kl15)>=40 and use_15m_fallback:
        vol15, txt15 = volume_check(kl15)
        if vol15>10:
            scalp_mode=True; vol_score=vol15; vol_txt=f"15M {txt15} (4H low, using 15M ⚡)"
            closes4=[c["c"] for c in kl15[-80:]]; live=closes4[-1]; src="15M SCALP MODE (4H low vol)"
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
    pats, c_score = detect_patterns_scored(kl4 if not scalp_mode else kl15)
    recent_high=max([c["h"] for c in kl4[-10:]]); recent_low=min([c["l"] for c in kl4[-10:]])
    liquidity_txt=""
    if live > recent_high*0.998: liquidity_txt=f"⚠️ Liquidity sweep above {fmt(recent_high)} - possible fakeout"
    elif live < recent_low*1.002: liquidity_txt=f"⚠️ Liquidity sweep below {fmt(recent_low)} - possible fakeout"
    else: liquidity_txt=f"Liq above {fmt(recent_high)} | below {fmt(recent_low)}"
    final = mtf_score*0.35 + t_score*0.25 + c_score*0.20 + vol_score*0.10 + (adx-25)*0.3
    is_fast = code in FAST_COINS or scalp_mode
    base_conf = 60 + abs(final)*0.32
    if mtf_agree: base_conf+=8
    if vol_score>10: base_conf+=4
    if adx>25: base_conf+=5
    if adx<18: base_conf-=10
    conf = min(93, max(50, base_conf)); high_win = conf>=75 and mtf_agree and adx>20; win_est = min(89, conf*0.96 + (5 if high_win else 0))
    pats_str=" ".join(pats)
    if vol_score<=-15: high_win=False; conf=min(conf,68); win_est=min(win_est,68)
    if vol_score<=-25: high_win=False; conf=min(conf,62); win_est=min(win_est,62)
    if "3 GREEN" in pats_str and final<0: high_win=False; conf=max(50,conf-8); win_est=max(50,win_est-8)
    if "3 RED" in pats_str and final>0: high_win=False; conf=max(50,conf-8); win_est=max(50,win_est-8)
    if adx<18: high_win=False; conf=min(conf,65); win_est=min(win_est,65)
    btc_txt=""
    if code!="BTC" and btc_trend_score!=0:
        if btc_trend_score<-30 and final>10: btc_txt=f"⚠️ BTC DOWN ({btc_trend_score}) vs {code} BUY = CONFLICT - Risky"; high_win=False; conf=max(50,conf-10); win_est=max(50,win_est-10)
        elif btc_trend_score>30 and final<-10: btc_txt=f"⚠️ BTC UP ({btc_trend_score}) vs {code} SELL = CONFLICT - Risky"; high_win=False; conf=max(50,conf-10); win_est=max(50,win_est-10)
        else: btc_txt=f"✅ BTC {btc_trend_score:+.0f} aligns with {code}"
    if final>=5:
        direction="BUY"; entry=live
        if is_fast: sl_raw=sup-atr*0.25; risk_raw=max(entry-sl_raw, atr*0.35); sl=entry-risk_raw; risk=risk_raw; tp1=entry+risk*0.8; tp2=entry+risk*1.6; tp3=entry+risk*2.8
        else: sl_raw=sup-atr*0.5; risk_raw=max(entry-sl_raw, atr*0.6); sl=entry-(risk_raw*1.10); risk=risk_raw*1.10; tp1=entry+risk*1.5; tp2=entry+risk*3.0; tp3=entry+risk*5.0
    else:
        direction="SELL"; entry=live
        if is_fast: sl_raw=res+atr*0.25; risk_raw=max(sl_raw-entry, atr*0.35); sl=entry+risk_raw; risk=risk_raw; tp1=entry-risk*0.8; tp2=entry-risk*1.6; tp3=entry-risk*2.8
        else: sl_raw=res+atr*0.5; risk_raw=max(sl_raw-entry, atr*0.6); sl=entry+(risk_raw*1.10); risk=risk_raw*1.10; tp1=entry-risk*1.5; tp2=entry-risk*3.0; tp3=entry-risk*5.0
    atr_pct=atr/live*100 if live!=0 else 1
    if is_fast: lev="25x-50x (Fast Scalp)" if atr_pct<0.8 else "15x-30x (Fast)" if atr_pct<2 else "10x-20x (Very Fast)"
    else: lev="20x-25x (Low Vol)" if atr_pct<0.5 else "10x-15x (Normal 4H)" if atr_pct<1.2 else "5x-7x (High Vol 4H)"
    trend_txt = "STRONG UPTREND 🚀" if t_score>60 else "UPTREND 📈" if t_score>15 else "STRONG DOWNTREND 📉" if t_score<-60 else "DOWNTREND 📉" if t_score<-15 else "SIDEWAYS ↔️"
    return {"error":False,"code":code,"price":live,"src":src,"trend":trend_txt,"e20":e20,"e50":e50,"e200":e200,"rsi":rsi,"sup":sup,"res":res,"atr":atr,"t_score":t_score,"c_score":c_score,"final":final,"pats":pats,"dir":direction,"entry":entry,"sl":sl,"sl_raw":sl_raw,"tp1":tp1,"tp2":tp2,"tp3":tp3,"lev":lev,"conf":conf,"kl":kl4 if not scalp_mode else kl15,"is_fast":is_fast,"mtf_score":mtf_score,"mtf_agree":mtf_agree,"mtf_txt":f"1H {t1} | 4H {t4} | 1D {tD}","vol_txt":vol_txt,"vol_score":vol_score,"high_win":high_win,"win_est":win_est,"adx":adx,"btc_txt":btc_txt,"liq_txt":liquidity_txt,"scalp_mode":scalp_mode}

def get_btc_trend():
    try:
        kl=get_klines("BTCUSDT","4h")
        if not kl: return 0
        closes=[c["c"] for c in kl]
        s,_=get_mtf_trend(closes)
        return s
    except: return 0

def scan_best_coins():
    btc_score=get_btc_trend(); results=[]
    for code in CRYPTO.keys():
        if code=="XAUUSD": continue
        try:
            r=analyze_balanced(code, btc_trend_score=btc_score, use_15m_fallback=True)
            if not r.get("error"): results.append(r)
            time.sleep(0.25)
        except: pass
    results_sorted=sorted(results, key=lambda x: (x["win_est"], x["vol_score"]), reverse=True)
    return results_sorted[:5], btc_score

def generate_chart_image(symbol, direction, entry, sl, tp1, tp2, tp3, kl, sup, res, conf, trend_txt, is_fast, win_est, high_win):
    try:
        data = kl[-80:]; closes=[c["c"] for c in kl]
        e20_s=ema_series(closes,20)[-80:]; e50_s=ema_series(closes,50)[-80:]; e200_s=ema_series(closes,200)[-80:]
        fig, ax = plt.subplots(figsize=(12,6.5), facecolor='white')
        for i, c in enumerate(data):
            color = '#26A69A' if c["c"] >= c["o"] else '#EF5350'
            ax.plot([i][i], [c["l"], c["h"]], color=color, linewidth=0.8, zorder=1)
            body_h = abs(c["c"]-c["o"]); body_y = min(c["o"], c["c"])
            if body_h < (max([x["h"]-x["l"] for x in data]) * 0.008): body_h = max([x["h"]-x["l"] for x in data]) * 0.008
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
        buf.seek(0); plt.close(fig); buf.name=f"{symbol}_V4.png"
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
    daily=get_daily(); active=get_active(); btns=[]
    if active and active.get("status")=="OPEN":
        btns.append([InlineKeyboardButton(f"🎯 FOCUSING: {active['coin']} {active['dir']} - Status",callback_data=f"STATUS_{active['coin']}")])
        btns.append([InlineKeyboardButton(f"✅ Close WIN",callback_data="CLOSE_WIN"), InlineKeyboardButton(f"❌ Close LOSS",callback_data="CLOSE_LOSS")])
    else:
        if daily["trades"]>=3: btns.append([InlineKeyboardButton(f"✅ Daily 3/3 Done P&L ${daily['pnl']:.2f}",callback_data="DAILY_DONE")])
        elif daily["losses"]>=2: btns.append([InlineKeyboardButton(f"🛡️ Guard: 2 Losses Stop Today",callback_data="DAILY_DONE")])
        else: btns.append([InlineKeyboardButton(f"🔍 SCAN BEST MASTER - Trade {daily['trades']+1}/3 Today",callback_data="SCAN_BEST")])
        btns.append([InlineKeyboardButton(f"📊 Daily: {daily['wins']}W/{daily['losses']}L {daily['trades']}/3 P&L ${daily['pnl']:.2f}",callback_data="SHOW_DAILY")])
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

def master_focus_kb(master):
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"🎯 FOCUS & TRADE {master['code']} NOW - MASTER",callback_data=f"FOCUS_{master['code']}")],[InlineKeyboardButton(f"📈 Chart {master['code']}",callback_data=f"C_{master['code']}")]])

def monitor_loop():
    while True:
        try:
            active=get_active()
            if active and active.get("status")=="OPEN":
                sym=CRYPTO.get(active["coin"],active["coin"]+"USDT")
                kl=get_klines(sym,"1h")
                if kl:
                    live=kl[-1]["c"]; entry=active["entry"]; tp1=active["tp1"]; tp2=active["tp2"]; sl=active["sl"]; direction=active["dir"]
                    hit_tp1=False; hit_tp2=False; hit_sl=False
                    if direction=="BUY":
                        if live>=tp1: hit_tp1=True
                        if live>=tp2: hit_tp2=True
                        if live<=sl: hit_sl=True
                    else:
                        if live<=tp1: hit_tp1=True
                        if live<=tp2: hit_tp2=True
                        if live>=sl: hit_sl=True
                    if hit_tp1 and not active.get("tp1_hit"):
                        active["tp1_hit"]=True; set_active(active); send_telegram_alert(f"🔔 MASTER {active['coin']} TP1 HIT! Live {fmt(live)} Entry {fmt(entry)} - Move SL to BE!")
                    if hit_tp2:
                        daily=update_daily("WIN",3.0,active["coin"]); clear_active(); send_telegram_alert(f"💰 MASTER {active['coin']} TP2 HIT WIN! Daily {daily['wins']}W/{daily['losses']}L {daily['trades']}/3 P&L ${daily['pnl']:.2f} - SCAN NEXT!")
                    if hit_sl:
                        daily=update_daily("LOSS",-1.5,active["coin"]); clear_active(); guard=" GUARD STOP TODAY!" if daily["losses"]>=2 else f" Next {daily['trades']+1}/3"; send_telegram_alert(f"🛑 MASTER {active['coin']} SL HIT Daily {daily['wins']}W/{daily['losses']}L{guard}")
            time.sleep(60)
        except: time.sleep(60)

async def start(u,c):
    save_chat_id(u.message.chat.id if hasattr(u.message,'chat') else u.effective_chat.id)
    daily=get_daily(); active=get_active()
    if daily["losses"]>=2:
        await u.message.reply_text(f"🛡️ DAILY GUARD ACTIVE\nYou don lose 2 today ({daily['losses']}L). Stop trading today boss to save your $5.\nP&L today: ${daily['pnl']:.2f}\nCome back tomorrow.\n\nUse /resetdaily if new day.",reply_markup=coins_kb()); return
    if active and active.get("status")=="OPEN":
        await u.message.reply_text(f"🎯 MASTER FOCUS ACTIVE\n\nYou dey trade {active['coin']} {active['dir']} now\nEntry {fmt(active['entry'])} | TP1 {fmt(active['tp1'])} | TP2 {fmt(active['tp2'])} | SL {fmt(active['sl'])}\nBot dey monitor am. No open new coin till TP/SL.\nUse buttons 👇",reply_markup=coins_kb()); return
    await u.message.reply_text(f"🚀 V4 MASTER FOCUS - ALL FEATURES + 2-3 Trades/Day + TP/SL Monitor ✅\n\nDaily: {daily['wins']}W/{daily['losses']}L Trades {daily['trades']}/3 P&L ${daily['pnl']:.2f}\n\n✅ EMA20/50/200 + RSI + ATR + Sup/Res + MTF + Vol + ADX + BTC + Liq + Patterns + Chart + Leverage + Risk Calc + MASTER + TP/SL Alert + Guard\n\nPress SCAN to find MASTER coin for Trade {daily['trades']+1}/3 👇",reply_markup=coins_kb())

async def status_cmd(u,c):
    save_chat_id(u.message.chat.id); active=get_active()
    if not active or active.get("status")!="OPEN": await u.message.reply_text("No active MASTER focus. Press SCAN",reply_markup=coins_kb()); return
    kl=get_klines(active["coin"]+"USDT","1h"); live=kl[-1]["c"] if kl else active["entry"]
    await u.message.reply_text(f"📡 LIVE MONITORING MASTER\n\n🎯 {active['coin']} {active['dir']}\nEntry {fmt(active['entry'])}\nLive {fmt(live)}\nTP1 {fmt(active['tp1'])} TP2 {fmt(active['tp2'])} SL {fmt(active['sl'])}",reply_markup=coins_kb())

async def reset_daily_cmd(u,c):
    save_json(DAILY_FILE,{"date":str(date.today()),"wins":0,"losses":0,"trades":0,"pnl":0.0,"history":[]}); clear_active()
    await u.message.reply_text("✅ Daily reset done. 3 trades available again.",reply_markup=coins_kb())

async def btn_handler(u,c):
    q=u.callback_query; await q.answer(); d=q.data
    save_chat_id(q.message.chat.id); daily=get_daily(); active=get_active()
    if d.startswith("IGNORE") or d=="DAILY_DONE":
        await q.answer("Pick coin boss" if d!="DAILY_DONE" else f"Daily {daily['trades']}/3",show_alert=False); return
    if d=="SHOW_DAILY":
        await q.message.reply_text(f"📊 DAILY STATS {daily['date']}\nWins {daily['wins']} Losses {daily['losses']} Trades {daily['trades']}/3\nP&L ${daily['pnl']:.2f}",reply_markup=coins_kb()); return
    if d.startswith("STATUS_"):
        kl=get_klines(active["coin"]+"USDT","1h") if active else []; live=kl[-1]["c"] if kl else (active["entry"] if active else 0)
        await q.message.reply_text(f"📡 {active['coin']} Entry {fmt(active['entry'])} Live {fmt(live)} TP1 {fmt(active['tp1'])} TP2 {fmt(active['tp2'])} SL {fmt(active['sl'])}",reply_markup=coins_kb()); return
    if d=="CLOSE_WIN":
        daily_new=update_daily("WIN",2.5,active.get("coin","")); clear_active()
        await q.message.reply_text(f"✅ WIN Closed +$2.5 Daily {daily_new['wins']}W/{daily_new['losses']}L {daily_new['trades']}/3 - SCAN NEXT MASTER Trade {daily_new['trades']+1}/3 👇",reply_markup=coins_kb()); return
    if d=="CLOSE_LOSS":
        daily_new=update_daily("LOSS",-1.5,active.get("coin","")); clear_active()
        msg=f"❌ LOSS Closed Daily {daily_new['wins']}W/{daily_new['losses']}L {daily_new['trades']}/3"
        if daily_new["losses"]>=2: msg+="\n🛡️ GUARD 2 losses - STOP TODAY"
        await q.message.reply_text(msg,reply_markup=coins_kb()); return
    if d.startswith("FOCUS_"):
        coin=d[5:]; btc=get_btc_trend(); r=analyze_balanced(coin, btc_trend_score=btc, use_15m_fallback=True)
        if r.get("error"): await q.message.reply_text(f"No data {coin}",reply_markup=coins_kb()); return
        set_active({"coin":coin,"dir":r["dir"],"entry":r["entry"],"tp1":r["tp1"],"tp2":r["tp2"],"tp3":r["tp3"],"sl":r["sl"],"confidence":r["conf"],"win_est":r["win_est"],"status":"OPEN","opened_at":str(datetime.now())[:16],"tp1_hit":False})
        pats_txt="\n".join([f"• {p}" for p in r["pats"]])
        risk_txt=get_risk_calculator_text(r["entry"], r["sl"], r["tp1"], r["tp2"], r["tp3"], r["lev"], r["dir"], r["is_fast"])
        status="🔥 HIGH WIN 80%+ - TRADE THIS ✅" if r["high_win"] else "⚠️ MEDIUM 65-74%" if r["conf"]>=65 else "⛔ LOW CONF <65% - SKIP"
        msg=f"🎯 MASTER FOCUS LOCKED: {coin} Trade {daily['trades']+1}/3\n\n{r['dir']} @ {fmt(r['entry'])} TP1 {fmt(r['tp1'])} TP2 {fmt(r['tp2'])} SL {fmt(r['sl'])}\nConf {r['conf']:.0f}% Win {r['win_est']:.0f}% ADX {r['adx']:.0f}\nMTF {r['mtf_txt']}\nVol {r['vol_txt']}\nBTC {r['btc_txt']}\nTrend {r['trend']} EMA20 {fmt(r['e20'])} EMA50 {fmt(r['e50'])} EMA200 {fmt(r['e200'])} RSI {r['rsi']:.0f}\n{risk_txt}\nBot go monitor ONLY {coin} till TP/SL hit. Enter Binance now $5 10x. Bot go alert you."
        try:
            buf=generate_chart_image(r['code'], r['dir'], r['entry'], r['sl'], r['tp1'], r['tp2'], r['tp3'], r['kl'], r['sup'], r['res'], r['conf'], r['trend'], r['is_fast'], r['win_est'], r['high_win'])
            if buf: await c.bot.send_photo(chat_id=q.message.chat.id, photo=buf, caption=msg, reply_markup=coins_kb()); return
        except: pass
        await q.message.reply_text(msg,reply_markup=coins_kb()); return
    if d=="SCAN_BEST":
        if daily["trades"]>=3: await q.message.reply_text(f"✅ Daily limit 3/3 reached P&L ${daily['pnl']:.2f} Rest boss!",reply_markup=coins_kb()); return
        if daily["losses"]>=2: await q.message.reply_text(f"🛡️ Guard 2 losses today stop P&L ${daily['pnl']:.2f}",reply_markup=coins_kb()); return
        if active and active.get("status")=="OPEN": await q.message.reply_text(f"🎯 You still dey focus on {active['coin']} {active['dir']}. No open new till TP/SL.",reply_markup=coins_kb()); return
        await q.edit_message_text(f"🔍 V4 MASTER SCAN - Finding BEST coin for Trade {daily['trades']+1}/3...\nBTC filter + ADX + Vol + 15M fallback... ⏳ 30 secs...")
        try:
            top5, btc_score = scan_best_coins()
            if not top5: await q.message.reply_text("❌ No data, try again",reply_markup=coins_kb()); return
            master=top5[0]; others=top5[1:3]
            txt=f"🏆 V4 MASTER FOCUS - BEST COIN TO TRADE NOW\nBTC Trend {btc_score:+.0f} | Daily {daily['wins']}W/{daily['losses']}L Trades {daily['trades']}/3\n\n🥇 MASTER RECOMMENDATION - TRADE THIS ONE ONLY (Trade {daily['trades']+1}/3):\n🔥 {master['code']} {master['dir']} {'⚡15M SCALP' if master['scalp_mode'] else '4H'}\nWin {master['win_est']:.0f}% | Conf {master['conf']:.0f}% | ADX {master['adx']:.0f}\nVol: {master['vol_txt']}\nMTF: {master['mtf_txt']}\nEntry {fmt(master['entry'])} | SL {fmt(master['sl'])} | TP1 {fmt(master['tp1'])} TP2 {fmt(master['tp2'])}\n{master['btc_txt']}\n{master['liq_txt']}\n\n👇 Press FOCUS to lock bot on {master['code']} till TP/SL hit\n\n🥈🥉 OTHER GOOD (Ignore until MASTER close):\n"
            for o in others: txt+=f"- {o['code']} {o['dir']} {o['win_est']:.0f}% Conf {o['conf']:.0f}%\n"
            txt+=f"\nAfter MASTER hit TP/SL, bot go allow next scan for Trade {daily['trades']+2}/3"
            await q.message.reply_text(txt,reply_markup=master_focus_kb(master))
        except Exception as e:
            print(traceback.format_exc()); await q.message.reply_text(f"❌ Scan error {e}",reply_markup=coins_kb())
        return
    if not d.startswith("C_"): return
    code=d[2:]; now=time.time()
    if q.from_user.id in LAST_CLICK and now-LAST_CLICK[q.from_user.id]<1.5:
        await q.answer("⏳ Wait small boss!",show_alert=False); return
    LAST_CLICK[q.from_user.id]=now
    try: await q.edit_message_text(f"📊 V4 Analyzing {code} with ALL features + MASTER + TP/SL monitor... ⏳")
    except: pass
    try:
        btc=get_btc_trend(); r=analyze_balanced(code, btc_trend_score=btc, use_15m_fallback=True)
        if r.get("error"): await q.message.reply_text(f"⚠️ {r['msg']}",reply_markup=coins_kb()); return
        pats_txt="\n".join([f"• {p}" for p in r["pats"]])
        risk_txt=get_risk_calculator_text(r["entry"], r["sl"], r["tp1"], r["tp2"], r["tp3"], r["lev"], r["dir"], r["is_fast"])
        if r["high_win"]: status="🔥 HIGH WIN 80%+ - TRADE THIS ✅"
        elif r["conf"]>=65: status="⚠️ MEDIUM 65-74% - Trade small / Wait Vol"
        else: status="⛔ LOW CONF <65% - SKIP - NO TRADE"
        if r["vol_score"]<=-15: status+="\n⚠️ VOL LOW - RISKY"
        if r["scalp_mode"]: status+="\n⚡ 15M SCALP MODE ACTIVE (4H low vol)"
        msg=f"""{"🟢" if r['dir']=="BUY" else "🔴"} {r['code']} {r['dir']} SIGNAL - V4 MASTER FINAL {"⚡FAST" if r['is_fast'] else "🐢SLOW"} {"+15M" if r['scalp_mode'] else ""}

{status}
Win Est: {r['win_est']:.0f}% | Conf: {r['conf']:.0f}% | ADX: {r['adx']:.0f}

💰 Price: {fmt(r['price'])} | {r['src']}
⏰ MTF FUTURE EYE:
{r['mtf_txt']}
Agree: {'✅ ALL ALIGN' if r['mtf_agree'] else '⚠️ CONFLICT'}
Vol: {r['vol_txt']}
ADX: {r['adx']:.0f} {'✅ Strong Trend' if r['adx']>25 else '⚠️ Weak/Sideways' if r['adx']<20 else 'Normal'}
BTC Filter: {r['btc_txt'] or 'BTC Neutral'}
Liq: {r['liq_txt']}

📊 4H FULL ANALYSIS:
Trend: {r['trend']} ({r['t_score']:.0f})
EMA20 {fmt(r['e20'])} | EMA50 {fmt(r['e50'])} | EMA200 {fmt(r['e200'])}
RSI {r['rsi']:.0f} | ATR {fmt(r['atr'])}
Sup {fmt(r['sup'])} | Res {fmt(r['res'])}

🕯️ CANDLE: {r['c_score']:.0f}
{pats_txt}

💵 ENTRY - ALL DETAILS:
Dir: {r['dir']} | Lev: {r['lev']}
Entry: {fmt(r['entry'])}
🛑 SL: {fmt(r['sl'])} (old {fmt(r['sl_raw'])})
🎯 TP1: {fmt(r['tp1'])} | TP2: {fmt(r['tp2'])} | TP3: {fmt(r['tp3'])}
{risk_txt}
Daily: {daily['wins']}W/{daily['losses']}L Trades {daily['trades']}/3 P&L ${daily['pnl']:.2f}

🎯 Want to FOCUS bot on {code} till TP/SL? Press FOCUS button below.
"""
        try:
            buf=generate_chart_image(r['code'], r['dir'], r['entry'], r['sl'], r['tp1'], r['tp2'], r['tp3'], r['kl'], r['sup'], r['res'], r['conf'], r['trend'], r['is_fast'], r['win_est'], r['high_win'])
            if buf: await c.bot.send_photo(chat_id=q.message.chat.id, photo=buf, caption=msg, reply_markup=coins_kb()); return
        except Exception as e: print(f"Chart send failed {e}")
        await q.message.reply_text(msg,reply_markup=coins_kb())
    except Exception as e:
        print(traceback.format_exc()); await q.message.reply_text(f"❌ {code} {e}",reply_markup=coins_kb())

async def txt_handler(u,c):
    save_chat_id(u.message.chat.id); s=clean((u.message.text or "").strip())
    if s in CRYPTO or s=="XAUUSD":
        await u.message.reply_text(f"📊 V4 ALL FEATURES Analysis for {s}...")
        btc=get_btc_trend(); r=analyze_balanced(s, btc_trend_score=btc, use_15m_fallback=True)
        if r.get("error"): await u.message.reply_text(f"⚠️ {r['msg']}",reply_markup=coins_kb()); return
        pats_txt="\n".join([f"• {p}" for p in r["pats"]])
        risk_txt=get_risk_calculator_text(r["entry"], r["sl"], r["tp1"], r["tp2"], r["tp3"], r["lev"], r["dir"], r["is_fast"])
        msg=f"{r['code']} {r['dir']} Win {r['win_est']:.0f}% Conf {r['conf']:.0f}% ADX {r['adx']:.0f}\nPrice {fmt(r['price'])} EMA20 {fmt(r['e20'])} EMA50 {fmt(r['e50'])} EMA200 {fmt(r['e200'])} RSI {r['rsi']:.0f}\nEntry {fmt(r['entry'])} SL {fmt(r['sl'])} TP1 {fmt(r['tp1'])} TP2 {fmt(r['tp2'])} TP3 {fmt(r['tp3'])} Lev {r['lev']}\n{risk_txt}"
        await u.message.reply_text(msg,reply_markup=coins_kb())

def run_flask(): app.run(host="0.0.0.0",port=PORT)
def run_bot():
    if not BOT_TOKEN: print("No BOT_TOKEN"); return
    a=ApplicationBuilder().token(BOT_TOKEN).build()
    a.add_handler(CommandHandler("start",start))
    a.add_handler(CommandHandler("status",status_cmd))
    a.add_handler(CommandHandler("resetdaily",reset_daily_cmd))
    a.add_handler(CallbackQueryHandler(btn_handler))
    a.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,txt_handler))
    print("Bot V4 MASTER FOCUS FINAL ALL FEATURES starting with monitor..."); threading.Thread(target=monitor_loop,daemon=True).start()
    a.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    threading.Thread(target=run_flask,daemon=True).start()
    run_bot()
