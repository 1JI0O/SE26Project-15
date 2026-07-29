# TraceLab 单元测试代码说明

本目录保存本轮为后端仓库静态分析子系统新增的 xUnit 风格 pytest 测试代码：

- test_code_analysis_boundaries.py：归档路径与容量限制、忽略规则、UTF-8/二进制/超大文件、编辑覆盖层、语言分类、Python AST 和文件树边界。
- test_code_analysis_extended.py：补充静态分析、定义解析和 LSP 桥接的异常、歧义、进程及异步 I/O 路径。
- vscode-extension/webview_utils.test.cjs：VS Code Webview HTML 与内联 JSON 安全转义测试。
- rag/：RAG 分块、Embedding、索引服务和 API 边界测试的交付归档副本；正式执行源位于 backend/tests/rag。

新增 `tracelab_core` 测试与源码共同维护，避免 FinalRelease 副本失同步；本目录作为交付索引，正式代码位置为：

- `packages/tracelab_core/tests/test_workspace.py`
- `packages/tracelab_core/tests/test_review.py`
- `packages/tracelab_core/tests/test_probe.py`

正式覆盖率还复用仓库原有测试：

- backend/tests/test_code_analyzer.py
- backend/tests/repositories/test_analysis.py
- backend/tests/repositories/test_file_access.py
- backend/tests/rag/test_rag_agent_tools.py
- backend/tests/rag/test_rag_index.py
- backend/tests/rag/test_rag_chunking_boundaries.py
- backend/tests/rag/test_rag_chunking_embeddings.py
- backend/tests/rag/test_rag_embedding_boundaries.py
- backend/tests/rag/test_rag_service_boundaries.py

backend/pyproject.toml 已把本目录加入 pytest 的 testpaths。从 backend 目录执行：

~~~powershell
uv sync --frozen --extra dev
uv run pytest -q
~~~

覆盖率报告的完整复现命令见 ../单元测试报告/单元测试报告_TraceLab.md。
