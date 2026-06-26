#!/usr/bin/env python3
"""
watchlist_tickers.py — shared ticker discovery for the cache-prefetch tools.

The workspace is watchlist-driven: `watchlist.md` is the single source of truth.
This module parses the markdown tables in `watchlist.md` and returns the tickers,
optionally including the cryptocurrency section.

Used by: earnings_history.py, fetch_fundamentals.py, fetch_news.py
"""

import os
import re
from pathlib import Path

# First markdown-table cell that looks like a ticker/symbol: 1-6 chars, A-Z/0-9
# (covers stocks like NVDA and crypto symbols like BTC, SOL).
_CELL_RE = re.compile(r"^\|\s*([A-Z0-9]{1,6})\s*\|")

# Header/label cells that are NOT tickers.
_NON_TICKER = {"TICKER", "SYMBOL", "LEAPS"}

# Section headers that begin the crypto table.
_CRYPTO_MARKERS = ("加密", "crypto", "CRYPTO", "Crypto")


def parse_watchlist_tickers(path: Path, include_crypto: bool = False) -> list[str]:
    """Parse tickers from a watchlist.md file.

    By default returns only equity/option tickers (the crypto section is skipped,
    since crypto has no earnings/PE). Set include_crypto=True to also return the
    crypto symbols.
    """
    if not path.exists():
        return []
    tickers: list[str] = []
    seen: set[str] = set()
    in_crypto_section = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("#"):
            in_crypto_section = any(m in line for m in _CRYPTO_MARKERS)
            continue
        if in_crypto_section and not include_crypto:
            continue
        m = _CELL_RE.match(raw)
        if not m:
            continue
        sym = m.group(1).upper()
        if sym in _NON_TICKER:
            continue
        if sym not in seen:
            tickers.append(sym)
            seen.add(sym)
    return tickers


def parse_crypto_symbols(path: Path) -> list[str]:
    """Return ONLY the symbols under the crypto section of watchlist.md."""
    if not path.exists():
        return []
    symbols: list[str] = []
    seen: set[str] = set()
    in_crypto_section = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("#"):
            in_crypto_section = any(m in line for m in _CRYPTO_MARKERS)
            continue
        if not in_crypto_section:
            continue
        m = _CELL_RE.match(raw)
        if not m:
            continue
        sym = m.group(1).upper()
        if sym in _NON_TICKER:
            continue
        if sym not in seen:
            symbols.append(sym)
            seen.add(sym)
    return symbols


def get_tickers(root: Path, env_var: str | None = None,
                include_crypto: bool = False) -> list[str]:
    """Resolve tickers: watchlist.md first, then optional env-var override."""
    wl = root / "watchlist.md"
    ts = parse_watchlist_tickers(wl, include_crypto=include_crypto)
    if ts:
        print(f"📋 tickers from watchlist.md: {len(ts)} found")
        return ts
    if env_var:
        env_tickers = os.environ.get(env_var, "").strip()
        if env_tickers:
            ts = [s.strip().upper() for s in env_tickers.split(",") if s.strip()]
            print(f"📋 tickers from {env_var} env: {len(ts)} found")
            return ts
    print(f"⚠️  no tickers found (watchlist.md empty"
          + (f" + {env_var} unset)" if env_var else ")"))
    return []
