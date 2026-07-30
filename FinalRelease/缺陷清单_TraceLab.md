# TraceLab 缺陷清单

## 汇总

| 状态 | P0 | P1 | P2 | P3 | 测试设施 |
|---|---:|---:|---:|---:|---:|
| 已关闭 | 0 | 7 | 6 | 1 | 2 |
| 未关闭 | 0 | 0 | 0 | 0 | 0 |

## BUG-20260728-001 空白项目名称不显示校验提示

- **等级 / 状态**：P2 / 已关闭
- **发现用例**：TC-F-002
- **影响**：创建按钮在名称为空或全空格时被禁用，用户无法触发提交处理中的“请输入项目名称”提示，与用例预期不一致。
- **根因**：按钮层 disabled 条件提前截断了表单校验逻辑。
- **修复**：移除提前禁用，统一由 submit() 校验并显示反馈；创建请求仍不会发送。
- **回归**：Chrome、Edge、Firefox × 1366x768、1920x1080 共 6 组通过。
- **证据**：系统测试证据/兼容性测试/playwright-junit.xml

## BUG-20260728-002 Web 页面缺少 favicon

- **等级 / 状态**：P3 / 已关闭
- **发现用例**：TC-C-001 自动化子流程
- **影响**：Chromium 请求 /favicon.ico 返回 404，污染控制台并削弱浏览器标签识别。
- **根因**：frontend/index.html 未声明 favicon。
- **修复**：复用 Tauri 现有 32x32.png 图标；Vite 生产构建已生成对应资源。
- **回归**：6 组浏览器矩阵通过，前端生产构建通过。
- **证据**：系统测试证据/兼容性测试/playwright-terminal.txt、构建与环境/frontend-build.txt

## TEST-20260728-001 全后端覆盖率插桩放大后台任务时序

- **等级 / 状态**：测试设施 / 已关闭
- **现象**：Python 3.14 下对完整后端套件插入 coverage 探针时，论文后台任务 5 秒轮询曾偶发拿到非状态响应；单测或无插桩全量运行稳定通过。
- **处理**：按验收口径只对仓库静态分析子系统执行覆盖率插桩，完整后端另行无插桩回归；CI 使用同样的两道门禁。
- **结果**：静态分析定向测试 52 条通过、覆盖率 100.00%；RAG 定向测试 74 条通过、覆盖率 100.00%；当前完整后端 362 条通过。
- **证据**：单元测试报告/pytest-terminal.txt、单元测试报告/backend-regression-terminal.txt

## BUG-20260728-003 冲突分析误判换行符差异

- **等级 / 状态**：P1 / 已关闭
- **发现用例**：新增冲突分析自动化回归；关联 TC-F-037。
- **影响**：Windows 编辑覆盖文件使用 CRLF、导入 ZIP 使用 LF 时，未改变内容的文件被计为冲突，生成 `changed_lines = 0` 的伪差异，并导致“无代码变化”校验失效。
- **根因**：变更收集在比较、哈希和 diff 前没有统一换行符。
- **修复**：将 CRLF 和 CR 规范为 LF 后再比较、计算哈希及生成证据。
- **回归**：冲突分析 8 条测试通过；完整 backend 231 条通过。
- **证据**：单元测试报告/backend-regression-junit.xml

## BUG-20260728-004 VS Code 扩展无法通过 TypeScript 编译

- **等级 / 状态**：P1 / 已关闭
- **发现用例**：新增扩展编译门禁；关联 TC-F-039。
- **影响**：Webview 内联 JSON 转义代码缺少函数参数分隔符，扩展无法编译和打包。
- **根因**：U+2028/U+2029 转义调用语法错误，且原 CI 未编译 VS Code 扩展。
- **修复**：拆出可独立测试的 Webview 转义工具，修正实现；CI 增加 `npm ci && npm test`。
- **回归**：TypeScript 编译通过；Node 测试 3 条通过。
- **证据**：单元测试报告/vscode-extension-terminal.txt

## BUG-20260728-005 VS Code 追溯评审错误解析符号路径

- **等级 / 状态**：P2 / 已关闭
- **发现用例**：`packages/tracelab_core/tests/test_review.py`；关联 TC-F-039。
- **影响**：`pkg/model.py::Model` 被当作完整文件路径，可能导致 VS Code 无法定位代码文件。
- **根因**：无显式行号时的 symbol fallback 未移除 `::symbol` 后缀。
- **修复**：fallback 先提取 `::` 前的相对路径。
- **回归**：VS Code core 46 条测试通过，选定三模块覆盖率 100%。
- **证据**：单元测试报告/tracelab-core-junit.xml

## BUG-20260729-001 远程 Embedding 非法响应未稳定降级

- **等级 / 状态**：P1 / 已关闭
- **发现用例**：`backend/tests/rag/test_rag_chunking_embeddings.py`；关联 TC-F-053。
- **影响**：远程接口返回非数组 `data` 时原因错误，向量含非数值元素时原生 `ValueError` 直接泄漏，可能中断依赖语义检索的 Agent 或搜索请求。
- **根因**：响应解析只检查了空向量和数量，没有校验 `data` 容器类型，也没有捕获 float 转换异常。
- **修复**：要求 `data` 为 list，并将容器、条目、空向量和非数值转换错误统一映射为 `EmbeddingError("embedding_response_invalid")`。
- **回归**：RAG 74 条测试通过，438/438 语句覆盖率 100.00%。
- **证据**：单元测试报告/rag-junit.xml、rag-coverage.xml

## BUG-20260729-002 删除已复核追溯后先例索引未失效

- **等级 / 状态**：P1 / 已关闭
- **发现用例**：`backend/tests/tracing/test_trace_api.py::test_clear_all_scope_empties_the_project`；关联 TC-F-051。
- **影响**：删除 accepted/rejected 追溯后，`recall_trace_cases` 仍可能从旧 generation 返回已删除先例，误导后续 Agent。
- **根因**：单条和批量复核会失效 trace 索引，但清理追溯接口删除已复核关系后没有执行同一失效逻辑。
- **修复**：清理集合包含 accepted/rejected 关系时，将 trace 索引标记为 pending，下一次搜索按当前关系重建。
- **回归**：定向清理测试通过；当前完整 backend 362 条通过。
- **证据**：单元测试报告/backend-regression-junit.xml

## BUG-20260729-003 论文任务状态文件并发读取瞬态 404

- **等级 / 状态**：P2 / 已关闭
- **发现用例**：完整 backend 回归中的论文文件端点流程。
- **影响**：Windows 上后台线程替换任务 JSON 时，轮询读取可能短暂得到“任务不存在”，客户端收到 404 而不是 queued/running/succeeded/failed。
- **根因**：任务文件写入由 `_lock` 保护，`get()` 读取没有使用同一把锁。
- **修复**：读取存在性检查、UTF-8 解码和反序列化全程使用同一锁；增加读取等待写入锁的确定性并发测试。
- **回归**：论文定向 4 条通过；当前完整 backend 362 条通过。
- **证据**：单元测试报告/backend-regression-junit.xml

## TEST-20260729-001 浏览器首个冷启动组合等待不足

- **等级 / 状态**：测试设施 / 已关闭
- **现象**：Chrome 1366 首个组合已创建项目并进入正确 URL，但工作台仍显示加载中，全局 8 秒项目名称断言超时；同轮其余 5 组通过。
- **处理**：仅对工作台项目数据加载断言设置 20 秒等待，不放宽 HTTP、控制台、布局或功能断言。
- **结果**：Chrome、Edge、Firefox × 1366x768、1920x1080 完整复测 6 passed。
- **证据**：系统测试证据/兼容性测试/playwright-junit.xml、playwright-terminal.txt

## BUG-20260730-001 显式默认维度错误回退原始置信度

- **等级 / 状态**：P2 / 已关闭
- **发现用例**：`backend/tests/agent/test_confidence_boundaries.py`；关联 TC-F-058。
- **影响**：调用方显式提交六个默认维度时，系统仍按“未提供维度”处理并沿用原始 confidence，导致六维评分结果与用户输入不一致。
- **根因**：评分逻辑通过维度值是否等于默认值判断字段是否缺省，无法区分“未提交”和“显式提交默认值”。
- **修复**：使用 Pydantic `model_fields_set` 判断六个维度是否实际出现；仅在全部缺省时采用兼容回退。
- **回归**：追溯创作与置信度定向测试 20 条通过，188/188 语句覆盖率 100.00%；完整 backend 362 条通过。
- **证据**：单元测试报告/trace-authoring-junit.xml、trace-authoring-coverage.xml

## BUG-20260730-002 重复 penalty 被重复扣分

- **等级 / 状态**：P2 / 已关闭
- **发现用例**：`backend/tests/agent/test_confidence_boundaries.py`；关联 TC-F-058。
- **影响**：相同 penalty 在输入中重复出现时会多次扣分，使结果低于设计公式并可能错误触发人工复核阈值。
- **根因**：评分循环直接遍历原列表，没有按 penalty 类型去重。
- **修复**：按首次出现顺序去重，每类 penalty 最多应用一次，同时保留上下界裁剪。
- **回归**：评分公式、重复项、未知项和上下界测试通过；追溯创作与置信度范围 100.00%。
- **证据**：单元测试报告/trace-authoring-junit.xml、trace-authoring-terminal.txt

## BUG-20260730-003 Agent 追溯写操作遗漏同步和索引失效

- **等级 / 状态**：P1 / 已关闭
- **发现用例**：`backend/tests/agent/test_agent_confirmation.py`；关联 TC-F-057、TC-F-059。
- **影响**：Agent 创建、修改、删除或变更追溯状态后，云同步 outbox 没有对应操作，RAG 已复核先例索引也可能继续返回旧关系，造成不同设备和 Agent 召回结果不一致。
- **根因**：Agent 工具直接调用服务层写入路径，没有复用 REST 路由已有的同步记录与索引失效副作用。
- **修复**：统一 Agent create/update/delete/status 路径的 outbox 记录和 trace 索引失效，并保留人工确认、项目隔离与版本校验。
- **回归**：Agent CRUD、确认接受/拒绝、跨项目隔离、字段校验和版本测试通过；完整 backend 362 条通过。
- **证据**：单元测试报告/backend-regression-junit.xml

## BUG-20260730-004 运行中切换六维开关导致评分口径漂移

- **等级 / 状态**：P1 / 已关闭
- **发现用例**：`backend/tests/agent/test_deep_thinking_confidence.py`；关联 TC-F-058。
- **影响**：Agent 任务启动后若项目开关发生变化，提示词、父/子代理评分和最终持久化可能使用不同模式，同一任务结果不可解释也不可复现。
- **根因**：各阶段执行时重新读取项目设置，没有在任务边界冻结配置快照。
- **修复**：任务启动时冻结评分模式，并显式传递给父代理、子代理、发布和持久化流程。
- **回归**：运行快照、父/子代理传递、评分与持久化一致性测试通过；完整 backend 362 条通过。
- **证据**：单元测试报告/backend-regression-junit.xml

## BUG-20260730-005 六维设置未跨设备同步

- **等级 / 状态**：P1 / 已关闭
- **发现用例**：`backend/tests/sync/test_local_sync_modes.py`、`server/tests/integration/test_cloud_auth_sync.py`；关联 TC-F-059。
- **影响**：项目的 `agent_deep_thinking` 设置只保存在本地，切换设备或执行 bootstrap 后可能恢复默认值，导致同一项目在不同设备采用不同评分模式。
- **根因**：Desktop 和 Server 的项目同步 schema、payload、冲突应用及数据库模型均未包含该字段。
- **修复**：补齐 Desktop/Server push、pull、bootstrap、冲突应用、云项目读写以及 Server 0002 迁移。
- **回归**：本地同步模式和云同步集成测试通过；Server 42 passed、1 skipped，完整 backend 362 条通过。
- **证据**：系统测试证据/构建与环境/server-junit.xml、单元测试报告/backend-regression-junit.xml

## BUG-20260730-006 取消标注遗留选择且错误提示不准确

- **等级 / 状态**：P2 / 已关闭
- **发现用例**：TC-F-056 设计评审与 `backend/tests/tracing/test_annotation_mode.py`；关联 TC-U-007、TC-C-007。
- **影响**：取消标注后旧的论文/代码选择仍可能带入下一次操作；本地校验异常又可能被统一显示为 API 创建失败，用户难以判断如何恢复。
- **根因**：对话框关闭路径未完整重置选择状态，校验和网络请求共用同一异常处理分支。
- **修复**：关闭/取消时清空选择，把本地校验错误与请求错误分开处理并显示对应反馈。
- **回归**：后端标注锚点测试及前端 typecheck/build 通过；真实浏览器选择、高亮与失败恢复仍由 TC-F-056、TC-U-007、TC-C-007 在冻结 RC 上执行。
- **证据**：单元测试报告/trace-authoring-junit.xml、系统测试证据/构建与环境/frontend-typecheck.txt
