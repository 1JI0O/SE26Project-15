#!/usr/bin/env bash
# 启动浏览器模式演示
# 使用方式: bash docs/demo/launch-browser.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "=== TraceLab 浏览器模式启动 ==="
echo ""

# 启动后端
echo "[1/2] 启动后端服务..."
cd "$PROJECT_ROOT/backend"
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
echo "  后端 PID: $BACKEND_PID"
echo "  后端地址: http://127.0.0.1:8000"
echo "  API 文档: http://127.0.0.1:8000/docs"

# 等待后端启动
sleep 2

# 启动前端
echo ""
echo "[2/2] 启动前端服务..."
cd "$PROJECT_ROOT/frontend"
pnpm dev &
FRONTEND_PID=$!
echo "  前端 PID: $FRONTEND_PID"
echo "  前端地址: http://localhost:5173"

echo ""
echo "=== 启动完成 ==="
echo "浏览器打开 http://localhost:5173 即可使用"
echo "按 Ctrl+C 停止所有服务"

# 等待用户中断
trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" INT TERM
wait
