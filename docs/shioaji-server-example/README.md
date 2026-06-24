# shioaji-server（自建 Python MCP 範例）

用 PyPI `shioaji` 套件直連永豐金證券，提供持倉/餘額/報價給 Step 0b。以 api_key/secret_key
登入，查詢持倉與報價**不需憑證**；下單才需 activate_ca（憑證 .pfx）。**不含金鑰，全從 `.env` 讀。**

```bash
mkdir shioaji-server && cd shioaji-server   # 放入 server.py / shioaji_setup.py / pyproject.toml
cp .env.example .env                         # 填永豐金 Shioaji API 金鑰
uv sync

uv run python3 shioaji_setup.py login        # 驗證金鑰、列出帳戶
uv run python3 shioaji_setup.py ca           # （選用，下單前）啟用憑證

claude mcp add shioaji-server -- uv --directory $(pwd) run server.py
```

**工具**：`get_account_position` / `get_account_balance` / `get_account_history` / `get_single_quote` / `get_watchlist_quote`

金鑰申請：永豐金證券 → 個人首頁 → API 金鑰管理。憑證至永豐 e-leader 下載 .pfx。
連線/金鑰問題見 `../setup-troubleshooting.md §3`。

> ⚠️ 可替換成富邦 neo（fubon-neo）、元大 等其他券商 API；只要對外提供相同的
> `get_account_*` / `get_*_quote` 工具介面，框架其餘部分無需改動。
