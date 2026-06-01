# Setup 踩坑速查

從零安裝（7 個 MCP + Telegram 自動推送）實際會卡住的點。憑證放 `.env` / `.mcp.json`（皆 gitignored），本檔無金鑰。

## 1. MCP 安裝：能 uvx 就別 clone
多數 server 已在 PyPI，免 clone：
```bash
claude mcp add yfinance-advanced -- uvx yfinance-mcp        # 註冊名≠套件名
claude mcp add sec-edgar-mcp --env SEC_EDGAR_USER_AGENT="Name your@email.com" -- uvx sec-edgar-mcp
claude mcp add polymarket-mcp -- uvx polymarket-mcp
claude mcp add technical -- uv --directory /path/to/fadacai-mcp-servers/technical run server.py
claude mcp add eodhd-mcp --env EODHD_API_TOKEN=xxx -- uv --directory /path/to/fadacai-mcp-servers/eodhd run server.py
```
> macOS 別用 `pip3`（撞 PEP 668），一律 `uv` / `uvx`。

## 2. fmp-mcp 是 HTTP server，要常駐
唯一要 clone+build 的（npm 無套件）。坑：env 是 `FMP_ACCESS_TOKEN`（非 `FMP_API_KEY`）、固定 port、要 `--transport http`。
```bash
# launchd 常駐（plist 設 node dist/index.js --port 8081 + FMP_ACCESS_TOKEN + KeepAlive）
claude mcp add fmp-mcp --transport http http://localhost:8081/mcp
```

## 3. firstrade-server：自建 Python MCP
官方 `morristai/firstrade-mcp` 是 Rust + 要另起 API server。改用 PyPI `firstrade` 套件自寫 FastMCP（範例見 `firstrade-server-example/`）。三個坑：
- **`login()` 回傳值是反的**：`False`=成功（重用 session）、`True`=需 OTP。別寫 `if not ok: raise`。
- **憑證從 server 自己的 `.env` 讀**，別用 `claude mcp add --env`（會明碼寫進 `~/.claude.json`）。
- **2FA 只首次互動**：`save_session=True` 存 cookies，之後 ~30 天免 OTP。首次分兩步：`ft_setup.py step1`（觸發 OTP）→ `step2 <code>`。
- 雜：401=帳密錯（注意特殊字元）、429=試太多次等 1-2 分鐘。

## 4. headless `claude -p` 兩大坑（會 exit 0 但沒產出）
- **PATH 找不到 claude**（exit 127）：plist 的 `PATH` 加 `/Users/YOU/.local/bin`。
- **MCP 權限非互動模式無法授予**：claude 拿不到持倉→拒絕捏造→空手而回。解法 `.claude/settings.json` 預授權：
```json
{ "enableAllProjectMcpServers": true,
  "permissions": { "defaultMode": "acceptEdits",
    "allow": ["mcp__firstrade-server","mcp__yfinance-advanced","mcp__technical",
      "mcp__eodhd-mcp","mcp__sec-edgar-mcp","mcp__fmp-mcp","mcp__polymarket-mcp",
      "Read","Edit","Write","Task","WebSearch","WebFetch","Bash(python3 *)"] } }
```

## 5. 子代理拿不到 MCP → 用 `.mcp.json`
`claude mcp add` 存的是 project scope，子代理/別的目錄載不到。專案根放 `.mcp.json`（含 token，務必 gitignore，範本見 `.mcp.json.example`）。

## 6. macOS TCC
launchd 跑 `/bin/bash` 存取 `~/Desktop` 被擋（`Operation not permitted`）→ System Settings → Privacy & Security → Full Disk Access → 加 `/bin/bash`。

## 7. Mac 須醒著（最易忽略）
launchd 在睡眠不觸發。用 pmset 定時喚醒（需 sudo、接 AC）：
```bash
sudo pmset repeat wake MTWRF 18:50:00   # 時間換算成你時區的 ET 13:00 前 10 分鐘
```

## 8. 雜項
- **`SMTP_PASS` 有空格要加引號**：`SMTP_PASS="xxxx xxxx xxxx xxxx"`。
- **dedup**：`send_briefing.py` 同日只發一次，重發要清 `send-log.jsonl` 當日記錄。
- `exchange_calendars` / FRED 429 皆非致命（有 fallback / cache）。

## 驗證
```bash
claude mcp list                  # 7 個 ✓ Connected
launchctl list | grep fadacai    # briefing + fmp-mcp
```
成功標誌：`claude -p "/briefing telegram --send"` 跑完，`briefing-out/` 出現當天兩檔 + `send-log.jsonl` 多一筆 `"telegram":"ok","email":"ok"`。
