#!/usr/bin/env bash
# 佩丽卡监督 —— Ubuntu 22.04 云服务器部署脚本（2核4G 足够）
#
# 用法：
#   ./deploy/deploy.sh docker    # Docker / docker-compose 部署（推荐）
#   ./deploy/deploy.sh bare      # 裸机部署（venv + systemd）
set -euo pipefail
cd "$(dirname "$0")/.."

MODE="${1:-docker}"

if [ "$MODE" = "docker" ]; then
  echo "== Docker 部署 =="
  # 语料与数据库不在镜像里：首次部署请把 corpus/ 与 data/pelica.db 一起同步到服务器
  docker compose build
  docker compose up -d
  docker compose ps
  echo "== 完成。查看日志：docker compose logs -f pelica =="

elif [ "$MODE" = "bare" ]; then
  echo "== 裸机部署 =="
  if [ ! -d .venv ]; then
    python3.11 -m venv .venv
  fi
  ./.venv/bin/pip install -U pip
  ./.venv/bin/pip install -r requirements.txt
  if [ ! -d bridges/wechaty/node_modules ]; then
    (cd bridges/wechaty && npm install --omit=dev --no-audit --no-fund) || \
      echo "[warn] wechaty 依赖安装失败；BRIDGE_MODE=mock 不受影响"
  fi
  # 首次运行需要先建库：
  #   ./.venv/bin/python scripts/build_db.py
  cat > /tmp/pelica.service <<'EOF'
[Unit]
Description=Pelica WeChat Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=%i
WorkingDirectory=/opt/pelica
ExecStart=/opt/pelica/.venv/bin/python main.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
  echo "== systemd 单元模板已生成：/tmp/pelica.service =="
  echo "   复制到 /etc/systemd/system/pelica.service 并按需修改 User/WorkingDirectory，"
  echo "   然后: systemctl daemon-reload && systemctl enable --now pelica"
else
  echo "用法: $0 docker|bare" >&2
  exit 1
fi
