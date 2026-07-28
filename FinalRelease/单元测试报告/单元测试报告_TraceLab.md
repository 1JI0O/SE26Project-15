# TraceLab 单元测试报告

## 1. 验收结论

本轮选择后端“仓库静态分析子系统”作为课程要求的正式覆盖率范围。使用 pytest（xUnit 风格）执行 52 条定向测试，全部通过；语句覆盖率为 **100.00%（389/389）**，严格超过 90% 的要求，也达到内部 100% 目标。

完整 backend 回归另行执行，结果为 **223 passed，0 failed**。覆盖率数字仅代表下述明确子系统，不代表整个后端。

## 2. 测试快照与环境

| 项目 | 值 |
|---|---|
| 执行日期 | 2026-07-28 |
| Git 基线 | cfc1bc222773d08fc53b4b6ed12c5c825e69e68a |
| 工作树 | 含本轮测试、CI、前端缺陷修复和报告改动，尚未形成冻结 RC |
| 操作系统 | Microsoft Windows 10.0.26200，x64（Windows 11 内核版本） |
| Python | 3.14.5 |
| pytest | 9.1.1 |
| Coverage.py / pytest-cov | 7.15.2 / 7.1.0 |
| 框架类型 | pytest，xUnit 风格；JUnit XML 输出 |

仓库仍在实现新功能，因此本报告是当前执行快照。RC 冻结后必须在冻结提交上重跑并更新 Git 提交号。

## 3. 覆盖率统计口径

纳入分母的生产文件：

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

definition_resolve.py 属于代码导航解析，lsp_bridge.py 属于桌面 LSP 兼容能力，不进入“仓库静态分析子系统”的正式分母；其新增测试仍随完整回归执行。排除规则按职责固定在 backend/pyproject.toml，不按覆盖结果动态排除。

覆盖率硬门禁配置为 fail_under = 90.01，确保 90.00% 不会误判达标；本次正式命令额外使用 --cov-fail-under=100 验证内部目标。

## 4. 测试内容

- ZIP 根目录识别、重复路径、路径穿越、绝对路径、符号链接、条目数和解压大小限制。
- 默认忽略规则、.gitignore、.git/info/exclude、超大忽略文件和 macOS 元数据。
- 可编辑文件判定、无效 UTF-8、二进制、源码/编辑内容超限、编辑覆盖层和符号链接逃逸。
- Python AST 的类、函数、异步函数、调用、PyTorch 候选和语法错误降级。
- 语言分类、层级文件树、快速扫描、分析汇总，以及编辑覆盖层失败后的归档源回退。
- 定义解析歧义与 LSP 消息/进程边界（参与回归，不进入正式覆盖率分母）。

新增测试代码位于 FinalRelease/单元测试代码；已有测试作为复用资产保留在 backend/tests。

## 5. 执行结果

| 检查 | 通过 | 失败 | 跳过 | 耗时 | 结论 |
|---|---:|---:|---:|---:|---|
| 静态分析子系统定向测试 | 52 | 0 | 0 | 0.67 秒 | 通过 |
| 语句覆盖率 | 389 | 0 | - | - | 100.00%，通过 |
| 完整后端回归 | 223 | 0 | 0 | 17.81 秒 | 通过 |
| Ruff（应用、既有测试、新增测试） | - | 0 项问题 | - | - | 通过 |

正式覆盖率命令：

~~~powershell
Set-Location backend
$env:COVERAGE_FILE = '../FinalRelease/单元测试报告/.coverage'
uv run pytest -q --disable-warnings tests/test_code_analyzer.py tests/repositories/test_analysis.py tests/repositories/test_file_access.py "../FinalRelease/单元测试代码" --cov=app.services.code_analysis --cov-report=term-missing --cov-report="html:../FinalRelease/单元测试报告/htmlcov" --cov-report="xml:../FinalRelease/单元测试报告/coverage.xml" --junitxml="../FinalRelease/单元测试报告/junit.xml" --cov-fail-under=100
~~~

完整回归命令：

~~~powershell
Set-Location backend
uv run pytest -q --disable-warnings --junitxml="../FinalRelease/单元测试报告/backend-regression-junit.xml"
~~~

## 6. 报告与证据

- pytest-terminal.txt：定向测试和逐文件覆盖率终端结果。
- junit.xml：52 条定向测试的 JUnit XML。
- coverage.xml：机器可读覆盖率报告。
- htmlcov/index.html：可浏览的逐行 HTML 覆盖率报告。
- backend-regression-terminal.txt：完整后端回归日志。
- backend-regression-junit.xml：完整后端回归 JUnit XML。

CI 已新增相同的全量回归和覆盖率门禁，并归档 JUnit、XML 与 HTML 报告。当前本机 Python 为 3.14.5，CI 固定 Python 3.12；冻结 RC 应以 CI 结果再次确认跨版本稳定性。
