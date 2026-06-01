import os
import json
from mcp.server.fastmcp import FastMCP
from firstrade.account import FTSession, FTAccountData


def _load_env():
    """Load FT_* credentials from server-dir .env (stdlib only, no commit risk)."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    v = v.split("#")[0].strip()
                    if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                        v = v[1:-1]
                    os.environ.setdefault(k.strip(), v)


_load_env()

mcp = FastMCP("firstrade-server")

USERNAME = os.environ.get("FT_USERNAME", "")
PASSWORD = os.environ.get("FT_PASSWORD", "")
PIN      = os.environ.get("FT_PIN", "")
EMAIL    = os.environ.get("FT_EMAIL", "")
PROFILE  = os.path.expanduser("~/.local/share/firstrade-session")

_session: FTSession | None = None
_data: FTAccountData | None = None


def _get_data() -> tuple[FTSession, FTAccountData]:
    global _session, _data
    if _session is None:
        _session = FTSession(
            username=USERNAME,
            password=PASSWORD,
            pin=PIN,
            email=EMAIL,
            profile_path=PROFILE,
            save_session=True,
        )
        # login() returns False when an existing saved session is reused (success),
        # True when a fresh OTP code is required (can't satisfy headlessly).
        need_code = _session.login()
        if need_code:
            raise RuntimeError(
                "Firstrade OTP required — saved session expired. "
                "Run: uv run python3 tools/ft_setup.py step1/step2 to refresh."
            )
        _data = FTAccountData(_session)
    return _session, _data


@mcp.tool()
def get_account_position() -> str:
    """Get current stock and options positions for all accounts."""
    _, data = _get_data()
    result = {}
    for acct in data.account_numbers:
        result[acct] = data.get_positions(acct)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def get_account_balance() -> str:
    """Get account equity, cash, and balance overview for all accounts."""
    _, data = _get_data()
    result = {}
    for acct in data.account_numbers:
        result[acct] = data.get_account_balances(acct)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def get_account_history(date_range: str = "1m") -> str:
    """Get transaction history. date_range: today|1w|1m|2m|mtd|ytd|ly"""
    _, data = _get_data()
    result = {}
    for acct in data.account_numbers:
        result[acct] = data.get_account_history(acct, date_range=date_range)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def get_single_quote(symbol: str) -> str:
    """Get real-time quote for a stock symbol."""
    session, data = _get_data()
    if not data.account_numbers:
        return json.dumps({"error": "No account found"})
    acct = data.account_numbers[0]
    from firstrade import urls
    resp = session._request("get", urls.quote(acct, symbol))
    return json.dumps(resp.json(), ensure_ascii=False)


@mcp.tool()
def get_watchlist_quote(symbols: str) -> str:
    """Get real-time quotes for multiple symbols (comma-separated, e.g. 'AAPL,NVDA,MU')."""
    session, data = _get_data()
    if not data.account_numbers:
        return json.dumps({"error": "No account found"})
    acct = data.account_numbers[0]
    from firstrade import urls
    results = {}
    for sym in [s.strip() for s in symbols.split(",")]:
        resp = session._request("get", urls.quote(acct, sym))
        results[sym] = resp.json()
    return json.dumps(results, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
