# X（Twitter）追蹤名單整理 — `tools/x_curate.py`

目的：讓手機 X 的「正在跟隨」時間線只剩財經 / AI / 半導體訊號。一次性整理 + 可重跑。

## 為什麼不是純 API

X API 自 2026-04 起把 follow / unfollow / like 寫入端點從自助方案（含 pay-per-use）移除，只剩 Enterprise。
所以分工是：

| 層 | 做法 | 成本 |
|---|---|---|
| 讀名單、驗帳號、抓最近貼文 | X API v2（bearer，`.env X_BEARER_TOKEN`） | user read $0.010/個、post read $0.005/則 |
| 退追 / 追蹤 | Claude 操作已登入的 Chrome（Claude in Chrome），逐一開 profile 點按鈕 | 0，但受 X 追蹤速率限制 |
| 記帳 | `research/x-curation/`（整個 research/ 已 gitignore） | — |

## 流程（2026-10-19 首跑）

1. `pull-following --handle <參考帳號>`：拉參考名單（本次用 @mengkunghsieh／股癌 238 帳）與自己的名單快照（= 備份，退追可逆）。
2. Workflow A：9 個類別 agent 並行提名 + 1 個 agent 過濾參考名單 → 去重（168 個候選）。
3. `resolve <handles…>`：API 一次驗 100 個 handle（存在 / bio / 粉絲 / 建立日 → 算 lifetime 日均貼文量）。
4. Workflow B：每桶一個評審（上限、流量紀律：>40 則/日剔除、新聞 firehose 剔除、同題材去重）→ 每桶一個懷疑者跑 `recent -n 5` 讀最近 5 則原創貼文反證（停更 >90 天、離題 ≥3/5、engagement bait → 淘汰）。
5. `plan.json` = unfollow / follow_whitelist（`source-config.json` 的 X 來源）/ follow / refuted / excluded_by_judge。
6. Chrome 執行；**UI 回報不可信**（限速時按鈕會先變再彈回），一律 `pull-following` 再 `reconcile` 以 API 快照為準。
7. `report` 產出 `research/x-curation/report-<date>.md`。

## 實測限制

- 新帳號（0 貼文 / 0 粉絲）連續追蹤約 20–25 個後出現「Sorry, you are rate limited」，需等待再分批（每批 ≤5、批間隔數分鐘）。
- 有訂閱功能的帳號追蹤後主按鈕變「Subscribe」，`data-testid` 仍是 `<id>-unfollow`，判斷狀態要看 testid 不是文字。
- `recent` 排除轉推與回覆；只轉推的帳號會顯示 0 則原創，判定停更前先看 `tweets` 總數。

## 指令

```bash
python3 tools/x_curate.py pull-following --handle patricksudo          # 快照 / 備份
python3 tools/x_curate.py resolve @a @b …                              # 驗帳號
python3 tools/x_curate.py recent @a @b -n 5                            # 最近原創貼文
python3 tools/x_curate.py reconcile && python3 tools/x_curate.py status  # 對帳 + 待辦
python3 tools/x_curate.py report
```
