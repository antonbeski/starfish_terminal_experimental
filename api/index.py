#!/usr/bin/env python3
"""
STARFISH — Sector Intelligence Platform
Light / White Primary · Premium Palette
"""

from flask import Flask, jsonify, request, render_template_string
import httpx
from bs4 import BeautifulSoup
from datetime import datetime
import re
from urllib.parse import quote_plus
import time
import concurrent.futures

app = Flask(__name__)

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
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html{-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale;scroll-behavior:smooth}

:root{
  --white:       #ffffff;
  --off-white:   #f7f6f3;
  --paper:       #f2f0eb;
  --paper-dark:  #e8e5de;
  --ink:         #0f0e0b;
  --ink-soft:    #1c1b18;
  --ink-mid:     #3a3830;
  --ink-light:   #6b6860;
  --ink-faint:   #9e9b95;
  --gold:        #c8860a;
  --gold-light:  #e8a020;
  --gold-dim:    rgba(200,134,10,0.10);
  --gold-border: rgba(200,134,10,0.25);
  --teal:        #1a6b5a;
  --teal-light:  #248c75;
  --teal-dim:    rgba(26,107,90,0.09);
  --teal-border: rgba(26,107,90,0.22);
  --border:      rgba(15,14,11,0.09);
  --border-mid:  rgba(15,14,11,0.14);
  --shadow-xs:   0 1px 2px rgba(15,14,11,0.06);
  --shadow-sm:   0 2px 8px rgba(15,14,11,0.08),0 1px 2px rgba(15,14,11,0.05);
  --shadow-md:   0 4px 20px rgba(15,14,11,0.10),0 2px 6px rgba(15,14,11,0.06);
}

body{
  font-family:'DM Sans',sans-serif;
  background:var(--off-white);
  color:var(--ink);
  min-height:100vh;
  overflow-x:hidden;
}
body::before{
  content:'';position:fixed;inset:0;
  background:
    radial-gradient(ellipse 80% 60% at 70% 0%,rgba(200,134,10,0.055) 0%,transparent 55%),
    radial-gradient(ellipse 60% 50% at 0% 100%,rgba(26,107,90,0.045) 0%,transparent 50%);
  pointer-events:none;z-index:0;
}

/* ── HEADER ── */
header{
  position:sticky;top:0;z-index:400;
  height:62px;
  display:flex;align-items:center;justify-content:space-between;
  padding:0 clamp(1rem,4vw,2.5rem);
  background:rgba(247,246,243,0.9);
  backdrop-filter:blur(20px) saturate(160%);
  -webkit-backdrop-filter:blur(20px) saturate(160%);
  border-bottom:1px solid var(--border-mid);
  box-shadow:var(--shadow-xs);
}
.logo{display:flex;align-items:center;gap:9px;text-decoration:none}
.logo-star{
  width:26px;height:26px;background:var(--ink);
  clip-path:polygon(50% 0%,61% 35%,98% 35%,68% 57%,79% 91%,50% 70%,21% 91%,32% 57%,2% 35%,39% 35%);
  position:relative;animation:star-spin 12s linear infinite;flex-shrink:0;
}
.logo-star::after{
  content:'';position:absolute;inset:4px;background:var(--gold);
  clip-path:polygon(50% 0%,61% 35%,98% 35%,68% 57%,79% 91%,50% 70%,21% 91%,32% 57%,2% 35%,39% 35%);
}
@keyframes star-spin{to{transform:rotate(360deg)}}
.logo-wordmark{
  font-family:'Syne',sans-serif;font-size:1.35rem;font-weight:800;
  letter-spacing:-0.5px;color:var(--ink);line-height:1;
}
.logo-wordmark em{color:var(--gold);font-style:normal}
.header-center{display:flex;align-items:center}
.header-tag{
  font-family:'DM Mono',monospace;font-size:0.62rem;font-weight:500;
  letter-spacing:1.8px;text-transform:uppercase;color:var(--ink-faint);
}
@media(max-width:640px){.header-tag{display:none}}
.live-dot{
  display:flex;align-items:center;gap:6px;
  font-family:'DM Mono',monospace;font-size:0.6rem;font-weight:500;
  letter-spacing:1.5px;text-transform:uppercase;
  color:var(--teal);background:var(--teal-dim);
  border:1px solid var(--teal-border);
  padding:0.22rem 0.7rem;border-radius:20px;
}
.live-dot::before{
  content:'';width:5px;height:5px;border-radius:50%;
  background:var(--teal-light);
  animation:blink 1.3s ease-in-out infinite;
}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0.2}}

/* ── TICKER ── */
.ticker{
  position:relative;z-index:10;
  height:34px;overflow:hidden;
  display:flex;align-items:center;
  background:var(--ink);
  border-bottom:2px solid var(--gold);
}
.ticker::before,.ticker::after{
  content:'';position:absolute;top:0;bottom:0;width:80px;z-index:2;
}
.ticker::before{left:0;background:linear-gradient(90deg,var(--ink) 40%,transparent)}
.ticker::after{right:0;background:linear-gradient(-90deg,var(--ink) 40%,transparent)}
.ticker-badge{
  position:absolute;left:0;height:100%;z-index:3;
  display:flex;align-items:center;padding:0 1rem;
  background:var(--gold);white-space:nowrap;
  font-family:'Syne',sans-serif;font-size:0.6rem;font-weight:800;
  letter-spacing:2px;text-transform:uppercase;color:var(--ink);
}
.ticker-track{
  display:flex;padding-left:120px;
  animation:ticker-run 55s linear infinite;white-space:nowrap;
}
.ticker-track:hover{animation-play-state:paused}
.t-item{
  font-family:'DM Mono',monospace;font-size:0.65rem;
  font-weight:400;letter-spacing:0.8px;
  color:rgba(255,255,255,0.45);padding:0 1.75rem;
}
.t-item strong{color:rgba(255,255,255,0.88);font-weight:500}
.t-sep{color:var(--gold);opacity:0.7}
@keyframes ticker-run{from{transform:translateX(100vw)}to{transform:translateX(-100%)}}

/* ── HERO ── */
.hero{
  position:relative;z-index:10;
  padding:clamp(3.5rem,8vw,6.5rem) clamp(1.25rem,5vw,3rem) clamp(3rem,6vw,5rem);
  text-align:center;
  background:linear-gradient(180deg,var(--off-white) 0%,var(--paper) 100%);
  border-bottom:1px solid var(--border-mid);
  overflow:hidden;
}
.hero::before{
  content:'';position:absolute;inset:0;
  background-image:
    linear-gradient(var(--border) 1px,transparent 1px),
    linear-gradient(90deg,var(--border) 1px,transparent 1px);
  background-size:60px 60px;
  mask-image:radial-gradient(ellipse 80% 60% at 50% 0%,black 0%,transparent 70%);
  -webkit-mask-image:radial-gradient(ellipse 80% 60% at 50% 0%,black 0%,transparent 70%);
  pointer-events:none;
}
.hero-eyebrow{
  display:inline-flex;align-items:center;gap:0.75rem;
  font-family:'DM Mono',monospace;font-size:0.68rem;font-weight:500;
  letter-spacing:2.5px;text-transform:uppercase;
  color:var(--gold);margin-bottom:1.5rem;
}
.hero-eyebrow::before,.hero-eyebrow::after{
  content:'';height:1px;width:32px;
  background:linear-gradient(90deg,transparent,var(--gold));
}
.hero-eyebrow::after{background:linear-gradient(-90deg,transparent,var(--gold))}
.hero h1{
  font-family:'Playfair Display',serif;
  font-size:clamp(2.8rem,8vw,6.5rem);
  font-weight:900;line-height:0.95;letter-spacing:-2px;
  color:var(--ink);margin-bottom:1.5rem;
}
.hero h1 .italic-accent{font-style:italic;color:var(--gold)}
.hero h1 .outlined{color:transparent;-webkit-text-stroke:2px var(--ink)}
.hero-desc{
  font-family:'DM Sans',sans-serif;
  font-size:clamp(0.88rem,2vw,1rem);
  font-weight:400;line-height:1.7;
  color:var(--ink-light);max-width:560px;margin:0 auto 3rem;
}

/* ── SELECTOR ── */
.selector-wrap{max-width:720px;margin:0 auto;display:flex;flex-direction:column;gap:1rem}
.select-compound{
  display:flex;
  background:var(--white);
  border:1.5px solid var(--border-mid);
  border-radius:6px;
  box-shadow:var(--shadow-sm);
  overflow:hidden;
  transition:border-color 0.2s,box-shadow 0.2s;
}
.select-compound:focus-within{
  border-color:var(--gold);
  box-shadow:0 0 0 3px var(--gold-dim),var(--shadow-sm);
}
.sel-prefix{
  display:flex;align-items:center;padding:0 1.1rem;
  font-family:'DM Mono',monospace;font-size:0.6rem;font-weight:500;
  letter-spacing:2px;text-transform:uppercase;color:var(--ink-faint);
  white-space:nowrap;border-right:1px solid var(--border);
  background:var(--off-white);flex-shrink:0;
}
@media(max-width:480px){.sel-prefix{display:none}}
.sector-select{
  flex:1;appearance:none;background:transparent;
  border:none;outline:none;
  padding:0.95rem 3rem 0.95rem 1.1rem;
  font-family:'DM Sans',sans-serif;font-size:0.92rem;font-weight:600;
  color:var(--ink);cursor:pointer;min-width:0;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='13' height='8' viewBox='0 0 13 8'%3E%3Cpath d='M1 1l5.5 5.5L12 1' stroke='%23c8860a' stroke-width='2' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
  background-repeat:no-repeat;background-position:right 1.1rem center;
}
.sector-select option{background:#fff;color:var(--ink)}
.fetch-btn{
  display:flex;align-items:center;gap:0.5rem;
  padding:0.95rem 1.6rem;flex-shrink:0;
  background:var(--ink);border:none;cursor:pointer;
  font-family:'Syne',sans-serif;font-size:0.72rem;font-weight:700;
  letter-spacing:1.5px;text-transform:uppercase;color:var(--white);
  transition:background 0.18s,transform 0.1s;white-space:nowrap;
}
.fetch-btn:hover{background:var(--gold)}
.fetch-btn:active{transform:scale(0.98)}
.fetch-btn:disabled{opacity:0.45;cursor:not-allowed}
.fetch-btn .arr{transition:transform 0.2s}
.fetch-btn:not(:disabled):hover .arr{transform:translateX(3px)}
.source-chips{
  display:flex;align-items:center;justify-content:center;
  flex-wrap:wrap;gap:0.35rem;
}
.chips-label{
  font-family:'DM Mono',monospace;font-size:0.58rem;font-weight:500;
  letter-spacing:1.8px;text-transform:uppercase;color:var(--ink-faint);
  margin-right:0.35rem;
}
.chip{
  font-family:'DM Mono',monospace;font-size:0.58rem;font-weight:500;
  letter-spacing:0.8px;text-transform:uppercase;
  color:var(--ink-light);background:var(--white);
  border:1px solid var(--border-mid);padding:0.18rem 0.6rem;
  border-radius:20px;
}
@media(max-width:480px){.source-chips{display:none}}

/* ── MAIN ── */
main{
  position:relative;z-index:10;
  max-width:1400px;margin:0 auto;
  padding:clamp(1.75rem,4vw,2.75rem) clamp(1rem,3vw,2rem) 5rem;
}

/* ── SECTOR TILES ── */
.sector-intro{display:flex;flex-direction:column;gap:1.25rem}
.intro-heading{display:flex;align-items:baseline;gap:1rem;flex-wrap:wrap}
.intro-title{
  font-family:'Playfair Display',serif;
  font-size:clamp(1.1rem,3vw,1.5rem);font-weight:800;color:var(--ink);
}
.intro-sub{
  font-family:'DM Mono',monospace;font-size:0.65rem;font-weight:500;
  letter-spacing:1.5px;text-transform:uppercase;color:var(--ink-faint);
}
.sector-grid{
  display:grid;
  grid-template-columns:repeat(auto-fill,minmax(165px,1fr));
  gap:0.75rem;
}
.s-tile{
  background:var(--white);border:1px solid var(--border);
  border-radius:6px;padding:1.1rem 1rem;
  cursor:pointer;text-align:left;color:inherit;
  box-shadow:var(--shadow-xs);
  transition:transform 0.15s,box-shadow 0.15s,border-color 0.15s;
  display:flex;flex-direction:column;gap:0.3rem;
}
.s-tile:hover{
  transform:translateY(-2px);
  box-shadow:var(--shadow-md);
  border-color:var(--gold-border);
}
.s-tile-key{
  font-family:'DM Mono',monospace;font-size:0.65rem;font-weight:500;
  letter-spacing:1.5px;text-transform:uppercase;
  color:var(--gold);background:var(--gold-dim);
  border:1px solid var(--gold-border);
  padding:0.15rem 0.5rem;border-radius:3px;
  display:inline-block;align-self:flex-start;margin-bottom:0.3rem;
}
.s-tile-name{
  font-family:'DM Sans',sans-serif;font-size:0.82rem;font-weight:700;
  color:var(--ink);line-height:1.3;
}
.s-tile-sub{
  font-family:'DM Sans',sans-serif;font-size:0.68rem;font-weight:400;
  color:var(--ink-faint);line-height:1.3;
}
@media(max-width:768px){.sector-grid{grid-template-columns:repeat(2,1fr)}}
@media(max-width:400px){.sector-grid{grid-template-columns:1fr}}

/* ── RESULTS HEADER ── */
.res-header{
  display:flex;align-items:flex-end;justify-content:space-between;
  gap:1rem;margin-bottom:1.5rem;
  padding-bottom:1.25rem;border-bottom:1.5px solid var(--border-mid);
  flex-wrap:wrap;
}
.res-title-block{display:flex;flex-direction:column;gap:0.3rem}
.res-eyebrow{
  font-family:'DM Mono',monospace;font-size:0.62rem;font-weight:500;
  letter-spacing:2px;text-transform:uppercase;color:var(--gold);
}
.res-title{
  font-family:'Playfair Display',serif;
  font-size:clamp(1.4rem,4vw,2.2rem);font-weight:800;line-height:1.1;color:var(--ink);
}
.res-title em{font-style:italic;color:var(--gold)}
.res-meta{display:flex;align-items:center;gap:0.75rem;flex-wrap:wrap}
.res-count{
  font-family:'DM Mono',monospace;font-size:0.62rem;font-weight:500;
  letter-spacing:1.5px;text-transform:uppercase;
  color:var(--teal);background:var(--teal-dim);
  border:1px solid var(--teal-border);
  padding:0.28rem 0.75rem;border-radius:20px;
}
.res-time{
  font-family:'DM Mono',monospace;font-size:0.6rem;
  font-weight:500;letter-spacing:1px;color:var(--ink-faint);
}

/* ── FILTER PILLS ── */
.filter-row{
  display:flex;flex-wrap:wrap;gap:0.4rem;
  margin-bottom:1.75rem;align-items:center;
}
.filter-label{
  font-family:'DM Mono',monospace;font-size:0.58rem;font-weight:500;
  letter-spacing:1.8px;text-transform:uppercase;color:var(--ink-faint);margin-right:0.35rem;
}
.pill{
  font-family:'DM Sans',sans-serif;font-size:0.72rem;font-weight:600;
  padding:0.32rem 0.85rem;
  border:1px solid var(--border-mid);border-radius:20px;
  background:var(--white);color:var(--ink-light);cursor:pointer;
  transition:all 0.15s;box-shadow:var(--shadow-xs);
}
.pill:hover{border-color:var(--gold-border);color:var(--gold);background:var(--gold-dim)}
.pill.active{background:var(--ink);border-color:var(--ink);color:var(--white);box-shadow:var(--shadow-sm)}

/* ── NEWS GRID ── */
.news-grid{
  display:grid;
  grid-template-columns:repeat(auto-fill,minmax(320px,1fr));
  gap:1rem;
}
@media(max-width:680px){.news-grid{grid-template-columns:1fr}}
@media(min-width:1200px){.news-grid{grid-template-columns:repeat(3,1fr)}}

/* ── NEWS CARD ── */
@keyframes card-in{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}

.card{
  background:var(--white);
  border:1px solid var(--border);
  border-radius:8px;
  padding:1.35rem;
  display:flex;flex-direction:column;gap:0.85rem;
  box-shadow:var(--shadow-xs);
  transition:transform 0.18s,box-shadow 0.18s,border-color 0.18s;
  position:relative;overflow:hidden;
  animation:card-in 0.38s ease both;
}
.card::after{
  content:'';
  position:absolute;top:0;left:0;
  width:100%;height:2px;
  background:linear-gradient(90deg,var(--gold),var(--teal));
  opacity:0;transition:opacity 0.2s;
}
.card:hover{
  transform:translateY(-3px);
  box-shadow:var(--shadow-md);
  border-color:var(--border-mid);
}
.card:hover::after{opacity:1}
.card-top{
  display:flex;align-items:flex-start;
  justify-content:space-between;gap:0.75rem;
}
.card-src{
  font-family:'DM Mono',monospace;font-size:0.58rem;font-weight:500;
  letter-spacing:1.5px;text-transform:uppercase;
  color:var(--teal);background:var(--teal-dim);
  border:1px solid var(--teal-border);
  padding:0.16rem 0.55rem;border-radius:3px;white-space:nowrap;
}
.card-num{
  font-family:'DM Mono',monospace;font-size:0.65rem;
  font-weight:500;color:var(--ink-faint);flex-shrink:0;
}
.card-title{
  font-family:'DM Sans',sans-serif;
  font-size:0.92rem;font-weight:700;line-height:1.5;
  color:var(--ink);flex:1;
}
.card-title a{
  color:inherit;text-decoration:none;display:block;transition:color 0.15s;
}
.card-title a:hover{color:var(--gold)}
.card-footer{
  display:flex;align-items:center;justify-content:space-between;
  gap:0.75rem;margin-top:auto;
  padding-top:0.85rem;border-top:1px solid var(--border);
}
.card-date{
  font-family:'DM Mono',monospace;font-size:0.62rem;font-weight:400;
  color:var(--ink-faint);white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis;
}
.card-read{
  font-family:'Syne',sans-serif;font-size:0.65rem;font-weight:700;
  letter-spacing:1px;text-transform:uppercase;
  color:var(--ink-light);text-decoration:none;
  padding:0.28rem 0.7rem;border:1px solid var(--border-mid);
  border-radius:4px;background:var(--off-white);
  transition:all 0.15s;white-space:nowrap;flex-shrink:0;
}
.card-read:hover{
  background:var(--ink);color:var(--white);
  border-color:var(--ink);
}

/* ── STATE BOXES ── */
.state{
  display:flex;flex-direction:column;align-items:center;
  justify-content:center;padding:5rem 2rem;
  text-align:center;gap:1.25rem;
}
.state-icon{
  width:56px;height:56px;
  border:1.5px solid var(--border-mid);border-radius:50%;
  display:flex;align-items:center;justify-content:center;
  background:var(--white);box-shadow:var(--shadow-sm);
}
.state-icon svg{
  width:22px;height:22px;stroke:var(--ink-faint);fill:none;
  stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round;
}
.state-title{
  font-family:'Playfair Display',serif;
  font-size:1.6rem;font-weight:800;color:var(--ink-mid);
}
.state-sub{
  font-family:'DM Sans',sans-serif;font-size:0.88rem;
  color:var(--ink-faint);max-width:380px;line-height:1.65;
}
.spinner{
  width:40px;height:40px;
  border:2.5px solid var(--border-mid);
  border-top-color:var(--gold);
  border-radius:50%;animation:spin 0.75s linear infinite;
}
@keyframes spin{to{transform:rotate(360deg)}}
.spin-label{
  font-family:'DM Mono',monospace;font-size:0.65rem;font-weight:500;
  letter-spacing:2.5px;text-transform:uppercase;color:var(--ink-faint);
  animation:pulse-label 1.6s ease-in-out infinite;
}
@keyframes pulse-label{0%,100%{opacity:0.4}50%{opacity:1}}

/* ── FOOTER ── */
footer{
  position:relative;z-index:10;
  border-top:1px solid var(--border-mid);
  padding:1.75rem clamp(1rem,4vw,2.5rem);
  background:var(--paper);
  display:flex;align-items:center;justify-content:space-between;
  flex-wrap:wrap;gap:0.75rem;
}
.f-brand{
  font-family:'Syne',sans-serif;font-size:0.9rem;font-weight:800;
  letter-spacing:1px;color:var(--ink-light);
}
.f-brand em{color:var(--gold);font-style:normal}
.f-copy{
  font-family:'DM Mono',monospace;font-size:0.58rem;font-weight:400;
  letter-spacing:1px;text-transform:uppercase;color:var(--ink-faint);
}
.f-srcs{
  font-family:'DM Mono',monospace;font-size:0.56rem;
  letter-spacing:0.8px;text-transform:uppercase;color:var(--ink-faint);opacity:0.7;
}
@media(max-width:768px){footer{flex-direction:column;text-align:center}.f-srcs{display:none}}
</style>
</head>
<body>

<!-- Header -->
<header>
  <a class="logo" href="/">
    <div class="logo-star"></div>
    <span class="logo-wordmark">STAR<em>FISH</em></span>
  </a>
  <div class="header-center">
    <span class="header-tag">Sector Intelligence Platform</span>
  </div>
  <div>
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
  <div class="hero-eyebrow">11 GICS Sectors &nbsp;&middot;&nbsp; 8 Premium Sources</div>
  <h1>
    Sector<br>
    <span class="italic-accent">Intelligence</span>&nbsp;<span class="outlined">Aggregated</span>
  </h1>
  <p class="hero-desc">Real-time financial news from Reuters, CNBC, WSJ, Yahoo Finance, MarketWatch, Financial Times, Benzinga and Seeking Alpha &mdash; all in one place.</p>

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
let allArticles = [];

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
      <div class="state-sub">Pulling live data from Reuters, CNBC, WSJ, Yahoo Finance, MarketWatch, Financial Times, Benzinga and Seeking Alpha simultaneously.</div>
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
        <div class="state-sub">${esc(e.message)}. Please try again.</div>
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
        <div class="res-title">Latest: <em>${esc(label || '')}</em></div>
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
      ${sources.map(s => `<button class="pill" onclick="filterBy(${JSON.stringify(s)},this)">${esc(s)}</button>`).join('')}
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
    const src   = esc(a.source || '');
    const title = esc(a.title  || '');
    const url   = (a.url || '#').replace(/"/g, '%22');
    const date  = esc(a.published || 'Date unavailable');
    const idx   = String(i + 1).padStart(2, '0');
    const delay = Math.min(i * 0.032, 0.72);
    return `<div class="card" data-source="${src}" style="animation-delay:${delay}s">
      <div class="card-top">
        <span class="card-src">${src}</span>
        <span class="card-num">${idx}</span>
      </div>
      <div class="card-title"><a href="${url}" target="_blank" rel="noopener noreferrer">${title}</a></div>
      <div class="card-footer">
        <span class="card-date">${date}</span>
        <a class="card-read" href="${url}" target="_blank" rel="noopener noreferrer">Read &rsaquo;</a>
      </div>
    </div>`;
  }).join('');

  document.getElementById('output').innerHTML =
    header + filters + `<div class="news-grid">${cards}</div>`;
}

function filterBy(source, btn) {
  document.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.card').forEach(c => {
    c.style.display = (source === 'all' || c.dataset.source === source) ? '' : 'none';
  });
}

function esc(str) {
  return String(str)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

document.getElementById('sector').addEventListener('change', function() {
  if (this.value) fetchNews();
});
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


if __name__ == "__main__":
    print("=" * 60)
    print("  STARFISH — Sector Intelligence Platform")
    print("  http://127.0.0.1:5000")
    print("=" * 60)
    print("\n  pip install flask httpx beautifulsoup4 lxml\n")
    app.run(debug=True, host="0.0.0.0", port=5000)
