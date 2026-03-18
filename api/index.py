#!/usr/bin/env python3
"""
STARFISH — Sector Intelligence Platform
Light / White Primary · Premium Palette · OpenRouter AI Analysis
"""

import os
from flask import Flask, jsonify, request, render_template_string
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

SCRAPE_HEADERS = {
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
    with httpx.Client(headers=SCRAPE_HEADERS, follow_redirects=True, timeout=10) as client:
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
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,700;0,800;0,900;1,700;1,800&family=Syne:wght@600;700;800&family=DM+Sans:ital,wght@0,300;0,400;0,500;0,600;1,400&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
/* ── Reset & Base ── */
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;scroll-behavior:smooth}

:root {
  /* Core palette */
  --white:       #ffffff;
  --off-white:   #f7f6f3;
  --paper:       #f2f0eb;
  --paper-dark:  #e8e5de;
  --ink:         #0f0e0b;
  --ink-soft:    #1c1b18;
  --ink-mid:     #3a3830;
  --ink-light:   #6b6860;
  --ink-faint:   #9e9b95;

  /* Accent — warm amber-gold */
  --gold:        #c8860a;
  --gold-light:  #e8a020;
  --gold-dim:    rgba(200,134,10,0.10);
  --gold-border: rgba(200,134,10,0.25);

  /* Accent 2 — deep forest teal */
  --teal:        #1a6b5a;
  --teal-light:  #248c75;
  --teal-dim:    rgba(26,107,90,0.09);
  --teal-border: rgba(26,107,90,0.22);

  /* Accent 3 — slate blue for AI */
  --blue:        #2b4d8c;
  --blue-light:  #3b62b0;
  --blue-dim:    rgba(43,77,140,0.09);
  --blue-border: rgba(43,77,140,0.22);

  /* Surface & shadow */
  --card-bg:     #ffffff;
  --card-hover:  #fdfcf9;
  --border:      rgba(15,14,11,0.09);
  --border-mid:  rgba(15,14,11,0.14);
  --shadow-xs:   0 1px 2px rgba(15,14,11,0.06);
  --shadow-sm:   0 2px 8px rgba(15,14,11,0.08), 0 1px 2px rgba(15,14,11,0.05);
  --shadow-md:   0 4px 20px rgba(15,14,11,0.10), 0 2px 6px rgba(15,14,11,0.06);
  --shadow-lg:   0 12px 48px rgba(15,14,11,0.14), 0 4px 12px rgba(15,14,11,0.08);
  --shadow-panel:0 0 0 1px rgba(15,14,11,0.08), -8px 0 40px rgba(15,14,11,0.12);
}

body {
  font-family: 'DM Sans', sans-serif;
  background: var(--off-white);
  color: var(--ink);
  min-height: 100vh;
  overflow-x: hidden;
}

/* Subtle paper texture */
body::before {
  content: '';
  position: fixed;
  inset: 0;
  background:
    radial-gradient(ellipse 80% 60% at 70% 0%, rgba(200,134,10,0.055) 0%, transparent 55%),
    radial-gradient(ellipse 60% 50% at 0% 100%, rgba(26,107,90,0.045) 0%, transparent 50%);
  pointer-events: none;
  z-index: 0;
}

/* ── HEADER ── */
header {
  position: sticky; top: 0; z-index: 400;
  height: 62px;
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 clamp(1rem, 4vw, 2.5rem);
  background: rgba(247,246,243,0.88);
  backdrop-filter: blur(20px) saturate(160%);
  -webkit-backdrop-filter: blur(20px) saturate(160%);
  border-bottom: 1px solid var(--border-mid);
  box-shadow: var(--shadow-xs);
}

.logo { display: flex; align-items: center; gap: 8px; text-decoration: none; }
.logo-wordmark {
  font-family: 'Syne', sans-serif;
  font-size: 1.35rem; font-weight: 800;
  letter-spacing: -0.5px; color: var(--ink);
  line-height: 1;
}
.logo-wordmark em { color: var(--gold); font-style: normal; }
.logo-star {
  width: 26px; height: 26px;
  background: var(--ink);
  clip-path: polygon(50% 0%,61% 35%,98% 35%,68% 57%,79% 91%,50% 70%,21% 91%,32% 57%,2% 35%,39% 35%);
  position: relative;
  animation: star-spin 12s linear infinite;
}
.logo-star::after {
  content: '';
  position: absolute; inset: 4px;
  background: var(--gold);
  clip-path: polygon(50% 0%,61% 35%,98% 35%,68% 57%,79% 91%,50% 70%,21% 91%,32% 57%,2% 35%,39% 35%);
}
@keyframes star-spin { to { transform: rotate(360deg); } }

.header-center {
  display: flex; align-items: center; gap: 0.5rem;
}
.header-tag {
  font-family: 'DM Mono', monospace;
  font-size: 0.62rem; font-weight: 500;
  letter-spacing: 1.8px; text-transform: uppercase;
  color: var(--ink-faint);
}
@media(max-width:640px){.header-tag{display:none}}

.header-right { display: flex; align-items: center; gap: 0.75rem; }
.live-dot {
  display: flex; align-items: center; gap: 6px;
  font-family: 'DM Mono', monospace;
  font-size: 0.6rem; font-weight: 500; letter-spacing: 1.5px;
  text-transform: uppercase; color: var(--teal);
  background: var(--teal-dim); border: 1px solid var(--teal-border);
  padding: 0.22rem 0.7rem; border-radius: 20px;
}
.live-dot::before {
  content: ''; width: 5px; height: 5px; border-radius: 50%;
  background: var(--teal-light);
  animation: blink 1.3s ease-in-out infinite;
}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0.2}}

/* ── TICKER ── */
.ticker {
  position: relative; z-index: 10;
  height: 34px; overflow: hidden;
  display: flex; align-items: center;
  background: var(--ink);
  border-bottom: 2px solid var(--gold);
}
.ticker::before,.ticker::after {
  content:'';position:absolute;top:0;bottom:0;width:80px;z-index:2;
}
.ticker::before{left:0;background:linear-gradient(90deg,var(--ink) 40%,transparent)}
.ticker::after{right:0;background:linear-gradient(-90deg,var(--ink) 40%,transparent)}
.ticker-badge {
  position: absolute; left: 0; height: 100%; z-index: 3;
  display: flex; align-items: center; padding: 0 1rem;
  background: var(--gold); white-space: nowrap;
  font-family: 'Syne', sans-serif; font-size: 0.6rem; font-weight: 800;
  letter-spacing: 2px; text-transform: uppercase; color: var(--ink);
}
.ticker-track {
  display: flex; padding-left: 120px;
  animation: ticker-run 55s linear infinite; white-space: nowrap;
}
.ticker-track:hover { animation-play-state: paused; }
.t-item {
  font-family: 'DM Mono', monospace;
  font-size: 0.65rem; font-weight: 400; letter-spacing: 0.8px;
  color: rgba(255,255,255,0.45); padding: 0 1.75rem;
}
.t-item strong { color: rgba(255,255,255,0.88); font-weight: 500; }
.t-sep { color: var(--gold); opacity: 0.7; }
@keyframes ticker-run{from{transform:translateX(100vw)}to{transform:translateX(-100%)}}

/* ── HERO ── */
.hero {
  position: relative; z-index: 10;
  padding: clamp(3.5rem,8vw,6.5rem) clamp(1.25rem,5vw,3rem) clamp(3rem,6vw,5rem);
  text-align: center;
  background: linear-gradient(180deg, var(--off-white) 0%, var(--paper) 100%);
  border-bottom: 1px solid var(--border-mid);
  overflow: hidden;
}
/* Decorative grid */
.hero::before {
  content: '';
  position: absolute; inset: 0;
  background-image:
    linear-gradient(var(--border) 1px, transparent 1px),
    linear-gradient(90deg, var(--border) 1px, transparent 1px);
  background-size: 60px 60px;
  mask-image: radial-gradient(ellipse 80% 60% at 50% 0%, black 0%, transparent 70%);
  -webkit-mask-image: radial-gradient(ellipse 80% 60% at 50% 0%, black 0%, transparent 70%);
  pointer-events: none;
}

.hero-eyebrow {
  display: inline-flex; align-items: center; gap: 0.75rem;
  font-family: 'DM Mono', monospace; font-size: 0.68rem; font-weight: 500;
  letter-spacing: 2.5px; text-transform: uppercase;
  color: var(--gold); margin-bottom: 1.5rem;
}
.hero-eyebrow::before,.hero-eyebrow::after {
  content: ''; height: 1px; width: 32px;
  background: linear-gradient(90deg, transparent, var(--gold));
}
.hero-eyebrow::after { background: linear-gradient(-90deg, transparent, var(--gold)); }

.hero h1 {
  font-family: 'Playfair Display', serif;
  font-size: clamp(2.8rem, 8vw, 6.5rem);
  font-weight: 900; line-height: 0.95; letter-spacing: -2px;
  color: var(--ink); margin-bottom: 1.5rem;
}
.hero h1 .italic-accent {
  font-style: italic; color: var(--gold);
}
.hero h1 .outlined {
  color: transparent;
  -webkit-text-stroke: 2px var(--ink);
}

.hero-desc {
  font-family: 'DM Sans', sans-serif;
  font-size: clamp(0.88rem, 2vw, 1rem);
  font-weight: 400; line-height: 1.7;
  color: var(--ink-light); max-width: 560px; margin: 0 auto 3rem;
}

/* ── SELECTOR ── */
.selector-wrap {
  max-width: 720px; margin: 0 auto;
  display: flex; flex-direction: column; gap: 1rem;
}

.select-compound {
  display: flex;
  background: var(--white);
  border: 1.5px solid var(--border-mid);
  border-radius: 6px;
  box-shadow: var(--shadow-sm);
  overflow: hidden;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.select-compound:focus-within {
  border-color: var(--gold);
  box-shadow: 0 0 0 3px var(--gold-dim), var(--shadow-sm);
}

.sel-prefix {
  display: flex; align-items: center; padding: 0 1.1rem;
  font-family: 'DM Mono', monospace; font-size: 0.6rem; font-weight: 500;
  letter-spacing: 2px; text-transform: uppercase; color: var(--ink-faint);
  white-space: nowrap; border-right: 1px solid var(--border);
  background: var(--off-white); flex-shrink: 0;
}
@media(max-width:480px){.sel-prefix{display:none}}

.sector-select {
  flex: 1; appearance: none; background: transparent;
  border: none; outline: none;
  padding: 0.95rem 3rem 0.95rem 1.1rem;
  font-family: 'DM Sans', sans-serif; font-size: 0.92rem; font-weight: 600;
  color: var(--ink); cursor: pointer; min-width: 0;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='13' height='8' viewBox='0 0 13 8'%3E%3Cpath d='M1 1l5.5 5.5L12 1' stroke='%23c8860a' stroke-width='2' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
  background-repeat: no-repeat; background-position: right 1.1rem center;
}
.sector-select option { background: #fff; color: var(--ink); }

.fetch-btn {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.95rem 1.6rem; flex-shrink: 0;
  background: var(--ink); border: none; cursor: pointer;
  font-family: 'Syne', sans-serif; font-size: 0.72rem; font-weight: 700;
  letter-spacing: 1.5px; text-transform: uppercase; color: var(--white);
  transition: background 0.18s, transform 0.1s; white-space: nowrap;
}
.fetch-btn:hover { background: var(--gold); }
.fetch-btn:active { transform: scale(0.98); }
.fetch-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.fetch-btn .arr { transition: transform 0.2s; }
.fetch-btn:not(:disabled):hover .arr { transform: translateX(3px); }

.source-chips {
  display: flex; align-items: center; justify-content: center;
  flex-wrap: wrap; gap: 0.35rem;
}
.chips-label {
  font-family: 'DM Mono', monospace; font-size: 0.58rem; font-weight: 500;
  letter-spacing: 1.8px; text-transform: uppercase; color: var(--ink-faint);
  margin-right: 0.35rem;
}
.chip {
  font-family: 'DM Mono', monospace; font-size: 0.58rem; font-weight: 500;
  letter-spacing: 0.8px; text-transform: uppercase;
  color: var(--ink-light); background: var(--white);
  border: 1px solid var(--border-mid); padding: 0.18rem 0.6rem;
  border-radius: 20px;
}
@media(max-width:480px){.source-chips{display:none}}

/* ── MAIN ── */
main {
  position: relative; z-index: 10;
  max-width: 1400px; margin: 0 auto;
  padding: clamp(1.75rem,4vw,2.75rem) clamp(1rem,3vw,2rem) 5rem;
}

/* ── SECTOR TILES ── */
.sector-intro {
  display: flex; flex-direction: column; gap: 1.25rem;
}
.intro-heading {
  display: flex; align-items: baseline; gap: 1rem;
}
.intro-title {
  font-family: 'Playfair Display', serif;
  font-size: clamp(1.1rem,3vw,1.5rem); font-weight: 800;
  color: var(--ink);
}
.intro-sub {
  font-family: 'DM Mono', monospace; font-size: 0.65rem; font-weight: 500;
  letter-spacing: 1.5px; text-transform: uppercase; color: var(--ink-faint);
}

.sector-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(165px, 1fr));
  gap: 0.75rem;
}
.s-tile {
  background: var(--white); border: 1px solid var(--border);
  border-radius: 6px; padding: 1.1rem 1rem;
  cursor: pointer; text-align: left; color: inherit;
  box-shadow: var(--shadow-xs);
  transition: transform 0.15s, box-shadow 0.15s, border-color 0.15s;
  display: flex; flex-direction: column; gap: 0.3rem;
}
.s-tile:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
  border-color: var(--gold-border);
}
.s-tile-key {
  font-family: 'DM Mono', monospace; font-size: 0.65rem; font-weight: 500;
  letter-spacing: 1.5px; text-transform: uppercase;
  color: var(--gold); background: var(--gold-dim);
  border: 1px solid var(--gold-border);
  padding: 0.15rem 0.5rem; border-radius: 3px;
  display: inline-block; align-self: flex-start; margin-bottom: 0.3rem;
}
.s-tile-name {
  font-family: 'DM Sans', sans-serif; font-size: 0.82rem; font-weight: 700;
  color: var(--ink); line-height: 1.3;
}
.s-tile-sub {
  font-family: 'DM Sans', sans-serif; font-size: 0.68rem; font-weight: 400;
  color: var(--ink-faint); line-height: 1.3;
}
@media(max-width:768px){.sector-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:400px){.sector-grid{grid-template-columns:1fr}}

/* ── RESULTS HEADER ── */
.res-header {
  display: flex; align-items: flex-end; justify-content: space-between;
  gap: 1rem; margin-bottom: 1.5rem;
  padding-bottom: 1.25rem; border-bottom: 1.5px solid var(--border-mid);
  flex-wrap: wrap;
}
.res-title-block { display: flex; flex-direction: column; gap: 0.3rem; }
.res-eyebrow {
  font-family: 'DM Mono', monospace; font-size: 0.62rem; font-weight: 500;
  letter-spacing: 2px; text-transform: uppercase; color: var(--gold);
}
.res-title {
  font-family: 'Playfair Display', serif;
  font-size: clamp(1.4rem,4vw,2.2rem); font-weight: 800; line-height: 1.1;
  color: var(--ink);
}
.res-title em { font-style: italic; color: var(--gold); }
.res-meta { display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap; }
.res-count {
  font-family: 'DM Mono', monospace; font-size: 0.62rem; font-weight: 500;
  letter-spacing: 1.5px; text-transform: uppercase; color: var(--teal);
  background: var(--teal-dim); border: 1px solid var(--teal-border);
  padding: 0.28rem 0.75rem; border-radius: 20px;
}
.res-time {
  font-family: 'DM Mono', monospace; font-size: 0.6rem; font-weight: 500;
  letter-spacing: 1px; color: var(--ink-faint);
}

/* ── FILTER PILLS ── */
.filter-row {
  display: flex; flex-wrap: wrap; gap: 0.4rem;
  margin-bottom: 1.75rem; align-items: center;
}
.filter-label {
  font-family: 'DM Mono', monospace; font-size: 0.58rem; font-weight: 500;
  letter-spacing: 1.8px; text-transform: uppercase; color: var(--ink-faint);
  margin-right: 0.35rem;
}
.pill {
  font-family: 'DM Sans', sans-serif; font-size: 0.72rem; font-weight: 600;
  padding: 0.32rem 0.85rem;
  border: 1px solid var(--border-mid); border-radius: 20px;
  background: var(--white); color: var(--ink-light); cursor: pointer;
  transition: all 0.15s; box-shadow: var(--shadow-xs);
}
.pill:hover { border-color: var(--gold-border); color: var(--gold); background: var(--gold-dim); }
.pill.active { background: var(--ink); border-color: var(--ink); color: var(--white); box-shadow: var(--shadow-sm); }

/* ── NEWS GRID ── */
.news-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 1rem;
}
@media(max-width:680px){.news-grid{grid-template-columns:1fr}}
@media(min-width:1200px){.news-grid{grid-template-columns:repeat(3,1fr)}}

/* ── NEWS CARD ── */
@keyframes card-in{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}

.card {
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1.35rem;
  display: flex; flex-direction: column; gap: 0.85rem;
  box-shadow: var(--shadow-xs);
  transition: transform 0.18s, box-shadow 0.18s, border-color 0.18s;
  position: relative; overflow: hidden;
  animation: card-in 0.38s ease both;
}
.card::after {
  content: '';
  position: absolute; top: 0; left: 0;
  width: 100%; height: 2px;
  background: linear-gradient(90deg, var(--gold), var(--teal));
  opacity: 0; transition: opacity 0.2s;
}
.card:hover {
  transform: translateY(-3px);
  box-shadow: var(--shadow-md);
  border-color: var(--border-mid);
}
.card:hover::after { opacity: 1; }

.card-top {
  display: flex; align-items: flex-start;
  justify-content: space-between; gap: 0.75rem;
}
.card-src {
  font-family: 'DM Mono', monospace; font-size: 0.58rem; font-weight: 500;
  letter-spacing: 1.5px; text-transform: uppercase;
  color: var(--teal); background: var(--teal-dim);
  border: 1px solid var(--teal-border);
  padding: 0.16rem 0.55rem; border-radius: 3px; white-space: nowrap;
}
.card-num {
  font-family: 'DM Mono', monospace; font-size: 0.65rem; font-weight: 500;
  color: var(--ink-faint); flex-shrink: 0;
}

.card-title {
  font-family: 'DM Sans', sans-serif;
  font-size: 0.92rem; font-weight: 700; line-height: 1.5;
  color: var(--ink); flex: 1;
}
.card-title a {
  color: inherit; text-decoration: none; display: block;
  transition: color 0.15s;
}
.card-title a:hover { color: var(--gold); }

.card-footer {
  display: flex; align-items: center; justify-content: space-between;
  gap: 0.75rem; margin-top: auto;
  padding-top: 0.85rem;
  border-top: 1px solid var(--border);
}
.card-date {
  font-family: 'DM Mono', monospace; font-size: 0.62rem; font-weight: 400;
  color: var(--ink-faint); white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis;
}
.card-actions { display: flex; align-items: center; gap: 0.5rem; flex-shrink: 0; }
.card-read {
  font-family: 'DM Sans', sans-serif; font-size: 0.68rem; font-weight: 600;
  color: var(--ink-light); text-decoration: none;
  transition: color 0.15s;
}
.card-read:hover { color: var(--gold); }
.ai-btn {
  display: flex; align-items: center; gap: 0.3rem;
  font-family: 'DM Sans', sans-serif; font-size: 0.68rem; font-weight: 700;
  color: var(--white); background: var(--blue);
  border: none; padding: 0.28rem 0.7rem; border-radius: 4px;
  cursor: pointer; transition: background 0.15s, transform 0.1s;
  white-space: nowrap;
}
.ai-btn:hover { background: var(--blue-light); }
.ai-btn:active { transform: scale(0.97); }
.ai-btn svg { width: 11px; height: 11px; fill: currentColor; }

/* ── STATE BOXES ── */
.state {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; padding: 5rem 2rem;
  text-align: center; gap: 1.25rem;
}
.state-icon {
  width: 56px; height: 56px;
  border: 1.5px solid var(--border-mid); border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  background: var(--white); box-shadow: var(--shadow-sm);
}
.state-icon svg { width: 22px; height: 22px; stroke: var(--ink-faint); fill: none; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
.state-title { font-family: 'Playfair Display', serif; font-size: 1.6rem; font-weight: 800; color: var(--ink-mid); }
.state-sub { font-family: 'DM Sans', sans-serif; font-size: 0.88rem; color: var(--ink-faint); max-width: 380px; line-height: 1.65; }
.spinner { width: 40px; height: 40px; border: 2.5px solid var(--border-mid); border-top-color: var(--gold); border-radius: 50%; animation: spin 0.75s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.spin-label { font-family: 'DM Mono', monospace; font-size: 0.65rem; font-weight: 500; letter-spacing: 2.5px; text-transform: uppercase; color: var(--ink-faint); animation: pulse-label 1.6s ease-in-out infinite; }
@keyframes pulse-label { 0%,100%{opacity:0.4}50%{opacity:1} }

/* ── AI PANEL ── */
.panel-overlay {
  position: fixed; inset: 0; z-index: 500;
  background: rgba(15,14,11,0.4);
  opacity: 0; pointer-events: none;
  transition: opacity 0.3s;
  backdrop-filter: blur(2px);
  -webkit-backdrop-filter: blur(2px);
}
.panel-overlay.visible { opacity: 1; pointer-events: auto; }

.ai-panel {
  position: fixed; top: 0; right: 0; bottom: 0;
  width: min(500px, 100vw); z-index: 600;
  background: var(--white);
  box-shadow: var(--shadow-panel);
  display: flex; flex-direction: column;
  transform: translateX(100%);
  transition: transform 0.38s cubic-bezier(0.4,0,0.2,1);
  overflow: hidden;
}
.ai-panel.open { transform: translateX(0); }

/* Panel header */
.panel-hd {
  display: flex; align-items: center; justify-content: space-between;
  padding: 1.25rem 1.5rem;
  border-bottom: 1.5px solid var(--border-mid);
  background: var(--off-white); flex-shrink: 0;
}
.panel-hd-left { display: flex; flex-direction: column; gap: 0.2rem; }
.panel-hd-label {
  font-family: 'DM Mono', monospace; font-size: 0.58rem; font-weight: 500;
  letter-spacing: 2px; text-transform: uppercase;
  color: var(--blue); background: var(--blue-dim);
  border: 1px solid var(--blue-border); padding: 0.15rem 0.55rem;
  border-radius: 20px; display: inline-block; align-self: flex-start;
}
.panel-hd-title {
  font-family: 'Playfair Display', serif;
  font-size: 1.2rem; font-weight: 800; color: var(--ink);
}
.panel-close {
  width: 34px; height: 34px; border-radius: 6px;
  border: 1px solid var(--border-mid); background: var(--white);
  cursor: pointer; display: flex; align-items: center; justify-content: center;
  color: var(--ink-light); font-size: 1rem;
  transition: all 0.15s; box-shadow: var(--shadow-xs);
  flex-shrink: 0;
}
.panel-close:hover { background: var(--ink); color: var(--white); border-color: var(--ink); }

/* Article preview in panel */
.panel-article {
  padding: 1rem 1.5rem; border-bottom: 1px solid var(--border);
  background: var(--card-bg); flex-shrink: 0; display: none;
}
.panel-art-src {
  font-family: 'DM Mono', monospace; font-size: 0.58rem; font-weight: 500;
  letter-spacing: 1.5px; text-transform: uppercase;
  color: var(--teal); margin-bottom: 0.35rem;
}
.panel-art-title {
  font-family: 'DM Sans', sans-serif; font-size: 0.85rem; font-weight: 700;
  color: var(--ink); line-height: 1.45;
}

/* Model selector */
.panel-model {
  padding: 1rem 1.5rem; border-bottom: 1.5px solid var(--border-mid);
  background: var(--off-white); flex-shrink: 0;
  display: flex; flex-direction: column; gap: 0.6rem;
}
.panel-model-label {
  font-family: 'DM Mono', monospace; font-size: 0.58rem; font-weight: 500;
  letter-spacing: 2px; text-transform: uppercase; color: var(--ink-faint);
}
.model-row { display: flex; gap: 0; }
.model-select-wrap {
  display: flex; flex: 1;
  background: var(--white); border: 1.5px solid var(--border-mid);
  border-right: none; border-radius: 6px 0 0 6px;
  transition: border-color 0.2s;
  overflow: hidden;
}
.model-select-wrap:focus-within { border-color: var(--blue); }
.model-select {
  flex: 1; appearance: none; background: transparent;
  border: none; outline: none;
  padding: 0.75rem 2.8rem 0.75rem 1rem;
  font-family: 'DM Sans', sans-serif; font-size: 0.82rem; font-weight: 600;
  color: var(--ink); cursor: pointer; min-width: 0;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='7' viewBox='0 0 12 7'%3E%3Cpath d='M1 1l5 4.5L11 1' stroke='%232b4d8c' stroke-width='1.8' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
  background-repeat: no-repeat; background-position: right 1rem center;
}
.model-select option,.model-select optgroup { background: #fff; color: var(--ink); }
.run-btn {
  display: flex; align-items: center; gap: 0.45rem;
  padding: 0.75rem 1.35rem;
  background: var(--blue); border: 1.5px solid var(--blue);
  border-radius: 0 6px 6px 0; cursor: pointer;
  font-family: 'Syne', sans-serif; font-size: 0.7rem; font-weight: 700;
  letter-spacing: 1.5px; text-transform: uppercase;
  color: var(--white); white-space: nowrap;
  transition: background 0.18s; flex-shrink: 0;
}
.run-btn:hover { background: var(--blue-light); border-color: var(--blue-light); }
.run-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.run-btn .spin-sm {
  display: none; width: 13px; height: 13px;
  border: 2px solid rgba(255,255,255,0.3); border-top-color: #fff;
  border-radius: 50%; animation: spin 0.6s linear infinite;
}
.run-btn.loading .run-label { display: none; }
.run-btn.loading .spin-sm { display: block; }

/* Provider info line */
.model-info-row {
  display: flex; align-items: center; gap: 0.5rem;
}
.model-provider-badge {
  font-family: 'DM Mono', monospace; font-size: 0.58rem; font-weight: 500;
  letter-spacing: 1px; text-transform: uppercase;
  color: var(--blue); background: var(--blue-dim);
  border: 1px solid var(--blue-border);
  padding: 0.12rem 0.5rem; border-radius: 20px;
}
.model-id-text {
  font-family: 'DM Mono', monospace; font-size: 0.58rem;
  color: var(--ink-faint); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

/* ── Panel output ── */
.panel-body { flex: 1; overflow-y: auto; padding: 1.5rem; display: flex; flex-direction: column; gap: 0; }
.panel-body::-webkit-scrollbar { width: 4px; }
.panel-body::-webkit-scrollbar-track { background: transparent; }
.panel-body::-webkit-scrollbar-thumb { background: var(--border-mid); border-radius: 4px; }

/* Idle state */
.panel-idle {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; height: 100%; gap: 1rem; text-align: center; padding: 2rem;
}
.panel-idle-icon {
  width: 52px; height: 52px; border-radius: 12px;
  background: var(--off-white); border: 1.5px solid var(--border-mid);
  display: flex; align-items: center; justify-content: center;
  box-shadow: var(--shadow-sm);
}
.panel-idle-icon svg { width: 24px; height: 24px; stroke: var(--ink-faint); fill: none; stroke-width: 1.5; stroke-linecap: round; stroke-linejoin: round; }
.panel-idle-title { font-family: 'Playfair Display', serif; font-size: 1.1rem; font-weight: 800; color: var(--ink-mid); }
.panel-idle-sub { font-family: 'DM Sans', sans-serif; font-size: 0.8rem; color: var(--ink-faint); line-height: 1.65; max-width: 280px; }

/* Loading state */
.panel-loading {
  display: flex; flex-direction: column; align-items: center;
  justify-content: center; height: 100%; gap: 1rem;
}
.panel-loading .spinner { border-top-color: var(--blue); }
.panel-loading-label {
  font-family: 'DM Mono', monospace; font-size: 0.62rem; font-weight: 500;
  letter-spacing: 2px; text-transform: uppercase; color: var(--ink-faint);
  animation: pulse-label 1.5s ease-in-out infinite;
}
.panel-model-used {
  font-family: 'DM Mono', monospace; font-size: 0.58rem;
  color: var(--blue); background: var(--blue-dim);
  border: 1px solid var(--blue-border);
  padding: 0.18rem 0.65rem; border-radius: 20px;
}

/* Analysis sections */
.analysis-wrap { display: flex; flex-direction: column; gap: 1.1rem; }
.analysis-section {
  background: var(--off-white); border: 1px solid var(--border);
  border-radius: 8px; overflow: hidden;
  box-shadow: var(--shadow-xs);
  animation: card-in 0.3s ease both;
}
.section-header {
  display: flex; align-items: center; gap: 0.5rem;
  padding: 0.65rem 1rem;
  border-bottom: 1px solid var(--border);
  background: var(--paper);
}
.section-icon {
  width: 20px; height: 20px; border-radius: 4px;
  background: var(--white); border: 1px solid var(--border-mid);
  display: flex; align-items: center; justify-content: center; flex-shrink: 0;
  font-size: 0.55rem;
}
.section-label {
  font-family: 'Syne', sans-serif; font-size: 0.62rem; font-weight: 700;
  letter-spacing: 1.5px; text-transform: uppercase; color: var(--ink-mid);
}
.section-body {
  padding: 0.85rem 1rem;
  font-family: 'DM Sans', sans-serif; font-size: 0.82rem;
  font-weight: 400; line-height: 1.7; color: var(--ink-soft);
}

/* Error state */
.panel-error {
  margin: 1rem 0; padding: 1rem;
  background: #fff5f5; border: 1px solid rgba(200,0,0,0.15);
  border-radius: 8px; border-left: 3px solid #cc0000;
}
.panel-error-title {
  font-family: 'Syne', sans-serif; font-size: 0.7rem; font-weight: 700;
  letter-spacing: 1px; text-transform: uppercase; color: #cc0000;
  margin-bottom: 0.35rem;
}
.panel-error-msg {
  font-family: 'DM Sans', sans-serif; font-size: 0.8rem;
  color: var(--ink-mid); line-height: 1.55;
}
.panel-error-hint {
  margin-top: 0.5rem; font-family: 'DM Mono', monospace;
  font-size: 0.68rem; color: var(--ink-faint); line-height: 1.5;
}

/* ── FOOTER ── */
footer {
  position: relative; z-index: 10;
  border-top: 1px solid var(--border-mid);
  padding: 1.75rem clamp(1rem,4vw,2.5rem);
  background: var(--paper);
  display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: 0.75rem;
}
.f-brand {
  font-family: 'Syne', sans-serif; font-size: 0.9rem; font-weight: 800;
  letter-spacing: 1px; color: var(--ink-light);
}
.f-brand em { color: var(--gold); font-style: normal; }
.f-copy {
  font-family: 'DM Mono', monospace; font-size: 0.58rem; font-weight: 400;
  letter-spacing: 1px; text-transform: uppercase; color: var(--ink-faint);
}
.f-srcs {
  font-family: 'DM Mono', monospace; font-size: 0.56rem;
  letter-spacing: 0.8px; text-transform: uppercase; color: var(--ink-faint);
  opacity: 0.7;
}
@media(max-width:768px){footer{flex-direction:column;text-align:center}.f-srcs{display:none}}
</style>
</head>
<body>

<!-- Panel overlay -->
<div class="panel-overlay" id="panelOverlay" onclick="closePanel()"></div>

<!-- AI Analysis Panel -->
<div class="ai-panel" id="aiPanel">
  <!-- Header -->
  <div class="panel-hd">
    <div class="panel-hd-left">
      <span class="panel-hd-label">AI Analysis</span>
      <span class="panel-hd-title">News Intelligence</span>
    </div>
    <button class="panel-close" onclick="closePanel()" aria-label="Close panel">&#10005;</button>
  </div>

  <!-- Article preview -->
  <div class="panel-article" id="panelArticle">
    <div class="panel-art-src" id="panelSrc"></div>
    <div class="panel-art-title" id="panelHeadline"></div>
  </div>

  <!-- Model selector -->
  <div class="panel-model">
    <span class="panel-model-label">Select Model</span>
    <div class="model-row">
      <div class="model-select-wrap">
        <select class="model-select" id="modelSelect" onchange="updateModelInfo()">
          <optgroup label="Meta">
            <option value="meta-llama/llama-3.3-70b-instruct:free" data-provider="Meta">Llama 3.3 70B Instruct</option>
            <option value="meta-llama/llama-3.1-8b-instruct:free" data-provider="Meta">Llama 3.1 8B Instruct</option>
            <option value="meta-llama/llama-3.2-3b-instruct:free" data-provider="Meta">Llama 3.2 3B Instruct</option>
            <option value="meta-llama/llama-3.2-1b-instruct:free" data-provider="Meta">Llama 3.2 1B Instruct</option>
          </optgroup>
          <optgroup label="Google">
            <option value="google/gemma-3-27b-it:free" data-provider="Google">Gemma 3 27B</option>
            <option value="google/gemma-3-12b-it:free" data-provider="Google">Gemma 3 12B</option>
            <option value="google/gemma-3-4b-it:free" data-provider="Google">Gemma 3 4B</option>
            <option value="google/gemma-2-9b-it:free" data-provider="Google">Gemma 2 9B</option>
          </optgroup>
          <optgroup label="Mistral AI">
            <option value="mistralai/mistral-7b-instruct:free" data-provider="Mistral AI">Mistral 7B Instruct</option>
            <option value="mistralai/mistral-small-3.1-24b-instruct:free" data-provider="Mistral AI">Mistral Small 3.1 24B</option>
          </optgroup>
          <optgroup label="DeepSeek">
            <option value="deepseek/deepseek-r1:free" data-provider="DeepSeek">DeepSeek R1</option>
            <option value="deepseek/deepseek-r1-zero:free" data-provider="DeepSeek">DeepSeek R1 Zero</option>
            <option value="deepseek/deepseek-v3-base:free" data-provider="DeepSeek">DeepSeek V3 Base</option>
            <option value="deepseek/deepseek-chat-v3-0324:free" data-provider="DeepSeek">DeepSeek Chat V3</option>
          </optgroup>
          <optgroup label="Alibaba">
            <option value="qwen/qwen3-235b-a22b:free" data-provider="Alibaba">Qwen3 235B</option>
            <option value="qwen/qwen3-32b:free" data-provider="Alibaba">Qwen3 32B</option>
            <option value="qwen/qwen3-30b-a3b:free" data-provider="Alibaba">Qwen3 30B MoE</option>
            <option value="qwen/qwen3-14b:free" data-provider="Alibaba">Qwen3 14B</option>
            <option value="qwen/qwen3-8b:free" data-provider="Alibaba">Qwen3 8B</option>
            <option value="qwen/qwq-32b:free" data-provider="Alibaba">QwQ 32B</option>
          </optgroup>
          <optgroup label="Microsoft">
            <option value="microsoft/phi-4:free" data-provider="Microsoft">Phi-4</option>
            <option value="microsoft/phi-4-reasoning:free" data-provider="Microsoft">Phi-4 Reasoning</option>
            <option value="microsoft/phi-4-reasoning-plus:free" data-provider="Microsoft">Phi-4 Reasoning Plus</option>
            <option value="microsoft/phi-4-multimodal-instruct:free" data-provider="Microsoft">Phi-4 Multimodal</option>
          </optgroup>
          <optgroup label="NVIDIA">
            <option value="nvidia/llama-3.1-nemotron-ultra-253b-v1:free" data-provider="NVIDIA">Nemotron Ultra 253B</option>
            <option value="nvidia/llama-3.3-nemotron-super-49b-v1:free" data-provider="NVIDIA">Nemotron Super 49B</option>
          </optgroup>
          <optgroup label="Other">
            <option value="tngtech/deepseek-r1t-chimera:free" data-provider="TNG Tech">R1T Chimera</option>
            <option value="moonshotai/kimi-vl-a3b-thinking:free" data-provider="Moonshot AI">Kimi VL A3B</option>
          </optgroup>
        </select>
      </div>
      <button class="run-btn" id="runBtn" onclick="runAnalysis()">
        <span class="spin-sm"></span>
        <span class="run-label">Analyse</span>
      </button>
    </div>
    <div class="model-info-row">
      <span class="model-provider-badge" id="providerBadge">Meta</span>
      <span class="model-id-text" id="modelIdText">meta-llama/llama-3.3-70b-instruct:free</span>
    </div>
  </div>

  <!-- Output body -->
  <div class="panel-body" id="panelBody">
    <div class="panel-idle">
      <div class="panel-idle-icon">
        <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
      </div>
      <div class="panel-idle-title">Ready to Analyse</div>
      <div class="panel-idle-sub">Click "AI Analyse" on any article card, then select a free model and press Analyse.</div>
    </div>
  </div>
</div>

<!-- Header -->
<header>
  <a class="logo" href="/">
    <div class="logo-star"></div>
    <span class="logo-wordmark">STAR<em>FISH</em></span>
  </a>
  <div class="header-center">
    <span class="header-tag">Sector Intelligence Platform</span>
  </div>
  <div class="header-right">
    <span class="live-dot">Live</span>
  </div>
</header>

<!-- Ticker -->
<div class="ticker">
  <span class="ticker-badge">Markets</span>
  <div class="ticker-track">
    <span class="t-item"><strong>XLC</strong> Comm Services <span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLY</strong> Consumer Disc <span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLP</strong> Consumer Staples <span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLE</strong> Energy <span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLF</strong> Financials <span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLV</strong> Health Care <span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLI</strong> Industrials <span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLK</strong> Info Technology <span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLB</strong> Materials <span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLRE</strong> Real Estate <span class="t-sep">&middot;</span></span>
    <span class="t-item"><strong>XLU</strong> Utilities <span class="t-sep">&middot;</span></span>
    <span class="t-item">Reuters &middot; CNBC &middot; WSJ &middot; Yahoo Finance &middot; MarketWatch &middot; FT &middot; Benzinga &middot; Seeking Alpha <span class="t-sep">&middot;</span></span>
  </div>
</div>

<!-- Hero -->
<section class="hero">
  <div class="hero-eyebrow">11 GICS Sectors &nbsp;&middot;&nbsp; 8 Premium Sources &nbsp;&middot;&nbsp; AI Analysis</div>
  <h1>
    Sector<br>
    <span class="italic-accent">Intelligence</span>&nbsp;<span class="outlined">Aggregated</span>
  </h1>
  <p class="hero-desc">Real-time financial news from Reuters, CNBC, WSJ, Yahoo Finance, MarketWatch, Financial Times, Benzinga and Seeking Alpha &mdash; with AI-powered analysis using 27 free OpenRouter models.</p>

  <div class="selector-wrap">
    <div class="select-compound">
      <span class="sel-prefix">Sector</span>
      <select id="sector" class="sector-select">
        <option value="">Select a GICS Sector &mdash;</option>
        <option value="communication-services">Communication Services &middot; XLC</option>
        <option value="consumer-discretionary">Consumer Discretionary &middot; XLY</option>
        <option value="consumer-staples">Consumer Staples &middot; XLP</option>
        <option value="energy">Energy &middot; XLE</option>
        <option value="financials">Financials &middot; XLF</option>
        <option value="health-care">Health Care &middot; XLV</option>
        <option value="industrials">Industrials &middot; XLI</option>
        <option value="information-technology">Information Technology &middot; XLK</option>
        <option value="materials">Materials &middot; XLB</option>
        <option value="real-estate">Real Estate &middot; XLRE</option>
        <option value="utilities">Utilities &middot; XLU</option>
      </select>
      <button class="fetch-btn" id="fetchBtn" onclick="fetchNews()">
        Fetch News <span class="arr">&#8594;</span>
      </button>
    </div>
    <div class="source-chips">
      <span class="chips-label">Sources</span>
      <span class="chip">Reuters</span><span class="chip">CNBC</span>
      <span class="chip">WSJ</span><span class="chip">Yahoo Finance</span>
      <span class="chip">MarketWatch</span><span class="chip">FT</span>
      <span class="chip">Benzinga</span><span class="chip">Seeking Alpha</span>
    </div>
  </div>
</section>

<!-- Main -->
<main>
  <div id="output">
    <div class="sector-intro">
      <div class="intro-heading">
        <span class="intro-title">Browse by Sector</span>
        <span class="intro-sub">Click any sector to load live news</span>
      </div>
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
  </div>
</main>

<footer>
  <div class="f-brand">STAR<em>FISH</em></div>
  <div class="f-copy">Sector Intelligence Platform &copy; 2024</div>
  <div class="f-srcs">Reuters &middot; CNBC &middot; WSJ &middot; Yahoo Finance &middot; MarketWatch &middot; FT &middot; Benzinga &middot; Seeking Alpha</div>
</footer>

<script>
// ── State ──────────────────────────────────────────────────────────────────
let allArticles = [];
let currentArticle = null;

// ── Model info update ──────────────────────────────────────────────────────
function updateModelInfo() {
  const sel = document.getElementById('modelSelect');
  const opt = sel.options[sel.selectedIndex];
  document.getElementById('providerBadge').textContent = opt.dataset.provider || '';
  document.getElementById('modelIdText').textContent = sel.value;
}
updateModelInfo();

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
  btn.innerHTML = '<span style="display:inline-block;width:12px;height:12px;border:2px solid rgba(255,255,255,0.3);border-top-color:#fff;border-radius:50%;animation:spin .6s linear infinite;vertical-align:middle;margin-right:6px"></span>Fetching';

  document.getElementById('output').innerHTML = `
    <div class="state">
      <div class="spinner"></div>
      <div class="state-title">Scanning Sources</div>
      <div class="state-sub">Pulling live data from Reuters, CNBC, WSJ, Yahoo Finance, MarketWatch, FT, Benzinga and Seeking Alpha simultaneously.</div>
      <div class="spin-label">Please Wait</div>
    </div>`;

  try {
    const resp = await fetch('/api/news?sector=' + encodeURIComponent(sector));
    if (!resp.ok) throw new Error('Server responded with ' + resp.status);
    const data = await resp.json();
    allArticles = data.articles || [];
    renderNews(allArticles, data.sector_label, data.elapsed_seconds);
  } catch(e) {
    document.getElementById('output').innerHTML = `
      <div class="state">
        <div class="state-icon"><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg></div>
        <div class="state-title">Request Failed</div>
        <div class="state-sub">${escHtml(e.message)}. Please try again.</div>
      </div>`;
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Fetch News <span class="arr">&#8594;</span>';
  }
}

function renderNews(articles, label, elapsed) {
  const sources = [...new Set(articles.map(a => a.source))].sort();

  const header = `
    <div class="res-header">
      <div class="res-title-block">
        <span class="res-eyebrow">Live Results</span>
        <div class="res-title">Latest: <em>${escHtml(label || '')}</em></div>
      </div>
      <div class="res-meta">
        <span class="res-count">${articles.length} Articles</span>
        ${elapsed ? `<span class="res-time">${elapsed}s</span>` : ''}
      </div>
    </div>`;

  const filters = `
    <div class="filter-row">
      <span class="filter-label">Filter</span>
      <button class="pill active" onclick="filterBy('all',this)">All</button>
      ${sources.map(s => `<button class="pill" onclick="filterBy(${JSON.stringify(s)},this)">${escHtml(s)}</button>`).join('')}
    </div>`;

  if (!articles.length) {
    document.getElementById('output').innerHTML = header + filters + `
      <div class="state">
        <div class="state-icon"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg></div>
        <div class="state-title">No Articles Found</div>
        <div class="state-sub">No matching articles at this time. Try a different sector or refresh in a moment.</div>
      </div>`;
    return;
  }

  const cards = articles.map((a, i) => {
    const src   = escHtml(a.source || '');
    const title = escHtml(a.title  || '');
    const url   = (a.url || '#').replace(/"/g,'%22');
    const date  = escHtml(a.published || 'Date unavailable');
    const idx   = String(i+1).padStart(2,'0');
    const delay = Math.min(i * 0.032, 0.72);
    return `<div class="card" data-source="${src}" data-idx="${i}" style="animation-delay:${delay}s">
      <div class="card-top">
        <span class="card-src">${src}</span>
        <span class="card-num">${idx}</span>
      </div>
      <div class="card-title"><a href="${url}" target="_blank" rel="noopener noreferrer">${title}</a></div>
      <div class="card-footer">
        <span class="card-date">${date}</span>
        <div class="card-actions">
          <button class="ai-btn" onclick="openPanel(${i})" title="Analyse with AI">
            <svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 18a8 8 0 1 1 8-8 8 8 0 0 1-8 8zm1-13h-2v6l5.25 3.15.75-1.23-4-2.43z"/></svg>
            AI Analyse
          </button>
          <a class="card-read" href="${url}" target="_blank" rel="noopener noreferrer">Read &rsaquo;</a>
        </div>
      </div>
    </div>`;
  }).join('');

  document.getElementById('output').innerHTML = header + filters + `<div class="news-grid" id="newsGrid">${cards}</div>`;
}

function filterBy(source, btn) {
  document.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.card').forEach(c => {
    c.style.display = (source === 'all' || c.dataset.source === source) ? '' : 'none';
  });
}

document.getElementById('sector').addEventListener('change', function() {
  if (this.value) fetchNews();
});

// ── Panel ──────────────────────────────────────────────────────────────────
function openPanel(idx) {
  currentArticle = allArticles[idx];
  if (!currentArticle) return;

  document.getElementById('panelSrc').textContent = currentArticle.source || '';
  document.getElementById('panelHeadline').textContent = currentArticle.title || '';
  document.getElementById('panelArticle').style.display = 'block';

  // Reset to idle
  document.getElementById('panelBody').innerHTML = `
    <div class="panel-idle">
      <div class="panel-idle-icon">
        <svg viewBox="0 0 24 24"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
      </div>
      <div class="panel-idle-title">Ready to Analyse</div>
      <div class="panel-idle-sub">Select a model above and press Analyse to generate a structured breakdown of this article.</div>
    </div>`;

  document.getElementById('aiPanel').classList.add('open');
  document.getElementById('panelOverlay').classList.add('visible');
  document.body.style.overflow = 'hidden';
}

function closePanel() {
  document.getElementById('aiPanel').classList.remove('open');
  document.getElementById('panelOverlay').classList.remove('visible');
  document.body.style.overflow = '';
}

// Close on Escape
document.addEventListener('keydown', e => { if (e.key === 'Escape') closePanel(); });

async function runAnalysis() {
  if (!currentArticle) return;

  const modelId = document.getElementById('modelSelect').value;
  const modelOpt = document.getElementById('modelSelect').options[document.getElementById('modelSelect').selectedIndex];
  const provider = modelOpt.dataset.provider || '';
  const modelName = modelOpt.text || modelId;

  const btn = document.getElementById('runBtn');
  btn.disabled = true;
  btn.classList.add('loading');

  document.getElementById('panelBody').innerHTML = `
    <div class="panel-loading">
      <div class="spinner"></div>
      <div class="panel-loading-label">Analysing Article</div>
      <span class="panel-model-used">${escHtml(modelName)}</span>
    </div>`;

  try {
    const resp = await fetch('/api/analyse', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        title:     currentArticle.title     || '',
        source:    currentArticle.source    || '',
        published: currentArticle.published || '',
        url:       currentArticle.url       || '',
        model:     modelId
      })
    });

    const data = await resp.json();

    if (!resp.ok) {
      throw new Error(data.error || 'Server error ' + resp.status);
    }

    renderAnalysis(data.analysis, modelName, provider);

  } catch(e) {
    document.getElementById('panelBody').innerHTML = `
      <div class="panel-error">
        <div class="panel-error-title">Analysis Failed</div>
        <div class="panel-error-msg">${escHtml(e.message)}</div>
        <div class="panel-error-hint">Ensure OPENROUTER_API_KEY is set in your Vercel environment variables. Get a free key at openrouter.ai</div>
      </div>`;
  } finally {
    btn.disabled = false;
    btn.classList.remove('loading');
  }
}

// Section metadata
const SECTIONS = [
  { key: 'headline',     label: 'Headline Hook',         icon: '&#9670;' },
  { key: 'what',         label: 'What',                  icon: '&#9632;' },
  { key: 'who',          label: 'Who',                   icon: '&#9675;' },
  { key: 'when_where',   label: 'When &amp; Where',      icon: '&#9671;' },
  { key: 'why_how',      label: 'Why &amp; How',         icon: '&#9634;' },
  { key: 'consequences', label: 'Consequences &amp; Impact', icon: '&#9650;' },
  { key: 'significance', label: 'Why It Matters',        icon: '&#9679;' },
  { key: 'reactions',    label: 'Reactions',             icon: '&#9826;' },
  { key: 'outlook',      label: 'Outlook',               icon: '&#9658;' },
];

function renderAnalysis(analysis, modelName, provider) {
  if (!analysis) {
    document.getElementById('panelBody').innerHTML = `<div class="panel-error"><div class="panel-error-title">No Output</div><div class="panel-error-msg">The model returned an empty response. Try a different model.</div></div>`;
    return;
  }

  let html = `<div class="analysis-wrap">`;

  // Model credit
  html += `<div style="display:flex;align-items:center;gap:.5rem;padding:.5rem 0 .75rem;border-bottom:1px solid var(--border);margin-bottom:.25rem">
    <span class="model-provider-badge">${escHtml(provider)}</span>
    <span class="model-id-text">${escHtml(modelName)}</span>
  </div>`;

  let rendered = 0;
  for (const s of SECTIONS) {
    const val = analysis[s.key];
    if (!val || String(val).trim() === '' || String(val).toLowerCase() === 'not available') continue;
    const body = escHtml(String(val).trim());
    html += `<div class="analysis-section" style="animation-delay:${rendered * 0.06}s">
      <div class="section-header">
        <div class="section-icon">${s.icon}</div>
        <span class="section-label">${s.label}</span>
      </div>
      <div class="section-body">${body}</div>
    </div>`;
    rendered++;
  }

  // Fallback: if no structured sections matched, show raw
  if (rendered === 0) {
    const raw = typeof analysis === 'string' ? analysis : JSON.stringify(analysis, null, 2);
    html += `<div class="analysis-section">
      <div class="section-header"><div class="section-icon">&#9632;</div><span class="section-label">Raw Output</span></div>
      <div class="section-body" style="white-space:pre-wrap;font-family:'DM Mono',monospace;font-size:.75rem">${escHtml(raw)}</div>
    </div>`;
  }

  html += `</div>`;
  document.getElementById('panelBody').innerHTML = html;
  // Scroll to top
  document.getElementById('panelBody').scrollTop = 0;
}

function escHtml(str) {
  return String(str)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;')
    .replace(/'/g,'&#39;');
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
    # Check API key first
    if not OPENROUTER_API_KEY:
        return jsonify({
            "error": "OPENROUTER_API_KEY is not configured. Add it to your Vercel environment variables."
        }), 500

    body = request.get_json(silent=True) or {}
    title     = body.get("title", "").strip()
    source    = body.get("source", "").strip()
    published = body.get("published", "").strip()
    url       = body.get("url", "").strip()
    model     = body.get("model", "meta-llama/llama-3.3-70b-instruct:free").strip()

    if not title:
        return jsonify({"error": "No article title provided"}), 400

    # Validate model ID (must contain :free suffix or be a known pattern)
    if len(model) > 120 or not re.match(r'^[a-zA-Z0-9/_\-.:]+$', model):
        return jsonify({"error": "Invalid model ID"}), 400

    PROMPT = f"""You are a senior financial news analyst. Analyse the following news headline and return ONLY a valid JSON object — no markdown, no code fences, no explanation, just the raw JSON.

The JSON must have exactly these keys (all values are strings):
- headline: One punchy sentence capturing the core story hook.
- what: What happened? (1-2 sentences, plain language)
- who: Key people, companies, or organisations involved. (1 sentence)
- when_where: Exact timing and location if known. (1 sentence)
- why_how: The underlying cause and the mechanism or process. (1-2 sentences)
- consequences: Market, economic, or societal effects. (2-3 sentences)
- significance: The broader importance — why this matters. (1-2 sentences)
- reactions: Notable statements, market moves, or stakeholder responses. (1-2 sentences, or write "Not yet reported" if unknown)
- outlook: What to watch for next. (1-2 sentences)

Article:
Title: {title}
Source: {source}
Published: {published}
URL: {url}

Respond ONLY with the JSON object. Begin with {{ and end with }}."""

    try:
        with httpx.Client(timeout=50) as client:
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
                    "messages": [{"role": "user", "content": PROMPT}],
                    "max_tokens": 900,
                    "temperature": 0.25,
                    "response_format": {"type": "json_object"},
                }
            )

        # Handle HTTP errors with descriptive messages
        if resp.status_code == 401:
            return jsonify({"error": "Invalid OpenRouter API key. Check your OPENROUTER_API_KEY environment variable."}), 401
        if resp.status_code == 402:
            return jsonify({"error": "OpenRouter account has insufficient credits."}), 402
        if resp.status_code == 429:
            return jsonify({"error": "Rate limit hit. Wait a moment and try again."}), 429
        if resp.status_code == 503:
            return jsonify({"error": "The selected model is currently unavailable. Try a different model."}), 503
        if not resp.is_success:
            try:
                err = resp.json()
                msg = err.get("error", {}).get("message", resp.text[:200]) if isinstance(err.get("error"), dict) else str(err.get("error", resp.text[:200]))
            except Exception:
                msg = resp.text[:200]
            return jsonify({"error": f"OpenRouter error {resp.status_code}: {msg}"}), 502

        data = resp.json()

        # Extract content safely
        choices = data.get("choices", [])
        if not choices:
            return jsonify({"error": "Model returned no choices. Try a different model."}), 502

        raw = choices[0].get("message", {}).get("content", "").strip()
        if not raw:
            return jsonify({"error": "Model returned empty content. Try a different model."}), 502

        # Strip any accidental markdown fences
        raw = re.sub(r'^```[a-zA-Z]*\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw).strip()

        # Parse JSON
        try:
            analysis = json.loads(raw)
        except json.JSONDecodeError:
            # Try to extract JSON from within the text
            match = re.search(r'\{[\s\S]*\}', raw)
            if match:
                try:
                    analysis = json.loads(match.group(0))
                except json.JSONDecodeError:
                    analysis = {"headline": raw}
            else:
                analysis = {"headline": raw}

        return jsonify({"analysis": analysis, "model": model})

    except httpx.TimeoutException:
        return jsonify({"error": "Request timed out. The model may be overloaded — try again or select a smaller model."}), 504
    except httpx.ConnectError:
        return jsonify({"error": "Could not connect to OpenRouter. Check your internet connection."}), 503
    except Exception as e:
        return jsonify({"error": f"Unexpected error: {str(e)[:200]}"}), 500


if __name__ == "__main__":
    print("=" * 60)
    print("  STARFISH — Sector Intelligence Platform")
    print("  http://127.0.0.1:5000")
    print("=" * 60)
    print("\n  pip install flask httpx beautifulsoup4 lxml")
    print("  export OPENROUTER_API_KEY=sk-or-...\n")
    app.run(debug=True, host="0.0.0.0", port=5000)
