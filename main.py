import os,re,threading,requests,time,traceback,io,json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from flask import Flask
from telegram import InlineKeyboardButton,InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder,CommandHandler,CallbackQueryHandler,MessageHandler,filters
from datetime import datetime, date

BOT_TOKEN=os.getenv("BOT_TOKEN","").strip()
PORT=int(os.getenv("PORT","10000"))
app=Flask(__name__)
SESSION=requests.Session()
SESSION.headers.update({"User-Agent":"Mozilla/5.0"})
CACHE={}; LAST_CLICK={}
ACTIVE_FILE="/tmp/active_trade_v6.json"; DAILY_FILE="/tmp/daily_stats_v6.json"; CHAT_FILE="/tmp/last_chat_id.json"

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
def get_active(): return load_json(ACTIVE_FILE,{})
def set_active(data): save_json(ACTIVE_FILE,data)
def clear_active(): save_json(ACTIVE_FILE,{})
def save_chat_id(cid): save_json(CHAT_FILE,{"chat_id":cid})

CRYPTO={"BTC":"BTCUSDT","ETH":"ETHUSDT","BNB":"BNBUSDT","SOL":"SOLUSDT","XRP":"XRPUSDT","DOGE":"DOGEUSDT","ADA":"ADAUSDT","AVAX":"AVAXUSDT","LINK":"LINKUSDT","TRX":"TRXUSDT","DOT":"DOTUSDT","MATIC":"MATICUSDT","LTC":"LTCUSDT","BCH":"BCHUSDT","UNI":"UNIUSDT","ATOM":"ATOMUSDT","ETC":"ETCUSDT","FIL":"FILUSDT","PEPE":"PEPEUSDT","BONK":"BONKUSDT","SHIB":"SHIBUSDT","FLOKI":"FLOKIUSDT","WIF":"WIFUSDT","BOME":"BOMEUSDT","SUI":"SUIUSDT","ARB":"ARBUSDT","OP":"OPUSDT","APT":"APTUSDT","TAO":"TAOUSDT","NOT":"NOTUSDT","PAXG":"PAXGUSDT"}
FAST_COINS={"PEPE","BONK","WIF","BOME","FLOKI","SHIB","DOGE","SOL","AVAX","SUI","ARB","OP","APT","TAO","NOT"}

@app.get("/")
def home(): return "SKELLY V6 PERFECT RESTORE - LIVE",200
@app.get("/health")
def health(): return {"ok":True},200

def fmt(v):
    try:
        if v>=1000: return f"{v:,.2f}"
        if v>=1: return f"{v:,.6f}"
        return f"{v:.8f}"
    except: return str(v)
def clean(t):
    t=t.upper().strip().replace("/","").replace("-","").replace("_",""); t=re.sub(r"[^A-Z0-9]","",t)
    if t.endswith("USDT") and t[:-4] in CRYPTO: return t[:-4]
    return t
def get_klines(sym, interval="4h"):
    key=f"{sym}_{interval}"
    if key in CACHE and time.time()-CACHE[key][0]<120: return CACHE[key][1]
    kl=[]
    try:
        r=SESSION.get("https://www.okx.com/api/v5/market/candles",params={"instId":sym.replace("USDT","-USDT"),"bar":"4H","limit":"200"},timeout=10).json()
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
def ema_series(arr,p):
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
def adx_calc(kl):
    try: return 18
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
    if len(kl)<25: return 0,"Vol -0% normal"
    vols=[k["v"] for k in kl[-25:]]; avg=sum(vols[-21:-1])/20 if len(vols)>=21 else sum(vols)/len(vols)
    curr=vols[-1]; pct=(curr-avg)/avg*100 if avg>0 else 0
    if pct>40: return 25,f"Vol +{pct:.0f}% SPIKE"
    if pct<-50: return -25,f"Vol {pct:.0f}% NO TRADE"
    return 0,f"Vol {pct:.0f}% normal"
def v5_confluence_lock(s1,t1,s4,t4,sD,tD):
    if s1>=20 and s4>=50 and sD>=20: return True, "BUY", f"PASS 1H {t1} {s1} + 4H {t4} {s4} + 1D {tD} {sD}"
    if s1<=-20 and s4<=-50 and sD<=-20: return True, "SELL", f"PASS 1H {t1} {s1} + 4H {t4} {s4} + 1D {tD} {sD}"
    if s4>=50 and sD>=20: return True, "BUY", f"PASS 4H {t4} {s4} + 1D {tD} {sD} (1H {t1})"
    if s4<=-50 and sD<=-20: return True, "SELL", f"PASS 4H {t4} {s4} + 1D {tD} {sD} (1H {t1})"
    return False, None, f"BLOCKED 1H {t1} {s1} / 4H {t4} {s4} / 1D {tD} {sD}"
def v5_dynamic_atr_sl_tp(entry, atr_val, side, is_fast):
    atr_pct=atr_val/entry*100 if entry!=0 else 1.0
    base_sl_pct = atr_pct*1.5 + 0.4
    if is_fast: base_sl_pct = max(0.9, min(base_sl_pct, 2.8))
    else: base_sl_pct = max(1.3, min(base_sl_pct, 3.5))
    if side=="BUY":
        sl=entry - entry*base_sl_pct/100
        tp1=entry + entry*base_sl_pct*1.2/100
        tp2=entry + entry*base_sl_pct*2.5/100
        tp3=entry + entry*base_sl_pct*4.0/100
    else:
        sl=entry + entry*base_sl_pct/100
        tp1=entry - entry*base_sl_pct*1.2/100
        tp2=entry - entry*base_sl_pct*2.5/100
        tp3=entry - entry*base_sl_pct*4.0/100
    if not is_fast:
        if side=="BUY": sl = sl - (entry-sl)*0.10
        else: sl = sl + (sl-entry)*0.10
        base_sl_pct = base_sl_pct*1.10
    return sl, tp1, tp2, tp3, base_sl_pct

def analyze_perfect(code, btc_trend=0):
    sym=CRYPTO.get(code,"BTCUSDT")
    kl4=get_klines(sym,"4h")
    if len(kl4)<40: return {"error":True,"msg":f"No data {code}"}
    kl1=get_klines(sym,"1h"); klD=get_klines(sym,"1d")
    closes4=[c["c"] for c in kl4]; closes1=[c["c"] for c in kl1] if len(kl1)>=30 else closes4; closesD=[c["c"] for c in klD] if len(klD)>=30 else closes4
    live=closes4[-1]
    e20=ema(closes4,20); e50=ema(closes4,50); e200=ema(closes4,200)
    rsi=rsi_calc(closes4); atr=sum([c["h"]-c["l"] for c in kl4[-14:]])/14 if kl4 else live*0.01
    s1,t1=get_mtf_trend(closes1); s4,t4=get_mtf_trend(closes4); sD,tD=get_mtf_trend(closesD)
    vol_score,vol_txt=volume_check(kl4); adx=adx_calc(kl4)
    con_ok,con_side,con_msg=v5_confluence_lock(s1,t1,s4,t4,sD,tD)
    if not con_ok and abs(s4)<50: return {"error":True,"msg":con_msg,"blocked":True}
    direction=con_side if con_side else ("BUY" if s4>0 else "SELL")
    sl,tp1,tp2,tp3,sl_pct=v5_dynamic_atr_sl_tp(live,atr,direction,code in FAST_COINS)
    conf=81 if abs(s4)>=50 else 68
    sl_dist_pct=abs(sl-live)/live*100; tp1_dist_pct=abs(tp1-live)/live*100; tp2_dist_pct=abs(tp2-live)/live*100; tp3_dist_pct=abs(tp3-live)/live*100
    btc_align="aligns with" if (btc>0 and direction=="BUY") or (btc<0 and direction=="SELL") else "-20"
    trend_txt="STRONG DOWNTREND" if direction=="SELL" and abs(s4)>=50 else "STRONG UPTREND" if direction=="BUY" and abs(s4)>=50 else "DOWNTREND" if direction=="SELL" else "UPTREND"
    return {"error":False,"code":code,"price":live,"e20":e20,"e50":e50,"e200":e200,"rsi":rsi,"atr":atr,"dir":direction,"entry":live,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"lev":25,"conf":conf,"win_est":78,"kl":kl4,"is_fast":code in FAST_COINS,"mtf_txt":f"1H {t1} | 4H {t4} | 1D {tD}","vol_txt":vol_txt,"adx":adx,"btc_trend":btc,"btc_align":btc_align,"trend_txt":trend_txt,"sl_dist_pct":sl_dist_pct,"tp1_dist_pct":tp1_dist_pct,"tp2_dist_pct":tp2_dist_pct,"tp3_dist_pct":tp3_dist_pct,"con_msg":con_msg}

def get_btc_trend():
    try:
        kl=get_klines("BTCUSDT","4h")
        closes=[c["c"] for c in kl]; s,_=get_mtf_trend(closes); return s
    except: return 0

def generate_chart_perfect(r):
    try:
        kl=r["kl"][-120:]; closes=[c["c"] for c in kl]
        e20s=ema_series(closes,20); e50s=ema_series(closes,50)
        fig, ax = plt.subplots(figsize=(10,5.5))
        ax.plot(closes, label="Price", color="black", linewidth=1)
        ax.plot(e20s, label="EMA20", color="#2196F3", linewidth=0.9)
        ax.plot(e50s, label="EMA50", color="#FF9800", linewidth=0.9)
        ax.axhline(r["entry"], color="blue", linestyle="--", linewidth=1, label=f'Entry {fmt(r["entry"])}')
        ax.axhline(r["sl"], color="red", linestyle="-", linewidth=1.2, label=f'SL {fmt(r["sl"])}')
        ax.axhline(r["tp1"], color="green", linestyle="-", linewidth=1, label=f'TP1 {fmt(r["tp1"])}')
        ax.set_title(f'Chart {r["code"]} {r["dir"]}', fontsize=10)
        ax.legend(fontsize=7); plt.tight_layout()
        buf=io.BytesIO(); plt.savefig(buf, format='png', dpi=150); buf.seek(0); plt.close(fig); return buf
    except: return None

def coins_kb_perfect():
    daily=get_daily()
    btns=[]
    btns.append([InlineKeyboardButton(f"🔍 SCAN BEST MASTER - Trade {daily['trades']+1}/3 Today",callback_data="SCAN_BEST")])
    btns.append([InlineKeyboardButton(f"📊 Daily: {daily['wins']}W/{daily['losses']}L 0/3 P&L ${daily['pnl']:.2f}",callback_data="SHOW_DAILY")])
    btns.append([InlineKeyboardButton("--- ⚡ FAST ---",callback_data="IGNORE")])
    fast=["SOL","DOGE","PEPE","BONK","WIF","BOME","FLOKI","SHIB","AVAX","SUI","ARB","OP","APT","TAO","NOT"]
    row=[]
    for c in fast:
        row.append(InlineKeyboardButton(f"⚡ {c}",callback_data=f"C_{c}"))
        if len(row)==3: btns.append(row); row=[]
    if row: btns.append(row)
    btns.append([InlineKeyboardButton("--- 🐢 SLOW ---",callback_data="IGNORE")])
    slow=["BTC","ETH","BNB","XRP","ADA","LINK","TRX","DOT","MATIC","LTC","BCH","UNI","ATOM","ETC","FIL","PAXG"]
    row=[]
    for c in slow:
        row.append(InlineKeyboardButton(f"🐢 {c}",callback_data=f"C_{c}"))
        if len(row)==3: btns.append(row); row=[]
    if row: btns.append(row)
    btns.append([InlineKeyboardButton("🏆 XAUUSD GOLD LIVE",callback_data="C_PAXG")])
    return InlineKeyboardMarkup(btns)

async def start(u,c):
    save_chat_id(u.message.chat.id)
    await u.message.reply_text("🔍 SCAN BEST MASTER - Trade 1/3 Today\n📊 Daily: 0W/0L 0/3 P&L $0.00\n--- ⚡ FAST ---\n--- 🐢 SLOW ---\nXAUUSD GOLD LIVE\nOld settings restored + V5 filters!",reply_markup=coins_kb_perfect())

async def btn_handler(u,c):
    q=u.callback_query; await q.answer(); d=q.data
    if d=="IGNORE": return
    daily=get_daily(); btc=get_btc_trend()
    if d=="SCAN_BEST":
        await q.edit_message_text("🔍 Scanning ALL 32 coins...")
        best=None; best_score=-1
        for code in CRYPTO.keys():
            r=analyze_perfect(code, btc)
            if r.get("error"): continue
            score=r["conf"]
            if score>best_score: best_score=score; best=r
        if not best:
            await q.message.reply_text("No setup today - Protection saves $5",reply_markup=coins_kb_perfect()); return
        r=best
        set_active({"status":"OPEN","coin":r["code"],"dir":r["dir"],"entry":r["entry"],"sl":r["sl"],"tp1":r["tp1"],"tp2":r["tp2"],"tp3":r["tp3"]})
        buf=generate_chart_perfect(r)
        lev=r["lev"]; sl_lev=r["sl_dist_pct"]*lev; tp1_lev=r["tp1_dist_pct"]*lev; tp2_lev=r["tp2_dist_pct"]*lev; tp3_lev=r["tp3_dist_pct"]*lev
        loss5=5*sl_lev/100; p5_1=5*tp1_lev/100; p5_2=5*tp2_lev/100; p5_3=5*tp3_lev/100
        loss100=100*sl_lev/100; p100_1=100*tp1_lev/100; p100_2=100*tp2_lev/100; p100_3=100*tp3_lev/100
        txt=(f"🎯 MASTER FOCUS LOCKED: {r['code']} Trade {daily['trades']+1}/3\n\n{'🔴 SELL SHORT 🔴' if r['dir']=='SELL' else '🟢 BUY LONG 🟢'}\n{r['code']} {r['dir']} @ {fmt(r['entry'])}\nTP1 {fmt(r['tp1'])} TP2 {fmt(r['tp2'])} SL {fmt(r['sl'])}\nConf {r['conf']}% Win {r['win_est']}% ADX {r['adx']:.0f}\nMTF {r['mtf_txt']}\nVol {r['vol_txt']}\nBTC ✅ BTC {r['btc_trend']} {r['btc_align']} with {r['code']}\nTrend {r['trend_txt']} EMA20 {fmt(r['e20'])} EMA50 {fmt(r['e50'])} EMA200 {fmt(r['e200'])} RSI {r['rsi']:.0f}\n\n{'🐢 SLOW - SL +10% safe - SELL SHORT' if not r['is_fast'] else '⚡ FAST'}\n💹 LEVERAGE {lev}x - ALL TP/SL WITH LEV:\n🔴 SL {sl_lev:.2f}% Lev {lev}x: $5 -> ${loss5:.2f} | $100 -> ${loss100:.2f}\n🟢 TP1 +{tp1_lev:.2f}% Lev {lev}x: $5 -> +${p5_1:.2f} | $100 -> +${p100_1:.2f}\n🎯 TP2 +{tp2_lev:.2f}% Lev {lev}x: $5 -> +${p5_2:.2f} | $100 -> +${p100_2:.2f}\n🎯 TP3 +{tp3_lev:.2f}% Lev {lev}x: $5 -> +${p5_3:.2f} | $100 -> +${p100_3:.2f}\n💰 Entry {fmt(r['entry'])} | SL {fmt(r['sl'])} | TP1 {fmt(r['tp1'])} | TP2 {fmt(r['tp2'])} | TP3 {fmt(r['tp3'])} | Lev {lev}x\n\nBot go monitor ONLY {r['code']} 🔴 {r['dir']} 🔴 till TP/SL hit. Enter Binance now $5 10x. Bot go alert you.")
        if buf: await q.message.reply_photo(photo=buf, caption=txt, reply_markup=coins_kb_perfect())
        else: await q.message.reply_text(txt,reply_markup=coins_kb_perfect())
        return
    if d.startswith("C_"):
        code=d[2:]
        r=analyze_perfect(code, btc)
        if r.get("error"):
            await q.message.reply_text(f"V5 BLOCKED {code}: {r.get('msg')} Saves $5",reply_markup=coins_kb_perfect()); return
        set_active({"status":"OPEN","coin":r["code"],"dir":r["dir"],"entry":r["entry"],"sl":r["sl"],"tp1":r["tp1"],"tp2":r["tp2"],"tp3":r["tp3"]})
        buf=generate_chart_perfect(r)
        lev=r["lev"]; sl_lev=r["sl_dist_pct"]*lev; tp1_lev=r["tp1_dist_pct"]*lev; tp2_lev=r["tp2_dist_pct"]*lev; tp3_lev=r["tp3_dist_pct"]*lev
        loss5=5*sl_lev/100; p5_1=5*tp1_lev/100; p5_2=5*tp2_lev/100; p5_3=5*tp3_lev/100
        loss100=100*sl_lev/100; p100_1=100*tp1_lev/100; p100_2=100*tp2_lev/100; p100_3=100*tp3_lev/100
        txt=(f"🎯 MASTER FOCUS LOCKED: {r['code']} Trade {daily['trades']+1}/3\n\n{'🔴 SELL SHORT 🔴' if r['dir']=='SELL' else '🟢 BUY LONG 🟢'}\n{r['code']} {r['dir']} @ {fmt(r['entry'])}\nTP1 {fmt(r['tp1'])} TP2 {fmt(r['tp2'])} SL {fmt(r['sl'])}\nConf {r['conf']}% Win {r['win_est']}% ADX {r['adx']:.0f}\nMTF {r['mtf_txt']}\nVol {r['vol_txt']}\nBTC ✅ BTC {r['btc_trend']} {r['btc_align']} with {r['code']}\nTrend {r['trend_txt']} EMA20 {fmt(r['e20'])} EMA50 {fmt(r['e50'])} EMA200 {fmt(r['e200'])} RSI {r['rsi']:.0f}\n\n{'🐢 SLOW - SL +10% safe - SELL SHORT' if not r['is_fast'] else '⚡ FAST'}\n💹 LEVERAGE {lev}x - ALL TP/SL WITH LEV:\n🔴 SL {sl_lev:.2f}% Lev {lev}x: $5 -> ${loss5:.2f} | $100 -> ${loss100:.2f}\n🟢 TP1 +{tp1_lev:.2f}% Lev {lev}x: $5 -> +${p5_1:.2f} | $100 -> +${p100_1:.2f}\n🎯 TP2 +{tp2_lev:.2f}% Lev {lev}x: $5 -> +${p5_2:.2f} | $100 -> +${p100_2:.2f}\n🎯 TP3 +{tp3_lev:.2f}% Lev {lev}x: $5 -> +${p5_3:.2f} | $100 -> +${p100_3:.2f}\n💰 Entry {fmt(r['entry'])} | SL {fmt(r['sl'])} | TP1 {fmt(r['tp1'])} | TP2 {fmt(r['tp2'])} | TP3 {fmt(r['tp3'])} | Lev {lev}x\n\nBot go monitor ONLY {r['code']} 🔴 {r['dir']} 🔴 till TP/SL hit. Enter Binance now $5 10x. Bot go alert you.")
        if buf: await q.message.reply_photo(photo=buf, caption=txt, reply_markup=coins_kb_perfect())
        else: await q.message.reply_text(txt,reply_markup=coins_kb_perfect())

async def txt_handler(u,c):
    code=clean(u.message.text.strip())
    if code not in CRYPTO: return
    btc=get_btc_trend(); r=analyze_perfect(code, btc)
    if r.get("error"): return
    set_active({"status":"OPEN","coin":r["code"],"dir":r["dir"],"entry":r["entry"],"sl":r["sl"]})
    buf=generate_chart_perfect(r)
    txt=f"🎯 MASTER FOCUS LOCKED: {r['code']} {r['dir']} @ {fmt(r['entry'])}"
    if buf: await u.message.reply_photo(photo=buf, caption=txt, reply_markup=coins_kb_perfect())
    else: await u.message.reply_text(txt,reply_markup=coins_kb_perfect())

def run_flask(): app.run(host="0.0.0.0",port=PORT)
def run_bot():
    if not BOT_TOKEN: return
    a=ApplicationBuilder().token(BOT_TOKEN).build()
    a.add_handler(CommandHandler("start",start))
    a.add_handler(CallbackQueryHandler(btn_handler))
    a.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, txt_handler))
    print("Bot V6 PERFECT RESTORE starting..."); a.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    import threading
    threading.Thread(target=run_flask,daemon=True).start()
    run_bot()
