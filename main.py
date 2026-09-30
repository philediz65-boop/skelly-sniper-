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
    return {"symbol":symbol_code,"pair":symbol,"price":live_price,"mark":mark_price,"mark_diff":mark_diff,"candles":candles,"ema20":e20,"ema50":e50,"ema200":e200,"rsi":r14,"atr":a14,"macd":macd_line,"macd_hist":macd_hist,"bb_up":bb_up,"bb_low":bb_low,"support":sup,"resistance":res,"momentum":mom,"pattern":pattern,"vol_confirm":vol_confirm,"score":score,"direction":direction,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"leverage":lev,"reasons":reasons,"timeframe":"15M","source":"Bybit (linear+spot) + OKX"}

def get_xauusd():
    real_gold_price=None
    try:
        r=SESSION.get("https://api.gold-api.com/price/XAU", timeout=10)
        if r.status_code==200:
            real_gold_price=float(r.json().get("price",0))
    except: pass
    if not real_gold_price:
        try:
            r=SESSION.get("https://query1.finance.yahoo.com/v8/finance/chart/XAUUSD=X", params={"range":"1d","interval":"1m"}, timeout=10)
            if r.status_code==200:
                real_gold_price=float(r.json()["chart"]["result"][0]["meta"]["regularMarketPrice"])
        except: pass
    candles=get_bybit_klines("PAXGUSDT","15",200)
    if len(candles)<60:
        candles=get_okx_klines("PAXGUSDT","15m",150)
    if len(candles)>=60:
        closes_orig=[c["close"] for c in candles]
        paxg_last=closes_orig[-1]
        if real_gold_price and abs(real_gold_price-paxg_last)<300:
            offset=real_gold_price-paxg_last
            new_candles=[]
            for c in candles:
                new_candles.append({"time":c["time"],"open":c["open"]+offset,"high":c["high"]+offset,"low":c["low"]+offset,"close":c["close"]+offset,"volume":c["volume"]})
            candles=new_candles
            display_price=real_gold_price
            source=f"REAL XAUUSD ${real_gold_price:.2f} Live + PAXG chart"
        else:
            display_price=paxg_last
            source=f"PAXGUSDT ${paxg_last:.2f} proxy"
        closes=[c["close"] for c in candles]
        e20=ema(closes,20); e50=ema(closes,50); r14=rsi(closes,14); a14=atr(candles,14)
        if None not in (e20,e50,r14,a14):
            sup=min(c["low"] for c in candles[-50:]); res=max(c["high"] for c in candles[-50:])
            pattern=candle_pattern(candles)
            score=(1 if display_price>e20 else -1)+(1 if e20>e50 else -1)+(1 if r14>=55 else -1 if r14<=45 else 0)
            direction="BUY" if score>=2 else "SELL" if score<=-2 else "WAIT"
            if direction=="BUY":
                sl=display_price-1.2*a14; tp1=display_price+1.0*a14; tp2=display_price+2.0*a14; tp3=display_price+3.5*a14
            elif direction=="SELL":
                sl=display_price+1.2*a14; tp1=display_price-1.0*a14; tp2=display_price-2.0*a14; tp3=display_price-3.5*a14
            else:
                sl=display_price-1.2*a14; tp1=display_price+1.0*a14; tp2=display_price+2.0*a14; tp3=display_price+3.5*a14
            lev=get_real_leverage("PAXGUSDT")
            return {"pair":f"XAUUSD ${display_price:.2f}","symbol":"XAUUSD","price":display_price,"candles":candles,"ema20":e20,"ema50":e50,"rsi":r14,"atr":a14,"support":sup,"resistance":res,"pattern":pattern,"direction":direction,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"leverage":lev,"timeframe":"15M","source":source,"score":score}
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
        ax.set_xlim(-5, n+20); ax.get_xaxis().set_visible(False)
        ax.tick_params(axis='y', colors='black', labelsize=8)
        ax.spines['top'].set_visible(False); ax.spines['bottom'].set_visible(False); ax.spines['left'].set_visible(False); ax.spines['right'].set_visible(False)
        ax.set_title(f'{symbol} - Order Block + BOS - {analysis["direction"]} | {analysis["pattern"]} | ${analysis["price"]:.2f}', color='black', fontsize=10, loc='left')
        plt.tight_layout()
        path="/tmp/philediz_smc_chart.png"
        plt.savefig(path, dpi=300, facecolor='white', bbox_inches='tight')
        plt.close()
        return path
    except: return None

def crypto_message(a: dict)->str:
    lev=f"{a['leverage']:g}x"; direction=a['direction']; emoji="🟢 BUY" if direction=="BUY" else "🔴 SELL" if direction=="SELL" else "⚪ WAIT"
    vol_txt="✅ High" if a['vol_confirm'] else "⚪ Normal"
    hist_emoji="🟢" if a['macd_hist'] and a['macd_hist']>0 else "🔴" if a['macd_hist'] and a['macd_hist']<0 else "⚪"
    lines=["🤖 PHILEDIZ V2 PRO ANALYSIS","",f"🪙 Pair: {a['pair']}",f"⏱ Timeframe: {a['timeframe']}",f"💰 Last: {fmt_price(a['price'])}",f"🎯 Mark: {fmt_price(a['mark'])} ({a['mark_diff']:+.3f}%)",f"📡 Source: {a['source']}","","📊 INDICATORS",f"🕯 Candle: {a['pattern']}",f"📈 EMA20: {fmt_price(a['ema20'])} | EMA50: {fmt_price(a['ema50'])}",f"💪 RSI14: {a['rsi']:.1f}",f"📉 MACD: {hist_emoji} {a['macd']:.4f}" if a['macd'] else "📉 MACD: N/A",f"📦 Volume: {vol_txt}",f"⚡ ATR: {fmt_price(a['atr'])} | Mom: {a['momentum']:+.2f}%","",f"📌 SETUP: {emoji} (Score {a['score']}/10)"]
    if a['reasons']: lines+=["","🔍 Logic:"]+[f"• {r}" for r in a['reasons'][:5]]
    if direction!="WAIT":
        entry=a['price']; sl_pct=(a['sl']-entry)/entry*100; tp1_pct=(a['tp1']-entry)/entry*100; tp2_pct=(a['tp2']-entry)/entry*100; tp3_pct=(a['tp3']-entry)/entry*100
        lines+=["","━━━━━━━━━━━━━━━━━━",f"{emoji} {a['symbol']}","",f"💵 Entry: {fmt_price(entry)} | ⚡ Leverage: {lev} (Small Safe)",f"🛑 SL: {fmt_price(a['sl'])} ({sl_pct:+.2f}%)",f"🎯 TP1: {fmt_price(a['tp1'])} ({tp1_pct:+.2f}%)",f"🎯 TP2: {fmt_price(a['tp2'])} ({tp2_pct:+.2f}%)",f"🎯 TP3: {fmt_price(a['tp3'])} ({tp3_pct:+.2f}%)","━━━━━━━━━━━━━━━━━━","","📸 SMC Chart above 👆","💡 Move SL to BE after TP1"]
    else:
        lines+=["",f"⚡ Safe Leverage: {lev}","","⏳ WAIT - Low confluence","📸 SMC Chart above 👆"]
    lines+=["","⚠️ Not financial advice."]
    return "\n".join(lines)

def xau_message(a: dict)->str:
    emoji="🟢 BUY" if a['direction']=="BUY" else "🔴 SELL" if a['direction']=="SELL" else "⚪ WAIT"
    lev=f"{a['leverage']:g}x"; entry=a['price']; sl_pct=(a['sl']-entry)/entry*100; tp1_pct=(a['tp1']-entry)/entry*100; tp2_pct=(a['tp2']-entry)/entry*100; tp3_pct=(a['tp3']-entry)/entry*100
    return "\n".join(["🤖 PHILEDIZ V2 MT5 GOLD ANALYSIS","","🥇 Pair: XAUUSD (REAL LIVE PRICE)",f"⏱ {a['timeframe']}",f"💰 REAL XAUUSD Price: {fmt_price(a['price'])}",f"📡 {a['source']}",f"⚡ ATR: {fmt_price(a['atr'])}","","📊 INDICATORS",f"🕯 {a['pattern']}",f"EMA20: {fmt_price(a['ema20'])} | EMA50: {fmt_price(a['ema50'])}",f"RSI14: {a['rsi']:.1f}","","📍 Support: {fmt_price(a['support'])} | Resistance: {fmt_price(a['resistance'])}","",f"📌 SETUP: {emoji} {a['direction']} (Score {a['score']}/10)","", "━━━━━━━━━━━━━━━━━━",f"{emoji} XAUUSD GOLD","",f"💵 Entry: {fmt_price(entry)} | ⚡ Leverage: {lev} (MT5 Safe)",f"🛑 SL: {fmt_price(a['sl'])} ({sl_pct:+.2f}%)",f"🎯 TP1: {fmt_price(a['tp1'])} ({tp1_pct:+.2f}%)",f"🎯 TP2: {fmt_price(a['tp2'])} ({tp2_pct:+.2f}%)",f"🎯 TP3: {fmt_price(a['tp3'])} ({tp3_pct:+.2f}%)","━━━━━━━━━━━━━━━━━━","","📸 SMC Chart above 👆","💡 MT5: Move SL to BE after TP1","","⚠️ Not financial advice."])

def coins_keyboard():
    coins=list(CRYPTO.keys())
    buttons=[]; row=[]
    for c in coins:
        row.append(InlineKeyboardButton(c, callback_data=f"COIN_{c}"))
        if len(row)==3:
            buttons.append(row); row=[]
    if row: buttons.append(row)
    buttons.append([InlineKeyboardButton("🥇 MT5 GOLD MENU", callback_data="MENU_MT5")])
    return InlineKeyboardMarkup(buttons)

def mt5_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🥇 XAUUSD REAL $4154", callback_data="COIN_XAUUSD"), InlineKeyboardButton("🪙 PAXG", callback_data="COIN_PAXG")],[InlineKeyboardButton("📋 ALL CRYPTO MENU", callback_data="MENU_COINS")]])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 PHILEDIZ V2 ORIGINAL + FIXED!\n\n📋 /coins → Crypto menu\n🥇 /mt5 → MT5 Gold\n\n✅ XAUUSD REAL price $4154 + TP1,2,3 + SL", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 CRYPTO MENU", callback_data="MENU_COINS"), InlineKeyboardButton("🥇 MT5 MENU", callback_data="MENU_MT5")]]))

async def coins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📋 SELECT CRYPTO COIN (BTC, ETH, SOL...):", reply_markup=coins_keyboard())

async def mt5_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🥇 MT5 MENU - REAL XAUUSD LIVE:", reply_markup=mt5_keyboard())

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📚 /coins - Crypto\n/mt5 - Gold\n/analyze BTC\n/analyze XAUUSD", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📋 CRYPTO", callback_data="MENU_COINS"), InlineKeyboardButton("🥇 MT5 GOLD", callback_data="MENU_MT5")]]))

async def testbybit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    last, mark = get_bybit_tickers("PAXGUSDT")
    okx=get_okx_price("PAXGUSDT")
    try: real=SESSION.get("https://api.gold-api.com/price/XAU", timeout=8).json().get("price")
    except: real="N/A"
    await update.message.reply_text(f"✅ REAL XAUUSD: ${real}\n✅ PAXG Bybit: {last} Mark {mark}\n✅ PAXG OKX: {okx}", reply_markup=mt5_keyboard())

async def analyze_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: await update.message.reply_text("Example: /analyze BTC or /analyze XAUUSD", reply_markup=coins_keyboard()); return
    symbol=clean_symbol(context.args[0]); await run_analysis(update,symbol)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query=update.callback_query; await query.answer()
    data=query.data
    if data=="MENU_COINS":
        await query.edit_message_text("📋 SELECT CRYPTO COIN:", reply_markup=coins_keyboard()); return
    if data=="MENU_MT5":
        await query.edit_message_text("🥇 MT5 MENU - REAL XAUUSD LIVE PRICE:", reply_markup=mt5_keyboard()); return
    if data.startswith("COIN_"):
        symbol=data.replace("COIN_","")
        await query.edit_message_text(f"🔎 Analyzing {symbol}...")
        await run_analysis(query, symbol)

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text=(update.message.text or "").strip()
    if not text: return
    if len(text.split())==1:
        symbol=clean_symbol(text)
        if symbol in CRYPTO or symbol=="XAUUSD": await run_analysis(update,symbol); return

async def run_analysis(update_or_query, symbol: str):
    from telegram import CallbackQuery
    if isinstance(update_or_query, CallbackQuery):
        send_msg = update_or_query.message.reply_text
        send_photo = update_or_query.message.reply_photo
    else:
        send_msg = update_or_query.message.reply_text
        send_photo = update_or_query.message.reply_photo
        await update_or_query.message.reply_text(f"🔎 Analyzing {symbol} + SMC chart...")
    if symbol=="XAUUSD" or symbol=="PAXG" or symbol=="GOLD":
        result=get_xauusd()
        if not result: await send_msg("❌ XAUUSD unavailable."); return
        chart_path=create_chart(result["candles"], {"direction":result["direction"],"price":result["price"],"support":result["support"],"resistance":result["resistance"],"pattern":result["pattern"],"score":result["score"]}, "XAUUSD")
        if chart_path:
            try: await send_photo(photo=open(chart_path,'rb'), caption=f"📸 XAUUSD REAL ${result['price']:.2f} | {result['direction']} | TP1,2,3 + SL")
            except: pass
        await send_msg(xau_message(result), reply_markup=mt5_keyboard())
        return
    result=analyze_crypto(symbol)
    if not result: await send_msg("❌ Data unavailable.", reply_markup=coins_keyboard()); return
    chart_path=create_chart(result["candles"], result, symbol)
    if chart_path:
        try: await send_photo(photo=open(chart_path,'rb'), caption=f"📸 {symbol} SMC | {result['direction']} | Lev {result['leverage']:g}x")
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
    print("🤖 PHILEDIZ ORIGINAL + FIXED READY",flush=True)
    application.run_polling(drop_pending_updates=True)

if __name__=="__main__":
    threading.Thread(target=run_flask,daemon=True).start()
    run_bot()
