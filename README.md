# 🐟 Starfish — AI Market Oracle

A real-time stock analysis platform powered by a **3-AI orchestration pipeline** (DeepSeek R1 → Llama 3.3 → Qwen3), live RSS financial news from 8 sources, and YouTube live streams — all in a single Python/Flask app.

---

## ✨ Features

| Feature | Details |
|---|---|
| 📈 **Interactive Charts** | Candlestick & line charts via Plotly — SMA, Bollinger Bands, RSI, MACD, Volume |
| 🤖 **3-AI Pipeline** | DeepSeek R1 (Technical) → Llama 3.3 (Macro+News) → Qwen3 (Synthesis) — runs automatically |
| 📰 **Live RSS Feeds** | Reuters, Bloomberg, CNBC, FT, WSJ, MoneyControl, Economic Times, Seeking Alpha |
| 📺 **Live TV Streams** | CNBC TV18, Bloomberg Global, Yahoo Finance (YouTube embeds) |
| 💹 **Market Data** | Yahoo Finance scraper with crumb auth, v8/v7 API fallback, yfinance fallback |
| ⚡ **SSE Streaming** | Pipeline results stream step-by-step in real time — no page reload |

---

## 🗂 Project Structure

```
starfish/
├── api/
│   └── index.py          # Flask app (Vercel entry point)
├── requirements.txt      # Python dependencies
├── vercel.json           # Vercel deployment config
├── .gitignore
└── README.md
```

---

## 🚀 Deploy to Vercel (Recommended)

### 1. Get an OpenRouter API Key
Sign up at [openrouter.ai](https://openrouter.ai) → Dashboard → Keys → Create key.  
The free tier includes DeepSeek R1, Llama 3.3 70B, and Qwen3 Coder.

### 2. Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit — Starfish AI Market Oracle"
gh repo create starfish --public --push
# or: git remote add origin https://github.com/YOUR_USERNAME/starfish.git && git push -u origin main
```

### 3. Import into Vercel

1. Go to [vercel.com/new](https://vercel.com/new)
2. Import your GitHub repo
3. Framework: **Other** (auto-detected)
4. Add Environment Variable:
   - Key: `OPEN_ROUTER_API_KEY`
   - Value: `sk-or-v1-xxxxxxxx...`
5. Click **Deploy**

> ⚠️ **Vercel Hobby plan has a 10-second function timeout.** The AI orchestration pipeline (3 sequential LLM calls) takes 30–90s.  
> **Upgrade to Vercel Pro** (60s timeout) or use the `maxDuration` setting below.

### 4. Increase Function Timeout (Vercel Pro)

Add to `vercel.json`:
```json
{
  "functions": {
    "api/index.py": {
      "maxDuration": 300
    }
  }
}
```

---

## 💻 Run Locally

```bash
# 1. Clone / download
git clone https://github.com/YOUR_USERNAME/starfish.git
cd starfish

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set your OpenRouter key
export OPEN_ROUTER_API_KEY="sk-or-v1-xxxxxxxx..."
# Windows PowerShell: $env:OPEN_ROUTER_API_KEY="sk-or-v1-..."

# 5. Run
python api/index.py             # runs on http://127.0.0.1:5000
# or:
flask --app api/index run --debug
```

---

## 🤖 AI Orchestration Pipeline

The pipeline fires **automatically** when a page loads (1.2s delay). Each model has a specific role and receives the previous model's output:

```
┌─────────────────────────────────────────────────┐
│  STEP 1 — DeepSeek R1  (Technical Analyst)      │
│  Input : OHLCV + all indicators (30d data)      │
│  Output: verdict, key levels, indicator signals │
└───────────────────┬─────────────────────────────┘
                    │ passes findings down
┌───────────────────▼─────────────────────────────┐
│  STEP 2 — Llama 3.3 70B  (Macro Strategist)     │
│  Input : DeepSeek findings + live RSS headlines │
│  Output: macro verdict, news impact, catalysts  │
└───────────────────┬─────────────────────────────┘
                    │ passes findings down
┌───────────────────▼─────────────────────────────┐
│  STEP 3 — Qwen3 Coder  (Quant Synthesizer)      │
│  Input : Both prior analyses                    │
│  Output: BUY/SELL/HOLD, 5 price targets,        │
│          conviction, action plan, AI agreement  │
└─────────────────────────────────────────────────┘
```

Results stream live via **Server-Sent Events** — you see each step complete in real time.

---

## 📰 RSS Sources

| ID | Source | Region |
|---|---|---|
| `reuters` | Reuters Business | Global |
| `bloomberg` | Bloomberg Markets | Global |
| `cnbc` | CNBC Markets | US |
| `ft` | Financial Times | UK/Global |
| `wsj` | WSJ Markets | US |
| `moneyctrl` | MoneyControl | India |
| `ecdimes` | Economic Times | India |
| `seeking` | Seeking Alpha | US |

---

## 🔑 Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPEN_ROUTER_API_KEY` | ✅ Yes | Your OpenRouter API key |

---

## ⚠️ Known Limitations

- **Vercel Hobby** has 10s function timeout — AI pipeline needs Pro (60s) or higher
- Yahoo Finance may occasionally block requests; the scraper has 3-layer fallback (v8 → v7 → yfinance lib)
- RSS feeds that require JS rendering (e.g. some FT pages) may return no items — fallback to other sources
- Rate limits: 20 RPM / 200 RPD per model (configurable in `app.py`)

---

## 📄 License

MIT — do whatever you want with it.

---

*Built by Anton Beski*
