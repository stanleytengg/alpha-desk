#!/usr/bin/env python3
"""
send_briefing.py — Push daily briefing to a Discord channel via webhook.

Usage:
  python3 tools/send_briefing.py YYYY-MM-DD   # send specific date
  python3 tools/send_briefing.py latest        # send most recent files

Environment (from .env or shell):
  DISCORD_WEBHOOK_URL   # https://discord.com/api/webhooks/<id>/<token>
  DRY_RUN=1             # print what would be sent, don't actually send
  RETRY_MAX=3           # retry count on send failure (default 3)

Reports-site (optional; appends a 🔗 link if all three are set):
  REPORT_SITE_TOKEN, REPORT_SITE_URL, REPORTS_REPO_PATH
"""

import json
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ── Path setup ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
BRIEFING_OUT = ROOT / "briefing-out"
LOG_FILE = BRIEFING_OUT / "send-log.jsonl"


# ── .env loader (stdlib only) ───────────────────────────────────────────────
def load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                # strip inline comments (e.g. VALUE=foo  # comment)
                v = v.split("#")[0].strip()
                # strip surrounding quotes (single or double)
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                    v = v[1:-1]
                os.environ.setdefault(k.strip(), v)


def require(key: str) -> str:
    val = os.environ.get(key, "")
    if not val:
        raise RuntimeError(f"Missing required env var: {key}")
    return val


# ── File resolution ─────────────────────────────────────────────────────────
def resolve_date(arg: str) -> str:
    if arg == "latest":
        files = sorted(BRIEFING_OUT.glob("*-discord.txt"))
        if not files:
            raise FileNotFoundError("No discord files found in briefing-out/")
        return files[-1].name.replace("-discord.txt", "")
    # validate YYYY-MM-DD
    datetime.strptime(arg, "%Y-%m-%d")
    return arg


def read_push_text(date_str: str) -> str:
    """Read the plain-text push payload. Falls back to the legacy -telegram.txt name."""
    discord_path = BRIEFING_OUT / f"{date_str}-discord.txt"
    legacy_path = BRIEFING_OUT / f"{date_str}-telegram.txt"
    path = discord_path if discord_path.exists() else legacy_path
    if not path.exists():
        raise FileNotFoundError(f"Not found: {discord_path}")
    return path.read_text(encoding="utf-8")


# ── Discord webhook ──────────────────────────────────────────────────────────
MAX_DISCORD_CHARS = 2000  # Discord hard limit per message content


def split_message(text: str, limit: int = MAX_DISCORD_CHARS) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts = []
    while text:
        if len(text) <= limit:
            parts.append(text)
            break
        # split at last newline before limit
        cut = text.rfind("\n", 0, limit)
        if cut == -1:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return parts


def send_discord(text: str, dry_run: bool = False) -> None:
    webhook = require("DISCORD_WEBHOOK_URL")
    ctx = ssl._create_unverified_context()
    chunks = split_message(text)

    for i, part in enumerate(chunks):
        if dry_run:
            print(f"[DRY-RUN] Discord webhook ← part {i+1}/{len(chunks)}")
            print(part[:200] + ("…" if len(part) > 200 else ""))
            continue
        payload = json.dumps({"content": part}).encode()
        req = urllib.request.Request(
            webhook, data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
                # Discord returns 204 No Content on success
                if resp.status not in (200, 204):
                    raise RuntimeError(f"Discord webhook HTTP {resp.status}")
        except urllib.error.HTTPError as e:
            # 429 = rate limited; honour retry_after then bubble up to with_retry
            if e.code == 429:
                try:
                    info = json.loads(e.read())
                    wait = float(info.get("retry_after", 1.0))
                except Exception:
                    wait = 1.0
                time.sleep(min(wait, 10))
                raise RuntimeError("Discord rate limited (429)")
            raise RuntimeError(f"Discord webhook HTTP {e.code}: {e.reason}")
        # gentle pacing between chunks to avoid burst rate limit
        if i < len(chunks) - 1:
            time.sleep(0.6)


# ── Logging ───────────────────────────────────────────────────────────────────
def already_sent_today(date_str: str) -> bool:
    """Return True if send-log already has a successful (non-dry-run) entry for date_str."""
    if not LOG_FILE.exists():
        return False
    for line in LOG_FILE.read_text().splitlines():
        try:
            entry = json.loads(line)
            if (entry.get("date") == date_str
                    and not entry.get("dry_run")
                    and entry.get("discord") == "ok"):
                return True
        except json.JSONDecodeError:
            continue
    return False


def write_log(entry: dict) -> None:
    BRIEFING_OUT.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ── Retry wrapper ─────────────────────────────────────────────────────────────
def with_retry(fn, label: str, max_retries: int) -> bool:
    for attempt in range(1, max_retries + 1):
        try:
            fn()
            return True
        except Exception as e:
            print(f"[{label}] attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                time.sleep(3 * attempt)
    return False


# ── HTML generation helper ─────────────────────────────────────────────────────
def _generate_html(date_str: str, dry_run: bool) -> str | None:
    """Call generate_html.py and return the public URL on success, or None on failure.

    Returns empty string if site URL/token not configured (skip silently).
    """
    token = os.environ.get("REPORT_SITE_TOKEN", "")
    site_url = os.environ.get("REPORT_SITE_URL", "")
    repo_path = os.environ.get("REPORTS_REPO_PATH", "")
    if not (token and site_url and repo_path):
        return ""  # not configured, skip

    script = ROOT / "tools" / "generate_html.py"
    cmd = [sys.executable, str(script), "briefing", date_str, "--push"]
    if dry_run:
        print(f"[DRY-RUN] HTML 生成 + push → {site_url}/r/{token}/briefing/{date_str}.html")
        return f"{site_url}/r/{token}/briefing/{date_str}.html"
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode in (0, 2):  # 0=ok, 2=push failed (repo not ready) but HTML written
            url = f"{site_url}/r/{token}/briefing/{date_str}.html"
            if result.returncode == 2:
                print(f"[send_briefing] ⚠️ HTML 已生成但 push 失敗，連結暫不附加")
                return None
            return url
        print(f"[send_briefing] ⚠️ generate_html 失敗 (exit {result.returncode})")
        if result.stderr:
            print(result.stderr[:300])
        return None
    except subprocess.TimeoutExpired:
        print("[send_briefing] ⚠️ generate_html 逾時（60s）")
        return None
    except Exception as e:
        print(f"[send_briefing] ⚠️ generate_html 例外：{e}")
        return None


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> int:
    load_env()

    dry_run = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "yes")
    max_retries = int(os.environ.get("RETRY_MAX", "3"))

    if len(sys.argv) < 2:
        print("Usage: send_briefing.py YYYY-MM-DD | latest")
        return 1

    try:
        date_str = resolve_date(sys.argv[1])
        push_text = read_push_text(date_str)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}")
        return 1

    # Guard: skip if already successfully sent today (prevents duplicate from runner retry)
    if not dry_run and already_sent_today(date_str):
        print(f"⏭️  {date_str} 已成功發送過，跳過重複發送")
        return 0

    log_entry: dict = {
        "date": date_str,
        "sent_at": datetime.now(tz=timezone.utc).isoformat(),
        "dry_run": dry_run,
        "discord": None,
        "html": None,
    }

    # ── HTML generation (best-effort, runs before send so link can be appended)
    html_url = _generate_html(date_str, dry_run)
    if html_url:
        push_text = push_text.rstrip() + f"\n\n🔗 Web version: {html_url}"
        log_entry["html"] = "ok"
    else:
        log_entry["html"] = "failed" if html_url is None else "skipped"

    # ── Discord
    discord_ok = with_retry(
        lambda: send_discord(push_text, dry_run),
        "Discord", max_retries
    )
    log_entry["discord"] = "ok" if discord_ok else "failed"

    write_log(log_entry)

    if discord_ok:
        print(f"✅ {date_str} Discord 已發送")
        return 0
    else:
        print(f"❌ {date_str} Discord 推送失敗（已重試 {max_retries} 次），詳見 send-log.jsonl")
        return 2


if __name__ == "__main__":
    sys.exit(main())
