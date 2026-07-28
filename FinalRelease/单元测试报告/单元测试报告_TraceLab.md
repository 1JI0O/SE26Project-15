# TraceLab 单元测试报告

## 1. 验收结论

本轮采用两个边界明确的后端子系统作为课程覆盖率验收范围，均使用 pytest（xUnit 风格）并设置严格 `fail_under = 90.01`：

| 被测子系统 | 测试结果 | 语句覆盖率 | 结论 |
|---|---:|---:|---|
| 本地后端仓库静态分析 `backend/app/services/code_analysis` | 52 passed | 389/389 = 100.00% | 通过 |
| VS Code 无头核心 `workspace/review/probe` | 46 passed | 275/275 = 100.00% | 通过 |

两个子系统合计 **664/664 条语句，100.00%**。完整 backend 回归为 **231 passed**；VS Code 扩展纯函数测试为 **3 passed**，TypeScript 编译通过。覆盖率只代表表中明确范围，不代表整个 backend 或整个 `tracelab_core`。

## 2. 测试快照

| 项目 | 值 |
|---|---|
| 执行日期 | 2026-07-28 |
| Git 基线 | c21588a（当前 HEAD） |
| 工作树 | 含本轮新增测试、缺陷修复、CI 与报告更新，尚未冻结 |
| 操作系统 | Microsoft Windows 10.0.26200，x64 |
| Python / pytest | 3.14.5 / 9.1.1 |
| Coverage.py / pytest-cov | 7.15.2 / 7.1.0 |
| Node | 22.16.0 |
| 测试框架 | pytest xUnit + JUnit XML；Node `node:test` |

仓库仍在实现功能。本报告是当前执行快照；最终 RC 冻结后必须在同一提交上重新生成全部报告。

## 3. 覆盖率口径

### 3.1 仓库静态分析子系统

| 文件 | 语句 | 未覆盖 | 覆盖率 |
|---|---:|---:|---:|
| __init__.py | 4 | 0 | 100.00% |
| analyzer.py | 53 | 0 | 100.00% |
| archive.py | 68 | 0 | 100.00% |
| constants.py | 8 | 0 | 100.00% |
| editor.py | 73 | 0 | 100.00% |
| ignore_rules.py | 48 | 0 | 100.00% |
| languages.py | 21 | 0 | 100.00% |
| python_ast.py | 87 | 0 | 100.00% |
| tree.py | 27 | 0 | 100.00% |
| **合计** | **389** | **0** | **100.00%** |

`definition_resolve.py` 属于代码导航解析，`lsp_bridge.py` 属于桌面 LSP 兼容能力，不进入该子系统分母；相关测试仍参与 backend 回归。

### 3.2 VS Code 无头核心子系统

| 文件 | 语句 | 未覆盖 | 覆盖率 |
|---|---:|---:|---:|
| workspace.py | 91 | 0 | 100.00% |
| review.py | 93 | 0 | 100.00% |
| probe.py | 91 | 0 | 100.00% |
| **合计** | **275** | **0** | **100.00%** |

该范围覆盖工作区布局与 JSON/PDF 元数据、追溯候选转换和评审状态、LLM/MinerU 配置探测及网络异常。尚未纳入 `agent_trace.py`、`analyze.py`、`paper_export.py`、`parse.py`、`cli.py` 等模块，因此不得将 100% 表述为整个 `tracelab_core` 的覆盖率。

## 4. 执行结果

| 检查 | 结果 | 结论 |
|---|---:|---|
| 静态分析定向测试 | 52 passed | 通过 |
| 静态分析语句覆盖率 | 389/389，100.00% | 通过 |
| VS Code core 定向测试 | 46 passed | 通过 |
| VS Code core 语句覆盖率 | 275/275，100.00% | 通过 |
| 完整 backend 回归 | 231 passed | 通过 |
| VS Code 扩展工具函数 | 3 passed | 通过 |
| VS Code 扩展 TypeScript 编译 | 通过 | 通过 |
| backend / core Ruff | 0 项问题 | 通过 |
| 前端 typecheck / build | 通过 / 1885 modules transformed | 通过 |

## 5. 本轮发现并修复的缺陷

- `BUG-20260728-003`：冲突分析把 Windows CRLF 与 ZIP 内 LF 的差异误判为代码修改，产生 `changed_lines = 0` 的伪冲突，并破坏“无代码变化”前置检查。现统一换行符后再比较、哈希和生成 diff；8 条冲突分析测试及完整 backend 回归通过。
- `BUG-20260728-004`：VS Code 扩展 `jsonForScript` 缺少参数分隔符，TypeScript 无法编译。现拆出纯函数并增加 HTML、脚本闭合标签、U+2028/U+2029 回归测试。
- `BUG-20260728-005`：`pkg/model.py::Model` 被追溯评审解析为完整 symbol ref 文件路径。现正确解析为 `pkg/model.py`，相关测试覆盖。

## 6. 复现命令

~~~powershell
Set-Location backend
uv run pytest -q --disable-warnings tests/test_code_analyzer.py tests/repositories/test_analysis.py tests/repositories/test_file_access.py "../FinalRelease/单元测试代码" --cov=app.services.code_analysis --cov-report=term-missing --cov-report="html:../FinalRelease/单元测试报告/htmlcov" --cov-report="xml:../FinalRelease/单元测试报告/coverage.xml" --junitxml="../FinalRelease/单元测试报告/junit.xml" --cov-fail-under=100

Set-Location ../packages/tracelab_core
uv run --extra dev pytest -q --junitxml="../../FinalRelease/单元测试报告/tracelab-core-junit.xml" --cov-report=xml:"../../FinalRelease/单元测试报告/tracelab-core-coverage.xml" --cov-report=html:"../../FinalRelease/单元测试报告/tracelab-core-htmlcov"

Set-Location ../../vscode-extension
npm test
~~~

## 7. 报告与证据

- `junit.xml`、`coverage.xml`、`htmlcov/index.html`：静态分析子系统。
- `tracelab-core-junit.xml`、`tracelab-core-coverage.xml`、`tracelab-core-htmlcov/index.html`：VS Code core 子系统。
- `backend-regression-junit.xml`：完整 backend 回归。
- `pytest-terminal.txt`、`tracelab-core-terminal.txt`、`backend-regression-terminal.txt`、`vscode-extension-terminal.txt`：终端摘要。

CI 已增加两套 Python 覆盖率门禁、完整 backend 回归、VS Code 扩展编译和单元测试，并归档机器可读报告。
