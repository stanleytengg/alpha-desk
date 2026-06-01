# firstrade-server（自建 Python MCP 範例）

一個輕量的 Firstrade MCP server，用 PyPI `firstrade` 套件直接連券商，提供即時持倉/餘額/報價給框架的 Step 0b。比官方 Rust 版（要另起 REST API server）簡單：單一服務、saved session 免每次 OTP。

> ⚠️ 不含任何憑證。所有帳密從同目錄 `.env`（gitignored）讀取。詳見 `../setup-troubleshooting.md §3`。

## 安裝

```bash
mkdir firstrade-server && cd firstrade-server
# 放入 server.py / ft_setup.py / pyproject.toml
cp .env.example .env        # 填入你的 Firstrade 帳密
uv sync
```

## 首次認證（一次性，之後 ~30 天免 OTP）

```bash
uv run python3 ft_setup.py step1          # 觸發 OTP 到 email/SMS
uv run python3 ft_setup.py step2 123456   # 輸入收到的驗證碼
```

成功後 session cookies 存在 `~/.local/share/firstrade-session`，server 之後自動重用。

## 註冊到 Claude Code

```bash
claude mcp add firstrade-server -- uv --directory /abs/path/to/firstrade-server run server.py
```

憑證由 server.py 自己讀 `.env`，**不需**在註冊指令帶 `--env`（避免密碼寫進 `~/.claude.json`）。

## 提供的工具

| Tool | 說明 |
|------|------|
| `get_account_position` | 所有帳戶的股票 + 選擇權持倉 |
| `get_account_balance` | 帳戶淨值、現金 |
| `get_account_history` | 交易紀錄（date_range: today/1w/1m/2m/mtd/ytd/ly）|
| `get_single_quote` | 單一標的即時報價 |
| `get_watchlist_quote` | 多標的即時報價（逗號分隔）|

## session 過期

約 30 天後 cookies 失效，server 會回 `OTP required`，重跑 `ft_setup.py step1/step2` 即可。auto-send runner 失敗時會自動發 Telegram 通知。
