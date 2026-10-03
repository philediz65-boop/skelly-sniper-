import os,re,threading,requests,time
from flask import Flask
from telegram import InlineKeyboardButton,InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder,CommandHandler,MessageHandler,CallbackQueryHandler,filters

BOT_TOKEN=os.getenv("BOT_TOKEN","").strip()
PORT=int(os.getenv("PORT","10000"))
app=Flask(__name__)

CRYPTO={"BTC":"BTCUSDT","ETH":"ETHUSDT","BNB":"BNBUSDT","SOL":"SOLUSDT","XRP":"XRPUSDT","DOGE":"DOGEUSDT","ADA":"ADAUSDT","AVAX":"AVAXUSDT","LINK":"LINKUSDT","TRX":"TRXUSDT","DOT":"DOTUSDT","MATIC":"MATICUSDT","LTC":"LTCUSDT","BCH":"BCHUSDT","UNI":"UNIUSDT","ATOM":"ATOMUSDT","ETC":"ETCUSDT","FIL":"FILUSDT","PEPE":"PEPEUSDT","BONK":"BONKUSDT","SHIB":"SHIBUSDT","FLOKI":"FLOKIUSDT","FARTCOIN":"FARTCOINUSDT","WIF":"WIFUSDT","BABY":"BABYUSDT","BOME":"BOMEUSDT","PAXG":"PAXGUSDT"}
SESSION=requests.Session()
SESSION.headers.update({"User-Agent":"Mozilla/5.0"})
CACHE={}

@app.get("/")
def home(): return "PHILEDIZ XAU LIVE OK",200
@app.get("/health")
def health(): return {"ok":True},200

def clean(t):
    t=t.upper().strip().replace("/","").replace("-","").replace("_","")
    t=re.sub(r"[^A-Z0-9]","",t)
    m={"BITCOIN":"BTC","ETHEREUM":"ETH","SOLANA":"SOL","GOLD":"XAUUSD","XAU":"XAUUSD","XAUUSD":"XAUUSD","PAXG":"PAXG"}
    if t in m: t=m[t]
    if t.endswith("USDT") and t[:-4] in CRYPTO: return t[:-4]
    return t
def fmt(v): return f"{v:,.2f}" if v>=1000 else f"{v:,.4f}" if v>=1 else f"{v:,.6f}"

def get_klines(sym, use_cache=True):
    if use_cache and sym in CACHE and time.time()-CACHE[sym][0]<300:
        return CACHE[sym][1]
    try:
        inst=sym.replace("USDT","-USDT")
        r=SESSION.get("https://www.okx.com/api/v5/market/candles",params={"instId":inst,"bar":"1H","limit":"200"},timeout=10).json()
        data=r.get("data",[])
        if len(data)>=50:
            c=[{"h":float(row[2]),"l":float(row[3]),"c":float(row[4])} for row in data]
            c.reverse()
            if use_cache: CACHE[sym]=(time.time(),c)
            return c
    except: pass
    try:
        pair=sym.replace("USDT","_USDT")
        r=SESSION.get("https://api.gateio.ws/api/v4/spot/candlesticks",params={"currency_pair":pair,"interval":"1h","limit":"200"},timeout=10).json()
        if isinstance(r,list) and len(r)>=50:
            kl=[{"h":float(x[3]),"l":float(x[4]),"c":float(x[2])} for x in r]
            if use_cache: CACHE[sym]=(time.time(),kl)
            return kl
    except: pass
    try:
        r=SESSION.get("https://data-api.binance.vision/api/v3/klines",params={"symbol":sym,"interval":"1h","limit":200},timeout=10).json()
        if isinstance(r,list) and len(r)>=50:
            kl=[{"h":float(x[2]),"l":float(x[3]),"c":float(x[4])} for x in r]
            if use_cache: CACHE[sym]=(time.time(),kl)
            return kl
    except: pass
    return []

def get_price(sym):
    try:
        inst=sym.replace("USDT","-USDT")
        r=SESSION.get("https://www.okx.com/api/v5/market/ticker",params={"instId":inst},timeout=5).json()
        return float(r["data"][0]["last"])
    except: pass
    try:
        r=SESSION.get("https://data-api.binance.vision/api/v3/ticker/price",params={"symbol":sym},timeout=5).json()
        if "price" in r: return float(r["price"])
    except: pass
    try:
        pair=sym.replace("USDT","_USDT")
        r=SESSION.get(f"https://api.gateio.ws/api/v4/spot/tickers",params={"currency_pair":pair},timeout=5).json()
        if isinstance(r,list) and r: return float(r[0]["last"])
    except: pass
    return None

def ema(v,p):
    if len(v)<p: return None
    m=2/(p+1); res=sum(v[:p])/p
    for x in v[p:]: res=(x-res)*m+res
    return res
def rsi(v):
    if len(v)<15: return 50
    g=[];l=[]
    for i in range(1,len(v)):
        ch=v[i]-v[i-1]; g.append(max(ch,0)); l.append(max(-ch,0))
    ag=sum(g[:14])/14; al=sum(l[:14])/14
    if al==0: return 70
    return 100-(100/(1+ag/al))
def atr(c):
    if len(c)<15: return c[-1]["h"]-c[-1]["l"]
    trs=[max(c[i]["h"]-c[i]["l"],abs(c[i]["h"]-c[i-1]["c"]),abs(c[i]["l"]-c[i-1]["c"])) for i in range(1,len(c))]
    return sum(trs[-14:])/14

def analyze(code):
    sym=CRYPTO.get(code)
    kl=get_klines(sym, use_cache=True)
    if len(kl)<50: return None
    closes=[x["c"] for x in kl]
    live=get_price(sym)
    price=live if live else closes[-1]
    e20=ema(closes,20); e50=ema(closes,50); rr=rsi(closes); a=atr(kl)
    if not e20 or not e50: return None
    score=(1 if price>e20 else -1)+(1 if e20>e50 else -1)+(1 if rr>55 else -1 if rr<45 else 0)
    d="BUY" if score>=2 else "SELL" if score<=-2 else "WAIT"
    lev=15 if code in ["BTC","ETH"] else 10 if code in ["SOL","BNB","XRP","PAXG"] else 5
    if d=="BUY": sl=price-1.5*a; tp1=price+1.5*a; tp2=price+2.5*a; tp3=price+4*a
    elif d=="SELL": sl=price+1.5*a; tp1=price-1.5*a; tp2=price-2.5*a; tp3=price-4*a
    else: sl=tp1=tp2=tp3=None
    return {"sym":sym,"price":price,"e20":e20,"e50":e50,"rsi":rr,"dir":d,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"lev":lev,"score":score}

def get_xau():
    # === LIVE PRICE - NO CACHE ===
    live_price=None
    src=""

    # 1. Try real gold API
    try:
        r=SESSION.get("https://api.gold-api.com/price/XAU",timeout=4)
        if r.status_code==200:
            p=float(r.json().get("price",0))
            if 3000<p<6000:
                live_price=p
                src=f"REAL GOLD API ${p:.2f}"
    except: pass

    # 2. Try OKX PAXG live ticker (always changes)
    try:
        r=SESSION.get("https://www.okx.com/api/v5/market/ticker",params={"instId":"PAXG-USDT"},timeout=4).json()
        p=float(r["data"][0]["last"])
        if not live_price:
            live_price=p
            src=f"OKX PAXG LIVE ${
