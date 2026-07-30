# TraceLab 单元测试代码说明

本目录保存本轮为后端仓库静态分析子系统新增的 xUnit 风格 pytest 测试代码：

- test_code_analysis_boundaries.py：归档路径与容量限制、忽略规则、UTF-8/二进制/超大文件、编辑覆盖层、语言分类、Python AST 和文件树边界。
- test_code_analysis_extended.py：补充静态分析、定义解析和 LSP 桥接的异常、歧义、进程及异步 I/O 路径。
- vscode-extension/webview_utils.test.cjs：VS Code Webview HTML 与内联 JSON 安全转义测试。
- rag/：RAG 分块、Embedding、索引服务和 API 边界测试的交付归档副本；正式执行源位于 backend/tests/rag。
- trace-authoring/：手工标注锚点、六维置信度、项目设置 API/迁移和 Agent 追溯 CRUD/矩阵兼容性测试的交付归档副本。
- frontend/annotation.spec.ts、annotation-selection.spec.ts：引导式标注状态机、提交锁、失败重试、跨项目旧请求隔离、跨段论文选择和代码行末边界测试的交付归档；正式执行源位于 `frontend/src/stores/annotation.spec.ts` 与 `frontend/src/features/tracing/annotation-selection.spec.ts`。

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

`trace-authoring/` 中各文件的正式执行源为：

- `backend/tests/tracing/test_annotation_mode.py`
- `backend/tests/agent/test_confidence_boundaries.py`
- `backend/tests/projects/test_project_confidence_api.py`
- `backend/tests/test_confidence_migration.py`
- `backend/tests/agent/test_agent_confirmation.py`（归档副本为 `trace-authoring/test_agent_trace_crud.py`，当前同步 13 条 Agent 确认、追溯 CRUD、矩阵读取兼容和关系归一化测试）

backend/pyproject.toml 的默认 `testpaths` 只收集正式源 `backend/tests`，避免本目录归档副本与正式源同名时被重复导入。从 backend 目录执行完整回归：

~~~powershell
uv sync --frozen --extra dev
uv run pytest -q
~~~

覆盖率报告的完整复现命令见 ../单元测试报告/单元测试报告_TraceLab.md。
