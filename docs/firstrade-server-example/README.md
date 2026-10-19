# firstrade-server（自建 Python MCP 範例）

用 PyPI `firstrade` 套件直連券商，提供持倉/餘額/報價給 Step 0b。比官方 Rust 版簡單（單一服務、saved session 免每次 OTP）。**不含憑證，全從 `.env` 讀。**

```bash
mkdir firstrade-server && cd firstrade-server   # 放入 server.py / ft_setup.py / pyproject.toml
cp .env.example .env                            # 填 Firstrade 帳密
uv sync

uv run python3 ft_setup.py step1                # 首次：觸發 OTP
uv run python3 ft_setup.py step2 123456         # 輸入驗證碼（之後 ~30 天免 OTP）

claude mcp add firstrade-server -- uv --directory $(pwd) run server.py
```

**工具**：`get_account_position` / `get_account_balance` / `get_account_history` / `get_single_quote` / `get_watchlist_quote`

session 過期（~30 天）→ 重跑 `ft_setup.py`。細節見 `../setup-troubleshooting.md 第 3 節`。
