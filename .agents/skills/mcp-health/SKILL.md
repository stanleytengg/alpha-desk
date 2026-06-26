---
name: mcp-health
description: Test all MCP server connections and report health status. Usage - /mcp-health
user_invocable: true
model: claude-haiku-4-5-20251001
---

# MCP Health Check

測試所有 MCP server 的連線狀態，快速診斷問題。

## Workflow

### 1. 平行測試所有 MCP Server

盡可能同時呼叫以下測試，使用最簡單的工具確認連線：

| # | Server | 測試工具 | 測試呼叫 |
|---|--------|---------|---------|
| 1 | yfinance-advanced | `get_stock_info` | `("AAPL")` |
| 2 | sec-edgar-mcp | `get_company_info` | `("AAPL")` |
| 3 | fmp-mcp | `getCompanyProfile` | `("AAPL")` |
| 4 | technical-mcp | `get_technical_indicators` | `("AAPL")` |
| 5 | eodhd-mcp | `get_sentiment_trend` | `("AAPL.US", 7)` |
| 6 | polymarket-mcp | `get_trending_markets` | `()` |
| 7 | coingecko *(選用)* | `get_simple_price` | `("bitcoin")` |

> coingecko 為選用的加密貨幣研究來源；若未設定則標記「⚪ 未配置」而非失敗。

### 2. 判定狀態

對每個 server 的回應判定：
- **✅ Healthy** — 正常返回數據
- **⚠️ Degraded** — 返回但數據不完整或響應異常慢
- **❌ Failed** — 呼叫失敗或超時

### 3. 輸出狀態表

```
## MCP Server 健康檢查

| Server | 狀態 | 延遲 | 備註 |
|--------|------|------|------|
| yfinance-advanced | ✅ Healthy | ~Xs | 主要報價/基本面來源 |
| sec-edgar-mcp | ✅ Healthy | ~Xs | — |
| fmp-mcp | ✅ Healthy | ~Xs | Free tier |
| technical-mcp | ✅ Healthy | ~Xs | — |
| eodhd-mcp | ❌ Failed | — | 連線失敗 |
| polymarket-mcp | ✅ Healthy | ~Xs | Demo mode |
| coingecko | ⚪ 未配置 | — | 選用（加密貨幣）|

健康: X/N | 異常: X/N（coingecko 未配置不計入分母）
```

### 4. 失敗時的處理

對於 ❌ Failed 的 server，顯示：
- 錯誤訊息摘要
- 手動重啟指令（僅顯示，**不自動執行**）：

```
# 手動重啟指令（請在終端機執行）：
# yfinance-advanced:
cd ~/.claude/yahoo-finance-mcp && uv run server.py

# sec-edgar-mcp:
cd ~/.claude/sec-edgar-mcp && uv run --project sec-edgar-runner server.py

# fmp-mcp:
node /opt/homebrew/lib/node_modules/financial-modeling-prep-mcp-server/stdio-entry.mjs
```

### 5. 建議

- 若 1-2 個 server 失敗 → 建議重啟該 server，其他 skill 可正常使用（會 fallback）
- 若 3+ 個 server 失敗 → 建議重啟 Claude Code session
- 提醒：MCP server 由 Claude Code 自動管理，通常重開 session 即可恢復

## Output Format
- 繁體中文輸出
- 簡潔表格格式
- 預估執行時間：~30 秒
