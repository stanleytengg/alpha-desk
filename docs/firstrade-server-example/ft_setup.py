"""
Firstrade one-time auth setup (de-sensitized example).
Reads credentials from the same-dir .env (FT_USERNAME / FT_PASSWORD / FT_PIN / FT_EMAIL).

Two steps (split to avoid interactive input issues in headless shells):
  uv run python3 ft_setup.py step1          -- triggers OTP to registered email/phone
  uv run python3 ft_setup.py step2 <code>   -- completes auth and saves session cookies

After this, server.py reuses the saved session (~30 days) with no further OTP.
"""
import sys, os, json, requests
from firstrade.account import FTSession, FTAccountData
from firstrade import urls


def _load_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        for line in open(env_path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                v = v.split("#")[0].strip().strip('"').strip("'")
                os.environ.setdefault(k.strip(), v)


_load_env()

STATE_FILE = "/tmp/ft_auth_state.json"
PROFILE    = os.path.expanduser("~/.local/share/firstrade-session")
USERNAME   = os.environ["FT_USERNAME"]
PASSWORD   = os.environ["FT_PASSWORD"]
EMAIL      = os.environ.get("FT_EMAIL", "")


def step1():
    s = FTSession(username=USERNAME, password=PASSWORD, email=EMAIL,
                  profile_path=PROFILE, save_session=True)
    need_code = s.login()
    print("need_code:", need_code, "| login_json:", s.login_json)
    state = {
        "headers": dict(s.session.headers),
        "cookies": requests.utils.dict_from_cookiejar(s.session.cookies),
        "t_token": s.t_token,
        "verification_sid": s.login_json.get("verificationSid", ""),
        "mfa": s.login_json.get("mfa", False),
    }
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)
    print("✅ OTP triggered. Run: uv run python3 ft_setup.py step2 <CODE>")


def step2(code):
    state = json.load(open(STATE_FILE))
    s = FTSession(username=USERNAME, password=PASSWORD, email=EMAIL,
                  profile_path=PROFILE, save_session=True)
    s.session.headers.update(state["headers"])
    for k, v in state["cookies"].items():
        s.session.cookies.set(k, v)
    s.t_token = state["t_token"]
    s.login_json = {"mfa": state["mfa"]}

    if state["mfa"]:
        data = {"mfaCode": code, "remember_for": "30", "t_token": state["t_token"]}
    else:
        data = {"otpCode": code, "verificationSid": state["verification_sid"],
                "remember_for": "30", "t_token": state["t_token"]}

    result = s._request("post", url=urls.verify_pin(), data=data).json()
    if result.get("error"):
        print("❌", result["error"]); sys.exit(1)
    s.session.headers["ftat"] = result.get("ftat", "")
    s.session.headers["sid"]  = result.get("sid", "")
    s._save_cookies()
    d = FTAccountData(s)
    print("✅ Auth complete! Accounts:", d.account_numbers)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "step1":
        step1()
    elif len(sys.argv) == 3 and sys.argv[1] == "step2":
        step2(sys.argv[2])
    else:
        print(__doc__)
