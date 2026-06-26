#!/usr/bin/env python3
"""
earnings_history.py — Cache trailing 8Q earnings beat-rate + next dates per ticker.

Source: yfinance Ticker(sym).earnings_dates (12-row DataFrame, newest-first)
Output:
  briefing-out/cache/earnings-history.json   trailing 8Q beat/miss/surprise per ticker
  briefing-out/cache/earnings-dates.json     next earnings per ticker (with timing BMO/AMC)
TTL:
  history: 7 days (trailing 8Q stable within a week)
  dates:   24 hours (next date may flip BMO/AMC or get confirmed)

Ticker source priority:
  1. ROOT/watchlist.md  (parse the equity table)
  2. EARNINGS_TICKERS env var (comma-separated)
  3. abort with warning if both empty

Usage:
  python3 tools/earnings_history.py             # refresh stale caches
  python3 tools/earnings_history.py --force     # force refresh both
  python3 tools/earnings_history.py --force-dates  # only dates
"""

import json
import os
import re
import sys
import time
import warnings
from datetime import date, datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore")  # silence yfinance/pandas warnings

import pandas as pd
import yfinance as yf

# ── Path setup ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "briefing-out" / "cache"
HIST_FILE = CACHE_DIR / "earnings-history.json"
DATES_FILE = CACHE_DIR / "earnings-dates.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from watchlist_tickers import get_tickers as _get_watchlist_tickers

# ── Config ─────────────────────────────────────────────────────────────────
CACHE_HIST_TTL_HOURS = 24 * 7  # 7 days
CACHE_DATES_TTL_HOURS = 24
TICKERS_PER_FETCH_DELAY = 0.3   # be polite to yfinance


# ── .env loader ─────────────────────────────────────────────────────────────
def load_env():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                v = v.split("#")[0].strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                    v = v[1:-1]
                os.environ.setdefault(k.strip(), v)


# ── Ticker discovery ───────────────────────────────────────────────────────
def get_tickers() -> list[str]:
    # Equities only (crypto has no earnings); falls back to EARNINGS_TICKERS env.
    return _get_watchlist_tickers(ROOT, env_var="EARNINGS_TICKERS", include_crypto=False)


# ── Cache helpers ──────────────────────────────────────────────────────────
def is_cache_fresh(path: Path, ttl_hours: int) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < ttl_hours * 3600


def atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2,
                              default=str), encoding="utf-8")
    tmp.replace(path)


# ── yfinance fetch ─────────────────────────────────────────────────────────
def _safe_float(v) -> float | None:
    if v is None or pd.isna(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _timing(ts) -> str:
    """Return 'BMO' (before 12:00 ET) or 'AMC' (after) based on timestamp hour."""
    if ts is None or pd.isna(ts):
        return "?"
    h = ts.hour
    return "BMO" if h < 12 else "AMC"


def fetch_ticker_data(sym: str) -> tuple[dict | None, dict | None]:
    """Return (history_record, next_date_record), each may be None on failure."""
    t = yf.Ticker(sym)
    df = t.earnings_dates
    if df is None or df.empty:
        return None, None

    # ensure newest-first sorted
    df = df.sort_index(ascending=False)

    # ── Trailing past 8Q with both estimate + actual filled ──
    past = df[df["Reported EPS"].notna() & df["EPS Estimate"].notna()].head(8)
    history: dict | None = None
    if not past.empty:
        last_8q = []
        beat_count = 0
        surprises = []
        for idx, row in past.iterrows():
            est = _safe_float(row.get("EPS Estimate"))
            actual = _safe_float(row.get("Reported EPS"))
            surprise = _safe_float(row.get("Surprise(%)"))
            beat = (actual is not None and est is not None and actual > est)
            if beat:
                beat_count += 1
            if surprise is not None:
                surprises.append(surprise)
            last_8q.append({
                "date": idx.strftime("%Y-%m-%d"),
                "timing": _timing(idx),
                "est": est,
                "actual": actual,
                "surprise_pct": surprise,
                "beat": beat,
            })
        total = len(last_8q)
        avg_surprise = round(sum(surprises) / len(surprises), 2) if surprises else None
        history = {
            "beat_count": beat_count,
            "total": total,
            "beat_rate_pct": round(100 * beat_count / total, 1),
            "avg_surprise_pct": avg_surprise,
            "last_8q": last_8q,
        }

    # ── Next earnings date ──
    today_utc = pd.Timestamp.now(tz="UTC")
    if df.index.tz is None:
        # naive index, compare with naive today
        future = df[df.index > pd.Timestamp.now()]
    else:
        future = df[df.index > today_utc.tz_convert(df.index.tz)]
    next_date: dict | None = None
    if not future.empty:
        # nearest future = smallest future timestamp (last when sorted desc)
        next_idx = future.index.min()
        next_row = future.loc[next_idx]
        est = _safe_float(next_row.get("EPS Estimate"))
        try:
            days_until = (next_idx.date() - date.today()).days
        except Exception:
            days_until = None
        next_date = {
            "next_date": next_idx.strftime("%Y-%m-%d"),
            "timing": _timing(next_idx),
            "confirmed": est is not None,
            "eps_estimate": est,
            "days_until": days_until,
        }

    return history, next_date


# ── Main ────────────────────────────────────────────────────────────────────
def main() -> int:
    load_env()
    force = "--force" in sys.argv
    force_dates_only = "--force-dates" in sys.argv
    dry_run = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "yes")

    refresh_hist = force and not force_dates_only or \
        (not is_cache_fresh(HIST_FILE, CACHE_HIST_TTL_HOURS))
    refresh_dates = force or force_dates_only or \
        (not is_cache_fresh(DATES_FILE, CACHE_DATES_TTL_HOURS))

    # combined logic: --force refreshes both; --force-dates only dates
    if force:
        refresh_hist = True
        refresh_dates = True
    if force_dates_only:
        refresh_hist = False
        refresh_dates = True

    if not refresh_hist and not refresh_dates:
        print("✅ both earnings caches fresh, skipping")
        return 0

    tickers = get_tickers()
    if not tickers:
        # write empty caches to avoid downstream "missing file" errors
        empty = {
            "status": "skipped",
            "reason": "no_tickers",
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "tickers": {},
            "errors": [],
        }
        if refresh_hist and not dry_run:
            atomic_write(HIST_FILE, empty)
        if refresh_dates and not dry_run:
            atomic_write(DATES_FILE, empty)
        return 0

    print(f"🔄 fetching earnings for {len(tickers)} tickers "
          f"(hist={refresh_hist}, dates={refresh_dates})...")

    hist_data: dict = {}
    dates_data: dict = {}
    errors: list = []

    for i, sym in enumerate(tickers):
        if dry_run:
            print(f"[DRY-RUN] would fetch {sym}")
            continue
        try:
            hist, nxt = fetch_ticker_data(sym)
            if refresh_hist:
                if hist is not None:
                    hist_data[sym] = hist
                else:
                    errors.append({"ticker": sym, "error": "no historical data"})
            if refresh_dates:
                if nxt is not None:
                    dates_data[sym] = nxt
        except Exception as e:
            errors.append({"ticker": sym, "error": f"{type(e).__name__}: {e}"})
        if i < len(tickers) - 1:
            time.sleep(TICKERS_PER_FETCH_DELAY)

    if dry_run:
        print("[DRY-RUN] complete, no write")
        return 0

    if refresh_hist:
        payload = {
            "status": "ok" if hist_data else "empty",
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "tickers": hist_data,
            "errors": errors,
        }
        atomic_write(HIST_FILE, payload)
        print(f"✅ earnings-history.json refreshed: {len(hist_data)} tickers, "
              f"{len(errors)} errors")

    if refresh_dates:
        payload = {
            "status": "ok" if dates_data else "empty",
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "tickers": dates_data,
            "errors": errors,
        }
        atomic_write(DATES_FILE, payload)
        print(f"✅ earnings-dates.json refreshed: {len(dates_data)} tickers")

    return 0


if __name__ == "__main__":
    sys.exit(main())
