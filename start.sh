#!/usr/bin/env bash
# ============ 一键启动脚本 ============
# 用法：
#   ./start.sh                 # 前端已构建过就直接起服务（http://127.0.0.1:8000）
#   ./start.sh --build         # 强制重新构建前端再起服务
#   ./start.sh --port 8001     # 其他参数原样传给 sai serve（如换端口）
#
# 它只做两件事：
#   1) 发现 frontend/dist 不存在（或你点名 --build）就先构建前端；
#   2) 启动 FastAPI 单端口服务（界面 + API 同端口）。
# 定时推送等后台任务与它无关，仍用 cron + sai watch（见 README）。

set -euo pipefail
cd "$(dirname "$0")"

BUILD=0
if [ "${1:-}" = "--build" ]; then
  BUILD=1
  shift
fi

if [ "$BUILD" = 1 ] || [ ! -f frontend/dist/index.html ]; then
  echo "==> 构建前端…"
  if ! command -v npm >/dev/null; then
    echo "未检测到 npm（Node.js）。请先安装：https://nodejs.org （或跳过构建，用纯 API 模式：uv run sai serve）"
    exit 1
  fi
  ( cd frontend
    if [ ! -d node_modules ]; then
      echo "==> 首次安装前端依赖…"
      npm install
    fi
    npm run build
  )
  echo "==> 前端构建完成。"
fi

echo "==> 启动服务：http://127.0.0.1:8000（Ctrl+C 停止；换端口：./start.sh --port 8001）"
exec uv run sai serve "$@"
