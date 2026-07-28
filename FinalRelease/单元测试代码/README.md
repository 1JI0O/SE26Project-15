# TraceLab 单元测试代码说明

本目录保存本轮为后端仓库静态分析子系统新增的 xUnit 风格 pytest 测试代码：

- test_code_analysis_boundaries.py：归档路径与容量限制、忽略规则、UTF-8/二进制/超大文件、编辑覆盖层、语言分类、Python AST 和文件树边界。
- test_code_analysis_extended.py：补充静态分析、定义解析和 LSP 桥接的异常、歧义、进程及异步 I/O 路径。

正式覆盖率还复用仓库原有测试：

- backend/tests/test_code_analyzer.py
- backend/tests/repositories/test_analysis.py
- backend/tests/repositories/test_file_access.py

backend/pyproject.toml 已把本目录加入 pytest 的 testpaths。从 backend 目录执行：

~~~powershell
uv sync --frozen --extra dev
uv run pytest -q
~~~

覆盖率报告的完整复现命令见 ../单元测试报告/单元测试报告_TraceLab.md。
