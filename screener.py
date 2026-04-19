import yfinance as yf
import pandas as pd
import requests
import os
from datetime import datetime

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

US_WATCHLIST = [
    "AAPL","MSFT","NVDA","AMD","META","GOOGL","AMZN","TSLA",
    "AVGO","ORCL","CRM","PANW","SNOW","PLTR","SMCI","ARM",
    "TSM","ASML","MRVL","QCOM","AMAT","KLAC","LRCX","MU",
    "GS","V","MA","PYPL","SQ","COIN",
    "SPY","QQQ","SOXX","XLK"
]

TW_WATCHLIST = [
    "2330.TW","2317.TW","2454.TW","2382.TW","2308.TW",
    "2303.TW","2881.TW","2882.TW","2891.TW","2886.TW",
    "3711.TW","2379.TW","2345.TW","3034.TW","6770.TW",
    "2395.TW","3008.TW","2357.TW","4938.TW","6669.TW"
]

def fetch_data(ticker):
    try:
        df = yf.download(ticker, period="90d", interval="1d",
                         auto_adjust=True, progress=False)
        if len(df) < 30:
            return None
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        return df
    except Exception:
        return None

def calc_indicators(df):
    close = df["Close"]
    volume = df["Volume"]
    ma20  = close.rolling(20).mean()
    ma60  = close.rolling(60).mean()
    vol5  = volume.rolling(5).mean()
    vol20 = volume.rolling(20).mean()
    last_close = float(close.iloc[-1])
    last_ma20  = float(ma20.iloc[-1])
    last_ma60  = float(ma60.iloc[-1])
    last_vol5  = float(vol5.iloc[-1])
    last_vol20 = float(vol20.iloc[-1])
    pct_5d = (last_close / float(close.iloc[-6]) - 1) * 100 if len(close) >= 6 else 0
    return {
        "close"    : last_close,
        "ma20"     : last_ma20,
        "ma60"     : last_ma60,
        "vol_ratio": last_vol5 / last_vol20 if last_vol20 > 0 else 0,
        "pct_5d"   : pct_5d,
        "above_ma20": last_close > last_ma20,
        "above_ma60": last_close > last_ma60,
        "ma20_up"   : float(ma20.iloc[-1]) > float(ma20.iloc[-5]),
        "ma60_up"   : float(ma60.iloc[-1]) > float(ma60.iloc[-5]),
    }

def is_qualified(ind):
    trend_ok    = ind["above_ma20"] and ind["above_ma60"] and ind["ma20_up"] and ind["ma60_up"]
    volume_ok   = ind["vol_ratio"] >= 1.3
    momentum_ok = ind["pct_5d"] > 0
    return trend_ok and volume_ok and momentum_ok

def screen(tickers):
    results = []
    for ticker in tickers:
        df = fetch_data(ticker)
        if df is None:
            continue
        ind = calc_indicators(df)
        if is_qualified(ind):
            results.append({
                "ticker"   : ticker,
                "close"    : ind["close"],
                "pct_5d"   : ind["pct_5d"],
                "vol_ratio": ind["vol_ratio"],
            })
    return results

def format_message(us_hits, tw_hits):
    today = datetime.now().strftime("%Y/%m/%d")
    lines = [f"📊 *波段觀察名單 {today}*\n"]

    def block(title, hits):
        if not hits:
            return f"*{title}*\n- 今日無符合標的\n"
        rows = [f"*{title}*"]
        for h in sorted(hits, key=lambda x: x["vol_ratio"], reverse=True):
            ticker = h['ticker'].replace('.TW','')
            pct = h['pct_5d']
            vol = h['vol_ratio']
            price = h['close']
            rows.append(f"- {ticker}  ${price:.2f}  5d:{pct:+.1f}%  vol:{vol:.1f}x")
        return "\n".join(rows) + "\n"

    lines.append(block("美股", us_hits))
    lines.append(block("台股", tw_hits))
    lines.append("條件: 股價>MA20>MA60 均線走揚 | 量比1.3x+ | 近5日正報酬")
    return "\n".join(lines)

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()

if __name__ == "__main__":
    print("scanning US stocks...")
    us_hits = screen(US_WATCHLIST)
    print("scanning TW stocks...")
    tw_hits = screen(TW_WATCHLIST)
    msg = format_message(us_hits, tw_hits)
    print(msg)
    send_telegram(msg)
    print("done")
