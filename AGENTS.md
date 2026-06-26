# Fundamental Allocation Study - Project Instructions

## Project Overview
This is an investment research workspace for US stocks, options, and cryptocurrency. It is **watchlist-driven**: the user maintains a manual `watchlist.md` (tickers + optional holdings) which is the source of truth for every skill — there is no broker integration. The user researches equities/options and crypto, and reasons about ideas through a first-principles + expected-value lens.

## Language & Format
- **Output language resolution (applies to EVERY skill, governs all per-skill output instructions):**
  - **Default: English.** All reports, briefings, analysis, and Verdicts are written in English unless a switch below applies.
  - **`--cn` flag → Traditional Chinese (繁體中文).** If the user's invocation includes `--cn` (or `--zh`), render that entire run's output in Traditional Chinese.
  - **Follow the user's language otherwise.** If the user writes their request in Chinese (and no flag is given), respond in Traditional Chinese; if in English, respond in English.
  - This rule **overrides** any "繁體中文輸出 / Traditional Chinese output" line still present in individual SKILL.md files — treat those as "use the resolved output language," not a hard Chinese mandate.
- Thread/social media posts: plain text only, NO markdown, NO tables
- Reports and analysis: markdown tables are fine

## Workflow
1. `/briefing` — quick daily check (~1 min); `/briefing full` (~3 min); `/briefing deep` (~5 min)
   - `/briefing push` — Discord push tier (~2-3 min)：盤中推送專用，產出 briefing-out/ 兩個檔案
   - `--send` 旗標（任何 tier 可加）：執行完後推送 Discord（webhook）
   - 例：`/briefing push --send`、`/briefing full --send`
   - launchd 每個交易日 CEST 17:00 自動執行 `/briefing push --send`（週五加 `--codex`）
   - Setup 文件：`docs/briefing-auto-send.md`
2. `/stock-analysis TICKER` — individual stock deep dive（`/stock-analysis TICKER1 TICKER2` 比較）
3. `/crypto-analysis SYMBOL` — cryptocurrency deep dive（tokenomics / 供給 / 鏈上 / 主導率）
4. `/options-strategy TICKER STRATEGY` — options calculation (supports multi-ticker comparison)
5. `/ev-check [horizon]` — watchlist 的機率分布 + EV 檢查
6. `/todo` — 下一個交易日的優先行動清單
7. `/mcp-health` — test all MCP server connections

### Codex 第二意見（opt-in `--codex` / `--2nd`）

Add `--codex` to any of the above (except `/mcp-health`) to append a Codex second-opinion section:

- **B1. 獨立第一性分析（預設）** — Codex 在**不知道 Claude 結論**的情況下，獨立執行 Step 0e（thesis / 證偽條件 / 機率分布 / EV / Verdict），只給它 raw data。然後 Claude 與 Codex 兩個獨立輸出**並排比較**，找出真實共識 vs 真實分歧。所有分析型 skill 適用。
- **B2. 機會掃描** (`/codex:rescue`) — surface hot themes/tickers not on the current watchlist. `/briefing full/deep`, `/todo` only.
- **B3. 輪動分析** (`/codex:rescue`) — sector + stock rotation (leading/lagging vs SPY, money flow, 3 actionable rotation moves). Same skills.

#### 為什麼預設用「獨立第一性」而不是「對立面審查」

舊版 B1 是 `/codex:adversarial-review`（攻擊 thesis），這是 **confirmation bias by design**：要它找 bug 它一定找出 bug，即使 thesis 完全成立。結果是兩邊「分歧」很多但大部分由 framing 製造，不是真實見解衝突。

獨立第一性分析讓 Claude 和 Codex 從同樣 raw data 出發、各自跑 Step 0e、不知道對方結論。**真實共識 = 高信心**；**真實分歧 = 值得深入的學習點**。

#### 進階：`--codex-adversarial`（opt-in 壓力測試）

若需要對「兩邊已對齊的結論」做進一步壓力測試（例如重大資金決策前），可改用 `--codex-adversarial`（或 `--codex-adv`）觸發舊版對立面審查。**僅在有意識需要 attacker mode 時使用**，預設 `--codex` 不跑 adversarial。

#### Codex 呼叫方式（CLI，所有 skill 共用 — 取代舊 plugin 路徑）

⚠️ **不要用 `subagent_type: "codex:codex-rescue"` 或 `/codex:rescue`**。實測（2026-06-07）那條路徑會載入 `~/.codex/config.toml` 的 `superpowers@openai-curated` plugin，強制「回應前必須 invoke skill」+ 全域 `model_reasoning_effort = "xhigh"`，把整個 turn 燒在讀檔 preamble，**不產出分析**。

改用 `codex exec` CLI，**強制關掉 superpowers + 降 effort**：

```bash
codex exec --color never --skip-git-repo-check --sandbox read-only \
  -c 'plugins."superpowers@openai-curated".enabled=false' \
  -c model_reasoning_effort=medium \
  "$(cat <PROMPT_FILE>)" > <OUT_FILE> 2>&1
```

規則：
1. **Prompt 第一行強制加**：`ANSWER DIRECTLY FROM THE DATA BELOW. Do NOT read files, do NOT invoke skills, do NOT run shell commands, do NOT use any tools. Output the analysis immediately.`（雙保險，即使 superpowers 漏關也不讀檔）
2. **B1/B2/B3 並行**：各寫一個 prompt 檔，用 `run_in_background` 同時跑，輪詢 `grep -c "tokens used"` 判完成
3. **抽取回覆**：`awk '/^codex$/{f=1} f' <OUT_FILE> | sed '/tokens used/q'`（去掉 echo 回來的 prompt + startup banner）
4. **中性化**：B1 prompt 只給 raw watchlist + fact 數據，不含 Claude 結論（per `feedback/codex-prompt-neutrality.md`）
5. **失敗 → 跳過**：輸出 `⚠️ Codex 不可用：[error]，跳過第二意見` 後照常輸出主分析
6. `hook: SessionStart Failed` 是 peon-ping 音效 hook 在非互動下的無害噪音，忽略
7. **B1 機率分布反偷懶（必嵌 prompt）**：Codex 走一次性 prompt 無我們的 `probability-honesty-checker` agent，會落回 default mirror（25/50/25）。故 B1 prompt 的機率分布段**必須內嵌 5 步強制流程 + 禁用 default mirror shape**（見各 skill B1 模板的「嚴禁偷懶」段，源自 `feedback/probability-distribution-honesty.md`）。比較 Claude vs Codex EV 前先確認 Codex 機率非 default，否則分歧是「Codex 偷懶」而非真實見解衝突。

## Key Files
- `watchlist.md` — **所有 skills 的真實來源**：追蹤的標的（股票/加密）+ 選填持倉（股數/成本）。手動維護；gitignored（範本 `watchlist.example.md`）
- `plan.md` — 投資計畫（板塊目標、策略佇列、觀察清單、策略原則）— 只在用戶要求時更新
- `feedback/` — 研究/風格偏好，所有 skills 每次必讀
- `research/` — 投資論文與研究筆記

## HTML 報告站工作流

每份報告輸出 markdown（source of truth）後自動轉為 HTML，push 到獨立 private repo 部署為 Netlify 靜態網站。

### 工具
```bash
python3 tools/generate_html.py briefing 2026-06-10 [--push]
python3 tools/generate_html.py stock-analysis briefing-out/stock-analysis-NVDA-2026-06-10.md [--push]
python3 tools/generate_html.py crypto-analysis briefing-out/crypto-analysis-BTC-2026-06-10.md [--push]
python3 tools/generate_html.py options-strategy briefing-out/options-strategy-NVDA-2026-06-10.md [--push]
```
- 無 `--push`：只在 `briefing-out/html/` 存一份本地 HTML
- 有 `--push`：同步到 `$REPORTS_REPO_PATH` 並 git push（Netlify 自動部署）
- `send_briefing.py` 在 `--send` 流程中自動呼叫 `generate_html briefing --push`，Discord 訊息末自動附連結

### 環境變數（.env，絕不 commit 到主 repo）
```
REPORT_SITE_TOKEN=<32-hex-token>          # URL 混淆用，等同隱私鎖
REPORT_SITE_URL=https://reports.patricksudo.com
REPORTS_REPO_PATH=/path/to/fadacai-reports  # private repo local clone
```

### 隱私原則
- Reports repo 必須是 **private**，token 只存在 .env 與 repo 目錄名
- 網站根目錄放空白 decoy index.html；所有頁面含 `noindex,nofollow` meta
- 安全標頭由 reports repo 的 `_headers` 設定（HSTS、`X-Robots-Tag: noindex`、`X-Frame-Options: DENY`、`X-Content-Type-Options: nosniff`），Netlify 部署時套用
- `cache/`、`send-log.jsonl`、`launchd.log`、codex prompt/out 等敏感快取**不上傳**到 reports repo

## Step 0 統一規範（所有 skills 共用）

### 0a. 每次必做
- 讀取 `plan.md` — 了解策略佇列與板塊目標
- 讀取 `feedback/*.md` — 套用研究/風格偏好

### 0b. 載入 watchlist（取代即時持倉）
- 讀取 `watchlist.md` — 這是**所有 skills 的真實來源**。沒有 broker、沒有即時持倉抓取。
- watchlist 含兩類條目：
  - **追蹤標的**（純研究，無持倉）— 只有 ticker/symbol + 選填 thesis 標籤
  - **持倉標的**（選填）— 額外帶 `shares` / `avg_cost`（及加密的 `qty`）。用戶手動維護。
- **持倉欄位是選填的。** 凡需要組合權重 / 集中度 / 損益% 的分析：
  - 若 watchlist 有 `shares`/`avg_cost` → 用它們算 market value、% 權重、未實現損益
  - 若沒有 → **跳過**權重/集中度/損益段，只做標的層級的研究（估值、技術、catalyst），並標記「（無持倉資料，略過組合層級分析）」
- 不存在 `watchlist.md` → 提示用戶用 `watchlist.example.md` 建立，並（若用戶有給 ticker）以該批 ticker 當臨時 watchlist 繼續。

### 0c.（已移除）持倉變動偵測 / journal
- 本工作區無 broker，不做倉位變動偵測，也不維護 `journal/`。watchlist 即唯一狀態。

### 0e. 第一性原理紀律（Verdict / Recommendation / Action 前必做）

在輸出任何投資結論之前，**強制**回答三個第一性問題（First-Principles Discipline）：

1. **核心 thesis 是什麼？**
   - 用 1 句可驗證的陳述句（**非 narrative，非 adjective**）
   - ❌ 反例：「AI 帶動需求」「股票超買」「題材熱絡」
   - ✅ 範例：「全球資料量 2024→2028 從 150ZB→290ZB，冷資料佔 80%+，HDD per TB 成本比 SSD 低 4-5x」

2. **這個 thesis 在什麼條件下會被證偽？**
   - 列出 2-3 個 **falsifiable 觀察點**（可量化的指標、事件、時程）
   - ❌ 反例：「市況不好就錯」
   - ✅ 範例：「下次財報 HDD ASP 不再上漲、HAMR 60TB 量產延後、Hyperscaler capex 下修 >10%」

3. **目前 Verdict 在多大機率上 conditional 在 thesis 成立？**
   - 給**機率分布而非單點**（不寫「可能會漲」而是 60% 看多 / 25% 中性 / 15% 看空）
   - 算 expected value：Σ(機率 × 各情境公允價)，與現價比較
   - **強制呼叫 `probability-honesty-checker` agent**（見下方）— 不可手動套機率
   - **Fair PE 三錨點推導（不可手寫猜測）：** A1=EODHD `pe_ratio`（現行市場隱含）；A2=`peg_ratio×成長率`（成長合理倍數，AI龍頭目標PEG 1.5，其餘 1.0）；A3=`wall_street_target÷forward_EPS`（分析師隱含）。**A3 的 base forward_EPS 取真實賣方共識：`fundamentals-snapshot.json forward_estimates.curr_fy.eps_avg`（缺→next_fy.eps_avg，再缺→`eps_ttm×(1+growth)` 近似）；cache `self_valuation.a3_fwdeps_source` 已標來源，勿手推。** 任一錨回 0.0/null → 丟棄。基準Fair PE=median(A1,A2,A3)；樂觀=max 上限current_PE×1.25；悲觀=min 下限current_PE×0.70。Forward EPS：樂觀=base×(1+min(avg_surprise_pct,15%))；悲觀=base×(1−5%~10%)。
   - **A4 自建錨（sanity/divergence flag，不進 median，不進 EV）：** 從 `fundamentals-snapshot.json self_valuation` 讀取（`tools/fetch_fundamentals.py` 已在 cache 計算）。`own_fwdEPS = projected_revenue × net_margin ÷ shares`，revenue 用歷史 CAGR 淡化向 8% terminal，**完全不看分析師 estimate**。`own_target_price = own_fwdEPS × base_FairPE(median(A1,A2,A3))`。`A4vsA3% = (own_target − wall_street_target) / wall_street_target`——隔離「我的盈利觀 vs Street 盈利觀」（倍數固定）。`confidence=unavailable` → `(self-val N/A)`；`low` → `⚠️低信心（高波動）`；`ok` → 正常顯示。

**為什麼這條重要：**
- Claude 的分析、Codex 的 adversarial review 都會帶 framing 偏差
- narrative 層的辯論（「該買 vs 該避」）永遠分歧，第一性是繞開兩者的 ground truth
- 連續做不到這三題 = Verdict 是 narrative + heuristic + framing 的產物，不可靠

**⚠️ 機率分布強制流程（briefing / stock-analysis / crypto-analysis / todo / ev-check 適用）：**

凡輸出機率分布或 EV，必須先呼叫：

```
Agent(subagent_type: "probability-honesty-checker", prompt: "...")
```

或對組合整體用 `/ev-check [horizon]`。Agent 會強制執行 6 步流程：
1. Input Enumeration（8 項齊全才能進下一步）
2. 形狀反推（從事實 mapping，禁止 default bell shape）
3. 各 catalyst 的 conditional 機率（顯式 base rate）
4. Aggregated 三情境合成（sum check = 100%）
5. EV 顯式 Σ 計算（中點 = 區間算術平均）
6. Self-audit checklist 全勾

**禁止偷懶寫法**（Agent 與主 skill 都不可寫）：
- ❌ 30/45/25、35/45/20、20/45/35、25/50/25（default mirror shape，無依據時禁用）
- ❌ 「略偏正」「略偏負」「中性偏多」「應該會」「不確定性高」（質性語言）
- ❌ 跳過 Input Enumeration 直接給機率
- ❌ EV 寫成文字而非顯式 Σ 數字

**輸出格式（所有 Verdict 前置）：**
```
### 第一性檢查
- **核心 thesis：** [1 句可驗證命題]
- **證偽條件：** [2-3 個 falsifiable 觀察點]
- **機率分布：** [由 probability-honesty-checker agent 算出，含 8 項輸入 + 形狀反推 + EV Σ]
```

用戶 push back「你真的有算嗎」時的處理：
- 不辯解、不重組原數字
- 重跑 agent，明確要求 audit checklist 全勾
- 發現原本確實偷懶 → 老實承認 + 顯示新算（見 feedback/probability-distribution-honesty.md）

**⚠️ Agent 註冊限制（重要）：**
- Claude Code session 啟動時載入 `.claude/agents/` 目錄，**session 內新增的 agent 檔案不會被動態 picked up**
- 若呼叫返回 `Agent type 'X' not found`：(1) 確認檔案在 `.claude/agents/X.md`，(2) 該 session 暫時用 workaround，(3) 下次 session 自動載入

**Workaround：當 probability-honesty-checker agent 不可用時**
直接呼叫 `general-purpose` agent，並把 `.claude/agents/probability-honesty-checker.md` 的內容當 prompt 前綴傳入：

```
Agent(
  subagent_type: "general-purpose",
  prompt: "<貼上 probability-honesty-checker.md 從 '# Probability Honesty Checker' 開始的全部內容>

  ---

  以下是本次任務的輸入：

  [Step 1 九項輸入...]
  [額外 context...]

  請按 6 步流程執行。"
)
```

紀律不打折 — 6 步 + audit checklist 全勾的要求對 general-purpose agent 同樣適用。

### 0f. Thesis Ledger（thesis 追蹤與到期驗收）

第一性檢查產出的可驗證 thesis 不是寫完就忘 — 凡帶**明確時間/事件觸發點**的 thesis（「請在財報後/N 日後檢視 X」）都登錄到帳本 `research/thesis-ledger.json`，到期自動回頭抓實際數字驗收（passed/failed/partial），結果驅動下一步 actionable。

- 工具：`tools/thesis_ledger.py`（去重、碰撞攔截、到期/過期掃描、狀態轉換、統計全在程式層，**Claude 不手改 JSON**）
- 去重 key = `ticker:slug`；同 key 但 thesis 差太多 → exit code 2 碰撞，改 slug 或 `supersede`
- 逾期 >30 天未驗收 → 自動 `expired`（當作無結果，不算命中率分母）
- **驗收（每次 briefing 自動跑）**：`thesis_ledger.py due` → 對到期項抓數判定 → `resolve`；抓不到新數 → `reschedule` 不猜 verdict
- **登錄（briefing 收尾）**：`list` 看既有 slug → `add`
- **Signal-inference 來源**：從 news body / SEC 8-K / 逐字稿抽**已量化陳述**推導的 thesis，登錄時加 `--source signal-inference --ev "signal: <metric> <value>, <source>, conf=<confidence>"`。僅 `confidence ∈ {high, medium}` 且有明確前瞻 trigger + 強制 `raw_quote`（≤120 字逐字）才登錄；`low` 只在文字呈現。`stats --source signal-inference` 可量測新聞推導命中率（閉環驗證 P3 價值）。反幻覺鎖：無 raw_quote = 無 signal = 不登錄。
- **Resolve 附加估值影響欄位（選填，有數就帶）：**
  ```
  python3 tools/thesis_ledger.py resolve --id <id> --verdict passed|failed|partial \
    --actual "實際數字" --note "判讀" --next-action "操作" \
    --fair-value-before <float> --fair-value-after <float> \
    --price-impact-pct <float> --impact-decomp "thesis +X%/multiple −Z%=net −W%"
  ```
  passed→公允價上修（recompute D1 三錨點）；failed→下修；partial→拆分 thesis 成分 vs 倍數成分（impact_decomp）。數字存入 history[]，long-term queryable via stats。
- 詳見 `docs/thesis-ledger.md`

## Investment Style
- 主軸：AI/半導體、高成長科技（無板塊上限，單一個股 > 10% 才提醒）
- 加密：BTC/ETH 為核心，選擇性高信念 alt（thesis 必須可驗證，非 narrative）
- 避險：基建、航太、貴金屬、核能（小比例平衡）
- Strategies: LEAPS (stock replacement, deep ITM delta 0.72-0.85), Bull Put Spread, Bull Call Spread, Covered Calls, PMCC
- Risk: 單一持倉 > 10% flagged as over-concentrated（僅在 watchlist 有持倉資料時計算）

## MCP Tools Available
- `mcp__yfinance-advanced__*` — real-time quotes, options chains, financials, news, recommendations (primary). Also quotes crypto via `BTC-USD` / `ETH-USD` style tickers.
- `mcp__sec-edgar-mcp__*` — SEC filings, XBRL financials, insider trading (Form 4), 8-K events, segment data
- `mcp__fmp-mcp__*` — stock peers, market movers, company profiles (free tier; most endpoints need paid plan)
- `mcp__technical-mcp__*` — technical indicators (RSI, MACD, Bollinger Bands, ATR, momentum score, support/resistance)
  - `get_technical_indicators(ticker, period)` — full single-ticker analysis
  - `get_support_resistance(ticker, period)` — S/R levels + 52W range
  - `get_batch_indicators(tickers, period)` — compact multi-ticker summary
- `mcp__polymarket-mcp__*` — prediction market probabilities (demo mode, read-only)
  - `search_markets(query)` — search for events by keyword
  - `get_trending_markets()` — trending prediction markets
- `mcp__eodhd-mcp__*` — EODHD financial data (ticker format: "AAPL.US"; needs session restart after server.py changes to pick up new tools)
  - `get_news(ticker, days, limit)` — **raw news articles with full body** (up to 1500 chars content), symbols[], tags[], sentiment. Use when you need article body for P3 signal extraction (wafer starts, capex, ASP data). Distinct from get_news_sentiment which discards body/symbols/tags. Also cached daily by `tools/fetch_news.py` → `briefing-out/cache/news-articles.json` (TTL 6h, top 8 articles/ticker, 600-char excerpts).
  - `get_news_sentiment(ticker, days, limit)` — news with AI sentiment scores
  - `get_sentiment_trend(ticker, days)` — aggregated daily sentiment trajectory (-1 to +1)
  - `get_fundamentals_snapshot(ticker)` — **one-call valuation bundle**: PE/PEG/margins/ROE/eps_ttm/revenue_ttm/qtrly growth YoY/wall_street_target/analyst_ratings/52w/beta/SMA. **Free-tier-safe substitute for 402-gated fmp ratios/PT endpoints.** Known data gaps: pe_ratio=0.0/peg=0.0 → drop that anchor. ticker format: "MU.US"
  - `get_earnings_history(ticker, quarters)` — trailing 8Q EPS beat base-rate: `{beat_pct, avg_surprise_pct, beats, quarters_counted}` + next_earnings. **Primary source for probability-honesty-checker Step 1d.** Caveat: avg_surprise_pct unreliable for low-EPS-base stocks (AMD shows +152% artifact — use beat COUNT, not avg%); cross-check vs local earnings-history.json cache
  - `get_economic_calendar(from_date, to_date, country, high_impact_only, limit)` — CPI/NFP/FOMC/PCE with forecast vs previous vs actual. `high_impact_only=True` for macro catalysts. country="US" (2-letter); feeds probability-honesty-checker Step 1i forward catalyst dates
  - `get_macro_indicator(country, indicator, limit)` — annual macro time series (inflation_consumer_prices_annual, real_interest_rate, gdp_growth_annual…). country="USA" (3-letter). **Annual/lagged — regime context only, not high-frequency signals**
- `mcp__coingecko__*` — **(optional)** cryptocurrency data for `/crypto-analysis`: price/market-cap/volume, circulating vs max supply (tokenomics), BTC/ETH dominance, market-cap rankings, historical OHLC. Public demo endpoints work without a key. If not configured → mark "⚠️ coingecko 未配置" and fall back to yfinance (`BTC-USD`) + WebSearch.
- Use parallel agent dispatch for batch data fetching across multiple tickers

## MCP Retry & Fallback Policy
- Any MCP tool call that fails → retry up to **3 times**
- 3 次都失敗 → call that server's health test (single simple tool) to diagnose:
  - yfinance-advanced: `get_stock_info("AAPL")`
  - sec-edgar-mcp: `get_company_info("AAPL")`
  - fmp-mcp: `getCompanyProfile("AAPL")`
  - technical-mcp: `get_technical_indicators("AAPL")`
  - eodhd-mcp: `get_sentiment_trend("AAPL.US", 7)`
  - polymarket-mcp: `get_trending_markets()`
  - coingecko (optional): `get_simple_price("bitcoin")`
- Health test also fails → fallback to WebSearch/WebFetch for equivalent data
- 在輸出中標記 "⚠️ [server] MCP 不可用，使用替代數據源"

## Research Boundaries
- 不主動研究用戶未要求的付費 API/服務
- FMP free tier 限制已記錄，不嘗試付費端點（會返回 402）

## Permission Protection
- 不覆蓋/刪除 `.claude.json` 中現有 allow rules
- 只 append 新權限，並向用戶展示新增內容

## Skill 模型分工（2026-05-05）

### 數據收集 subagent — Haiku 4.5
所有 skill 的平行數據收集 Agent 都指定 `subagent_type: "data-collector"`（見 `.claude/agents/data-collector.md`）。
Data-collector 每次啟動是全新 context（無歷史），Haiku 完全勝任純 MCP 抓資料工作。

### 主 skill 執行模型（2026-06-13 更新：全面回歸 Opus 4.8）

模型階梯：**Opus 4.8**（`claude-opus-4-8`，$15/$75，旗艦推理）> **Sonnet 4.6**（中堅）> **Haiku 4.5**（純機械）。

| Skill / 任務 | 模型 | 理由 |
|---|---|---|
| `/ev-check` | **Opus 4.8** | 純第一性機率分布 + EV，反偷懶紀律最吃推理 |
| `/briefing deep` | **Opus 4.8** | 深度合成 + Codex 整合 + 機率/EV |
| `/stock-analysis` | **Opus 4.8** | 單標的深掘，旗艦推理 |
| `/crypto-analysis` | **Opus 4.8** | 加密第一性（tokenomics/供給/鏈上）+ EV |
| `/options-strategy` | **Opus 4.8** | Greeks / 價差計算 + 多腿比較 |
| `/briefing full` | **Opus 4.8** | 中等綜合 + Verdict |
| `/briefing`（quick）| **Sonnet 4.6** | ~1min 彙整 |
| `/briefing push` | **Sonnet 4.6** | 每日 launchd 自動推送，成本敏感 |
| `/todo` | **Sonnet 4.6** | 行動清單 |
| `/mcp-health` | **Haiku 4.5** | 純連線測試 |
| data-collector subagent | **Haiku 4.5** | 純 MCP 抓資料 |
| probability-honesty-checker subagent | **Opus 4.8** | 機率紀律執法者，用旗艦 |

**長 context：** session > 100k 時先 `/compact`，再繼續執行。換主題先 `/clear`。

**手動切換：** skill frontmatter `model:` 已聲明；若 harness 未自動套用，用 `/model opus`、`/model sonnet`、`/model haiku` 切換後再呼叫。
