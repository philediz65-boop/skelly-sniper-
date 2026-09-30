import os, threading, requests, time
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN","").strip()
PORT = int(os.getenv("PORT","10000"))
COINS = ["BTC","ETH","SOL","BNB","XRP","DOGE","AVAX","ADA","LINK","DOT","MATIC","LTC","BCH","UNI","ATOM","ETC","FIL","HBAR","NEAR","APT","SUI","SEI","INJ","TIA","ARB","OP","PEPE","BONK","SHIB","FLOKI","FARTCOIN","WIF","BABY","BOME","BRETT","POPCAT","TRUMP","TURBO","GOAT","PNUT","ACT","MEW","NEIRO","NOT","JUP","ENA","WLD","FET","RNDR","IMX"]
CACHE={}

def fmt(v):
    v=float(v)
    return f"{v:.6f}" if v<0.0001 else f"{v:.5f}" if v<0.01 else f"{v:.4f}" if v<1 else f"{v:.2f}"

def get_price(s):
    try:
        r=requests.get(f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={s}USDT",timeout=10).json()
        return float(r["result"]["list"][0]["lastPrice"])
    except:
        try:
            r=requests.get(f"https://www.okx.com/api/v5/market/ticker?instId={s}-USDT",timeout=10).json()
            return float(r["data"][0]["last"])
        except: return None

def get_leverage(s):
    if s in CACHE and time.time()-CACHE[s][1]<3600: return CACHE[s][0]
    try:
        r=requests.get(f"https://api.bybit.com/v5/market/instruments-info?category=linear&symbol={s}USDT",timeout=10).json()
        lev=float(r["result"]["list"][0]["leverageFilter"]["maxLeverage"])
        ls=f"{lev:g}x"; CACHE[s]=(ls,time.time()); return ls
    except: return "25x"

def menu(pg=0):
    per=12; st=pg*per; ch=COINS[st:st+per]; b=[]; row=[]
    for c in ch:
        row.append(InlineKeyboardButton(c, callback_data=f"C_{c}"))
        if len(row)==3: b.append(row); row=[]
    if row: b.append(row)
    nav=[]
    if pg>0: nav.append(InlineKeyboardButton("Prev", callback_data=f"P_{pg-1}"))
    if st+per<len(COINS): nav.append(InlineKeyboardButton("Next", callback_data=f"P_{pg+1}"))
    if nav: b.append(nav)
    return InlineKeyboardMarkup(b)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Skelly 50 - Real Leverage Per Coin\nSelect:", reply_markup=menu(0))

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer(); d=q.data
    if d.startswith("P_"):
        pg=int(d[2:]); await q.edit_message_text(f"Page {pg+1}", reply_markup=menu(pg)); return
    if d.startswith("C_"):
        sym=d[2:]; await q.edit_message_text(f"Fetching {sym}...")
        pr=get_price(sym); lev=get_leverage(sym)
        if pr:
            txt=f"BUY - {sym}\n\nEntry: {fmt(pr)}\nLeverage: {lev} (Bybit Real Max)\n\nTP1 {fmt(pr*1.02)} / TP2 {fmt(pr*1.05)} / SL {fmt(pr*0.95)}"
        else: txt=f"{sym} loading - tap again"
        await context.bot.send_message(chat_id=q.message.chat.id, text=txt, reply_markup=menu(0))

def run_bot():
    if not BOT_TOKEN: print("No BOT_TOKEN set"); return
    app=ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle))
    app.run_polling()

flask_app=Flask(__name__)
@flask_app.route("/")
def home(): return "OK",200

if __name__=="__main__":
    threading.Thread(target=lambda: flask_app.run(host="0.0.0.0",port=PORT), daemon=True).start()
    run_bot()
