#!/usr/bin/env bash
# 设备快速报修 · 每日备份
# 用法：./deploy/backup.sh
# 定时：0 2 * * * /opt/repair/deploy/backup.sh >> /opt/repair/logs/backup.log 2>&1
set -euo pipefail

BASE="$(cd "$(dirname "$0")/.." && pwd)"
DB="$BASE/data/repair.db"
DIR="$BASE/backups"
KEEP=30

mkdir -p "$DIR"

if [ ! -f "$DB" ]; then
  echo "[$(date '+%F %T')] 找不到数据库：$DB"
  exit 1
fi

OUT="$DIR/repair-$(date '+%Y%m%d-%H%M%S').db"

# 用 SQLite 在线备份 API，服务运行中也能安全备份（不要直接 cp，可能拷到半截数据）
python3 - "$DB" "$OUT" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
s = sqlite3.connect(src)
d = sqlite3.connect(dst)
with d:
    s.backup(d)
d.close(); s.close()
PY

echo "[$(date '+%F %T')] 已备份 -> $OUT ($(du -h "$OUT" | cut -f1))"

# 清理超过 30 天的备份
find "$DIR" -name 'repair-*.db' -type f -mtime +$KEEP -print -delete | while read -r f; do
  echo "[$(date '+%F %T')] 已清理旧备份：$f"
done
