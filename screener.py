import yfinance as yf
import pandas as pd
import requests
import os
from datetime import datetime

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
MODE = os.environ.get("MODE", "morning")

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

TW_MARKET = [
    ("TWII", "^TWII"),
    ("TSMC", "2330.TW"),
    ("MediaTek", "2454.TW"),
    ("Foxconn", "2317.TW"),
    ("Delta", "2308.TW"),
    ("Fubon", "2881.TW"),
]

US_MARKET = [
    ("SP500", "^GSPC"),
    ("Nasdaq", "^IXIC"),
    ("Dow", "^DJI"),
    ("VIX", "^VIX"),
    ("NVDA", "NVDA"),
    ("AAPL", "AAPL"),
    ("MSFT", "MSFT"),
    ("TSLA", "TSLA"),
    ("AMD", "AMD"),
    ("SOXX", "SOXX"),
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

def calc_rsi(close, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calc_indicators(df):
    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    vol5 = volume.rolling(5).mean()
    vol20 = volume.rolling(20).mean()
    rsi = calc_rsi(close)
    last_close = float(close.iloc[-1])
    last_high = float(high.iloc[-1])
    last_low = float(low.iloc[-1])
    day_range = last_high - last_low
    close_strength = (last_close - last_low) / day_range if day_range > 0 else 0.5
    pct_5d = (last_close / float(close.iloc[-6]) - 1) * 100 if len(close) >= 6 else 0
    return {
        "close": last_close,
        "vol_ratio": float(vol5.iloc[-1]) / float(vol20.iloc[-1]) if float(vol20.iloc[-1]) > 0 else 0,
        "pct_5d": pct_5d,
        "rsi": float(rsi.iloc[-1]),
        "close_strength": close_strength,
        "above_ma20": last_close > float(ma20.iloc[-1]),
        "above_ma60": last_close > float(ma60.iloc[-1]),
        "ma20_up": float(ma20.iloc[-1]) > float(ma20.iloc[-5]),
        "ma60_up": float(ma60.iloc[-1]) > float(ma60.iloc[-5]),
    }

def is_qualified(ind):
    trend_ok = ind["above_ma20"] and ind["above_ma60"] and ind["ma20_up"] and ind["ma60_up"]
    volume_ok = ind["vol_ratio"] >= 1.3
    momentum_ok = ind["pct_5d"] > 0
    rsi_ok = 50 <= ind["rsi"] <= 75
    strength_ok = ind["close_strength"] >= 0.8
    return trend_ok and volume_ok and momentum_ok and rsi_ok and strength_ok

def screen(tickers):
    results = []
    for ticker in tickers:
        df = fetch_data(ticker)
        if df is None:
            continue
        ind = calc_indicators(df)
        if is_qualified(ind):
            results.append({
                "ticker": ticker,
                "close": ind["close"],
                "pct_5d": ind["pct_5d"],
                "vol_ratio": ind["vol_ratio"],
                "rsi": ind["rsi"],
                "close_strength": ind["close_strength"],
            })
    return results

def fetch_quote(ticker):
    try:
        df = yf.download(ticker, period="5d", interval="1d",
                         auto_adjust=True, progress=False)
        if len(df) < 2:
            return None
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        last = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2])
        pct = (last / prev - 1) * 100
        return {"price": last, "pct": pct}
    except Exception:
        return None

def format_quote_block(title, market_list):
    lines = [title]
    for name, ticker in market_list:
        q = fetch_quote(ticker)
        if q is None:
            lines.append(name + ": N/A")
            continue
        arrow = "up" if q["pct"] >= 0 else "dn"
        lines.append(name + " " + str(round(q["price"], 2)) + " (" + arrow + " " + str(round(q["pct"], 2)) + "%)")
    return "\n".join(lines)

def fetch_institutional_flow():
    try:
        url = "https://www.twse.com.tw/rwd/zh/fund/BFI82U?type=day&response=json"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = r.json()
        if data.get("stat") != "OK":
            return None
        results = []
        for row in data.get("data", []):
            name = row[0].strip()
            try:
                net = int(row[3].replace(",", ""))
            except Exception:
                net = 0
            results.append({"name": name, "net": net})
        return results
    except Exception:
        return None

def fetch_industry_flow():
    try:
        url = "https://www.twse.com.tw/rwd/zh/fund/TWT38U?response=json"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = r.json()
        if data.get("stat") != "OK":
            return None
        rows = []
        for row in data.get("data", []):
            try:
                net = int(row[4].replace(",", "").replace(" ", ""))
            except Exception:
                net = 0
            rows.append({"industry": row[0].strip(), "net": net})
        rows.sort(key=lambda x: x["net"], reverse=True)
        return rows
    except Exception:
        return None

def format_institutional_block():
    lines = ["--- Institutional Flow ---"]
    flow = fetch_institutional_flow()
    if flow:
        for item in flow:
            arrow = "+" if item["net"] >= 0 else "-"
            lines.append(arrow + " " + item["name"] + ": " + str(item["net"]) + "M")
    else:
        lines.append("No data yet")
    lines.append("")
    industries = fetch_industry_flow()
    if industries:
        lines.append("Top 5 inflow sectors:")
        for item in industries[:5]:
            lines.append("+ " + item["industry"] + ": " + str(item["net"]) + "M")
        lines.append("")
        lines.append("Bottom 3 outflow sectors:")
        for item in industries[-3:]:
            lines.append("- " + item["industry"] + ": " + str(item["net"]) + "M")
    else:
        lines.append("No sector data yet")
    return "\n".join(lines)

def morning_message():
    today = datetime.now().strftime("%Y/%m/%d")
    lines = ["Good morning! Stock Watch " + today, ""]
    us_hits = screen(US_WATCHLIST)
    tw_hits = screen(TW_WATCHLIST)

    lines.append("== US Stocks ==")
    if not us_hits:
        lines.append("No qualified stocks today")
    else:
        for h in sorted(us_hits, key=lambda x: x["vol_ratio"], reverse=True):
            t = h["ticker"]
            p = str(round(h["close"], 2))
            d = str(round(h["pct_5d"], 1))
            r = str(round(h["rsi"], 0))
            v = str(round(h["vol_ratio"], 1))
            s = str(round(h["close_strength"] * 100, 0))
            lines.append(t + " $" + p + " 5d:" + d + "% RSI:" + r + " vol:" + v + "x str:" + s + "%")

    lines.append("")
    lines.append("== TW Stocks ==")
    if not tw_hits:
        lines.append("No qualified stocks today")
    else:
        for h in sorted(tw_hits, key=lambda x: x["vol_ratio"], reverse=True):
            t = h["ticker"].replace(".TW", "")
            p = str(round(h["close"], 2))
            d = str(round(h["pct_5d"], 1))
            r = str(round(h["rsi"], 0))
            v = str(round(h["vol_ratio"], 1))
            s = str(round(h["close_strength"] * 100, 0))
            lines.append(t + " $" + p + " 5d:" + d + "% RSI:" + r + " vol:" + v + "x str:" + s + "%")

    lines.append("")
    lines.append("Conditions: MA bullish | RSI 50-75 | vol 1.3x+ | close str 80%+")
    lines.append("")
    lines.append(format_institutional_block())
    return "\n".join(lines)

def tw_close_message():
    today = datetime.now().strftime("%Y/%m/%d")
    lines = ["TW Market Close " + today, ""]
    lines.append(format_quote_block("== TW Market ==", TW_MARKET))
    lines.append("")
    lines.append(format_institutional_block())
    return "\n".join(lines)

def us_close_message():
    today = datetime.now().strftime("%Y/%m/%d")
    lines = ["US Market Close " + today, ""]
    lines.append(format_quote_block("== US Market ==", US_MARKET))
    lines.append("")
    vix = fetch_quote("^VIX")
    if vix:
        v = vix["price"]
        if v < 15:
            mood = "Extremely bullish, watch for overheating"
        elif v < 20:
            mood = "Market calm"
        elif v < 30:
            mood = "Panic emerging, watch volatility"
        else:
            mood = "Extreme fear, crisis mode"
        lines.append("VIX " + str(round(v, 1)) + " -> " + mood)
    return "\n".join(lines)

def send_telegram(text):
    url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()

if __name__ == "__main__":
    if MODE == "morning":
        print("morning mode...")
        msg = morning_message()
    elif MODE == "tw_close":
        print("tw close mode...")
        msg = tw_close_message()
    elif MODE == "us_close":
        print("us close mode...")
        msg = us_close_message()
    else:
        msg = "Unknown mode"
    print(msg)
    send_telegram(msg)
    print("done")
