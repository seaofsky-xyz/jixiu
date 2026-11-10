#!/usr/bin/env bash
# 设备快速报修 · 一键部署到 8080（在目标服务器上以 root 执行）
#
#   sudo bash install_8080.sh
#
# 做的事：装到 /opt/repair → 注册 systemd 服务 repair → 开机自启 → 健康检查
set -euo pipefail

APP_DIR=/opt/repair
PORT=8080
SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
# 脚本位于 deploy/ 子目录时，向上一级找项目根（以 server.py 为标志）
if [ ! -f "$SRC_DIR/server.py" ] && [ -f "$SRC_DIR/../server.py" ]; then
  SRC_DIR="$(cd "$SRC_DIR/.." && pwd)"
fi
[ -f "$SRC_DIR/server.py" ] || { echo "[失败] 找不到 server.py，请在部署包目录内执行" >&2; exit 1; }

say() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m[失败] %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "请用 root 执行：sudo bash install_8080.sh"

say "1/6 检查 Python"
command -v python3 >/dev/null 2>&1 || {
  say "未装 python3，尝试安装"
  if command -v apt-get >/dev/null 2>&1; then apt-get update -qq && apt-get install -y python3
  elif command -v yum >/dev/null 2>&1; then yum install -y python3
  else die "请手动安装 python3（3.8+）"; fi
}
PYV=$(python3 -c 'import sys;print("%d%02d"%sys.version_info[:2])')
[ "$PYV" -ge 308 ] || die "Python 版本过低（需要 3.8+）"

say "2/6 安装目录 $APP_DIR"
systemctl stop repair 2>/dev/null || true
mkdir -p "$APP_DIR"
# 保留旧数据库与已有配置，避免覆盖线上真实工单和企微机器人 key
if [ -f "$APP_DIR/data/repair.db" ]; then
  cp -a "$APP_DIR/data/repair.db" "/tmp/repair.db.keep.$$"
  echo "检测到已有数据库，已临时备份到 /tmp/repair.db.keep.$$"
fi
if [ -f "$APP_DIR/config.json" ]; then
  cp -a "$APP_DIR/config.json" "/tmp/repair.cfg.keep.$$"
  echo "检测到已有配置（企微 key 等），安装后保留"
fi
cp -a "$SRC_DIR/." "$APP_DIR/"
rm -rf "$APP_DIR/logs"/*.log 2>/dev/null || true
mkdir -p "$APP_DIR/logs" "$APP_DIR/data"
if [ -f "/tmp/repair.db.keep.$$" ]; then
  mv -f "/tmp/repair.db.keep.$$" "$APP_DIR/data/repair.db"
fi
if [ -f "/tmp/repair.cfg.keep.$$" ]; then
  mv -f "/tmp/repair.cfg.keep.$$" "$APP_DIR/config.json"
fi

say "3/6 写入配置端口 $PORT"
python3 - "$APP_DIR/config.json" "$PORT" <<'PY'
import json, sys
path, port = sys.argv[1], int(sys.argv[2])
try:
    cfg = json.load(open(path, encoding='utf-8'))
except Exception:
    cfg = {}
cfg['port'] = port
json.dump(cfg, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print('port =', cfg['port'])
PY

say "4/6 注册 systemd 服务"
cat > /etc/systemd/system/repair.service <<UNIT
[Unit]
Description=Repair Workbench (self-hosted)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/python3 $APP_DIR/server.py
Restart=always
RestartSec=3
StandardOutput=append:$APP_DIR/logs/server.log
StandardError=append:$APP_DIR/logs/server.err.log

NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable repair >/dev/null 2>&1 || true
systemctl restart repair

say "5/6 健康检查"
ok=0
for i in $(seq 1 20); do
  if curl -fsS -m 3 "http://127.0.0.1:$PORT/api/health" >/tmp/repair_health.json 2>/dev/null; then ok=1; break; fi
  sleep 1
done
if [ "$ok" != "1" ]; then
  echo "--- 最近日志 ---"; tail -n 40 "$APP_DIR/logs/server.err.log" 2>/dev/null || true
  tail -n 20 "$APP_DIR/logs/server.log" 2>/dev/null || true
  die "服务未起来，见上方日志"
fi
echo "健康检查：$(cat /tmp/repair_health.json)"

say "6/6 放行防火墙 $PORT"
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow "$PORT"/tcp >/dev/null 2>&1 || true; echo "ufw 已放行 $PORT/tcp"
elif command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
  firewall-cmd --permanent --add-port="$PORT"/tcp >/dev/null 2>&1 || true
  firewall-cmd --reload >/dev/null 2>&1 || true; echo "firewalld 已放行 $PORT/tcp"
else
  echo "未检测到本机防火墙规则，跳过"
fi

IP=$(curl -fsS -m 3 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')
printf '\n\033[1;32m部署完成\033[0m\n'
printf '  本机访问：http://127.0.0.1:%s/\n' "$PORT"
printf '  公网访问：http://%s:%s/   （还需在云控制台「防火墙」放行 %s 端口）\n' "$IP" "$PORT" "$PORT"
printf '  服务管理：systemctl status repair / restart repair\n'
printf '  日志目录：%s/logs/\n' "$APP_DIR"
printf '  数据文件：%s/data/repair.db  （备份就拷这一个文件）\n' "$APP_DIR"
