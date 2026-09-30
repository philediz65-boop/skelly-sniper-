import os, re, threading
import requests
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PORT = int(os.getenv("PORT", "10000"))
app = Flask(__name__)

CRYPTO = {
    "BTC":"BTCUSDT","ETH":"ETHUSDT","BNB":"BNBUSDT","SOL":"SOLUSDT",
    "XRP":"XRPUSDT","DOGE":"DOGEUSDT","ADA":"ADAUSDT","AVAX":"AVAXUSDT",
    "LINK":"LINKUSDT","TRX":"TRXUSDT","DOT":"DOTUSDT","MATIC":"MATICUSDT",
    "LTC":"LTCUSDT","BCH":"BCHUSDT","UNI":"UNIUSDT","ATOM":"ATOMUSDT",
    "ETC":"ETCUSDT","FIL":"FILUSDT","PEPE":"PEPEUSDT","BONK":"BONKUSDT",
    "SHIB":"SHIBUSDT","FLOKI":"FLOKIUSDT","FARTCOIN":"FARTCOINUSDT",
    "WIF":"WIFUSDT","BABY":"BABYUSDT","BOME":"BOMEUSDT","PAXG":"PAXGUSDT"
}
MT5_ASSETS = {"XAUUSD":"PAXGUSDT","GOLD":"PAXGUSDT","XAGUSD":"PAXGUSDT"}

BYBIT_BASES=["https://api.bybit.com"]
SESSION=requests.Session()
SESSION.headers.update({"User-Agent":"Mozilla/5.0 PHILEDIZ-MENU-FIXED","Accept":"application/json"})
SMALL_ACCOUNT_MODE=True
REAL_LEV_FALLBACK={"BTCUSDT":15,"ETHUSDT":15,"SOLUSDT":10,"BNBUSDT":10,"XRPUSDT":10,"DOGEUSDT":10,"ADAUSDT":10,"AVAXUSDT":10,"LINKUSDT":10,"TRXUSDT":10,"DOTUSDT":10,"MATICUSDT":10,"LTCUSDT":10,"BCHUSDT":10,"UNIUSDT":10,"ATOMUSDT":10,"ETCUSDT":10,"FILUSDT":10,"PEPEUSDT":5,"BONKUSDT":5,"SHIBUSDT":5,"FLOKIUSDT":5,"FARTCOINUSDT":5,"WIFUSDT":5,"BABYUSDT":5,"BOMEUSDT":5,"PAXGUSDT":10}

@app.get("/")
def home(): return "PHILEDIZ V2 MENU + XAUUSD TP FIXED", 200
@app.get("/health")
def health(): return {"status":"ok","menu":"coins+mt5","xauusd_tp":"enabled"}, 200

def clean_symbol(t:str)->str:
    t=t.upper().strip().replace("/","").replace("-","").replace("_",""); t=re.sub(r"[^A-Z0-9]","",t)
    aliases={"BITCOIN":"BTC","ETHEREUM":"ETH","SOLANA":"SOL","RIPPLE":"XRP","GOLD":"XAUUSD","XAU":"XAUUSD","XAUUSD":"XAUUSD","PAXG":"PAXG"}
    if t in aliases: t=aliases[t]
    if t.endswith("USDT") and t[:-4] in CRYPTO: return t[:-4]
    return t

def fmt_price(v:float)->str:
    if v>=1000: return f"{v:,.2f}"
    if v>=100: return f"{v:,.3f}"
    if v>=1: return f"{v:,.4f}"
    if v>=0.01: return f"{v:,.5f}"
    return f"{v:,.8f}"

def bybit_get(path:str, params:dict):
    for base in BYBIT_BASES:
        try:
            r=SESSION.get(base+path, params=params, timeout=10)
            if r.status_code!=200: continue
            data=r.json()
            if data.get("retCode")!=0: continue
            return data
        except: continue
    return None

def get_bybit_klines(symbol, interval="15", limit=200):
    for category in ["linear","spot"]:
        data=bybit_get("/v5/market/kline", {"category":category,"symbol":symbol,"interval":interval,"limit":limit})
        if not data: continue
        rows=data.get("result",{}).get("list",[])
        if not rows: continue
        c=[]
        for row in rows:
            try: c.append({"time":int(row[0]),"open":float(row[1]),"high":float(row[2]),"low":float(row[3]),"close":float(row[4]),"volume":float(row[5])})
            except: pass
        if len(c)>=30:
            c.reverse()
            return c
    return []

def get_okx_klines(symbol, interval="15m", limit=150):
    try:
        okx_sym=symbol.replace("USDT","-USDT")
        r=SESSION.get(f"https://www.okx.com/api/v5/market/candles?instId={okx_sym}&bar={interval}&limit={limit}", timeout=10).json()
        rows=r.get("data",[]); c=[]
        for row in rows:
            try: c.append({"time":int(row[0]),"open":float(row[1]),"high":float(row[2]),"low":float(row[3]),"close":float(row[4]),"volume":float(row[5])})
            except: pass
        c.reverse()
        return c
    except: return []

def get_bybit_tickers(symbol):
    for cat in ["linear","spot"]:
        data=bybit_get("/v5/market/tickers", {"category":cat,"symbol":symbol})
        if not data: continue
        rows=data.get("result",{}).get("list",[])
        if not rows: continue
        try:
            last=float(rows[0]["lastPrice"]); mark=float(rows[0].get("markPrice", last))
            return last, mark
        except: continue
    return None,None

def get_okx_price(symbol):
    try:
        okx_sym=symbol.replace("USDT","-USDT")
        r=SESSION.get(f"https://www.okx.com/api/v5/market/ticker?instId={okx_sym}", timeout=10).json()
        return float(r["data"][0]["last"])
    except: return None

def get_real_leverage(symbol):
    if SMALL_ACCOUNT_MODE:
        if symbol in ["BTCUSDT","ETHUSDT"]: return 15
        elif symbol in ["SOLUSDT","BNBUSDT","XRPUSDT","AVAXUSDT","LINKUSDT","TRXUSDT","PAXGUSDT"]: return 10
        else: return 5
    return float(REAL_LEV_FALLBACK.get(symbol,10))

def ema(values, period):
    if len(values)<period: return None
    m=2.0/(period+1.0); res=sum(values[:period])/period
    for p in values[period:]: res=(p-res)*m+res
    return res

def rsi(values, period=14):
    if len(values)<=period: return None
    gains=[]; losses=[]
    for i in range(1,len(values)):
        ch=values[i]-values[i-1]; gains.append(max(ch,0.0)); losses.append(max(-ch,0.0))
    ag=sum(gains[:period])/period; al=sum(losses[:period])/period
    for i in range(period,len(gains)):
        ag=(ag*(period-1)+gains[i])/period; al=(al*(period-1)+losses[i])/period
    if al==0: return 100.0
    return 100.0-(100.0/(1.0+ag/al))

def macd(values):
    if len(values)<35: return None,None,None
    e12=ema(values,12); e26=ema(values,26)
    if e12 is None or e26 is None: return None,None,None
    macd_line=e12-e26
    macd_vals=[]
    for i in range(26, len(values)):
        sub=values[:i+1]
        e12s=ema(sub,12); e26s=ema(sub,26)
        if e12s and e26s: macd_vals.append(e12s-e26s)
    if len(macd_vals)<9: return macd_line,None,None
    signal=ema(macd_vals,9)
    hist=macd_line-signal if signal else None
    return macd_line, signal, hist

def atr(candles, period=14):
    if len(candles)<=period: return None
    trs=[]
    for i in range(1,len(candles)):
        c=candles[i]; p=candles[i-1]
        tr=max(c["high"]-c["low"],abs(c["high"]-p["close"]),abs(c["low"]-p["close"])); trs.append(tr)
    if len(trs)<period: return None
    v=sum(trs[:period])/period
    for tr in trs[period:]: v=(v*(period-1)+tr)/period
    return v

def bollinger(values, period=20, mult=2):
    if len(values)<period: return None,None,None
    ma=sum(values[-period:])/period
    var=sum((x-ma)**2 for x in values[-period:])/period
    std=var**0.5
    return ma+mult*std, ma, ma-mult*std

def candle_pattern(candles):
    if len(candles)<3: return "None"
    c1=candles[-2]; c2=candles[-1]
    body2=abs(c2["close"]-c2["open"])
    if c1["close"]<c1["open"] and c2["close"]>c2["open"] and c2["open"]<c1["close"] and c2["close"]>c1["open"]: return "Bullish Engulfing 🟢"
    if c1["close"]>c1["open"] and c2["close"]<c2["open"] and c2["open"]>c1["close"] and c2["close"]<c1["open"]: return "Bearish Engulfing 🔴"
    lower_wick=c2["open"]-c2["low"] if c2["close"]>c2["open"] else c2["close"]-c2["low"]
    upper_wick=c2["high"]-c2["close"] if c2["close"]>c2["open"] else c2["high"]-c2["open"]
    if lower_wick>body2*2 and upper_wick<body2*0.5: return "Hammer 🔨"
    if upper_wick>body2*2 and lower_wick<body2*0.5: return "Shooting Star ⭐"
    if body2 < (c2["high"]-c2["low"])*0.1: return "Doji ⚪"
    if c2["close"]>c2["open"]: return "Bullish 🟢"
    return "Bearish 🔴"

def support_resistance(candles, lookback=50):
    s=candles[-lookback:]; return min(c["low"] for c in s), max(c["high"] for c in s)

def analyze_crypto(symbol_code:str):
    symbol=CRYPTO.get(symbol_code)
    if not symbol: return None
    candles=get_bybit_klines(symbol,"15",200)
    if len(candles)<60: candles=get_okx_klines(symbol,"15m",150)
    if len(candles)<60: return None
    closes=[c["close"] for c in candles]; volumes=[c["volume"] for c in candles]
    last_price, mark_price = get_bybit_tickers(symbol)
    if not last_price: last_price=get_okx_price(symbol)
    live_price = last_price or closes[-1]
    if not mark_price: mark_price=live_price
    e20=ema(closes,20); e50=ema(closes,50); e200=ema(closes,200)
    r14=rsi(closes,14); a14=atr(candles,14)
    macd_line, macd_signal, macd_hist = macd(closes)
    bb_up, bb_mid, bb_low = bollinger(closes)
    if None in (e20,e50,r14,a14): return None
    sup,res=support_resistance(candles)
    pattern=candle_pattern(candles)
    mom=(closes[-1]-closes[-6])/closes[-6]*100
    vol_avg=sum(volumes[-20:])/20; vol_now=volumes[-1]; vol_confirm = vol_now > vol_avg*1.2
    score=0; reasons=[]
    if live_price>e20: score+=1; reasons.append("Price > EMA20")
    else: score-=1; reasons.append("Price < EMA20")
    if e20>e50: score+=1; reasons.append("EMA20 > EMA50 uptrend")
    else: score-=1; reasons.append("EMA20 < EMA50 downtrend")
    if e50 and e200:
        if e50>e200: score+=1
        else: score-=1
    if r14>=55 and r14<70: score+=1; reasons.append(f"RSI {r14:.1f} bullish")
    elif r14<=45 and r14>30: score-=1; reasons.append(f"RSI {r14:.1f} bearish")
    if macd_hist is not None:
        if macd_hist>0: score+=1; reasons.append("MACD bullish")
        else: score-=1; reasons.append("MACD bearish")
    if mom>0.3: score+=1
    elif mom<-0.3: score-=1
    if "Bullish Engulfing" in pattern or "Hammer" in pattern: score+=1; reasons.append(pattern)
    elif "Bearish Engulfing" in pattern or "Shooting Star" in pattern: score-=1; reasons.append(pattern)
    if vol_confirm: score+=1 if score>0 else -1
    mark_diff = (live_price - mark_price)/mark_price*100 if mark_price else 0
    if score>=3: direction="BUY"
    elif score<=-3: direction="SELL"
    else: direction="WAIT"
    if direction=="BUY":
        sl=live_price-1.5*a14; tp1=live_price+1.5*a14; tp2=live_price+2.5*a14; tp3=live_price+4.0*a14
    elif direction=="SELL":
        sl=live_price+1.5*a14; tp1=live_price-1.5*a14; tp2=live_price-2.5*a14; tp3=live_price-4.0*a14
    else: sl=tp1=tp2=tp3=None
    lev=get_real_leverage(symbol)
    return {
        "symbol":symbol_code,"pair":symbol,"price":live_price,"mark":mark_price,"mark_diff":mark_diff,"candles":candles,
        "ema20":e20,"ema50":e50,"ema200":e200,"rsi":r14,"atr":a14,"macd":macd_line,"macd_hist":macd_hist,
        "bb_up":bb_up,"bb_low":bb_low,"support":sup,"resistance":res,"momentum":mom,"pattern":pattern,
        "vol_confirm":vol_confirm,"score":score,"direction":direction,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"leverage":lev,"reasons":reasons,"timeframe":"15M","source":"Bybit (linear+spot) + OKX"
    }

def get_xauusd():
    # PAXGUSDT from Bybit + OKX - FIXED WITH TP/SL
    for symbol in ["PAXGUSDT"]:
        # Bybit
        try:
            candles=get_bybit_klines(symbol,"15",200)
            if len(candles)>=60:
                closes=[c["close"] for c in candles]; price=closes[-1]
                e20=ema(closes,20); e50=ema(closes,50); r14=rsi(closes,14); a14=atr(candles,14)
                if None not in (e20,e50,r14,a14):
                    sup=min(c["low"] for c in candles[-50:]); res=max(c["high"] for c in candles[-50:])
                    pattern=candle_pattern(candles)
                    score=(1 if price>e20 else -1)+(1 if e20>e50 else -1)+(1 if r14>=55 else -1 if r14<=45 else 0)
                    direction="BUY" if score>=2 else "SELL" if score<=-2 else "WAIT"
                    if direction=="BUY":
                        sl=price-1.2*a14; tp1=price+1.0*a14; tp2=price+2.0*a14; tp3=price+3.5*a14
                    elif direction=="SELL":
                        sl=price+1.2*a14; tp1=price-1.0*a14; tp2=price-2.0*a14; tp3=price-3.5*a14
                    else:
                        sl=price-1.2*a14; tp1=price+1.0*a14; tp2=price+2.0*a14; tp3=price+3.5*a14
                    lev=get_real_leverage(symbol)
                    return {"pair":"XAUUSD (PAXG Bybit)","symbol":"XAUUSD","price":price,"candles":candles,"ema20":e20,"ema50":e50,"rsi":r14,"atr":a14,"support":sup,"resistance":res,"pattern":pattern,"direction":direction,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"leverage":lev,"timeframe":"15M","source":"Bybit PAXGUSDT (Gold)","score":score}
        except: pass
        # OKX fallback
        try:
            candles=get_okx_klines(symbol,"15m",150)
            if len(candles)>=60:
                closes=[c["close"] for c in candles]; price=closes[-1]
                e20=ema(closes,20); e50=ema(closes,50); r14=rsi(closes,14); a14=atr(candles,14)
                if None not in (e20,e50,r14,a14):
                    sup=min(c["low"] for c in candles[-50:]); res=max(c["high"] for c in candles[-50:])
                    pattern=candle_pattern(candles)
                    score=(1 if price>e20 else -1)+(1 if e20>e50 else -1)
                    direction="BUY" if score>=1 else "SELL" if score<=-1 else "WAIT"
                    if direction=="BUY":
                        sl=price-1.2*a14; tp1=price+1.0*a14; tp2=price+2.0*a14; tp3=price+3.5*a14
                    elif direction=="SELL":
                        sl=price+1.2*a14; tp1=price-1.0*a14; tp2=price-2.0*a14; tp3=price-3.5*a14
                    else:
                        sl=price-1.2*a14; tp1=price+1.0*a14; tp2=price+2.0*a14; tp3=price+3.5*a14
                    lev=get_real_leverage(symbol)
                    return {"pair":"XAUUSD (PAXG OKX)","symbol":"XAUUSD","price":price,"candles":candles,"ema20":e20,"ema50":e50,"rsi":r14,"atr":a14,"support":sup,"resistance":res,"pattern":pattern,"direction":direction,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"leverage":lev,"timeframe":"15M","source":"OKX PAXG-USDT (Gold)","score":score}
        except: pass
    return None

def create_chart(candles, analysis, symbol):
    try:
        data=candles[-100:]; n=len(data)
        times=list(range(n)); opens=[c["open"] for c in data]; highs=[c["high"] for c in data]; lows=[c["low"] for c in data]; closes=[c["close"] for c in data]
        ob_idx=None
        for i in range(n-10, n-30, -1):
            if closes[i] < opens[i]:
                if i+3 < n and closes[i+1]>opens[i+1] and closes[i+2]>opens[i+2]:
                    ob_idx=i; break
        if ob_idx is None: ob_idx=n-25
        ob_high = highs[ob_idx]; ob_low = lows[ob_idx]
        recent_highs=[]
        for i in range(10, n-10):
            if highs[i] == max(highs[i-5:i+5]): recent_highs.append((i, highs[i]))
        recent_highs = sorted(recent_highs, key=lambda x: x[1], reverse=True)[:3]
        fig, ax = plt.subplots(figsize=(12,6))
        fig.patch.set_facecolor('white'); ax.set_facecolor('white')
        for i in range(n):
            ax.plot([times[i], times[i]], [lows[i], highs[i]], color='black', linewidth=0.8, alpha=0.9)
            ax.plot([times[i], times[i]], [opens[i], closes[i]], color='black', linewidth=2.2)
        ob_start = ob_idx; ob_end = n-5
        ax.add_patch(plt.Rectangle((ob_start, ob_low), ob_end-ob_start, ob_high-ob_low, facecolor='#a8c0ff', edgecolor='#4a7bff', alpha=0.6, linewidth=1))
        for idx, price in recent_highs:
            ax.axhline(price, color='black', linewidth=0.9, alpha=0.8)
            ax.text(n+1, price, f'{price:.2f}', va='center', ha='left', fontsize=8, bbox=dict(boxstyle='square,pad=0.2', facecolor='black', edgecolor='black'), color='white')
        if analysis["direction"]=="BUY":
            curr_idx=n-1; curr_price=closes[-1]
            path_x=[curr_idx-8, curr_idx-4, ob_idx+5, ob_idx+12, ob_idx+18, n+15]
            path_y=[
                curr_price+(recent_highs[0][1]-curr_price)*0.3 if recent_highs else curr_price+2,
                curr_price-0.5*(curr_price-ob_low),
                (ob_low+ob_high)/2,
                ob_high+(recent_highs[1][1]-ob_high)*0.5 if len(recent_highs)>1 else ob_high*1.01,
                recent_highs[0][1]*0.995 if recent_highs else ob_high*1.03,
                recent_highs[0][1]*1.02 if recent_highs else ob_high*1.05
            ]
            ax.plot(path_x, path_y, color='black', linewidth=1.2)
            ax.annotate('', xy=(path_x[-1], path_y[-1]), xytext=(path_x[-2], path_y[-2]), arrowprops=dict(facecolor='black', edgecolor='black', arrowstyle='->', lw=1.2))
        else:
            curr_idx=n-1; curr_price=closes[-1]
            path_x=[curr_idx-8, curr_idx-4, ob_idx+5, n+10]
            path_y=[curr_price, curr_price+0.5, ob_low*0.99, ob_low*0.97]
            ax.plot(path_x, path_y, color='black', linewidth=1.2)
            ax.annotate('', xy=(path_x[-1], path_y[-1]), xytext=(path_x[-2], path_y[-2]), arrowprops=dict(facecolor='black', edgecolor='black', arrowstyle='->', lw=1.2))
        ax.set_xlim(-5, n+20); ax.get_xaxis().set_visible(False)
        ax.tick_params(axis='y', colors='black', labelsize=8)
        ax.spines['top'].set_visible(False); ax.spines['bottom'].set_visible(False); ax.spines['left'].set_visible(False); ax.spines['right'].set_visible(False)
        ax.set_title(f'{symbol} - Order Block + BOS - {analysis["direction"]} | {analysis["pattern"]}', color='black', fontsize=10, loc='left')
        plt.tight_layout()
        path="/tmp/philediz_smc_chart.png"
        plt.savefig(path, dpi=300, facecolor='white', bbox_inches='tight')
        plt.close()
        return path
    except Exception as e:
        print(f"Chart error {e}", flush=True)
        return None

def crypto_message(a: dict)->str:
    lev=f"{a['leverage']:g}x"
    direction=a['direction']; emoji="🟢 BUY" if direction=="BUY" else "🔴 SELL" if direction=="SELL" else "⚪ WAIT"
    vol_txt="✅ High" if a['vol_confirm'] else "⚪ Normal"
    hist_emoji="🟢" if a['macd_hist'] and a['macd_hist']>0 else "🔴" if a['macd_hist'] and a['macd_hist']<0 else "⚪"
    lines=[
        "🤖 PHILEDIZ V2 PRO ANALYSIS","",
        f"🪙 Pair: {a['pair']}",
        f"⏱ Timeframe: {a['timeframe']}",
        f"💰 Last: {fmt_price(a['price'])}",
        f"🎯 Mark: {fmt_price(a['mark'])} ({a['mark_diff']:+.3f}%)",
        f"📡 Source: {a['source']}","",
        "📊 INDICATORS (Candles+Mark+RSI+EMA+MACD)",
        f"🕯 Candle: {a['pattern']}",
        f"📈 EMA20: {fmt_price(a['ema20'])} | EMA50: {fmt_price(a['ema50'])}",
        f"💪 RSI14: {a['rsi']:.1f}",
        f"📉 MACD: {hist_emoji} {a['macd']:.4f}" if a['macd'] else "📉 MACD: N/A",
        f"📦 Volume: {vol_txt}",
        f"⚡ ATR: {fmt_price(a['atr'])} | Mom: {a['momentum']:+.2f}%","",
        f"📌 SETUP: {emoji} (Score {a['score']}/10)",
    ]
    if a['reasons']: lines+=["","🔍 Logic:"]+[f"• {r}" for r in a['reasons'][:5]]
    if direction!="WAIT":
        entry=a['price']; sl_pct=(a['sl']-entry)/entry*100; tp1_pct=(a['tp1']-entry)/entry*100; tp2_pct=(a['tp2']-entry)/entry*100; tp3_pct=(a['tp3']-entry)/entry*100
        lines+=["","━━━━━━━━━━━━━━━━━━",f"{emoji} {a['symbol']}","",f"💵 Entry: {fmt_price(entry)} | ⚡ Leverage: {lev} (Small Safe)",f"🛑 SL: {fmt_price(a['sl'])} ({sl_pct:+.2f}%)",f"🎯 TP1: {fmt_price(a['tp1'])} ({tp1_pct:+.2f}%)",f"🎯 TP2: {fmt_price(a['tp2'])} ({tp2_pct:+.2f}%)",f"🎯 TP3: {fmt_price(a['tp3'])} ({tp3_pct:+.2f}%)","━━━━━━━━━━━━━━━━━━","","📸 SMC Chart above 👆","💡 Move SL to BE after TP1"]
    else:
        lines+=["",f"⚡ Safe Leverage: {lev} (small account)","","⏳ WAIT - Low confluence","📸 SMC Chart above 👆"]
    lines+=["","⚠️ Not financial advice."]
    return "\n".join(lines)

def xau_message(a: dict)->str:
    emoji="🟢 BUY" if a['direction']=="BUY" else "🔴 SELL" if a['direction']=="SELL" else "⚪ WAIT"
    lev=f"{a['leverage']:g}x"
    entry=a['price']; sl_pct=(a['sl']-entry)/entry*100; tp1_pct=(a['tp1']-entry)/entry*100; tp2_pct=(a['tp2']-entry)/entry*100; tp3_pct=(a['tp3']-entry)/entry*100
    return "\n".join([
        "🤖 PHILEDIZ V2 MT5 GOLD ANALYSIS","","🥇 Pair: XAUUSD (Gold via PAXG Bybit+OKX)",f"⏱ {a['timeframe']}",f"💰 Price: {fmt_price(a['price'])}",f"📡 {a['source']}",f"⚡ ATR: {fmt_price(a['atr'])}","","📊 INDICATORS",f"🕯 {a['pattern']}",f"EMA20: {fmt_price(a['ema20'])} | EMA50: {fmt_price(a['ema50'])}",f"RSI14: {a['rsi']:.1f}","","📍 Support: {fmt_price(a['support'])} | Resistance: {fmt_price(a['resistance'])}","",f"📌 SETUP: {emoji} {a['direction']} (Score {a['score']}/10)","", "━━━━━━━━━━━━━━━━━━",f"{emoji} XAUUSD GOLD","",f"💵 Entry: {fmt_price(entry)} | ⚡ Leverage: {lev} (MT5 Safe)",f"🛑 SL: {fmt_price(a['sl'])} ({sl_pct:+.2f}%)",f"🎯 TP1: {fmt_price(a['tp1'])} ({tp1_pct:+.2f}%)",f"🎯 TP2: {fmt_price(a['tp2'])} ({tp2_pct:+.2f}%)",f"🎯 TP3: {fmt_price(a['tp3'])} ({tp3_pct:+.2f}%)","━━━━━━━━━━━━━━━━━━","","📸 SMC Chart above 👆","💡 MT5: Move SL to BE after TP1","","⚠️ Not financial advice."
    ])

# MENU KEYBOARDS
def coins_keyboard():
    coins=list(CRYPTO.keys())
    buttons=[]
    row=[]
    for i, c in enumerate(coins):
        row.append(InlineKeyboardButton(c, callback_data=f"COIN_{c}"))
        if len(row)==3:
            buttons.append(row); row=[]
    if row: buttons.append(row)
    buttons.append([InlineKeyboardButton("🥇 MT5 GOLD MENU", callback_data="MENU_MT5")])
    return InlineKeyboardMarkup(buttons)

def mt5_keyboard():
    buttons=[
        [InlineKeyboardButton("🥇 XAUUSD (Gold)", callback_data="COIN_XAUUSD"), InlineKeyboardButton("🪙 PAXG (Gold)", callback_data="COIN_PAXG")],
        [InlineKeyboardButton("📋 ALL CRYPTO MENU", callback_data="MENU_COINS")],
        [InlineKeyboardButton("🔄 Refresh MT5", callback_data="MENU_MT5")]
    ]
    return InlineKeyboardMarkup(buttons)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text="🤖 PHILEDIZ V2 MENU ENABLED!\n\n📋 /coins → Select crypto (BTC, ETH, SOL...)\n🥇 /mt5 → MT5 Gold menu (XAUUSD)\n\n✅ XAUUSD now has TP1,2,3 + SL\n✅ All coins work (Bybit linear+spot + OKX)\n✅ Small safe leverage 5x/10x/15x\n\nChoose menu:"
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 CRYPTO MENU", callback_data="MENU_COINS"), InlineKeyboardButton("🥇 MT5 MENU", callback_data="MENU_MT5")]]))

async def coins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📋 SELECT CRYPTO COIN:", reply_markup=coins_keyboard())

async def mt5_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🥇 MT5 MENU - SELECT GOLD:", reply_markup=mt5_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📚 PHILEDIZ V2\n\n/coins - Crypto menu\n/mt5 - MT5 Gold menu\n/analyze BTC - Direct\n/analyze XAUUSD - Direct\n/testbybit - Test PAXG Bybit+OKX", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 CRYPTO", callback_data="MENU_COINS"), InlineKeyboardButton("🥇 MT5 GOLD", callback_data="MENU_MT5")]]))

async def testbybit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    last, mark = get_bybit_tickers("PAXGUSDT")
    okx=get_okx_price("PAXGUSDT")
    await update.message.reply_text(f"✅ PAXG Bybit: Last {last} Mark {mark}\n✅ PAXG OKX: {okx}\n✅ XAUUSD TP1,2,3 + SL enabled\n✅ Menu enabled", reply_markup=mt5_keyboard())

async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: await update.message.reply_text("Example: /analyze BTC or /analyze XAUUSD", reply_markup=coins_keyboard()); return
    symbol=clean_symbol(context.args[0]); await run_analysis(update,symbol)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query; await query.answer()
    data=query.data
    if data=="MENU_COINS":
        await query.edit_message_text("📋 SELECT CRYPTO COIN:", reply_markup=coins_keyboard())
        return
    if data=="MENU_MT5":
        await query.edit_message_text("🥇 MT5 MENU - SELECT GOLD:", reply_markup=mt5_keyboard())
        return
    if data.startswith("COIN_"):
        symbol=data.replace("COIN_","")
        await query.edit_message_text(f"🔎 Analyzing {symbol}...")
        # Create dummy update for run_analysis
        await run_analysis(query, symbol)

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text=(update.message.text or "").strip()
    if not text: return
    if len(text.split())==1:
        symbol=clean_symbol(text)
        if symbol in CRYPTO or symbol=="XAUUSD" or symbol in MT5_ASSETS: await run_analysis(update,symbol); return

async def run_analysis(update_or_query, symbol: str):
    # Support both Message and CallbackQuery
    is_query = hasattr(update_or_query, 'message') and hasattr(update_or_query, 'edit_message_text') == False or type(update_or_query).__name__=='CallbackQuery'
    # Actually check if it's CallbackQuery
    from telegram import CallbackQuery
    if isinstance(update_or_query, CallbackQuery):
        send_msg = update_or_query.message.reply_text
        send_photo = update_or_query.message.reply_photo
        query = update_or_query
        await query.message.reply_text(f"🔎 PHILEDIZ analyzing {symbol} + SMC chart...")
    else:
        send_msg = update_or_query.message.reply_text
        send_photo = update_or_query.message.reply_photo
        await update_or_query.message.reply_text(f"🔎 PHILEDIZ analyzing {symbol} + SMC chart...")

    if symbol=="XAUUSD" or symbol=="PAXG" or symbol in MT5_ASSETS:
        result=get_xauusd()
        if not result:
            await send_msg("❌ XAUUSD/PAXG unavailable. Try /mt5")
            return
        chart_path=create_chart(result["candles"], {"direction":result["direction"],"price":result["price"],"support":result["support"],"resistance":result["resistance"],"pattern":result["pattern"],"score":result["score"]}, "XAUUSD")
        if chart_path:
            try: await send_photo(photo=open(chart_path,'rb'), caption=f"📸 XAUUSD SMC - {result['direction']} | TP1,2,3 + SL | {result['source']}")
            except: pass
        await send_msg(xau_message(result), reply_markup=mt5_keyboard())
        return

    result=analyze_crypto(symbol)
    if not result:
        await send_msg("❌ Data unavailable. Try again.", reply_markup=coins_keyboard())
        return
    chart_path=create_chart(result["candles"], result, symbol)
    if chart_path:
        try:
            await send_photo(photo=open(chart_path,'rb'), caption=f"📸 {symbol} SMC | {result['direction']} | Lev {result['leverage']:g}x Safe | {result['pair']}")
        except: pass
    await send_msg(crypto_message(result), reply_markup=coins_keyboard())

def run_flask(): app.run(host="0.0.0.0",port=PORT,debug=False,use_reloader=False)

def run_bot():
    if not BOT_TOKEN: print("BOT_TOKEN missing",flush=True); return
    application=ApplicationBuilder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start",start))
    application.add_handler(CommandHandler("coins",coins_command))
    application.add_handler(CommandHandler("mt5",mt5_command))
    application.add_handler(CommandHandler("help",help_command))
    application.add_handler(CommandHandler("testbybit",testbybit_command))
    application.add_handler(CommandHandler("analyze",analyze_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_handler))
    print("🤖 PHILEDIZ V2 MENU + XAUUSD TP FIXED",flush=True)
    application.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    threading.Thread(target=run_flask,daemon=True).start()
    run_bot()
