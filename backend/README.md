# TraceLab Backend

FastAPI 后端提供项目、MinerU 异步论文解析、ZIP/GitHub 代码分析、安全文件编辑、张量流、追溯审阅和 Agent 确认接口。

Agent 与 MinerU 的运行时配置优先由前端右上角“集成设置”管理，并持久化到本机 SQLite；环境变量仅提供尚未保存应用设置时的默认值。

```bash
cp ../.env.example .env
uv sync --extra dev
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

验证：

```bash
uv run ruff check .
uv run python -m pytest -q
```

OpenAPI：`http://127.0.0.1:8000/docs`。完整配置和前后端启动流程见仓库根目录 [README](../README.md)，接口总览见 [docs/api-contract.md](../docs/api-contract.md)。

桌面构建会通过 `app.desktop` 将后端打包为 PyInstaller sidecar，并把数据库、上传文件和任务状态写入 Tauri 应用数据目录。日常后端开发仍使用上面的 Uvicorn 命令。
