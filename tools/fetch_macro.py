#!/usr/bin/env python3
"""
fetch_macro.py — Fetch FRED macro indicators with TTL cache.

Datasets:
  DFF              fed_funds      Effective Fed Funds Rate (daily)
  CPIAUCSL         cpi_yoy        CPI All Urban (monthly, computed YoY)
  T10Y2Y           yield_2s10s    10Y - 2Y Treasury spread
  BAMLH0A0HYM2     hy_oas         ICE BofA US High Yield OAS
  VIXCLS           vix            CBOE VIX

Output: briefing-out/cache/macro-snapshot.json
TTL:    24h (skip refresh if cache fresher)

Usage:
  python3 tools/fetch_macro.py              # refresh if cache stale
  python3 tools/fetch_macro.py --force      # force refresh

Env:
  FRED_API_KEY    required (free at https://fred.stlouisfed.org/docs/api/api_key.html)
  DRY_RUN=1       print what would be fetched, don't write
"""

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Use certifi CA bundle when available (fixes SSL in launchd environments)
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = ssl.create_default_context()

# ── Path setup ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "briefing-out" / "cache"
CACHE_FILE = CACHE_DIR / "macro-snapshot.json"

# ── Config ─────────────────────────────────────────────────────────────────
FRED_SERIES = {
    "DFF": "fed_funds",
    "CPIAUCSL": "cpi_yoy",
    "T10Y2Y": "yield_2s10s",
    "BAMLH0A0HYM2": "hy_oas",
    "VIXCLS": "vix",
}
CACHE_TTL_HOURS = 24
FRED_URL = "https://api.stlouisfed.org/fred/series/observations"


# ── .env loader (stdlib only) ───────────────────────────────────────────────
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


# ── Retry wrapper ───────────────────────────────────────────────────────────
def with_retry(fn, label: str, max_retries: int = 3):
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except Exception as e:
            print(f"[{label}] attempt {attempt}/{max_retries} failed: {e}",
                  file=sys.stderr)
            if attempt < max_retries:
                time.sleep(3 * attempt)
    return None


# ── FRED fetch ──────────────────────────────────────────────────────────────
def fetch_series(series_id: str, api_key: str, limit: int = 400) -> list:
    """Return list of {date, value} dicts, newest first."""
    params = urllib.parse.urlencode({
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    })
    url = f"{FRED_URL}?{params}"
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=20, context=_SSL_CTX) as resp:
        data = json.loads(resp.read())
    obs = []
    for row in data.get("observations", []):
        if row.get("value") in (".", None, ""):
            continue
        try:
            obs.append({"date": row["date"], "value": float(row["value"])})
        except (ValueError, KeyError):
            continue
    return obs


# ── Regime computation ─────────────────────────────────────────────────────
def percentile(value: float, sample: list) -> float:
    """0-100 percentile of `value` within `sample`."""
    if not sample:
        return 50.0
    below = sum(1 for s in sample if s < value)
    return round(100 * below / len(sample), 1)


def classify_vix(v: float) -> str:
    if v < 15:
        return "low"
    if v < 25:
        return "mid"
    return "high"


def classify_2s10s(v: float) -> str:
    if v < 0:
        return "inverted"
    if v < 0.5:
        return "flat"
    return "normal"


def classify_hy_oas(value: float, sample_1y: list) -> tuple[str, float]:
    pct = percentile(value, sample_1y)
    if pct < 33:
        regime = "tight"
    elif pct < 67:
        regime = "normal"
    else:
        regime = "wide"
    return regime, pct


def cpi_yoy_from_index(obs: list) -> tuple[float, str, list]:
    """Compute current YoY %, trend, and 24-month YoY series for context.

    obs is newest-first. Returns (current_yoy_pct, trend, yoy_series_newest_first).
    """
    if len(obs) < 13:
        return (0.0, "stable", [])
    yoy_series = []
    for i in range(len(obs) - 12):
        cur = obs[i]["value"]
        prev = obs[i + 12]["value"]
        if prev > 0:
            yoy_series.append({
                "date": obs[i]["date"],
                "value": round(100 * (cur - prev) / prev, 2),
            })
    current = yoy_series[0]["value"] if yoy_series else 0.0
    # trend: slope of recent 6 months
    if len(yoy_series) >= 6:
        recent = [yoy_series[i]["value"] for i in range(6)]
        # newest-first, so trend = recent[0] - recent[-1]
        delta = recent[0] - recent[-1]
        if delta > 0.2:
            trend = "up"
        elif delta < -0.2:
            trend = "down"
        else:
            trend = "stable"
    else:
        trend = "stable"
    return current, trend, yoy_series[:24]


def compute_regime_tag(series: dict) -> str:
    """Combine 5 dimensions into a single regime label."""
    parts = []

    # Yield curve
    yc = series.get("yield_2s10s", {}).get("regime")
    if yc == "inverted":
        parts.append("recession_signal")
    elif yc == "flat":
        parts.append("late_cycle")
    else:
        parts.append("normal_cycle")

    # HY credit
    hy = series.get("hy_oas", {}).get("regime")
    if hy == "tight":
        parts.append("risk_on")
    elif hy == "wide":
        parts.append("risk_off")

    # VIX
    vix = series.get("vix", {}).get("regime")
    if vix == "high":
        parts.append("vol_stress")
    elif vix == "low" and "risk_on" in parts:
        parts.append("complacent")

    # CPI
    cpi_trend = series.get("cpi_yoy", {}).get("trend")
    if cpi_trend == "down":
        parts.append("disinflation")
    elif cpi_trend == "up":
        parts.append("reflation")

    return "/".join(parts) if parts else "neutral"


# ── Cache helpers ──────────────────────────────────────────────────────────
def is_cache_fresh(path: Path, ttl_hours: int) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < ttl_hours * 3600


def atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def write_skipped(reason: str) -> None:
    snapshot = {
        "status": "skipped",
        "reason": reason,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "series": {},
        "regime_tag": None,
    }
    atomic_write(CACHE_FILE, snapshot)


# ── Main ────────────────────────────────────────────────────────────────────
def main() -> int:
    load_env()
    force = "--force" in sys.argv
    dry_run = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "yes")

    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        print("⚠️  FRED_API_KEY missing, writing skipped status to cache")
        if not dry_run:
            write_skipped("no_api_key")
        return 0

    if not force and is_cache_fresh(CACHE_FILE, CACHE_TTL_HOURS):
        print(f"✅ macro cache fresh (< {CACHE_TTL_HOURS}h), skipping")
        return 0

    print(f"🔄 fetching {len(FRED_SERIES)} FRED series...")
    series_data: dict = {}
    errors: list = []

    # Fetch all series
    raw_obs: dict = {}
    for series_id, name in FRED_SERIES.items():
        if dry_run:
            print(f"[DRY-RUN] would fetch FRED {series_id} → {name}")
            continue
        obs = with_retry(lambda sid=series_id: fetch_series(sid, api_key),
                         f"FRED {series_id}", max_retries=3)
        if obs is None or len(obs) == 0:
            errors.append(series_id)
            continue
        raw_obs[name] = obs

    if dry_run:
        print("[DRY-RUN] complete, no write")
        return 0

    # Process each series into snapshot format
    # 1. fed_funds (daily, take latest)
    if "fed_funds" in raw_obs:
        obs = raw_obs["fed_funds"]
        latest = obs[0]
        # 30d change = latest vs ~30 days ago
        prev_30d = next((o["value"] for o in obs if
                         (datetime.strptime(latest["date"], "%Y-%m-%d") -
                          datetime.strptime(o["date"], "%Y-%m-%d")).days >= 30),
                        latest["value"])
        series_data["fed_funds"] = {
            "value": round(latest["value"], 2),
            "date": latest["date"],
            "prev_30d": round(prev_30d, 2),
            "change_30d": round(latest["value"] - prev_30d, 2),
        }

    # 2. cpi_yoy (compute from index)
    if "cpi_yoy" in raw_obs:
        cur_yoy, trend, yoy_series = cpi_yoy_from_index(raw_obs["cpi_yoy"])
        prev_yoy = yoy_series[1]["value"] if len(yoy_series) > 1 else cur_yoy
        series_data["cpi_yoy"] = {
            "value": cur_yoy,
            "date": yoy_series[0]["date"] if yoy_series else raw_obs["cpi_yoy"][0]["date"],
            "prev": prev_yoy,
            "trend": trend,
        }

    # 3. yield_2s10s
    if "yield_2s10s" in raw_obs:
        obs = raw_obs["yield_2s10s"]
        latest = obs[0]
        series_data["yield_2s10s"] = {
            "value": round(latest["value"], 2),
            "date": latest["date"],
            "regime": classify_2s10s(latest["value"]),
        }

    # 4. hy_oas
    if "hy_oas" in raw_obs:
        obs = raw_obs["hy_oas"]
        latest = obs[0]
        sample_1y = [o["value"] for o in obs[:252]]
        regime, pct = classify_hy_oas(latest["value"], sample_1y)
        series_data["hy_oas"] = {
            "value": round(latest["value"], 2),
            "date": latest["date"],
            "regime": regime,
            "pct_1y": pct,
        }

    # 5. vix
    if "vix" in raw_obs:
        obs = raw_obs["vix"]
        latest = obs[0]
        series_data["vix"] = {
            "value": round(latest["value"], 2),
            "date": latest["date"],
            "regime": classify_vix(latest["value"]),
        }

    regime_tag = compute_regime_tag(series_data)
    status = "ok" if not errors else "partial"

    snapshot = {
        "status": status,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "series": series_data,
        "regime_tag": regime_tag,
        "errors": errors,
    }
    atomic_write(CACHE_FILE, snapshot)
    print(f"✅ macro cache refreshed ({len(series_data)}/{len(FRED_SERIES)} series, "
          f"regime={regime_tag})")
    if errors:
        print(f"⚠️  errors on: {', '.join(errors)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
