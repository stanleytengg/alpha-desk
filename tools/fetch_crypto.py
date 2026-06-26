#!/usr/bin/env python3
"""
fetch_crypto.py — Cache a tokenomics/market snapshot for watchlist crypto symbols.

Optional pre-fetch for /briefing and /crypto-analysis. Uses the public CoinGecko
REST API (no key required for these endpoints; COINGECKO_API_KEY raises rate limits).
Degrades gracefully: if CoinGecko is unreachable, writes status="skipped" and the
skills fall back to yfinance (BTC-USD) + WebSearch.

Output:
  briefing-out/cache/crypto-snapshot.json
    {
      "status": "ok" | "skipped",
      "fetched_at": "<iso>",
      "btc_dominance": <float|null>,
      "total_market_cap_usd": <float|null>,
      "coins": { "BTC": {price, market_cap, rank, circulating, max_supply,
                          pct_circulating, ath, pct_from_ath, vol_24h}, ... },
      "skipped": ["<SYM>", ...]   # symbols with no known CoinGecko id
    }

Ticker source: ROOT/watchlist.md crypto section (shared watchlist_tickers.py).
"""

import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "briefing-out" / "cache"
SNAP_FILE = CACHE_DIR / "crypto-snapshot.json"
CG_BASE = "https://api.coingecko.com/api/v3"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from watchlist_tickers import parse_crypto_symbols

# Built-in symbol → CoinGecko id map for common assets. Unknown symbols are
# resolved via /coins/list (cached in-process) and skipped if still not found.
KNOWN_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "BNB": "binancecoin",
    "XRP": "ripple", "ADA": "cardano", "AVAX": "avalanche-2", "DOGE": "dogecoin",
    "DOT": "polkadot", "MATIC": "matic-network", "LINK": "chainlink",
    "LTC": "litecoin", "TRX": "tron", "ATOM": "cosmos", "UNI": "uniswap",
    "AAVE": "aave", "ARB": "arbitrum", "OP": "optimism", "SUI": "sui",
    "TON": "the-open-network", "NEAR": "near", "APT": "aptos", "INJ": "injective-protocol",
}


def load_env() -> None:
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


def _ctx():
    return ssl._create_unverified_context()


def _headers() -> dict:
    key = os.environ.get("COINGECKO_API_KEY", "").strip()
    return {"x-cg-demo-api-key": key} if key else {}


def _get(url: str, timeout: int = 20):
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as resp:
        return json.loads(resp.read())


def resolve_ids(symbols: list[str]) -> tuple[dict[str, str], list[str]]:
    """Map symbols → CoinGecko ids. Returns (id_map, skipped)."""
    id_map: dict[str, str] = {}
    unknown: list[str] = []
    for s in symbols:
        if s in KNOWN_IDS:
            id_map[s] = KNOWN_IDS[s]
        else:
            unknown.append(s)
    if unknown:
        try:
            coins = _get(f"{CG_BASE}/coins/list")
            by_symbol: dict[str, str] = {}
            for c in coins:
                sym = c.get("symbol", "").upper()
                # first occurrence wins (CoinGecko lists are roughly rank-ordered)
                by_symbol.setdefault(sym, c.get("id", ""))
            for s in list(unknown):
                if by_symbol.get(s):
                    id_map[s] = by_symbol[s]
                    unknown.remove(s)
        except Exception as e:
            print(f"[fetch_crypto] coins/list lookup failed: {e}")
    return id_map, unknown


def write_skipped(reason: str, skipped: list[str]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    SNAP_FILE.write_text(json.dumps({
        "status": "skipped",
        "reason": reason,
        "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
        "coins": {},
        "skipped": skipped,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[fetch_crypto] skipped: {reason}")


def main() -> int:
    load_env()
    symbols = parse_crypto_symbols(ROOT / "watchlist.md")
    if not symbols:
        write_skipped("no crypto symbols in watchlist.md", [])
        return 0

    try:
        id_map, unresolved = resolve_ids(symbols)
        if not id_map:
            write_skipped("no resolvable CoinGecko ids", unresolved)
            return 0

        ids = ",".join(sorted(set(id_map.values())))
        markets = _get(f"{CG_BASE}/coins/markets?"
                       + urllib.parse.urlencode({"vs_currency": "usd", "ids": ids}))
        by_id = {m["id"]: m for m in markets}

        coins: dict[str, dict] = {}
        for sym, cid in id_map.items():
            m = by_id.get(cid)
            if not m:
                unresolved.append(sym)
                continue
            circ = m.get("circulating_supply")
            mx = m.get("max_supply")
            coins[sym] = {
                "id": cid,
                "price": m.get("current_price"),
                "market_cap": m.get("market_cap"),
                "rank": m.get("market_cap_rank"),
                "vol_24h": m.get("total_volume"),
                "circulating": circ,
                "max_supply": mx,
                "pct_circulating": round(circ / mx * 100, 1) if (circ and mx) else None,
                "ath": m.get("ath"),
                "pct_from_ath": m.get("ath_change_percentage"),
            }

        btc_dom = None
        total_mc = None
        try:
            g = _get(f"{CG_BASE}/global").get("data", {})
            btc_dom = g.get("market_cap_percentage", {}).get("btc")
            total_mc = g.get("total_market_cap", {}).get("usd")
        except Exception as e:
            print(f"[fetch_crypto] global endpoint failed (non-fatal): {e}")

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        SNAP_FILE.write_text(json.dumps({
            "status": "ok",
            "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
            "btc_dominance": btc_dom,
            "total_market_cap_usd": total_mc,
            "coins": coins,
            "skipped": unresolved,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[fetch_crypto] ok: {len(coins)} coins cached"
              + (f"; skipped {unresolved}" if unresolved else ""))
        return 0

    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        write_skipped(f"CoinGecko unreachable: {e}", symbols)
        return 0
    except Exception as e:
        write_skipped(f"unexpected error: {e}", symbols)
        return 0


if __name__ == "__main__":
    sys.exit(main())
