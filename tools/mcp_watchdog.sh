#!/usr/bin/env bash
# tools/mcp_watchdog.sh — FMP MCP container health watchdog
#
# Called every 5 minutes by ~/Library/LaunchAgents/com.fadacai.mcp-watchdog.plist
#
# What it does:
#   1. If Docker daemon is not running → open Docker Desktop and wait
#   2. Check FMP /healthcheck endpoint (stateless probe, no MCP session needed)
#   3. If healthy → silent exit (no log spam on good runs)
#   4. If unhealthy → docker compose restart + log
#
# Log: /Users/supatrick/laptop/mcp-servers/fmp-mcp/watchdog.log (auto-rotated at 1MB)

COMPOSE_FILE="/Users/supatrick/laptop/mcp-servers/fmp-mcp/compose.yaml"
LOG="/Users/supatrick/laptop/mcp-servers/fmp-mcp/watchdog.log"
FMP_HEALTH="http://localhost:8081/healthcheck"
ROTATE_BYTES=1048576  # 1 MB

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"
}

# ── Log rotation ────────────────────────────────────────────────────────────
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt "$ROTATE_BYTES" ]; then
    mv "$LOG" "${LOG}.bak"
fi

# ── Check Docker daemon ─────────────────────────────────────────────────────
if ! docker info >/dev/null 2>&1; then
    log "⚠️  Docker daemon not running — opening Docker Desktop"
    open -a Docker
    log "   Waiting 20s for Docker to start..."
    sleep 20
    if ! docker info >/dev/null 2>&1; then
        log "❌ Docker still not running after 20s — skipping FMP check (will retry in 5 min)"
        exit 1
    fi
    log "✅ Docker daemon now running"
fi

# ── Check FMP health ────────────────────────────────────────────────────────
if curl -fsS --max-time 5 "$FMP_HEALTH" >/dev/null 2>&1; then
    # Healthy — silent success; no log entry to avoid noise
    exit 0
fi

# ── Unhealthy: restart ──────────────────────────────────────────────────────
log "⚠️  FMP healthcheck failed (${FMP_HEALTH}) — restarting container"
if docker compose -f "$COMPOSE_FILE" restart >>"$LOG" 2>&1; then
    log "✅ FMP container restarted successfully"
else
    log "❌ docker compose restart failed (exit $?) — check compose logs"
    exit 1
fi
