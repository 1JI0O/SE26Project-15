# TraceLab 核心源码（FinalRelease 交付副本）

本目录为验收交付用的源码快照，**不含** `node_modules`、`.venv`、`dist`、`target`、sidecar 运行时、`.vsix` 等构建产物。

## 目录说明

| 路径 | 内容 |
|---|---|
| `backend/` | 本地 FastAPI（论文/代码/追溯/Agent/RAG），Desktop sidecar 入口 |
| `frontend/` | Vue 3 工作台 + Tauri 2 桌面壳（`src-tauri/`） |
| `server/` | 独立账号 / Workspace / 同步 / Blob / 管理台 |
| `vscode-extension/` | VS Code 扩展（TypeScript 源码；`bundled/` 需构建时生成） |
| `packages/tracelab_core/` | 扩展用无头分析核心 |
| `scripts/bundle_vscode_runtime.sh` | 生成扩展 `bundled/` 运行时 |

## 构建提示（需在仓库根或本目录按依赖安装后执行）

- Web：`backend` 起 uvicorn；`frontend` 执行 `pnpm install && pnpm dev`
- Desktop：`cd frontend && pnpm desktop:build`（会打包 Python sidecar）
- VS Code：`bash scripts/bundle_vscode_runtime.sh` 后 `cd vscode-extension && npm install && npx @vscode/vsce package --allow-missing-repository`
- Server：`cd server && uv sync --extra dev`，见 `server/README.md`

密钥与本地数据请自行配置，勿提交 `.env`。
