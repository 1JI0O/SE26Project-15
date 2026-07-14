#!/usr/bin/env bash
# 启动桌面客户端模式演示
# 使用方式: bash docs/demo/launch-desktop.sh

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "=== TraceLab 桌面客户端模式启动 ==="
echo ""

# 加载 Rust 环境
if [ -f "$HOME/.cargo/env" ]; then
  source "$HOME/.cargo/env"
fi

# 检查 Rust 是否安装
if ! command -v cargo &> /dev/null; then
  echo "错误: 未安装 Rust。请先运行以下命令安装:"
  echo "  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
  exit 1
fi

# 启动后端
echo "[1/2] 启动后端服务..."
cd "$PROJECT_ROOT/backend"
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
echo "  后端 PID: $BACKEND_PID"

# 等待后端启动
sleep 2

# 启动 Tauri 桌面客户端
echo ""
echo "[2/2] 启动 Tauri 桌面客户端..."
cd "$PROJECT_ROOT/frontend"
pnpm tauri dev &
TAURI_PID=$!
echo "  Tauri PID: $TAURI_PID"

echo ""
echo "=== 启动完成 ==="
echo "桌面窗口将自动打开，首次编译 Rust 需要几分钟"
echo "按 Ctrl+C 停止所有服务"

# 等待用户中断
trap "kill $BACKEND_PID $TAURI_PID 2>/dev/null; exit 0" INT TERM
wait
