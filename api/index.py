import os
import re
import time
import traceback
import requests
import random
import json
import numpy as np
import pandas as pd
import xml.etree.ElementTree as ET
from flask import Flask, request, jsonify
import yfinance as yf
import plotly.graph_objects as go
import plotly.offline as pyo
from plotly.subplots import make_subplots

app = Flask(__name__)

# ── OpenRouter AI config ─────────────────────────────────────────────────────
OPEN_ROUTER_API_KEY = os.environ.get("OPEN_ROUTER_API_KEY", "")

AI_MODELS = [
    {"id": "deepseek/deepseek-r1",              "key": "deepseek", "label": "DeepSeek R1",   "desc": "Chain-of-thought reasoning",  "color": "#7c3aed", "role": "Technical Analyst"},
    {"id": "meta-llama/llama-3.3-70b-instruct", "key": "llama",    "label": "Llama 3.3 70B", "desc": "Fast & balanced",             "color": "#0ea5e9", "role": "Macro Strategist"},
    {"id": "qwen/qwen3-coder",                  "key": "qwen",     "label": "Qwen3 Coder",   "desc": "Quantitative synthesis",      "color": "#f59e0b", "role": "Quant Synthesizer"},
]
RL_RPM = 20
RL_RPD = 200

# Serverless note: rate-limit state cannot persist across invocations.
# These stubs always report available=True. OpenRouter itself enforces limits.
def rl_check(key):
    return {"rpm_used": 0, "rpm_max": RL_RPM, "rpd_used": 0, "rpd_max": RL_RPD, "available": True}

def rl_record(key):
    pass

def rl_next_rpm_reset(key):
    return 0


# ── YouTube live news ────────────────────────────────────────────────────────
NEWS_CHANNELS = [
    {"id": "cnbctv18",  "handle": "cnbctv18",  "label": "CNBC TV18",       "lang": "EN", "region": "India",  "video_id": "1_Ih0JYmkjI"},
    {"id": "bloomberg", "handle": "Bloomberg", "label": "Bloomberg Global", "lang": "EN", "region": "Global", "video_id": "iEpJwprxDdk"},
    {"id": "yahoofi",   "handle": "yahoofi",   "label": "Yahoo Finance",    "lang": "EN", "region": "Global", "video_id": "KQp-e_XQmDE"},
]
_YT_HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
           "Accept-Language": "en-US,en;q=0.9", "Referer": "https://www.youtube.com/"}


def fetch_live_video_id(handle):
    for ch in NEWS_CHANNELS:
        if ch["handle"] == handle and ch.get("video_id"):
            return ch["video_id"], True
    def _get(u): return requests.get(u, headers=_YT_HDR, timeout=12, allow_redirects=True)
    vid, live = None, False
    try:
        r = _get(f"https://www.youtube.com/@{handle}/live"); text = r.text
        m = re.search(r'[?&]v=([A-Za-z0-9_-]{11})', r.url) or re.search(r'"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"', text)
        if m and ('"isLive":true' in text or '"liveBroadcastContent":"live"' in text):
            vid, live = m.group(1), True
    except Exception: pass
    if not live:
        try:
            r2 = _get(f"https://www.youtube.com/@{handle}/videos")
            ids = list(dict.fromkeys(re.findall(r'"videoId"\s*:\s*"([A-Za-z0-9_-]{11})"', r2.text)))
            if ids: vid, live = ids[0], False
        except Exception: pass
    return vid, live


# ── RSS News Feeds ────────────────────────────────────────────────────────────
RSS_FEEDS = [
    {"id": "reuters",    "label": "Reuters",        "url": "https://feeds.reuters.com/reuters/businessNews"},
    {"id": "bloomberg",  "label": "Bloomberg",      "url": "https://feeds.bloomberg.com/markets/news.rss"},
    {"id": "cnbc",       "label": "CNBC",           "url": "https://www.cnbc.com/id/10001147/device/rss/rss.html"},
    {"id": "ft",         "label": "Financial Times", "url": "https://www.ft.com/rss/home/uk"},
    {"id": "wsj",        "label": "WSJ Markets",    "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"},
    {"id": "moneyctrl",  "label": "MoneyControl",   "url": "https://www.moneycontrol.com/rss/MCtopnews.xml"},
    {"id": "ecdimes",    "label": "Economic Times",  "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"},
    {"id": "seeking",    "label": "Seeking Alpha",  "url": "https://seekingalpha.com/feed.xml"},
]

_RSS_CACHE = {}
_RSS_CACHE_TTL = 300  # 5 minutes

_RSS_HDR = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


def fetch_rss_feed(feed_id):
    feed = next((f for f in RSS_FEEDS if f["id"] == feed_id), None)
    if not feed:
        return []
    now = time.time()
    if feed_id in _RSS_CACHE and now - _RSS_CACHE[feed_id]["ts"] < _RSS_CACHE_TTL:
        return _RSS_CACHE[feed_id]["items"]
    items = []
    try:
        r = requests.get(feed["url"], headers=_RSS_HDR, timeout=10)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        # Handle both RSS and Atom
        entries = root.findall(".//item") or root.findall(".//atom:entry", ns)
        for entry in entries[:20]:
            def gt(tag):
                el = entry.find(tag) or entry.find(f"atom:{tag}", ns)
                return (el.text or "").strip() if el is not None else ""
            title = gt("title")
            link  = gt("link") or (entry.find("atom:link", ns).get("href","") if entry.find("atom:link", ns) is not None else "")
            pub   = gt("pubDate") or gt("published") or gt("updated")
            desc  = gt("description") or gt("summary")
            # Strip HTML from description
            desc = re.sub(r'<[^>]+>', '', desc)[:200].strip()
            if title:
                items.append({"title": title, "link": link, "pub": pub, "desc": desc, "source": feed["label"]})
    except Exception as e:
        pass
    _RSS_CACHE[feed_id] = {"items": items, "ts": now}
    return items


def fetch_all_rss(limit=30):
    all_items = []
    for feed in RSS_FEEDS:
        try:
            items = fetch_rss_feed(feed["id"])
            all_items.extend(items)
        except Exception:
            pass
    # Sort by publication date (best-effort)
    def parse_date(s):
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(s).timestamp()
        except Exception:
            try:
                from datetime import datetime
                for fmt in ["%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%a, %d %b %Y %H:%M:%S %z"]:
                    try:
                        return datetime.strptime(s[:25], fmt[:len(s[:25])]).timestamp()
                    except Exception:
                        pass
            except Exception:
                pass
        return 0
    all_items.sort(key=lambda x: parse_date(x.get("pub", "")), reverse=True)
    return all_items[:limit]


POPULAR_STOCKS = [("AAPL","Apple"),("GOOGL","Google"),("MSFT","Microsoft"),("TSLA","Tesla"),
                  ("AMZN","Amazon"),("NVDA","NVIDIA"),("TCS.NS","TCS"),("RELIANCE.NS","Reliance")]
PERIODS = [("1mo","1 Month"),("3mo","3 Months"),("6mo","6 Months"),("1y","1 Year"),("2y","2 Years"),("5y","5 Years")]
VALID_PERIODS = {p[0] for p in PERIODS}
INDICATORS = [("sma","SMA"),("bb","Bollinger"),("rsi","RSI"),("macd","MACD"),("vol","Volume")]


# ══════════════════════════════════════════════════════════════════════════════
# YAHOO FINANCE SCRAPER (unchanged from original)
# ══════════════════════════════════════════════════════════════════════════════
_CACHE = {"session": None, "crumb": None, "ts": 0}
_CACHE_TTL = 1800
_PERIOD_DAYS = {"1mo":31,"3mo":92,"6mo":183,"1y":366,"2y":731,"5y":1827}
_YF_BASES = ["https://query1.finance.yahoo.com","https://query2.finance.yahoo.com"]
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.6367.207 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]


def _new_session(ua=None):
    s = requests.Session()
    s.headers.update({"User-Agent": ua or random.choice(_UA_POOL),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive", "Upgrade-Insecure-Requests": "1",
        "Sec-CH-UA": '"Chromium";v="124","Google Chrome";v="124","Not-A.Brand";v="99"',
        "Sec-CH-UA-Mobile": "?0", "Sec-CH-UA-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0", "DNT": "1"})
    return s


def _scrape_crumb(session, ticker):
    crumb = None
    for base in _YF_BASES:
        try:
            r = session.get(f"{base}/v1/test/getcrumb", timeout=8, headers={"Referer": "https://finance.yahoo.com/"})
            if r.status_code == 200 and r.text and len(r.text) < 50 and "<" not in r.text:
                return r.text.strip()
        except Exception: pass
    for url in [f"https://finance.yahoo.com/quote/{ticker}", "https://finance.yahoo.com/"]:
        try:
            html = session.get(url, timeout=15, allow_redirects=True).text
            for pat in [r'"crumb"\s*:\s*"([^"]{5,30})"',
                        r'CrumbStore\s*:\s*\{\s*crumb\s*:\s*"([^"]{5,30})"']:
                m = re.search(pat, html)
                if m: crumb = m.group(1).replace("\\u002F", "/"); break
            if crumb: break
        except Exception: continue
    if not crumb:
        for base in _YF_BASES:
            try:
                r = session.get(f"{base}/v1/test/getcrumb", timeout=8, headers={"Referer": "https://finance.yahoo.com/"})
                if r.status_code == 200 and r.text and len(r.text) < 50 and "<" not in r.text:
                    crumb = r.text.strip(); break
            except Exception: pass
    return crumb


def _get_auth(ticker, force=False):
    now = time.time()
    if not force and _CACHE["session"] and _CACHE["crumb"] and (now - _CACHE["ts"]) < _CACHE_TTL:
        return _CACHE["session"], _CACHE["crumb"]
    s = _new_session()
    for u in ["https://fc.yahoo.com", "https://finance.yahoo.com/"]:
        try: s.get(u, timeout=8, allow_redirects=True); break
        except Exception: pass
    c = _scrape_crumb(s, ticker)
    _CACHE.update({"session": s, "crumb": c, "ts": now})
    return s, c


def _parse_v8(j):
    try:
        res = j.get("chart", {}).get("result", [None])[0]
        if not res: return None
        ts = res.get("timestamp", [])
        if not ts: return None
        q = res["indicators"]["quote"][0]
        adj = res["indicators"].get("adjclose", [{}])
        cl = (adj[0].get("adjclose") if adj else None) or q.get("close")
        df = pd.DataFrame({"Open": q.get("open"), "High": q.get("high"),
                           "Low": q.get("low"), "Close": cl, "Volume": q.get("volume")},
                          index=pd.to_datetime(ts, unit="s", utc=True).normalize())
        df.index.name = "Date"
        df = df[df["Close"].notna()]
        return df if not df.empty else None
    except Exception: return None


def _fetch_v8(ticker, period, session, crumb):
    p = {"range": period, "interval": "1d", "includeAdjustedClose": "true", "events": "div,splits"}
    if crumb: p["crumb"] = crumb
    h = {"Referer": "https://finance.yahoo.com/", "Accept": "application/json,*/*",
         "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-site"}
    for base in _YF_BASES:
        try:
            r = session.get(f"{base}/v8/finance/chart/{ticker}", params=p, headers=h, timeout=15)
            if r.status_code == 401: return None
            if r.status_code == 200:
                df = _parse_v8(r.json())
                if df is not None: return df
        except Exception: continue
    return None


def _fetch_v7(ticker, period, session, crumb):
    from io import StringIO
    e, s2 = int(time.time()), int(time.time()) - _PERIOD_DAYS.get(period, 183) * 86400
    p = {"period1": s2, "period2": e, "interval": "1d", "events": "history", "includeAdjustedClose": "true"}
    if crumb: p["crumb"] = crumb
    h = {"Referer": "https://finance.yahoo.com/", "Accept": "text/csv,*/*",
         "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-site"}
    for base in _YF_BASES:
        try:
            r = session.get(f"{base}/v7/finance/download/{ticker}", params=p, headers=h, timeout=15)
            if r.status_code != 200 or "Date" not in r.text: continue
            df = pd.read_csv(StringIO(r.text))
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
            df = df.dropna(subset=["Date"]).set_index("Date")
            df["Close"] = pd.to_numeric(df.get("Adj Close", df.get("Close", pd.Series())), errors="coerce")
            for col in ["Open","High","Low","Volume"]:
                if col in df.columns: df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df[["Open","High","Low","Close","Volume"]].dropna(subset=["Close"])
            if not df.empty: return df
        except Exception: continue
    return None


def _fetch_lib(ticker, period, session):
    import io, contextlib
    buf = io.StringIO()
    for fn in [
        lambda: _flat(yf.Ticker(ticker, session=session).history(period=period, interval="1d", auto_adjust=True, actions=False, timeout=15)),
        lambda: _flat(yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True, actions=False, timeout=15, session=session)),
    ]:
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                df = fn()
            if df is not None and not df.empty: return df
        except Exception: pass
    return None


def fetch_yfinance_data(ticker, period):
    last_err = None
    for attempt in range(2):
        try:
            session, crumb = _get_auth(ticker, force=(attempt == 1))
        except Exception as e: last_err = str(e); continue
        for fn in [lambda: _fetch_v8(ticker, period, session, crumb),
                   lambda: _fetch_v7(ticker, period, session, crumb)]:
            try:
                df = fn()
                if df is not None and not df.empty: return df, None
            except Exception as e: last_err = str(e)
        _CACHE.update({"session": None, "crumb": None}); time.sleep(0.4)
    try:
        session, _ = _get_auth(ticker, force=True)
        df = _fetch_lib(ticker, period, session)
        if df is not None and not df.empty: return df, None
    except Exception as e: last_err = str(e)
    hint = " (use .NS for NSE, e.g. TCS.NS)" if "." not in ticker else ""
    return None, f"Could not fetch '{ticker}'{hint}. {last_err or ''}"


def _flat(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def _get_name(ticker):
    try:
        s, _ = _get_auth(ticker)
        t = yf.Ticker(ticker, session=s)
        return (t.fast_info.get("longName") or t.info.get("shortName") or "").strip() or ticker
    except Exception: return ticker


# ══════════════════════════════════════════════════════════════════════════════
# TECHNICAL INDICATORS
# ══════════════════════════════════════════════════════════════════════════════
def calc_sma(c, w):  return c.rolling(w).mean()
def calc_ema(c, w):  return c.ewm(span=w, adjust=False).mean()
def calc_bb(c, w=20, n=2):
    sma = calc_sma(c, w); std = c.rolling(w).std()
    return sma + n*std, sma, sma - n*std
def calc_rsi(c, w=14):
    d = c.diff(); g = d.clip(lower=0); l = -d.clip(upper=0)
    ag = g.ewm(com=w-1, min_periods=w).mean(); al = l.ewm(com=w-1, min_periods=w).mean()
    return 100 - 100/(1 + ag/al.replace(0, np.nan))
def calc_macd(c, f=12, s=26, sg=9):
    ml = calc_ema(c,f) - calc_ema(c,s); sl = ml.ewm(span=sg, adjust=False).mean()
    return ml, sl, ml-sl
def calc_atr(h, l, c, w=14):
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    return tr.ewm(com=w-1, min_periods=w).mean()


# ══════════════════════════════════════════════════════════════════════════════
# AI ANALYSIS ENGINE
# ══════════════════════════════════════════════════════════════════════════════
def _sf(v, d=4):
    try: x = float(v); return None if np.isnan(x) else round(x, d)
    except: return None


def build_analysis_payload(ticker, period, name, df):
    c = df["Close"].squeeze().dropna()
    h = df["High"].squeeze(); lo = df["Low"].squeeze()
    op = df["Open"].squeeze()
    vol = df["Volume"].squeeze() if "Volume" in df.columns else None
    n = len(c)
    cur = _sf(c.iloc[-1]); prev = _sf(c.iloc[-2]) if n > 1 else cur
    currency = "INR" if ticker.upper().endswith((".NS",".BO")) else "USD"

    hi52 = _sf(c.tail(252).max()); lo52 = _sf(c.tail(252).min())
    macd_d = {}
    if n >= 27:
        ml, sl, hl = calc_macd(c)
        macd_d = {"macd": _sf(ml.iloc[-1]), "signal": _sf(sl.iloc[-1]),
                  "histogram": _sf(hl.iloc[-1]), "hist_prev": _sf(hl.iloc[-2]) if n > 27 else None,
                  "crossover": "bullish" if (hl.iloc[-1] > 0 and hl.iloc[-2] < 0) else
                               "bearish" if (hl.iloc[-1] < 0 and hl.iloc[-2] > 0) else "none"}
    bb_d = {}
    if n >= 20:
        bbu, bbm, bbl = calc_bb(c)
        bb_d = {"upper": _sf(bbu.iloc[-1]), "mid": _sf(bbm.iloc[-1]), "lower": _sf(bbl.iloc[-1]),
                "percent_b": _sf((cur - _sf(bbl.iloc[-1])) / (_sf(bbu.iloc[-1]) - _sf(bbl.iloc[-1]))) if _sf(bbu.iloc[-1]) != _sf(bbl.iloc[-1]) else None,
                "bandwidth": _sf(((bbu.iloc[-1]-bbl.iloc[-1])/bbm.iloc[-1])*100)}
    sma20 = _sf(calc_sma(c,20).iloc[-1]) if n>=20 else None
    sma50 = _sf(calc_sma(c,50).iloc[-1]) if n>=50 else None
    sma200= _sf(calc_sma(c,200).iloc[-1]) if n>=200 else None
    rsi_v = _sf(calc_rsi(c).iloc[-1]) if n>=15 else None
    atr_v = _sf(calc_atr(h,lo,c).iloc[-1]) if n>=15 else None
    vol_d = {}
    if vol is not None:
        avg20 = _sf(vol.tail(20).mean()); cv = _sf(vol.iloc[-1])
        vol_d = {"latest": cv, "avg_20d": avg20, "ratio_vs_avg": _sf(cv/avg20) if avg20 else None}
    trend = []
    if sma20 and cur: trend.append("above_sma20" if cur>sma20 else "below_sma20")
    if sma50 and cur: trend.append("above_sma50" if cur>sma50 else "below_sma50")
    if sma200 and cur: trend.append("above_sma200" if cur>sma200 else "below_sma200")
    if sma20 and sma50: trend.append("golden_cross" if sma20>sma50 else "death_cross")

    recent = df.tail(30).copy(); recent.index = recent.index.astype(str)
    ohlcv = [{"date": d[:10], "open": _sf(r.get("Open")), "high": _sf(r.get("High")),
               "low": _sf(r.get("Low")), "close": _sf(r.get("Close")),
               "volume": int(r["Volume"]) if "Volume" in r and pd.notna(r["Volume"]) else None}
              for d, r in recent.iterrows()]
    return {
        "ticker": ticker, "name": name, "currency": currency, "period": period, "bars": n,
        "price": {"current": cur, "prev": prev, "change": _sf(cur-prev) if cur and prev else None,
                  "change_pct": _sf(((cur-prev)/prev)*100) if cur and prev else None,
                  "52w_high": hi52, "52w_low": lo52,
                  "pct_from_52h": _sf(((cur-hi52)/hi52)*100) if cur and hi52 else None},
        "ma": {"sma20": sma20, "sma50": sma50, "sma200": sma200,
               "ema9": _sf(calc_ema(c,9).iloc[-1]), "ema21": _sf(calc_ema(c,21).iloc[-1])},
        "bb": bb_d, "rsi": {"value": rsi_v, "last5": [_sf(v) for v in calc_rsi(c).tail(5).tolist()] if n>=20 else []},
        "macd": macd_d, "atr": {"value": atr_v, "pct": _sf((atr_v/cur)*100) if atr_v and cur else None},
        "volume": vol_d, "trend": trend, "ohlcv": ohlcv,
    }


def build_technical_prompt(payload):
    """Prompt for DeepSeek — pure technical analysis"""
    p = payload; px = p["price"]; ma = p["ma"]; bb = p.get("bb",{}); rsi = p.get("rsi",{})
    macd = p.get("macd",{}); atr = p.get("atr",{}); vol = p.get("volume",{})
    f = lambda v,d=2: f"{v:.{d}f}" if v is not None else "N/A"
    up = lambda v: ("↑ Price above" if px["current"] and v and px["current"]>v else "↓ Price below") if v else "N/A"
    lines = [
        f"You are DeepSeek R1 acting as an elite Technical Analyst. Your task is STEP 1 of 3 in a multi-AI orchestration pipeline.",
        f"Analyse ONLY the technical indicators for **{p['name']} ({p['ticker']})** over the {p['period']} period.",
        f"Your output will be passed to a Macro Strategist and then a Quant Synthesizer to make a final market prediction.",
        "",
        "## PRICE SNAPSHOT",
        f"- Current: {p['currency']} {f(px['current'])}  |  Prev Close: {p['currency']} {f(px['prev'])}",
        f"- Change: {f(px['change'])} ({f(px['change_pct'])}%)",
        f"- 52W High: {p['currency']} {f(px['52w_high'])}  |  52W Low: {p['currency']} {f(px['52w_low'])}",
        f"- Distance from 52W High: {f(px['pct_from_52h'])}%",
        "",
        "## MOVING AVERAGES",
        f"- SMA 20: {f(ma['sma20'])} ({up(ma['sma20'])} SMA20)",
        f"- SMA 50: {f(ma['sma50'])} ({up(ma['sma50'])} SMA50)",
        f"- SMA 200: {f(ma['sma200'])} ({up(ma['sma200'])} SMA200)",
        f"- EMA 9: {f(ma['ema9'])}  |  EMA 21: {f(ma['ema21'])}",
        f"- Trend signals: {', '.join(p['trend']) or 'none'}",
        "",
        "## BOLLINGER BANDS (20,2σ)",
        f"- Upper: {f(bb.get('upper'))}  Mid: {f(bb.get('mid'))}  Lower: {f(bb.get('lower'))}",
        f"- %B: {f(bb.get('percent_b'),3)}  |  Bandwidth: {f(bb.get('bandwidth'))}%",
        "",
        "## RSI (14)",
        f"- Current: {f(rsi.get('value'))}  Zone: {'OVERBOUGHT' if rsi.get('value') and rsi['value']>70 else 'OVERSOLD' if rsi.get('value') and rsi['value']<30 else 'NEUTRAL'}",
        f"- Last 5: {', '.join(f(v) for v in rsi.get('last5',[]))}",
        "",
        "## MACD (12,26,9)",
        f"- MACD: {f(macd.get('macd'))}  Signal: {f(macd.get('signal'))}  Histogram: {f(macd.get('histogram'))}",
        f"- Crossover: {(macd.get('crossover') or 'none').upper()}",
        "",
        "## VOLATILITY",
        f"- ATR(14): {p['currency']} {f(atr.get('value'))} ({f(atr.get('pct'))}% of price)",
        f"- Latest Vol Ratio: {f(vol.get('ratio_vs_avg'))}x vs 20D avg",
        "",
        "## RECENT OHLCV (last 30 trading days)",
        "date,open,high,low,close,volume",
    ] + [f"{r['date']},{r['open']},{r['high']},{r['low']},{r['close']},{r['volume']}" for r in p["ohlcv"]] + [
        "",
        "---",
        "Respond with a single valid JSON object. No markdown. No extra text:",
        '{"technical_verdict":"BULLISH|BEARISH|NEUTRAL",',
        '"key_levels":{"support_1":0.0,"support_2":0.0,"resistance_1":0.0,"resistance_2":0.0},',
        '"indicator_signals":{"rsi":"string","macd":"string","bollinger":"string","moving_averages":"string","volume":"string"},',
        '"pattern_detected":"string (describe any chart pattern visible)",',
        '"technical_analysis":"Detailed 3-paragraph technical breakdown. Be specific about price levels, crossovers, divergences.",',
        '"technical_bias":"SHORT_TERM direction with reasoning — 1-2 sentences.",',
        '"confidence_score":75}',
    ]
    return "\n".join(lines)


def build_macro_prompt(payload, technical_result, news_headlines):
    """Prompt for Llama — macro + news context, receives technical findings"""
    p = payload; px = p["price"]
    f = lambda v,d=2: f"{v:.{d}f}" if v is not None else "N/A"
    headlines_text = "\n".join(f"- {h['source']}: {h['title']}" for h in news_headlines[:15]) if news_headlines else "No headlines available."
    lines = [
        f"You are Llama 3.3 acting as a Macro Strategist. Your task is STEP 2 of 3 in a multi-AI orchestration pipeline.",
        f"You are analysing **{p['name']} ({p['ticker']})** — {p['currency']} {f(px['current'])}",
        "",
        "## STEP 1 — TECHNICAL FINDINGS (from DeepSeek R1)",
        f"Technical Verdict: {technical_result.get('technical_verdict','N/A')}",
        f"Confidence Score: {technical_result.get('confidence_score','N/A')}",
        f"Technical Bias: {technical_result.get('technical_bias','N/A')}",
        f"Technical Analysis: {technical_result.get('technical_analysis','N/A')}",
        f"Pattern Detected: {technical_result.get('pattern_detected','N/A')}",
        "",
        "## LIVE NEWS HEADLINES (from RSS feeds — use these for macro context)",
        headlines_text,
        "",
        "---",
        "Your job: Provide the macro, sector, and news context that will help the Quant Synthesizer make a final prediction.",
        "Consider: Fed policy, sector rotation, earnings calendar, geopolitical events, institutional flows, sentiment.",
        "",
        "Respond with a single valid JSON object. No markdown. No extra text:",
        '{"macro_verdict":"BULLISH|BEARISH|NEUTRAL",',
        '"relevant_headlines":["headline 1","headline 2","headline 3"],',
        '"macro_environment":"2-paragraph macro backdrop — interest rates, sector health, institutional sentiment",',
        '"news_impact":"How the current news specifically affects this stock/sector.",',
        '"catalyst_ahead":"Any upcoming catalyst (earnings, FOMC, product launch, index rebalance) to watch.",',
        '"macro_risk":"Primary macro risk that could reverse the technical setup.",',
        '"macro_confidence_score":70}',
    ]
    return "\n".join(lines)


def build_synthesis_prompt(payload, technical_result, macro_result):
    """Prompt for Qwen — final synthesis, receives both previous analyses"""
    p = payload; px = p["price"]
    f = lambda v,d=2: f"{v:.{d}f}" if v is not None else "N/A"
    currency = p["currency"]
    cur = px["current"]
    lines = [
        f"You are Qwen3 acting as the Quant Synthesizer. Your task is STEP 3 of 3 in a multi-AI orchestration pipeline.",
        f"You have received analyses from two specialists. Synthesize them into a single authoritative market prediction.",
        f"Stock: **{p['name']} ({p['ticker']})** — Current Price: {currency} {f(cur)}",
        "",
        "## STEP 1 — TECHNICAL ANALYSIS (DeepSeek R1)",
        f"Verdict: {technical_result.get('technical_verdict','N/A')} | Confidence: {technical_result.get('confidence_score','N/A')}",
        f"Bias: {technical_result.get('technical_bias','N/A')}",
        f"Key Levels — Support: {technical_result.get('key_levels',{}).get('support_1','N/A')}/{technical_result.get('key_levels',{}).get('support_2','N/A')} | Resistance: {technical_result.get('key_levels',{}).get('resistance_1','N/A')}/{technical_result.get('key_levels',{}).get('resistance_2','N/A')}",
        f"Indicators: RSI={technical_result.get('indicator_signals',{}).get('rsi','N/A')}, MACD={technical_result.get('indicator_signals',{}).get('macd','N/A')}, BB={technical_result.get('indicator_signals',{}).get('bollinger','N/A')}",
        "",
        "## STEP 2 — MACRO ANALYSIS (Llama 3.3)",
        f"Macro Verdict: {macro_result.get('macro_verdict','N/A')} | Confidence: {macro_result.get('macro_confidence_score','N/A')}",
        f"Macro Environment: {macro_result.get('macro_environment','N/A')}",
        f"News Impact: {macro_result.get('news_impact','N/A')}",
        f"Catalyst Ahead: {macro_result.get('catalyst_ahead','N/A')}",
        f"Macro Risk: {macro_result.get('macro_risk','N/A')}",
        "",
        "---",
        "Now synthesize EVERYTHING into a final prediction. Be specific about price targets.",
        f"Current price is {currency} {f(cur)}. Give realistic targets based on ATR and key levels.",
        "",
        "Respond with a single valid JSON object. No markdown. No extra text:",
        '{"final_verdict":"BUY|SELL|HOLD",',
        '"conviction":"Low|Medium|High|Very High",',
        '"time_horizon":"Short (1-5 days)|Mid (1-4 weeks)|Long (1-3 months)",',
        '"price_targets":{"entry":0.0,"stop_loss":0.0,"target_1":0.0,"target_2":0.0,"target_3":0.0},',
        '"risk_reward_ratio":0.0,',
        '"prediction_summary":"One powerful sentence — the core thesis and what the market is about to do.",',
        '"agreement_score":"0-100 — how much do technical and macro agree? 100=perfect alignment",',
        '"action_plan":"Step-by-step concrete action for a trader right now. Entry, sizing, exits.",',
        '"key_risk":"The single most important risk that could invalidate this call.",',
        '"orchestration_insight":"What did the 3-AI pipeline reveal that a single AI would have missed?"}',
    ]
    return "\n".join(lines)


def call_openrouter(model_id, prompt):
    if not OPEN_ROUTER_API_KEY:
        raise ValueError("OPEN_ROUTER_API_KEY environment variable is not set.")
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPEN_ROUTER_API_KEY}",
                 "Content-Type": "application/json",
                 "HTTP-Referer": "https://starfish.finance",
                 "X-Title": "Starfish Stock Analyzer"},
        json={"model": model_id, "messages": [{"role": "user", "content": prompt}],
              "temperature": 0.15, "max_tokens": 2048},
        timeout=90,
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"].strip()
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    m = re.search(r'\{.*\}', content, re.DOTALL)
    if m: content = m.group(0)
    return json.loads(content)


# ══════════════════════════════════════════════════════════════════════════════
# CHART BUILDER (unchanged)
# ══════════════════════════════════════════════════════════════════════════════
_C = {"bg":"rgba(0,0,0,0)","paper":"rgba(0,0,0,0)","grid":"rgba(255,255,255,0.06)","axis":"#555",
      "text":"#888","white":"#fff","green":"#26a69a","red":"#ef5350",
      "sma20":"#FFD700","sma50":"#FF8C00","sma200":"#00BFFF",
      "bb_u":"rgba(120,180,255,0.7)","bb_l":"rgba(120,180,255,0.7)","bb_f":"rgba(120,180,255,0.06)",
      "rsi":"#a78bfa","rsi_ob":"rgba(239,83,80,0.25)","rsi_os":"rgba(38,166,154,0.25)",
      "macd":"#60a5fa","sig":"#f97316","hp":"rgba(38,166,154,0.8)","hn":"rgba(239,83,80,0.8)",
      "vu":"rgba(38,166,154,0.5)","vd":"rgba(239,83,80,0.5)"}


def build_chart(ticker, period, chart_type, indicators):
    data, err = fetch_yfinance_data(ticker, period)
    if err: return None, f"Data error: {err}"
    if data is None or data.empty: return None, f"No data for '{ticker}'. Use .NS for NSE stocks."
    missing = {"Open","High","Low","Close"} - set(data.columns)
    if missing: return None, f"Missing: {missing}"
    data = data.dropna(subset=["Close"])
    if len(data) < 5: return None, "Not enough data points."

    cl = data["Close"].squeeze(); hi = data["High"].squeeze()
    lo = data["Low"].squeeze(); op = data["Open"].squeeze()
    vol = data["Volume"].squeeze() if "Volume" in data.columns else None
    dates = data.index; name = _get_name(ticker)
    currency = "INR" if ticker.upper().endswith((".NS",".BO")) else "USD"

    sv = "vol" in indicators and vol is not None
    sr = "rsi" in indicators; sm = "macd" in indicators
    rows = 1 + int(sv) + int(sr) + int(sm)
    rh = {1:[1.0],2:[0.65,0.35],3:[0.55,0.22,0.23],4:[0.50,0.17,0.17,0.16]}.get(rows,[0.5,0.17,0.17,0.16])
    titles = [f"{name} ({ticker.upper()})"]
    if sv: titles.append("Volume")
    if sr: titles.append("RSI (14)")
    if sm: titles.append("MACD (12, 26, 9)")
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True,
                        vertical_spacing=0.03, row_heights=rh, subplot_titles=titles)
    rv = 2 if sv else None; rr = (2+int(sv)) if sr else None; rm = (2+int(sv)+int(sr)) if sm else None

    if chart_type == "candlestick":
        fig.add_trace(go.Candlestick(x=dates,open=op,high=hi,low=lo,close=cl,name="Price",
            increasing_line_color=_C["green"],increasing_fillcolor="rgba(38,166,154,.18)",
            decreasing_line_color=_C["red"],decreasing_fillcolor="rgba(239,83,80,.18)",
            line=dict(width=1)), row=1,col=1)
    else:
        fig.add_trace(go.Scatter(x=dates,y=cl,mode="lines",name="Price",
            line=dict(color=_C["white"],width=2),fill="tozeroy",fillcolor="rgba(255,255,255,.04)"),row=1,col=1)

    if "sma" in indicators:
        for w,color,lbl in [(20,_C["sma20"],"SMA 20"),(50,_C["sma50"],"SMA 50"),(200,_C["sma200"],"SMA 200")]:
            if len(cl) >= w:
                fig.add_trace(go.Scatter(x=dates,y=calc_sma(cl,w),mode="lines",name=lbl,
                    line=dict(color=color,width=1.2),opacity=0.85),row=1,col=1)
    if "bb" in indicators and len(cl) >= 20:
        bbu,bbm,bbl = calc_bb(cl)
        fig.add_trace(go.Scatter(x=dates,y=bbu,mode="lines",name="BB Upper",
            line=dict(color=_C["bb_u"],width=1,dash="dot")),row=1,col=1)
        fig.add_trace(go.Scatter(x=dates,y=bbl,mode="lines",name="BB Lower",
            line=dict(color=_C["bb_l"],width=1,dash="dot"),
            fill="tonexty",fillcolor=_C["bb_f"]),row=1,col=1)
    if sv and vol is not None:
        colors = [_C["vu"] if c>=o else _C["vd"] for c,o in zip(cl,op)]
        fig.add_trace(go.Bar(x=dates,y=vol,name="Volume",marker_color=colors,showlegend=False),row=rv,col=1)
    if sr and len(cl) >= 15:
        rv2 = calc_rsi(cl)
        fig.add_trace(go.Scatter(x=dates,y=rv2,mode="lines",name="RSI",
            line=dict(color=_C["rsi"],width=1.5),showlegend=False),row=rr,col=1)
        fig.add_hrect(y0=70,y1=100,row=rr,col=1,fillcolor=_C["rsi_ob"],line_width=0,layer="below")
        fig.add_hrect(y0=0,y1=30,row=rr,col=1,fillcolor=_C["rsi_os"],line_width=0,layer="below")
        for lvl,c in [(70,"rgba(239,83,80,.5)"),(30,"rgba(38,166,154,.5)"),(50,"rgba(255,255,255,.15)")]:
            fig.add_hline(y=lvl,row=rr,col=1,line=dict(color=c,width=0.8,dash="dash"))
    if sm and len(cl) >= 27:
        ml,sl,hl = calc_macd(cl)
        hc = [_C["hp"] if v>=0 else _C["hn"] for v in hl.fillna(0)]
        fig.add_trace(go.Bar(x=dates,y=hl,name="MACD Hist",marker_color=hc,showlegend=False),row=rm,col=1)
        fig.add_trace(go.Scatter(x=dates,y=ml,mode="lines",name="MACD",
            line=dict(color=_C["macd"],width=1.5),showlegend=False),row=rm,col=1)
        fig.add_trace(go.Scatter(x=dates,y=sl,mode="lines",name="Signal",
            line=dict(color=_C["sig"],width=1.5),showlegend=False),row=rm,col=1)
        fig.add_hline(y=0,row=rm,col=1,line=dict(color="rgba(255,255,255,.2)",width=0.8,dash="dash"))

    ax = dict(gridcolor=_C["grid"],color=_C["axis"],showline=False,zeroline=False,tickfont=dict(size=9,color=_C["text"]))
    fig.update_layout(
        height=420+120*(rows-1), plot_bgcolor=_C["bg"], paper_bgcolor=_C["paper"],
        font=dict(color=_C["text"],family="'DM Sans',sans-serif",size=11),
        legend=dict(orientation="h",yanchor="bottom",y=1.01,xanchor="left",x=0,
                    bgcolor="rgba(0,0,0,0)",font=dict(size=10,color=_C["text"])),
        hovermode="x unified", margin=dict(l=55,r=20,t=55,b=30),
        hoverlabel=dict(bgcolor="rgba(12,12,12,.95)",bordercolor="rgba(255,255,255,.12)",font=dict(color="#fff")),
        xaxis_rangeslider_visible=False, dragmode="pan",
    )
    for i in range(1, rows+1):
        fig.update_layout(**{f"xaxis{'' if i==1 else i}": {**ax,"rangeslider":{"visible":False}}})
        fig.update_layout(**{f"yaxis{'' if i==1 else i}": {**ax}})
    if sr: fig.update_layout(**{f"yaxis{'' if rr==1 else rr}": {**ax,"range":[0,100]}})
    for ann in fig.layout.annotations: ann.font.color="#555"; ann.font.size=10
    return pyo.plot(fig,output_type="div",include_plotlyjs=False), None


# ══════════════════════════════════════════════════════════════════════════════
# HTML RENDERER
# ══════════════════════════════════════════════════════════════════════════════
DEFAULT_INDICATORS = {"sma","vol"}


def render_page(ticker, period, chart_type, active_indicators, graph_html, error):
    chips = "".join(
        f'<span class="{"chip active" if s==ticker else "chip"}" onclick="setTicker(\'{s}\')">{s}</span>\n'
        for s,_ in POPULAR_STOCKS)
    popts = "".join(f'<option value="{v}" {"selected" if v==period else ""}>{lbl}</option>\n' for v,lbl in PERIODS)
    ct_c  = "selected" if chart_type=="candlestick" else ""
    ct_l  = "selected" if chart_type=="line" else ""
    ichips= "".join(
        f'<span class="{"ind-chip active" if k in active_indicators else "ind-chip"}" data-ind="{k}" onclick="toggleInd(this)">{lbl}</span>\n'
        for k,lbl in INDICATORS)
    content = (f'<div class="error-box">{error}</div>' if error else
               graph_html if graph_html else '<div class="empty-state">Enter a ticker above.</div>')
    ntabs = "".join(
        f'<button class="{"news-tab active" if i==0 else "news-tab"}" data-handle="{ch["handle"]}">'
        f'{ch["label"]} <span class="news-tag">{ch["region"]}</span></button>\n'
        for i,ch in enumerate(NEWS_CHANNELS))
    rss_tabs = "".join(
        f'<button class="{"rss-tab active" if i==0 else "rss-tab"}" data-feed="{f["id"]}">{f["label"]}</button>\n'
        for i,f in enumerate(RSS_FEEDS))

    # Build AI orchestration pipeline display
    pipeline_steps = ""
    for i, m in enumerate(AI_MODELS):
        arrow = '<div class="pipe-arrow">↓</div>' if i < len(AI_MODELS)-1 else ""
        pipeline_steps += f"""
<div class="pipe-step" id="pipe-{m['key']}">
  <div class="pipe-step-hdr">
    <span class="pipe-dot" style="background:{m['color']}"></span>
    <span class="pipe-model">{m['label']}</span>
    <span class="pipe-role">{m['role']}</span>
    <span class="pipe-status" id="pipe-status-{m['key']}">waiting</span>
  </div>
  <div class="pipe-body" id="pipe-body-{m['key']}"></div>
</div>
{arrow}"""

    ai_js = json.dumps(list(active_indicators))
    models_js = json.dumps([{"id":m["id"],"key":m["key"],"label":m["label"],"color":m["color"],"role":m["role"]} for m in AI_MODELS])
    fh = NEWS_CHANNELS[0]["handle"]
    first_rss = RSS_FEEDS[0]["id"]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>STARFISH — AI Market Oracle</title>
  <link rel="preconnect" href="https://fonts.googleapis.com"/>
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600&family=DM+Mono:wght@400;500&family=Syne:wght@700;800&display=swap" rel="stylesheet"/>
  <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
  <style>
    *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
    :root{{
      --bg:#060606;--sur:rgba(255,255,255,.04);--bdr:rgba(255,255,255,.09);--bds:rgba(255,255,255,.05);
      --tx:#f0f0f0;--txm:#666;--txd:#3a3a3a;--acc:#fff;--acm:rgba(255,255,255,.1);
      --blur:blur(20px);--r:16px;--rs:9px;
      --c1:#7c3aed;--c2:#0ea5e9;--c3:#f59e0b;
    }}
    body{{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--tx);min-height:100vh;-webkit-font-smoothing:antialiased;overflow-x:hidden}}
    body::before{{content:'';position:fixed;inset:0;pointer-events:none;z-index:0;
      background:
        radial-gradient(ellipse 90% 55% at 15% 5%,rgba(124,58,237,.035) 0%,transparent 55%),
        radial-gradient(ellipse 55% 45% at 85% 85%,rgba(14,165,233,.025) 0%,transparent 50%),
        radial-gradient(ellipse 60% 40% at 50% 50%,rgba(245,158,11,.01) 0%,transparent 60%)
    }}
    header{{position:sticky;top:0;z-index:100;height:58px;display:flex;align-items:center;
            justify-content:space-between;padding:0 28px;background:rgba(6,6,6,.8);
            backdrop-filter:var(--blur);border-bottom:1px solid var(--bds)}}
    .logo{{display:flex;align-items:center;gap:10px;font-family:'Syne',sans-serif;font-size:1rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--acc)}}
    .logo-pip{{width:7px;height:7px;border-radius:50%;background:var(--acc);animation:blink 2.8s ease-in-out infinite}}
    @keyframes blink{{0%,100%{{opacity:1;transform:scale(1)}}50%{{opacity:.2;transform:scale(.65)}}}}
    .subtitle{{font-size:.7rem;color:var(--txd);letter-spacing:.06em;text-transform:uppercase;font-family:'DM Mono',monospace}}
    main{{position:relative;z-index:1;max-width:1200px;margin:0 auto;padding:30px 20px 64px}}
    .glass{{background:var(--sur);backdrop-filter:var(--blur);border:1px solid var(--bdr);border-radius:var(--r)}}
    .panel{{padding:26px 30px;margin-bottom:18px}}
    .panel-label{{font-size:.6rem;font-weight:700;letter-spacing:.2em;text-transform:uppercase;color:var(--txd);margin-bottom:20px;font-family:'DM Mono',monospace}}
    form{{display:grid;grid-template-columns:1.5fr 1fr 1fr auto;gap:14px;align-items:end}}
    .fg label{{display:block;font-size:.68rem;font-weight:500;letter-spacing:.06em;color:var(--txm);margin-bottom:8px;text-transform:uppercase}}
    input,select{{width:100%;background:rgba(255,255,255,.035);border:1px solid var(--bdr);border-radius:var(--rs);color:var(--tx);padding:10px 14px;font-size:.875rem;font-family:inherit;outline:none;transition:border-color .2s,background .2s,box-shadow .2s;appearance:none;-webkit-appearance:none}}
    input::placeholder{{color:var(--txd)}}
    input:focus,select:focus{{border-color:rgba(255,255,255,.28);background:rgba(255,255,255,.065);box-shadow:0 0 0 3px rgba(255,255,255,.05)}}
    select{{cursor:pointer;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'%3E%3Cpath fill='%23555' d='M5 6L0 0z'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 13px center;padding-right:34px}}
    select option{{background:#111;color:#f0f0f0}}
    .btn{{background:var(--acc);color:#000;border:none;border-radius:var(--rs);padding:10px 26px;font-size:.78rem;font-weight:700;font-family:inherit;cursor:pointer;white-space:nowrap;letter-spacing:.1em;text-transform:uppercase;transition:opacity .18s,transform .13s;height:42px}}
    .btn:hover{{opacity:.85}}.btn:active{{transform:scale(.96)}}
    .chips{{display:flex;flex-wrap:wrap;gap:7px;margin-top:22px;padding-top:20px;border-top:1px solid var(--bds)}}
    .chip{{background:transparent;border:1px solid var(--bdr);border-radius:100px;padding:5px 15px;font-size:.7rem;font-family:'DM Mono',monospace;cursor:pointer;color:var(--txm);letter-spacing:.05em;transition:all .16s;user-select:none}}
    .chip:hover{{border-color:rgba(255,255,255,.3);color:var(--tx);background:var(--acm)}}
    .chip.active{{background:var(--acc);border-color:var(--acc);color:#000;font-weight:600}}
    .ind-row{{display:flex;flex-wrap:wrap;gap:7px;margin-top:16px;padding-top:16px;border-top:1px solid var(--bds);align-items:center}}
    .ind-label{{font-size:.6rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--txd);margin-right:4px;font-family:'DM Mono',monospace}}
    .ind-chip{{background:transparent;border:1px solid var(--bdr);border-radius:100px;padding:4px 14px;font-size:.7rem;font-family:'DM Mono',monospace;cursor:pointer;color:var(--txm);letter-spacing:.05em;transition:all .16s;user-select:none}}
    .ind-chip:hover{{border-color:rgba(255,255,255,.3);color:var(--tx);background:var(--acm)}}
    .ind-chip.active{{background:rgba(255,255,255,.12);border-color:rgba(255,255,255,.35);color:var(--tx);font-weight:600}}
    .chart-card{{padding:20px 16px 12px;min-height:460px;display:flex;align-items:flex-start;justify-content:center;overflow:hidden}}
    .chart-card>div{{width:100%}}
    .error-box{{border:1px solid rgba(255,255,255,.1);border-left:3px solid rgba(255,255,255,.45);border-radius:var(--rs);padding:16px 20px;color:#999;font-size:.875rem;background:rgba(255,255,255,.025);width:100%;line-height:1.6}}
    .empty-state{{color:var(--txd);font-size:.85rem;text-align:center;letter-spacing:.03em}}

    /* ══ AI ORCHESTRATION PANEL ══ */
    .orch-panel{{padding:28px 30px;margin-bottom:18px}}
    .orch-header{{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px;flex-wrap:wrap;gap:12px}}
    .orch-title-group{{display:flex;flex-direction:column;gap:4px}}
    .orch-title{{font-family:'Syne',sans-serif;font-size:1rem;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--acc)}}
    .orch-subtitle{{font-size:.67rem;color:var(--txm);letter-spacing:.04em}}
    .orch-controls{{display:flex;align-items:center;gap:12px}}
    .btn-orch{{background:linear-gradient(135deg,rgba(124,58,237,.2),rgba(14,165,233,.15));border:1px solid rgba(124,58,237,.4);border-radius:var(--rs);color:var(--tx);padding:10px 24px;font-size:.75rem;font-weight:700;font-family:'DM Mono',monospace;cursor:pointer;letter-spacing:.1em;text-transform:uppercase;transition:all .2s}}
    .btn-orch:hover{{background:linear-gradient(135deg,rgba(124,58,237,.35),rgba(14,165,233,.28));border-color:rgba(124,58,237,.65)}}
    .btn-orch:active{{transform:scale(.96)}}.btn-orch:disabled{{opacity:.35;cursor:not-allowed;transform:none}}
    .orch-status-lbl{{font-size:.65rem;font-family:'DM Mono',monospace;color:var(--txm)}}

    /* Pipeline steps */
    .pipeline{{display:flex;flex-direction:column;gap:0;margin-bottom:20px}}
    .pipe-step{{border:1px solid var(--bdr);border-radius:12px;overflow:hidden;transition:border-color .3s,box-shadow .3s}}
    .pipe-step.active{{border-color:rgba(255,255,255,.2);box-shadow:0 0 20px rgba(255,255,255,.04)}}
    .pipe-step.done{{border-color:rgba(255,255,255,.12)}}
    .pipe-step-hdr{{display:flex;align-items:center;gap:10px;padding:14px 18px;background:rgba(255,255,255,.025)}}
    .pipe-dot{{width:8px;height:8px;border-radius:50%;flex-shrink:0}}
    .pipe-model{{font-size:.8rem;font-weight:600;color:var(--tx);font-family:'DM Mono',monospace}}
    .pipe-role{{font-size:.65rem;color:var(--txm);flex:1;letter-spacing:.04em}}
    .pipe-status{{font-size:.6rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;padding:3px 10px;border-radius:100px;background:rgba(255,255,255,.04);color:var(--txd);border:1px solid var(--bds);font-family:'DM Mono',monospace;transition:all .3s}}
    .pipe-status.running{{background:rgba(255,196,0,.12);color:#ffc400;border-color:rgba(255,196,0,.3);animation:pulse-badge .9s ease-in-out infinite}}
    .pipe-status.done{{background:rgba(38,166,154,.12);color:#26a69a;border-color:rgba(38,166,154,.3)}}
    .pipe-status.error{{background:rgba(239,83,80,.12);color:#ef5350;border-color:rgba(239,83,80,.3)}}
    @keyframes pulse-badge{{0%,100%{{opacity:1}}50%{{opacity:.5}}}}
    .pipe-body{{padding:0 18px;max-height:0;overflow:hidden;transition:max-height .5s ease,padding .3s}}
    .pipe-body.open{{max-height:600px;padding:14px 18px 18px}}
    .pipe-verdict{{display:inline-flex;align-items:center;gap:8px;margin-bottom:10px}}
    .pv-badge{{font-size:.72rem;font-weight:700;padding:4px 12px;border-radius:6px;letter-spacing:.09em;text-transform:uppercase}}
    .pv-BULLISH,.pv-BUY{{background:rgba(38,166,154,.2);border:1px solid rgba(38,166,154,.4);color:#26a69a}}
    .pv-BEARISH,.pv-SELL{{background:rgba(239,83,80,.2);border:1px solid rgba(239,83,80,.4);color:#ef5350}}
    .pv-NEUTRAL,.pv-HOLD{{background:rgba(255,196,0,.12);border:1px solid rgba(255,196,0,.3);color:#ffc400}}
    .pipe-conf{{font-size:.65rem;color:var(--txm);font-family:'DM Mono',monospace}}
    .pipe-text{{font-size:.8rem;color:#bbb;line-height:1.75;white-space:pre-wrap;word-break:break-word}}
    .pipe-arrow{{text-align:center;padding:6px 0;color:var(--txd);font-size:.9rem;letter-spacing:.05em}}

    /* Final verdict */
    .final-verdict{{display:none;margin-top:16px}}
    .final-verdict.show{{display:block}}
    .fv-card{{border:1px solid var(--bdr);border-radius:14px;overflow:hidden}}
    .fv-top{{padding:20px 24px;background:rgba(255,255,255,.03);border-bottom:1px solid var(--bds);display:flex;align-items:center;gap:16px;flex-wrap:wrap}}
    .fv-badge{{font-size:1.1rem;font-weight:800;letter-spacing:.15em;padding:10px 22px;border-radius:10px;text-transform:uppercase;font-family:'Syne',sans-serif}}
    .fv-BUY{{background:rgba(38,166,154,.2);border:2px solid rgba(38,166,154,.5);color:#26a69a}}
    .fv-SELL{{background:rgba(239,83,80,.2);border:2px solid rgba(239,83,80,.5);color:#ef5350}}
    .fv-HOLD{{background:rgba(255,196,0,.15);border:2px solid rgba(255,196,0,.4);color:#ffc400}}
    .fv-meta{{flex:1}}
    .fv-summary{{font-size:.9rem;color:var(--tx);line-height:1.5;font-weight:500;margin-bottom:6px}}
    .fv-submeta{{display:flex;gap:14px;flex-wrap:wrap}}
    .fv-mi{{font-size:.67rem;color:var(--txm)}}.fv-mi strong{{color:var(--txd)}}
    .fv-pts{{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--bds);border-bottom:1px solid var(--bds)}}
    .fv-pt{{background:var(--bg);padding:14px 10px;text-align:center}}
    .fv-pt-lbl{{font-size:.55rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--txd);margin-bottom:5px;font-family:'DM Mono',monospace}}
    .fv-pt-val{{font-size:.88rem;font-weight:600;font-family:'DM Mono',monospace}}
    .pt-e{{color:#fff}}.pt-sl{{color:#ef5350}}.pt-t1{{color:#26a69a}}.pt-t2{{color:#00BFFF}}.pt-t3{{color:#a78bfa}}
    .fv-secs{{padding:0}}
    .fv-sec{{padding:16px 22px;border-bottom:1px solid var(--bds)}}
    .fv-sec:last-child{{border-bottom:none}}
    .fv-sec-hdr{{font-size:.57rem;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--txd);margin-bottom:8px;font-family:'DM Mono',monospace}}
    .fv-sec-body{{font-size:.8rem;color:#bbb;line-height:1.8;white-space:pre-wrap;word-break:break-word}}
    .agree-bar{{display:flex;align-items:center;gap:10px;padding:14px 22px;border-bottom:1px solid var(--bds)}}
    .agree-lbl{{font-size:.6rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--txd);font-family:'DM Mono',monospace;width:120px}}
    .agree-track{{flex:1;height:6px;background:rgba(255,255,255,.06);border-radius:3px;overflow:hidden}}
    .agree-fill{{height:100%;border-radius:3px;background:linear-gradient(90deg,var(--c1),var(--c2),var(--c3));transition:width .8s ease}}
    .agree-pct{{font-size:.67rem;font-family:'DM Mono',monospace;color:var(--txm);width:36px;text-align:right}}

    /* Spinner */
    .ai-loading{{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:40px 24px;gap:14px}}
    .ai-spin{{width:26px;height:26px;border-radius:50%;border:2px solid rgba(255,255,255,.08);border-top-color:rgba(255,255,255,.5);animation:spin .7s linear infinite}}
    @keyframes spin{{to{{transform:rotate(360deg)}}}}
    .ai-load-txt{{font-size:.75rem;color:var(--txm);letter-spacing:.04em}}

    /* ══ RSS NEWS PANEL ══ */
    .rss-panel{{padding:26px 30px;margin-bottom:18px}}
    .rss-tabs{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:18px}}
    .rss-tab{{background:transparent;border:1px solid var(--bdr);border-radius:100px;padding:5px 14px;font-size:.68rem;font-family:'DM Mono',monospace;cursor:pointer;color:var(--txm);letter-spacing:.05em;transition:all .16s;user-select:none}}
    .rss-tab:hover{{border-color:rgba(255,255,255,.3);color:var(--tx);background:var(--acm)}}
    .rss-tab.active{{background:var(--acc);border-color:var(--acc);color:#000;font-weight:600}}
    .rss-feed{{max-height:480px;overflow-y:auto;scrollbar-width:thin;scrollbar-color:rgba(255,255,255,.1) transparent}}
    .rss-feed::-webkit-scrollbar{{width:4px}}.rss-feed::-webkit-scrollbar-thumb{{background:rgba(255,255,255,.1);border-radius:2px}}
    .rss-item{{padding:14px 0;border-bottom:1px solid var(--bds);display:flex;flex-direction:column;gap:5px;cursor:pointer;transition:background .15s}}
    .rss-item:last-child{{border-bottom:none}}
    .rss-item:hover .rss-title{{color:var(--acc)}}
    .rss-item-meta{{display:flex;align-items:center;gap:8px}}
    .rss-source{{font-size:.58rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--txd);font-family:'DM Mono',monospace}}
    .rss-time{{font-size:.58rem;color:var(--txd);font-family:'DM Mono',monospace}}
    .rss-title{{font-size:.82rem;color:#ccc;line-height:1.5;transition:color .15s}}
    .rss-desc{{font-size:.72rem;color:var(--txm);line-height:1.5;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}}
    .rss-loading{{display:flex;align-items:center;justify-content:center;padding:40px;gap:10px;color:var(--txm);font-size:.8rem}}
    .rss-spinner{{width:18px;height:18px;border-radius:50%;border:2px solid rgba(255,255,255,.08);border-top-color:rgba(255,255,255,.4);animation:spin .7s linear infinite}}
    .rss-all-tab{{font-weight:700}}

    /* ══ LIVE NEWS PANEL (YouTube) ══ */
    .news-panel{{padding:26px 30px;margin-bottom:18px}}
    .news-live-dot{{display:inline-block;width:6px;height:6px;border-radius:50%;background:#ff4444;margin-right:6px;animation:lp 1.4s ease-in-out infinite;vertical-align:middle}}
    @keyframes lp{{0%,100%{{opacity:1;transform:scale(1)}}50%{{opacity:.3;transform:scale(.6)}}}}
    .news-tabs{{display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap}}
    .news-tab{{background:transparent;border:1px solid var(--bdr);border-radius:100px;padding:6px 18px;font-size:.7rem;font-family:'DM Mono',monospace;cursor:pointer;color:var(--txm);letter-spacing:.05em;transition:all .16s;user-select:none}}
    .news-tab:hover{{border-color:rgba(255,255,255,.3);color:var(--tx);background:var(--acm)}}
    .news-tab.active{{background:var(--acc);border-color:var(--acc);color:#000;font-weight:600}}
    .news-iframe-wrap{{position:relative;width:100%;padding-top:56.25%;border-radius:var(--rs);overflow:hidden;background:rgba(0,0,0,.5)}}
    .news-loading{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:var(--txm);font-size:.8rem;letter-spacing:.05em;flex-direction:column;gap:12px}}
    .news-spinner{{width:22px;height:22px;border-radius:50%;border:2px solid rgba(255,255,255,.1);border-top-color:rgba(255,255,255,.5);animation:spin .8s linear infinite}}
    .news-iframe-wrap iframe{{position:absolute;inset:0;width:100%;height:100%;border:none}}
    .news-tag{{font-size:.52rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;padding:1px 5px;border-radius:4px;background:rgba(255,255,255,.08);color:var(--txd);margin-left:4px;vertical-align:middle}}
    .nsb{{display:inline-flex;align-items:center;gap:5px;font-size:.6rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;padding:3px 10px;border-radius:100px;white-space:nowrap;margin-top:10px}}
    .nsb.live{{background:rgba(255,60,60,.15);border:1px solid rgba(255,60,60,.35);color:#ff6b6b}}
    .nsb.live::before{{content:'';display:inline-block;width:5px;height:5px;border-radius:50%;background:#ff4444;animation:lp 1.4s ease-in-out infinite}}
    .nsb.latest{{background:rgba(255,255,255,.06);border:1px solid var(--bdr);color:var(--txm)}}

    /* ══ Footer ══ */
    .site-footer{{position:relative;z-index:1;text-align:center;padding:52px 20px 80px;border-top:1px solid rgba(255,255,255,.04)}}
    .site-footer-sub{{font-size:.62rem;font-weight:700;letter-spacing:.28em;text-transform:uppercase;color:#2e2e2e;margin-bottom:14px;font-family:'DM Mono',monospace}}
    .site-footer-name{{font-size:clamp(3rem,9vw,6rem);font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:#ffffff;line-height:1;font-family:'Syne',sans-serif}}

    @media(max-width:860px){{form{{grid-template-columns:1fr 1fr;gap:12px}}.fg:first-child{{grid-column:span 2}}.btn{{grid-column:span 2;width:100%}}.fv-pts{{grid-template-columns:repeat(3,1fr)}}}}
    @media(max-width:600px){{header{{padding:0 16px}}.subtitle{{display:none}}main{{padding:18px 14px 48px}}.panel,.orch-panel,.rss-panel,.news-panel{{padding:20px 18px}}.chart-card{{padding:16px 10px 10px;min-height:300px}}.fv-pts{{grid-template-columns:repeat(2,1fr)}}}}
  </style>
</head>
<body>
<header>
  <div class="logo"><span class="logo-pip"></span>Starfish</div>
  <span class="subtitle">AI Market Oracle · Live Feeds</span>
</header>
<main>

<!-- ── Search Panel ── -->
<div class="glass panel">
  <div class="panel-label">Search</div>
  <form method="POST" action="/" id="main-form">
    <input type="hidden" name="indicators" id="inds-h" value="{','.join(active_indicators)}"/>
    <div class="fg">
      <label for="ticker">Ticker Symbol</label>
      <input id="ticker" name="ticker" type="text" value="{ticker}"
             placeholder="AAPL, GOOGL, TCS.NS" required autocomplete="off" autocapitalize="characters" spellcheck="false"/>
    </div>
    <div class="fg">
      <label for="period">Time Range</label>
      <select id="period" name="period">{popts}</select>
    </div>
    <div class="fg">
      <label for="chart_type">Chart Type</label>
      <select id="chart_type" name="chart_type">
        <option value="candlestick" {ct_c}>Candlestick</option>
        <option value="line" {ct_l}>Line</option>
      </select>
    </div>
    <button type="submit" class="btn">Load</button>
  </form>
  <div class="chips">{chips}</div>
  <div class="ind-row"><span class="ind-label">Indicators</span>{ichips}</div>
</div>

<!-- ── Chart ── -->
<div class="glass chart-card">{content}</div>

<!-- ── AI Orchestration Panel ── -->
<div class="glass orch-panel">
  <div class="orch-header">
    <div class="orch-title-group">
      <div class="orch-title">3-AI Orchestration Pipeline</div>
      <div class="orch-subtitle">DeepSeek → Llama → Qwen · Fully automatic · Sequential market prediction</div>
    </div>
    <div class="orch-controls">
      <span class="orch-status-lbl" id="orch-status-lbl"></span>
      <button class="btn-orch" id="btn-orch" onclick="runOrchestration()">▶ Run Analysis</button>
    </div>
  </div>

  <div class="pipeline" id="pipeline">
    {pipeline_steps}
  </div>

  <div class="final-verdict" id="final-verdict"></div>
</div>

<!-- ── RSS News Feed ── -->
<div class="glass rss-panel">
  <div class="panel-label">Live RSS · Financial News</div>
  <div class="rss-tabs" id="rss-tabs">
    <button class="rss-tab rss-all-tab active" data-feed="all">All Sources</button>
    {rss_tabs}
  </div>
  <div class="rss-feed" id="rss-feed">
    <div class="rss-loading"><div class="rss-spinner"></div>Loading headlines…</div>
  </div>
</div>

<!-- ── Live YouTube Stream ── -->
<div class="glass news-panel">
  <div class="panel-label"><span class="news-live-dot"></span>Live Financial TV</div>
  <div class="news-tabs" id="ntabs">{ntabs}</div>
  <div class="news-iframe-wrap">
    <div id="nload" class="news-loading"><div class="news-spinner"></div><span>Loading stream…</span></div>
    <iframe id="nframe" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen style="display:none"></iframe>
  </div>
  <span id="nbadge" class="nsb" style="display:none"></span>
</div>

</main>

<footer class="site-footer">
  <div class="site-footer-sub">made by</div>
  <div class="site-footer-name">ANTON BESKI</div>
</footer>

<script>
var TICKER = {json.dumps(ticker)};
var PERIOD = {json.dumps(period)};
var MODELS = {models_js};

// ── Indicator toggles ────────────────────────────────────────────────────────
function setTicker(s){{document.getElementById('ticker').value=s;document.getElementById('main-form').submit();}}
var aInds = {ai_js};
function toggleInd(el){{
  var k=el.dataset.ind,i=aInds.indexOf(k);
  i===-1?(aInds.push(k),el.classList.add('active')):(aInds.splice(i,1),el.classList.remove('active'));
  document.getElementById('inds-h').value=aInds.join(',');
  document.getElementById('main-form').submit();
}}

// ── Utilities ────────────────────────────────────────────────────────────────
function esc(s){{return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
function fn(v,d){{d=d===undefined?2:d;return(v==null||v===undefined||v==='')?'N/A':Number(v).toFixed(d);}}
function fmtDate(s){{
  if(!s)return'';
  try{{
    var d=new Date(s);
    if(isNaN(d.getTime()))return s.split('T')[0]||s.substring(0,16);
    return d.toLocaleString('en-US',{{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}});
  }}catch(e){{return s.substring(0,16);}}
}}

// ══ 3-AI ORCHESTRATION ═══════════════════════════════════════════════════════
var orchRunning = false;

function setStepStatus(key, status){{
  var el=document.getElementById('pipe-status-'+key);
  if(!el)return;
  el.textContent=status;
  el.className='pipe-status '+(status==='running'?'running':status==='done'?'done':status==='error'?'error':'');
  var step=document.getElementById('pipe-'+key);
  if(step){{
    step.className='pipe-step '+(status==='running'?'active':status==='done'||status==='error'?'done':'');
  }}
}}

function setStepBody(key, html, open){{
  var el=document.getElementById('pipe-body-'+key);
  if(!el)return;
  el.innerHTML=html;
  el.className='pipe-body'+(open?' open':'');
}}

function renderTechnical(r){{
  if(!r)return;
  var verdict=(r.technical_verdict||'NEUTRAL').toUpperCase();
  var kl=r.key_levels||{{}};
  var sig=r.indicator_signals||{{}};
  var html='<div class="pipe-verdict"><span class="pv-badge pv-'+verdict+'">'+verdict+'</span><span class="pipe-conf">Confidence: '+esc(r.confidence_score||'N/A')+'</span></div>';
  html+='<div class="pipe-text">'+esc(r.technical_analysis||'')+'</div>';
  html+='<div style="margin-top:10px;display:flex;gap:16px;flex-wrap:wrap;font-size:.67rem;color:var(--txm);font-family:\'DM Mono\',monospace">';
  html+='<span>S1: '+fn(kl.support_1)+'</span><span>S2: '+fn(kl.support_2)+'</span>';
  html+='<span>R1: '+fn(kl.resistance_1)+'</span><span>R2: '+fn(kl.resistance_2)+'</span>';
  if(r.pattern_detected)html+='<span>Pattern: '+esc(r.pattern_detected)+'</span>';
  html+='</div>';
  setStepBody('deepseek',html,true);
}}

function renderMacro(r){{
  if(!r)return;
  var verdict=(r.macro_verdict||'NEUTRAL').toUpperCase();
  var html='<div class="pipe-verdict"><span class="pv-badge pv-'+verdict+'">'+verdict+'</span><span class="pipe-conf">Confidence: '+esc(r.macro_confidence_score||'N/A')+'</span></div>';
  var headlines=(r.relevant_headlines||[]);
  if(headlines.length){{
    html+='<div style="margin-bottom:10px;display:flex;flex-direction:column;gap:4px">';
    headlines.forEach(function(h){{html+='<div style="font-size:.7rem;color:#888;padding:3px 0;border-left:2px solid rgba(14,165,233,.4);padding-left:10px">'+esc(h)+'</div>';}});
    html+='</div>';
  }}
  html+='<div class="pipe-text">'+esc(r.news_impact||r.macro_environment||'')+'</div>';
  if(r.catalyst_ahead)html+='<div style="margin-top:8px;font-size:.72rem;color:#ffc400">⚡ '+esc(r.catalyst_ahead)+'</div>';
  setStepBody('llama',html,true);
}}

function renderFinalVerdict(r){{
  if(!r)return;
  var verdict=(r.final_verdict||'HOLD').toUpperCase();
  var pt=r.price_targets||{{}};
  var agree=parseInt(r.agreement_score)||50;
  var secs=[
    {{lbl:'Orchestration Insight',key:'orchestration_insight'}},
    {{lbl:"Trader's Action Plan",key:'action_plan'}},
    {{lbl:'Key Risk',key:'key_risk'}},
  ];
  var secHtml=secs.map(function(s){{return '<div class="fv-sec"><div class="fv-sec-hdr">'+esc(s.lbl)+'</div><div class="fv-sec-body">'+esc(r[s.key]||'No data.')+'</div></div>';}}).join('');
  var html=
    '<div class="fv-card">'+
    '<div class="fv-top">'+
      '<div class="fv-badge fv-'+verdict+'">'+verdict+'</div>'+
      '<div class="fv-meta">'+
        '<div class="fv-summary">'+esc(r.prediction_summary||'')+'</div>'+
        '<div class="fv-submeta">'+
          '<span class="fv-mi"><strong>Conviction&nbsp;</strong>'+esc(r.conviction||'Medium')+'</span>'+
          '<span class="fv-mi"><strong>Horizon&nbsp;</strong>'+esc(r.time_horizon||'Mid')+'</span>'+
          '<span class="fv-mi"><strong>Risk/Reward&nbsp;</strong>'+fn(r.risk_reward_ratio,1)+'x</span>'+
        '</div>'+
      '</div>'+
    '</div>'+
    '<div class="agree-bar">'+
      '<span class="agree-lbl">AI Agreement</span>'+
      '<div class="agree-track"><div class="agree-fill" style="width:0%" id="agree-fill"></div></div>'+
      '<span class="agree-pct">'+agree+'%</span>'+
    '</div>'+
    '<div class="fv-pts">'+
      '<div class="fv-pt"><div class="fv-pt-lbl">Entry</div><div class="fv-pt-val pt-e">'+fn(pt.entry)+'</div></div>'+
      '<div class="fv-pt"><div class="fv-pt-lbl">Stop Loss</div><div class="fv-pt-val pt-sl">'+fn(pt.stop_loss)+'</div></div>'+
      '<div class="fv-pt"><div class="fv-pt-lbl">Target 1</div><div class="fv-pt-val pt-t1">'+fn(pt.target_1)+'</div></div>'+
      '<div class="fv-pt"><div class="fv-pt-lbl">Target 2</div><div class="fv-pt-val pt-t2">'+fn(pt.target_2)+'</div></div>'+
      '<div class="fv-pt"><div class="fv-pt-lbl">Target 3</div><div class="fv-pt-val pt-t3">'+fn(pt.target_3)+'</div></div>'+
    '</div>'+
    '<div class="fv-secs">'+secHtml+'</div>'+
    '</div>';

  var fvEl=document.getElementById('final-verdict');
  fvEl.innerHTML=html;
  fvEl.className='final-verdict show';
  setTimeout(function(){{
    var fill=document.getElementById('agree-fill');
    if(fill)fill.style.width=agree+'%';
  }},100);
}}

function renderSynthesis(r){{
  if(!r)return;
  var verdict=(r.final_verdict||'HOLD').toUpperCase();
  var html='<div class="pipe-verdict"><span class="pv-badge pv-'+verdict+'">'+verdict+'</span><span class="pipe-conf">Conviction: '+esc(r.conviction||'Medium')+'</span></div>';
  html+='<div class="pipe-text">'+esc(r.orchestration_insight||r.prediction_summary||'')+'</div>';
  setStepBody('qwen',html,true);
}}

function animateSteps(data){{
  var delay=0;
  MODELS.forEach(function(m,i){{
    setTimeout(function(){{
      setStepStatus(m.key,'running');
      document.getElementById('orch-status-lbl').textContent=m.label+': thinking…';
      setStepBody(m.key,'<div class="ai-loading"><div class="ai-spin"></div><div class="ai-load-txt">'+esc(m.label)+' analysing…</div></div>',true);
    }},delay);
    delay+=900;
    setTimeout(function(){{
      var step=data.steps&&data.steps[m.key];
      if(!step){{setStepStatus(m.key,'error');return;}}
      if(step.status==='error'){{
        setStepStatus(m.key,'error');
        setStepBody(m.key,'<div style="color:#ef5350;font-size:.78rem;padding:8px 0">'+esc(step.error||'Unknown error')+'</div>',true);
      }}else{{
        setStepStatus(m.key,'done');
        if(m.key==='deepseek')renderTechnical(step.result);
        else if(m.key==='llama')renderMacro(step.result);
        else if(m.key==='qwen')renderSynthesis(step.result);
      }}
    }},delay);
    delay+=600;
  }});
  setTimeout(function(){{
    if(data.final){{renderFinalVerdict(data.final);document.getElementById('orch-status-lbl').textContent='Analysis complete';}}
    orchRunning=false;
    document.getElementById('btn-orch').disabled=false;
    document.getElementById('btn-orch').textContent='▶ Run Analysis';
  }},delay+200);
}}

function runOrchestration(){{
  if(orchRunning)return;
  orchRunning=true;
  var btn=document.getElementById('btn-orch');
  btn.disabled=true; btn.textContent='Running…';
  document.getElementById('orch-status-lbl').textContent='Fetching market data…';
  document.getElementById('final-verdict').className='final-verdict';
  MODELS.forEach(function(m){{setStepStatus(m.key,'waiting');setStepBody(m.key,'',false);}});

  fetch('/api/orchestrate',{{
    method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{ticker:TICKER,period:PERIOD}})
  }}).then(function(res){{
    return res.json().then(function(data){{
      if(!res.ok||data.error)throw new Error(data.error||'HTTP '+res.status);
      return data;
    }});
  }}).then(function(data){{
    document.getElementById('orch-status-lbl').textContent='Rendering results…';
    animateSteps(data);
  }}).catch(function(err){{
    orchRunning=false;btn.disabled=false;btn.textContent='▶ Run Analysis';
    document.getElementById('orch-status-lbl').textContent='Error: '+err.message;
  }});
}}

// ══ RSS NEWS FEED ════════════════════════════════════════════════════════════
var currentRssFeed='all';

function loadRss(feedId){{
  currentRssFeed=feedId;
  var container=document.getElementById('rss-feed');
  container.innerHTML='<div class="rss-loading"><div class="rss-spinner"></div>Loading headlines…</div>';
  fetch('/api/rss?feed='+encodeURIComponent(feedId))
    .then(function(r){{return r.json();}})
    .then(function(data){{
      if(data.error){{container.innerHTML='<div style="color:#ef5350;padding:20px;font-size:.8rem">'+esc(data.error)+'</div>';return;}}
      if(!data.items||!data.items.length){{container.innerHTML='<div style="color:var(--txm);padding:20px;font-size:.8rem;text-align:center">No headlines available.</div>';return;}}
      var html='';
      data.items.forEach(function(item){{
        html+='<div class="rss-item" onclick="window.open(\''+esc(item.link)+'\',\'_blank\')">';
        html+='<div class="rss-item-meta"><span class="rss-source">'+esc(item.source)+'</span>';
        if(item.pub)html+='<span class="rss-time">'+esc(fmtDate(item.pub))+'</span>';
        html+='</div>';
        html+='<div class="rss-title">'+esc(item.title)+'</div>';
        if(item.desc)html+='<div class="rss-desc">'+esc(item.desc)+'</div>';
        html+='</div>';
      }});
      container.innerHTML=html;
    }})
    .catch(function(){{container.innerHTML='<div style="color:var(--txm);padding:20px;font-size:.8rem">Failed to load feed.</div>';}});
}}

document.getElementById('rss-tabs').addEventListener('click',function(e){{
  var btn=e.target.closest('.rss-tab');if(!btn)return;
  document.querySelectorAll('.rss-tab').forEach(function(t){{t.classList.remove('active');}});
  btn.classList.add('active');
  loadRss(btn.dataset.feed);
}});
loadRss('all');
setInterval(function(){{loadRss(currentRssFeed);}},300000); // refresh every 5 min

// ══ YOUTUBE LIVE STREAM ══════════════════════════════════════════════════════
var nframe=document.getElementById('nframe'),nload=document.getElementById('nload'),
    nbadge=document.getElementById('nbadge'),curHandle=null;

function nSetLoad(m){{nframe.style.display='none';nload.innerHTML='<div class="news-spinner"></div><span>'+m+'</span>';nload.style.display='flex';nbadge.style.display='none';}}
function nSetErr(m){{nframe.style.display='none';nload.innerHTML='<span>'+m+'</span>';nload.style.display='flex';}}

function loadCh(h){{
  if(curHandle===h)return;
  curHandle=h;nSetLoad('Loading stream…');nframe.src='about:blank';
  fetch('/api/live-id?handle='+encodeURIComponent(h))
    .then(function(r){{if(!r.ok)throw new Error('HTTP '+r.status);return r.json();}})
    .then(function(d){{
      if(h!==curHandle)return;
      if(d.error||!d.video_id){{nSetErr('Stream unavailable.');return;}}
      nframe.src='https://www.youtube.com/embed/'+d.video_id+'?autoplay=1&rel=0&modestbranding=1';
      nframe.style.display='block';nload.style.display='none';
      nbadge.style.display='inline-flex';
      nbadge.className=d.is_live?'nsb live':'nsb latest';
      nbadge.textContent=d.is_live?'LIVE':'Latest Video';
    }}).catch(function(){{if(h!==curHandle)return;nSetErr('Could not load stream.');}});
}}

document.getElementById('ntabs').addEventListener('click',function(e){{
  var btn=e.target.closest('.news-tab');if(!btn)return;
  document.querySelectorAll('.news-tab').forEach(function(t){{t.classList.remove('active');}});
  btn.classList.add('active');curHandle=null;loadCh(btn.dataset.handle);
}});
loadCh('{fh}');

// Auto-run orchestration on page load if ticker is set
setTimeout(function(){{
  if(TICKER && TICKER !== 'AAPL' || true){{
    runOrchestration();
  }}
}}, 1200);
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/", methods=["GET","POST"])
def index():
    ticker     = (request.form.get("ticker","AAPL") or "AAPL").strip().upper()
    period     = request.form.get("period","6mo")
    chart_type = request.form.get("chart_type","candlestick")
    ind_raw    = request.form.get("indicators",",".join(DEFAULT_INDICATORS))
    if period not in VALID_PERIODS: period = "6mo"
    if chart_type not in ("candlestick","line"): chart_type = "candlestick"
    active = set(filter(None, ind_raw.split(","))) if ind_raw else DEFAULT_INDICATORS
    graph_html, error = build_chart(ticker, period, chart_type, active)
    return render_page(ticker, period, chart_type, active, graph_html, error)


@app.route("/api/orchestrate", methods=["POST"])
def api_orchestrate():
    """Runs the full 3-AI pipeline synchronously and returns one JSON response.
    Vercel serverless does not support SSE/streaming, so we run all steps and
    return everything at once. The frontend animates the steps from the result."""
    body   = request.get_json(force=True) or {}
    ticker = (body.get("ticker","AAPL") or "AAPL").strip().upper()
    period = body.get("period","6mo")
    if period not in VALID_PERIODS: period = "6mo"

    steps  = {}   # collects per-step results + errors
    errors = []

    # ── Fetch market data ──
    try:
        df, err = fetch_yfinance_data(ticker, period)
        if err or df is None or df.empty:
            return jsonify({"error": f"Data fetch failed: {err or 'No data'}"}), 502
        name    = _get_name(ticker)
        payload = build_analysis_payload(ticker, period, name, df)
    except Exception as e:
        return jsonify({"error": f"Setup error: {e}"}), 500

    # ── Fetch RSS headlines ──
    try:
        headlines = fetch_all_rss(20)
    except Exception:
        headlines = []

    # ── STEP 1: DeepSeek — Technical Analysis ──
    technical_result = None
    m1 = AI_MODELS[0]
    try:
        prompt1 = build_technical_prompt(payload)
        technical_result = call_openrouter(m1["id"], prompt1)
        steps[m1["key"]] = {"status": "done", "result": technical_result}
    except Exception as e:
        steps[m1["key"]] = {"status": "error", "error": str(e)}
        errors.append(str(e))
        technical_result = {"technical_verdict":"NEUTRAL","technical_analysis":"Analysis failed.","technical_bias":"Unknown.","confidence_score":50,"key_levels":{},"indicator_signals":{},"pattern_detected":""}

    # ── STEP 2: Llama — Macro + News ──
    macro_result = None
    m2 = AI_MODELS[1]
    try:
        prompt2 = build_macro_prompt(payload, technical_result or {}, headlines)
        macro_result = call_openrouter(m2["id"], prompt2)
        steps[m2["key"]] = {"status": "done", "result": macro_result}
    except Exception as e:
        steps[m2["key"]] = {"status": "error", "error": str(e)}
        errors.append(str(e))
        macro_result = {"macro_verdict":"NEUTRAL","macro_environment":"Analysis failed.","news_impact":"Unknown.","catalyst_ahead":"","macro_risk":"","macro_confidence_score":50,"relevant_headlines":[]}

    # ── STEP 3: Qwen — Final Synthesis ──
    synthesis_result = None
    m3 = AI_MODELS[2]
    try:
        prompt3 = build_synthesis_prompt(payload, technical_result or {}, macro_result or {})
        synthesis_result = call_openrouter(m3["id"], prompt3)
        steps[m3["key"]] = {"status": "done", "result": synthesis_result}
    except Exception as e:
        steps[m3["key"]] = {"status": "error", "error": str(e)}
        errors.append(str(e))

    return jsonify({
        "ticker":   ticker,
        "period":   period,
        "steps":    steps,
        "final":    synthesis_result,
        "errors":   errors,
    })


@app.route("/api/rss")
def api_rss():
    feed_id = request.args.get("feed","all").strip()
    try:
        if feed_id == "all":
            items = fetch_all_rss(40)
        else:
            items = fetch_rss_feed(feed_id)
        return jsonify({"items": items})
    except Exception as e:
        return jsonify({"error": str(e), "items": []}), 500


@app.route("/api/rate-limits")
def api_rate_limits():
    return jsonify({
        m["key"]: {**rl_check(m["key"]), "rpm_reset_secs": rl_next_rpm_reset(m["key"])}
        for m in AI_MODELS
    })


@app.route("/api/live-id")
def api_live_id():
    handle = request.args.get("handle","").strip()
    if not handle: return jsonify({"error": "missing handle"}), 400
    vid, live = fetch_live_video_id(handle)
    if vid: return jsonify({"video_id": vid, "is_live": live})
    return jsonify({"error": "not found"}), 404


@app.route("/debug")
def debug():
    out, color = [], "#7fff7f"
    try:
        df, err = fetch_yfinance_data("AAPL","5d")
        if err: out.append(f"Error: {err}"); color="#ff7f7f"
        elif df is not None: out.append(f"OK shape:{df.shape}"); out.append(df.tail().to_string())
        else: out.append("No data"); color="#ffaa44"
    except Exception: out.append(traceback.format_exc()); color="#ff7f7f"
    # Also test RSS
    try:
        items = fetch_rss_feed("reuters")
        out.append(f"\nRSS Reuters: {len(items)} items")
        if items: out.append(f"First: {items[0]['title'][:80]}")
    except Exception as e: out.append(f"\nRSS error: {e}")
    body = "\n".join(out)
    return f"<pre style='background:#111;color:{color};padding:24px;font-family:monospace;white-space:pre-wrap'>{body}</pre>"


@app.errorhandler(500)
def e500(e):
    return f"<pre style='background:#111;color:#aaa;padding:24px;font-family:monospace'>500\n\n{traceback.format_exc()}</pre>", 500


# Vercel exposes `app` directly — do not call app.run() here.
# Local dev: run with `flask run` or `python app.py` from project root.
