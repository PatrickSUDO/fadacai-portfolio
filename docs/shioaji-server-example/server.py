import os
import json
from mcp.server.fastmcp import FastMCP
import shioaji as sj


def _load_env():
    """Load SHIOAJI_* credentials from server-dir .env (stdlib only, no commit risk)."""
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

mcp = FastMCP("shioaji-server")

API_KEY    = os.environ.get("SHIOAJI_API_KEY", "")
SECRET_KEY = os.environ.get("SHIOAJI_SECRET_KEY", "")
CA_PATH    = os.path.expanduser(os.environ.get("SHIOAJI_CA_PATH", ""))   # 憑證 .pfx（下單才需）
CA_PASSWD  = os.environ.get("SHIOAJI_CA_PASSWD", "")
PERSON_ID  = os.environ.get("SHIOAJI_PERSON_ID", "")

_api: "sj.Shioaji | None" = None


def _get_api() -> "sj.Shioaji":
    """Lazy login。永豐金 Shioaji 以 api_key/secret_key 登入；查詢持倉/報價不需 OTP。
    下單才需 activate_ca（憑證）。session 失效 → 重跑 shioaji_setup.py。"""
    global _api
    if _api is None:
        api = sj.Shioaji()  # 正式環境；測試可加 simulation=True
        if not API_KEY or not SECRET_KEY:
            raise RuntimeError(
                "SHIOAJI_API_KEY / SHIOAJI_SECRET_KEY 未設定 — "
                "請在 .env 填入永豐金 Shioaji API 金鑰。"
            )
        api.login(api_key=API_KEY, secret_key=SECRET_KEY, contracts_timeout=10000)
        if CA_PATH and PERSON_ID:
            try:
                api.activate_ca(ca_path=CA_PATH, ca_passwd=CA_PASSWD, person_id=PERSON_ID)
            except Exception as e:  # 查詢仍可用，僅下單受影響
                print(f"[shioaji] activate_ca skipped: {e}")
        _api = api
    return _api


@mcp.tool()
def get_account_position() -> str:
    """取得現股 + 期貨/選擇權 持倉（所有帳戶）。"""
    api = _get_api()
    result = {}
    # 證券帳戶現股
    if getattr(api, "stock_account", None):
        result["stock"] = [p.__dict__ if hasattr(p, "__dict__") else p
                           for p in api.list_positions(api.stock_account)]
    # 期貨帳戶（期/選）
    if getattr(api, "futopt_account", None):
        result["futopt"] = [p.__dict__ if hasattr(p, "__dict__") else p
                            for p in api.list_positions(api.futopt_account)]
    return json.dumps(result, ensure_ascii=False, default=str)


@mcp.tool()
def get_account_balance() -> str:
    """取得帳戶權益、現金與交割款。"""
    api = _get_api()
    bal = api.account_balance()
    return json.dumps(bal.__dict__ if hasattr(bal, "__dict__") else bal,
                      ensure_ascii=False, default=str)


@mcp.tool()
def get_account_history(start: str = "", end: str = "") -> str:
    """取得成交/委託歷史（start/end 為 YYYY-MM-DD；空值=當日）。"""
    api = _get_api()
    acct = getattr(api, "stock_account", None)
    if acct is None:
        return json.dumps({"error": "No stock account"})
    profitloss = api.list_profit_loss(acct, start or None, end or None)
    return json.dumps([p.__dict__ if hasattr(p, "__dict__") else p
                       for p in profitloss], ensure_ascii=False, default=str)


def _contract(api, symbol: str):
    """4 碼代號 → Shioaji 合約（先試上市 TSE，再試上櫃 OTC）。"""
    for exch in (api.Contracts.Stocks.TSE, api.Contracts.Stocks.OTC):
        c = exch.get(symbol)
        if c is not None:
            return c
    return None


@mcp.tool()
def get_single_quote(symbol: str) -> str:
    """取得單一台股即時報價（snapshot，含成交價/漲跌/量）。symbol = 4 碼代號，如 '2330'。"""
    api = _get_api()
    c = _contract(api, symbol)
    if c is None:
        return json.dumps({"error": f"contract not found: {symbol}"})
    snap = api.snapshots([c])
    return json.dumps([s.__dict__ if hasattr(s, "__dict__") else s for s in snap],
                      ensure_ascii=False, default=str)


@mcp.tool()
def get_watchlist_quote(symbols: str) -> str:
    """取得多檔台股即時報價（逗號分隔 4 碼代號，如 '2330,2454,3661'）。"""
    api = _get_api()
    contracts = []
    for sym in [s.strip() for s in symbols.split(",") if s.strip()]:
        c = _contract(api, sym)
        if c is not None:
            contracts.append(c)
    if not contracts:
        return json.dumps({"error": "no valid contracts"})
    snap = api.snapshots(contracts)
    return json.dumps([s.__dict__ if hasattr(s, "__dict__") else s for s in snap],
                      ensure_ascii=False, default=str)


if __name__ == "__main__":
    mcp.run()
