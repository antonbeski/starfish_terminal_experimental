#!/usr/bin/env python3
"""
STARFISH — Sector Intelligence Platform
Glassmorphic UI · Black / White / Red · OpenRouter AI Analysis
"""

import os
from flask import Flask, jsonify, request, render_template_string, Response, stream_with_context
import httpx
from bs4 import BeautifulSoup
from datetime import datetime
import re
import json
from urllib.parse import quote_plus
import time
import concurrent.futures

app = Flask(__name__)

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# ── Free OpenRouter models ────────────────────────────────────────────────────
FREE_MODELS = [
    {"id": "meta-llama/llama-3.3-70b-instruct:free",        "label": "Llama 3.3 70B",            "provider": "Meta"},
    {"id": "meta-llama/llama-3.1-8b-instruct:free",         "label": "Llama 3.1 8B",             "provider": "Meta"},
    {"id": "meta-llama/llama-3.2-3b-instruct:free",         "label": "Llama 3.2 3B",             "provider": "Meta"},
    {"id": "meta-llama/llama-3.2-1b-instruct:free",         "label": "Llama 3.2 1B",             "provider": "Meta"},
    {"id": "google/gemma-3-27b-it:free",                    "label": "Gemma 3 27B",              "provider": "Google"},
    {"id": "google/gemma-3-12b-it:free",                    "label": "Gemma 3 12B",              "provider": "Google"},
    {"id": "google/gemma-3-4b-it:free",                     "label": "Gemma 3 4B",               "provider": "Google"},
    {"id": "google/gemma-2-9b-it:free",                     "label": "Gemma 2 9B",               "provider": "Google"},
    {"id": "mistralai/mistral-7b-instruct:free",            "label": "Mistral 7B",               "provider": "Mistral AI"},
    {"id": "mistralai/mistral-small-3.1-24b-instruct:free", "label": "Mistral Small 3.1 24B",    "provider": "Mistral AI"},
    {"id": "deepseek/deepseek-r1:free",                     "label": "DeepSeek R1",              "provider": "DeepSeek"},
    {"id": "deepseek/deepseek-r1-zero:free",                "label": "DeepSeek R1 Zero",         "provider": "DeepSeek"},
    {"id": "deepseek/deepseek-v3-base:free",                "label": "DeepSeek V3 Base",         "provider": "DeepSeek"},
    {"id": "deepseek/deepseek-chat-v3-0324:free",           "label": "DeepSeek Chat V3",         "provider": "DeepSeek"},
    {"id": "qwen/qwen3-235b-a22b:free",                     "label": "Qwen3 235B",               "provider": "Alibaba"},
    {"id": "qwen/qwen3-32b:free",                           "label": "Qwen3 32B",                "provider": "Alibaba"},
    {"id": "qwen/qwen3-30b-a3b:free",                       "label": "Qwen3 30B MoE",            "provider": "Alibaba"},
    {"id": "qwen/qwen3-14b:free",                           "label": "Qwen3 14B",                "provider": "Alibaba"},
    {"id": "qwen/qwen3-8b:free",                            "label": "Qwen3 8B",                 "provider": "Alibaba"},
    {"id": "qwen/qwq-32b:free",                             "label": "QwQ 32B",                  "provider": "Alibaba"},
    {"id": "microsoft/phi-4:free",                          "label": "Phi-4",                    "provider": "Microsoft"},
    {"id": "microsoft/phi-4-reasoning:free",                "label": "Phi-4 Reasoning",          "provider": "Microsoft"},
    {"id": "microsoft/phi-4-reasoning-plus:free",           "label": "Phi-4 Reasoning Plus",     "provider": "Microsoft"},
    {"id": "microsoft/phi-4-multimodal-instruct:free",      "label": "Phi-4 Multimodal",         "provider": "Microsoft"},
    {"id": "tngtech/deepseek-r1t-chimera:free",             "label": "R1T Chimera",              "provider": "TNG Tech"},
    {"id": "nvidia/llama-3.1-nemotron-ultra-253b-v1:free",  "label": "Nemotron Ultra 253B",      "provider": "NVIDIA"},
    {"id": "nvidia/llama-3.3-nemotron-super-49b-v1:free",   "label": "Nemotron Super 49B",       "provider": "NVIDIA"},
    {"id": "moonshotai/kimi-vl-a3b-thinking:free",          "label": "Kimi VL A3B",              "provider": "Moonshot AI"},
]

# ── Sector configuration ──────────────────────────────────────────────────────
SECTORS = {
    "communication-services": {
        "label": "Communication Services", "sub": "Telecom · Media · Internet", "key": "XLC",
        "keywords": ["telecom","media","streaming","internet","AT&T","Netflix","Meta","Alphabet","Disney","Comcast","Verizon"],
        "queries": ["communication services sector stocks","telecom media internet stocks news"],
    },
    "consumer-discretionary": {
        "label": "Consumer Discretionary", "sub": "Retail · Autos · Leisure", "key": "XLY",
        "keywords": ["retail","auto","leisure","Amazon","Tesla","Nike","McDonald's","Booking","Home Depot"],
        "queries": ["consumer discretionary sector stocks news","retail auto leisure stocks"],
    },
    "consumer-staples": {
        "label": "Consumer Staples", "sub": "Food · Beverages · Essentials", "key": "XLP",
        "keywords": ["food","beverage","household","Procter Gamble","Coca-Cola","PepsiCo","Walmart","Costco","Unilever"],
        "queries": ["consumer staples sector stocks news","food beverage essentials stocks"],
    },
    "energy": {
        "label": "Energy", "sub": "Oil · Gas · Renewables", "key": "XLE",
        "keywords": ["oil","gas","energy","renewable","ExxonMobil","Chevron","Shell","BP","ConocoPhillips","pipeline"],
        "queries": ["energy sector stocks oil gas news","oil gas renewables stocks"],
    },
    "financials": {
        "label": "Financials", "sub": "Banks · Insurance · Fintech", "key": "XLF",
        "keywords": ["bank","insurance","fintech","JPMorgan","Visa","Mastercard","Goldman Sachs","Wells Fargo","Berkshire"],
        "queries": ["financial sector stocks banks insurance news","banks fintech stocks news"],
    },
    "health-care": {
        "label": "Health Care", "sub": "Pharma · Biotech · Hospitals", "key": "XLV",
        "keywords": ["pharma","biotech","hospital","Pfizer","UnitedHealth","Johnson","Merck","Abbott","Moderna","drug"],
        "queries": ["healthcare sector stocks pharma biotech news","pharma biotech hospital stocks"],
    },
    "industrials": {
        "label": "Industrials", "sub": "Aerospace · Machinery · Logistics", "key": "XLI",
        "keywords": ["aerospace","defense","machinery","logistics","Boeing","Caterpillar","Honeywell","UPS","Raytheon"],
        "queries": ["industrials sector stocks aerospace machinery news","defense logistics industrial stocks"],
    },
    "information-technology": {
        "label": "Information Technology", "sub": "Software · Hardware · Semiconductors", "key": "XLK",
        "keywords": ["software","hardware","semiconductor","chip","Apple","Microsoft","Nvidia","Intel","AMD","cloud","AI"],
        "queries": ["technology sector stocks software semiconductor news","software hardware chip stocks"],
    },
    "materials": {
        "label": "Materials", "sub": "Chemicals · Metals · Mining", "key": "XLB",
        "keywords": ["chemical","metal","mining","gold","Dow","Rio Tinto","Freeport","Newmont","Linde","commodity"],
        "queries": ["materials sector stocks chemicals metals mining news","mining metals commodities stocks"],
    },
    "real-estate": {
        "label": "Real Estate", "sub": "Property · REITs", "key": "XLRE",
        "keywords": ["REIT","property","real estate","Prologis","American Tower","Simon Property","Crown Castle","Equinix"],
        "queries": ["real estate sector REIT stocks news","property REIT stocks news"],
    },
    "utilities": {
        "label": "Utilities", "sub": "Power · Water · Gas", "key": "XLU",
        "keywords": ["power","electric","water","gas utility","NextEra","Duke Energy","Southern Company","Dominion","grid"],
        "queries": ["utilities sector stocks power water news","electric gas utility stocks news"],
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# ── Scrapers ──────────────────────────────────────────────────────────────────

def parse_relative_time(text):
    if not text: return ""
    text = text.strip()
    if re.match(r"\d{4}-\d{2}-\d{2}", text):
        try: return datetime.strptime(text[:10], "%Y-%m-%d").strftime("%b %d, %Y")
        except: return text
    return text[:60]

def _rss_scrape(url, source, sector_id, client):
    results = []
    try:
        r = client.get(url, timeout=8)
        soup = BeautifulSoup(r.text, "xml")
        keywords = [k.lower() for k in SECTORS[sector_id]["keywords"]]
        for item in soup.find_all("item"):
            title = item.find("title"); link = item.find("link"); pub_date = item.find("pubDate")
            if not title or not link: continue
            title_text = title.get_text(strip=True)
            if not any(kw in title_text.lower() for kw in keywords): continue
            href = link.get_text(strip=True)
            pub = pub_date.get_text(strip=True) if pub_date else ""
            try:
                dt = datetime.strptime(pub[:25], "%a, %d %b %Y %H:%M:%S")
                pub = dt.strftime("%b %d, %Y %H:%M")
            except: pub = pub[:30]
            results.append({"title": title_text, "url": href, "source": source, "published": pub, "sector": sector_id})
            if len(results) >= 8: break
    except: pass
    return results

def scrape_yahoo_finance(s, c): return _rss_scrape("https://finance.yahoo.com/news/rssindex","Yahoo Finance",s,c)
def scrape_cnbc(s, c): return _rss_scrape("https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664","CNBC",s,c)
def scrape_marketwatch(s, c): return _rss_scrape("https://feeds.marketwatch.com/marketwatch/topstories/","MarketWatch",s,c)
def scrape_benzinga(s, c): return _rss_scrape("https://www.benzinga.com/feeds/news","Benzinga",s,c)
def scrape_ft(s, c): return _rss_scrape("https://www.ft.com/rss/home/us","Financial Times",s,c)
def scrape_wsj(s, c): return _rss_scrape("https://feeds.a.dj.com/rss/RSSMarketsMain.xml","Wall Street Journal",s,c)

def scrape_reuters(sector_id, client):
    results = []
    try:
        query = quote_plus(SECTORS[sector_id]["queries"][0])
        r = client.get(f"https://www.reuters.com/search/news?blob={query}&sortBy=date&dateRange=pastMonth", timeout=8)
        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.select(".search-result-indiv, article")[:8]:
            a_tag = item.find("a", href=True)
            if not a_tag: continue
            title = a_tag.get_text(strip=True)
            href = a_tag["href"]
            if not href.startswith("http"): href = "https://www.reuters.com" + href
            time_tag = item.find("time")
            pub = time_tag.get("datetime", "") if time_tag else ""
            if title and len(title) > 20:
                results.append({"title": title, "url": href, "source": "Reuters", "published": parse_relative_time(pub), "sector": sector_id})
    except: pass
    return results

def scrape_seeking_alpha(sector_id, client):
    results = []
    try:
        etf = SECTORS[sector_id]["key"].lower()
        r = client.get(f"https://seekingalpha.com/symbol/{etf}/news", timeout=8)
        soup = BeautifulSoup(r.text, "html.parser")
        for art in soup.select("article, [data-test-id='post-list-item']")[:10]:
            a_tag = art.find("a", href=True)
            if not a_tag: continue
            title = a_tag.get_text(strip=True)
            href = a_tag["href"]
            if not href.startswith("http"): href = "https://seekingalpha.com" + href
            time_tag = art.find("time")
            pub = time_tag.get("datetime", "") if time_tag else ""
            if title and len(title) > 20:
                results.append({"title": title, "url": href, "source": "Seeking Alpha", "published": parse_relative_time(pub), "sector": sector_id})
    except: pass
    return results

def fetch_all_news(sector_id):
    scrapers = [scrape_yahoo_finance, scrape_cnbc, scrape_marketwatch,
                scrape_benzinga, scrape_ft, scrape_wsj, scrape_reuters, scrape_seeking_alpha]
    all_results = []
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=10) as client:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            for future in concurrent.futures.as_completed({executor.submit(fn, sector_id, client): fn for fn in scrapers}):
                try: all_results.extend(future.result())
                except: pass
    seen = set(); unique = []
    for item in all_results:
        key = re.sub(r"[^a-z0-9]", "", item["title"].lower())[:60]
        if key not in seen: seen.add(key); unique.append(item)
    unique.sort(key=lambda x: x.get("published", ""), reverse=True)
    return unique[:40]


# ── HTML ──────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>STARFISH &mdash; Sector Intelligence</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,600;0,700;0,800;1,700;1,800&family=Bebas+Neue&family=Archivo:wght@300;400;500;600;700;800;900&family=Archivo+Narrow:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --black:#000;--black-soft:#0c0c0c;--black-mid:#161616;
  --white:#fff;--white-dim:rgba(255,255,255,0.82);
  --red:#cc0000;--red-bright:#e60000;
  --red-dim:rgba(204,0,0,0.11);--red-border:rgba(204,0,0,0.28);
  --glass:rgba(255,255,255,0.032);--glass-hi:rgba(255,255,255,0.06);
  --gb:rgba(255,255,255,0.085);--gb-hi:rgba(255,255,255,0.15);
  --muted:rgba(255,255,255,0.36);--muted-mid:rgba(255,255,255,0.56);
}
html{-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale}
body{font-family:'Archivo',sans-serif;background:var(--black);color:var(--white);min-height:100vh;overflow-x:hidden}
body::before{
  content:'';position:fixed;inset:0;
  background:radial-gradient(ellipse 65% 50% at 15% 8%,rgba(160,0,0,0.14) 0%,transparent 55%),
             radial-gradient(ellipse 45% 45% at 85% 92%,rgba(90,0,0,0.09) 0%,transparent 50%),
             linear-gradient(160deg,#0a0a0a 0%,#000 100%);
  pointer-events:none;z-index:0;
}
body::after{
  content:'';position:fixed;inset:0;
  background-image:linear-gradient(rgba(255,255,255,0.014) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,0.014) 1px,transparent 1px);
  background-size:72px 72px;pointer-events:none;z-index:0;
}

/* ── HEADER ── */
header{
  position:sticky;top:0;z-index:500;height:60px;
  display:flex;align-items:center;justify-content:space-between;
  padding:0 clamp(1rem,4vw,2.5rem);
  background:rgba(0,0,0,0.82);
  backdrop-filter:blur(28px) saturate(180%);
  -webkit-backdrop-filter:blur(28px) saturate(180%);
  border-bottom:1px solid var(--gb);
}
.logo{display:flex;align-items:center;gap:7px}
.logo-text{font-family:'Bebas Neue',sans-serif;font-size:1.75rem;letter-spacing:4px;color:var(--white);line-height:1}
.logo-text em{color:var(--red);font-style:normal}
.logo-pulse{width:7px;height:7px;border-radius:50%;background:var(--red);animation:pulse 2.5s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:0.3;transform:scale(0.6)}}
.header-right{display:flex;align-items:center;gap:1rem}
.header-label{font-family:'Archivo Narrow',sans-serif;font-size:0.62rem;font-weight:600;letter-spacing:2.5px;text-transform:uppercase;color:var(--muted)}
@media(max-width:580px){.header-label{display:none}}
.badge-live{display:flex;align-items:center;gap:5px;font-family:'Archivo Narrow',sans-serif;font-size:0.6rem;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--red);background:var(--red-dim);border:1px solid var(--red-border);padding:0.22rem 0.65rem;border-radius:2px}
.badge-live::before{content:'';width:5px;height:5px;border-radius:50%;background:var(--red-bright);animation:blink 1.1s ease-in-out infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0.15}}

/* ── TICKER ── */
.ticker{position:relative;z-index:10;height:32px;overflow:hidden;display:flex;align-items:center;background:rgba(0,0,0,0.55);border-bottom:1px solid var(--gb)}
.ticker::before,.ticker::after{content:'';position:absolute;top:0;bottom:0;width:90px;z-index:2}
.ticker::before{left:0;background:linear-gradient(90deg,#000 30%,transparent)}
.ticker::after{right:0;background:linear-gradient(-90deg,#000 30%,transparent)}
.ticker-flag{position:absolute;left:0;height:100%;display:flex;align-items:center;padding:0 1rem;font-family:'Archivo Narrow',sans-serif;font-size:0.58rem;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;color:var(--red);background:#000;border-right:1px solid var(--gb);z-index:3;white-space:nowrap}
.ticker-track{display:flex;animation:ticker-scroll 50s linear infinite;padding-left:110px;white-space:nowrap}
.ticker-track:hover{animation-play-state:paused}
.t-item{font-family:'Archivo Narrow',sans-serif;font-size:0.67rem;font-weight:500;letter-spacing:1px;color:rgba(255,255,255,0.42);padding:0 2.25rem}
.t-item strong{color:rgba(255,255,255,0.82);font-weight:700}
.t-sep{color:rgba(204,0,0,0.6);padding:0 0.3rem}
@keyframes ticker-scroll{from{transform:translateX(100vw)}to{transform:translateX(-100%)}}

/* ── HERO ── */
.hero{position:relative;z-index:10;text-align:center;padding:clamp(3rem,8vw,6rem) clamp(1.25rem,5vw,3rem) clamp(2.5rem,6vw,4.5rem);border-bottom:1px solid var(--gb)}
.eyebrow{display:inline-flex;align-items:center;gap:0.8rem;font-family:'Archivo Narrow',sans-serif;font-size:0.68rem;font-weight:700;letter-spacing:4px;text-transform:uppercase;color:var(--red);margin-bottom:1.5rem}
.eyebrow::before,.eyebrow::after{content:'';height:1px;width:36px;background:linear-gradient(90deg,transparent,var(--red))}
.eyebrow::after{background:linear-gradient(-90deg,transparent,var(--red))}
.hero h1{font-family:'Cormorant Garamond',serif;font-size:clamp(3rem,9vw,7rem);font-weight:800;line-height:0.93;letter-spacing:-1.5px;color:var(--white);margin-bottom:1.5rem}
.hero h1 .hollow{color:transparent;-webkit-text-stroke:1.5px var(--red);font-style:italic}
.hero-desc{font-family:'Archivo',sans-serif;font-size:clamp(0.82rem,2vw,0.94rem);font-weight:400;color:var(--muted-mid);line-height:1.65;max-width:520px;margin:0 auto 3rem}

/* ── SELECTOR ── */
.selector{max-width:700px;margin:0 auto;display:flex;flex-direction:column;gap:1rem}
.select-box{display:flex;border:1px solid var(--gb-hi);border-radius:3px;overflow:hidden;background:rgba(255,255,255,0.03);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);transition:border-color .2s,box-shadow .2s}
.select-box:focus-within{border-color:rgba(204,0,0,0.45);box-shadow:0 0 0 3px rgba(204,0,0,0.07)}
.sel-label{display:flex;align-items:center;padding:0 1.1rem;font-family:'Archivo Narrow',sans-serif;font-size:0.62rem;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;color:var(--muted);white-space:nowrap;border-right:1px solid var(--gb);background:rgba(255,255,255,0.02)}
@media(max-width:480px){.sel-label{display:none}}
.sector-select,.model-select{flex:1;appearance:none;background:transparent;border:none;outline:none;padding:.95rem 3rem .95rem 1.2rem;font-family:'Archivo',sans-serif;font-size:.88rem;font-weight:600;color:var(--white);cursor:pointer;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='13' height='8' viewBox='0 0 13 8'%3E%3Cpath d='M1 1l5.5 5.5L12 1' stroke='%23cc0000' stroke-width='2' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 1.2rem center}
.sector-select option,.model-select option{background:#111;color:#fff;font-weight:500}
.go-btn{display:flex;align-items:center;gap:.5rem;padding:.95rem 1.6rem;background:var(--red);border:none;cursor:pointer;font-family:'Archivo Narrow',sans-serif;font-size:.72rem;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;color:#fff;white-space:nowrap;transition:background .18s,transform .1s;position:relative;overflow:hidden}
.go-btn::after{content:'';position:absolute;inset:0;background:linear-gradient(135deg,rgba(255,255,255,0.12),transparent);pointer-events:none}
.go-btn:hover{background:var(--red-bright)}.go-btn:active{transform:scale(.975)}.go-btn:disabled{opacity:.4;cursor:not-allowed}
.go-btn .arr{transition:transform .2s}.go-btn:not(:disabled):hover .arr{transform:translateX(3px)}
.sources-row{display:flex;align-items:center;justify-content:center;flex-wrap:wrap;gap:.4rem}
.src-label{font-family:'Archivo Narrow',sans-serif;font-size:.6rem;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-right:.3rem}
.src-tag{font-family:'Archivo Narrow',sans-serif;font-size:.6rem;font-weight:600;letter-spacing:.8px;text-transform:uppercase;color:rgba(255,255,255,0.28);border:1px solid rgba(255,255,255,0.07);padding:.18rem .55rem;border-radius:2px}
@media(max-width:480px){.sources-row{display:none}}

/* ── MAIN ── */
main{position:relative;z-index:10;max-width:1360px;margin:0 auto;padding:clamp(1.5rem,4vw,2.5rem) clamp(1rem,3vw,2rem) 5rem}

/* ── SECTOR TILE GRID ── */
.sector-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:1px;background:var(--gb);border:1px solid var(--gb);margin-top:.25rem}
.s-tile{background:var(--glass);backdrop-filter:blur(12px);padding:1.2rem;cursor:pointer;border:none;text-align:left;color:inherit;transition:background .15s}
.s-tile:hover{background:var(--glass-hi)}
.s-tile-key{font-family:'Bebas Neue',sans-serif;font-size:1.1rem;letter-spacing:2px;color:var(--red);display:block;margin-bottom:.3rem}
.s-tile-name{font-family:'Archivo',sans-serif;font-size:.75rem;font-weight:700;color:rgba(255,255,255,.82);display:block;line-height:1.3;margin-bottom:.2rem}
.s-tile-sub{font-family:'Archivo Narrow',sans-serif;font-size:.6rem;font-weight:500;letter-spacing:.5px;color:var(--muted);display:block}
@media(max-width:768px){.sector-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:420px){.sector-grid{grid-template-columns:1fr}}

/* ── RESULTS HEADER ── */
.res-header{display:flex;align-items:flex-end;justify-content:space-between;gap:1rem;margin-bottom:1.5rem;padding-bottom:1.25rem;border-bottom:1px solid var(--gb);flex-wrap:wrap}
.res-title{font-family:'Cormorant Garamond',serif;font-size:clamp(1.4rem,4vw,2.1rem);font-weight:700;line-height:1.1}
.res-title span{color:var(--red);font-style:italic}
.res-meta{display:flex;align-items:center;gap:.75rem;flex-wrap:wrap}
.res-count{font-family:'Archivo Narrow',sans-serif;font-size:.65rem;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--red);background:var(--red-dim);border:1px solid var(--red-border);padding:.28rem .7rem;border-radius:2px}
.res-time{font-family:'Archivo Narrow',sans-serif;font-size:.62rem;font-weight:500;letter-spacing:1.5px;text-transform:uppercase;color:var(--muted)}

/* ── FILTER PILLS ── */
.filter-row{display:flex;flex-wrap:wrap;gap:.45rem;margin-bottom:1.75rem;align-items:center}
.f-label{font-family:'Archivo Narrow',sans-serif;font-size:.6rem;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--muted);margin-right:.3rem}
.pill{font-family:'Archivo Narrow',sans-serif;font-size:.65rem;font-weight:600;letter-spacing:1px;text-transform:uppercase;padding:.33rem .85rem;border:1px solid var(--gb);border-radius:2px;background:var(--glass);color:rgba(255,255,255,.42);cursor:pointer;transition:all .15s;backdrop-filter:blur(8px)}
.pill:hover{border-color:rgba(255,255,255,.22);color:rgba(255,255,255,.78);background:var(--glass-hi)}
.pill.active{background:var(--red);border-color:var(--red);color:#fff}

/* ── NEWS GRID ── */
.news-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:1px;background:var(--gb);border:1px solid var(--gb)}
@media(max-width:660px){.news-grid{grid-template-columns:1fr}}
@media(min-width:1200px){.news-grid{grid-template-columns:repeat(3,1fr)}}

/* ── NEWS CARD ── */
@keyframes card-in{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
.card{background:var(--glass);backdrop-filter:blur(18px) saturate(140%);-webkit-backdrop-filter:blur(18px) saturate(140%);padding:1.4rem;display:flex;flex-direction:column;gap:.85rem;transition:background .18s;position:relative;overflow:hidden;min-height:175px;animation:card-in .4s ease both}
.card::before{content:'';position:absolute;top:0;left:0;width:2px;height:100%;background:var(--red);opacity:0;transition:opacity .2s}
.card:hover{background:var(--glass-hi)}.card:hover::before{opacity:1}
.card-head{display:flex;align-items:center;justify-content:space-between;gap:.5rem}
.card-src{font-family:'Archivo Narrow',sans-serif;font-size:.58rem;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--red);background:var(--red-dim);border:1px solid var(--red-border);padding:.16rem .55rem;border-radius:1px;white-space:nowrap}
.card-idx{font-family:'Bebas Neue',sans-serif;font-size:.7rem;letter-spacing:1px;color:rgba(255,255,255,.1)}
.card-title{font-family:'Archivo',sans-serif;font-size:.88rem;font-weight:700;line-height:1.48;color:rgba(255,255,255,.88);flex:1}
.card-title a{color:inherit;text-decoration:none;transition:color .15s;display:block}.card-title a:hover{color:var(--white)}
.card-foot{display:flex;align-items:center;justify-content:space-between;gap:.75rem;margin-top:auto;padding-top:.75rem;border-top:1px solid rgba(255,255,255,.05)}
.card-date{font-family:'Archivo Narrow',sans-serif;font-size:.62rem;font-weight:500;letter-spacing:.8px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.card-actions{display:flex;align-items:center;gap:.6rem;flex-shrink:0}
.card-link{font-family:'Archivo Narrow',sans-serif;font-size:.62rem;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:rgba(255,255,255,.35);text-decoration:none;transition:color .15s}
.card-link:hover{color:var(--red)}
.analyze-btn{font-family:'Archivo Narrow',sans-serif;font-size:.6rem;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:rgba(255,255,255,.35);background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);padding:.22rem .6rem;border-radius:1px;cursor:pointer;transition:all .15s;white-space:nowrap}
.analyze-btn:hover{background:var(--red-dim);border-color:var(--red-border);color:var(--red)}

/* ── AI ANALYSIS PANEL ── */
.ai-panel{
  position:fixed;top:0;right:0;bottom:0;
  width:min(480px,100vw);
  z-index:900;
  background:rgba(8,8,8,0.96);
  backdrop-filter:blur(32px) saturate(160%);
  -webkit-backdrop-filter:blur(32px) saturate(160%);
  border-left:1px solid var(--gb-hi);
  display:flex;flex-direction:column;
  transform:translateX(100%);
  transition:transform .35s cubic-bezier(.4,0,.2,1);
}
.ai-panel.open{transform:translateX(0)}

.panel-header{
  display:flex;align-items:center;justify-content:space-between;
  padding:1.25rem 1.5rem;
  border-bottom:1px solid var(--gb);
  flex-shrink:0;
}
.panel-title-wrap{display:flex;flex-direction:column;gap:.3rem}
.panel-label{font-family:'Archivo Narrow',sans-serif;font-size:.6rem;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:var(--red)}
.panel-title{font-family:'Cormorant Garamond',serif;font-size:1.25rem;font-weight:700;color:var(--white);line-height:1.2}
.panel-close{width:32px;height:32px;border:1px solid var(--gb-hi);border-radius:2px;background:var(--glass);cursor:pointer;display:flex;align-items:center;justify-content:center;color:var(--muted-mid);font-size:1.1rem;transition:all .15s;flex-shrink:0}
.panel-close:hover{border-color:var(--red-border);color:var(--white);background:var(--red-dim)}

.panel-article{
  padding:1rem 1.5rem;
  border-bottom:1px solid var(--gb);
  flex-shrink:0;
}
.article-src{font-family:'Archivo Narrow',sans-serif;font-size:.58rem;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--red);margin-bottom:.4rem}
.article-headline{font-family:'Archivo',sans-serif;font-size:.82rem;font-weight:700;color:rgba(255,255,255,.85);line-height:1.45}

/* ── Model selector in panel ── */
.model-row{padding:1rem 1.5rem;border-bottom:1px solid var(--gb);flex-shrink:0;display:flex;flex-direction:column;gap:.65rem}
.model-row-label{font-family:'Archivo Narrow',sans-serif;font-size:.6rem;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;color:var(--muted)}
.model-box{display:flex;border:1px solid var(--gb-hi);border-radius:3px;overflow:hidden;background:rgba(255,255,255,0.03)}
.model-box:focus-within{border-color:rgba(204,0,0,0.4)}
.model-select{font-size:.82rem;padding:.7rem 2.8rem .7rem 1rem}
.run-btn{display:flex;align-items:center;gap:.45rem;padding:.7rem 1.2rem;background:var(--red);border:none;cursor:pointer;font-family:'Archivo Narrow',sans-serif;font-size:.68rem;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:#fff;white-space:nowrap;transition:background .18s;flex-shrink:0}
.run-btn:hover{background:var(--red-bright)}.run-btn:disabled{opacity:.4;cursor:not-allowed}

/* ── Analysis output ── */
.panel-output{flex:1;overflow-y:auto;padding:1.25rem 1.5rem;display:flex;flex-direction:column;gap:1rem}
.panel-output::-webkit-scrollbar{width:4px}.panel-output::-webkit-scrollbar-track{background:transparent}.panel-output::-webkit-scrollbar-thumb{background:rgba(255,255,255,.12);border-radius:2px}

/* Analysis sections */
.a-section{display:flex;flex-direction:column;gap:.5rem}
.a-section-label{font-family:'Archivo Narrow',sans-serif;font-size:.6rem;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;color:var(--red);display:flex;align-items:center;gap:.5rem}
.a-section-label::after{content:'';flex:1;height:1px;background:linear-gradient(90deg,var(--red-border),transparent)}
.a-section-body{font-family:'Archivo',sans-serif;font-size:.82rem;font-weight:400;line-height:1.65;color:rgba(255,255,255,.78)}
.a-tag{display:inline-block;font-family:'Archivo Narrow',sans-serif;font-size:.6rem;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.1);color:rgba(255,255,255,.6);padding:.18rem .55rem;border-radius:2px;margin:.2rem .2rem 0 0}

/* Streaming cursor */
.stream-cursor{display:inline-block;width:2px;height:.9em;background:var(--red);margin-left:2px;animation:blink-cur .7s ease-in-out infinite;vertical-align:middle}
@keyframes blink-cur{0%,100%{opacity:1}50%{opacity:0}}

/* Panel states */
.panel-idle{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:1rem;text-align:center;padding:2rem;color:var(--muted)}
.panel-idle svg{width:40px;height:40px;stroke:rgba(255,255,255,.12);fill:none;stroke-width:1.2;stroke-linecap:round;stroke-linejoin:round}
.panel-idle-title{font-family:'Cormorant Garamond',serif;font-size:1.1rem;font-weight:700;color:rgba(255,255,255,.4)}
.panel-idle-sub{font-family:'Archivo',sans-serif;font-size:.78rem;color:rgba(255,255,255,.25);line-height:1.6;max-width:260px}

.panel-spinner{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;gap:.85rem}
.p-spinner{width:36px;height:36px;border:2px solid rgba(255,255,255,.07);border-top-color:var(--red);border-radius:50%;animation:spin .7s linear infinite}
.p-spin-label{font-family:'Archivo Narrow',sans-serif;font-size:.65rem;font-weight:600;letter-spacing:3px;text-transform:uppercase;color:var(--muted);animation:fp 1.6s ease-in-out infinite}
@keyframes fp{0%,100%{opacity:.3}50%{opacity:1}}
@keyframes spin{to{transform:rotate(360deg)}}

/* ── STATE BOXES ── */
.state{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:5rem 2rem;text-align:center;gap:1.2rem}
.state-icon{width:54px;height:54px;border:1px solid var(--gb);border-radius:50%;display:flex;align-items:center;justify-content:center;background:var(--glass)}
.state-icon svg{width:21px;height:21px;stroke:var(--muted-mid);fill:none;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}
.state-title{font-family:'Cormorant Garamond',serif;font-size:1.65rem;font-weight:700;color:rgba(255,255,255,.65)}
.state-sub{font-family:'Archivo',sans-serif;font-size:.83rem;font-weight:400;color:var(--muted);max-width:360px;line-height:1.65}
.spinner{width:42px;height:42px;border:2px solid rgba(255,255,255,.07);border-top-color:var(--red);border-radius:50%;animation:spin .7s linear infinite}
.spin-label{font-family:'Archivo Narrow',sans-serif;font-size:.67rem;font-weight:600;letter-spacing:3px;text-transform:uppercase;color:var(--muted);animation:fp 1.6s ease-in-out infinite}

/* ── FOOTER ── */
footer{position:relative;z-index:10;border-top:1px solid var(--gb);padding:1.75rem clamp(1rem,4vw,2.5rem);display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:.75rem;background:rgba(0,0,0,0.35)}
.f-brand{font-family:'Bebas Neue',sans-serif;font-size:.95rem;letter-spacing:3px;color:rgba(255,255,255,.18)}
.f-brand em{color:rgba(204,0,0,.45);font-style:normal}
.f-copy{font-family:'Archivo Narrow',sans-serif;font-size:.58rem;font-weight:500;letter-spacing:1.5px;text-transform:uppercase;color:rgba(255,255,255,.15)}
.f-srcs{font-family:'Archivo Narrow',sans-serif;font-size:.57rem;font-weight:500;letter-spacing:1px;text-transform:uppercase;color:rgba(255,255,255,.12)}
@media(max-width:768px){footer{flex-direction:column;text-align:center}.f-srcs{display:none}}

/* Panel overlay for mobile */
.panel-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:899;opacity:0;pointer-events:none;transition:opacity .3s}
.panel-overlay.show{opacity:1;pointer-events:auto}
</style>
</head>
<body>

<!-- AI Analysis Panel Overlay -->
<div class="panel-overlay" id="panelOverlay" onclick="closePanel()"></div>

<!-- AI Analysis Panel -->
<div class="ai-panel" id="aiPanel">
  <div class="panel-header">
    <div class="panel-title-wrap">
      <span class="panel-label">AI Analysis</span>
      <span class="panel-title" id="panelTitle">Select an article</span>
    </div>
    <button class="panel-close" onclick="closePanel()" title="Close">&#10005;</button>
  </div>

  <div class="panel-article" id="panelArticle" style="display:none">
    <div class="article-src" id="panelSrc"></div>
    <div class="article-headline" id="panelHeadline"></div>
  </div>

  <div class="model-row">
    <span class="model-row-label">Select Model</span>
    <div class="model-box">
      <select class="model-select" id="modelSelect">
        <optgroup label="Meta">
          <option value="meta-llama/llama-3.3-70b-instruct:free">Llama 3.3 70B</option>
          <option value="meta-llama/llama-3.1-8b-instruct:free">Llama 3.1 8B</option>
          <option value="meta-llama/llama-3.2-3b-instruct:free">Llama 3.2 3B</option>
          <option value="meta-llama/llama-3.2-1b-instruct:free">Llama 3.2 1B</option>
        </optgroup>
        <optgroup label="Google">
          <option value="google/gemma-3-27b-it:free">Gemma 3 27B</option>
          <option value="google/gemma-3-12b-it:free">Gemma 3 12B</option>
          <option value="google/gemma-3-4b-it:free">Gemma 3 4B</option>
          <option value="google/gemma-2-9b-it:free">Gemma 2 9B</option>
        </optgroup>
        <optgroup label="Mistral AI">
          <option value="mistralai/mistral-7b-instruct:free">Mistral 7B</option>
          <option value="mistralai/mistral-small-3.1-24b-instruct:free">Mistral Small 3.1 24B</option>
        </optgroup>
        <optgroup label="DeepSeek">
          <option value="deepseek/deepseek-r1:free">DeepSeek R1</option>
          <option value="deepseek/deepseek-r1-zero:free">DeepSeek R1 Zero</option>
          <option value="deepseek/deepseek-v3-base:free">DeepSeek V3 Base</option>
          <option value="deepseek/deepseek-chat-v3-0324:free">DeepSeek Chat V3</option>
        </optgroup>
        <optgroup label="Alibaba">
          <option value="qwen/qwen3-235b-a22b:free">Qwen3 235B</option>
          <option value="qwen/qwen3-32b:free">Qwen3 32B</option>
          <option value="qwen/qwen3-30b-a3b:free">Qwen3 30B MoE</option>
          <option value="qwen/qwen3-14b:free">Qwen3 14B</option>
          <option value="qwen/qwen3-8b:free">Qwen3 8B</option>
          <option value="qwen/qwq-32b:free">QwQ 32B</option>
        </optgroup>
        <optgroup label="Microsoft">
          <option value="microsoft/phi-4:free">Phi-4</option>
          <option value="microsoft/phi-4-reasoning:free">Phi-4 Reasoning</option>
          <option value="microsoft/phi-4-reasoning-plus:free">Phi-4 Reasoning Plus</option>
          <option value="microsoft/phi-4-multimodal-instruct:free">Phi-4 Multimodal</option>
        </optgroup>
        <optgroup label="NVIDIA">
          <option value="nvidia/llama-3.1-nemotron-ultra-253b-v1:free">Nemotron Ultra 253B</option>
          <option value="nvidia/llama-3.3-nemotron-super-49b-v1:free">Nemotron Super 49B</option>
        </optgroup>
        <optgroup label="Other">
          <option value="tngtech/deepseek-r1t-chimera:free">R1T Chimera</option>
          <option value="moonshotai/kimi-vl-a3b-thinking:free">Kimi VL A3B</option>
        </optgroup>
      </select>
      <button class="run-btn" id="runBtn" onclick="runAnalysis()">
        Analyse <span>&#8594;</span>
      </button>
    </div>
  </div>

  <div class="panel-output" id="panelOutput">
    <div class="panel-idle">
      <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
      <div class="panel-idle-title">Ready to Analyse</div>
      <div class="panel-idle-sub">Click "Analyse" on any news card, select a free AI model, then press Analyse to get a structured breakdown.</div>
    </div>
  </div>
</div>

<!-- Header -->
<header>
  <div class="logo">
    <span class="logo-text">STAR<em>FISH</em></span>
    <div class="logo-pulse"></div>
  </div>
  <div class="header-right">
    <span class="header-label">Sector Intelligence Platform</span>
    <div class="badge-live">Live</div>
  </div>
</header>

<!-- Ticker -->
<div class="ticker">
  <span class="ticker-flag">Markets</span>
  <div class="ticker-track">
    <span class="t-item"><strong>XLC</strong> Communication Services<span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLY</strong> Consumer Discretionary<span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLP</strong> Consumer Staples<span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLE</strong> Energy<span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLF</strong> Financials<span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLV</strong> Health Care<span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLI</strong> Industrials<span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLK</strong> Information Technology<span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLB</strong> Materials<span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLRE</strong> Real Estate<span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLU</strong> Utilities<span class="t-sep">&middot;</span></span>
    <span class="t-item">Reuters &middot; CNBC &middot; WSJ &middot; Yahoo Finance &middot; MarketWatch &middot; FT &middot; Benzinga &middot; Seeking Alpha<span class="t-sep">&middot;</span></span>
  </div>
</div>

<!-- Hero -->
<section class="hero">
  <div class="eyebrow">11 GICS Sectors &nbsp;&middot;&nbsp; 8 Premium Sources &nbsp;&middot;&nbsp; AI Analysis</div>
  <h1>Sector <span class="hollow">Intelligence</span><br>Aggregated Live</h1>
  <p class="hero-desc">Real-time financial news from Reuters, CNBC, WSJ, Yahoo Finance, MarketWatch, FT, Benzinga and Seeking Alpha &mdash; with AI-powered analysis by free OpenRouter models.</p>

  <div class="selector">
    <div class="select-box">
      <span class="sel-label">Sector</span>
      <select id="sector" class="sector-select">
        <option value="">Select a GICS Sector</option>
        <option value="communication-services">Communication Services &nbsp;&middot;&nbsp; XLC</option>
        <option value="consumer-discretionary">Consumer Discretionary &nbsp;&middot;&nbsp; XLY</option>
        <option value="consumer-staples">Consumer Staples &nbsp;&middot;&nbsp; XLP</option>
        <option value="energy">Energy &nbsp;&middot;&nbsp; XLE</option>
        <option value="financials">Financials &nbsp;&middot;&nbsp; XLF</option>
        <option value="health-care">Health Care &nbsp;&middot;&nbsp; XLV</option>
        <option value="industrials">Industrials &nbsp;&middot;&nbsp; XLI</option>
        <option value="information-technology">Information Technology &nbsp;&middot;&nbsp; XLK</option>
        <option value="materials">Materials &nbsp;&middot;&nbsp; XLB</option>
        <option value="real-estate">Real Estate &nbsp;&middot;&nbsp; XLRE</option>
        <option value="utilities">Utilities &nbsp;&middot;&nbsp; XLU</option>
      </select>
      <button class="go-btn" id="fetchBtn" onclick="fetchNews()">
        Fetch News <span class="arr">&#8594;</span>
      </button>
    </div>
    <div class="sources-row">
      <span class="src-label">Sources</span>
      <span class="src-tag">Reuters</span><span class="src-tag">CNBC</span><span class="src-tag">WSJ</span>
      <span class="src-tag">Yahoo Finance</span><span class="src-tag">MarketWatch</span>
      <span class="src-tag">FT</span><span class="src-tag">Benzinga</span><span class="src-tag">Seeking Alpha</span>
    </div>
  </div>
</section>

<!-- Output -->
<main>
  <div id="output">
    <div class="sector-grid">
      <button class="s-tile" onclick="selectAndFetch('communication-services')"><span class="s-tile-key">XLC</span><span class="s-tile-name">Communication Services</span><span class="s-tile-sub">Telecom &middot; Media &middot; Internet</span></button>
      <button class="s-tile" onclick="selectAndFetch('consumer-discretionary')"><span class="s-tile-key">XLY</span><span class="s-tile-name">Consumer Discretionary</span><span class="s-tile-sub">Retail &middot; Autos &middot; Leisure</span></button>
      <button class="s-tile" onclick="selectAndFetch('consumer-staples')"><span class="s-tile-key">XLP</span><span class="s-tile-name">Consumer Staples</span><span class="s-tile-sub">Food &middot; Beverages &middot; Essentials</span></button>
      <button class="s-tile" onclick="selectAndFetch('energy')"><span class="s-tile-key">XLE</span><span class="s-tile-name">Energy</span><span class="s-tile-sub">Oil &middot; Gas &middot; Renewables</span></button>
      <button class="s-tile" onclick="selectAndFetch('financials')"><span class="s-tile-key">XLF</span><span class="s-tile-name">Financials</span><span class="s-tile-sub">Banks &middot; Insurance &middot; Fintech</span></button>
      <button class="s-tile" onclick="selectAndFetch('health-care')"><span class="s-tile-key">XLV</span><span class="s-tile-name">Health Care</span><span class="s-tile-sub">Pharma &middot; Biotech &middot; Hospitals</span></button>
      <button class="s-tile" onclick="selectAndFetch('industrials')"><span class="s-tile-key">XLI</span><span class="s-tile-name">Industrials</span><span class="s-tile-sub">Aerospace &middot; Machinery &middot; Logistics</span></button>
      <button class="s-tile" onclick="selectAndFetch('information-technology')"><span class="s-tile-key">XLK</span><span class="s-tile-name">Information Technology</span><span class="s-tile-sub">Software &middot; Hardware &middot; Chips</span></button>
      <button class="s-tile" onclick="selectAndFetch('materials')"><span class="s-tile-key">XLB</span><span class="s-tile-name">Materials</span><span class="s-tile-sub">Chemicals &middot; Metals &middot; Mining</span></button>
      <button class="s-tile" onclick="selectAndFetch('real-estate')"><span class="s-tile-key">XLRE</span><span class="s-tile-name">Real Estate</span><span class="s-tile-sub">Property &middot; REITs</span></button>
      <button class="s-tile" onclick="selectAndFetch('utilities')"><span class="s-tile-key">XLU</span><span class="s-tile-name">Utilities</span><span class="s-tile-sub">Power &middot; Water &middot; Gas</span></button>
    </div>
  </div>
</main>

<footer>
  <div class="f-brand">STAR<em>FISH</em></div>
  <div class="f-copy">Sector Intelligence Platform &copy; 2024</div>
  <div class="f-srcs">Reuters &middot; CNBC &middot; WSJ &middot; Yahoo Finance &middot; MarketWatch &middot; FT &middot; Benzinga &middot; Seeking Alpha</div>
</footer>

<script>
let allArticles = [];
let currentArticle = null;

// ── News Fetching ──────────────────────────────────────────────────────────
function selectAndFetch(id) {
  document.getElementById('sector').value = id;
  fetchNews();
}

async function fetchNews() {
  const sector = document.getElementById('sector').value;
  if (!sector) { document.getElementById('sector').focus(); return; }
  const btn = document.getElementById('fetchBtn');
  btn.disabled = true;
  btn.innerHTML = '<span style="display:inline-block;width:11px;height:11px;border:2px solid rgba(255,255,255,0.25);border-top-color:#fff;border-radius:50%;animation:spin .6s linear infinite;vertical-align:middle;margin-right:6px"></span>Fetching';
  document.getElementById('output').innerHTML = `
    <div class="state">
      <div class="spinner"></div>
      <div class="state-title">Scanning Sources</div>
      <div class="state-sub">Retrieving live data from Reuters, CNBC, Wall Street Journal, Yahoo Finance, MarketWatch, Financial Times, Benzinga and Seeking Alpha.</div>
      <div class="spin-label">Please Wait</div>
    </div>`;
  try {
    const resp = await fetch('/api/news?sector=' + encodeURIComponent(sector));
    if (!resp.ok) throw new Error('Server error ' + resp.status);
    const data = await resp.json();
    allArticles = data.articles || [];
    renderNews(allArticles, data.sector_label, data.elapsed_seconds);
  } catch(e) {
    document.getElementById('output').innerHTML = `
      <div class="state">
        <div class="state-icon"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg></div>
        <div class="state-title">Request Failed</div>
        <div class="state-sub">${e.message}. Please try again.</div>
      </div>`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Fetch News <span class="arr">&#8594;</span>';
  }
}

function renderNews(articles, label, elapsed) {
  const sources = [...new Set(articles.map(a => a.source))].sort();
  const headerHtml = `
    <div class="res-header">
      <div class="res-title">Latest: <span>${label || ''}</span></div>
      <div class="res-meta">
        <span class="res-count">${articles.length} Articles</span>
        ${elapsed ? `<span class="res-time">${elapsed}s</span>` : ''}
      </div>
    </div>`;
  const filtersHtml = `
    <div class="filter-row">
      <span class="f-label">Filter</span>
      <button class="pill active" onclick="filterSource('all',this)">All</button>
      ${sources.map(s=>`<button class="pill" onclick="filterSource(${JSON.stringify(s)},this)">${s}</button>`).join('')}
    </div>`;
  if (!articles.length) {
    document.getElementById('output').innerHTML = headerHtml + filtersHtml + `
      <div class="state">
        <div class="state-icon"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg></div>
        <div class="state-title">No Articles Found</div>
        <div class="state-sub">No matching articles at this time. Try a different sector or refresh.</div>
      </div>`;
    return;
  }
  const cardsHtml = articles.map((a, i) => {
    const src   = (a.source||'').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    const title = (a.title ||'').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    const url   = (a.url   ||'#').replace(/"/g,'%22');
    const date  = (a.published||'Date unavailable').replace(/</g,'&lt;');
    const idx   = String(i+1).padStart(2,'0');
    const delay = Math.min(i * 0.035, 0.7);
    return `<div class="card" data-source="${src}" data-idx="${i}" style="animation-delay:${delay}s">
      <div class="card-head">
        <span class="card-src">${src}</span>
        <span class="card-idx">${idx}</span>
      </div>
      <div class="card-title"><a href="${url}" target="_blank" rel="noopener noreferrer">${title}</a></div>
      <div class="card-foot">
        <span class="card-date">${date}</span>
        <div class="card-actions">
          <button class="analyze-btn" onclick="openPanel(${i})">AI Analyse</button>
          <a class="card-link" href="${url}" target="_blank" rel="noopener noreferrer">Read &rsaquo;</a>
        </div>
      </div>
    </div>`;
  }).join('');
  document.getElementById('output').innerHTML = headerHtml + filtersHtml + `<div class="news-grid" id="newsGrid">${cardsHtml}</div>`;
}

function filterSource(source, btn) {
  document.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.card').forEach(c => {
    c.style.display = (source === 'all' || c.dataset.source === source) ? '' : 'none';
  });
}

document.getElementById('sector').addEventListener('change', function() { if (this.value) fetchNews(); });

// ── AI Panel ───────────────────────────────────────────────────────────────
function openPanel(idx) {
  currentArticle = allArticles[idx];
  if (!currentArticle) return;
  document.getElementById('panelSrc').textContent = currentArticle.source || '';
  document.getElementById('panelHeadline').textContent = currentArticle.title || '';
  document.getElementById('panelArticle').style.display = 'block';
  document.getElementById('panelTitle').textContent = 'AI Analysis';
  document.getElementById('panelOutput').innerHTML = `
    <div class="panel-idle">
      <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
      <div class="panel-idle-title">Ready to Analyse</div>
      <div class="panel-idle-sub">Select a model above and press Analyse to generate a structured breakdown of this article.</div>
    </div>`;
  document.getElementById('aiPanel').classList.add('open');
  document.getElementById('panelOverlay').classList.add('show');
  document.body.style.overflow = 'hidden';
}

function closePanel() {
  document.getElementById('aiPanel').classList.remove('open');
  document.getElementById('panelOverlay').classList.remove('show');
  document.body.style.overflow = '';
}

async function runAnalysis() {
  if (!currentArticle) return;
  const model = document.getElementById('modelSelect').value;
  const btn = document.getElementById('runBtn');
  btn.disabled = true;
  btn.textContent = 'Analysing...';

  document.getElementById('panelOutput').innerHTML = `
    <div class="panel-spinner">
      <div class="p-spinner"></div>
      <div class="p-spin-label">Analysing with AI</div>
    </div>`;

  try {
    const resp = await fetch('/api/analyse', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        title: currentArticle.title,
        source: currentArticle.source,
        published: currentArticle.published,
        url: currentArticle.url,
        model: model
      })
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({error: 'Unknown error'}));
      throw new Error(err.error || 'Server error ' + resp.status);
    }
    const data = await resp.json();
    renderAnalysis(data.analysis);
  } catch(e) {
    document.getElementById('panelOutput').innerHTML = `
      <div style="padding:1rem;font-family:'Archivo',sans-serif;font-size:.82rem;color:rgba(255,100,100,.8);line-height:1.6">
        <strong>Analysis failed:</strong> ${e.message}.<br><br>
        Check that OPENROUTER_API_KEY is set in your Vercel environment variables.
      </div>`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Analyse <span>&#8594;</span>';
  }
}

function renderAnalysis(analysis) {
  if (!analysis) {
    document.getElementById('panelOutput').innerHTML = '<div style="padding:1rem;color:var(--muted);font-family:\'Archivo\',sans-serif;font-size:.82rem">No analysis returned.</div>';
    return;
  }
  const sections = [
    { key: 'headline',      label: 'Headline Hook' },
    { key: 'what',          label: 'What' },
    { key: 'who',           label: 'Who' },
    { key: 'when_where',    label: 'When & Where' },
    { key: 'why_how',       label: 'Why & How' },
    { key: 'consequences',  label: 'Consequences & Impact' },
    { key: 'significance',  label: 'Why It Matters' },
    { key: 'reactions',     label: 'Reactions & Quotes' },
    { key: 'outlook',       label: 'Outlook' },
  ];
  let html = '';
  for (const s of sections) {
    const val = analysis[s.key];
    if (!val) continue;
    const escaped = String(val).replace(/</g,'&lt;').replace(/>/g,'&gt;');
    html += `<div class="a-section">
      <div class="a-section-label">${s.label}</div>
      <div class="a-section-body">${escaped}</div>
    </div>`;
  }
  if (!html) {
    const raw = typeof analysis === 'string' ? analysis : JSON.stringify(analysis, null, 2);
    html = `<div class="a-section"><div class="a-section-body" style="white-space:pre-wrap">${raw.replace(/</g,'&lt;')}</div></div>`;
  }
  document.getElementById('panelOutput').innerHTML = html;
}
</script>
</body>
</html>"""


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/news")
def api_news():
    sector_id = request.args.get("sector", "").strip()
    if sector_id not in SECTORS:
        return jsonify({"error": "Invalid sector", "articles": []}), 400
    t0 = time.time()
    articles = fetch_all_news(sector_id)
    elapsed = round(time.time() - t0, 2)
    return jsonify({
        "sector": sector_id,
        "sector_label": SECTORS[sector_id]["label"],
        "count": len(articles),
        "elapsed_seconds": elapsed,
        "articles": articles,
    })


@app.route("/api/analyse", methods=["POST"])
def api_analyse():
    if not OPENROUTER_API_KEY:
        return jsonify({"error": "OPENROUTER_API_KEY not configured in environment variables"}), 500

    body = request.get_json(silent=True) or {}
    title     = body.get("title", "").strip()
    source    = body.get("source", "").strip()
    published = body.get("published", "").strip()
    url       = body.get("url", "").strip()
    model     = body.get("model", "meta-llama/llama-3.3-70b-instruct:free").strip()

    if not title:
        return jsonify({"error": "No article title provided"}), 400

    prompt = f"""You are a financial news analyst. Analyse this news headline and return a JSON object with exactly these keys:

headline    — One sentence capturing the core hook.
what        — What happened? (1-2 sentences)
who         — Key people, companies, or organisations involved. (1 sentence)
when_where  — When and where this occurred. (1 sentence)
why_how     — The cause and method/process. (1-2 sentences)
consequences — Effects on markets, economy, or people. (2-3 sentences)
significance — Why this matters broadly. (1-2 sentences)
reactions   — Any notable reactions, statements, or market moves. (1-2 sentences, or "Not available")
outlook     — What to watch next. (1-2 sentences)

Article details:
Title: {title}
Source: {source}
Published: {published}
URL: {url}

Respond ONLY with valid JSON. No markdown, no code fences, no preamble. Just the JSON object."""

    try:
        with httpx.Client(timeout=45) as client:
            resp = client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://starfish-terminal.vercel.app",
                    "X-Title": "STARFISH Sector Intelligence",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 800,
                    "temperature": 0.3,
                }
            )
        resp.raise_for_status()
        data = resp.json()
        raw_content = data["choices"][0]["message"]["content"].strip()

        # Strip markdown fences if present
        raw_content = re.sub(r"^```[a-z]*\n?", "", raw_content)
        raw_content = re.sub(r"\n?```$", "", raw_content)
        raw_content = raw_content.strip()

        try:
            analysis = json.loads(raw_content)
        except json.JSONDecodeError:
            # Return raw text if not valid JSON
            analysis = {"headline": raw_content}

        return jsonify({"analysis": analysis, "model": model})

    except httpx.HTTPStatusError as e:
        err_body = e.response.text[:300]
        return jsonify({"error": f"OpenRouter API error {e.response.status_code}: {err_body}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("="*60)
    print("  STARFISH — Sector Intelligence Platform")
    print("  http://127.0.0.1:5000")
    print("="*60)
    print("\n  pip install flask httpx beautifulsoup4 lxml")
    print("  export OPENROUTER_API_KEY=sk-or-...\n")
    app.run(debug=True, host="0.0.0.0", port=5000)
