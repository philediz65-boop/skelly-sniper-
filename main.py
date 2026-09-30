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

BYBIT_BASES=["https://api.bybit.com"]
SESSION=requests.Session()
SESSION.headers.update({"User-Agent":"Mozilla/5.0 PHILEDIZ-ORIGINAL-FIXED","Accept":"application/json"})
REAL_LEV_FALLBACK={"BTCUSDT":15,"ETHUSDT":15,"SOLUSDT":10,"BNBUSDT":10,"XRPUSDT":10,"DOGEUSDT":10,"ADAUSDT":10,"AVAXUSDT":10,"LINKUSDT":10,"TRXUSDT":10,"DOTUSDT":10,"MATICUSDT":10,"LTCUSDT":10,"BCHUSDT":10,"UNIUSDT":10,"ATOMUSDT":10,"ETCUSDT":10,"FILUSDT":10,"PEPEUSDT":5,"BONKUSDT":5,"SHIBUSDT":5,"FLOKIUSDT":5,"FARTCOINUSDT":5,"WIFUSDT":5,"BABYUSDT":5,"BOMEUSDT":5,"PAXGUSDT":10}

@app.get("/")
def home(): return "PHILEDIZ ORIGINAL SETUP FIXED", 200
@app.get("/health")
def health(): return {"status":"ok"}, 200

def clean_symbol(t:str)->str:
    t=t.upper().strip().replace("/","").replace("-","").replace("_","")
    t=re.sub(r"[^A-Z0-9]","",t)
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

def get_bybit_klines(symbol, interval="15", limit=200
