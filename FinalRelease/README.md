# TraceLab 最终交付物索引

**代码基线：** `main`（合并提交 `0b7c604`）
**整理日期：** 2026-07-31

本目录汇总项目全部成果。下表按验收要求逐条对应交付路径与当前状态。

## 交付物对照表

| # | 验收要求 | 交付路径 | 状态 |
|---|---|---|---|
| 1 | Vision 文档 | `Vision文档.md` | 已交付（v2.0，按当前实现重写） |
| 2 | 软件架构文档 | `软件架构文档.md` | 已交付（v3.0，按源码核对） |
| 3 | UML 模型（用例/分析/设计） | `UML.md` | 已交付（含用例、分析、设计三层模型） |
| 4 | 软件代码（源代码 + 可执行代码） | `source_code/`、`tracelab-vscode-0.5.0.vsix` | 已交付；桌面安装包因体积超限未提交，见下文 |
| 5 | 单元测试代码与测试报告（语句覆盖率 > 90%） | `单元测试代码/`、`单元测试报告/` | 已交付，四套后端/核心包覆盖率均 100% |
| 6 | 系统测试用例（功能/易用性/兼容性） | `系统测试用例_TraceLab.xlsx` | 74 条用例已交付并全部执行通过 |
| 7 | 项目总结报告 | `项目总结报告.docx` | 已交付 |
| 8 | 验收答辩 PPT | `TraceLab答辩ppt.pptx` | 已交付 |

## 4. 软件代码

- **源代码：** `source_code/`（backend / frontend / server / vscode-extension / packages / scripts，不含 `node_modules`、`.venv`、`dist`、`target` 等构建产物），运行与打包说明见 `source_code/README.md`。
- **可执行代码：** `tracelab-vscode-0.5.0.vsix`（VS Code 扩展安装包，3.05 MB，`code --install-extension` 直接安装）。

打包在同一提交上验证通过：`pnpm build`（vue-tsc + vite build）、`tsc -p .`（扩展编译）、`vsce package`、`pnpm tauri build --bundles msi,nsis`。

桌面安装包已构建验证成功，但体积超过 GitHub 单文件 100 MiB 硬限制（NSIS 109.4 MiB、MSI 153.9 MiB，主要来自 sidecar 内置 Python 运行时与 67 MB 的 basedpyright 语言服务），故未提交二进制。可按 `source_code/README.md` 自行构建，或手动触发 `.github/workflows/desktop-release.yml` 由 CI 产出 Windows 与 macOS 安装包 artifact。

## 5. 单元测试

语句覆盖率要求 > 90%，实测四套定向套件全部 100%：

| 套件 | 语句数 | 未覆盖 | 覆盖率 | 用例 |
|---|---:|---:|---:|---:|
| 静态代码分析（`app/services/code_analysis`） | 389 | 0 | 100.00% | 52 passed |
| RAG（`app/services/rag`） | 438 | 0 | 100.00% | 74 passed |
| 追溯创作与置信度 | 188 | 0 | 100.00% | 20 passed |
| VS Code core（`tracelab_core`） | 275 | 0 | 100.00% | 46 passed |

另有后端全量回归 326 passed、云服务 42 passed / 1 skipped、前端引导式标注 10 passed、VS Code 扩展纯函数 3 passed。证据包含 junit XML、coverage XML、HTML 覆盖率报告与终端输出，见 `单元测试报告/`（汇总说明：`单元测试报告/单元测试报告_TraceLab.md`）。

## 6. 系统测试

用例共 74 条：功能 59（覆盖基本流与备选流）、易用性 7、兼容性 7、可选可靠性 1。

**执行状态：74 条全部通过，0 失败，无未关闭缺陷。** 其中浏览器兼容性子流程由 Playwright 矩阵自动化验证（Chrome / Edge / Firefox × 1366×768 / 1920×1080，6 passed），其余由项目组人工执行。性能测试按要求为 optional，另有独立压力测试报告见仓库 `docs/stress-test-report.md`。

相关文件：

- `系统测试用例_TraceLab.xlsx` — 提交模板格式，74 条用例与执行结果
- `系统测试代码/browser_compatibility.spec.ts` — 浏览器兼容性自动化脚本
- `系统测试证据/` — 兼容性截图、Playwright 报告、构建与环境输出

## 说明

本目录为提交快照，只保留验收要求的 8 项交付物。以下过程文档保留在仓库 `docs/` 作为日常维护源，未纳入本目录：

- `docs/系统测试用例_TraceLab.md`、`docs/系统测试报告_TraceLab.md` — 用例维护源与执行报告（本目录以 xlsx 作为提交件）
- `docs/缺陷清单_TraceLab.md` — 缺陷记录与修复情况
- `docs/测试与缺陷修复计划_TraceLab.md` — 覆盖率门禁与用例策略
- `docs/答辩问题整理_TraceLab.md` — 答辩预备问题
- `docs/文档符合性检查.md` — 文档与实现一致性核对记录
