# TraceLab VS Code Extension

Self-contained paper–code workbench. The VSIX bundles a Python runtime under
`bundled/`. Artifacts live in **`.tracelab/`** and reload when you reopen the folder.

## Persistence (`.tracelab/`)

| Path | Content |
|------|---------|
| `papers/source.pdf` | Imported original PDF |
| `papers/parsed/normalized.json` | Parsed paper (MinerU / fallback) |
| `papers/parsed/document.md` | Anchored Markdown for the reader |
| `papers/parsed/assets/` | Images referenced by Markdown |
| `papers/parsed/paper_document.json` | Title, sections, blocks, markdown source |
| `analysis/symbols.json` | Code symbols |
| `analysis/tensor_graph.json` | Raw semantic tensor graph |
| `analysis/architecture.json` | Hierarchical roots / expandable layers |
| `traces/links.json` | Trace relationships (Agent progressive publish + review) |
| `traces/jobs/` | Job logs (parse / agent-trace events) |

## Prerequisites

- VS Code 1.85+
- [uv](https://astral.sh/uv) on `PATH`
- **LLM API Key** required for「生成追溯」(Agent multi-step; static keyword path removed)
- Optional MinerU credentials for high-quality paper Markdown

## Cross-workspace settings

- **API keys / tokens**: VS Code `SecretStorage` (machine-wide). Saving settings with an empty key field **keeps** the existing secret; use explicit「清除」to delete.
- Non-secret LLM/MinerU settings: **Global** user configuration

## Install

```bash
make extension-build
cd vscode-extension && npx @vscode/vsce package --allow-missing-repository
code --install-extension tracelab-vscode-0.5.0.vsix --force
```

Reload Window.

## Sidebar（中文工作台）

- 工作流：初始化 / 导入论文 / 解析论文 / 分析代码 / 生成追溯 / 论文 / 追溯矩阵 / 张量流图
- **分析日志**：Agent 逐步活动（阅读代码、发布候选等）
- LLM / MinerU 表单与连通性测试

## Panels

- **论文**（编辑器区）：工具栏切换 Markdown / PDF 原件；大纲下拉；公式与块级追溯高亮（对齐桌面）；点击跳代码。PDF 仅在切到「PDF 原件」时懒加载，IntersectionObserver 按可见页渲染
- **底栏 TraceLab**：与桌面一致，**追溯矩阵**与**张量流图**并列两个 tab（`tracelab-panel`）；侧栏打开时聚焦对应底栏视图
- **追溯矩阵**：固定顶栏筛选/批量审阅；列表独立滚动；论文证据从 `document.md` 截取并用 KaTeX 渲染。重新「生成追溯」时若已有结果，会询问 **清空后重跑 / 保留并追加 / 取消**
- **张量流图**：分层 Architecture/Debug；**单击跳转代码**；双击可展开模块下钻；缩放平移
- **论文 PDF**：放大 / 缩小 / 适应宽度；高亮半透明（multiply），不挡原文

## Acceptance

- [ ] Save LLM URL without retyping key → restart / switch folder → key still configured
- [ ] Paper: MD/PDF toggle; formulas/images; PDF CJK; highlight → code; `document.md` under `.tracelab/papers/parsed/`
- [ ] Tensor: click opens code; dblclick expands
- [ ] Trace without key fails clearly; with key runs multi-step with Chinese log lines; links grow progressively
- [ ] UI labels match desktop Chinese copy

## Maintainers

```bash
make extension-bundle
MINERU_TOKEN=… DEEPSEEK_KEY=… ./scripts/e2e_vscode_bundled.sh
```
