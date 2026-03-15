import os, re, time, traceback, requests, random, json, xml.etree.ElementTree as ET
import numpy as np
import pandas as pd
from flask import Flask, request, jsonify
import yfinance as yf
import plotly.graph_objects as go
import plotly.offline as pyo
from plotly.subplots import make_subplots

app = Flask(__name__)

# ── Config ───────────────────────────────────────────────────────────────────
OPEN_ROUTER_API_KEY = os.environ.get("OPEN_ROUTER_API_KEY", "")

AI_MODELS = [
    {"id": "deepseek/deepseek-r1",              "key": "deepseek", "label": "DeepSeek R1",   "color": "#7c3aed", "role": "Technical Analyst"},
    {"id": "meta-llama/llama-3.3-70b-instruct", "key": "llama",    "label": "Llama 3.3 70B", "color": "#0ea5e9", "role": "Macro Strategist"},
    {"id": "qwen/qwen3-coder",                  "key": "qwen",     "label": "Qwen3 Coder",   "color": "#f59e0b", "role": "Quant Synthesizer"},
]

POPULAR_STOCKS = [("AAPL","Apple"),("GOOGL","Google"),("MSFT","Microsoft"),("TSLA","Tesla"),
                  ("AMZN","Amazon"),("NVDA","NVIDIA"),("TCS.NS","TCS"),("RELIANCE.NS","Reliance")]
PERIODS        = [("1mo","1 Month"),("3mo","3 Months"),("6mo","6 Months"),("1y","1 Year"),("2y","2 Years"),("5y","5 Years")]
VALID_PERIODS  = {p[0] for p in PERIODS}
INDICATORS     = [("sma","SMA"),("bb","Bollinger"),("rsi","RSI"),("macd","MACD"),("vol","Volume")]
DEFAULT_INDICATORS = {"sma","vol"}

# Serverless-safe stubs — no shared state across Vercel invocations
def rl_check(key):  return {"rpm_used":0,"rpm_max":20,"rpd_used":0,"rpd_max":200,"available":True}
def rl_record(key): pass
def rl_next_rpm_reset(key): return 0

# ── YouTube channels ──────────────────────────────────────────────────────────
NEWS_CHANNELS = [
    {"id":"cnbctv18",  "handle":"cnbctv18",  "label":"CNBC TV18",       "region":"India",  "video_id":"1_Ih0JYmkjI"},
    {"id":"bloomberg", "handle":"Bloomberg", "label":"Bloomberg Global", "region":"Global", "video_id":"iEpJwprxDdk"},
    {"id":"yahoofi",   "handle":"yahoofi",   "label":"Yahoo Finance",    "region":"Global", "video_id":"KQp-e_XQnDE"},
]

def fetch_live_video_id(handle):
    for ch in NEWS_CHANNELS:
        if ch["handle"] == handle and ch.get("video_id"):
            return ch["video_id"], True
    return None, False

# ── RSS ───────────────────────────────────────────────────────────────────────
RSS_FEEDS = [
    {"id":"reuters",   "label":"Reuters",        "url":"https://feeds.reuters.com/reuters/businessNews"},
    {"id":"cnbc",      "label":"CNBC",            "url":"https://www.cnbc.com/id/10001147/device/rss/rss.html"},
    {"id":"wsj",       "label":"WSJ Markets",     "url":"https://feeds.a.dj.com/rss/RSSMarketsMain.xml"},
    {"id":"moneyctrl", "label":"MoneyControl",    "url":"https://www.moneycontrol.com/rss/MCtopnews.xml"},
    {"id":"ecdimes",   "label":"Economic Times",  "url":"https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"},
    {"id":"ft",        "label":"Financial Times", "url":"https://www.ft.com/rss/home/uk"},
]
_RSS_CACHE = {}
_RSS_TTL   = 300

def _parse_date(s):
    if not s: return 0
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(s).timestamp()
    except Exception:
        pass
    return 0

def fetch_rss(feed_id):
    feed = next((f for f in RSS_FEEDS if f["id"] == feed_id), None)
    if not feed: return []
    now = time.time()
    if feed_id in _RSS_CACHE and now - _RSS_CACHE[feed_id]["ts"] < _RSS_TTL:
        return _RSS_CACHE[feed_id]["items"]
    items = []
    try:
        r = requests.get(feed["url"], headers={"User-Agent":"Mozilla/5.0","Accept":"application/rss+xml,*/*"}, timeout=8)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        ns   = {"atom":"http://www.w3.org/2005/Atom"}
        entries = root.findall(".//item") or root.findall(".//atom:entry", ns)
        for e in entries[:20]:
            def gt(tag):
                el = e.find(tag) or e.find(f"atom:{tag}", ns)
                return (el.text or "").strip() if el is not None else ""
            link = gt("link")
            if not link:
                al = e.find("atom:link", ns)
                link = al.get("href","") if al is not None else ""
            title = gt("title")
            if not title: continue
            desc = re.sub(r'<[^>]+>','', gt("description") or gt("summary"))[:200].strip()
            items.append({"title":title,"link":link,"pub":gt("pubDate") or gt("published") or gt("updated"),"desc":desc,"source":feed["label"]})
    except Exception:
        pass
    _RSS_CACHE[feed_id] = {"items":items,"ts":now}
    return items

def fetch_all_rss(limit=40):
    all_items = []
    for f in RSS_FEEDS:
        try: all_items.extend(fetch_rss(f["id"]))
        except: pass
    all_items.sort(key=lambda x: _parse_date(x.get("pub","")), reverse=True)
    return all_items[:limit]

# ══════════════════════════════════════════════════════════════════════════════
# MARKET DATA — yfinance only (custom Yahoo scraper gets 429'd on cloud IPs)
# ══════════════════════════════════════════════════════════════════════════════
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

def _make_session():
    s = requests.Session()
    s.headers.update({"User-Agent":random.choice(_UA_POOL),"Accept-Language":"en-US,en;q=0.9","Accept-Encoding":"gzip, deflate, br"})
    return s

def _clean_df(df):
    if df is None or df.empty: return None
    if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
    cols = [c for c in ["Open","High","Low","Close","Volume"] if c in df.columns]
    if "Close" not in cols: return None
    return df[cols].dropna(subset=["Close"]) if not df.empty else None

def fetch_market_data(ticker, period):
    import io, contextlib
    buf = io.StringIO(); errors = []

    for attempt in range(3):
        try:
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                if attempt < 2:
                    sess = _make_session()
                    df = yf.Ticker(ticker, session=sess).history(period=period, interval="1d", auto_adjust=True, actions=False, timeout=25)
                else:
                    df = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=True, actions=False, timeout=30)
            df = _clean_df(df)
            if df is not None and not df.empty: return df, None
        except Exception as e:
            errors.append(str(e))

    hint = " — for NSE stocks add .NS suffix (e.g. TCS.NS)" if "." not in ticker else ""
    return None, f"Could not fetch '{ticker}'{hint}. Last error: {errors[-1] if errors else 'unknown'}"

def get_ticker_name(ticker):
    try:
        info = yf.Ticker(ticker).fast_info
        name = getattr(info, "long_name", None) or getattr(info, "longName", None)
        if not name:
            name = yf.Ticker(ticker).info.get("shortName") or yf.Ticker(ticker).info.get("longName")
        return (name or "").strip() or ticker
    except Exception:
        return ticker

# ══════════════════════════════════════════════════════════════════════════════
# TECHNICAL INDICATORS
# ══════════════════════════════════════════════════════════════════════════════
def calc_sma(c, w): return c.rolling(w).mean()
def calc_ema(c, w): return c.ewm(span=w, adjust=False).mean()
def calc_bb(c, w=20, n=2):
    m = calc_sma(c,w); s = c.rolling(w).std(); return m+n*s, m, m-n*s
def calc_rsi(c, w=14):
    d=c.diff(); g=d.clip(lower=0); l=-d.clip(upper=0)
    ag=g.ewm(com=w-1,min_periods=w).mean(); al=l.ewm(com=w-1,min_periods=w).mean()
    return 100-100/(1+ag/al.replace(0,np.nan))
def calc_macd(c, f=12, s=26, sg=9):
    ml=calc_ema(c,f)-calc_ema(c,s); sl=ml.ewm(span=sg,adjust=False).mean(); return ml,sl,ml-sl
def calc_atr(h, l, c, w=14):
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    return tr.ewm(com=w-1,min_periods=w).mean()

def _sf(v, d=4):
    try: x=float(v); return None if np.isnan(x) else round(x,d)
    except: return None

# ══════════════════════════════════════════════════════════════════════════════
# ANALYSIS PAYLOAD
# ══════════════════════════════════════════════════════════════════════════════
def build_analysis_payload(ticker, period, name, df):
    c=df["Close"].squeeze().dropna(); h=df["High"].squeeze(); lo=df["Low"].squeeze(); op=df["Open"].squeeze()
    vol=df["Volume"].squeeze() if "Volume" in df.columns else None
    n=len(c); cur=_sf(c.iloc[-1]); prev=_sf(c.iloc[-2]) if n>1 else cur
    currency="INR" if ticker.upper().endswith((".NS",".BO")) else "USD"
    hi52=_sf(c.tail(252).max()); lo52=_sf(c.tail(252).min())
    macd_d={}
    if n>=27:
        ml,sl,hl=calc_macd(c)
        macd_d={"macd":_sf(ml.iloc[-1]),"signal":_sf(sl.iloc[-1]),"histogram":_sf(hl.iloc[-1]),
                "hist_prev":_sf(hl.iloc[-2]) if n>27 else None,
                "crossover":"bullish" if(hl.iloc[-1]>0 and hl.iloc[-2]<0) else "bearish" if(hl.iloc[-1]<0 and hl.iloc[-2]>0) else "none"}
    bb_d={}
    if n>=20:
        bbu,bbm,bbl=calc_bb(c)
        denom=(_sf(bbu.iloc[-1]) or 0)-(_sf(bbl.iloc[-1]) or 0)
        bb_d={"upper":_sf(bbu.iloc[-1]),"mid":_sf(bbm.iloc[-1]),"lower":_sf(bbl.iloc[-1]),
              "percent_b":_sf(((cur or 0)-(_sf(bbl.iloc[-1]) or 0))/denom) if denom else None,
              "bandwidth":_sf((bbu.iloc[-1]-bbl.iloc[-1])/bbm.iloc[-1]*100) if bbm.iloc[-1] else None}
    sma20=_sf(calc_sma(c,20).iloc[-1]) if n>=20 else None
    sma50=_sf(calc_sma(c,50).iloc[-1]) if n>=50 else None
    sma200=_sf(calc_sma(c,200).iloc[-1]) if n>=200 else None
    rsi_v=_sf(calc_rsi(c).iloc[-1]) if n>=15 else None
    atr_v=_sf(calc_atr(h,lo,c).iloc[-1]) if n>=15 else None
    vol_d={}
    if vol is not None:
        avg20=_sf(vol.tail(20).mean()); cv=_sf(vol.iloc[-1])
        vol_d={"latest":cv,"avg_20d":avg20,"ratio_vs_avg":_sf(cv/avg20) if avg20 else None}
    trend=[]
    if sma20 and cur: trend.append("above_sma20" if cur>sma20 else "below_sma20")
    if sma50 and cur: trend.append("above_sma50" if cur>sma50 else "below_sma50")
    if sma200 and cur: trend.append("above_sma200" if cur>sma200 else "below_sma200")
    if sma20 and sma50: trend.append("golden_cross" if sma20>sma50 else "death_cross")
    recent=df.tail(30).copy(); recent.index=recent.index.astype(str)
    ohlcv=[{"date":d[:10],"open":_sf(r.get("Open")),"high":_sf(r.get("High")),"low":_sf(r.get("Low")),
             "close":_sf(r.get("Close")),"volume":int(r["Volume"]) if "Volume" in r and pd.notna(r["Volume"]) else None}
            for d,r in recent.iterrows()]
    return {"ticker":ticker,"name":name,"currency":currency,"period":period,"bars":n,
            "price":{"current":cur,"prev":prev,"change":_sf(cur-prev) if cur and prev else None,
                     "change_pct":_sf(((cur-prev)/prev)*100) if cur and prev else None,
                     "52w_high":hi52,"52w_low":lo52,"pct_from_52h":_sf(((cur-hi52)/hi52)*100) if cur and hi52 else None},
            "ma":{"sma20":sma20,"sma50":sma50,"sma200":sma200,"ema9":_sf(calc_ema(c,9).iloc[-1]),"ema21":_sf(calc_ema(c,21).iloc[-1])},
            "bb":bb_d,"rsi":{"value":rsi_v,"last5":[_sf(v) for v in calc_rsi(c).tail(5).tolist()] if n>=20 else []},
            "macd":macd_d,"atr":{"value":atr_v,"pct":_sf((atr_v/cur)*100) if atr_v and cur else None},
            "volume":vol_d,"trend":trend,"ohlcv":ohlcv}

# ══════════════════════════════════════════════════════════════════════════════
# AI PROMPTS
# ══════════════════════════════════════════════════════════════════════════════
def _fmt(p):
    px=p["price"]; ma=p["ma"]; bb=p.get("bb",{}); rsi=p.get("rsi",{})
    macd=p.get("macd",{}); atr=p.get("atr",{}); vol=p.get("volume",{})
    f=lambda v,d=2: f"{v:.{d}f}" if v is not None else "N/A"
    up=lambda v:("above" if px["current"] and v and px["current"]>v else "below") if v else "N/A"
    rows="\n".join(f"{r['date']},{r['open']},{r['high']},{r['low']},{r['close']},{r['volume']}" for r in p["ohlcv"])
    return (f"STOCK: {p['name']} ({p['ticker']}) | {p['currency']} {f(px['current'])} | Period:{p['period']} Bars:{p['bars']}\n"
            f"PRICE: chg {f(px['change'])} ({f(px['change_pct'])}%) | 52W H:{f(px['52w_high'])} L:{f(px['52w_low'])} | from52H:{f(px['pct_from_52h'])}%\n"
            f"MA: SMA20={f(ma['sma20'])}({up(ma['sma20'])} SMA20) SMA50={f(ma['sma50'])}({up(ma['sma50'])} SMA50) SMA200={f(ma['sma200'])}({up(ma['sma200'])} SMA200) EMA9={f(ma['ema9'])} EMA21={f(ma['ema21'])}\n"
            f"TREND: {', '.join(p['trend']) or 'none'}\n"
            f"BB(20,2): upper={f(bb.get('upper'))} mid={f(bb.get('mid'))} lower={f(bb.get('lower'))} %B={f(bb.get('percent_b'),3)} bw={f(bb.get('bandwidth'))}%\n"
            f"RSI(14): {f(rsi.get('value'))} | last5: {', '.join(f(v) for v in rsi.get('last5',[]))}\n"
            f"MACD(12,26,9): line={f(macd.get('macd'))} signal={f(macd.get('signal'))} hist={f(macd.get('histogram'))} prev={f(macd.get('hist_prev'))} cross={macd.get('crossover','none').upper()}\n"
            f"ATR(14):{f(atr.get('value'))} ({f(atr.get('pct'))}%) | Vol ratio:{f(vol.get('ratio_vs_avg'))}x\n"
            f"OHLCV last 30d:\ndate,open,high,low,close,volume\n{rows}")

def build_technical_prompt(p):
    return (f"You are DeepSeek R1 — STEP 1 of 3 in a multi-AI pipeline. Role: Technical Analyst.\n"
            f"Analyse ONLY technical indicators. Output feeds to Macro Strategist then Quant Synthesizer.\n\n"
            f"{_fmt(p)}\n\n"
            f"Return ONLY valid JSON, no markdown:\n"
            f'{{"technical_verdict":"BULLISH|BEARISH|NEUTRAL","confidence_score":75,'
            f'"key_levels":{{"support_1":0.0,"support_2":0.0,"resistance_1":0.0,"resistance_2":0.0}},'
            f'"indicator_signals":{{"rsi":"string","macd":"string","bollinger":"string","moving_averages":"string","volume":"string"}},'
            f'"pattern_detected":"string",'
            f'"technical_analysis":"3-paragraph detailed breakdown of indicators, agreements, conflicts, key price levels",'
            f'"technical_bias":"1-2 sentence short-term directional bias with specific price levels"}}')

def build_macro_prompt(p, tech, headlines):
    px=p["price"]; f=lambda v,d=2: f"{v:.{d}f}" if v is not None else "N/A"
    hl="\n".join(f"- {h['source']}: {h['title']}" for h in headlines[:15]) if headlines else "No headlines."
    return (f"You are Llama 3.3 — STEP 2 of 3 in a multi-AI pipeline. Role: Macro Strategist.\n\n"
            f"STOCK: {p['name']} ({p['ticker']}) — {p['currency']} {f(px['current'])}\n\n"
            f"STEP 1 TECHNICAL (DeepSeek R1):\n"
            f"Verdict:{tech.get('technical_verdict','N/A')} Confidence:{tech.get('confidence_score','N/A')}\n"
            f"Bias:{tech.get('technical_bias','N/A')}\nPattern:{tech.get('pattern_detected','N/A')}\n"
            f"Analysis:{str(tech.get('technical_analysis','N/A'))[:500]}\n\n"
            f"LIVE RSS HEADLINES:\n{hl}\n\n"
            f"Return ONLY valid JSON, no markdown:\n"
            f'{{"macro_verdict":"BULLISH|BEARISH|NEUTRAL","macro_confidence_score":70,'
            f'"relevant_headlines":["headline1","headline2","headline3"],'
            f'"macro_environment":"2-paragraph macro backdrop covering rates, sector, institutional flows",'
            f'"news_impact":"How current news specifically affects this stock/sector",'
            f'"catalyst_ahead":"Upcoming catalyst to watch",'
            f'"macro_risk":"Primary macro risk that could reverse the technical setup"}}')

def build_synthesis_prompt(p, tech, macro):
    px=p["price"]; f=lambda v,d=2: f"{v:.{d}f}" if v is not None else "N/A"
    kl=tech.get("key_levels",{})
    return (f"You are Qwen3 — STEP 3 of 3 in a multi-AI pipeline. Role: Quant Synthesizer.\n"
            f"Synthesize both analyses into ONE authoritative prediction with precise price targets.\n\n"
            f"STOCK: {p['name']} ({p['ticker']}) — Current: {p['currency']} {f(px['current'])}\n\n"
            f"STEP 1 TECHNICAL:\n"
            f"Verdict:{tech.get('technical_verdict','N/A')} Confidence:{tech.get('confidence_score','N/A')}\n"
            f"Bias:{tech.get('technical_bias','N/A')}\n"
            f"Support:{kl.get('support_1','N/A')}/{kl.get('support_2','N/A')} Resistance:{kl.get('resistance_1','N/A')}/{kl.get('resistance_2','N/A')}\n"
            f"RSI:{tech.get('indicator_signals',{}).get('rsi','N/A')} MACD:{tech.get('indicator_signals',{}).get('macd','N/A')}\n\n"
            f"STEP 2 MACRO:\n"
            f"Verdict:{macro.get('macro_verdict','N/A')} Confidence:{macro.get('macro_confidence_score','N/A')}\n"
            f"Macro:{str(macro.get('macro_environment','N/A'))[:400]}\n"
            f"News:{macro.get('news_impact','N/A')}\nCatalyst:{macro.get('catalyst_ahead','N/A')}\nRisk:{macro.get('macro_risk','N/A')}\n\n"
            f"Current price is {p['currency']} {f(px['current'])}. Set realistic targets based on ATR and support/resistance.\n\n"
            f"Return ONLY valid JSON, no markdown:\n"
            f'{{"final_verdict":"BUY|SELL|HOLD","conviction":"Low|Medium|High|Very High",'
            f'"time_horizon":"Short (1-5 days)|Mid (1-4 weeks)|Long (1-3 months)",'
            f'"price_targets":{{"entry":0.0,"stop_loss":0.0,"target_1":0.0,"target_2":0.0,"target_3":0.0}},'
            f'"risk_reward_ratio":0.0,"agreement_score":75,'
            f'"prediction_summary":"One powerful sentence — core thesis and what market will do",'
            f'"action_plan":"Step-by-step trader action: entry timing, position sizing, exit rules",'
            f'"key_risk":"Most important risk that could invalidate this call",'
            f'"orchestration_insight":"What the 3-AI pipeline revealed that a single AI would have missed"}}')

def call_openrouter(model_id, prompt):
    if not OPEN_ROUTER_API_KEY:
        raise ValueError("OPEN_ROUTER_API_KEY not set. Add it in Vercel → Settings → Environment Variables.")
    r = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization":f"Bearer {OPEN_ROUTER_API_KEY}","Content-Type":"application/json",
                 "HTTP-Referer":"https://starfish.finance","X-Title":"Starfish Market Oracle"},
        json={"model":model_id,"messages":[{"role":"user","content":prompt}],"temperature":0.15,"max_tokens":2048},
        timeout=90,
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"]["content"].strip()
    content = re.sub(r"^```(?:json)?\s*","",content); content = re.sub(r"\s*```$","",content)
    m = re.search(r'\{.*\}', content, re.DOTALL)
    if m: content = m.group(0)
    return json.loads(content)

# ══════════════════════════════════════════════════════════════════════════════
# CHART BUILDER
# ══════════════════════════════════════════════════════════════════════════════
_C = {"bg":"rgba(0,0,0,0)","paper":"rgba(0,0,0,0)","grid":"rgba(255,255,255,0.06)","axis":"#555",
      "text":"#888","white":"#fff","green":"#26a69a","red":"#ef5350",
      "sma20":"#FFD700","sma50":"#FF8C00","sma200":"#00BFFF",
      "bb_u":"rgba(120,180,255,0.7)","bb_l":"rgba(120,180,255,0.7)","bb_f":"rgba(120,180,255,0.06)",
      "rsi":"#a78bfa","rsi_ob":"rgba(239,83,80,0.25)","rsi_os":"rgba(38,166,154,0.25)",
      "macd":"#60a5fa","sig":"#f97316","hp":"rgba(38,166,154,0.8)","hn":"rgba(239,83,80,0.8)",
      "vu":"rgba(38,166,154,0.5)","vd":"rgba(239,83,80,0.5)"}

def build_chart(ticker, period, chart_type, indicators):
    data, err = fetch_market_data(ticker, period)
    if err: return None, err
    if data is None or data.empty: return None, f"No data for '{ticker}'."
    data = data.dropna(subset=["Close"])
    if len(data) < 5: return None, "Not enough data points."
    cl=data["Close"].squeeze(); hi=data["High"].squeeze(); lo=data["Low"].squeeze(); op=data["Open"].squeeze()
    vol=data["Volume"].squeeze() if "Volume" in data.columns else None
    dates=data.index; name=get_ticker_name(ticker)
    sv="vol" in indicators and vol is not None; sr="rsi" in indicators; sm="macd" in indicators
    rows=1+int(sv)+int(sr)+int(sm)
    rh={1:[1.0],2:[0.65,0.35],3:[0.55,0.22,0.23],4:[0.50,0.17,0.17,0.16]}.get(rows,[0.5,0.17,0.17,0.16])
    titles=[f"{name} ({ticker.upper()})"]
    if sv: titles.append("Volume")
    if sr: titles.append("RSI (14)")
    if sm: titles.append("MACD (12,26,9)")
    fig=make_subplots(rows=rows,cols=1,shared_xaxes=True,vertical_spacing=0.03,row_heights=rh,subplot_titles=titles)
    rv=2 if sv else None; rr=(2+int(sv)) if sr else None; rm=(2+int(sv)+int(sr)) if sm else None
    if chart_type=="candlestick":
        fig.add_trace(go.Candlestick(x=dates,open=op,high=hi,low=lo,close=cl,name="Price",
            increasing_line_color=_C["green"],increasing_fillcolor="rgba(38,166,154,.18)",
            decreasing_line_color=_C["red"],decreasing_fillcolor="rgba(239,83,80,.18)",line=dict(width=1)),row=1,col=1)
    else:
        fig.add_trace(go.Scatter(x=dates,y=cl,mode="lines",name="Price",
            line=dict(color=_C["white"],width=2),fill="tozeroy",fillcolor="rgba(255,255,255,.04)"),row=1,col=1)
    if "sma" in indicators:
        for w,color,lbl in [(20,_C["sma20"],"SMA 20"),(50,_C["sma50"],"SMA 50"),(200,_C["sma200"],"SMA 200")]:
            if len(cl)>=w: fig.add_trace(go.Scatter(x=dates,y=calc_sma(cl,w),mode="lines",name=lbl,line=dict(color=color,width=1.2),opacity=0.85),row=1,col=1)
    if "bb" in indicators and len(cl)>=20:
        bbu,bbm,bbl=calc_bb(cl)
        fig.add_trace(go.Scatter(x=dates,y=bbu,mode="lines",name="BB Upper",line=dict(color=_C["bb_u"],width=1,dash="dot")),row=1,col=1)
        fig.add_trace(go.Scatter(x=dates,y=bbl,mode="lines",name="BB Lower",line=dict(color=_C["bb_l"],width=1,dash="dot"),fill="tonexty",fillcolor=_C["bb_f"]),row=1,col=1)
    if sv and vol is not None:
        colors=[_C["vu"] if c>=o else _C["vd"] for c,o in zip(cl,op)]
        fig.add_trace(go.Bar(x=dates,y=vol,name="Volume",marker_color=colors,showlegend=False),row=rv,col=1)
    if sr and len(cl)>=15:
        rv2=calc_rsi(cl)
        fig.add_trace(go.Scatter(x=dates,y=rv2,mode="lines",name="RSI",line=dict(color=_C["rsi"],width=1.5),showlegend=False),row=rr,col=1)
        fig.add_hrect(y0=70,y1=100,row=rr,col=1,fillcolor=_C["rsi_ob"],line_width=0,layer="below")
        fig.add_hrect(y0=0,y1=30,row=rr,col=1,fillcolor=_C["rsi_os"],line_width=0,layer="below")
        for lvl,c in [(70,"rgba(239,83,80,.5)"),(30,"rgba(38,166,154,.5)"),(50,"rgba(255,255,255,.15)")]:
            fig.add_hline(y=lvl,row=rr,col=1,line=dict(color=c,width=0.8,dash="dash"))
    if sm and len(cl)>=27:
        ml,sl,hl=calc_macd(cl)
        hc=[_C["hp"] if v>=0 else _C["hn"] for v in hl.fillna(0)]
        fig.add_trace(go.Bar(x=dates,y=hl,name="MACD Hist",marker_color=hc,showlegend=False),row=rm,col=1)
        fig.add_trace(go.Scatter(x=dates,y=ml,mode="lines",name="MACD",line=dict(color=_C["macd"],width=1.5),showlegend=False),row=rm,col=1)
        fig.add_trace(go.Scatter(x=dates,y=sl,mode="lines",name="Signal",line=dict(color=_C["sig"],width=1.5),showlegend=False),row=rm,col=1)
        fig.add_hline(y=0,row=rm,col=1,line=dict(color="rgba(255,255,255,.2)",width=0.8,dash="dash"))
    ax=dict(gridcolor=_C["grid"],color=_C["axis"],showline=False,zeroline=False,tickfont=dict(size=9,color=_C["text"]))
    fig.update_layout(height=420+120*(rows-1),plot_bgcolor=_C["bg"],paper_bgcolor=_C["paper"],
        font=dict(color=_C["text"],family="'DM Sans',sans-serif",size=11),
        legend=dict(orientation="h",yanchor="bottom",y=1.01,xanchor="left",x=0,bgcolor="rgba(0,0,0,0)",font=dict(size=10,color=_C["text"])),
        hovermode="x unified",margin=dict(l=55,r=20,t=55,b=30),
        hoverlabel=dict(bgcolor="rgba(12,12,12,.95)",bordercolor="rgba(255,255,255,.12)",font=dict(color="#fff")),
        xaxis_rangeslider_visible=False,dragmode="pan")
    for i in range(1,rows+1):
        fig.update_layout(**{f"xaxis{'' if i==1 else i}":{**ax,"rangeslider":{"visible":False}}})
        fig.update_layout(**{f"yaxis{'' if i==1 else i}":{**ax}})
    if sr: fig.update_layout(**{f"yaxis{'' if rr==1 else rr}":{**ax,"range":[0,100]}})
    for ann in fig.layout.annotations: ann.font.color="#555"; ann.font.size=10
    return pyo.plot(fig,output_type="div",include_plotlyjs=False), None

# ══════════════════════════════════════════════════════════════════════════════
# HTML PAGE
# ══════════════════════════════════════════════════════════════════════════════
def render_page(ticker, period, chart_type, active_indicators, graph_html, error):
    chips  = "".join(f'<span class="{"chip active" if s==ticker else "chip"}" onclick="setTicker(\'{s}\')">{s}</span>' for s,_ in POPULAR_STOCKS)
    popts  = "".join(f'<option value="{v}" {"selected" if v==period else ""}>{lbl}</option>' for v,lbl in PERIODS)
    ichips = "".join(f'<span class="{"ind-chip active" if k in active_indicators else "ind-chip"}" data-ind="{k}" onclick="toggleInd(this)">{lbl}</span>' for k,lbl in INDICATORS)
    content = f'<div class="error-box">{error}</div>' if error else (graph_html or '<div class="empty-state">Enter a ticker above.</div>')
    ntabs  = "".join(f'<button class="{"news-tab active" if i==0 else "news-tab"}" data-handle="{ch["handle"]}">{ch["label"]} <span class="ntag">{ch["region"]}</span></button>' for i,ch in enumerate(NEWS_CHANNELS))
    rss_tabs = "".join(f'<button class="{"rss-tab active" if i==0 else "rss-tab"}" data-feed="{f["id"]}">{f["label"]}</button>' for i,f in enumerate(RSS_FEEDS))
    pipe_html = ""
    for i,m in enumerate(AI_MODELS):
        pipe_html += f'<div class="pipe-step" id="pipe-{m["key"]}"><div class="pipe-hdr"><span class="pipe-dot" style="background:{m["color"]}"></span><span class="pipe-model">{m["label"]}</span><span class="pipe-role">{m["role"]}</span><span class="pipe-status" id="ps-{m["key"]}">waiting</span></div><div class="pipe-body" id="pb-{m["key"]}"></div></div>'
        if i < len(AI_MODELS)-1: pipe_html += '<div class="pipe-arrow">↓</div>'
    fh = NEWS_CHANNELS[0]["handle"]
    models_js = json.dumps([{"id":m["id"],"key":m["key"],"label":m["label"],"color":m["color"]} for m in AI_MODELS])
    ai_inds_js = json.dumps(list(active_indicators))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>STARFISH — AI Market Oracle</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet"/>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{--bg:#060606;--sur:rgba(255,255,255,.04);--bdr:rgba(255,255,255,.09);--bds:rgba(255,255,255,.05);
      --tx:#f0f0f0;--txm:#666;--txd:#3a3a3a;--acc:#fff;--acm:rgba(255,255,255,.1);
      --blur:blur(20px);--r:16px;--rs:9px;--c1:#7c3aed;--c2:#0ea5e9;--c3:#f59e0b}}
body{{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--tx);min-height:100vh;-webkit-font-smoothing:antialiased;overflow-x:hidden}}
body::before{{content:'';position:fixed;inset:0;pointer-events:none;z-index:0;
  background:radial-gradient(ellipse 90% 55% at 15% 5%,rgba(124,58,237,.04) 0%,transparent 55%),
             radial-gradient(ellipse 55% 45% at 85% 85%,rgba(14,165,233,.03) 0%,transparent 50%)}}
header{{position:sticky;top:0;z-index:100;height:58px;display:flex;align-items:center;justify-content:space-between;
        padding:0 28px;background:rgba(6,6,6,.85);backdrop-filter:var(--blur);border-bottom:1px solid var(--bds)}}
.logo{{display:flex;align-items:center;gap:10px;font-family:'Syne',sans-serif;font-size:1rem;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--acc)}}
.logo-pip{{width:7px;height:7px;border-radius:50%;background:var(--acc);animation:blink 2.8s ease-in-out infinite}}
@keyframes blink{{0%,100%{{opacity:1;transform:scale(1)}}50%{{opacity:.2;transform:scale(.6)}}}}
.hdr-sub{{font-size:.65rem;color:var(--txd);letter-spacing:.1em;text-transform:uppercase;font-family:'DM Mono',monospace}}
main{{position:relative;z-index:1;max-width:1200px;margin:0 auto;padding:28px 20px 64px}}
.glass{{background:var(--sur);backdrop-filter:var(--blur);border:1px solid var(--bdr);border-radius:var(--r)}}
.panel{{padding:24px 28px;margin-bottom:16px}}
.plbl{{font-size:.58rem;font-weight:700;letter-spacing:.2em;text-transform:uppercase;color:var(--txd);margin-bottom:18px;font-family:'DM Mono',monospace}}
form{{display:grid;grid-template-columns:1.5fr 1fr 1fr auto;gap:12px;align-items:end}}
.fg label{{display:block;font-size:.65rem;font-weight:600;letter-spacing:.07em;text-transform:uppercase;color:var(--txm);margin-bottom:7px}}
input,select{{width:100%;background:rgba(255,255,255,.035);border:1px solid var(--bdr);border-radius:var(--rs);
              color:var(--tx);padding:10px 13px;font-size:.875rem;font-family:inherit;outline:none;
              transition:border-color .2s,background .2s;appearance:none;-webkit-appearance:none}}
input:focus,select:focus{{border-color:rgba(255,255,255,.28);background:rgba(255,255,255,.06);box-shadow:0 0 0 3px rgba(255,255,255,.04)}}
select{{cursor:pointer;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath fill='%23555' d='M5 6L0 0h10z'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 12px center;padding-right:32px}}
select option{{background:#111}}
.btn{{background:var(--acc);color:#000;border:none;border-radius:var(--rs);padding:10px 24px;font-size:.75rem;font-weight:700;font-family:inherit;cursor:pointer;letter-spacing:.1em;text-transform:uppercase;transition:opacity .18s,transform .12s;height:42px;white-space:nowrap}}
.btn:hover{{opacity:.85}}.btn:active{{transform:scale(.96)}}
.chips{{display:flex;flex-wrap:wrap;gap:6px;margin-top:18px;padding-top:16px;border-top:1px solid var(--bds)}}
.chip,.ind-chip,.rss-tab,.news-tab{{background:transparent;border:1px solid var(--bdr);border-radius:100px;
  padding:4px 13px;font-size:.68rem;font-family:'DM Mono',monospace;cursor:pointer;color:var(--txm);
  letter-spacing:.05em;transition:all .15s;user-select:none}}
.chip:hover,.ind-chip:hover,.rss-tab:hover,.news-tab:hover{{border-color:rgba(255,255,255,.3);color:var(--tx);background:var(--acm)}}
.chip.active,.news-tab.active{{background:var(--acc);border-color:var(--acc);color:#000;font-weight:700}}
.ind-chip.active{{background:rgba(255,255,255,.1);border-color:rgba(255,255,255,.32);color:var(--tx);font-weight:600}}
.rss-tab.active{{background:rgba(255,255,255,.08);border-color:rgba(255,255,255,.25);color:var(--tx);font-weight:600}}
.ind-row{{display:flex;flex-wrap:wrap;gap:6px;margin-top:14px;padding-top:14px;border-top:1px solid var(--bds);align-items:center}}
.ind-lbl{{font-size:.58rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--txd);margin-right:4px;font-family:'DM Mono',monospace}}
.chart-card{{padding:18px 14px 10px;min-height:460px;display:flex;align-items:flex-start;justify-content:center;overflow:hidden;margin-bottom:16px}}
.chart-card>div{{width:100%}}
.error-box{{border:1px solid rgba(255,255,255,.1);border-left:3px solid rgba(255,255,255,.4);border-radius:var(--rs);padding:14px 18px;color:#999;font-size:.85rem;background:rgba(255,255,255,.02);width:100%;line-height:1.6}}
.empty-state{{color:var(--txd);font-size:.85rem;text-align:center}}
.orch-panel{{padding:24px 28px;margin-bottom:16px}}
.orch-hdr{{display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:20px;gap:12px;flex-wrap:wrap}}
.orch-titles .ot{{font-family:'Syne',sans-serif;font-size:.95rem;font-weight:800;letter-spacing:.07em;text-transform:uppercase}}
.orch-titles .os{{font-size:.63rem;color:var(--txm);margin-top:3px}}
.btn-orch{{background:linear-gradient(135deg,rgba(124,58,237,.25),rgba(14,165,233,.2));border:1px solid rgba(124,58,237,.45);
           border-radius:var(--rs);color:var(--tx);padding:10px 22px;font-size:.72rem;font-weight:700;
           font-family:'DM Mono',monospace;cursor:pointer;letter-spacing:.1em;text-transform:uppercase;transition:all .2s}}
.btn-orch:hover{{background:linear-gradient(135deg,rgba(124,58,237,.4),rgba(14,165,233,.32));border-color:rgba(124,58,237,.7)}}
.btn-orch:active{{transform:scale(.96)}}.btn-orch:disabled{{opacity:.35;cursor:not-allowed;transform:none}}
.orch-lbl{{font-size:.62rem;font-family:'DM Mono',monospace;color:var(--txm);margin-top:6px}}
.pipeline{{display:flex;flex-direction:column;gap:0;margin-bottom:16px}}
.pipe-step{{border:1px solid var(--bdr);border-radius:11px;overflow:hidden;transition:border-color .3s,box-shadow .3s}}
.pipe-step.active{{border-color:rgba(255,255,255,.22);box-shadow:0 0 18px rgba(255,255,255,.03)}}
.pipe-step.done{{border-color:rgba(255,255,255,.13)}}
.pipe-hdr{{display:flex;align-items:center;gap:9px;padding:12px 16px;background:rgba(255,255,255,.02)}}
.pipe-dot{{width:7px;height:7px;border-radius:50%;flex-shrink:0}}
.pipe-model{{font-size:.77rem;font-weight:700;color:var(--tx);font-family:'DM Mono',monospace}}
.pipe-role{{font-size:.62rem;color:var(--txm);flex:1}}
.pipe-status{{font-size:.57rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;padding:2px 9px;border-radius:100px;
              background:rgba(255,255,255,.04);color:var(--txd);border:1px solid var(--bds);font-family:'DM Mono',monospace;transition:all .3s}}
.pipe-status.running{{background:rgba(255,196,0,.12);color:#ffc400;border-color:rgba(255,196,0,.3);animation:pb .9s ease-in-out infinite}}
.pipe-status.done{{background:rgba(38,166,154,.12);color:#26a69a;border-color:rgba(38,166,154,.3)}}
.pipe-status.error{{background:rgba(239,83,80,.12);color:#ef5350;border-color:rgba(239,83,80,.3)}}
@keyframes pb{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
.pipe-body{{max-height:0;overflow:hidden;transition:max-height .5s ease,padding .3s;padding:0 16px}}
.pipe-body.open{{max-height:500px;padding:12px 16px 16px}}
.pipe-arrow{{text-align:center;padding:5px 0;color:var(--txd);font-size:.85rem}}
.pv{{display:inline-flex;align-items:center;gap:8px;margin-bottom:9px}}
.pvb{{font-size:.7rem;font-weight:700;padding:3px 11px;border-radius:6px;letter-spacing:.09em;text-transform:uppercase}}
.BULLISH,.BUY{{background:rgba(38,166,154,.2);border:1px solid rgba(38,166,154,.4);color:#26a69a}}
.BEARISH,.SELL{{background:rgba(239,83,80,.2);border:1px solid rgba(239,83,80,.4);color:#ef5350}}
.NEUTRAL,.HOLD{{background:rgba(255,196,0,.12);border:1px solid rgba(255,196,0,.3);color:#ffc400}}
.pconf{{font-size:.63rem;color:var(--txm);font-family:'DM Mono',monospace}}
.ptxt{{font-size:.78rem;color:#bbb;line-height:1.75;white-space:pre-wrap;word-break:break-word}}
.spin-wrap{{display:flex;align-items:center;gap:10px;padding:8px 0}}
.spin{{width:18px;height:18px;border-radius:50%;border:2px solid rgba(255,255,255,.08);border-top-color:rgba(255,255,255,.45);animation:sp .7s linear infinite;flex-shrink:0}}
@keyframes sp{{to{{transform:rotate(360deg)}}}}
.spin-txt{{font-size:.73rem;color:var(--txm)}}
.fv{{display:none;margin-top:4px}}.fv.show{{display:block}}
.fv-card{{border:1px solid var(--bdr);border-radius:12px;overflow:hidden}}
.fv-top{{padding:18px 22px;background:rgba(255,255,255,.025);border-bottom:1px solid var(--bds);display:flex;align-items:center;gap:14px;flex-wrap:wrap}}
.fv-badge{{font-size:1rem;font-weight:800;letter-spacing:.14em;padding:9px 20px;border-radius:9px;text-transform:uppercase;font-family:'Syne',sans-serif}}
.fv-meta{{flex:1}}.fv-summary{{font-size:.86rem;color:var(--tx);line-height:1.5;font-weight:500;margin-bottom:5px}}
.fv-sub{{display:flex;gap:12px;flex-wrap:wrap}}.fv-mi{{font-size:.65rem;color:var(--txm)}}.fv-mi b{{color:var(--txd)}}
.agree-row{{display:flex;align-items:center;gap:10px;padding:12px 22px;border-bottom:1px solid var(--bds)}}
.agree-lbl{{font-size:.58rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--txd);font-family:'DM Mono',monospace;width:110px}}
.agree-track{{flex:1;height:5px;background:rgba(255,255,255,.06);border-radius:3px;overflow:hidden}}
.agree-fill{{height:100%;border-radius:3px;background:linear-gradient(90deg,var(--c1),var(--c2),var(--c3));transition:width .8s ease}}
.agree-pct{{font-size:.65rem;font-family:'DM Mono',monospace;color:var(--txm);width:34px;text-align:right}}
.fv-pts{{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--bds);border-bottom:1px solid var(--bds)}}
.fv-pt{{background:var(--bg);padding:12px 8px;text-align:center}}
.fv-pt-lbl{{font-size:.54rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--txd);margin-bottom:5px;font-family:'DM Mono',monospace}}
.fv-pt-val{{font-size:.85rem;font-weight:600;font-family:'DM Mono',monospace}}
.pt-e{{color:#fff}}.pt-sl{{color:#ef5350}}.pt-t1{{color:#26a69a}}.pt-t2{{color:#00BFFF}}.pt-t3{{color:#a78bfa}}
.fv-secs{{padding:0}}
.fv-sec{{padding:14px 20px;border-bottom:1px solid var(--bds)}}.fv-sec:last-child{{border-bottom:none}}
.fv-sec-hdr{{font-size:.55rem;font-weight:700;letter-spacing:.16em;text-transform:uppercase;color:var(--txd);margin-bottom:7px;font-family:'DM Mono',monospace}}
.fv-sec-body{{font-size:.79rem;color:#bbb;line-height:1.8;white-space:pre-wrap;word-break:break-word}}
.rss-panel{{padding:24px 28px;margin-bottom:16px}}
.rss-tabs{{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:14px}}
.rss-feed-list{{max-height:460px;overflow-y:auto;scrollbar-width:thin;scrollbar-color:rgba(255,255,255,.1) transparent}}
.rss-feed-list::-webkit-scrollbar{{width:4px}}.rss-feed-list::-webkit-scrollbar-thumb{{background:rgba(255,255,255,.1);border-radius:2px}}
.rss-item{{padding:12px 0;border-bottom:1px solid var(--bds);cursor:pointer}}
.rss-item:last-child{{border-bottom:none}}
.rss-item:hover .rss-title{{color:var(--acc)}}
.rss-meta{{display:flex;align-items:center;gap:7px;margin-bottom:4px}}
.rss-src{{font-size:.57rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--txd);font-family:'DM Mono',monospace}}
.rss-time{{font-size:.57rem;color:var(--txd);font-family:'DM Mono',monospace}}
.rss-title{{font-size:.8rem;color:#ccc;line-height:1.5;transition:color .15s}}
.rss-desc{{font-size:.7rem;color:var(--txm);line-height:1.5;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;margin-top:3px}}
.rss-loading{{display:flex;align-items:center;justify-content:center;gap:9px;padding:36px;color:var(--txm);font-size:.78rem}}
.news-panel{{padding:24px 28px;margin-bottom:16px}}
.live-dot{{display:inline-block;width:6px;height:6px;border-radius:50%;background:#ff4444;margin-right:5px;animation:lp 1.4s ease-in-out infinite;vertical-align:middle}}
@keyframes lp{{0%,100%{{opacity:1;transform:scale(1)}}50%{{opacity:.3;transform:scale(.6)}}}}
.ntabs{{display:flex;gap:7px;margin-bottom:18px;flex-wrap:wrap}}
.ntag{{font-size:.5rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;padding:1px 5px;border-radius:4px;background:rgba(255,255,255,.07);color:var(--txd);margin-left:3px}}
.iframe-wrap{{position:relative;width:100%;padding-top:56.25%;border-radius:var(--rs);overflow:hidden;background:rgba(0,0,0,.5)}}
.nload{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;flex-direction:column;gap:10px;color:var(--txm);font-size:.78rem}}
.iframe-wrap iframe{{position:absolute;inset:0;width:100%;height:100%;border:none}}
.nbadge{{display:none;margin-top:8px;font-size:.6rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;padding:3px 10px;border-radius:100px;width:fit-content}}
.nbadge.live{{background:rgba(255,60,60,.15);border:1px solid rgba(255,60,60,.35);color:#ff6b6b}}
.nbadge.latest{{background:rgba(255,255,255,.05);border:1px solid var(--bdr);color:var(--txm)}}
footer{{position:relative;z-index:1;text-align:center;padding:48px 20px 72px;border-top:1px solid rgba(255,255,255,.04)}}
.ft-sub{{font-size:.6rem;font-weight:700;letter-spacing:.26em;text-transform:uppercase;color:#2a2a2a;margin-bottom:12px;font-family:'DM Mono',monospace}}
.ft-name{{font-size:clamp(2.8rem,8vw,5.5rem);font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:#fff;line-height:1;font-family:'Syne',sans-serif}}
@media(max-width:860px){{form{{grid-template-columns:1fr 1fr}}.fg:first-child{{grid-column:span 2}}.btn{{grid-column:span 2;width:100%}}.fv-pts{{grid-template-columns:repeat(3,1fr)}}}}
@media(max-width:600px){{header{{padding:0 14px}}.hdr-sub{{display:none}}main{{padding:16px 12px 48px}}.panel,.orch-panel,.rss-panel,.news-panel{{padding:18px 16px}}.chart-card{{padding:14px 8px 8px;min-height:300px}}.fv-pts{{grid-template-columns:repeat(2,1fr)}}}}
</style>
</head>
<body>
<header>
  <div class="logo"><span class="logo-pip"></span>Starfish</div>
  <span class="hdr-sub">AI Market Oracle · Live Feeds</span>
</header>
<main>
<div class="glass panel">
  <div class="plbl">Search</div>
  <form method="POST" action="/" id="mf">
    <input type="hidden" name="indicators" id="inds-h" value="{','.join(active_indicators)}"/>
    <div class="fg"><label>Ticker Symbol</label><input name="ticker" value="{ticker}" placeholder="AAPL · TSLA · TCS.NS" required autocomplete="off" autocapitalize="characters" spellcheck="false"/></div>
    <div class="fg"><label>Time Range</label><select name="period">{popts}</select></div>
    <div class="fg"><label>Chart Type</label><select name="chart_type"><option value="candlestick" {"selected" if chart_type=="candlestick" else ""}>Candlestick</option><option value="line" {"selected" if chart_type=="line" else ""}>Line</option></select></div>
    <button type="submit" class="btn">Load</button>
  </form>
  <div class="chips">{chips}</div>
  <div class="ind-row"><span class="ind-lbl">Indicators</span>{ichips}</div>
</div>
<div class="glass chart-card">{content}</div>
<div class="glass orch-panel">
  <div class="orch-hdr">
    <div class="orch-titles"><div class="ot">3-AI Orchestration Pipeline</div><div class="os">DeepSeek R1 → Llama 3.3 → Qwen3 · Sequential · Auto-runs on load</div></div>
    <div><button class="btn-orch" id="btn-orch" onclick="runOrch()">▶ Run Analysis</button><div class="orch-lbl" id="orch-lbl"></div></div>
  </div>
  <div class="pipeline">{pipe_html}</div>
  <div class="fv" id="fv"></div>
</div>
<div class="glass rss-panel">
  <div class="plbl">Live RSS · Financial News</div>
  <div class="rss-tabs" id="rss-tabs">
    <button class="rss-tab active" data-feed="all" style="font-weight:700">All Sources</button>{rss_tabs}
  </div>
  <div class="rss-feed-list" id="rss-list"><div class="rss-loading"><div class="spin"></div>Loading headlines…</div></div>
</div>
<div class="glass news-panel">
  <div class="plbl"><span class="live-dot"></span>Live Financial TV</div>
  <div class="ntabs" id="ntabs">{ntabs}</div>
  <div class="iframe-wrap">
    <div class="nload" id="nload"><div class="spin"></div><span>Loading stream…</span></div>
    <iframe id="nframe" allow="accelerometer;autoplay;clipboard-write;encrypted-media;gyroscope;picture-in-picture" allowfullscreen style="display:none"></iframe>
  </div>
  <div class="nbadge" id="nbadge"></div>
</div>
</main>
<footer><div class="ft-sub">made by</div><div class="ft-name">ANTON BESKI</div></footer>
<script>
var TICKER={json.dumps(ticker)},PERIOD={json.dumps(period)};
var MODELS={models_js};
var orchRunning=false;
function setTicker(s){{document.querySelector('[name=ticker]').value=s;document.getElementById('mf').submit();}}
var aInds={ai_inds_js};
function toggleInd(el){{
  var k=el.dataset.ind,i=aInds.indexOf(k);
  i===-1?(aInds.push(k),el.classList.add('active')):(aInds.splice(i,1),el.classList.remove('active'));
  document.getElementById('inds-h').value=aInds.join(',');document.getElementById('mf').submit();
}}
function esc(s){{return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}}
function fn(v,d){{d=d===undefined?2:d;return(v==null||v==='')?'N/A':Number(v).toFixed(d);}}
function fmtDate(s){{if(!s)return'';try{{var d=new Date(s);return isNaN(d)?s.substring(0,16):d.toLocaleString('en-US',{{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}});}}catch(e){{return s.substring(0,16);}}}}
function setSt(key,st){{
  var el=document.getElementById('ps-'+key);
  if(el){{el.textContent=st;el.className='pipe-status '+(st==='running'?'running':st==='done'?'done':st==='error'?'error':'');}}
  var step=document.getElementById('pipe-'+key);
  if(step)step.className='pipe-step '+(st==='running'?'active':st==='done'||st==='error'?'done':'');
}}
function setSb(key,html,open){{var el=document.getElementById('pb-'+key);if(el){{el.innerHTML=html;el.className='pipe-body'+(open?' open':'');}}}}
function pvH(verdict,conf){{var v=(verdict||'NEUTRAL').toUpperCase();return '<div class="pv"><span class="pvb '+v+'">'+v+'</span><span class="pconf">Conf: '+esc(conf||'N/A')+'</span></div>';}}
function renderTech(r){{
  if(!r)return;var kl=r.key_levels||{{}};
  var h=pvH(r.technical_verdict,r.confidence_score);
  h+='<div class="ptxt">'+esc(r.technical_analysis||'')+'</div>';
  h+='<div style="margin-top:8px;display:flex;gap:14px;flex-wrap:wrap;font-size:.63rem;color:var(--txm);font-family:\'DM Mono\',monospace">';
  h+='<span>S1:'+fn(kl.support_1)+'</span><span>S2:'+fn(kl.support_2)+'</span><span>R1:'+fn(kl.resistance_1)+'</span><span>R2:'+fn(kl.resistance_2)+'</span>';
  if(r.pattern_detected)h+='<span>'+esc(r.pattern_detected)+'</span>';
  h+='</div>';setSb('deepseek',h,true);
}}
function renderMacro(r){{
  if(!r)return;var h=pvH(r.macro_verdict,r.macro_confidence_score);
  var hl=r.relevant_headlines||[];
  if(hl.length){{h+='<div style="margin-bottom:8px;display:flex;flex-direction:column;gap:3px">';hl.forEach(function(x){{h+='<div style="font-size:.68rem;color:#888;padding:2px 0 2px 9px;border-left:2px solid rgba(14,165,233,.4)">'+esc(x)+'</div>';}});h+='</div>';}}
  h+='<div class="ptxt">'+esc(r.news_impact||r.macro_environment||'')+'</div>';
  if(r.catalyst_ahead)h+='<div style="margin-top:7px;font-size:.7rem;color:#ffc400">⚡ '+esc(r.catalyst_ahead)+'</div>';
  setSb('llama',h,true);
}}
function renderSynth(r){{if(!r)return;var h=pvH(r.final_verdict,r.conviction);h+='<div class="ptxt">'+esc(r.orchestration_insight||r.prediction_summary||'')+'</div>';setSb('qwen',h,true);}}
function renderFinal(r){{
  if(!r)return;var v=(r.final_verdict||'HOLD').toUpperCase();var pt=r.price_targets||{{}};var agree=parseInt(r.agreement_score)||50;
  var secs=[{{lbl:'Orchestration Insight',k:'orchestration_insight'}},{{lbl:"Trader's Action Plan",k:'action_plan'}},{{lbl:'Key Risk',k:'key_risk'}}];
  var secH=secs.map(function(s){{return '<div class="fv-sec"><div class="fv-sec-hdr">'+esc(s.lbl)+'</div><div class="fv-sec-body">'+esc(r[s.k]||'No data.')+'</div></div>';}}).join('');
  var html='<div class="fv-card"><div class="fv-top"><div class="fv-badge '+v+'">'+v+'</div>'+
    '<div class="fv-meta"><div class="fv-summary">'+esc(r.prediction_summary||'')+'</div>'+
    '<div class="fv-sub"><span class="fv-mi"><b>Conviction&nbsp;</b>'+esc(r.conviction||'Med')+'</span>'+
    '<span class="fv-mi"><b>Horizon&nbsp;</b>'+esc(r.time_horizon||'Mid')+'</span>'+
    '<span class="fv-mi"><b>R/R&nbsp;</b>'+fn(r.risk_reward_ratio,1)+'x</span></div></div></div>'+
    '<div class="agree-row"><span class="agree-lbl">AI Agreement</span>'+
    '<div class="agree-track"><div class="agree-fill" style="width:0%" id="afill"></div></div>'+
    '<span class="agree-pct">'+agree+'%</span></div>'+
    '<div class="fv-pts">'+
    '<div class="fv-pt"><div class="fv-pt-lbl">Entry</div><div class="fv-pt-val pt-e">'+fn(pt.entry)+'</div></div>'+
    '<div class="fv-pt"><div class="fv-pt-lbl">Stop Loss</div><div class="fv-pt-val pt-sl">'+fn(pt.stop_loss)+'</div></div>'+
    '<div class="fv-pt"><div class="fv-pt-lbl">Target 1</div><div class="fv-pt-val pt-t1">'+fn(pt.target_1)+'</div></div>'+
    '<div class="fv-pt"><div class="fv-pt-lbl">Target 2</div><div class="fv-pt-val pt-t2">'+fn(pt.target_2)+'</div></div>'+
    '<div class="fv-pt"><div class="fv-pt-lbl">Target 3</div><div class="fv-pt-val pt-t3">'+fn(pt.target_3)+'</div></div>'+
    '</div><div class="fv-secs">'+secH+'</div></div>';
  var el=document.getElementById('fv');el.innerHTML=html;el.className='fv show';
  setTimeout(function(){{var f=document.getElementById('afill');if(f)f.style.width=agree+'%';}},120);
}}
function animateSteps(data){{
  var delay=0;
  MODELS.forEach(function(m,i){{
    setTimeout(function(){{setSt(m.key,'running');document.getElementById('orch-lbl').textContent=m.label+': thinking…';setSb(m.key,'<div class="spin-wrap"><div class="spin"></div><span class="spin-txt">'+esc(m.label)+' analysing…</span></div>',true);}},delay);
    delay+=1000;
    setTimeout(function(){{
      var step=data.steps&&data.steps[m.key];
      if(!step){{setSt(m.key,'error');return;}}
      if(step.status==='error'){{setSt(m.key,'error');setSb(m.key,'<div style="color:#ef5350;font-size:.75rem;padding:6px 0">'+esc(step.error||'Failed')+'</div>',true);}}
      else{{setSt(m.key,'done');if(m.key==='deepseek')renderTech(step.result);else if(m.key==='llama')renderMacro(step.result);else if(m.key==='qwen')renderSynth(step.result);}}
    }},delay);
    delay+=500;
  }});
  setTimeout(function(){{if(data.final)renderFinal(data.final);document.getElementById('orch-lbl').textContent='Analysis complete ✓';orchRunning=false;document.getElementById('btn-orch').disabled=false;document.getElementById('btn-orch').textContent='▶ Run Analysis';}},delay+200);
}}
function runOrch(){{
  if(orchRunning)return;orchRunning=true;
  var btn=document.getElementById('btn-orch');btn.disabled=true;btn.textContent='Running…';
  document.getElementById('orch-lbl').textContent='Fetching market data…';
  document.getElementById('fv').className='fv';
  MODELS.forEach(function(m){{setSt(m.key,'waiting');setSb(m.key,'',false);}});
  fetch('/api/orchestrate',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{ticker:TICKER,period:PERIOD}})}})
    .then(function(r){{return r.json().then(function(d){{if(!r.ok||d.error)throw new Error(d.error||'HTTP '+r.status);return d;}});}})
    .then(function(data){{document.getElementById('orch-lbl').textContent='Rendering…';animateSteps(data);}})
    .catch(function(err){{orchRunning=false;btn.disabled=false;btn.textContent='▶ Run Analysis';document.getElementById('orch-lbl').textContent='Error: '+err.message;}});
}}
var curFeed='all';
function loadRss(id){{
  curFeed=id;var c=document.getElementById('rss-list');
  c.innerHTML='<div class="rss-loading"><div class="spin"></div>Loading…</div>';
  fetch('/api/rss?feed='+encodeURIComponent(id)).then(function(r){{return r.json();}}).then(function(data){{
    if(!data.items||!data.items.length){{c.innerHTML='<div style="color:var(--txm);padding:20px;font-size:.8rem;text-align:center">No headlines available.</div>';return;}}
    var h='';data.items.forEach(function(it){{h+='<div class="rss-item" onclick="window.open(\''+esc(it.link||'#')+'\',\'_blank\')">';h+='<div class="rss-meta"><span class="rss-src">'+esc(it.source)+'</span>';if(it.pub)h+='<span class="rss-time">'+esc(fmtDate(it.pub))+'</span>';h+='</div><div class="rss-title">'+esc(it.title)+'</div>';if(it.desc)h+='<div class="rss-desc">'+esc(it.desc)+'</div>';h+='</div>';}});c.innerHTML=h;
  }}).catch(function(){{c.innerHTML='<div style="color:var(--txm);padding:20px;font-size:.8rem">Failed to load feed.</div>';}});
}}
document.getElementById('rss-tabs').addEventListener('click',function(e){{var b=e.target.closest('.rss-tab');if(!b)return;document.querySelectorAll('.rss-tab').forEach(function(t){{t.classList.remove('active');}});b.classList.add('active');loadRss(b.dataset.feed);}});
loadRss('all');setInterval(function(){{loadRss(curFeed);}},300000);
var nframe=document.getElementById('nframe'),nload=document.getElementById('nload'),nbadge=document.getElementById('nbadge'),curH=null;
function loadCh(h){{
  if(curH===h)return;curH=h;nframe.style.display='none';nload.style.display='flex';nload.innerHTML='<div class="spin"></div><span>Loading…</span>';nbadge.style.display='none';
  fetch('/api/live-id?handle='+encodeURIComponent(h)).then(function(r){{return r.json();}}).then(function(d){{
    if(h!==curH)return;if(!d.video_id){{nload.innerHTML='<span>Stream unavailable.</span>';return;}}
    nframe.src='https://www.youtube.com/embed/'+d.video_id+'?autoplay=1&rel=0&modestbranding=1';nframe.style.display='block';nload.style.display='none';
    nbadge.style.display='block';nbadge.className='nbadge '+(d.is_live?'live':'latest');nbadge.textContent=d.is_live?'● LIVE':'Latest Video';
  }}).catch(function(){{if(h===curH)nload.innerHTML='<span>Could not load.</span>';}});
}}
document.getElementById('ntabs').addEventListener('click',function(e){{var b=e.target.closest('.news-tab');if(!b)return;document.querySelectorAll('.news-tab').forEach(function(t){{t.classList.remove('active');}});b.classList.add('active');curH=null;loadCh(b.dataset.handle);}});
loadCh('{fh}');
setTimeout(runOrch,1500);
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
    active = set(filter(None, ind_raw.split(","))) if ind_raw else set(DEFAULT_INDICATORS)
    graph_html, error = build_chart(ticker, period, chart_type, active)
    return render_page(ticker, period, chart_type, active, graph_html, error)

@app.route("/api/orchestrate", methods=["POST"])
def api_orchestrate():
    body   = request.get_json(force=True) or {}
    ticker = (body.get("ticker","AAPL") or "AAPL").strip().upper()
    period = body.get("period","6mo")
    if period not in VALID_PERIODS: period = "6mo"
    steps  = {}; errors = []
    try:
        df, err = fetch_market_data(ticker, period)
        if err or df is None or df.empty:
            return jsonify({"error": err or "No data returned"}), 502
        name    = get_ticker_name(ticker)
        payload = build_analysis_payload(ticker, period, name, df)
    except Exception as e:
        return jsonify({"error": f"Setup error: {e}"}), 500
    try:    headlines = fetch_all_rss(20)
    except: headlines = []
    _FALLBACK_TECH  = {"technical_verdict":"NEUTRAL","technical_analysis":"Analysis unavailable.","technical_bias":"Unknown.","confidence_score":50,"key_levels":{},"indicator_signals":{},"pattern_detected":""}
    _FALLBACK_MACRO = {"macro_verdict":"NEUTRAL","macro_environment":"Analysis unavailable.","news_impact":"Unknown.","catalyst_ahead":"","macro_risk":"","macro_confidence_score":50,"relevant_headlines":[]}
    m1=AI_MODELS[0]; tech=None
    try:
        tech=call_openrouter(m1["id"],build_technical_prompt(payload)); steps[m1["key"]]={"status":"done","result":tech}
    except Exception as e:
        steps[m1["key"]]={"status":"error","error":str(e)}; errors.append(str(e)); tech=_FALLBACK_TECH
    m2=AI_MODELS[1]; macro=None
    try:
        macro=call_openrouter(m2["id"],build_macro_prompt(payload,tech,headlines)); steps[m2["key"]]={"status":"done","result":macro}
    except Exception as e:
        steps[m2["key"]]={"status":"error","error":str(e)}; errors.append(str(e)); macro=_FALLBACK_MACRO
    m3=AI_MODELS[2]; synth=None
    try:
        synth=call_openrouter(m3["id"],build_synthesis_prompt(payload,tech,macro)); steps[m3["key"]]={"status":"done","result":synth}
    except Exception as e:
        steps[m3["key"]]={"status":"error","error":str(e)}; errors.append(str(e))
    return jsonify({"ticker":ticker,"period":period,"steps":steps,"final":synth,"errors":errors})

@app.route("/api/rss")
def api_rss():
    feed_id=request.args.get("feed","all").strip()
    try:
        items=fetch_all_rss(40) if feed_id=="all" else fetch_rss(feed_id)
        return jsonify({"items":items})
    except Exception as e:
        return jsonify({"error":str(e),"items":[]}), 500

@app.route("/api/live-id")
def api_live_id():
    handle=request.args.get("handle","").strip()
    if not handle: return jsonify({"error":"missing handle"}),400
    vid,live=fetch_live_video_id(handle)
    if vid: return jsonify({"video_id":vid,"is_live":live})
    return jsonify({"error":"not found"}),404

@app.route("/api/rate-limits")
def api_rate_limits():
    return jsonify({m["key"]:{**rl_check(m["key"]),"rpm_reset_secs":0} for m in AI_MODELS})

@app.route("/debug")
def debug():
    out=[]; color="#7fff7f"
    try:
        df,err=fetch_market_data("AAPL","5d")
        if err: out.append(f"ERROR: {err}"); color="#ff7f7f"
        elif df is not None: out.append(f"OK shape:{df.shape}\n{df.tail(3).to_string()}")
        else: out.append("No data"); color="#ffaa44"
    except Exception: out.append(traceback.format_exc()); color="#ff7f7f"
    try:
        items=fetch_rss("reuters"); out.append(f"\nRSS Reuters:{len(items)} items")
        if items: out.append(f"First:{items[0]['title'][:80]}")
    except Exception as e: out.append(f"\nRSS error:{e}")
    return f"<pre style='background:#111;color:{color};padding:24px;font-family:monospace;white-space:pre-wrap'>{''.join(out)}</pre>"

@app.errorhandler(500)
def e500(e):
    return f"<pre style='background:#111;color:#aaa;padding:24px;font-family:monospace'>500\n\n{traceback.format_exc()}</pre>",500
