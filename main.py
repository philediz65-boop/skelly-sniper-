import os,re,threading,requests,time,traceback
from flask import Flask
from telegram import InlineKeyboardButton,InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder,CommandHandler,MessageHandler,CallbackQueryHandler,filters
import ccxt

BOT_TOKEN=os.getenv("BOT_TOKEN","").strip()
PORT=int(os.getenv("PORT","10000"))
app=Flask(__name__)

# CCXT EXCHANGES - NO API KEY NEEDED FOR PRICE
okx = ccxt.okx({'enableRateLimit': True})
gate = ccxt.gateio({'enableRateLimit': True})
binance = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'spot'}})
# Use Binance Vision domain for Render
binance.urls['api'] = {
    'public': 'https://data-api.binance.vision/api/v3',
    'private': 'https://data-api.binance.vision/api/v3',
}

CRYPTO=["BTC/USDT","ETH/USDT","BNB/USDT","SOL/USDT","XRP/USDT","DOGE/USDT","ADA/USDT","AVAX/USDT","LINK/USDT","TRX/USDT","DOT/USDT","MATIC/USDT","LTC/USDT","BCH/USDT","UNI/USDT","ATOM/USDT","ETC/USDT","FIL/USDT","PEPE/USDT","BONK/USDT","SHIB/USDT","FLOKI/USDT","WIF/USDT","BOME/USDT","PAXG/USDT"]
DISPLAY={"BTC/USDT":"BTC","ETH/USDT":"ETH","BNB/USDT":"BNB","SOL/USDT":"SOL","XRP/USDT":"XRP","DOGE/USDT":"DOGE","ADA/USDT":"ADA","AVAX/USDT":"AVAX","LINK/USDT":"LINK","TRX/USDT":"TRX","DOT/USDT":"DOT","MATIC/USDT":"MATIC","LTC/USDT":"LTC","BCH/USDT":"BCH","UNI/USDT":"UNI","ATOM/USDT":"ATOM","ETC/USDT":"ETC","FIL/USDT":"FIL","PEPE/USDT":"PEPE","BONK/USDT":"BONK","SHIB/USDT":"SHIB","FLOKI/USDT":"FLOKI","WIF/USDT":"WIF","BOME/USDT":"BOME","PAXG/USDT":"PAXG","XAUUSD":"XAUUSD"}

@app.get("/")
def home(): return "SKELLY CCXT SUPER BOT OK",200
@app.get("/health")
def health(): return {"ok":True},200

def clean(t):
    t=t.upper().strip().replace("/","").replace("-","").replace("_","")
    t=re.sub(r"[^A-Z0-9]","",t)
    if t in ["XAU","GOLD","XAUUSD"]: return "XAUUSD"
    for k,v in DISPLAY.items():
        if t==v or t==k.replace("/",""): return v if v!="PAXG" or t=="PAXG" else v
    return t

def fmt(v):
    try: return f"{v:,.2f}" if v>=1000 else f"{v:,.4f}" if v>=1 else f"{v:.6f}"
    except: return str(v)

def get_ohlcv(symbol):
    # symbol like BTC/USDT
    # 1. OKX first - best for Render
    try:
        ohlcv = okx.fetch_ohlcv(symbol, '1h', limit=200)
        # ohlcv = [[ts, o, h, l, c, vol],...]
        if len(ohlcv)>=60:
            print(f"CCXT OKX OK {symbol}")
            return [{"o":x[1],"h":x[2],"l":x[3],"c":x[4],"v":x[5]} for x in ohlcv]
    except Exception as e:
        print(f"CCXT OKX FAIL {symbol} {e}")
    # 2. Gate for memes
    try:
        ohlcv = gate.fetch_ohlcv(symbol, '1h', limit=200)
        if len(ohlcv)>=60:
            print(f"CCXT GATE OK {symbol}")
            return [{"o":x[1],"h":x[2],"l":x[3],"c":x[4],"v":x[5]} for x in ohlcv]
    except Exception as e:
        print(f"CCXT GATE FAIL {symbol} {e}")
    # 3. Binance Vision
    try:
        ohlcv = binance.fetch_ohlcv(symbol, '1h', limit=200)
        if len(ohlcv)>=60:
            print(f"CCXT BINANCE OK {symbol}")
            return [{"o":x[1],"h":x[2],"l":x[3],"c":x[4],"v":x[5]} for x in ohlcv]
    except Exception as e:
        print(f"CCXT BINANCE FAIL {symbol} {e}")
    return []

def get_price_ccxt(symbol):
    try:
        t = okx.fetch_ticker(symbol)
        return t['last']
    except:
        try:
            t = gate.fetch_ticker(symbol)
            return t['last']
        except:
            try:
                t = binance.fetch_ticker(symbol)
                return t['last']
            except:
                return None

def ema(arr,p):
    if len(arr)<p: return None
    k=2/(p+1); e=sum(arr[:p])/p
    for x in arr[p:]: e=(x-e)*k+e
    return e

def analyze_10steps(code):
    symbol = f"{code}/USDT" if code!="XAUUSD" else "PAXG/USDT"
    if code=="XAUUSD": symbol="PAXG/USDT"

    kl=get_ohlcv(symbol)
    if len(kl)<60: return None
    closes=[c["c"] for c in kl]
    price=get_price_ccxt(symbol) or closes[-1]

    # REAL XAUUSD PRICE
    real_xau=None
    if code=="XAUUSD":
        try:
            r=requests.get("https://api.gold-api.com/price/XAU",timeout=4).json()
            p=float(r.get("price",0))
            if 3000<p<6000: real_xau=p
        except: pass
        if real_xau:
            # shift candles to real price
            diff=real_xau-price
            for c in kl: c["o"]+=diff; c["h"]+=diff; c["l"]+=diff; c["c"]+=diff
            closes=[c["c"] for c in kl]
            price=real_xau

    e20=ema(closes,20); e50=ema(closes,50); e200=ema(closes,200)
    trend="UPTREND" if price>e20>e50>e200 else "DOWNTREND" if price<e20<e50<e200 else "SIDEWAYS" if e20 and e50 and e200 else "SIDEWAYS"

    sup=min([c["l"] for c in kl[-20:]])
    res=max([c["h"] for c in kl[-20:]])
    last=kl[-1]; prev=kl[-2]

    # Breakout logic
    if last["c"]>res and prev["c"]<=res: btype="BREAKOUT_UP"
    elif last["c"]<sup and prev["c"]>=sup: btype="BREAKOUT_DOWN"
    elif abs(last["l"]-sup) < (last["h"]-last["l"])*0.5: btype="RETEST_SUPPORT"
    elif abs(last["h"]-res) < (last["h"]-last["l"])*0.5: btype="RETEST_RESISTANCE"
    else: btype="NO_BREAKOUT"

    conf = (last["c"]>last["o"] and last["c"]>prev["o"]) or (last["c"]<last["o"])
    conf_msg="Bullish Engulfing ✅" if last["c"]>last["o"] and last["c"]>prev["o"] else "Bearish Engulfing ✅" if last["c"]<last["o"] and last["c"]<prev["o"] else "Waiting confirmation ⏳"

    vols=[c["v"] for c in kl[-21:-1]]
    avg=sum(vols)/len(vols) if vols else 1
    vol_ok = last["v"] > avg*1.3
    vol_msg=f"High Vol {last['v']/avg:.1f}x ✅" if vol_ok else f"Low Vol {last['v']/avg:.1f}x ⚠️"

    atr=sum([c["h"]-c["l"] for c in kl[-14:]])/14

    if trend=="UPTREND" and btype in ["BREAKOUT_UP","RETEST_SUPPORT"] and vol_ok:
        direction="BUY"; entry=price; sl=sup-atr*0.5; risk=entry-sl
        tp1=entry+risk*2; tp2=entry+risk*3; tp3=entry+risk*5
    elif trend=="DOWNTREND" and btype in ["BREAKOUT_DOWN","RETEST_RESISTANCE"] and vol_ok:
        direction="SELL"; entry=price; sl=res+atr*0.5; risk=sl-entry
        tp1=entry-risk*2; tp2=entry-risk*3; tp3=entry-risk*5
    else:
        direction="WAIT"; entry=price; sl=tp1=tp2=tp3=None; risk=1

    checklist={
        "1. Trend Confirmed": trend!="SIDEWAYS",
        "2. S/R Marked": True,
        "3. Breakout/Retest": btype!="NO_BREAKOUT",
        "4. Confirmation Candle": conf,
        "5. Volume High": vol_ok,
        "6. Entry Planned": direction!="WAIT",
        "7. SL Logical": direction!="WAIT",
        "8. RR 1:2+": direction!="WAIT",
    }
    return {"code":code,"symbol":symbol,"price":price,"real_xau":real_xau,"trend":trend,"e20":e20,"e50":e50,"e200":e200,"sup":sup,"res":res,"btype":btype,"conf_msg":conf_msg,"conf":conf,"vol_msg":vol_msg,"vol_ok":vol_ok,"dir":direction,"entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"checklist":checklist,"atr":atr}

def coins_kb():
    btns=[]; row=[]
    for s in CRYPTO:
        name=DISPLAY[s]
        row.append(InlineKeyboardButton(name,callback_data=f"C_{name}"))
        if len(row)==3: btns.append(row); row=[]
    if row: btns.append(row)
    btns.append([InlineKeyboardButton("🥇 XAUUSD GOLD LIVE",callback_data="C_XAUUSD")])
    return InlineKeyboardMarkup(btns)

async def start(u,c):
    await u.message.reply_text("🤖 SKELLY SNIPER PRO - CCXT SUPER BOT ✅\n\nConnected to: OKX + Gate + Binance Vision\nLive price + 10-step plan with TP/SL\n\nTap any coin:",reply_markup=coins_kb())

async def btn_handler(u,c):
    q=u.callback_query; await q.answer()
    d=q.data
    if d.startswith("C_"):
        code=d[2:]
        try:
            await q.edit_message_text(f"🔎 Analysing {code} via CCXT (OKX/Gate/Binance)...")
            await run(q,code)
        except Exception as e:
            print(traceback.format_exc())
            await q.edit_message_text(f"❌ {code} error: {e}",reply_markup=coins_kb())

async def txt_handler(u,c):
    s=clean((u.message.text or "").strip())
    if s in DISPLAY.values() or s=="XAUUSD":
        await u.message.reply_text(f"🔎 Analysing {s} via CCXT...")
        await run(u,s)

async def run(upd, code):
    try:
        r=analyze_10steps(code)
        if not r:
            await upd.message.reply_text(f"❌ {code} - Exchange data busy. Tap again after 5 sec. Try BTC/ETH first, dem dey fastest.",reply_markup=coins_kb())
            return
        chk="\n".join([f"{'✅' if v else '❌'} {k}" for k,v in r["checklist"].items()])
        price_line = f"💰 {fmt(r['price'])} LIVE" + (f" | REAL XAU {fmt(r['real_xau'])}" if r['real_xau'] else "")

        if r["dir"]=="WAIT":
            msg=f"""⏳ {code} WAIT - NO TRADE

{price_line}
Trend: {r['trend']}
S/R: Sup {fmt(r['sup'])} | Res {fmt(r['res'])}
Breakout: {r['btype']}
Confirm: {r['conf_msg']}
Volume: {r['vol_msg']}

Checklist:
{chk}

Reason: No full confirmation yet. Patient = Profit.
"""
            await upd.message.reply_text(msg,reply_markup=coins_kb())
        else:
            msg=f"""🚀 {code} {r['dir']} - 10 STEP CONFIRMED

{price_line}
1. Trend: {r['trend']} ✅
EMA20 {fmt(r['e20'])} EMA50 {fmt(r['e50'])} EMA200 {fmt(r['e200'])}
2. S/R: Sup {fmt(r['sup'])} Res {fmt(r['res'])} ✅
3. Breakout: {r['btype']} ✅
4. Candle: {r['conf_msg']} ✅
5. Volume: {r['vol_msg']} ✅
6. Entry: {fmt(r['entry'])}
7. SL: {fmt(r['sl'])} (Sup/Res + ATR {fmt(r['atr'])})
8. RR: TP1 {fmt(r['tp1'])} 2R | TP2 {fmt(r['tp2'])} 3R | TP3 {fmt(r['tp3'])} 5R

Checklist:
{chk}

💵 Entry {fmt(r['entry'])} Lev 10x
🛑 SL {fmt(r['sl'])}
🎯 TP1 {fmt(r['tp1'])} TP2 {fmt(r['tp2'])} TP3 {fmt(r['tp3'])}
"""
            await upd.message.reply_text(msg,reply_markup=coins_kb())
    except Exception as e:
        print(traceback.format_exc())
        await upd.message.reply_text(f"❌ Error {code}: {e}",reply_markup=coins_kb())

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
