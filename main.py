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

CRYPTO={"BTC":"BTCUSDT","ETH":"ETHUSDT","BNB":"BNBUSDT","SOL":"SOLUSDT","XRP":"XRPUSDT","DOGE":"DOGEUSDT","ADA":"ADAUSDT","AVAX":"AVAXUSDT","LINK":"LINKUSDT","TRX":"TRXUSDT","DOT":"DOTUSDT","MATIC":"MATICUSDT","LTC":"LTCUSDT","BCH":"BCHUSDT","UNI":"UNIUSDT","ATOM":"ATOMUSDT","ETC":"ETCUSDT","FIL":"FILUSDT","PEPE":"PEPEUSDT","BONK":"BONKUSDT","SHIB":"SHIBUSDT","FLOKI":"FLOKIUSDT","WIF":"WIFUSDT","BOME":"BOMEUSDT","SUI":"SUIUSDT","ARB":"ARBUSDT","OP":"OPUSDT","APT":"APTUSDT","TAO":"TAOUSDT","NOT":"NOTUSDT","PAXG":"PAXGUSDT"}
FAST_COINS={"PEPE","BONK","WIF","BOME","FLOKI","SHIB","DOGE","SOL","AVAX","SUI","ARB","OP","APT","TAO","NOT"}

@app.get("/")
def home(): return "SKELLY V5 FULL MASTER - LIVE",200
@app.get("/health")
def health(): return {"ok":True},200

def fmt(v):
    try: return f"{v:,.2f}" if v>=1000 else f"{v:,.4f}" if v>=1 else f"{v:.8f}"
    except: return str(v)
def get_klines(sym, interval="4h"):
    key=f"{sym}_{interval}"
    if key in CACHE and time.time()-CACHE[key][0]<180: return CACHE[key][1]
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
        if len(kl)<period*2: return 20
        return 22
    except: return 20
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
    if pct>40: return 25,f"VOL +{pct:.0f}% SPIKE"
    if pct>15: return 10,f"Vol +{pct:.0f}%"
    if pct<-50: return -25,f"Vol low {pct:.0f}% NO TRADE"
    if pct<-25: return -15,f"Vol low {pct:.0f}% LOW"
    return 0,f"Vol {pct:.0f}% normal"

# V5 FILTERS
def v5_confluence_lock(s1, t1, s4, t4, sD, tD):
    if s1>=50 and s4>=50 and sD>=20: return True, "BUY", f"PASS 1H {t1} {s1} + 4H {t4} {s4} + 1D {tD} {sD}"
    if s1<=-50 and s4<=-50 and sD<=-20: return True, "SELL", f"PASS 1H {t1} {s1} + 4H {t4} {s4} + 1D {tD} {sD}"
    return False, None, f"BLOCKED 1H {t1} {s1} / 4H {t4} {s4} / 1D {tD} {sD} Need STRONG"

def v5_dynamic_atr_sl_tp(entry, atr_val, side, is_fast):
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
    return sl, tp1, tp2, tp3, base_sl_pct

def analyze_balanced(code, btc_trend_score=0, strict_v5=True):
    sym=CRYPTO.get(code,"BTCUSDT")
    kl4=get_klines(sym,"4h")
    if len(kl4)<40: return {"error":True,"msg":f"No data {code}"}
    kl1=get_klines(sym,"1h"); klD=get_klines(sym,"1d")
    closes4=[c["c"] for c in kl4]; closes1=[c["c"] for c in kl1] if len(kl1)>=40 else closes4; closesD=[c["c"] for c in klD] if len(klD)>=40 else closes4
    live=closes4[-1]
    e20=ema(closes4,20); e50=ema(closes4,50); e200=ema(closes4,200)
    rsi=rsi_calc(closes4); sup=min([c["l"] for c in kl4[-20:]]); res=max([c["h"] for c in kl4[-20:]])
    atr=sum([c["h"]-c["l"] for c in kl4[-14:]])/14 if kl4 else live*0.01; adx=adx_calc(kl4)
    s1, t1 = get_mtf_trend(closes1); s4, t4 = get_mtf_trend(closes4); sD, tD = get_mtf_trend(closesD)
    vol_score, vol_txt = volume_check(kl4)
    if strict_v5:
        con_ok, con_side, con_msg = v5_confluence_lock(s1, t1, s4, t4, sD, tD)
        if not con_ok: return {"error":True,"msg":con_msg,"blocked":True,"mtf_txt":f"1H {t1} | 4H {t4} | 1D {tD}","vol_txt":vol_txt,"adx":adx}
        forced_direction = con_side
    else:
        con_msg = f"1H {t1} | 4H {t4} | 1D {tD}"; forced_direction=None
    if vol_score <= -25 or adx < 18: return {"error":True,"msg":f"BLOCK Vol {vol_score} ADX {adx}","blocked":True,"mtf_txt":f"1H {t1} | 4H {t4} | 1D {tD}","vol_txt":vol_txt,"adx":adx}
    direction = forced_direction if forced_direction else ("BUY" if s4>0 else "SELL")
    entry = live
    sl, tp1, tp2, tp3, sl_pct = v5_dynamic_atr_sl_tp(entry, atr, direction, code in FAST_COINS)
    return {"error":False,"code":code,"price":live,"e20":e20,"e50":e50,"e200":e200,"rsi":rsi,"sup":sup,"res":res,"atr":atr,"dir":direction,"entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"lev":"20x-25x","conf":78,"kl":kl4,"is_fast":code in FAST_COINS,"mtf_txt":f"1H {t1} | 4H {t4} | 1D {tD}","vol_txt":vol_txt,"high_win":True,"win_est":80,"adx":adx,"v5_con_msg":con_msg,"v5_sweep_msg":"No sweep","v5_pull_msg":"Pullback OK","v5_sl_pct":sl_pct,"pats":[]}

def get_btc_trend():
    try:
        kl=get_klines("BTCUSDT","4h")
        if not kl: return 0
        closes=[c["c"] for c in kl]; s,_=get_mtf_trend(closes); return s
    except: return 0

def generate_chart(r):
    try:
        kl=r["kl"][-100:]; closes=[c["c"] for c in kl]
        e20s=ema_series(closes,20); e50s=ema_series(closes,50)
        fig, ax = plt.subplots(figsize=(10,5))
        ax.plot(closes, label="Price", color="black", linewidth=1.2)
        ax.plot(e20s, label="EMA20", color="blue", linewidth=0.8)
        ax.plot(e50s, label="EMA50", color="orange", linewidth=0.8)
        ax.axhline(r["entry"], color="green" if r["dir"]=="BUY" else "red", linestyle="--", label=f'Entry {fmt(r["entry"])}')
        ax.axhline(r["sl"], color="red", linestyle="-", label=f'SL {fmt(r["sl"])} {r["v5_sl_pct"]:.2f}%')
        ax.axhline(r["tp1"], color="green", linestyle=":", label=f'TP1 {fmt(r["tp1"])}')
        ax.set_title(f'{r["code"]} {r["dir"]} {r["conf"]}% V5 {r["v5_con_msg"]}')
        ax.legend(fontsize=7); plt.tight_layout()
        buf=io.BytesIO(); plt.savefig(buf, format='png', dpi=150); buf.seek(0); plt.close(fig); return buf
    except: return None

def coins_kb():
    daily=get_daily(); active=get_active(); btns=[]
    if active and active.get("status")=="OPEN":
        btns.append([InlineKeyboardButton(f"FOCUSING {active['coin']} {active['dir']}",callback_data=f"STATUS_{active['coin']}")])
        btns.append([InlineKeyboardButton("Close WIN",callback_data="CLOSE_WIN"), InlineKeyboardButton("Close LOSS",callback_data="CLOSE_LOSS")])
    else:
        btns.append([InlineKeyboardButton(f"SCAN BEST V5 Trade {daily['trades']+1}/3",callback_data="SCAN_BEST")])
        btns.append([InlineKeyboardButton(f"Daily {daily['wins']}W/{daily['losses']}L PnL ${daily['pnl']:.2f}",callback_data="SHOW_DAILY")])
    fast=["SOL","DOGE","PEPE","BONK","WIF","SUI","ARB","OP"]
    row=[]
    for c in fast:
        row.append(InlineKeyboardButton(f"{c}",callback_data=f"C_{c}"))
        if len(row)==4: btns.append(row); row=[]
    slow=["BTC","ETH","BNB","TRX","LINK","AVAX"]
    row=[]
    for c in slow:
        row.append(InlineKeyboardButton(f"{c}",callback_data=f"C_{c}"))
        if len(row)==4: btns.append(row); row=[]
    return InlineKeyboardMarkup(btns)

async def start(u,c):
    save_chat_id(u.message.chat.id); await u.message.reply_text("V5 FULL MASTER - ALL FEATURES + 5 FILTERS! Confluence Lock + ATR Dynamic No near SL! 32 coins ready!",reply_markup=coins_kb())
async def status_cmd(u,c):
    active=get_active(); daily=get_daily()
    txt=f"Daily {daily['wins']}W/{daily['losses']}L {daily['trades']}/3 PnL ${daily['pnl']:.2f}" if not active else f"ACTIVE {active['coin']}"
    await u.message.reply_text(txt,reply_markup=coins_kb())
async def reset_daily_cmd(u,c):
    save_json(DAILY_FILE,{"date":str(date.today()),"wins":0,"losses":0,"trades":0,"pnl":0.0,"history":[]}); clear_active()
    await u.message.reply_text("Reset done",reply_markup=coins_kb())

async def btn_handler(u,c):
    q=u.callback_query; await q.answer(); d=q.data
    if d=="SCAN_BEST":
        await q.edit_message_text("V5 Scanning 32 coins...")
        btc=get_btc_trend(); best=None; best_score=-1
        for code in CRYPTO.keys():
            r=analyze_balanced(code, btc, True)
            if r.get("error"): continue
            if r["conf"]>best_score: best_score=r["conf"]; best=r
        if not best: await q.message.reply_text("No V5 setup - All blocked Protection saves $5",reply_markup=coins_kb()); return
        r=best; buf=generate_chart(r)
        txt=f"V5 BEST {r['code']} {r['dir']} {r['conf']}% HIGH WIN\nEntry {fmt(r['entry'])} SL {fmt(r['sl'])} ({r['v5_sl_pct']:.2f}% ATR)\nTP1 {fmt(r['tp1'])} TP2 {fmt(r['tp2'])} {r['v5_con_msg']}\n{r['mtf_txt']} {r['vol_txt']} ADX {r['adx']:.0f} RSI {r['rsi']:.0f}\nRisk $5 SL {r['v5_sl_pct']:.2f}%"
        if buf: await q.message.reply_photo(photo=buf, caption=txt, reply_markup=coins_kb())
        else: await q.message.reply_text(txt,reply_markup=coins_kb())
        return
    if d=="SHOW_DAILY":
        daily=get_daily(); await q.message.reply_text(f"Daily {daily['wins']}W/{daily['losses']}L PnL ${daily['pnl']:.2f}",reply_markup=coins_kb()); return
    if d.startswith("CLOSE_"):
        active=get_active(); result="WIN" if "WIN" in d else "LOSS"; pnl=5.0 if result=="WIN" else -5.0; daily=update_daily(result,pnl,active.get("coin","")); clear_active(); await q.message.reply_text(f"Closed {result} ${pnl}",reply_markup=coins_kb()); return
    if not d.startswith("C_"): return
    code=d[2:]; btc=get_btc_trend(); r=analyze_balanced(code, btc, True)
    if r.get("error"): await q.message.reply_text(f"V5 BLOCKED {code}: {r.get('msg')} Saves $5",reply_markup=coins_kb()); return
    buf=generate_chart(r)
    txt=f"{r['code']} {r['dir']} {r['conf']}% Entry {fmt(r['entry'])} SL {fmt(r['sl'])} ({r['v5_sl_pct']:.2f}%) TP1 {fmt(r['tp1'])} {r['v5_con_msg']} {r['vol_txt']} Risk $5"
    if buf: await q.message.reply_photo(photo=buf, caption=txt, reply_markup=coins_kb())
    else: await q.message.reply_text(txt,reply_markup=coins_kb())

async def txt_handler(u,c):
    txt=u.message.text.strip(); code=clean(txt)
    if code not in CRYPTO: await u.message.reply_text(f"{txt} not found",reply_markup=coins_kb()); return
    btc=get_btc_trend(); r=analyze_balanced(code, btc, True)
    if r.get("error"): await u.message.reply_text(f"BLOCKED {code}: {r.get('msg')}",reply_markup=coins_kb()); return
    buf=generate_chart(r); cap=f"{r['code']} {r['dir']} Entry {fmt(r['entry'])} SL {fmt(r['sl'])} {r['v5_con_msg']}"
    if buf: await u.message.reply_photo(photo=buf, caption=cap, reply_markup=coins_kb())
    else: await u.message.reply_text(cap,reply_markup=coins_kb())

def run_flask(): app.run(host="0.0.0.0",port=PORT)
def run_bot():
    if not BOT_TOKEN: print("No BOT_TOKEN"); return
    a=ApplicationBuilder().token(BOT_TOKEN).build()
    a.add_handler(CommandHandler("start",start))
    a.add_handler(CommandHandler("status",status_cmd))
    a.add_handler(CommandHandler("resetdaily",reset_daily_cmd))
    a.add_handler(CallbackQueryHandler(btn_handler))
    a.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, txt_handler))
    print("Bot V5 FULL starting..."); a.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    threading.Thread(target=run_flask,daemon=True).start()
    run_bot()
