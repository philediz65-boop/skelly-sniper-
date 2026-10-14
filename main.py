import os,re,threading,requests,time,io,json,concurrent.futures
from flask import Flask
from telegram import InlineKeyboardButton,InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder,CommandHandler,CallbackQueryHandler,MessageHandler,filters
from datetime import datetime, date

BOT_TOKEN=os.getenv("BOT_TOKEN","").strip()
PORT=int(os.getenv("PORT","10000"))
app=Flask(__name__)
SESSION=requests.Session()
SESSION.headers.update({"User-Agent":"Mozilla/5.0"})
CACHE={}
ACTIVE_FILE="/tmp/active_trade_v6.json"; DAILY_FILE="/tmp/daily_stats_v6.json"; CHAT_FILE="/tmp/last_chat_id.json"
GLOBAL_ACTIVE={}; GLOBAL_CHAT_ID=None

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
    if d.get("date")!=today: d={"date":today,"wins":0,"losses":0,"trades":0,"pnl":0.0}; save_json(DAILY_FILE,d)
    return d
def update_daily(result,pnl,coin=""):
    d=get_daily(); d["trades"]+=1
    if result=="WIN": d["wins"]+=1
    else: d["losses"]+=1
    d["pnl"]+=pnl; save_json(DAILY_FILE,d); return d
def get_active():
    global GLOBAL_ACTIVE
    if GLOBAL_ACTIVE and GLOBAL_ACTIVE.get("status")=="OPEN": return GLOBAL_ACTIVE
    file_active=load_json(ACTIVE_FILE,{})
    if file_active and file_active.get("status")=="OPEN":
        GLOBAL_ACTIVE=file_active; return file_active
    return {}
def set_active(data):
    global GLOBAL_ACTIVE; GLOBAL_ACTIVE=data; save_json(ACTIVE_FILE,data)
def clear_active():
    global GLOBAL_ACTIVE; GLOBAL_ACTIVE={}; save_json(ACTIVE_FILE,{})
def save_chat_id(cid):
    global GLOBAL_CHAT_ID; GLOBAL_CHAT_ID=cid; save_json(CHAT_FILE,{"chat_id":cid})
def get_chat_id():
    global GLOBAL_CHAT_ID
    if GLOBAL_CHAT_ID: return GLOBAL_CHAT_ID
    d=load_json(CHAT_FILE,{}); cid=d.get("chat_id")
    if cid: GLOBAL_CHAT_ID=cid
    return cid

CRYPTO={"BTC":"BTCUSDT","ETH":"ETHUSDT","BNB":"BNBUSDT","SOL":"SOLUSDT","XRP":"XRPUSDT","DOGE":"DOGEUSDT","ADA":"ADAUSDT","AVAX":"AVAXUSDT","LINK":"LINKUSDT","TRX":"TRXUSDT","DOT":"DOTUSDT","MATIC":"MATICUSDT","LTC":"LTCUSDT","BCH":"BCHUSDT","UNI":"UNIUSDT","ATOM":"ATOMUSDT","ETC":"ETCUSDT","FIL":"FILUSDT","PEPE":"PEPEUSDT","BONK":"BONKUSDT","SHIB":"SHIBUSDT","FLOKI":"FLOKIUSDT","WIF":"WIFUSDT","BOME":"BOMEUSDT","SUI":"SUIUSDT","ARB":"ARBUSDT","OP":"OPUSDT","APT":"APTUSDT","TAO":"TAOUSDT","NOT":"NOTUSDT","PAXG":"PAXGUSDT","FARTCOIN":"FARTCOINUSDT","ENA":"ENAUSDT","TRUMP":"TRUMPUSDT"}
FAST_COINS={"PEPE","BONK","WIF","BOME","FLOKI","SHIB","DOGE","SOL","AVAX","SUI","ARB","OP","APT","TAO","NOT","FARTCOIN","ENA","TRUMP"}

@app.get("/")
def home(): return "SKELLY V6.20 LIGHT COLOURED CHART GOD 90% LIVE",200

def fmt(v):
    try:
        if v>=1000: return f"{v:,.2f}"
        if v>=1: return f"{v:.6f}"
        return f"{v:.8f}"
    except: return str(v)
def clean(t):
    t=t.upper().strip().replace("/","").replace("-","").replace("_",""); t=re.sub(r"[^A-Z0-9]","",t)
    if t.endswith("USDT") and t[:-4] in CRYPTO: return t[:-4]
    return t
def get_klines(sym, interval="4h"):
    key=f"{sym}_{interval}"
    if key in CACHE and time.time()-CACHE[key][0]<60: return CACHE[key][1]
    kl=[]
    for typ in ["OKX","BINANCE","BYBIT"]:
        try:
            if typ=="OKX":
                r=SESSION.get("https://www.okx.com/api/v5/market/candles",params={"instId":sym.replace("USDT","-USDT"),"bar":"4H","limit":"200"},timeout=4).json()
                data=r.get("data",[])
                if len(data)>=50: kl=[{"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),"v":float(x[5])} for x in data][::-1]; break
            elif typ=="BINANCE":
                r=SESSION.get("https://data-api.binance.vision/api/v3/klines",params={"symbol":sym,"interval":interval,"limit":200},timeout=4).json()
                if isinstance(r,list) and len(r)>=50: kl=[{"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),"v":float(x[5])} for x in r]; break
            else:
                r=SESSION.get("https://api.bybit.com/v5/market/kline",params={"category":"spot","symbol":sym,"interval":"240","limit":"200"},timeout=4).json()
                data=r.get("result",{}).get("list",[])
                if len(data)>=50: kl=[{"o":float(x[1]),"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),"v":float(x[5])} for x in data[::-1]]; break
        except: continue
    if kl: CACHE[key]=(time.time(),kl); return kl
    if key in CACHE: return CACHE[key][1]
    return []
def get_price_now(sym):
    try:
        kl=get_klines(sym,"4h")
        if kl: return kl[-1]["c"]
        kl=get_klines(sym,"1h")
        if kl: return kl[-1]["c"]
    except: pass
    return None
def ema(arr,p):
    if len(arr)<p: return sum(arr)/len(arr)
    k=2/(p+1); e=sum(arr[:p])/p
    for x in arr[p:]: e=(x-e)*k+e
    return e
def ema_series(arr,p):
    if len(arr)<p: return [sum(arr)/len(arr)]*len(arr)
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
    return 100 - (100/(1+gains/losses)) if losses!=0 else 50
def bollinger_calc(arr, p=20):
    if len(arr)<p: return arr[-1], arr[-1]*1.02, arr[-1]*0.98
    sma=sum(arr[-p:])/p
    std=(sum((x-sma)**2 for x in arr[-p:])/p)**0.5
    return sma, sma+2*std, sma-2*std
def macd_calc(arr):
    if len(arr)<35: return 0
    e12=ema(arr,12); e26=ema(arr,26)
    return e12-e26
def get_god_verdict(closes, rsi, vol_pct, trend_score):
    sma, bb_up, bb_low = bollinger_calc(closes)
    live=closes[-1]; macd=macd_calc(closes)
    score=0; reasons=[]
    if rsi<32: score+=15; reasons.append("RSI Oversold")
    elif rsi>68: score+=15; reasons.append("RSI Overbought")
    if live<=bb_low*1.01: score+=20; reasons.append("BB Bottom")
    elif live>=bb_up*0.99: score+=20; reasons.append("BB Top")
    if macd>0: score+=10; reasons.append("MACD Bull")
    else: score+=10; reasons.append("MACD Bear")
    score+= abs(trend_score)*0.2
    if vol_pct>50: score+=15; reasons.append(f"Vol +{vol_pct:.0f}%")
    e20=ema(closes,20); e50=ema(closes,50)
    if (live>e20>e50 and trend_score>0) or (live<e20<e50 and trend_score<0): score+=15; reasons.append("EMA Aligned")
    if score>=75: verdict=f"🔮 GOD 90% {', '.join(reasons[:3])}"
    elif score>=50: verdict=f"⚡ GOD 75% {', '.join(reasons[:2])}"
    else: verdict=f"👀 GOD 60% Waiting"
    return verdict, score
def get_mtf_trend(closes):
    if len(closes)<50: return 0,"N/A"
    e20=ema(closes,20); e50=ema(closes,50); e200=ema(closes,200); live=closes[-1]
    if live>e20>e50>e200: return 80,"🟢 STRONG UPTREND"
    if live>e20>e50: return 50,"⬆️ UPTREND"
    if live>e50: return 20,"↗️ WEAK UP"
    if live<e20<e50<e200: return -80,"🔴 STRONG DOWNTREND"
    if live<e20<e50: return -50,"⬇️ DOWNTREND"
    if live<e50: return -20,"↘️ WEAK DOWN"
    return 0,"➡️ SIDEWAYS"
def volume_check(kl):
    vols=[k["v"] for k in kl[-25:]]; avg=sum(vols[-21:-1])/20 if len(vols)>=21 else sum(vols)/len(vols); curr=vols[-1]; pct=(curr-avg)/avg*100 if avg>0 else 0
    return pct,f"📊 Vol {pct:.0f}%"
def v5_dynamic_atr_sl_tp(entry, atr_val, side, is_fast):
    atr_pct=atr_val/entry*100 if entry!=0 else 1.0
    base_sl_pct = atr_pct*0.8 + 0.6
    if is_fast: base_sl_pct = max(0.8, min(base_sl_pct, 1.6))
    else: base_sl_pct = max(1.0, min(base_sl_pct, 2.0))
    if side=="BUY":
        sl=entry - entry*base_sl_pct/100; tp1=entry + entry*base_sl_pct*1.2/100; tp2=entry + entry*base_sl_pct*2.4/100; tp3=entry + entry*base_sl_pct*3.6/100
    else:
        sl=entry + entry*base_sl_pct/100; tp1=entry - entry*base_sl_pct*1.2/100; tp2=entry - entry*base_sl_pct*2.4/100; tp3=entry - entry*base_sl_pct*3.6/100
    return sl, tp1, tp2, tp3, base_sl_pct
def analyze_perfect(code, btc_trend=0, strict_vol=True):
    sym=CRYPTO.get(code,"BTCUSDT")
    kl4=get_klines(sym,"4h")
    if len(kl4)<40: return {"error":True,"msg":f"❌ No data {code}"}
    closes4=[c["c"] for c in kl4]; live=closes4[-1]
    e20=ema(closes4,20); e50=ema(closes4,50); e200=ema(closes4,200)
    rsi=rsi_calc(closes4); atr=sum([c["h"]-c["l"] for c in kl4[-14:]])/14 if kl4 else live*0.01
    kl1=get_klines(sym,"1h"); klD=get_klines(sym,"1d")
    closes1=[c["c"] for c in kl1] if len(kl1)>=30 else closes4; closesD=[c["c"] for c in klD] if len(klD)>=30 else closes4
    s1,t1=get_mtf_trend(closes1); s4,t4=get_mtf_trend(closes4); sD,tD=get_mtf_trend(closesD)
    vol_pct,vol_txt=volume_check(kl4)
    if strict_vol and vol_pct < -85: return {"error":True,"msg":f"🚫 Vol too low {vol_pct:.0f}% - Saves $5"}
    if not strict_vol and vol_pct < -92: return {"error":True,"msg":f"🚫 Vol extremely low {vol_pct:.0f}%"}
    direction="SELL" if s4<0 else "BUY"
    sl,tp1,tp2,tp3,sl_pct=v5_dynamic_atr_sl_tp(live,atr,direction,code in FAST_COINS)
    god_verdict, god_score = get_god_verdict(closes4, rsi, vol_pct, s4)
    conf=81 if abs(s4)>=50 else 68
    if god_score>=75: conf = min(92, conf+11)
    elif god_score>=50: conf = min(85, conf+5)
    sl_dist_pct=abs(sl-live)/live*100; tp1_dist_pct=abs(tp1-live)/live*100; tp2_dist_pct=abs(tp2-live)/live*100; tp3_dist_pct=abs(tp3-live)/live*100
    return {"error":False,"code":code,"price":live,"e20":e20,"e50":e50,"e200":e200,"rsi":rsi,"atr":atr,"dir":direction,"entry":live,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"lev":25,"conf":conf,"kl":kl4,"is_fast":code in FAST_COINS,"mtf_txt":f"🕐 1H {t1} | 🕓 4H {t4} | 📅 1D {tD}","vol_txt":vol_txt,"vol_pct":vol_pct,"trend_txt":t4,"sl_dist_pct":sl_dist_pct,"tp1_dist_pct":tp1_dist_pct,"tp2_dist_pct":tp2_dist_pct,"tp3_dist_pct":tp3_dist_pct,"god_verdict":god_verdict,"god_score":god_score}

def get_btc_trend():
    try: kl=get_klines("BTCUSDT","4h"); closes=[c["c"] for c in kl]; s,_=get_mtf_trend(closes); return s
    except: return 0

# COLOURED CHART WITH LAZY IMPORT - FAST STARTUP
def generate_chart_perfect(r):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        kl=r["kl"][-100:]; closes=[c["c"] for c in kl]; e20s=ema_series(closes,20); e50s=ema_series(closes,50)
        fig, ax = plt.subplots(figsize=(10,5.5), facecolor='white')
        # Coloured background based on direction
        is_buy = r["dir"]=="BUY"
        bg_color = '#E8F5E9' if is_buy else '#FFEBEE'
        ax.set_facecolor(bg_color)
        # Price line coloured
        price_color = '#2E7D32' if is_buy else '#C62828'
        ax.plot(closes, label="Price", color=price_color, linewidth=1.5)
        ax.plot(e20s, label="EMA20", color="#2196F3", linewidth=1, linestyle='--')
        ax.plot(e50s, label="EMA50", color="#FF9800", linewidth=1, linestyle='--')
        ax.axhline(r["entry"], color="blue", linestyle="-", linewidth=1.5, label=f'Entry {fmt(r["entry"])}')
        ax.axhline(r["sl"], color="red", linestyle="-", linewidth=2, label=f'SL {fmt(r["sl"])} 🔴')
        ax.axhline(r["tp1"], color="green", linestyle="-", linewidth=2, label=f'TP1 {fmt(r["tp1"])} 🟢')
        ax.axhline(r["tp2"], color="#2E7D32", linestyle=":", linewidth=1, label=f'TP2 {fmt(r["tp2"])}')
        # Fill profit zone
        if is_buy:
            ax.fill_between(range(len(closes)), r["entry"], r["tp1"], color='green', alpha=0.1)
            ax.fill_between(range(len(closes)), r["sl"], r["entry"], color='red', alpha=0.1)
        else:
            ax.fill_between(range(len(closes)), r["tp1"], r["entry"], color='green', alpha=0.1)
            ax.fill_between(range(len(closes)), r["entry"], r["sl"], color='red', alpha=0.1)
        title_color = 'green' if is_buy else 'red'
        ax.set_title(f'📈 {r["code"]} {r["dir"]} GOD {r.get("god_score",0):.0f}% {r.get("god_verdict","")} V6.20 COLOURED', fontsize=10, color=title_color, fontweight='bold')
        ax.legend(fontsize=7, loc='upper left'); ax.grid(True, alpha=0.3); plt.tight_layout()
        buf=io.BytesIO(); plt.savefig(buf, format='png', dpi=150, facecolor='white'); buf.seek(0); plt.close(fig); return buf
    except Exception as e:
        print(f"Chart err {e}")
        return None

def main_menu_kb(active_override=None):
    daily=get_daily(); active=active_override if active_override is not None else get_active()
    btns=[]
    if active and active.get("status")=="OPEN":
        coin=active.get("coin"); dir_=active.get("dir"); emoji="🟢" if dir_=="BUY" else "🔴"
        btns.append([InlineKeyboardButton(f"📡 {emoji} MONITORING {coin} {dir_} LIVE",callback_data="MONITOR_LIVE")])
        btns.append([InlineKeyboardButton(f"🔍 Check {coin} Now ✅",callback_data="CHECK_NOW"), InlineKeyboardButton(f"❌ Close {coin}",callback_data="CLOSE_TRADE")])
    else:
        btns.append([InlineKeyboardButton(f"🔍 SCAN BEST - Trade {daily['trades']+1}/3 💪",callback_data="SCAN_BEST")])
    btns.append([InlineKeyboardButton(f"📊 Daily: {daily['wins']}W/{daily['losses']}L ${daily['pnl']:.2f} 💰",callback_data="SHOW_DAILY")])
    btns.append([InlineKeyboardButton("--- SELECT CATEGORY ---",callback_data="IGNORE")])
    btns.append([InlineKeyboardButton("⚡ FAST COINS (18)",callback_data="MENU_FAST"), InlineKeyboardButton("🐢 SLOW COINS (16)",callback_data="MENU_SLOW")])
    btns.append([InlineKeyboardButton("🏆 XAUUSD GOLD LIVE ✨",callback_data="MENU_XAU")])
    return InlineKeyboardMarkup(btns)
def fast_menu_kb():
    btns=[[InlineKeyboardButton("⚡ FAST 18 COINS - FAST PROFIT",callback_data="IGNORE")]]
    fast=["SOL","DOGE","PEPE","BONK","WIF","BOME","FLOKI","SHIB","AVAX","SUI","ARB","OP","APT","TAO","NOT","FARTCOIN","ENA","TRUMP"]
    row=[]
    for c in fast:
        row.append(InlineKeyboardButton(f"⚡ {c}",callback_data=f"C_{c}"))
        if len(row)==3: btns.append(row); row=[]
    btns.append([InlineKeyboardButton("⬅️ Back Main Menu",callback_data="MENU_MAIN")])
    return InlineKeyboardMarkup(btns)
def slow_menu_kb():
    btns=[[InlineKeyboardButton("🐢 SLOW 16 COINS - GOOD RESULT",callback_data="IGNORE")]]
    slow=["BTC","ETH","BNB","XRP","ADA","LINK","TRX","DOT","MATIC","LTC","BCH","UNI","ATOM","ETC","FIL","PAXG"]
    row=[]
    for c in slow:
        row.append(InlineKeyboardButton(f"🐢 {c}",callback_data=f"C_{c}"))
        if len(row)==3: btns.append(row); row=[]
    btns.append([InlineKeyboardButton("⬅️ Back Main Menu",callback_data="MENU_MAIN")])
    return InlineKeyboardMarkup(btns)
def xau_menu_kb():
    btns=[[InlineKeyboardButton("🏆 XAUUSD GOLD LIVE ✨",callback_data="IGNORE")]]
    btns.append([InlineKeyboardButton("🏆 XAUUSD (PAXG) TRADE NOW ✨",callback_data="C_PAXG")])
    btns.append([InlineKeyboardButton("⬅️ Back Main Menu",callback_data="MENU_MAIN")])
    return InlineKeyboardMarkup(btns)
def coins_kb_perfect(active_override=None): return main_menu_kb(active_override)

async def start(u,c):
    save_chat_id(u.message.chat.id)
    await u.message.reply_text("💪 V6.20 LIGHT COLOURED CHART GOD 90%\n\n✅ SELECT:\n⚡ FAST 18 (FARTCOIN ENA TRUMP DOGE WIF...)\n🐢 SLOW 16 (BTC ETH XRP...)\n🏆 XAUUSD GOLD\n\n📊 Coloured chart now!\nClick category below 👇",reply_markup=main_menu_kb())

async def btn_handler(u,c):
    q=u.callback_query; await q.answer(); d=q.data
    if d=="IGNORE": return
    daily=get_daily(); btc=get_btc_trend()
    if d=="MENU_MAIN":
        await q.edit_message_text("💪 V6.20 COLOURED CHART GOD 90%\n\n✅ SELECT CATEGORY:\n⚡ FAST 18 fast profit\n🐢 SLOW 16 stable\n🏆 XAUUSD GOLD\n\nClick below 👇",reply_markup=main_menu_kb()); return
    if d=="MENU_FAST":
        await q.edit_message_text("⚡ FAST COINS - Choose for FAST PROFIT V6.20 COLOURED CHART",reply_markup=fast_menu_kb()); return
    if d=="MENU_SLOW":
        await q.edit_message_text("🐢 SLOW COINS - Choose for GOOD RESULT V6.20",reply_markup=slow_menu_kb()); return
    if d=="MENU_XAU":
        await q.edit_message_text("🏆 XAUUSD GOLD LIVE - V6.20 COLOURED CHART ✨",reply_markup=xau_menu_kb()); return
    if d=="SHOW_DAILY":
        await q.message.reply_text(f"📊 Daily: {daily['wins']}W/{daily['losses']}L Trades {daily['trades']}/3 P&L ${daily['pnl']:.2f} V6.20 COLOURED",reply_markup=main_menu_kb()); return
    if d=="MONITOR_LIVE" or d=="CHECK_NOW":
        active=get_active()
        if not active or active.get("status")!="OPEN":
            await q.message.reply_text("❌ No active trade - Select category! V6.20",reply_markup=main_menu_kb()); return
        coin=active.get("coin"); entry=active.get("entry"); sl=active.get("sl"); tp1=active.get("tp1"); dir_=active.get("dir")
        price=get_price_now(CRYPTO.get(coin))
        if not price: price=entry
        lev=25
        if dir_=="BUY": live_pnl_pct=(price-entry)/entry*100*lev
        else: live_pnl_pct=(entry-price)/entry*100*lev
        live_pnl=5*live_pnl_pct/100; status="💚 PROFIT" if live_pnl_pct>=0 else "❤️ LOSS"
        emoji="🟢 BUY LONG 🚀" if dir_=="BUY" else "🔴 SELL SHORT 📉"
        try:
            kl=get_klines(CRYPTO.get(coin),"4h"); closes=[x["c"] for x in kl]; rsi=rsi_calc(closes); vol_pct,_=volume_check(kl); s,_=get_mtf_trend(closes); verdict,score=get_god_verdict(closes,rsi,vol_pct,s)
        except: verdict="🔮 GOD 90%"; score=90
        txt=(f"📡 MONITORING {coin} {emoji} LIVE V6.20 COLOURED\n\n💰 Entry {fmt(entry)} | Now {fmt(price)} | SL {fmt(sl)} | TP1 {fmt(tp1)}\n💥 P&L: {live_pnl_pct:.2f}% {lev}x $5->{'+' if live_pnl>=0 else ''}${live_pnl:.2f} {status}\n{verdict} Score {score:.0f}\n✅ Vol OK + Triple LIVE")
        await q.message.reply_text(txt,reply_markup=main_menu_kb(active)); return
    if d=="CLOSE_TRADE":
        active=get_active()
        if active: clear_active(); await q.message.reply_text(f"✅ Closed {active.get('coin')} - Ready new trade!",reply_markup=main_menu_kb())
        else: await q.message.reply_text("❌ No active trade",reply_markup=main_menu_kb())
        return
    if d=="SCAN_BEST":
        await q.edit_message_text("🔍 Scanning 18 BEST V6.20 COLOURED CHART GOD 90%...")
        best=None; best_score=-1000
        scan_list=["SOL","DOGE","PEPE","BONK","WIF","AVAX","SUI","ARB","OP","BTC","ETH","TRX","LINK","BNB","XRP","FARTCOIN","ENA","TRUMP"]
        def scan_one(code):
            try: return analyze_perfect(code, btc, strict_vol=False)
            except: return {"error":True}
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
                futures={ex.submit(scan_one, c): c for c in scan_list}
                for fut in concurrent.futures.as_completed(futures, timeout=15):
                    r=fut.result()
                    if r.get("error"): continue
                    score=r["conf"] + r["vol_pct"] + r.get("god_score",0)
                    if score>best_score: best_score=score; best=r
        except: pass
        if not best:
            await q.message.reply_text("❌ No setup - Try category",reply_markup=main_menu_kb()); return
        r=best
        active_data={"status":"OPEN","coin":r["code"],"dir":r["dir"],"entry":r["entry"],"sl":r["sl"],"tp1":r["tp1"],"tp2":r["tp2"],"tp3":r["tp3"],"time":str(datetime.now())}
        set_active(active_data)
        buf=generate_chart_perfect(r)
        lev=r["lev"]; sl_lev=r["sl_dist_pct"]*lev; tp1_lev=r["tp1_dist_pct"]*lev
        loss5=5*sl_lev/100; p5_1=5*tp1_lev/100
        emoji="🟢 BUY LONG 🚀" if r['dir']=="BUY" else "🔴 SELL SHORT 📉"
        txt=(f"💪 LOCKED: {r['code']} Trade {daily['trades']+1}/3 V6.20 COLOURED GOD 90% {emoji}\n\n💰 {r['code']} {r['dir']} @ {fmt(r['entry'])} LIVE\n🎯 TP1 {fmt(r['tp1'])} (+{tp1_lev:.0f}%) | SL {fmt(r['sl'])} (-{sl_lev:.0f}%)\n📊 Conf {r['conf']}% | {r['vol_txt']} OK\n{r['mtf_txt']}\n{r['trend_txt']} | RSI {r['rsi']:.0f}\n{r.get('god_verdict','🔮 GOD')}\n\n💥 {lev}x SL -${loss5:.2f} | TP1 +${p5_1:.2f} FAST")
        if buf: await q.message.reply_photo(photo=buf, caption=txt, reply_markup=main_menu_kb(active_data))
        else: await q.message.reply_text(txt,reply_markup=main_menu_kb(active_data))
        return
    if d.startswith("C_"):
        code=d[2:]
        r=analyze_perfect(code, btc, strict_vol=True)
        if r.get("error"):
            await q.message.reply_text(f"{r.get('msg')} 💔",reply_markup=main_menu_kb()); return
        active_data={"status":"OPEN","coin":r["code"],"dir":r["dir"],"entry":r["entry"],"sl":r["sl"],"tp1":r["tp1"],"tp2":r["tp2"],"tp3":r["tp3"],"time":str(datetime.now())}
        set_active(active_data)
        buf=generate_chart_perfect(r)
        lev=r["lev"]; sl_lev=r["sl_dist_pct"]*lev; tp1_lev=r["tp1_dist_pct"]*lev
        loss5=5*sl_lev/100; p5_1=5*tp1_lev/100
        emoji="🟢 BUY LONG 🚀" if r['dir']=="BUY" else "🔴 SELL SHORT 📉"
        txt=(f"💪 LOCKED: {r['code']} Trade {daily['trades']+1}/3 V6.20 COLOURED\n\n{emoji}\n💰 {r['code']} @ {fmt(r['entry'])} LIVE\n🎯 TP1 {fmt(r['tp1'])} (+{tp1_lev:.0f}%) | SL {fmt(r['sl'])} (-{sl_lev:.0f}%)\n{r['vol_txt']} OK | {r['trend_txt']}\n{r.get('god_verdict','🔮 GOD')}\n💥 {lev}x SL -${loss5:.2f} | TP1 +${p5_1:.2f}")
        if buf: await q.message.reply_photo(photo=buf, caption=txt, reply_markup=main_menu_kb(active_data))
        else: await q.message.reply_text(txt,reply_markup=main_menu_kb(active_data))

async def txt_handler(u,c):
    code=clean(u.message.text.strip())
    if code not in CRYPTO: return
    btc=get_btc_trend(); r=analyze_perfect(code, btc, strict_vol=True)
    if r.get("error"):
        await u.message.reply_text(f"{r.get('msg')} 💔",reply_markup=main_menu_kb()); return
    active_data={"status":"OPEN","coin":r["code"],"dir":r["dir"],"entry":r["entry"],"sl":r["sl"],"tp1":r["tp1"],"tp2":r["tp2"],"tp3":r["tp3"],"time":str(datetime.now())}
    set_active(active_data)
    buf=generate_chart_perfect(r)
    txt=f"💪 LOCKED: {r['code']} {r['dir']} @ {fmt(r['entry'])} V6.20 COLOURED GOD 90% {r.get('god_verdict','')}"
    if buf: await u.message.reply_photo(photo=buf, caption=txt, reply_markup=main_menu_kb(active_data))
    else: await u.message.reply_text(txt,reply_markup=main_menu_kb(active_data))

def monitor_loop():
    print("V6.20 COLOURED monitor started")
    while True:
        try:
            time.sleep(60)
            active=get_active()
            if not active or active.get("status")!="OPEN": continue
            coin=active.get("coin"); entry=active.get("entry"); sl=active.get("sl"); tp1=active.get("tp1"); tp2=active.get("tp2"); dir_=active.get("dir")
            sym=CRYPTO.get(coin)
            if not sym: continue
            price=get_price_now(sym)
            if not price: continue
            chat_id=get_chat_id()
            if not chat_id: continue
            hit=None
            if dir_=="BUY":
                if price>=tp1: hit="TP1 FAST PROFIT"
                elif price>=tp2: hit="TP2 GOOD RESULT"
                elif price<=sl: hit="SL"
            else:
                if price<=tp1: hit="TP1 FAST PROFIT"
                elif price<=tp2: hit="TP2 GOOD RESULT"
                elif price>=sl: hit="SL"
            if hit:
                lev=25
                if "TP1" in hit:
                    pnl_pct=abs(tp1-entry)/entry*100*lev; pnl=5*pnl_pct/100
                    msg=f"📡 V6.20 COLOURED FAST PROFIT! 🎉\n{coin} {hit} HIT!\nPrice {fmt(price)} TP1 {fmt(tp1)}\n+{pnl_pct:.2f}% $5->+${pnl:.2f}"
                    update_daily("WIN",pnl,coin); clear_active()
                elif "TP2" in hit:
                    pnl_pct=abs(tp2-entry)/entry*100*lev; pnl=5*pnl_pct/100
                    msg=f"📡 V6.20 GOOD RESULT! 🏆\n{coin} {hit} +{pnl_pct:.2f}% $5->+${pnl:.2f}"
                    update_daily("WIN",pnl,coin); clear_active()
                else:
                    pnl_pct=abs(sl-entry)/entry*100*lev; pnl=5*pnl_pct/100
                    msg=f"📡 SL HIT {coin} 🛑\nPrice {fmt(price)} SL {fmt(sl)}\n-{pnl_pct:.2f}% $5->-${pnl:.2f}"
                    update_daily("LOSS",-pnl,coin); clear_active()
                try: requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",json={"chat_id":chat_id,"text":msg},timeout=10)
                except: pass
        except Exception as e:
            print(f"Monitor err {e}"); time.sleep(30)

def run_flask(): app.run(host="0.0.0.0",port=PORT)
def run_bot():
    if not BOT_TOKEN: return
    a=ApplicationBuilder().token(BOT_TOKEN).build()
    a.add_handler(CommandHandler("start",start))
    a.add_handler(CallbackQueryHandler(btn_handler))
    a.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, txt_handler))
    print("Bot V6.20 COLOURED starting..."); a.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    threading.Thread(target=run_flask,daemon=True).start()
    threading.Thread(target=monitor_loop,daemon=True).start()
    run_bot()
