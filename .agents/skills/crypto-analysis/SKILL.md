---
name: crypto-analysis
description: Analyze a cryptocurrency with tokenomics, supply schedule, market structure, on-chain/usage context, technicals, and a first-principles thesis + EV. Usage - /crypto-analysis SYMBOL (e.g. BTC, ETH, SOL) or /crypto-analysis SYM1 SYM2 for comparison.
user_invocable: true
model: claude-opus-4-8
---

# Crypto Analysis

為一個或多個加密貨幣產生標準化研究報告。**加密原生框架** — 不套用股票的 PE/EPS/三錨點（加密無盈餘、無 PE）。改以供給排程（tokenomics）、市場結構（主導率/總市值）、網路使用（TVL/活躍地址/手續費）、資金流（ETF/穩定幣）、技術面與週期帶為估值地基。第一性紀律（Step 0e）asset-agnostic，照常套用。

> 💡 模型指引：重大決策（>5% 倉位）一律 Opus 4.8。session > 100k 先 `/compact`。

## Arguments
- 單一：`/crypto-analysis BTC`
- 比較：`/crypto-analysis BTC ETH`
- 帶 watchlist context：`/crypto-analysis SOL --current`（讀 watchlist 持倉/成本）
- 帶 Codex 第二意見：`/crypto-analysis BTC --codex`（或 `--2nd`）

## Symbol 映射（資料源代碼不同，務必對齊）
| 通用 | coingecko id | yfinance | eodhd | polymarket 關鍵字 |
|------|--------------|----------|-------|------------------|
| BTC | `bitcoin` | `BTC-USD` | `BTC-USD.CC` | "Bitcoin", "BTC ETF" |
| ETH | `ethereum` | `ETH-USD` | `ETH-USD.CC` | "Ethereum", "ETH ETF" |
| SOL | `solana` | `SOL-USD` | `SOL-USD.CC` | "Solana" |
| 其他 | coingecko search → id | `<SYM>-USD` | `<SYM>-USD.CC` | 幣名 |

不確定 coingecko id → 先用 `mcp__coingecko__*` 的 search/list 解析；解析不到該幣 → 標 `⚠️ 找不到 coingecko id，改用 yfinance + WebSearch`。

---

## Step 0: 分析前準備

### 預設模式（無 `--current`）— 純獨立分析
- **跳過** plan.md、feedback/*.md、watchlist；僅基於公開市場數據
- **保留 Step 0e**：Verdict 之前必須完成「核心 thesis / 證偽條件 / 機率分布」三題

### `--current` 模式 — 整合 watchlist
- 執行 CLAUDE.md Step 0（0a → 0b → 0e）
- 讀 `watchlist.md` 加密貨幣段，確認是否持有（`qty` / `avg_cost`）
- 若有 qty/avg_cost → 報告開頭輸出「持倉確認」（成本、數量、未實現損益）；純追蹤 → 標「watchlist 追蹤中（無持倉資料）」

### 不適用項目（相對股票分析）
- ❌ earnings / EPS / 三錨點 Fair PE / SEC filings / 內部人交易（Form 4）
- ✅ 改用下方加密原生資料維度

---

## Workflow

### 1. 平行資料收集（subagent_type: "data-collector"）
為每個 symbol 派一組 data-collector，取以下 raw 數據（失敗依 CLAUDE.md MCP retry policy → fallback）：

**A. 市場 & tokenomics（coingecko 首選）：**
- 現價、市值（market cap）、24h 量、市值排名
- **circulating supply / max supply / total supply** → 算 `流通率 = circ/max`、剩餘待釋出 %
- 通膨/發行：年化新供給 %（emission），若 coingecko 無 → WebSearch 該幣 emission schedule
- ATH / ATL + 距 ATH %
- **BTC 主導率 + 總加密市值**（market structure；coingecko global endpoint）
- coingecko 不可用 → yfinance `<SYM>-USD` 取價格/市值近似，supply 用 WebSearch，標 `⚠️ coingecko 未配置`

**B. 技術面（technical-mcp 對 `<SYM>-USD`；不支援加密則 fallback yfinance 歷史自算）：**
- RSI(14)、MACD line/signal/histogram、價 vs SMA20/50/200 %、ATR%、6-12 週區間、距 52W 高/低
- support / resistance 關鍵價位

**C. 網路使用 / 鏈上（盡力而為，標來源與信心）：**
- L1：TVL（DeFiLlama via WebSearch）、活躍地址、日交易數、手續費/Gas 趨勢
- 質押：staking ratio、staking 收益率（ETH/SOL 等 PoS）
- 穩定幣/結算：鏈上穩定幣市值趨勢（若相關）
- 抓不到硬數字 → 標 `(on-chain N/A)`，不臆造

**D. 資金流 & 催化：**
- ETF 流入/流出（BTC/ETH 現貨 ETF；WebSearch 最新淨流）
- `mcp__polymarket-mcp__search_markets` 取相關事件機率（ETF 批准、升級、宏觀利率）
- 宏觀：與風險資產相關性（macro-snapshot 若有；加密對流動性/實質利率敏感）

**E. 新聞 & 情緒：**
- `mcp__eodhd-mcp__get_news` / `get_sentiment_trend`（`<SYM>-USD.CC`）；缺則 yfinance news / WebSearch
- Fear & Greed Index（WebSearch，若可得）

多幣比較時各派一組 agent。

### 2. 加密原生估值框架（取代三錨點）

不寫 PE。對每個 symbol 建立**情境化公允市值**，三條互補錨：

- **M1 供給錨（stock-to-flow / 稀缺）：** 以 max supply 與年發行率框定稀缺度。發行率下降（如 BTC 減半、ETH 銷毀）→ 供給面利多。輸出「年通膨 X% → 供給面 [利多/中性/利空]」。
- **M2 相對市值錨：** 與可比資產比（BTC vs 黃金總市值的 %；alt vs ETH/BTC 的市值比；L1 vs 同類 L1 的 TVL/市值倍數）。給出「若達 [可比標的] 的 X% → 隱含市值 $Y → 隱含價 $Z」。
- **M3 週期/已實現價帶：** 用 ATH 回撤、過往週期區間、realized price（若可得 via WebSearch）框定 bear/base/bull 帶。

> 三錨是**框定區間**用，不取中位數當單點。EV 由 Step 0e 機率分布合成（見下）。

### 3. Step 0e 第一性檢查（Verdict 前強制）

按 CLAUDE.md 0e + 機率分布強制流程：

```
### 第一性檢查
- **核心 thesis：** [1 句可驗證命題，非 narrative]
  ✅ 例：「BTC 固定供給 21M、年發行率已降至 ~0.8%，現貨 ETF 近 90 天淨流入 $X B，吸收 > 新發行量」
  ❌ 反例：「BTC 是數位黃金」「題材熱」
- **證偽條件：** [2-3 個 falsifiable 觀察點]
  ✅ 例：「ETF 連續 4 週淨流出」「年發行率回升」「BTC 主導率跌破 X% 且 alt 未接棒」
- **機率分布：** 由 probability-honesty-checker agent 算出（8 項輸入 + 形狀反推 + EV Σ）
```

**強制呼叫** `probability-honesty-checker`（或 `/ev-check`）。加密版 Step 1 輸入對應：
- 1a 技術（RSI/距 ATH）；1b 距 52W；1c 已實現波動（加密波動高，誠實放大區間）
- 1d binary catalysts（ETF 決議日、網路升級、解鎖/unlock 事件、宏觀 FOMC）+ base rate
- 1e 集中度（若 watchlist 有持倉權重；單一加密 >10% 提醒）
- 1g sentiment（含 Fear&Greed）；1h thesis 健康（供給/流入/使用是否 intact）；1i macro state
- ⚠️ 禁 default mirror（25/50/25 等）；EV 必須顯式 Σ

機率分布合成後算 EV：
```
| 情境 | 機率 | 隱含市值/價（M1-M3 框定）| 公允價 |
|------|------|---------------------------|--------|
| 樂觀 | XX% | [錨：相對市值/週期上緣] | $XXX |
| 基準 | XX% | [錨：當前結構延續] | $XXX |
| 悲觀 | XX% | [錨：週期下緣/流入逆轉] | $XXX |

Expected Value = Σ(機率 × 公允價) = $XXX → vs 現價 $XXX：±X%
```

### 4. 報告輸出（每個 symbol）

```
# 加密分析：{SYMBOL}  （{date}）

（--current 且有持倉）持倉確認：{qty} @ avg ${cost}，未實現 ±X%

## 快照
現價 $X | 市值 $XB（#排名）| 24h 量 $XB | 距 ATH −X% | BTC 主導率 X%

## Tokenomics & 供給
- 流通/最大供給：X / Y（流通率 Z%）；待釋出 W%
- 年發行率：X%（趨勢：[減半後↓ / 銷毀 / 解鎖壓力↑]）
- 供給面結論：[利多/中性/利空]

## 市場結構 & 資金流
- 主導率/總市值定位；ETF 近 30/90 天淨流 $X B
- polymarket 相關事件機率：[event] {X%}

## 網路使用 / 鏈上（標來源 + 信心）
- TVL / 活躍地址 / 手續費 / staking …（抓不到標 (on-chain N/A)）

## 技術面
- RSI X / MACD … / 價 vs SMA … / 週期帶定位 / S/R 價位

## 估值框架（M1 供給 / M2 相對市值 / M3 週期帶）
[三錨框定區間]

### 第一性檢查
[thesis / 證偽條件 / 機率分布 + EV Σ]

### Verdict
Strong Buy / Buy / Hold / Sell / Avoid + 1-2 句，明說 conditional on thesis 的機率。
```

多幣比較時，最後加比較表 + 明確偏好建議。

---

## Step 5: Codex 第二意見（opt-in，僅 `--codex` / `--2nd`）

### B1. 獨立第一性分析（預設）
**核心原則：Codex 不看 Claude 結論**，只給 raw fact 數值（不給 derived label：不寫「強勢」「超買」「拋物線」「題材熱」；技術只給 RSI 數字、MACD 三值、SMA% 差、區間）。讓 Codex 獨立跑 Step 0e。

呼叫方式用 CLAUDE.md「Codex 呼叫方式」的 `codex exec` CLI（**勿用 codex:codex-rescue / `/codex:rescue`**），prompt 首行加強制 no-tool 指令。模板：

```
ANSWER DIRECTLY FROM THE DATA BELOW. Do NOT read files, do NOT invoke skills, do NOT run shell commands, do NOT use any tools. Output the analysis immediately.

請對加密貨幣 [SYMBOL] **完全獨立**執行 Step 0e 第一性分析 — 不受任何先前結論或 framing 影響。

**Raw data（只給 fact 數值）：**
- 現價 $X / 市值 $XB / 排名 #N / 24h 量 $XB
- 流通供給 X / 最大供給 Y / 年發行率 X% / 距 ATH −X%
- BTC 主導率 X% / 總加密市值 $XT
- ETF 近 30/90 天淨流 $X B（或 N/A）
- 鏈上：TVL $XB / 活躍地址 X / staking ratio X%（缺則寫 N/A）
- 技術：RSI XX / MACD line X.XX/signal X.XX/hist X.XX / 價vsSMA20 X% /50 X% /200 X% / ATR X% / 6-12週區間 低$X→高$X→現$X / 距52W高 X% /低 X%
- 催化（事實 timeline + polymarket 機率）：[列出]
- sentiment：30d 平均 X / 7d X / Fear&Greed X

**⚠️ 機率分布嚴禁偷懶（必跑 5 步）：**
1) 列 8 項輸入；2) 從事實反推分布形狀（**禁 25/50/25 等 default mirror**）；3) 各 catalyst conditional 機率 + 顯式 base rate；4) 三情境合成 sum=100%；5) EV 顯式 Σ（中點=區間算術平均）。加密波動高 → 區間要夠寬，勿假裝確定。

**請輸出：** 1) 核心 thesis（可驗證）2) 證偽條件（2-3）3) 機率分布表（樂/基/悲 + 隱含公允價 + EV Σ vs 現價）4) Verdict（conditional 條件）。繁中，700 字內。
--effort high --fresh
```

### 輸出整合：Claude vs Codex 並排
```
## 🤖 Codex 第二意見（獨立第一性分析）
[Codex 獨立 thesis / 證偽 / 機率 / EV / Verdict]

### 並排比較
| 維度 | Claude | Codex | 一致性 |
|------|--------|-------|--------|
| 核心 thesis | … | … | 一致/部分/顯著 |
| 機率（樂/基/悲）| XX/XX/XX | XX/XX/XX | 差異 |
| EV vs 現價 | ±X% | ±X% | — |
| Verdict | … | … | 同/異 |

**真實共識：** […]　**真實分歧：** […]　**整合建議：** […]
```
比較 EV 前先確認 Codex 機率非 default（否則分歧是「Codex 偷懶」非真實見解衝突）。
Codex 失敗 → 輸出 `⚠️ Codex 不可用：[error]，跳過第二意見`，繼續正常輸出。

---

## Step 6: Thesis Ledger 登錄（收尾）
帶明確時間/事件觸發點的 thesis（「ETF 決議後 / N 日後檢視 X」）登錄帳本（CLAUDE.md 0f）：
```
python3 tools/thesis_ledger.py list --ticker {SYMBOL}   # 看既有 slug
python3 tools/thesis_ledger.py add --ticker {SYMBOL} --slug <slug> --thesis "<可驗證命題>" \
  --falsification "<證偽條件>" --trigger-date YYYY-MM-DD --trigger-metric "<要抓的指標>"
```

## Output Language
全部繁體中文。

## 存檔 + HTML 生成
報告完成後：
1. Write tool 寫完整 markdown 到 `briefing-out/crypto-analysis-<SYMBOL>-YYYY-MM-DD.md`
2. 執行：
```bash
python3 tools/generate_html.py crypto-analysis briefing-out/crypto-analysis-<SYMBOL>-YYYY-MM-DD.md --push
```
成功印出網頁連結；失敗（repo 未建/網站未設）印警告並繼續。
