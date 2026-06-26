# Setup 踩坑速查

從零安裝（MCP servers + Discord 自動推送）實際會卡住的點。憑證放 `.env` / `.mcp.json`（皆 gitignored），本檔無金鑰。

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

## 3. coingecko：選用的加密貨幣來源
`/crypto-analysis` 的 tokenomics / 市值 / 主導率主要由 **`tools/fetch_crypto.py`**（直接打 CoinGecko REST，零 MCP）預載快取，所以 **coingecko MCP 完全選用**。若仍想掛官方 MCP（npm 套件，需 Node）：
```bash
claude mcp add coingecko --env COINGECKO_ENVIRONMENT=demo -- npx -y @coingecko/coingecko-mcp
```
- ⚠️ 沒有 `uvx coingecko-mcp` 這個 PyPI 套件——官方 MCP 是 npm 的 `@coingecko/coingecko-mcp`，用 `npx` 跑。
- 免金鑰有 rate limit；要更高額度去 https://www.coingecko.com/en/api 申請免費 Demo key，設 `COINGECKO_DEMO_API_KEY`。
- 未配置不致命：`/crypto-analysis` 會 fallback 到 `fetch_crypto.py` 快取 / yfinance（`BTC-USD`）+ WebSearch。

## 4. headless `claude -p` 兩大坑（會 exit 0 但沒產出）
- **PATH 找不到 claude**（exit 127）：plist 的 `PATH` 加 `/Users/YOU/.local/bin`。
- **MCP 權限非互動模式無法授予**：claude 拿不到數據→拒絕捏造→空手而回。解法 `.claude/settings.json` 預授權：
- **claude -p 可能 hang 數小時**（尤其同機另有互動 claude session 時）：runner 用 `perl -e 'alarm shift; exec @ARGV' 900 claude -p ...` 加 900s 硬超時，超時 exit 142 走 retry，避免卡死。
```json
{ "enableAllProjectMcpServers": true,
  "permissions": { "defaultMode": "acceptEdits",
    "allow": ["mcp__yfinance-advanced","mcp__technical",
      "mcp__eodhd-mcp","mcp__sec-edgar-mcp","mcp__fmp-mcp","mcp__polymarket-mcp","mcp__coingecko",
      "Read","Edit","Write","Task","WebSearch","WebFetch","Bash(python3 *)"] } }
```

## 5. 子代理拿不到 MCP → 用 `.mcp.json`
`claude mcp add` 存的是 project scope，子代理/別的目錄載不到。專案根放 `.mcp.json`（含 token，務必 gitignore，範本見 `.mcp.json.example`）。

## 6. macOS TCC
launchd 跑 `/bin/bash` 存取 `~/Desktop` 被擋（`Operation not permitted`）→ System Settings → Privacy & Security → Full Disk Access → 加 `/bin/bash`。

## 7. Mac 睡眠 → launchd 不觸發（筆電最大坑）
launchd 在睡眠不觸發，`pmset wake` 喚醒後筆電（尤其合蓋 clamshell）常立刻睡回去，到觸發那秒又睡著。單一固定時間極不可靠。

**解法 — 多觸發點 + dedup**（best for laptop）：plist 設多個 `StartCalendarInterval`（ET 11:30 / 13:30 / 15:30），只要當天任一時段醒著就觸發；`briefing_runner.sh` 開頭檢查「今天發過沒」、`send_briefing.py` 再 dedup → 一天最多實際發一次。
```xml
<key>StartCalendarInterval</key>
<array>
  <dict><key>Hour</key><integer>11</integer><key>Minute</key><integer>30</integer></dict>
  <dict><key>Hour</key><integer>13</integer><key>Minute</key><integer>30</integer></dict>
  <dict><key>Hour</key><integer>15</integer><key>Minute</key><integer>30</integer></dict>
</array>
```
搭配 pmset 喚醒第一個時間點（需 sudo、接 AC）：
```bash
sudo pmset repeat wake MTWRF 17:20:00   # 換算成你時區，ET 11:30 前 10 分鐘
```
> 仍要求機器在某個觸發點是醒的。完全可靠需接 AC + 設定「接電源永不睡眠」，或合蓋接外接螢幕。

## 8. 雜項
- **Discord webhook**：`DISCORD_WEBHOOK_URL` 完整貼到 `.env`；訊息 >2000 字 send_briefing.py 自動分段。
- **dedup**：`send_briefing.py` 同日只發一次，重發要清 `send-log.jsonl` 當日記錄。
- `exchange_calendars` / FRED 429 皆非致命（有 fallback / cache）。

## 驗證
```bash
claude mcp list                  # MCP server ✓ Connected
launchctl list | grep fadacai    # briefing + fmp-mcp
```
成功標誌：`claude -p "/briefing push --send"` 跑完，`briefing-out/` 出現當天兩檔 + `send-log.jsonl` 多一筆 `"discord":"ok"`。
