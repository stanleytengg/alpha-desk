# Briefing Auto-Send Setup

每個 NYSE 交易日 ET 13:00（系統本地 17:00 CET/CEST）自動跑 `/briefing push`，推送精簡摘要到 **Discord**（webhook）。週五自動加 Codex 第二意見。

---

## 快速起步（4 步驟）

### 1. 建立 Discord Webhook

1. 在你的 Discord 伺服器選一個頻道（建議專開一個 `#briefing`）
2. 頻道名稱旁 **⚙ Edit Channel → Integrations → Webhooks → New Webhook**
3. 取個名字（例：`AlphaDesk`），可換頭像 → **Copy Webhook URL**
4. URL 格式：`https://discord.com/api/webhooks/<id>/<token>`

> 一個 webhook 就夠了 — 不需要 bot token、不需要 app password。

### 2. 建立 .env 設定檔

```bash
cd /path/to/alpha-desk
cp .env.example .env
```

編輯 `.env`，填入：
```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/123.../abc...
```

其他欄位（FRED / EODHD / 報告站）依需要填，留空會優雅降級。

### 3. 安裝 Python 依賴

```bash
pip3 install -r tools/requirements.txt
# 或用 uv：
uv pip install -r tools/requirements.txt
```

### 4. 安裝 launchd 排程

```bash
# 複製 plist，並替換 YOUR_USERNAME 和路徑
cp tools/launchd/com.fadacai.briefing.plist ~/Library/LaunchAgents/

# 編輯 plist 換成你的實際路徑
nano ~/Library/LaunchAgents/com.fadacai.briefing.plist
# 把所有 YOUR_USERNAME 和 /path/to/portfolio 換成實際值

# 載入排程
launchctl load ~/Library/LaunchAgents/com.fadacai.briefing.plist

# 確認已載入
launchctl list | grep fadacai
```

---

## 測試

### 手動發送一次（推薦先測）

在 Claude Code session 內：
```
/briefing push --send
```

或直接用腳本重發最新一份：
```bash
python3 tools/send_briefing.py latest
```

### Dry-run（不實際發送，只印出內容）

```bash
DRY_RUN=1 python3 tools/send_briefing.py latest
```

### 立刻觸發 launchd（不等 17:00）

```bash
launchctl start com.fadacai.briefing
tail -f briefing-out/launchd.log
```

### 測試非交易日跳過

```bash
FAKE_DATE=2026-05-16 python3 tools/check_trading_day.py
# 預期：exit 1，印出 "2026-05-16 is NOT a NYSE trading day"
```

### 測試 Discord 連線（壞 URL 看 retry 行為）

```bash
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/bad RETRY_MAX=1 \
  python3 tools/send_briefing.py latest
# 預期：retry 1 次失敗，send-log.jsonl 記 "discord":"failed"
```

---

## 手動使用方式

| 指令 | 說明 |
|------|------|
| `/briefing push` | 跑 push tier，寫 briefing-out/ 兩個檔案，**不**發送 |
| `/briefing push --send` | 跑 + 發送到 Discord |
| `/briefing full --send` | 完整 full briefing + 發送（push 純文字從 full 內容提取）|
| `python3 tools/send_briefing.py latest` | 重發最新一份（不重新跑 briefing）|
| `python3 tools/send_briefing.py 2026-05-12` | 重發特定日期 |

---

## 每週行為

| 日期 | 行為 |
|------|------|
| 週一至週四 | `/briefing push --send`（無 Codex）|
| 週五 | `/briefing push --send --codex`（加 Codex 第二意見）|
| 週六、週日 | 跳過（不執行）|
| NYSE 休市日 | 跳過（exchange_calendars 判斷）|

---

## 輸出檔案

```
briefing-out/
├── YYYY-MM-DD-full.md        # 完整 briefing markdown（網頁版來源）
├── YYYY-MM-DD-discord.txt    # Discord 精簡純文字
├── send-log.jsonl            # 每次發送記錄（日期、狀態、discord OK 或 failed）
├── launchd.log               # launchd stdout
└── launchd.err               # launchd stderr
```

---

## 疑難排解

**launchd 沒跑**
```bash
launchctl list | grep fadacai
# 若無輸出 → 沒有 load
launchctl load ~/Library/LaunchAgents/com.fadacai.briefing.plist
```

**Discord 收不到訊息**
- 確認 `DISCORD_WEBHOOK_URL` 完整且未過期（在頻道 Webhooks 設定可重新 Copy）
- webhook 被刪除/頻道被刪 → URL 失效，需重建
- 訊息過長：send_briefing.py 會自動把 >2000 字切段；若仍失敗看 `send-log.jsonl`
- 429（rate limited）：腳本會讀 `retry_after` 稍候重試；短時間連發多次才會遇到

**`exchange_calendars` 找不到**
```bash
pip3 install exchange_calendars
# 或
uv pip install exchange_calendars
```

**claude CLI 找不到**
plist 的 `PATH` 需包含 `claude` 的安裝路徑。查詢：
```bash
which claude
# 把那個目錄加到 plist EnvironmentVariables → PATH
```

---

## 開源配置說明

若要在別的機器或分享給他人：

1. `.env` 不 commit（已 gitignore），每個人自己填 webhook URL
2. plist 路徑需對應各自的 home 目錄，依 README 步驟替換 `YOUR_USERNAME`
3. `briefing-out/` 不 commit（已 gitignore），純 local 輸出
4. 唯一需要 commit 的是 `.env.example`（模板）、`tools/`（scripts）、`tools/launchd/`（plist 模板）

## 喚醒排程 + 不睡著（單一發送時間）

發送時間（系統本地 CET/CEST）：**17:00，一天只試這一次**。無備援窗；失敗只記 log，**不**推 Discord 錯誤訊息（用戶決定：Discord 只收正式 briefing）。

**喚醒（把 Mac 叫醒）**
- `pmset repeat wakepoweron … 16:59 weekdays` — 16:59 喚醒，涵蓋 17:00 發送窗。

**保持清醒（關鍵）** — 實測 16:59 scheduled wake 只是 dark-wake，2 秒後就釋放、可能在 17:00 前又睡回去，導致 launchd 推遲 17:00 job（症狀：`launchctl print` 顯示 `runs` 沒增加）。解法：
- **`com.fadacai.caffeinate` LaunchAgent**（`tools/launchd/com.fadacai.caffeinate.plist`）在 16:59 weekdays 跑 `caffeinate -u -t 5520`，把 Mac 從 16:59 撐到 18:31 — 足以涵蓋 runner 最壞情況（3 次 claude retry × 900s timeout + 資料快取刷新 ≈ 50 分鐘）。
- 安裝：`cp tools/launchd/com.fadacai.caffeinate.plist ~/Library/LaunchAgents/ && launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.fadacai.caffeinate.plist`

## 故障排除：自動推送失敗 / 卡死

- **`claude -p` 卡滿 900s timeout ×3**：headless 跑遇到 Claude 工具權限提示無法回答。runner 已加 `--dangerously-skip-permissions`（信任的自動化、跑自己的 repo）。注意此旗標**不**繞過 macOS TCC 檔案彈窗。
- **`Operation not permitted`（TCC）**：repo 在 `~/Desktop`（受保護）。launchd job 第一次存取會跳「取用桌面」彈窗，按一次「允許」後就持續有效（不需每天按）。若真的反覆跳，把 `/bin/bash` 加進 系統設定→隱私權→完整取用磁碟。
- **`runs` 不增加 / 今天沒跑**：dark-wake 沒撐住 → 見上方 caffeinate。
- **手動補發**：`launchctl kickstart -k gui/$(id -u)/com.fadacai.briefing`（會真的推一則）。
