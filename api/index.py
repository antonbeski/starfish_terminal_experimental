#!/usr/bin/env python3
"""
Financial News Aggregator - Single File Flask App
Scrapes financial news by GICS sector from reliable sources.
"""

from flask import Flask, jsonify, request, render_template_string
import httpx
from bs4 import BeautifulSoup
import asyncio
from datetime import datetime
import re
from urllib.parse import urljoin, quote_plus
import time

app = Flask(__name__)

# ── Sector configuration ────────────────────────────────────────────────────
SECTORS = {
    "communication-services": {
        "label": "Communication Services",
        "key": "XLC",
        "keywords": ["telecom", "media", "streaming", "internet", "AT&T", "Netflix", "Meta", "Alphabet", "Disney", "Comcast", "Verizon"],
        "queries": ["communication services sector stocks", "telecom media internet stocks news"],
    },
    "consumer-discretionary": {
        "label": "Consumer Discretionary",
        "key": "XLY",
        "keywords": ["retail", "auto", "leisure", "Amazon", "Tesla", "Nike", "McDonald's", "Booking", "Home Depot"],
        "queries": ["consumer discretionary sector stocks news", "retail auto leisure stocks"],
    },
    "consumer-staples": {
        "label": "Consumer Staples",
        "key": "XLP",
        "keywords": ["food", "beverage", "household", "Procter Gamble", "Coca-Cola", "PepsiCo", "Walmart", "Costco", "Unilever"],
        "queries": ["consumer staples sector stocks news", "food beverage essentials stocks"],
    },
    "energy": {
        "label": "Energy",
        "key": "XLE",
        "keywords": ["oil", "gas", "energy", "renewable", "ExxonMobil", "Chevron", "Shell", "BP", "ConocoPhillips", "pipeline"],
        "queries": ["energy sector stocks oil gas news", "oil gas renewables stocks"],
    },
    "financials": {
        "label": "Financials",
        "key": "XLF",
        "keywords": ["bank", "insurance", "fintech", "JPMorgan", "Visa", "Mastercard", "Goldman Sachs", "Wells Fargo", "Berkshire"],
        "queries": ["financial sector stocks banks insurance news", "banks fintech stocks news"],
    },
    "health-care": {
        "label": "Health Care",
        "key": "XLV",
        "keywords": ["pharma", "biotech", "hospital", "Pfizer", "UnitedHealth", "Johnson", "Merck", "Abbott", "Moderna", "drug"],
        "queries": ["healthcare sector stocks pharma biotech news", "pharma biotech hospital stocks"],
    },
    "industrials": {
        "label": "Industrials",
        "key": "XLI",
        "keywords": ["aerospace", "defense", "machinery", "logistics", "Boeing", "Caterpillar", "Honeywell", "UPS", "Raytheon"],
        "queries": ["industrials sector stocks aerospace machinery news", "defense logistics industrial stocks"],
    },
    "information-technology": {
        "label": "Information Technology",
        "key": "XLK",
        "keywords": ["software", "hardware", "semiconductor", "chip", "Apple", "Microsoft", "Nvidia", "Intel", "AMD", "cloud", "AI"],
        "queries": ["technology sector stocks software semiconductor news", "software hardware chip stocks"],
    },
    "materials": {
        "label": "Materials",
        "key": "XLB",
        "keywords": ["chemical", "metal", "mining", "gold", "Dow", "Rio Tinto", "Freeport", "Newmont", "Linde", "commodity"],
        "queries": ["materials sector stocks chemicals metals mining news", "mining metals commodities stocks"],
    },
    "real-estate": {
        "label": "Real Estate",
        "key": "XLRE",
        "keywords": ["REIT", "property", "real estate", "Prologis", "American Tower", "Simon Property", "Crown Castle", "Equinix"],
        "queries": ["real estate sector REIT stocks news", "property REIT stocks news"],
    },
    "utilities": {
        "label": "Utilities",
        "key": "XLU",
        "keywords": ["power", "electric", "water", "gas utility", "NextEra", "Duke Energy", "Southern Company", "Dominion", "grid"],
        "queries": ["utilities sector stocks power water news", "electric gas utility stocks news"],
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# ── Scrapers ─────────────────────────────────────────────────────────────────

def parse_relative_time(text: str) -> str:
    """Normalize time strings."""
    if not text:
        return ""
    text = text.strip()
    # Already ISO-like
    if re.match(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").strftime("%b %d, %Y")
        except:
            return text
    return text[:60]


def scrape_seeking_alpha(sector_id: str, client: httpx.Client) -> list:
    """Scrape SeekingAlpha sector news via their public feed."""
    info = SECTORS[sector_id]
    results = []
    try:
        etf = info["key"].lower()
        url = f"https://seekingalpha.com/symbol/{etf}/news"
        r = client.get(url, timeout=8)
        soup = BeautifulSoup(r.text, "html.parser")
        articles = soup.select("article, [data-test-id='post-list-item']")[:10]
        for art in articles:
            a_tag = art.find("a", href=True)
            if not a_tag:
                continue
            title = a_tag.get_text(strip=True)
            href = a_tag["href"]
            if not href.startswith("http"):
                href = "https://seekingalpha.com" + href
            time_tag = art.find("time")
            pub = time_tag.get("datetime", "") if time_tag else ""
            if title and len(title) > 20:
                results.append({
                    "title": title,
                    "url": href,
                    "source": "Seeking Alpha",
                    "published": parse_relative_time(pub),
                    "sector": sector_id,
                })
    except Exception:
        pass
    return results


def scrape_reuters(sector_id: str, client: httpx.Client) -> list:
    """Scrape Reuters finance section."""
    info = SECTORS[sector_id]
    results = []
    try:
        query = quote_plus(info["queries"][0])
        url = f"https://www.reuters.com/search/news?blob={query}&sortBy=date&dateRange=pastMonth"
        r = client.get(url, timeout=8)
        soup = BeautifulSoup(r.text, "html.parser")
        items = soup.select(".search-result-indiv, article")[:8]
        for item in items:
            a_tag = item.find("a", href=True)
            if not a_tag:
                continue
            title = a_tag.get_text(strip=True)
            href = a_tag["href"]
            if not href.startswith("http"):
                href = "https://www.reuters.com" + href
            time_tag = item.find("time")
            pub = time_tag.get("datetime", "") if time_tag else ""
            if title and len(title) > 20:
                results.append({
                    "title": title,
                    "url": href,
                    "source": "Reuters",
                    "published": parse_relative_time(pub),
                    "sector": sector_id,
                })
    except Exception:
        pass
    return results


def scrape_marketwatch(sector_id: str, client: httpx.Client) -> list:
    """Scrape MarketWatch using RSS feed."""
    results = []
    try:
        url = "https://feeds.marketwatch.com/marketwatch/topstories/"
        r = client.get(url, timeout=8)
        soup = BeautifulSoup(r.text, "xml")
        items = soup.find_all("item")
        keywords = [k.lower() for k in SECTORS[sector_id]["keywords"]]
        for item in items:
            title = item.find("title")
            link = item.find("link")
            pub_date = item.find("pubDate")
            if not title or not link:
                continue
            title_text = title.get_text(strip=True)
            if not any(kw in title_text.lower() for kw in keywords):
                continue
            href = link.get_text(strip=True)
            pub = pub_date.get_text(strip=True) if pub_date else ""
            # Parse RFC-822 date
            try:
                dt = datetime.strptime(pub[:25], "%a, %d %b %Y %H:%M:%S")
                pub = dt.strftime("%b %d, %Y %H:%M")
            except:
                pub = pub[:30]
            results.append({
                "title": title_text,
                "url": href,
                "source": "MarketWatch",
                "published": pub,
                "sector": sector_id,
            })
            if len(results) >= 8:
                break
    except Exception:
        pass
    return results


def scrape_yahoo_finance(sector_id: str, client: httpx.Client) -> list:
    """Scrape Yahoo Finance RSS."""
    results = []
    try:
        url = "https://finance.yahoo.com/news/rssindex"
        r = client.get(url, timeout=8)
        soup = BeautifulSoup(r.text, "xml")
        items = soup.find_all("item")
        keywords = [k.lower() for k in SECTORS[sector_id]["keywords"]]
        for item in items:
            title = item.find("title")
            link = item.find("link")
            pub_date = item.find("pubDate")
            if not title or not link:
                continue
            title_text = title.get_text(strip=True)
            if not any(kw in title_text.lower() for kw in keywords):
                continue
            href = link.get_text(strip=True)
            pub = pub_date.get_text(strip=True) if pub_date else ""
            try:
                dt = datetime.strptime(pub[:25], "%a, %d %b %Y %H:%M:%S")
                pub = dt.strftime("%b %d, %Y %H:%M")
            except:
                pub = pub[:30]
            results.append({
                "title": title_text,
                "url": href,
                "source": "Yahoo Finance",
                "published": pub,
                "sector": sector_id,
            })
            if len(results) >= 8:
                break
    except Exception:
        pass
    return results


def scrape_cnbc(sector_id: str, client: httpx.Client) -> list:
    """Scrape CNBC RSS finance feed."""
    results = []
    try:
        url = "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664"
        r = client.get(url, timeout=8)
        soup = BeautifulSoup(r.text, "xml")
        items = soup.find_all("item")
        keywords = [k.lower() for k in SECTORS[sector_id]["keywords"]]
        for item in items:
            title = item.find("title")
            link = item.find("link")
            pub_date = item.find("pubDate")
            if not title or not link:
                continue
            title_text = title.get_text(strip=True)
            if not any(kw in title_text.lower() for kw in keywords):
                continue
            href = link.get_text(strip=True)
            pub = pub_date.get_text(strip=True) if pub_date else ""
            try:
                dt = datetime.strptime(pub[:25], "%a, %d %b %Y %H:%M:%S")
                pub = dt.strftime("%b %d, %Y %H:%M")
            except:
                pub = pub[:30]
            results.append({
                "title": title_text,
                "url": href,
                "source": "CNBC",
                "published": pub,
                "sector": sector_id,
            })
            if len(results) >= 8:
                break
    except Exception:
        pass
    return results


def scrape_benzinga(sector_id: str, client: httpx.Client) -> list:
    """Scrape Benzinga via their news feed."""
    results = []
    try:
        url = "https://www.benzinga.com/feeds/news"
        r = client.get(url, timeout=8)
        soup = BeautifulSoup(r.text, "xml")
        items = soup.find_all("item")
        keywords = [k.lower() for k in SECTORS[sector_id]["keywords"]]
        for item in items:
            title = item.find("title")
            link = item.find("link")
            pub_date = item.find("pubDate")
            if not title or not link:
                continue
            title_text = title.get_text(strip=True)
            if not any(kw in title_text.lower() for kw in keywords):
                continue
            href = link.get_text(strip=True)
            pub = pub_date.get_text(strip=True) if pub_date else ""
            try:
                dt = datetime.strptime(pub[:25], "%a, %d %b %Y %H:%M:%S")
                pub = dt.strftime("%b %d, %Y %H:%M")
            except:
                pub = pub[:30]
            results.append({
                "title": title_text,
                "url": href,
                "source": "Benzinga",
                "published": pub,
                "sector": sector_id,
            })
            if len(results) >= 8:
                break
    except Exception:
        pass
    return results


def scrape_ft(sector_id: str, client: httpx.Client) -> list:
    """Scrape Financial Times RSS."""
    results = []
    try:
        url = "https://www.ft.com/rss/home/us"
        r = client.get(url, timeout=8)
        soup = BeautifulSoup(r.text, "xml")
        items = soup.find_all("item")
        keywords = [k.lower() for k in SECTORS[sector_id]["keywords"]]
        for item in items:
            title = item.find("title")
            link = item.find("link")
            pub_date = item.find("pubDate")
            if not title or not link:
                continue
            title_text = title.get_text(strip=True)
            if not any(kw in title_text.lower() for kw in keywords):
                continue
            href = link.get_text(strip=True)
            pub = pub_date.get_text(strip=True) if pub_date else ""
            try:
                dt = datetime.strptime(pub[:25], "%a, %d %b %Y %H:%M:%S")
                pub = dt.strftime("%b %d, %Y %H:%M")
            except:
                pub = pub[:30]
            results.append({
                "title": title_text,
                "url": href,
                "source": "Financial Times",
                "published": pub,
                "sector": sector_id,
            })
            if len(results) >= 8:
                break
    except Exception:
        pass
    return results


def scrape_wsj(sector_id: str, client: httpx.Client) -> list:
    """Scrape WSJ markets RSS."""
    results = []
    try:
        url = "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"
        r = client.get(url, timeout=8)
        soup = BeautifulSoup(r.text, "xml")
        items = soup.find_all("item")
        keywords = [k.lower() for k in SECTORS[sector_id]["keywords"]]
        for item in items:
            title = item.find("title")
            link = item.find("link")
            pub_date = item.find("pubDate")
            if not title or not link:
                continue
            title_text = title.get_text(strip=True)
            if not any(kw in title_text.lower() for kw in keywords):
                continue
            href = link.get_text(strip=True)
            pub = pub_date.get_text(strip=True) if pub_date else ""
            try:
                dt = datetime.strptime(pub[:25], "%a, %d %b %Y %H:%M:%S")
                pub = dt.strftime("%b %d, %Y %H:%M")
            except:
                pub = pub[:30]
            results.append({
                "title": title_text,
                "url": href,
                "source": "Wall Street Journal",
                "published": pub,
                "sector": sector_id,
            })
            if len(results) >= 8:
                break
    except Exception:
        pass
    return results


def fetch_all_news(sector_id: str) -> list:
    """Run all scrapers concurrently using httpx."""
    all_results = []
    scrapers = [
        scrape_yahoo_finance,
        scrape_cnbc,
        scrape_marketwatch,
        scrape_benzinga,
        scrape_ft,
        scrape_wsj,
        scrape_reuters,
        scrape_seeking_alpha,
    ]
    # Use a single shared client with connection pooling for speed
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=10) as client:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(fn, sector_id, client): fn.__name__ for fn in scrapers}
            for future in concurrent.futures.as_completed(futures):
                try:
                    all_results.extend(future.result())
                except Exception:
                    pass

    # Deduplicate by title similarity
    seen_titles = set()
    unique = []
    for item in all_results:
        key = re.sub(r"[^a-z0-9]", "", item["title"].lower())[:60]
        if key not in seen_titles:
            seen_titles.add(key)
            unique.append(item)

    # Sort: items with a publication date first
    def sort_key(x):
        pub = x.get("published", "")
        if not pub:
            return ""
        return pub

    unique.sort(key=sort_key, reverse=True)
    return unique[:40]


# ── HTML Template ─────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>FinPulse — Sector News</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;700;900&family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
  :root {
    --ink: #0a0a0f;
    --paper: #f5f3ee;
    --cream: #ede9e0;
    --accent: #c8522a;
    --accent2: #2a5fc8;
    --gold: #c8a22a;
    --muted: #7a7570;
    --border: #d4cfc6;
    --card-bg: #ffffff;
    --shadow: 0 1px 3px rgba(10,10,15,0.08), 0 4px 16px rgba(10,10,15,0.06);
  }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'DM Sans', sans-serif;
    background: var(--paper);
    color: var(--ink);
    min-height: 100vh;
  }

  /* ── Header ── */
  header {
    background: var(--ink);
    padding: 0 2rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 64px;
    position: sticky; top: 0; z-index: 100;
    border-bottom: 2px solid var(--accent);
  }
  .logo {
    font-family: 'Playfair Display', serif;
    font-size: 1.6rem;
    font-weight: 900;
    color: #fff;
    letter-spacing: -0.5px;
  }
  .logo span { color: var(--accent); }
  .header-sub {
    font-family: 'DM Mono', monospace;
    font-size: 0.7rem;
    color: var(--muted);
    letter-spacing: 2px;
    text-transform: uppercase;
  }

  /* ── Hero band ── */
  .hero {
    background: var(--cream);
    border-bottom: 1px solid var(--border);
    padding: 3rem 2rem 2rem;
    text-align: center;
  }
  .hero h1 {
    font-family: 'Playfair Display', serif;
    font-size: clamp(2rem, 5vw, 3.5rem);
    font-weight: 900;
    line-height: 1.1;
    margin-bottom: 0.5rem;
  }
  .hero h1 em { color: var(--accent); font-style: normal; }
  .hero p {
    color: var(--muted);
    font-size: 1rem;
    margin-bottom: 2rem;
  }

  /* ── Selector ── */
  .selector-wrap {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 1rem;
    flex-wrap: wrap;
  }
  .selector-wrap label {
    font-family: 'DM Mono', monospace;
    font-size: 0.75rem;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--muted);
    font-weight: 500;
  }
  .sector-select {
    appearance: none;
    background: var(--ink);
    color: #fff;
    border: none;
    padding: 0.8rem 3rem 0.8rem 1.2rem;
    font-family: 'DM Sans', sans-serif;
    font-size: 1rem;
    font-weight: 500;
    border-radius: 2px;
    cursor: pointer;
    min-width: 280px;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath d='M1 1l5 5 5-5' stroke='%23c8522a' stroke-width='2' fill='none' stroke-linecap='round'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 1rem center;
    transition: opacity 0.2s;
  }
  .sector-select:focus { outline: 2px solid var(--accent); }
  .sector-select option { background: #1a1a2e; }

  .fetch-btn {
    background: var(--accent);
    color: #fff;
    border: none;
    padding: 0.8rem 2rem;
    font-family: 'DM Mono', monospace;
    font-size: 0.85rem;
    font-weight: 500;
    letter-spacing: 1px;
    text-transform: uppercase;
    border-radius: 2px;
    cursor: pointer;
    transition: background 0.2s, transform 0.1s;
  }
  .fetch-btn:hover { background: #b04020; }
  .fetch-btn:active { transform: scale(0.98); }
  .fetch-btn:disabled { opacity: 0.5; cursor: not-allowed; }

  /* ── Main layout ── */
  main {
    max-width: 1100px;
    margin: 0 auto;
    padding: 2.5rem 1.5rem 4rem;
  }

  /* ── Status bar ── */
  .status-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1.5rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid var(--border);
    flex-wrap: wrap;
    gap: 0.5rem;
  }
  .sector-title {
    font-family: 'Playfair Display', serif;
    font-size: 1.5rem;
    font-weight: 700;
  }
  .sector-title span { color: var(--accent); }
  .article-count {
    font-family: 'DM Mono', monospace;
    font-size: 0.75rem;
    color: var(--muted);
    letter-spacing: 1px;
  }

  /* ── Source filter pills ── */
  .source-filters {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin-bottom: 1.5rem;
  }
  .pill {
    font-family: 'DM Mono', monospace;
    font-size: 0.7rem;
    padding: 0.3rem 0.75rem;
    border-radius: 999px;
    border: 1px solid var(--border);
    background: var(--card-bg);
    cursor: pointer;
    letter-spacing: 0.5px;
    transition: all 0.15s;
    color: var(--muted);
  }
  .pill.active {
    background: var(--ink);
    color: #fff;
    border-color: var(--ink);
  }
  .pill:hover:not(.active) { border-color: var(--ink); color: var(--ink); }

  /* ── News grid ── */
  .news-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 1.25rem;
  }

  .news-card {
    background: var(--card-bg);
    border: 1px solid var(--border);
    border-radius: 2px;
    padding: 1.25rem 1.25rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    transition: transform 0.15s, box-shadow 0.15s;
    position: relative;
    overflow: hidden;
  }
  .news-card::before {
    content: '';
    position: absolute;
    top: 0; left: 0;
    width: 3px; height: 100%;
    background: var(--source-color, var(--accent));
  }
  .news-card:hover {
    transform: translateY(-2px);
    box-shadow: var(--shadow);
  }

  .card-source {
    font-family: 'DM Mono', monospace;
    font-size: 0.65rem;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--source-color, var(--accent));
    font-weight: 500;
  }
  .card-title {
    font-family: 'Playfair Display', serif;
    font-size: 1rem;
    font-weight: 700;
    line-height: 1.4;
    color: var(--ink);
  }
  .card-title a {
    color: inherit;
    text-decoration: none;
    transition: color 0.15s;
  }
  .card-title a:hover { color: var(--accent); }

  .card-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: auto;
  }
  .card-time {
    font-family: 'DM Mono', monospace;
    font-size: 0.68rem;
    color: var(--muted);
  }
  .card-link {
    font-family: 'DM Mono', monospace;
    font-size: 0.68rem;
    color: var(--accent2);
    text-decoration: none;
    letter-spacing: 0.5px;
  }
  .card-link:hover { text-decoration: underline; }

  /* ── Loading & empty states ── */
  .state-box {
    text-align: center;
    padding: 5rem 2rem;
    color: var(--muted);
  }
  .state-box .icon {
    font-size: 3rem;
    margin-bottom: 1rem;
    display: block;
    opacity: 0.4;
  }
  .state-box h3 {
    font-family: 'Playfair Display', serif;
    font-size: 1.3rem;
    margin-bottom: 0.5rem;
    color: var(--ink);
  }
  .state-box p { font-size: 0.9rem; }

  /* Spinner */
  .spinner {
    width: 36px; height: 36px;
    border: 3px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    margin: 0 auto 1.5rem;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── Ticker tape ── */
  .ticker {
    background: var(--ink);
    color: var(--gold);
    font-family: 'DM Mono', monospace;
    font-size: 0.72rem;
    padding: 0.45rem 0;
    overflow: hidden;
    white-space: nowrap;
    border-bottom: 1px solid #222;
  }
  .ticker-inner {
    display: inline-block;
    animation: ticker 35s linear infinite;
  }
  .ticker-inner span { margin: 0 2.5rem; }
  @keyframes ticker { from { transform: translateX(100vw); } to { transform: translateX(-100%); } }

  /* ── Footer ── */
  footer {
    text-align: center;
    padding: 2rem;
    font-family: 'DM Mono', monospace;
    font-size: 0.7rem;
    color: var(--muted);
    border-top: 1px solid var(--border);
    letter-spacing: 1px;
  }

  @media (max-width: 600px) {
    header { padding: 0 1rem; }
    .hero { padding: 2rem 1rem 1.5rem; }
    .news-grid { grid-template-columns: 1fr; }
  }
</style>
</head>
<body>

<header>
  <div class="logo">Fin<span>Pulse</span></div>
  <div class="header-sub">Live Sector Intelligence</div>
</header>

<div class="ticker">
  <div class="ticker-inner">
    <span>📈 S&amp;P 500</span>
    <span>XLC · XLY · XLP · XLE · XLF · XLV · XLI · XLK · XLB · XLRE · XLU</span>
    <span>REAL-TIME SECTOR NEWS AGGREGATOR</span>
    <span>Sources: Reuters · CNBC · WSJ · Yahoo Finance · MarketWatch · FT · Benzinga · Seeking Alpha</span>
    <span>📊 Select a sector below to load the latest financial news</span>
  </div>
</div>

<div class="hero">
  <h1>Sector <em>Intelligence</em><br>at Your Fingertips</h1>
  <p>Aggregated from Reuters, CNBC, WSJ, Yahoo Finance, FT &amp; more — updated live.</p>
  <div class="selector-wrap">
    <label for="sector">Select Sector</label>
    <select id="sector" class="sector-select">
      <option value="">— Choose a GICS Sector —</option>
      <option value="communication-services">Communication Services · XLC</option>
      <option value="consumer-discretionary">Consumer Discretionary · XLY</option>
      <option value="consumer-staples">Consumer Staples · XLP</option>
      <option value="energy">Energy · XLE</option>
      <option value="financials">Financials · XLF</option>
      <option value="health-care">Health Care · XLV</option>
      <option value="industrials">Industrials · XLI</option>
      <option value="information-technology">Information Technology · XLK</option>
      <option value="materials">Materials · XLB</option>
      <option value="real-estate">Real Estate · XLRE</option>
      <option value="utilities">Utilities · XLU</option>
    </select>
    <button class="fetch-btn" id="fetchBtn" onclick="fetchNews()">Get News →</button>
  </div>
</div>

<main>
  <div id="output">
    <div class="state-box">
      <span class="icon">📰</span>
      <h3>Choose a sector above</h3>
      <p>Select one of the 11 GICS sectors and click <strong>Get News</strong> to load live articles from premium financial sources.</p>
    </div>
  </div>
</main>

<footer>FINPULSE · SECTOR NEWS AGGREGATOR · SOURCES: REUTERS, CNBC, WSJ, YAHOO FINANCE, MARKETWATCH, FINANCIAL TIMES, BENZINGA, SEEKING ALPHA</footer>

<script>
const SOURCE_COLORS = {
  "Reuters": "#ff6b00",
  "CNBC": "#0055a5",
  "Yahoo Finance": "#6001d2",
  "MarketWatch": "#c00",
  "Financial Times": "#f5792c",
  "Wall Street Journal": "#0274b6",
  "Benzinga": "#00c896",
  "Seeking Alpha": "#1d6f42",
};

let allArticles = [];

async function fetchNews() {
  const sector = document.getElementById('sector').value;
  if (!sector) { alert('Please select a sector first.'); return; }

  const btn = document.getElementById('fetchBtn');
  btn.disabled = true;
  btn.textContent = 'Loading…';

  document.getElementById('output').innerHTML = `
    <div class="state-box">
      <div class="spinner"></div>
      <h3>Scanning financial sources…</h3>
      <p>Pulling live data from Reuters, CNBC, WSJ, Yahoo Finance, MarketWatch, FT, Benzinga &amp; Seeking Alpha</p>
    </div>`;

  try {
    const resp = await fetch('/api/news?sector=' + encodeURIComponent(sector));
    const data = await resp.json();
    allArticles = data.articles || [];
    renderNews(allArticles, data.sector_label);
  } catch(e) {
    document.getElementById('output').innerHTML = `
      <div class="state-box">
        <span class="icon">⚠️</span>
        <h3>Could not load news</h3>
        <p>${e.message}</p>
      </div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Refresh ↻';
  }
}

function renderNews(articles, sectorLabel) {
  const sources = [...new Set(articles.map(a => a.source))].sort();
  const pillsHtml = `<div class="source-filters">
    <button class="pill active" onclick="filterSource('all', this)">All Sources</button>
    ${sources.map(s => `<button class="pill" onclick="filterSource('${s}', this)">${s}</button>`).join('')}
  </div>`;

  const statusHtml = `<div class="status-bar">
    <div class="sector-title">Latest: <span>${sectorLabel || ''}</span></div>
    <div class="article-count">${articles.length} ARTICLES FOUND</div>
  </div>`;

  if (!articles.length) {
    document.getElementById('output').innerHTML = statusHtml + pillsHtml + `
      <div class="state-box">
        <span class="icon">🔍</span>
        <h3>No articles found</h3>
        <p>Try a different sector or check back later.</p>
      </div>`;
    return;
  }

  const cardsHtml = articles.map(a => {
    const color = SOURCE_COLORS[a.source] || '#666';
    return `<div class="news-card" data-source="${a.source}" style="--source-color:${color}">
      <div class="card-source">${a.source}</div>
      <div class="card-title"><a href="${a.url}" target="_blank" rel="noopener">${a.title}</a></div>
      <div class="card-footer">
        <span class="card-time">🕐 ${a.published || 'Date unknown'}</span>
        <a class="card-link" href="${a.url}" target="_blank" rel="noopener">Read →</a>
      </div>
    </div>`;
  }).join('');

  document.getElementById('output').innerHTML = statusHtml + pillsHtml + `<div class="news-grid" id="newsGrid">${cardsHtml}</div>`;
}

function filterSource(source, btn) {
  document.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.querySelectorAll('.news-card').forEach(card => {
    card.style.display = (source === 'all' || card.dataset.source === source) ? '' : 'none';
  });
}

// Auto-fetch on select change
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
    print("  FinPulse — Sector Financial News Aggregator")
    print("  http://127.0.0.1:5000")
    print("=" * 60)
    print("\nRequired packages:")
    print("  pip install flask httpx beautifulsoup4 lxml")
    print()
    pass
