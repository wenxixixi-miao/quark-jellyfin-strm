#!/usr/bin/env bash
# 兜底同步（建议每 2 小时）：手动往两个来源目录塞了新内容时也能被发现。
# 有变化才输出；另外会提示新增的、还没配 TMDB 的目录。
set -uo pipefail

PY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${STRM_STATE_DIR:-$HOME/.cache/strm/state}"
mkdir -p "$STATE_DIR"

exec 9>"$STATE_DIR/fallback.lock"
flock -n 9 || exit 0

STRM_REFRESH=1 timeout 1200 python3 "$PY/strm_sync.py" 2>&1 | tail -4
exit 0
