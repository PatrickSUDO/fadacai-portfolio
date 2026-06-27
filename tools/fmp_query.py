#!/usr/bin/env python3
"""
tools/fmp_query.py — FMP MCP curl 旁路 helper
Source:  FMP MCP HTTP server（http://localhost:8081/mcp）
Output:  stdout JSON（tool result，可直接 json.loads）
TTL:     無快取；每次呼叫做全新 MCP session handshake → 免疫 client session 過期
Usage:
  python3 tools/fmp_query.py getBiggestGainers
  python3 tools/fmp_query.py getStockPeers --args '{"symbol":"NVDA"}'
  python3 tools/fmp_query.py getEarningsCalendar --args '{"from":"2026-06-28","to":"2026-07-28"}'
  python3 tools/fmp_query.py getCompanyProfile --args '{"symbol":"AAPL"}'
  python3 tools/fmp_query.py getMostActiveStocks

原理：
  每次呼叫走完整 MCP Streamable HTTP 握手：
    initialize → notifications/initialized → tools/call
  建立全新一次性 session（Mcp-Session-Id），用完即棄。
  Claude Code client 持有的 stale session-id 對這個 helper 完全無影響。

背景（為何存在）：
  FMP MCP server 是 stateful HTTP server（http://localhost:8081/mcp）。
  Claude Code client 在 session 間快取 Mcp-Session-Id；server 端把閒置 session
  淘汰後，client 仍用舊 id → 「Session not found or expired」。
  用這個 helper 不走 Claude Code 的 MCP client 層，每次都拿新 session。
"""

import json
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("⚠️  requests 未安裝。請先：pip install requests", file=sys.stderr)
    sys.exit(1)

# ── 路徑設定（與 fetch_fundamentals.py 相同慣例）──────────────────────────────
ROOT = Path(__file__).resolve().parent.parent


def load_env() -> None:
    """從 project root 的 .env 載入環境變數（stdlib only，不需 python-dotenv）。"""
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


def parse_cli() -> tuple[str, dict]:
    """解析 CLI 參數：<toolName> [--args '<json>']"""
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    tool_name = args[0]
    tool_args: dict = {}
    if "--args" in args:
        idx = args.index("--args")
        if idx + 1 < len(args):
            try:
                tool_args = json.loads(args[idx + 1])
            except json.JSONDecodeError as e:
                print(f"⚠️  --args 不是合法 JSON：{e}", file=sys.stderr)
                sys.exit(1)
    return tool_name, tool_args


def _extract_sse_messages(text: str) -> list[dict]:
    """解析 SSE text/event-stream 回應中的 data: JSON lines。"""
    messages = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload and payload != "[DONE]":
                try:
                    messages.append(json.loads(payload))
                except json.JSONDecodeError:
                    pass
    return messages


def fmp_handshake(base_url: str, tool_name: str, tool_args: dict, timeout: int = 30) -> object:
    """
    完整 MCP Streamable HTTP 握手：
      1. initialize   → 取得 Mcp-Session-Id
      2. notifications/initialized  （notification，忽略回應）
      3. tools/call   → 取得 tool result，回傳 parsed JSON

    Raises:
      RuntimeError   — 握手失敗或 tool 回錯誤
      requests.*     — 網路/HTTP 錯誤（由 main() 捕捉）
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    # ── Step 1: initialize ───────────────────────────────────────────────────
    init_body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "fmp_query", "version": "1.0"},
        },
    }
    r1 = requests.post(base_url, headers=headers, json=init_body, timeout=timeout)
    r1.raise_for_status()

    session_id = r1.headers.get("Mcp-Session-Id") or r1.headers.get("mcp-session-id")
    if not session_id:
        raise RuntimeError(
            f"initialize 成功但未回傳 Mcp-Session-Id header。\n"
            f"回應 headers: {dict(r1.headers)}\n"
            f"回應 body (前 400 chars): {r1.text[:400]}"
        )

    headers_with_session = {**headers, "Mcp-Session-Id": session_id}

    # ── Step 2: notifications/initialized ────────────────────────────────────
    notif_body = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    try:
        requests.post(base_url, headers=headers_with_session, json=notif_body, timeout=timeout)
    except Exception:
        pass  # notification：不期待特定回應，忽略任何錯誤

    # ── Step 3: tools/call ───────────────────────────────────────────────────
    call_body = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": tool_args},
    }
    r3 = requests.post(base_url, headers=headers_with_session, json=call_body, timeout=timeout)
    r3.raise_for_status()

    # 解析回應（JSON 或 SSE）
    ct = r3.headers.get("Content-Type", "")
    if "text/event-stream" in ct:
        messages = _extract_sse_messages(r3.text)
    else:
        try:
            messages = [r3.json()]
        except json.JSONDecodeError:
            raise RuntimeError(f"tools/call 回應不是合法 JSON 也不是 SSE：{r3.text[:500]}")

    # 找 id=2 的 result
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        if msg.get("id") == 2:
            if "error" in msg:
                err = msg["error"]
                raise RuntimeError(
                    f"FMP tools/call 錯誤 {err.get('code')}: {err.get('message')}"
                )
            if "result" in msg:
                content = msg["result"].get("content", [])
                if content and content[0].get("type") == "text":
                    try:
                        return json.loads(content[0]["text"])
                    except json.JSONDecodeError:
                        # 非 JSON 文字（罕見）→ 直接回字串
                        return {"raw": content[0]["text"]}
                return msg["result"]

    raise RuntimeError(
        f"tools/call 回應未含 id=2 的 result。\n收到訊息：{json.dumps(messages[:2], ensure_ascii=False)[:600]}"
    )


def main() -> None:
    load_env()
    tool_name, tool_args = parse_cli()
    base_url = os.environ.get("FMP_MCP_URL", "http://localhost:8081/mcp")

    print(f"🔌 FMP query → {tool_name} {json.dumps(tool_args) if tool_args else ''}", file=sys.stderr)

    try:
        result = fmp_handshake(base_url, tool_name, tool_args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except requests.exceptions.ConnectionError:
        print(
            f"❌ 無法連線 {base_url}（FMP 容器未啟動？）\n"
            "   → 啟動：docker compose -f /Users/supatrick/laptop/mcp-servers/fmp-mcp/compose.yaml up -d",
            file=sys.stderr,
        )
        sys.exit(2)
    except requests.exceptions.HTTPError as e:
        print(
            f"❌ HTTP {e.response.status_code}：{e.response.text[:400]}",
            file=sys.stderr,
        )
        sys.exit(2)
    except RuntimeError as e:
        print(f"❌ {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
