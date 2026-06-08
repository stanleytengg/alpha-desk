#!/usr/bin/env bash
# briefing_runner.sh — launchd entry point for daily briefing push.
#
# Called by com.fadacai.briefing.plist at 13:00 America/New_York on weekdays.
# Checks NYSE calendar, adds --codex on Fridays, then invokes Claude CLI.

set -euo pipefail

# Report/log/trading-day timestamps stay on US market time (ET).
# NOTE: TZ lives here, NOT in the plist's EnvironmentVariables — keeping it out
# of the plist means launchd's StartCalendarInterval is evaluated in the system
# local timezone (CET/CEST), so the job fires at the wall-clock time we set.
: "${TZ:=America/New_York}"
export TZ

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$REPO_ROOT/briefing-out"

mkdir -p "$LOG_DIR"

# ── Load .env ──────────────────────────────────────────────────────────────
ENV_FILE="$REPO_ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

RETRY_MAX="${RETRY_MAX:-3}"
FRIDAY_CODEX="${FRIDAY_CODEX:-true}"
SKIP_NON_TRADING="${SKIP_NON_TRADING_DAYS:-true}"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

# ── NYSE calendar check ────────────────────────────────────────────────────
if [[ "$SKIP_NON_TRADING" == "true" ]]; then
  if ! python3 "$SCRIPT_DIR/check_trading_day.py"; then
    log "Non-trading day — exiting without briefing"
    exit 0
  fi
fi

# ── Friday → add --codex ───────────────────────────────────────────────────
DOW=$(python3 -c "from datetime import date; print(date.today().weekday())")  # 4 = Friday
CODEX_FLAG=""
if [[ "$FRIDAY_CODEX" == "true" && "$DOW" == "4" ]]; then
  CODEX_FLAG="--codex"
  log "Friday detected — appending --codex"
fi

# ── Pre-load data caches (non-fatal) ──────────────────────────────────────
log "Refreshing macro cache (FRED)..."
uv run --directory "$SCRIPT_DIR" python3 "$SCRIPT_DIR/fetch_macro.py" \
  >> "$LOG_DIR/launchd.log" 2>> "$LOG_DIR/launchd.err" \
  || log "macro refresh failed (non-fatal, briefing continues with stale/missing cache)"

log "Refreshing earnings cache (yfinance)..."
uv run --directory "$SCRIPT_DIR" python3 "$SCRIPT_DIR/earnings_history.py" \
  >> "$LOG_DIR/launchd.log" 2>> "$LOG_DIR/launchd.err" \
  || log "earnings refresh failed (non-fatal, briefing continues with stale/missing cache)"

log "Refreshing fundamentals cache (EODHD)..."
uv run --directory "$SCRIPT_DIR" python3 "$SCRIPT_DIR/fetch_fundamentals.py" \
  >> "$LOG_DIR/launchd.log" 2>> "$LOG_DIR/launchd.err" \
  || log "fundamentals refresh failed (non-fatal, briefing continues with stale/missing cache)"

log "Refreshing news cache (EODHD raw articles)..."
uv run --directory "$SCRIPT_DIR" python3 "$SCRIPT_DIR/fetch_news.py" \
  >> "$LOG_DIR/launchd.log" 2>> "$LOG_DIR/launchd.err" \
  || log "news refresh failed (non-fatal, briefing continues without news cache)"

# ── Invoke Claude CLI ──────────────────────────────────────────────────────
# Must cd to REPO_ROOT so Claude Code finds .claude/skills/ and project settings
cd "$REPO_ROOT"

PROMPT="/briefing telegram --send $CODEX_FLAG"
log "Running: claude -p \"$PROMPT\" (cwd: $REPO_ROOT)"


attempt=0
success=false
while [[ $attempt -lt $RETRY_MAX ]]; do
  attempt=$((attempt + 1))
  log "Attempt $attempt/$RETRY_MAX"

  # Wrap in a hard timeout (default 900s) so a hung headless claude -p
  # can't block for hours — alarm kills it and the retry loop takes over.
  # macOS has no `timeout`; perl's alarm is built-in and portable.
  CLAUDE_TIMEOUT="${CLAUDE_TIMEOUT:-900}"
  if perl -e 'alarm shift; exec @ARGV' "$CLAUDE_TIMEOUT" claude -p "$PROMPT" >> "$LOG_DIR/launchd.log" 2>> "$LOG_DIR/launchd.err"; then
    log "Claude briefing completed successfully"
    success=true
    break
  else
    EXIT_CODE=$?
    if [[ $EXIT_CODE -eq 142 ]]; then
      log "Claude TIMED OUT after ${CLAUDE_TIMEOUT}s (alarm) — treating as failure"
    fi
    log "Claude exited with code $EXIT_CODE"
    if [[ $attempt -lt $RETRY_MAX ]]; then
      log "Retrying in $((attempt * 30))s…"
      sleep $((attempt * 30))
    fi
  fi
done

if [[ "$success" != "true" ]]; then
  log "All $RETRY_MAX attempts failed — sending error notification"
  # best-effort Telegram error notification
  if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
    python3 - <<'PYEOF'
import os, json, urllib.request
token = os.environ["TELEGRAM_BOT_TOKEN"]
chat  = os.environ["TELEGRAM_CHAT_ID"]
url   = f"https://api.telegram.org/bot{token}/sendMessage"
msg   = "⚠️ Briefing runner 失敗：claude -p 所有 retry 均失敗，請手動檢查 briefing-out/launchd.err"
data  = json.dumps({"chat_id": chat, "text": msg}).encode()
req   = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
try:
    urllib.request.urlopen(req, timeout=10)
except Exception as e:
    print(f"Telegram error notify failed: {e}")
PYEOF
  fi
  exit 1
fi
