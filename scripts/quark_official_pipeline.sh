#!/usr/bin/env bash
# 官方接口追更流水线（建议每 10 分钟跑一次）
#   1. 查「存进过自动转存目录的分享」有没有新增 -> saveas-update 存回原目录
#   2. 有新增才刷新 OpenList 缓存并重建 strm
#   3. 通知 Jellyfin 扫库（strm_sync.py 内部做）
# 无新增 = 无输出 = 不推送。全程不经过大模型，零 token。
set -uo pipefail

PY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${STRM_STATE_DIR:-$HOME/.cache/strm/state}"
mkdir -p "$STATE_DIR"
LOG="$STATE_DIR/pipeline.log"
LOCK="$STATE_DIR/pipeline.lock"

# 防并发：上一轮还没跑完就跳过这一轮
exec 9>"$LOCK"
flock -n 9 || exit 0

out=$(timeout 900 python3 "$PY/quark_official_save.py" 2>&1)
rc=$?

{
  echo "=== $(date '+%F %T') rc=$rc ==="
  echo "${out:-<无输出>}"
} >> "$LOG" 2>&1
tail -c 200000 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"

if [ "$rc" -ne 0 ]; then
  echo "${out}"
  exit 1
fi

# 没有任何存入动作 -> 静默
if [ -z "${out:-}" ]; then
  exit 0
fi

# 有新增：让 OpenList 拉最新目录，再重建 strm
STRM_REFRESH=1 timeout 900 python3 "$PY/strm_sync.py" 2>&1 | tail -3
echo "$out"
