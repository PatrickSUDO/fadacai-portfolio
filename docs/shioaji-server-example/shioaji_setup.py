"""
永豐金 Shioaji 一次性連線/憑證設定（去敏感化範例）。
從同目錄 .env 讀 SHIOAJI_API_KEY / SHIOAJI_SECRET_KEY / SHIOAJI_CA_PATH /
SHIOAJI_CA_PASSWD / SHIOAJI_PERSON_ID。

Shioaji 不像 Firstrade 需要 email OTP：以 api_key/secret_key 直接登入；查詢持倉/報價
不需憑證，**下單**才需 activate_ca（憑證 .pfx）。本腳本只做：
  uv run python3 shioaji_setup.py login     -- 驗證 api_key/secret_key 可登入、列出帳戶
  uv run python3 shioaji_setup.py ca         -- 啟用憑證（下單前一次性）

申請金鑰：永豐金證券 → 個人首頁 → API 金鑰管理。憑證請至永豐 e-leader 下載 .pfx。
"""
import sys
import os
import shioaji as sj


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

API_KEY    = os.environ["SHIOAJI_API_KEY"]
SECRET_KEY = os.environ["SHIOAJI_SECRET_KEY"]
CA_PATH    = os.path.expanduser(os.environ.get("SHIOAJI_CA_PATH", ""))
CA_PASSWD  = os.environ.get("SHIOAJI_CA_PASSWD", "")
PERSON_ID  = os.environ.get("SHIOAJI_PERSON_ID", "")


def login():
    api = sj.Shioaji()
    accounts = api.login(api_key=API_KEY, secret_key=SECRET_KEY)
    print("✅ 登入成功。帳戶：")
    for a in accounts:
        print("  -", a)
    api.logout()


def ca():
    api = sj.Shioaji()
    api.login(api_key=API_KEY, secret_key=SECRET_KEY)
    ok = api.activate_ca(ca_path=CA_PATH, ca_passwd=CA_PASSWD, person_id=PERSON_ID)
    print("✅ 憑證啟用：" if ok else "❌ 憑證啟用失敗：", ok)
    api.logout()


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "login":
        login()
    elif len(sys.argv) >= 2 and sys.argv[1] == "ca":
        ca()
    else:
        print(__doc__)
