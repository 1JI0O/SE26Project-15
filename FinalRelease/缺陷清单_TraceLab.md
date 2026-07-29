# TraceLab 缺陷清单

## 汇总

| 状态 | P0 | P1 | P2 | P3 | 测试设施 |
|---|---:|---:|---:|---:|---:|
| 已关闭 | 0 | 4 | 3 | 1 | 2 |
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
- **结果**：静态分析定向测试 52 条通过、覆盖率 100.00%；RAG 定向测试 74 条通过、覆盖率 100.00%；修复本轮并发读取缺陷后完整后端 306 条通过。
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
- **回归**：定向清理测试通过；完整 backend 306 条通过。
- **证据**：单元测试报告/backend-regression-junit.xml

## BUG-20260729-003 论文任务状态文件并发读取瞬态 404

- **等级 / 状态**：P2 / 已关闭
- **发现用例**：完整 backend 回归中的论文文件端点流程。
- **影响**：Windows 上后台线程替换任务 JSON 时，轮询读取可能短暂得到“任务不存在”，客户端收到 404 而不是 queued/running/succeeded/failed。
- **根因**：任务文件写入由 `_lock` 保护，`get()` 读取没有使用同一把锁。
- **修复**：读取存在性检查、UTF-8 解码和反序列化全程使用同一锁；增加读取等待写入锁的确定性并发测试。
- **回归**：论文定向 4 条通过；完整 backend 306 条通过。
- **证据**：单元测试报告/backend-regression-junit.xml

## TEST-20260729-001 浏览器首个冷启动组合等待不足

- **等级 / 状态**：测试设施 / 已关闭
- **现象**：Chrome 1366 首个组合已创建项目并进入正确 URL，但工作台仍显示加载中，全局 8 秒项目名称断言超时；同轮其余 5 组通过。
- **处理**：仅对工作台项目数据加载断言设置 20 秒等待，不放宽 HTTP、控制台、布局或功能断言。
- **结果**：Chrome、Edge、Firefox × 1366x768、1920x1080 完整复测 6 passed。
- **证据**：系统测试证据/兼容性测试/playwright-junit.xml、playwright-terminal.txt
