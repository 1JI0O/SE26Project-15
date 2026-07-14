# 钱闵浩任务派发：追溯、LLM 与 Agent

## 1. 任务目标

负责把论文块与代码符号组合成“可解释、可确认、可追溯”的候选关系，并实现带用户确认门禁的 Agent。兼任数据模型所有者，集中维护实体、迁移和全局配置，避免三条后端分支同时修改数据库核心文件。

本任务消费论文与代码模块的稳定 schema，不直接解析 PDF、扫描仓库或实现工作台组件。

## 2. 实施范围与优先级

### P0：必须完成

1. 将追溯流程拆成候选生成、上下文组装、LLM 解释、置信度融合和人工状态五个阶段。
2. 基础候选来自章节/块关键词、代码符号、注释、调用关系和张量图；LLM 不负责从整个仓库盲猜关系。
3. LLM 输出使用结构化 schema，必须包含论文证据、代码证据、关系类型、理由、不确定性和模型信息。
4. 无 API 密钥、超时、限流或无效 JSON 时自动降级到静态候选，并清楚标记来源。
5. 保存 `proposed/accepted/rejected/stale` 状态；代码或论文版本变化后将相关关系标记为待复核。
6. Agent 首批仅开放只读查询、提出补丁、保存代码、重新分析和更新追溯状态等白名单工具；所有写操作必须创建待确认请求。

### P1：本轮争取完成

1. Agent 支持围绕当前论文块、代码符号和图节点进行多轮问答。
2. 写操作保留工具名、参数摘要、用户决定、执行结果和时间戳。
3. 冲突分析比较已确认追溯与当前代码，输出证据充分的差异提示。

### P2：时间允许再做

1. 关系检索的 embedding 召回。
2. 多模型 provider 和成本统计。

## 3. 代码所有权

可直接修改：

- `backend/app/api/routes/traces.py`
- `backend/app/schemas/traces.py`
- `backend/app/services/trace_suggester.py`
- `backend/app/services/tracing/**`（新建）
- `backend/app/api/routes/agent.py`（新建）
- `backend/app/schemas/agent.py`（新建）
- `backend/app/services/agent/**`（新建）
- `backend/app/models/entities.py`
- `backend/app/db/**`
- `backend/app/core/config.py`
- `backend/tests/tracing/**`、`backend/tests/agent/**`（新建）
- `docs/contracts/traces.md`、`docs/contracts/agent.md`（新建）

只读依赖，不直接修改：

- `backend/app/api/router.py`
- `backend/app/api/routes/papers.py`
- `backend/app/api/routes/repositories.py`
- `backend/app/schemas/papers.py`
- `backend/app/schemas/repositories.py`
- `backend/app/schemas/__init__.py`
- `frontend/**`

论文或代码负责人提出数据字段需求时，由你在一次迁移中统一落地。新增 Agent router 后把 router 对象、LLM 依赖和环境变量名交给秦浩翔集中注册，禁止两人同时修改公共入口或依赖文件。

## 4. 接口契约

候选关系最小输出：

```json
{
  "id": "trace-001",
  "paper_block_id": "p3-b12",
  "code_symbol_id": "models/resnet.py::BasicBlock.forward",
  "relation_type": "implements",
  "confidence": 0.82,
  "source": "static+llm",
  "evidence": [
    {"side": "paper", "ref": "p3-b12", "quote": "..."},
    {"side": "code", "ref": "models/resnet.py:24-31", "quote": "..."}
  ],
  "status": "proposed"
}
```

Agent 写工具采用两阶段协议：第一次返回 `confirmation_id`、工具名和参数摘要；只有用户确认后第二次执行。不得把任意 shell、任意路径写入或未校验的模型参数暴露为工具。

## 5. 验收标准

- 固定样例至少产生一条具有双侧证据的候选关系，并可确认或驳回。
- 关闭 LLM 后仍能生成静态候选；模型错误不会写入数据库或中断工作台。
- Agent 未确认时不能更改文件或追溯状态；确认、拒绝和过期请求均有测试。
- 日志和 API 响应不泄漏 API key、完整系统提示词或用户本地绝对路径。
- 追溯/Agent 单元测试、数据库测试及全部后端测试通过。

## 6. 开发与合并约束

分支使用 `codex/iter2-trace-agent`。数据库变化单独提交并附迁移说明；LLM provider、业务编排和 Agent 工具分开提交。不得以真实付费 API 作为默认测试依赖，测试统一使用 fake provider。该分支在论文与代码的最小契约稳定后联调，合并时由秦浩翔最后注册 Agent router。
