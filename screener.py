import yfinance as yf
import pandas as pd
import requests
import os
import json
from pathlib import Path
from datetime import datetime

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
MODE = os.environ.get("MODE", "morning")

HISTORY_FILE = "history.json"

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
    ("加權指數", "IX0001"),
    ("台積電", "2330"),
    ("聯發科", "2454"),
    ("鴻海", "2317"),
    ("台達電", "2308"),
    ("富邦金", "2881"),
]

US_MARKET = [
    ("S&P500", "^GSPC"),
    ("那斯達克", "^IXIC"),
    ("道瓊", "^DJI"),
    ("恐慌指數VIX", "^VIX"),
    ("輝達NVDA", "NVDA"),
    ("蘋果AAPL", "AAPL"),
    ("微軟MSFT", "MSFT"),
    ("特斯拉TSLA", "TSLA"),
    ("超微AMD", "AMD"),
    ("費城半導體SOXX", "SOXX"),
]

def load_history():
    try:
        if Path(HISTORY_FILE).exists():
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_history(data):
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def update_streak(history, key, value, date_str):
    if key not in history:
        history[key] = {"streak": 0, "last_date": "", "last_value": 0}
    entry = history[key]
    if value > 0:
        if entry["last_date"] != date_str:
            entry["streak"] = entry.get("streak", 0) + 1
    else:
        entry["streak"] = 0
    entry["last_date"] = date_str
    entry["last_value"] = value
    return entry["streak"]

def check_alerts(history, today):
    alerts = []
    for key, entry in history.items():
        if entry.get("last_date") == today and entry.get("streak", 0) >= 3:
            val = entry.get("last_value", 0)
            direction = "買超" if val > 0 else "賣超"
            alerts.append(key + " 連續" + str(entry["streak"]) + "天" + direction)
    return alerts

def fmt_money(val):
    val = int(val)
    sign = "+" if val >= 0 else "-"
    val = abs(val)
    if val >= 100000000:
        return sign + str(round(val / 100000000, 1)) + " 億"
    elif val >= 10000000:
        return sign + str(round(val / 10000000, 1)) + " 千萬"
    elif val >= 10000:
        return sign + str(round(val / 10000, 1)) + " 萬"
    else:
        return sign + str(val)

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

def fetch_tw_quote(stock_id):
    try:
        if stock_id == "IX0001":
            url = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_t00.tw"
        else:
            url = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_" + stock_id + ".tw"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        items = data.get("msgArray", [])
        if not items:
            return None
        item = items[0]
        last = float(item.get("z", 0) or item.get("y", 0))
        prev = float(item.get("y", 0))
        if not last or not prev:
            return None
        pct = (last / prev - 1) * 100
        return {"price": last, "pct": pct}
    except Exception:
        return None

def fetch_us_quote(ticker):
    try:
        tk = yf.Ticker(ticker)
        df = tk.history(period="2d", interval="1d")
        if len(df) < 1:
            return None
        last = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2]) if len(df) >= 2 else last
        pct = (last / prev - 1) * 100
        return {"price": last, "pct": pct}
    except Exception:
        return None

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
            if name == "合計":
                net = -net
            results.append({"name": name, "net": net})
        return results
    except Exception:
        return None

def fetch_industry_flow():
    try:
        from datetime import timedelta
        today = datetime.now()
        # 如果是週一早上，抓上週五的資料
        if today.weekday() == 0 and today.hour < 16:
            date_str = (today - timedelta(days=3)).strftime("%Y%m%d")
        # 如果還沒到下午4點，抓前一個交易日
        elif today.hour < 16:
            date_str = (today - timedelta(days=1)).strftime("%Y%m%d")
        else:
            date_str = today.strftime("%Y%m%d")

        url = "https://www.twse.com.tw/rwd/zh/fund/TWT38U?response=json&date=" + date_str
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = r.json()
        if data.get("stat") != "OK":
            return None
        rows = []
        for row in data.get("data", []):
            try:
                industry = row[0].strip()
                if not industry or industry == "*":
                    continue
                net = 0
                for col in [4, 3, 2]:
                    try:
                        val = row[col].replace(",", "").replace(" ", "").strip()
                        if val and val != "--":
                            net = int(val)
                            break
                    except Exception:
                        continue
                rows.append({"industry": industry, "net": net})
            except Exception:
                continue
        if not rows:
            return None
        rows.sort(key=lambda x: x["net"], reverse=True)
        return rows
    except Exception:
        return None


def format_institutional_block():
    lines = ["【三大法人買賣超】"]
    flow = fetch_institutional_flow()
    if flow:
        for item in flow:
            arrow = "▲" if item["net"] >= 0 else "▼"
            lines.append(arrow + " " + item["name"] + ": " + fmt_money(item["net"]))
    else:
        lines.append("今日資料尚未更新")
    lines.append("")
    industries = fetch_industry_flow()
    if industries:
        lines.append("資金流入產業 Top5:")
        for item in industries[:5]:
            lines.append("+ " + item["industry"] + " " + fmt_money(item["net"]))
        lines.append("")
        lines.append("資金流出產業 Bottom3:")
        for item in industries[-3:]:
            lines.append("- " + item["industry"] + " " + fmt_money(item["net"]))
    else:
        lines.append("產業資料尚未更新")
    return "\n".join(lines)

def calc_target_prices(close, df):
    ma20 = float(df["Close"].rolling(20).mean().iloc[-1])
    recent_high = float(df["High"].rolling(60).max().iloc[-1])
    entry_low = round(close * 0.995, 2)
    entry_high = round(close * 1.005, 2)
    target = round(min(close * 1.06, recent_high * 0.99), 2)
    stop = round(ma20 * 0.99, 2)
    gain = round((target / close - 1) * 100, 1)
    return entry_low, entry_high, target, stop, gain

def morning_message():
    today_label = datetime.now().strftime("%Y/%m/%d")
    today_key = datetime.now().strftime("%Y%m%d")
    lines = ["早安！波段觀察名單 " + today_label, ""]

    us_hits = []
    for ticker in US_WATCHLIST:
        df = fetch_data(ticker)
        if df is None:
            continue
        ind = calc_indicators(df)
        if is_qualified(ind):
            us_hits.append({"ticker": ticker, "df": df, **ind})

    tw_hits = []
    for ticker in TW_WATCHLIST:
        df = fetch_data(ticker)
        if df is None:
            continue
        ind = calc_indicators(df)
        if is_qualified(ind):
            tw_hits.append({"ticker": ticker, "df": df, **ind})

    lines.append("【美股篩選結果】")
    if not us_hits:
        lines.append("今日無符合條件標的")
    else:
        for h in sorted(us_hits, key=lambda x: x["vol_ratio"], reverse=True):
            entry_low, entry_high, target, stop, gain = calc_target_prices(h["close"], h["df"])
            lines.append("")
            lines.append(h["ticker"])
            lines.append("現價: $" + str(round(h["close"], 2)))
            lines.append("進場區間: $" + str(entry_low) + " - $" + str(entry_high))
            lines.append("目標價: $" + str(target) + " (+" + str(gain) + "%)")
            lines.append("停損價: $" + str(stop) + " (MA20跌破)")
            lines.append("RSI:" + str(int(h["rsi"])) + " 量比:" + str(round(h["vol_ratio"], 1)) + "倍 5日:" + ("+" if h["pct_5d"] >= 0 else "") + str(round(h["pct_5d"], 1)) + "%")

    lines.append("")
    lines.append("【台股篩選結果】")
    if not tw_hits:
        lines.append("今日無符合條件標的")
    else:
        for h in sorted(tw_hits, key=lambda x: x["vol_ratio"], reverse=True):
            entry_low, entry_high, target, stop, gain = calc_target_prices(h["close"], h["df"])
            t = h["ticker"].replace(".TW", "")
            lines.append("")
            lines.append(t)
            lines.append("現價: $" + str(round(h["close"], 2)))
            lines.append("進場區間: $" + str(entry_low) + " - $" + str(entry_high))
            lines.append("目標價: $" + str(target) + " (+" + str(gain) + "%)")
            lines.append("停損價: $" + str(stop) + " (MA20跌破)")
            lines.append("RSI:" + str(int(h["rsi"])) + " 量比:" + str(round(h["vol_ratio"], 1)) + "倍 5日:" + ("+" if h["pct_5d"] >= 0 else "") + str(round(h["pct_5d"], 1)) + "%")

    lines.append("")
    lines.append("篩選條件: 均線多頭排列 | RSI 50-75 | 量比1.3倍+ | 收盤強度80%+")
    lines.append("")
    lines.append(format_institutional_block())

    history = load_history()
    flow = fetch_institutional_flow()
    if flow:
        for item in flow:
            update_streak(history, item["name"], item["net"], today_key)
    for h in us_hits + tw_hits:
        update_streak(history, h["ticker"] + "_上漲", h["pct_5d"], today_key)
    save_history(history)

    alerts = check_alerts(history, today_key)
    if alerts:
        lines.append("")
        lines.append("【連續訊號警示】")
        for a in alerts:
            lines.append("！" + a)

    return "\n".join(lines)

def tw_close_message():
    today = datetime.now().strftime("%Y/%m/%d")
    lines = ["台股收盤摘要 " + today, ""]
    lines.append("【大盤與權值股】")
    for name, stock_id in TW_MARKET:
        q = fetch_tw_quote(stock_id)
        if q is None:
            lines.append(name + ": 休市或無資料")
            continue
        arrow = "▲" if q["pct"] >= 0 else "▼"
        lines.append(name + " " + str(round(q["price"], 2)) + " " + arrow + " " + str(round(q["pct"], 2)) + "%")
    lines.append("")
    lines.append(format_institutional_block())
    return "\n".join(lines)

def us_close_message():
    today = datetime.now().strftime("%Y/%m/%d")
    lines = ["美股收盤摘要 " + today, ""]
    lines.append("【指數與個股】")
    for name, ticker in US_MARKET:
        q = fetch_us_quote(ticker)
        if q is None:
            lines.append(name + ": 休市或無資料")
            continue
        arrow = "▲" if q["pct"] >= 0 else "▼"
        lines.append(name + " " + str(round(q["price"], 2)) + " " + arrow + " " + str(round(q["pct"], 2)) + "%")
    lines.append("")
    vix = fetch_us_quote("^VIX")
    if vix:
        v = vix["price"]
        if v < 15:
            mood = "市場極度樂觀，注意過熱風險"
        elif v < 20:
            mood = "市場情緒平穩"
        elif v < 30:
            mood = "市場出現恐慌，注意波動"
        else:
            mood = "市場極度恐慌，危機模式"
        lines.append("市場情緒: VIX " + str(round(v, 1)) + " → " + mood)
    return "\n".join(lines)

def send_telegram(text):
    url = "https://api.telegram.org/bot" + TELEGRAM_TOKEN + "/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()

if __name__ == "__main__":
    if MODE == "morning":
        msg = morning_message()
    elif MODE == "tw_close":
        msg = tw_close_message()
    elif MODE == "us_close":
        msg = us_close_message()
    else:
        msg = "未知模式"
    print(msg)
    send_telegram(msg)
    print("完成")
