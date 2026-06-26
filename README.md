<div align="right">

**English** · [繁體中文](README.zh-TW.md)

</div>

# Alpha Desk — Claude Code Investment Research Workspace (US Equities + Crypto)

An investment research workspace built on **Claude Code skills + MCP servers**, covering **US stocks / options and cryptocurrency**. It packages daily briefings, single-stock deep dives, crypto analysis, options strategy, and EV checks into repeatable slash commands — and constrains every investment conclusion with a **first-principles discipline** (falsifiable thesis → falsification conditions → probability distribution + EV) so output never degrades into narrative.

- **Who it's for**: individual investors / quants who trade US stocks / options / crypto themselves and want LLM assistance *with* discipline and verifiability
- **Output language**: **English by default**; append the `--cn` flag to any skill to switch that run to Traditional Chinese (繁體中文)
- **Data model**: **watchlist-driven** — a hand-maintained `watchlist.md` (tracked tickers + optional holdings) is the single source of truth for every skill, with **no broker integration**
- **Data sources**: MCP servers (real-time quotes, SEC, technical indicators, sentiment/fundamentals, prediction markets, CoinGecko, etc.) + FRED macro + EODHD fundamentals REST cache
- **Optional automation**: launchd generates and pushes a daily briefing to **Discord** (webhook) on every NYSE trading day

> ⚠️ **Not investment advice.** This project is an analysis and discipline tool; all output is for research reference only. You bear full responsibility for your own trading decisions and risk, and you supply your own API keys. See the disclaimer at the end.

> 🙏 **Attribution / derivative notice**: This workspace is derived from and customized off [PatrickSUDO/fadacai-portfolio](https://github.com/PatrickSUDO/fadacai-portfolio) (MIT). The two original in-house MCP servers (`technical` indicators, `eodhd` sentiment/fundamentals) are open-sourced at [fadacai-mcp-servers](https://github.com/PatrickSUDO/fadacai-mcp-servers).

---

## Key differences from upstream

| Aspect | Upstream fadacai-portfolio | This workspace (alpha-desk) |
|--------|----------------------------|------------------------------|
| Ticker source | `firstrade-server` MCP live positions | Manual `watchlist.md` (no broker) |
| Positions / journal | `journal/` auto position snapshots | Removed; watchlist is the only state |
| Delivery | Telegram + Gmail SMTP | **Discord webhook** |
| Asset classes | US stocks / options | US stocks / options **+ crypto** |
| Output language | Traditional Chinese only | **English default + `--cn` for Chinese** |
| Removed skills | — | `/portfolio-review`, `/trade-journal` |
| Added skill | — | `/crypto-analysis` |

---

## System architecture

```mermaid
flowchart TD
    User(["👤 User"])
    User -->|slash commands| Skills

    subgraph Skills ["⚡ Skills — Slash Commands"]
        direction LR
        B["/briefing<br/>quick · full · deep · push"]
        SA["/stock-analysis TICKER"]
        CA["/crypto-analysis SYMBOL"]
        OS["/options-strategy"]
        TODO["/todo · /ev-check"]
        MH["/mcp-health"]
    end

    Skills -->|shared run| Step0

    subgraph Step0 ["📋 Step 0 shared protocol (every skill)"]
        direction LR
        s0a["0a<br/>plan.md<br/>feedback/*.md"] --> s0b["0b<br/>load watchlist.md<br/>tickers + optional holdings"] --> s0e["0e<br/>first-principles discipline<br/>thesis · falsify · EV"]
    end

    subgraph Models ["🤖 AI model routing"]
        HAIKU["🟡 Haiku 4.5<br/>data-collector · mcp-health"]
        SONNET["🔵 Sonnet 4.6<br/>briefing quick+push · todo"]
        OPUS["🟠 Opus 4.8 (flagship)<br/>stock/crypto-analysis<br/>options · ev-check · briefing full/deep"]
    end

    s0e --> SONNET & OPUS
    Skills -->|"subagent_type: data-collector"| HAIKU

    subgraph MCP ["🔌 MCP Servers — external real-time data"]
        direction LR
        YF["📈 yfinance-advanced<br/>quotes · options · financials"]
        SEC["📋 sec-edgar-mcp<br/>filings · Form 4 · 8-K"]
        FMP["💹 fmp-mcp<br/>peers · movers"]
        TECH["📊 technical-mcp<br/>RSI · MACD · S/R"]
        EODHD["💬 eodhd-mcp<br/>sentiment + fundamentals + news"]
        PM["🎲 polymarket-mcp<br/>prediction-market odds"]
        CG["🪙 coingecko (optional)<br/>tokenomics · dominance"]
    end

    HAIKU -->|parallel calls (Retry 3x)| MCP

    subgraph KB ["📁 Knowledge Base — local files"]
        direction LR
        WL[("watchlist.md<br/>tickers + optional holdings")]
        PL[("plan.md<br/>sector targets · strategy queue")]
        FB[("feedback/<br/>research/style rules")]
        RES[("research/<br/>theses + thesis-ledger")]
    end

    s0a -->|read| PL & FB
    s0b -->|read| WL

    CODEX["🤖 Codex (opt-in)<br/>--codex flag<br/>B1 independent first-principles"]
    OPUS -->|opt-in| CODEX

    subgraph AutoSend ["📲 Daily auto-push (launchd)"]
        direction LR
        LAUNCHD["⏰ launchd<br/>NYSE trading days only<br/>Friday adds --codex"]
        RUNNER["🔧 briefing_runner.sh"]
        OUT_FILES["📄 briefing-out/<br/>*-full.md · *-discord.txt"]
        DISCORD["💬 Discord webhook<br/>emoji plain text · >2000 chars auto-split"]
    end

    LAUNCHD --> RUNNER --> SONNET
    SONNET -->|--send flag| OUT_FILES --> DISCORD
```

---

## watchlist.md — the source of truth

Every skill reads "what to analyze" from `watchlist.md`. It's a hand-maintained markdown file with a stock section and a crypto section:

```markdown
## Stocks / Options
| Ticker | Thesis tag | Shares | Avg Cost | Notes |
|--------|-----------|--------|----------|-------|
| NVDA   | Data-center AI compute, 70%+ gross margin | 100 | 120.50 | Conviction hold |
| AVGO   | Custom ASIC + software cash flow |      |          | Tracking only |

## Crypto
| Symbol | Thesis tag | Qty | Avg Cost | Notes |
|--------|-----------|-----|----------|-------|
| BTC    | Fixed supply + ETF net inflows | 0.5 | 60000 | Core |
```

- **Holdings columns (Shares / Avg Cost / Qty) are optional**: filled in → skills compute portfolio weight, concentration, and unrealized P&L; left blank → ticker-level research only (valuation / technicals / catalysts).
- Start by copying `watchlist.example.md` → `watchlist.md`. `watchlist.md` is gitignored (your holdings are never committed).

---

## Quick start

### Prerequisites
- **[Claude Code](https://docs.claude.com/claude-code)** CLI
- **Python 3.10+** and **[uv](https://github.com/astral-sh/uv)** (recommended for running Python MCP servers)
- macOS (the `launchd` auto-push is macOS-only; everything else is cross-platform)

### Install
```bash
# 1. clone
git clone <this-repo-url> alpha-desk && cd alpha-desk

# 2. Python deps
pip3 install -r tools/requirements.txt

# 3. watchlist
cp watchlist.example.md watchlist.md   # fill in your tickers

# 4. (optional) env vars for auto-push / macro / crypto caches
cp .env.example .env                    # fill keys per the comments

# 5. launch
claude
> /mcp-health        # confirm MCP connections first
> /briefing          # run your first briefing (English output by default)
> /briefing --cn     # add --cn for Traditional Chinese output
```

### MCP servers
| Server | How to get it | Key needed? |
|--------|---------------|:-----------:|
| `yfinance-advanced` | `uvx yfinance-mcp` (no clone; also quotes `BTC-USD`) | ❌ |
| `sec-edgar-mcp` | `uvx sec-edgar-mcp` (set your email as the user-agent) | ❌ |
| `fmp-mcp` | [Financial-Modeling-Prep-MCP-Server](https://github.com/imbenrabi/Financial-Modeling-Prep-MCP-Server) (clone + build) | ✅ free tier |
| `technical-mcp` | [fadacai-mcp-servers `/technical`](https://github.com/PatrickSUDO/fadacai-mcp-servers/tree/main/technical) | ❌ |
| `eodhd-mcp` | [fadacai-mcp-servers `/eodhd`](https://github.com/PatrickSUDO/fadacai-mcp-servers/tree/main/eodhd) | ✅ EODHD token |
| `polymarket-mcp` | `uvx polymarket-mcp` | ❌ |
| `coingecko` *(optional)* | `npx -y @coingecko/coingecko-mcp` (official npm, needs Node; demo endpoints need no key). Note: `tools/fetch_crypto.py` already pulls the CoinGecko REST API, so this MCP is fully optional | optional |

> Missing any one server won't break the framework — `/mcp-health` flags what's unavailable, and skills have a built-in retry → health check → WebSearch fallback. When `coingecko` isn't configured, `/crypto-analysis` automatically falls back to yfinance (`BTC-USD`) + WebSearch.

### Environment variables (`.env`, all optional)
| Variable | Purpose | Get it from |
|----------|---------|-------------|
| `DISCORD_WEBHOOK_URL` | Push briefings to Discord | Channel → Integrations → Webhooks → New Webhook |
| `FRED_API_KEY` | Macro snapshot (Fed Funds / yield curve / HY OAS / VIX) | [FRED free signup](https://fred.stlouisfed.org/docs/api/api_key.html) |
| `EODHD_API_TOKEN` | Fundamentals + news cache (`fetch_fundamentals.py` / `fetch_news.py`) | [EODHD](https://eodhd.com/financial-apis/) |
| `COINGECKO_API_KEY` | Higher CoinGecko rate limit (Demo plan is free; works without it) | [CoinGecko API](https://www.coingecko.com/en/api) |
| `BRIEFING_*` / `FRIDAY_CODEX` / `RETRY_MAX` | launchd auto-push behavior | see `.env.example` |

---

## Command reference

| Command | Purpose | Model | Est. time |
|---------|---------|-------|-----------|
| `/briefing` | Quick daily briefing (technicals + alerts + plan progress) | Sonnet | ~1 min |
| `/briefing full` | + sentiment + market movers + prediction markets | Opus | ~3 min |
| `/briefing deep` | + SEC + single-stock deep dives | Opus | ~5 min |
| `/briefing push` | Discord push format (emoji plain text, writes two briefing-out/ files) | Sonnet | ~2-3 min |
| `/briefing push --send` | Same, and actually pushes to Discord | Sonnet | ~2-3 min |
| `/stock-analysis TICKER` | Single-stock deep dive (multi-ticker compare; `--current` reads watchlist) | Opus | ~2 min |
| `/crypto-analysis SYMBOL` | Crypto deep dive (tokenomics / supply / on-chain / dominance) | Opus | ~2-3 min |
| `/options-strategy TICKER STRATEGY` | Options strategy calc (E_adj ranking) | Opus | ~1-2 min |
| `/todo` | Priority action list for next-day / intraday / after-hours | Sonnet | ~1 min |
| `/ev-check [7d\|14d\|30d]` | Forced first-principles probability distribution + watchlist EV | Opus | ~1 min |
| `/mcp-health` | Test all MCP server connections | Haiku | ~30 sec |

**`--cn` flag:** append to any skill to render that run's output entirely in **Traditional Chinese** (English is the default). e.g. `/stock-analysis NVDA --cn`
**`--send` flag:** append to any briefing tier to auto-push to Discord after running. e.g. `/briefing full --send`
**`--codex` flag:** append to any analysis skill to trigger an independent Codex first-principles analysis (B1). `--codex-adversarial` triggers stress-test mode.
**Model switching:** if the harness doesn't auto-apply the frontmatter model, switch manually with `/model sonnet` or `/model opus`. Run `/compact` when session context exceeds ~100k.

---

## Usage examples

```
# Daily routine
/briefing                        ← quick scan (Sonnet, ~1min, English)
/briefing --cn                   ← same, Traditional Chinese output
/briefing deep                   ← full version with SEC + stock analysis (Opus)
/briefing push --send            ← generate and push to Discord
/briefing full --send --codex    ← full + Codex + push

# Stock / crypto research
/stock-analysis PLTR
/stock-analysis ANET CRWD        ← compare two, ranked by EV
/crypto-analysis BTC             ← crypto first-principles analysis
/crypto-analysis BTC ETH         ← compare two coins
/crypto-analysis SOL --codex     ← + independent Codex second opinion

# Options
/options-strategy PLTR sell-put
/options-strategy MU leaps

# Manually resend a briefing
python3 tools/send_briefing.py latest          # resend the latest one
DRY_RUN=1 python3 tools/send_briefing.py latest # dry-run (no actual send)
```

---

## Discord auto-push

On every NYSE trading day at a fixed time (17:00 system-local CET/CEST) it pushes an intraday decision summary to a Discord channel. Fridays add a `--codex` second opinion. Full setup in [`docs/briefing-auto-send.md`](docs/briefing-auto-send.md).

**Quick setup:**
1. Discord channel → ⚙ Edit Channel → Integrations → Webhooks → New Webhook → Copy URL
2. Put `DISCORD_WEBHOOK_URL=...` in `.env` (one webhook is enough — no bot token needed)
3. `cp tools/launchd/com.fadacai.briefing.plist ~/Library/LaunchAgents/`, fix the paths, then `launchctl load`

**Pipeline:**
```
launchd → briefing_runner.sh
    ├── check_trading_day.py        ← skip NYSE holidays
    ├── Friday → --codex
    ├── [non-fatal] fetch_macro.py / earnings_history.py / fetch_fundamentals.py
    ├── [non-fatal] fetch_news.py / fetch_crypto.py
    └── claude -p "/briefing push --send $CODEX_FLAG"
            └── send_briefing.py → Discord webhook (>2000 chars auto-split) + send-log.jsonl
```

**Output files:** `briefing-out/YYYY-MM-DD-full.md`, `-discord.txt`, `send-log.jsonl`, `launchd.log/.err` (the entire `briefing-out/` is gitignored).

---

## MCP retry policy
On failure → retry 3× → health check → fall back to WebSearch/WebFetch, marking `⚠️ [server] MCP unavailable` in the output.

## Key local files
| File / directory | Purpose | How it's updated |
|------------------|---------|------------------|
| `watchlist.md` | **Source of truth**: tracked tickers + optional holdings (**gitignored**; template `watchlist.example.md`) | manual |
| `plan.md` | Investment plan: sector targets, strategy queue, watch list | manual |
| `feedback/` | Research / style rules, read by every skill on every run | manual |
| `research/` | Theses + `thesis-ledger.json` (thesis tracking ledger) | manual / tooling |
| `.env` | Discord webhook + API keys (**gitignored**, `cp .env.example`) | manual |
| `tools/` | Pipeline scripts: `send_briefing.py`, `briefing_runner.sh`, `fetch_macro.py`, `fetch_fundamentals.py`, `fetch_news.py`, `fetch_crypto.py`, `earnings_history.py`, `watchlist_tickers.py`, `thesis_ledger.py`, `generate_html.py` | git tracked |
| `briefing-out/cache/` | Pre-loaded caches: macro / earnings / fundamentals / news / crypto — the briefing's zero-latency data layer | auto (runner + launchd) |
| `CLAUDE.md` | Full project instruction manual (Step 0 protocol, MCP policy, model routing) | manual |

---

## Methodology highlights

The core of this framework isn't "ask an LLM for an opinion" — it's layered discipline that forces every conclusion onto verifiable ground truth:

- **First-principles discipline (Step 0e)** — before any Verdict, three questions are mandatory: ① a core thesis (one **falsifiable proposition**, not narrative) ② falsification conditions (2–3 falsifiable observation points) ③ a probability distribution + EV (computed by the `probability-honesty-checker` agent, which bans default bell shapes and qualitative hedging like "slightly bullish"). **Asset-agnostic** — stocks and crypto share the same discipline.
- **Three-anchor Fair PE valuation (stocks)** — no hand-waved PE multiples; triangulate three independent anchors: A1 market-implied PE / A2 PEG-justified growth multiple / A3 analyst-PT-implied PE. Base = median; Bull = max × 1.25; Bear = min × 0.70.
- **Crypto-native valuation (`/crypto-analysis`)** — crypto has no earnings and no PE, so it uses: supply schedule / tokenomics (circulating vs max supply, emission rate), market structure (BTC dominance, total market cap), network usage (TVL / active addresses / fees), flows (ETF / stablecoins), and cycle bands. Three framing anchors → synthesized into EV via a probability distribution.
- **Thesis Ledger (`tools/thesis_ledger.py`)** — register each thesis with a trigger point; on its due date (earnings / ETF decision) it auto-fetches the actual numbers to grade it passed/failed and accumulate a hit rate. See [`docs/thesis-ledger.md`](docs/thesis-ledger.md).
- **A4 self-built valuation anchor (stocks, sanity / divergence flag)** — in the same API call, `fetch_fundamentals.py` computes `own_fwdEPS` (historical CAGR × net margin ÷ shares, ignoring analyst estimates entirely), isolating "my earnings view vs the Street's." It never enters EV — purely a divergence flag.
- **Full-text news + P3 signal extraction** — `fetch_news.py` caches article bodies; the Deep tier / stock-analysis extract **already-quantified statements** from the body + SEC 8-K + earnings transcripts, with a mandatory `raw_quote` (≤120 chars verbatim). Anti-hallucination lock: **no raw_quote = no signal = not logged.**

## How to extend
- **Add a skill**: create `.claude/skills/<name>/SKILL.md` with frontmatter `user_invocable: true` + `description`, following the Step 0 protocol in `CLAUDE.md`. The Codex second-opinion path needs a mirror at `.agents/skills/<name>/SKILL.md`.
- **Add a data agent**: use `data-collector` (Haiku) for pure data-fetching subagents.
- **Add a tool**: put it in `tools/`, prefer pure stdlib (e.g. `thesis_ledger.py`, `watchlist_tickers.py` have zero dependencies).
- **Tune research style**: `feedback/*.md` (personal, gitignored) is read by every skill on every run — that's where you feed your preferences.

---

## License & derivative notice

Released under the **MIT License** (see [`LICENSE`](LICENSE)).

This workspace is a derivative of [PatrickSUDO/fadacai-portfolio](https://github.com/PatrickSUDO/fadacai-portfolio) (MIT, Copyright © 2026 fadacai), substantially customized: removed broker integration and portfolio management, switched to watchlist-driven, moved delivery to Discord, added cryptocurrency research, and changed the default output language to English. The original MIT copyright notice is retained in `LICENSE`.

## Disclaimer

This project is a **personal investment-research and discipline tool**. All output is for research reference only and **does not constitute investment advice, an offer, or a solicitation**. Investing carries risk; you bear full responsibility for your own trading decisions and outcomes. The author and contributors are not liable for any losses arising from use of this tool. You supply and safeguard all your own API keys and credentials; this repo contains no keys.
