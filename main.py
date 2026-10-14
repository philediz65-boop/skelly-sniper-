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
def home(): return "SKELLY V5 SNIPER MASTER - FIXED",200
@app.get("/health")
def health(): return {"ok":True},200

def clean(t):
    t=t.upper().strip().replace("/","").replace("-","").replace("_",""); t=re.sub(r"[^A-Z0-9]","",t)
    m={"BITCOIN":"BTC","ETHEREUM":"ETH","SOLANA":"SOL","GOLD":"XAUUSD","XAU":"XAUUSD","XAUUSD":"XAUUSD","PAXG":"PAXG"}
    if t in m: t=m[t]
    if t.endswith("USDT") and t[:-4] in CRYPTO: return t[:-4]
    return t
def fmt(v):
    try: return f"{v:,.2f}" if v>=1000 else f"{v:,.4f}" if v>=1 else f"{v:.8f}"
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
    for x in arr[p:]: e=(x-e)*k+e; res.append(e)
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

# V5 SNIPER FILTERS - NEW - NO CRASH
def v5_liquidity_sweep(kl, side):
    if len(kl)<22: return False, None, "No data"
    recent_high=max([k["h"] for k in kl[-21:-1]]); recent_low=min([k["l"] for k in kl[-21:-1]])
    last=kl[-1]
    if side=="SELL":
        if last["h"] > recent_high and last["c"] < recent_high:
            return True, last["h"], f"LIQ SWEEP HIGH {fmt(recent_high)} -> {fmt(last['h'])} REJECT Short!"
    else:
        if last["l"] < recent_low and last["c"] > recent_low:
            return True, last["l"], f"LIQ SWEEP LOW {fmt(recent_low)} -> {fmt(last['l'])} REJECT Long!"
    return False, None, f"No sweep"

def v5_confluence_lock(s1, t1, s4, t4, sD, tD):
    ultra_strong_up = (s1>=50 and s4>=50 and sD>=20)
    ultra_strong_down = (s1<=-50 and s4<=-50 and sD<=-20)
    if ultra_strong_up: return True, "BUY", f"CONFLUENCE PASS 1H {t1} {s1} + 4H {t4} {s4} + 1D {tD} {sD}"
    if ultra_strong_down: return True, "SELL", f"CONFLUENCE PASS 1H {t1} {s1} + 4H {t4} {s4} + 1D {tD} {sD}"
    return False, None, f"BLOCKED 1H {t1} {s1} / 4H {t4} {s4} / 1D {tD} {sD} Need 1H STRONG"

def v5_ema_pullback(closes, e20, side):
    if not closes: return False, 100, "No data"
    live=closes[-1]; dist=abs(live-e20)/live*100 if live!=0 else 100
    if dist < 1.0: return True, dist, f"PULLBACK EMA20 {fmt(e20)} dist {dist:.2f}% Perfect"
    return False, dist, f"No pullback EMA20 {fmt(e20)} dist {dist:.2f}%"

def v5_dynamic_atr_sl_tp(entry, atr_val, side, is_fast):
    if entry==0: return entry*0.98, entry*1.02, entry*1.04, entry*1.06, 2.0, 3.0, 5.0
    atr_pct=atr_val/entry*100 if entry!=0 else 1.0
    base_sl_pct = atr_pct*1.5 + 0.35
    if is_fast: base_sl_pct = max(0.8, min(base_sl_pct, 2.5))
    else: base_sl_pct = max(1.2, min(base_sl_pct, 3.2))
    if side=="BUY":
        sl=entry - entry*base_sl_pct/100
        tp1=entry + entry*base_sl_pct*1.5/100
        tp2=entry + entry*base_sl_pct*3.0/100
        tp3=entry + entry*base_sl_pct*5.0/100
    else:
        sl=entry + entry*base_sl_pct/100
        tp1=entry - entry*base_sl_pct*1.5/100
        tp2=entry - entry*base_sl_pct*3.0/100
        tp3=entry - entry*base_sl_pct*5.0/100
    if not is_fast:
        if side=="BUY": sl = sl - (entry-sl)*0.10
        else: sl = sl + (sl-entry)*0.10
        base_sl_pct = base_sl_pct*1.10
    return sl, tp1, tp2, tp3, base_sl_pct, base_sl_pct*1.5, base_sl_pct*3.0

def v5_volume_filter(vol_score, adx_val):
    if vol_score <= -25: return False, f"BLOCK Vol {vol_score} low"
    if adx_val < 18: return False, f"BLOCK ADX {adx_val:.0f} weak"
    return True, f"Vol + ADX OK"

def analyze_balanced(code, btc_trend_score=0, use_15m_fallback=False, strict_v5=True):
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
    if strict_v5:
        con_ok, con_side, con_msg = v5_confluence_lock(s1, t1, s4, t4, sD, tD)
        if not con_ok:
            return {"error":True,"msg":con_msg,"blocked":True,"mtf_txt":f"1H {t1} | 4H {t4} | 1D {tD}","vol_txt":vol_txt,"adx":adx}
        forced_direction = con_side
    else:
        con_msg = f"V4 Mode 1H {t1} | 4H {t4} | 1D {tD}"; forced_direction=None
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
    liquidity_txt=f"Liq above {fmt(recent_high)} | below {fmt(recent_low)}"
    final = mtf_score*0.35 + t_score*0.25 + c_score*0.20 + vol_score*0.10 + (adx-25)*0.3
    is_fast = code in FAST_COINS or scalp_mode
    vol_ok, vol_filter_msg = v5_volume_filter(vol_score, adx)
    if strict_v5 and not vol_ok:
        return {"error":True,"msg":vol_filter_msg,"blocked":True,"mtf_txt":f"1H {t1} | 4H {t4} | 1D {tD}","vol_txt":vol_txt,"adx":adx}
    direction = forced_direction if forced_direction else ("BUY" if final>=5 else "SELL")
    sweep_ok, sweep_level, sweep_msg = v5_liquidity_sweep(kl4 if not scalp_mode else kl15, direction)
    entry = sweep_level if (sweep_ok and sweep_level) else live
    pull_ok, pull_dist, pull_msg = v5_ema_pullback(closes4, e20, direction)
    if strict_v5 and not pull_ok and not sweep_ok:
        return {"error":True,"msg":pull_msg,"blocked":True,"mtf_txt":f"1H {t1} | 4H {t4} | 1D {tD}","vol_txt":vol_txt,"adx":adx}
    base_conf = 60 + abs(final)*0.32
    if mtf_agree: base_conf+=8
    if vol_score>10: base_conf+=4
    if adx>25: base_conf+=5
    if sweep_ok: base_conf+=10
    if pull_ok: base_conf+=5
    if adx<18: base_conf-=10
    conf = min(93, max(50, base_conf)); high_win = conf>=75 and mtf_agree and adx>20 and (sweep_ok or pull_ok); win_est = min(89, conf*0.96 + (5 if high_win else 0) + (5 if sweep_ok else 0))
    pats_str=" ".join(pats)
    if vol_score<=-15: high_win=False; conf=min(conf,68); win_est=min(win_est,68)
    if vol_score<=-25: high_win=False; conf=min(conf,62); win_est=min(win_est,62)
    if "3 GREEN" in pats_str and final<0: high_win=False; conf=max(50,conf-8); win_est=max(50,win_est-8)
    if "3 RED" in pats_str and final>0: high_win=False; conf=max(50,conf-8); win_est=max(50,win_est-8)
    if adx<18: high_win=False; conf=min(conf,65); win_est=min(win_est,65)
    btc_txt=""
    if code!="BTC" and btc_trend_score!=0:
        if btc_trend_score<-30 and final>10: btc_txt=f"BTC DOWN {btc_trend_score} vs {code} BUY CONFLICT"; high_win=False; conf=max(50,conf-10); win_est=max(50,win_est-10)
        elif btc_trend_score>30 and final<-10: btc_txt=f"BTC UP {btc_trend_score} vs {code} SELL CONFLICT"; high_win=False; conf=max(50,conf-10); win_est=max(50,win_est-10)
        else: btc_txt=f"BTC {btc_trend_score:+.0f} aligns"
    sl, tp1, tp2, tp3, sl_pct, tp1_pct, tp2_pct = v5_dynamic_atr_sl_tp(entry, atr, direction, is_fast)
    sl_raw = sl
    atr_pct=atr/live*100 if live!=0 else 1
    if is_fast: lev="25x-50x (Fast Scalp)" if atr_pct<0.8 else "15x-30x (Fast)" if atr_pct<2 else "10x-20x (Very Fast)"
    else: lev="20x-25x (Low Vol)" if atr_pct<0.5 else "10x-15x (Normal 4H)" if atr_pct<1.2 else "5x-7x (High Vol 4H)"
    trend_txt = "STRONG UPTREND" if t_score>60 else "UPTREND" if t_score>15 else "STRONG DOWNTREND" if t_score<-60 else "DOWNTREND" if t_score<-15 else "SIDEWAYS"
    return {"error":False,"code":code,"price":live,"src":src,"trend":trend_txt,"e20":e20,"e50":e50,"e200":e200,"rsi":rsi,"sup":sup,"res":res,"atr":atr,"t_score":t_score,"c_score":c_score,"final":final,"pats":pats,"dir":direction,"entry":entry,"sl":sl,"sl_raw":sl_raw,"tp1":tp1,"tp2":tp2,"tp3":tp3,"lev":lev,"conf":conf,"kl":kl4 if not scalp_mode else kl15,"is_fast":is_fast,"mtf_score":mtf_score,"mtf_agree":mtf_agree,"mtf_txt":f"1H {t1} | 4H {t4} | 1D {tD}","vol_txt":vol_txt,"vol_score":vol_score,"high_win":high_win,"win_est":win_est,"adx":adx,"btc_txt":btc_txt,"liq_txt":liquidity_txt,"scalp_mode":scalp_mode,"v5_con_msg":con_msg,"v5_sweep_ok":sweep_ok,"v5_sweep_level":sweep_level,"v5_sweep_msg":sweep_msg,"v5_pull_ok":pull_ok,"v5_pull_msg":pull_msg,"v5_pull_dist":pull_dist,"v5_vol_filter_msg":vol_filter_msg,"v5_sl_pct":sl_pct}
    def get_btc_trend():
    try:
        kl=get_klines("BTCUSDT","4h")
        if not kl: return 0
        closes=[c["c"] for c in kl]
        s,_=get_mtf_trend(closes)
        return s
    except: return 0

def scan_best_coins():
    btc_score=get_btc_trend(); results=[]; blocked=[]
    for code in CRYPTO.keys():
        if code=="XAUUSD": continue
        try:
            r=analyze_balanced(code, btc_trend_score=btc_score, use_15m_fallback=True, strict_v5=True)
            if not r.get("error"): results.append(r)
            else:
                if r.get("blocked"): blocked.append(f"{code}: {r.get('msg','')}")
            time.sleep(0.25)
        except: pass
    results_sorted=sorted(results, key=lambda x: (x["win_est"], x["vol_score"], x["adx"]), reverse=True)
    return results_sorted[:5], btc_score, blocked

def generate_chart_image(symbol, direction, entry, sl, tp1, tp2, tp3, kl, sup, res, conf, trend_txt, is_fast, win_est, high_win):
    try:
        data = kl[-80:]; closes=[c["c"] for c in kl]
        e20_s=ema_series(closes,20)[-80:]; e50_s=ema_series(closes,50)[-80:]; e200_s=ema_series(closes,200)[-80:]
        fig, ax = plt.subplots(figsize=(12,6.5), facecolor='white')
        for i, c in enumerate(data):
            color = '#26A69A' if c["c"] >= c["o"] else '#EF5350'
            ax.plot([i, i], [c["l"], c["h"]], color=color, linewidth=0.8, zorder=1)
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
        pair = f"{symbol}USDT"
        mode = "FAST" if is_fast else "SLOW"
        title_color = '#26A69A' if direction=="BUY" else '#EF5350'
        win_txt = f"WIN {win_est:.0f}%"
        ls_title = "BUY LONG" if direction=="BUY" else "SELL SHORT"
        ax.set_title(f"{pair} | {ls_title} | {mode} | {trend_txt} | Conf {conf:.0f}% | {win_txt}", loc='left', fontsize=11, fontweight='bold', color=title_color)
        ax.legend(loc='upper left', fontsize=7, bbox_to_anchor=(0.18,0.96))
        ax.grid(True, alpha=0.15)
        plt.tight_layout()
        buf=io.BytesIO()
        plt.savefig(buf, format='png', dpi=170)
        buf.seek(0); plt.close(fig); buf.name=f"{symbol}_V5.png"
        return buf
    except Exception as e:
        print(f"chart error {e}")
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
        def m5(pct): return 5*pct/100
        def m100(pct): return 100*pct/100
        long_short = "BUY LONG" if direction=="BUY" else "SELL SHORT"
        mode_txt = "FAST" if is_fast else "SLOW ATR DYNAMIC"
        return f"\n{mode_txt} - {long_short}\nLEV {lev_num}x: SL {sl_pct:.2f}% $5->{m5(sl_pct):.2f} $100->{m100(sl_pct):.2f} | TP1 {abs(tp1_pct):.2f}% $5->{abs(m5(tp1_pct)):.2f} TP2 {abs(tp2_pct):.2f}% $5->{abs(m5(tp2_pct)):.2f} TP3 {abs(tp3_pct):.2f}% $5->{abs(m5(tp3_pct)):.2f}\n"
    except: return ""

def coins_kb():
    daily=get_daily(); active=get_active(); btns=[]
    if active and active.get("status")=="OPEN":
        ls = "BUY LONG" if active['dir']=="BUY" else "SELL SHORT"
        btns.append([InlineKeyboardButton(f"FOCUSING: {active['coin']} {ls}",callback_data=f"STATUS_{active['coin']}")])
        btns.append([InlineKeyboardButton(f"Close WIN",callback_data="CLOSE_WIN"), InlineKeyboardButton(f"Close LOSS",callback_data="CLOSE_LOSS")])
    else:
        if daily["trades"]>=3: btns.append([InlineKeyboardButton(f"Daily 3/3 Done P&L ${daily['pnl']:.2f}",callback_data="DAILY_DONE")])
        elif daily["losses"]>=2: btns.append([InlineKeyboardButton(f"Guard: 2 Losses Stop",callback_data="DAILY_DONE")])
        else: btns.append([InlineKeyboardButton(f"SCAN BEST V5 - Trade {daily['trades']+1}/3",callback_data="SCAN_BEST")])
        btns.append([InlineKeyboardButton(f"Daily: {daily['wins']}W/{daily['losses']}L {daily['trades']}/3 ${daily['pnl']:.2f}",callback_data="SHOW_DAILY")])
    btns.append([InlineKeyboardButton("--- FAST ---",callback_data="IGNORE_FAST")])
    fast=["SOL","DOGE","PEPE","BONK","WIF","BOME","FLOKI","SHIB","AVAX","SUI","ARB","OP","APT","TAO","NOT"]
    row=[]
    for c in fast:
        if c in CRYPTO:
            row.append(InlineKeyboardButton(f"{c}",callback_data=f"C_{c}"))
            if len(row)==3: btns.append(row); row=[]
    if row: btns.append(row)
    btns.append([InlineKeyboardButton("--- SLOW ---",callback_data="IGNORE_SLOW")])
    slow=["BTC","ETH","BNB","XRP","ADA","LINK","TRX","DOT","MATIC","LTC","BCH","UNI","ATOM","ETC","FIL","PAXG"]
    row=[]
    for c in slow:
        if c in CRYPTO:
            row.append(InlineKeyboardButton(f"{c}",callback_data=f"C_{c}"))
            if len(row)==3: btns.append(row); row=[]
    if row: btns.append(row)
    btns.append([InlineKeyboardButton("XAUUSD GOLD",callback_data="C_XAUUSD")])
    return InlineKeyboardMarkup(btns)

def master_focus_kb(master):
    ls = "BUY LONG" if master['dir']=="BUY" else "SELL SHORT"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"FOCUS TRADE {master['code']} {ls} V5",callback_data=f"FOCUS_{master['code']}")],
        [InlineKeyboardButton(f"Chart {master['code']}",callback_data=f"C_{master['code']}")]
    ])

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
                        active["tp1_hit"]=True; set_active(active)
                        ls = "BUY LONG" if direction=="BUY" else "SELL SHORT"
                        send_telegram_alert(f"V5 MASTER {active['coin']} {ls} TP1 HIT Live {fmt(live)} Entry {fmt(entry)} Move SL BE 50%")
                    if hit_tp2:
                        ls = "BUY LONG" if direction=="BUY" else "SELL SHORT"
                        daily=update_daily("WIN",3.0,active["coin"]); clear_active()
                        send_telegram_alert(f"V5 MASTER {active['coin']} {ls} TP2 WIN +$3 Daily {daily['wins']}W/{daily['losses']}L {daily['trades']}/3 P&L ${daily['pnl']:.2f} SCAN NEXT")
                    if hit_sl:
                        ls = "BUY LONG" if direction=="BUY" else "SELL SHORT"
                        daily=update_daily("LOSS",-1.5,active["coin"]); clear_active()
                        guard=" GUARD STOP TODAY!" if daily["losses"]>=2 else f" Next {daily['trades']+1}/3"
                        send_telegram_alert(f"V5 MASTER {active['coin']} {ls} SL LOSS Daily {daily['wins']}W/{daily['losses']}L{guard}")
            time.sleep(60)
        except: time.sleep(60)

async def start(u,c):
    save_chat_id(u.message.chat.id if hasattr(u.message,'chat') else u.effective_chat.id)
    daily=get_daily(); active=get_active()
    if daily["losses"]>=2: await u.message.reply_text(f"GUARD ACTIVE Lose 2 today {daily['losses']}L Stop P&L ${daily['pnl']:.2f}",reply_markup=coins_kb()); return
    if active and active.get("status")=="OPEN":
        ls = "BUY LONG" if active['dir']=="BUY" else "SELL SHORT"
        await u.message.reply_text(f"FOCUS ACTIVE {active['coin']} {ls} Entry {fmt(active['entry'])} TP1 {fmt(active['tp1'])} TP2 {fmt(active['tp2'])} SL {fmt(active['sl'])}",reply_markup=coins_kb()); return
    await u.message.reply_text(f"V5 SNIPER MASTER - Daily {daily['wins']}W/{daily['losses']}L {daily['trades']}/3 P&L ${daily['pnl']:.2f} V5 Filters: Liquidity Sweep + Confluence Lock + EMA Pullback + ATR Dynamic + Vol ADX",reply_markup=coins_kb())

async def status_cmd(u,c):
    save_chat_id(u.message.chat.id); active=get_active()
    if not active or active.get("status")!="OPEN": await u.message.reply_text("No active focus",reply_markup=coins_kb()); return
    ls = "BUY LONG" if active['dir']=="BUY" else "SELL SHORT"
    kl=get_klines(active["coin"]+"USDT","1h"); live=kl[-1]["c"] if kl else active["entry"]
    await u.message.reply_text(f"LIVE V5 {active['coin']} {ls} Entry {fmt(active['entry'])} Live {fmt(live)} TP1 {fmt(active['tp1'])} TP2 {fmt(active['tp2'])} SL {fmt(active['sl'])}",reply_markup=coins_kb())

async def reset_daily_cmd(u,c):
    save_json(DAILY_FILE,{"date":str(date.today()),"wins":0,"losses":0,"trades":0,"pnl":0.0,"history":[]}); clear_active()
    await u.message.reply_text("Daily reset done",reply_markup=coins_kb())

async def btn_handler(u,c):
    q=u.callback_query; await q.answer(); d=q.data
    save_chat_id(q.message.chat.id); daily=get_daily(); active=get_active()
    if d.startswith("IGNORE") or d=="DAILY_DONE": await q.answer("Pick coin",show_alert=False); return
    if d=="SHOW_DAILY":
        await q.message.reply_text(f"DAILY {daily['date']} Wins {daily['wins']} Loss {daily['losses']} Trades {daily['trades']}/3 P&L ${daily['pnl']:.2f}",reply_markup=coins_kb()); return
    if d.startswith("STATUS_"):
        ls = "BUY LONG" if active['dir']=="BUY" else "SELL SHORT"
        kl=get_klines(active["coin"]+"USDT","1h") if active else []; live=kl[-1]["c"] if kl else (active["entry"] if active else 0)
        await q.message.reply_text(f"{active['coin']} {ls} Entry {fmt(active['entry'])} Live {fmt(live)} TP1 {fmt(active['tp1'])} TP2 {fmt(active['tp2'])} SL {fmt(active['sl'])}",reply_markup=coins_kb()); return
    if d=="CLOSE_WIN":
        ls = "BUY LONG" if active['dir']=="BUY" else "SELL SHORT"
        daily_new=update_daily("WIN",2.5,active.get("coin","")); clear_active()
        await q.message.reply_text(f"WIN Closed {ls} +$2.5 Daily {daily_new['wins']}W/{daily_new['losses']}L {daily_new['trades']}/3",reply_markup=coins_kb()); return
    if d=="CLOSE_LOSS":
        ls = "BUY LONG" if active['dir']=="BUY" else "SELL SHORT"
        daily_new=update_daily("LOSS",-1.5,active.get("coin","")); clear_active()
        msg=f"LOSS Closed {ls} Daily {daily_new['wins']}W/{daily_new['losses']}L {daily_new['trades']}/3"
        if daily_new["losses"]>=2: msg+=" GUARD 2 losses STOP TODAY"
        await q.message.reply_text(msg,reply_markup=coins_kb()); return
    if d.startswith("FOCUS_"):
        coin=d[6:]; btc=get_btc_trend(); r=analyze_balanced(coin, btc_trend_score=btc, use_15m_fallback=True, strict_v5=True)
        if r.get("error"): await q.message.reply_text(f"V5 BLOCKED {coin}: {r.get('msg','No data')} Protection!",reply_markup=coins_kb()); return
        set_active({"coin":coin,"dir":r["dir"],"entry":r["entry"],"tp1":r["tp1"],"tp2":r["tp2"],"tp3":r["tp3"],"sl":r["sl"],"confidence":r["conf"],"win_est":r["win_est"],"status":"OPEN","opened_at":str(datetime.now())[:16],"tp1_hit":False})
        ls = "BUY LONG" if r['dir']=="BUY" else "SELL SHORT"
        risk_txt=get_risk_calculator_text(r["entry"], r["sl"], r["tp1"], r["tp2"], r["tp3"], r["lev"], r["dir"], r["is_fast"])
        v5_extra = f"V5: {r['v5_con_msg']} | {r['v5_sweep_msg']} | {r['v5_pull_msg']} | ATR SL {r['v5_sl_pct']:.2f}%"
        msg=f"V5 FOCUS LOCKED {coin} Trade {daily['trades']+1}/3 {ls} {coin} @ {fmt(r['entry'])} TP1 {fmt(r['tp1'])} TP2 {fmt(r['tp2'])} SL {fmt(r['sl'])} Conf {r['conf']:.0f}% Win {r['win_est']:.0f}% ADX {r['adx']:.0f} {v5_extra} {risk_txt}"
        try:
            buf=generate_chart_image(r['code'], r['dir'], r['entry'], r['sl'], r['tp1'], r['tp2'], r['tp3'], r['kl'], r['sup'], r['res'], r['conf'], r['trend'], r['is_fast'], r['win_est'], r['high_win'])
            if buf: await c.bot.send_photo(chat_id=q.message.chat.id, photo=buf, caption=msg, reply_markup=coins_kb()); return
        except: pass
        await q.message.reply_text(msg,reply_markup=coins_kb()); return
    if d=="SCAN_BEST":
        if daily["trades"]>=3: await q.message.reply_text(f"Daily limit 3/3 P&L ${daily['pnl']:.2f}",reply_markup=coins_kb()); return
        if daily["losses"]>=2: await q.message.reply_text(f"Guard 2 losses stop P&L ${daily['pnl']:.2f}",reply_markup=coins_kb()); return
        if active and active.get("status")=="OPEN": await q.message.reply_text(f"You still focus on {active['coin']} {active['dir']}",reply_markup=coins_kb()); return
        await q.edit_message_text(f"V5 SNIPER SCAN Finding BEST for Trade {daily['trades']+1}/3 ... 40 secs")
        try:
            top5, btc_score, blocked = scan_best_coins()
            if not top5: 
                blk_txt = "\n".join(blocked[:10]) if blocked else "No coin passed V5"
                await q.message.reply_text(f"V5 BLOCKED ALL No perfect setup BTC {btc_score} Blocked {blk_txt}",reply_markup=coins_kb()); return
            master=top5[0]; others=top5[1:3]
            ls_master = "BUY LONG" if master['dir']=="BUY" else "SELL SHORT"
            txt=f"V5 MASTER BEST Trade {daily['trades']+1}/3 BTC {btc_score} {ls_master} {master['code']} {master['dir']} Win {master['win_est']:.0f}% Conf {master['conf']:.0f}% ADX {master['adx']:.0f} Entry {fmt(master['entry'])} SL {fmt(master['sl'])} TP1 {fmt(master['tp1'])} TP2 {fmt(master['tp2'])} V5 {master['v5_con_msg']} {master['v5_sweep_msg']} Blocked {len(blocked)} weak"
            await q.message.reply_text(txt,reply_markup=master_focus_kb(master))
        except Exception as e:
            print(traceback.format_exc()); await q.message.reply_text(f"Scan error {e}",reply_markup=coins_kb())
        return
    if not d.startswith("C_"): return
    code=d[2:]; now=time.time()
    if q.from_user.id in LAST_CLICK and now-LAST_CLICK[q.from_user.id]<1.5:
        await q.answer("Wait small",show_alert=False); return
    LAST_CLICK[q.from_user.id]=now
    try: await q.edit_message_text(f"V5 Analyzing {code} ...")
    except: pass
    try:
        btc=get_btc_trend(); r=analyze_balanced(code, btc_trend_score=btc, use_15m_fallback=True, strict_v5=True)
        if r.get("error"): 
            if r.get("blocked"):
                await q.message.reply_text(f"V5 BLOCKED {code} Protection {r.get('msg','')} MTF {r.get('mtf_txt','')} Vol {r.get('vol_txt','')} ADX {r.get('adx',0):.0f} This is why TRX today blocked - V5 saves $5",reply_markup=coins_kb())
            else:
                await q.message.reply_text(f"{r['msg']}",reply_markup=coins_kb())
            return
        pats_txt="\n".join([f"• {p}" for p in r["pats"]])
        risk_txt=get_risk_calculator_text(r["entry"], r["sl"], r["tp1"], r["tp2"], r["tp3"], r["lev"], r["dir"], r["is_fast"])
        ls = "BUY LONG" if r['dir']=="BUY" else "SELL SHORT"
        if r["high_win"]: status="HIGH WIN 80%+ SNIPER PERFECT"
        elif r["conf"]>=65: status="MEDIUM 65-74%"
        else: status="LOW CONF <65% SKIP"
        v5_extra = f"V5 FILTERS: {r['v5_con_msg']} | {r['v5_sweep_msg']} | {r['v5_pull_msg']} | ATR SL {r['v5_sl_pct']:.2f}%"
        msg=f"{ls} {r['code']} {r['dir']} SIGNAL V5 {'FAST' if r['is_fast'] else 'SLOW'} {status} Win {r['win_est']:.0f}% Conf {r['conf']:.0f}% ADX {r['adx']:.0f} Price {fmt(r['price'])} MTF {r['mtf_txt']} Vol {r['vol_txt']} ADX {r['adx']:.0f} BTC {r['btc_txt']} Liq {r['liq_txt']} {v5_extra} Trend {r['trend']} EMA20 {fmt(r['e20'])} EMA50 {fmt(r['e50'])} EMA200 {fmt(r['e200'])} RSI {r['rsi']:.0f} Sup {fmt(r['sup'])} Res {fmt(r['res'])} CANDLE {r['c_score']:.0f} {pats_txt} ENTRY Dir {ls} Lev {r['lev']} Entry {fmt(r['entry'])} {'SWEEP' if r['v5_sweep_ok'] else 'PULLBACK'} SL {fmt(r['sl'])} {r['v5_sl_pct']:.2f}% ATR TP1 {fmt(r['tp1'])} TP2 {fmt(r['tp2'])} TP3 {fmt(r['tp3'])} {risk_txt} Daily {daily['wins']}W/{daily['losses']}L {daily['trades']}/3 P&L ${daily['pnl']:.2f}"
        try:
            buf=generate_chart_image(r['code'], r['dir'], r['entry'], r['sl'], r['tp1'], r['tp2'], r['tp3'], r['kl'], r['sup'], r['res'], r['conf'], r['trend'], r['is_fast'], r['win_est'], r['high_win'])
            if buf: await c.bot.send_photo(chat_id=q.message.chat.id, photo=buf, caption=msg, reply_markup=coins_kb()); return
        except Exception as e: print(f"Chart send failed {e}")
        await q.message.reply_text(msg,reply_markup=coins_kb())
    except Exception as e:
        print(traceback.format_exc()); await q.message.reply_text(f"{code} {e}",reply_markup=coins_kb())

async def txt_handler(u,c):
    save_chat_id(u.message.chat.id); s=clean((u.message.text or "").strip())
    if s in CRYPTO or s=="XAUUSD":
        btc=get_btc_trend(); r=analyze_balanced(s, btc_trend_score=btc, use_15m_fallback=True, strict_v5=True)
        if r.get("error"): 
            await u.message.reply_text(f"V5 BLOCKED {s}: {r.get('msg','No data')} Protection!",reply_markup=coins_kb()); return
        ls = "BUY LONG" if r['dir']=="BUY" else "SELL SHORT"
        risk_txt=get_risk_calculator_text(r["entry"], r["sl"], r["tp1"], r["tp2"], r["tp3"], r["lev"], r["dir"], r["is_fast"])
        msg=f"{ls} {r['code']} {r['dir']} Win {r['win_est']:.0f}% Conf {r['conf']:.0f}% ADX {r['adx']:.0f} Sweep {r['v5_sweep_ok']} Price {fmt(r['price'])} Entry {fmt(r['entry'])} SL {fmt(r['sl'])} TP1 {fmt(r['tp1'])} TP2 {fmt(r['tp2'])} TP3 {fmt(r['tp3'])} Lev {r['lev']} {risk_txt}"
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
    print("Bot V5 SNIPER MASTER FIXED starting..."); threading.Thread(target=monitor_loop,daemon=True).start()
    a.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    threading.Thread(target=run_flask,daemon=True).start()
    run_bot()
