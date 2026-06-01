# Setup 踩坑記錄與解法

實際從零安裝這套框架（含 7 個 MCP server + Telegram 自動推送）時遇到的坑與解法。照 README 走之外，這些是文件沒寫清楚、實際會卡住的地方。

> 所有真實憑證放 `.env`（gitignored）；`.mcp.json` 含 API token 也已 gitignored，用 `.mcp.json.example` 當範本。本文件不含任何金鑰。

---

## 1. MCP server 安裝：能 `uvx` 就別 clone

README 的表格把幾個 server 寫成要去 clone，實際上多數已在 PyPI，`uvx` 一行直接跑、免 clone、免維護：

| Server | 實際最簡安裝 |
|--------|-------------|
| `yfinance-advanced` | `uvx yfinance-mcp`（PyPI 套件，**不是**叫 yfinance-advanced，那只是 Claude Code 內的註冊名）|
| `sec-edgar-mcp` | `uvx sec-edgar-mcp` |
| `polymarket-mcp` | `uvx polymarket-mcp` |
| `technical` / `eodhd` | 姊妹 repo `fadacai-mcp-servers`，`uv sync` 後 `uv run server.py` |
| `fmp-mcp` | **唯一要 clone + build 的**（npm 無套件，見下方 §2）|
| `firstrade-server` | 自建（見 §3）|

**註冊指令**（路徑換成你自己的）：
```bash
claude mcp add yfinance-advanced -- uvx yfinance-mcp
claude mcp add sec-edgar-mcp --env SEC_EDGAR_USER_AGENT="Name your@email.com" -- uvx sec-edgar-mcp
claude mcp add polymarket-mcp -- uvx polymarket-mcp
claude mcp add technical -- uv --directory /path/to/fadacai-mcp-servers/technical run server.py
claude mcp add eodhd-mcp --env EODHD_API_TOKEN=xxx -- uv --directory /path/to/fadacai-mcp-servers/eodhd run server.py
```

> macOS 用系統 Python 會撞 `externally-managed-environment`（PEP 668）。一律用 `uv`（`uv venv` + `uv pip install`）或 `uvx`，別用 `pip3 install`。

---

## 2. fmp-mcp 是 HTTP server，不是 stdio

`fmp-mcp`（Financial-Modeling-Prep-MCP-Server）跟其他不同，它是 **Node.js HTTP server**，不是 stdio。直接 `claude mcp add -- node dist/index.js` 會失敗。

**坑：**
- 環境變數名是 `FMP_ACCESS_TOKEN`，**不是** `FMP_API_KEY`（README 沒寫）
- 它監聽固定 port（預設 8080，常被占用），要常駐背景才能連
- 註冊時要用 `--transport http`，不是 stdio

**解法 — launchd 常駐 + HTTP 註冊：**

`~/Library/LaunchAgents/com.fadacai.fmp-mcp.plist`：
```xml
<key>ProgramArguments</key>
<array>
  <string>/opt/homebrew/bin/node</string>
  <string>/path/to/fmp-mcp/dist/index.js</string>
  <string>--port</string><string>8081</string>
</array>
<key>EnvironmentVariables</key>
<dict>
  <key>FMP_ACCESS_TOKEN</key><string>YOUR_TOKEN</string>
  <key>PORT</key><string>8081</string>
</dict>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
```
```bash
launchctl load ~/Library/LaunchAgents/com.fadacai.fmp-mcp.plist
claude mcp add fmp-mcp --transport http http://localhost:8081/mcp
```

---

## 3. firstrade-server：自建 Python MCP（官方是 Rust + 要另起 API server）

README 指的 `morristai/firstrade-mcp` 是 **Rust** 寫的，而且它**不直接連 Firstrade**——還需要你另外跑一個本地 REST API server（兩個服務）。太麻煩。

**更簡單：用 PyPI 的 `firstrade` 套件自寫一個 FastMCP server，一個服務搞定。** 完整 `server.py` 見本 repo `docs/firstrade-server-example/`（去敏感版）。關鍵踩坑：

### 坑 A — `login()` 的回傳值是反的
`firstrade` 套件的 `FTSession.login()`：
- 回傳 `False` = **成功**（重用已存的 session cookies，不需 OTP）
- 回傳 `True` = 需要新的 OTP 驗證碼

所以 `if not ok: raise` 是錯的（成功反而報錯）。正確：
```python
need_code = session.login()
if need_code:
    raise RuntimeError("OTP required — re-run ft_setup.py")
data = FTAccountData(session)
```

### 坑 B — 憑證要從 server 自己的 `.env` 讀，別放註冊指令
`claude mcp add` 的 `--env` 會把密碼寫進 `~/.claude.json`（明碼）。改成 server.py 啟動時自己讀同目錄 `.env`（gitignored），密碼不進任何被追蹤的檔案。

### 坑 C — 2FA 只能首次互動完成，之後靠 saved session
首次登入要 OTP（email/SMS）。`save_session=True` + `profile_path` 會把 session cookies 存檔，**之後 ~30 天內自動重用、不需再 OTP**，headless 自動推送才能跑。

首次設定分兩步（避免互動式 input 在 `claude !` 環境下 EOF）：
```bash
uv run python3 tools/ft_setup.py step1          # 觸發 OTP
uv run python3 tools/ft_setup.py step2 <CODE>   # 完成並存 session
```

**其他坑：**
- Firstrade 登入 401 = 帳密錯（注意密碼特殊字元，如開頭的 `!`）
- 試太多次會 429 Too Many Requests，等 1-2 分鐘
- session 過期（~30 天）→ 重跑 `ft_setup.py`，briefing runner 失敗時會自動發 Telegram 通知

---

## 4. headless `claude -p` 自動推送的兩個致命坑

launchd 跑 `claude -p "/briefing telegram --send"` 時，非互動模式有兩個會讓 briefing **靜默失敗（exit 0 但沒產出）** 的坑：

### 坑 A — PATH 找不到 `claude`
launchd 的 PATH 很乾淨，`claude` 在 `~/.local/bin` 找不到 → `exit code 127`。plist 的 `PATH` 要包含它：
```xml
<key>PATH</key><string>/Users/YOU/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
```

### 坑 B — MCP 工具權限在非互動模式無法授予
互動模式下 MCP 工具會跳權限確認框；headless 模式跳不出來 → 工具被擋 → claude 拿不到持倉 → 它（正確地）**拒絕捏造資料**，於是沒產出 briefing 就結束。

**解法 — `.claude/settings.json` 預先授權**（見本 repo 範例）：
```json
{
  "enableAllProjectMcpServers": true,
  "permissions": {
    "defaultMode": "acceptEdits",
    "allow": [
      "mcp__firstrade-server", "mcp__yfinance-advanced", "mcp__technical",
      "mcp__eodhd-mcp", "mcp__sec-edgar-mcp", "mcp__fmp-mcp", "mcp__polymarket-mcp",
      "Read", "Edit", "Write", "Task", "WebSearch", "WebFetch",
      "Bash(python3 *)"
    ]
  }
}
```

---

## 5. 子代理（Agent tool）拿不到 MCP → 用 `.mcp.json`

MCP 若只用 `claude mcp add` 註冊，是存在 `~/.claude.json` 的 **project scope**。從別的目錄啟動 claude、或子代理（`subagent_type: data-collector`）都可能載入不到。

**解法：** 在專案根目錄放 `.mcp.json`（本 repo 有 `.mcp.json.example`），讓 MCP 設定跟著專案走，子代理也能用。`.mcp.json` 含 token，**務必 gitignore**。

---

## 6. macOS TCC：launchd 要 Full Disk Access

launchd 背景跑 `/bin/bash` 存取 `~/Desktop` 下的腳本會被 TCC 擋（`Operation not permitted`）。

**System Settings → Privacy & Security → Full Disk Access → `+` → `Shift+Cmd+G` → 輸入 `/bin` → 選 `bash` → 開啟開關。**

---

## 7. Mac 必須醒著，否則 launchd 不觸發（最容易被忽略）

launchd 的 `StartCalendarInterval` 在 Mac **睡眠時不會觸發**，醒來也不一定補跑。每日 ET 13:00 推送若那時 Mac 在睡 → 當天沒 briefing。

**解法 — 用 `pmset` 設定定時喚醒**（需 sudo，自己跑）：
```bash
# 每天本地時間 18:50 喚醒（ET 13:00 ≈ 歐洲 19:00，提前 10 分鐘喚醒給 launchd 餘裕）
sudo pmset repeat wake MTWRF 18:50:00
pmset -g sched          # 確認排程
```
> 喚醒需接 AC 電源。時間依你所在時區換算 ET 13:00。

---

## 8. 雜項小坑

- **`SMTP_PASS` 有空格要加引號**：Gmail App Password 是 `xxxx xxxx xxxx xxxx` 格式，`.env` 裡要寫 `SMTP_PASS="xxxx xxxx xxxx xxxx"`，否則 bash source 會解析錯。
- **`exchange_calendars not installed`**：非致命，有 weekday fallback；要精確 NYSE 休市判斷才 `uv pip install exchange_calendars`。
- **dedup guard**：`send_briefing.py` 同一天只發一次（防重複推送）。要強制重發得清掉 `send-log.jsonl` 當天記錄。
- **FRED 429**：macro cache 短時間重刷會被限速，有 retry + 24h cache，非致命。

---

## 驗證 checklist

```bash
claude mcp list                              # 7 個 server 全 ✓ Connected
launchctl list | grep fadacai                # briefing + fmp-mcp 都在
DRY_RUN=1 python3 tools/send_briefing.py latest   # 推送管道 dry-run
```
end-to-end 成功的標誌：`claude -p "/briefing telegram --send"` 跑完後，`briefing-out/` 出現當天兩個檔案 + `send-log.jsonl` 多一筆 `"dry_run": false, "telegram": "ok", "email": "ok"`。
