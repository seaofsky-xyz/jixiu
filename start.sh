#!/usr/bin/env bash
# 设备快速报修 · 一键试运行（前台运行，Ctrl+C 停止）
# 生产环境请用 systemd：sudo systemctl enable --now repair
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "未找到 python3，请先安装：sudo apt install -y python3"
  exit 1
fi

PYV=$(python3 -c 'import sys;print("%d%d"%sys.version_info[:2])')
if [ "$PYV" -lt 38 ]; then
  echo "Python 版本过低（当前 $PYV），需要 3.8 及以上"
  exit 1
fi

if [ ! -f static/index.html ]; then
  echo "未找到 static/index.html，请先构建："
  echo "  python3 build_page.py --src ./设备快速报修.html"
  exit 1
fi

mkdir -p logs data
echo "启动中…… 打开 http://服务器IP:$(python3 -c "
import json,os
c={}
try:
    c=json.load(open('config.json',encoding='utf-8'))
except Exception:
    pass
print(c.get('port',8080))
")/"
exec python3 server.py
