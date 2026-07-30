# TraceLab 单元测试报告

## 1. 验收结论

本轮对四个边界明确的后端/无头子系统使用 pytest（xUnit 风格）执行独立语句覆盖率门禁。课程要求为“超过 90%”，CI 门禁保持 `fail_under = 90.01`，本次归档命令使用更严格的 100% 门禁：

| 被测子系统 | 测试结果 | 语句覆盖率 | 结论 |
|---|---:|---:|---|
| 本地后端仓库静态分析 `backend/app/services/code_analysis` | 52 passed | 389/389 = 100.00% | 通过 |
| 本地后端语义检索 `backend/app/services/rag` | 74 passed | 438/438 = 100.00% | 通过 |
| VS Code 无头核心 `workspace/review/probe` | 46 passed | 275/275 = 100.00% | 通过 |
| 追溯创作与置信度 `manual_anchors/confidence/projects/migration` | 20 passed | 188/188 = 100.00% | 通过 |

四个正式范围合计 **1290/1290 条语句，100.00%**。完整 backend 回归为 **362 passed**；VS Code 扩展 TypeScript 编译通过，Node 纯函数测试 **3 passed**。这些数字只代表表中明确范围，不代表整个 backend 或整个 `tracelab_core` 达到 100%。

## 2. 测试快照

| 项目 | 值 |
|---|---|
| 执行日期 | 2026-07-30 |
| Git 基线 | `b8e6b11`（当前 HEAD） |
| 工作树 | 含本轮新增功能补测、缺陷修复、CI 与报告更新，尚未冻结 |
| 操作系统 | Microsoft Windows 10.0.26200，x64 |
| Python / pytest | 3.14.5 / 9.1.1 |
| pytest-cov | 7.1.0 |
| Node / pnpm | 22.16.0 / 11.13.0 |
| 测试框架 | pytest xUnit + JUnit XML；Node `node:test` |

仓库仍在开发。本报告是当前执行快照；最终 RC 冻结后必须在同一提交上重新生成全部报告。

## 3. 覆盖率口径

### 3.1 仓库静态分析子系统

| 文件 | 语句 | 未覆盖 | 覆盖率 |
|---|---:|---:|---:|
| `__init__.py` | 4 | 0 | 100.00% |
| `analyzer.py` | 53 | 0 | 100.00% |
| `archive.py` | 68 | 0 | 100.00% |
| `constants.py` | 8 | 0 | 100.00% |
| `editor.py` | 73 | 0 | 100.00% |
| `ignore_rules.py` | 48 | 0 | 100.00% |
| `languages.py` | 21 | 0 | 100.00% |
| `python_ast.py` | 87 | 0 | 100.00% |
| `tree.py` | 27 | 0 | 100.00% |
| **合计** | **389** | **0** | **100.00%** |

`definition_resolve.py` 属于代码导航解析，`lsp_bridge.py` 属于桌面 LSP 兼容能力，不进入该子系统分母；相关测试仍参与 backend 回归。

### 3.2 语义检索子系统

| 文件 | 语句 | 未覆盖 | 覆盖率 |
|---|---:|---:|---:|
| `__init__.py` | 2 | 0 | 100.00% |
| `chunking.py` | 91 | 0 | 100.00% |
| `embeddings.py` | 120 | 0 | 100.00% |
| `service.py` | 225 | 0 | 100.00% |
| **合计** | **438** | **0** | **100.00%** |

该范围覆盖论文/代码/已复核追溯分块，本地与 OpenAI-compatible 远程 Embedding，向量编解码与排名，索引构建/复用/失效/失败恢复，以及状态、重建和搜索边界。路由、数据库实体、迁移、Agent 调用和前端设置不进入这 438 条语句的分母，但相应测试参与完整回归或系统用例。

### 3.3 VS Code 无头核心子系统

| 文件 | 语句 | 未覆盖 | 覆盖率 |
|---|---:|---:|---:|
| `workspace.py` | 91 | 0 | 100.00% |
| `review.py` | 93 | 0 | 100.00% |
| `probe.py` | 91 | 0 | 100.00% |
| **合计** | **275** | **0** | **100.00%** |

该范围不包含 `agent_trace.py`、`analyze.py`、`paper_export.py`、`parse.py`、`cli.py` 等模块，不得将结果表述为整个 `tracelab_core` 的覆盖率。

### 3.4 追溯创作与置信度子系统

| 文件 | 语句 | 未覆盖 | 覆盖率 |
|---|---:|---:|---:|
| `app/services/tracing/manual_anchors.py` | 69 | 0 | 100.00% |
| `app/services/agent/confidence.py` | 30 | 0 | 100.00% |
| `app/api/routes/projects.py` | 57 | 0 | 100.00% |
| `app/schemas/projects.py` | 15 | 0 | 100.00% |
| `app/db/migrations/versions/0014_project_deep_thinking.py` | 17 | 0 | 100.00% |
| **合计** | **188** | **0** | **100.00%** |

该范围覆盖手工引用到真实证据锚点、项目开关 API/schema/迁移、直接评分与六维公式、显式默认维度、penalty 去重、旧 schema 降级和上下界。Agent 大循环、同步服务和前端交互不进入这 188 条语句分母，但相应集成测试参与完整回归、Server 回归或系统用例。

## 4. 执行结果

| 检查 | 结果 | 结论 |
|---|---:|---|
| 静态分析定向测试 / 覆盖率 | 52 passed；389/389 | 通过 |
| RAG 定向测试 / 覆盖率 | 74 passed；438/438 | 通过 |
| VS Code core 定向测试 / 覆盖率 | 46 passed；275/275 | 通过 |
| 追溯创作与置信度定向测试 / 覆盖率 | 20 passed；188/188 | 通过 |
| 完整 backend 回归 | 362 passed | 通过 |
| VS Code 扩展编译 / 工具函数 | 通过；3 passed | 通过 |
| backend / core Ruff | 0 项问题 | 通过 |
| 前端 typecheck / build | 通过；1889 modules transformed | 通过 |
| 云服务回归 | 42 passed，1 skipped | 通过（真实 PostgreSQL 项按环境跳过） |

完整 backend 首轮曾出现论文任务状态文件读取与并发替换竞争，修复后相关定向测试 4 passed；当前完整回归 362 passed。

## 5. 本轮补测与缺陷修复

- RAG 从新增功能自带 27 条测试、72.94% 覆盖率起步，补充 47 条边界/异常测试后达到 74 passed、100.00%。新增覆盖包括长文本窗口、无效块/符号、CJK/CamelCase、本地零向量、远程批处理与排序、401/429/5xx/超时/断网/非法响应、强制重建、陈旧索引清理、失败恢复、去重和 API 校验。
- `BUG-20260729-001`：远程 Embedding 的非数组 `data` 和非数值向量未统一降级。现返回 `embedding_response_invalid`，相关回归通过。
- `BUG-20260729-002`：删除 accepted/rejected 追溯后 trace 先例索引未失效。现删除已复核关系后将索引标记为 pending。
- `BUG-20260729-003`：论文任务状态文件并发替换期间，无锁读取可能短暂返回 404。现读取和写入使用同一锁，避免轮询泄漏瞬态缺失。
- `TEST-20260729-001`：浏览器首个冷启动组合在全局 8 秒内仍显示加载中。用例改为对工作台数据加载使用 20 秒局部等待，完整 6 组浏览器复测通过。
- 新增追溯创作与置信度正式范围：补齐手工锚点的 flat paragraph、symbol、bare file、不可读/空内容边界，并覆盖项目开关 API、0014 迁移、公式和 penalty 边界，20 passed、188/188。
- `BUG-20260730-001/002`：显式默认维度误回退及重复 penalty 重复扣分。现依据 `model_fields_set` 判断是否提供维度，并对 penalty 去重。
- `BUG-20260730-003`：Agent 追溯写操作遗漏同步 outbox 与 RAG 失效。现 create/update/delete/status 与 REST 路由采用同一副作用，并补确认、隔离、schema 和版本测试。
- `BUG-20260730-004`：运行中切换六维设置会改变后续 publish/持久化口径。现任务启动时冻结评分模式并传递给父代理、子代理和持久化。
- `BUG-20260730-005`：项目六维设置未跨设备同步。现 Desktop/Server payload、bootstrap、冲突应用和 0002 Server 迁移均支持该字段。
- `BUG-20260730-006`：取消标注遗留选择且校验错误可能误报 API 失败。现关闭时清空选择并拆分校验与请求错误处理。

## 6. 复现命令

~~~powershell
Set-Location backend
uv run pytest -q tests/rag --cov=app.services.rag --cov-report=term-missing --cov-fail-under=100

uv run pytest -q tests/tracing/test_annotation_mode.py tests/agent/test_confidence_boundaries.py tests/projects/test_project_confidence_api.py tests/test_confidence_migration.py --cov=app.services.tracing.manual_anchors --cov=app.services.agent.confidence --cov=app.api.routes.projects --cov=app.schemas.projects --cov=app.db.migrations.versions.0014_project_deep_thinking --cov-report=term-missing --cov-fail-under=100

uv run pytest -q tests/test_code_analyzer.py tests/repositories/test_analysis.py tests/repositories/test_file_access.py "../FinalRelease/单元测试代码" --cov=app.services.code_analysis --cov-report=term-missing --cov-fail-under=100

uv run pytest -q

Set-Location ../packages/tracelab_core
uv run --extra dev pytest -q

Set-Location ../../vscode-extension
npm test
~~~

## 7. 报告与证据

- `coverage.xml`、`junit.xml`、`htmlcov/index.html`、`pytest-terminal.txt`：静态分析子系统。
- `rag-coverage.xml`、`rag-junit.xml`、`rag-htmlcov/index.html`、`rag-terminal.txt`：RAG 子系统。
- `tracelab-core-coverage.xml`、`tracelab-core-junit.xml`、`tracelab-core-htmlcov/index.html`、`tracelab-core-terminal.txt`：VS Code core 子系统。
- `trace-authoring-coverage.xml`、`trace-authoring-junit.xml`、`trace-authoring-htmlcov/index.html`、`trace-authoring-terminal.txt`：追溯创作与置信度子系统。
- `backend-regression-junit.xml`、`backend-regression-terminal.txt`：完整 backend 回归。
- `FinalRelease/单元测试代码/rag`：本轮 RAG 测试代码交付归档；正式执行源为 `backend/tests/rag`。
- `FinalRelease/单元测试代码/trace-authoring`：本轮标注、置信度、项目 API/迁移和 Agent CRUD 测试交付归档。

CI 已包含四套 Python 覆盖率门禁、完整 backend 回归、VS Code 扩展编译/单元测试、云服务和前端构建，并归档机器可读报告。
