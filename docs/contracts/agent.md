# Agent API contract

Agent 路由注册在 `/api/v1/projects/{project_id}/agent`。运行时由会话、消息、run trace、记忆、技能路由、环境工具和人工确认组成；旧的 `/query` 单轮接口保留用于兼容。

## 自动分析任务

追溯和模型流程图的语义分析由 Agent 独占，本地 AST/关键词结果只作为可选导航索引，不再作为工作台展示结果或 LLM 失败时的语义降级。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/analysis-jobs` | 创建 `architecture` 或 `trace` Agent 分析任务 |
| GET | `/analysis-jobs/{job_id}` | 查询 queued/running/validating/succeeded/failed/stale |
| GET | `/analysis-jobs/{job_id}/events` | SSE 读取可审计进度和工具事件 |
| GET | `/analysis-jobs/{job_id}/artifact` | 读取通过证据校验的结构化结果 |
| GET | `/analysis-jobs/{job_id}/diagnostics` | 读取该 Run 的完整失败信息，供工作台调试模式展示 |
| POST | `/analysis-jobs/{job_id}/retry` | 基于相同 artifact revision 强制重试 |
| POST | `/analysis-jobs/{job_id}/cancel` | 提前中止分析，保留已发布的追溯关系 |

`architecture` 默认深度为 2：入口函数、直接项目调用、项目调用内部的 `torch/nn/外部` 算子；硬上限为 3。`trace` 在单 Run 内按四阶段执行（侦察 → 代码制图 → 区域取证 → 归并自校，见 `analysis_jobs._system_prompt` 与 `builtin_skills/trace-analysis`），发布 schema 为 `trace-agent-v2`：每个候选含双侧精确 quote、`occurrence`（quote 在 block/行范围内的第几次出现）、论文 `target_type` 与代码 `role`，以及三个独立分数 `salience`/`relevance`/`confidence`。`publish_trace_candidates` 在指定 occurrence 处校验 quote 命中并计算字符范围与内容 hash，写入 `PaperTarget`/`CodeTarget` 与带 target 引用的 `TraceLink`。LLM 不可用、预算耗尽、schema 无效或证据无法在指定 occurrence 精确匹配时，任务失败且不产生 artifact。

`cancel` 用于用户提前中止：将 job 置为 `cancelling`，运行中的 worker 在下一步边界检测到后收尾并**保留已发布的追溯关系**，job 以 `succeeded` 结束（进度 `code=analysis_cancelled`）。尚未启动的排队 job 直接结束、不占用 worker。已处于终态的 job 幂等返回。中止后保留的关系与正常产出完全等价：它们已按 fingerprint 落库，下一轮重新生成会在其基础上 upsert，无需特殊处理。

`diagnostics` 是只读诊断接口，仅在工作台开启调试模式时调用。`error_code` 只是短代码（provider 4xx、证据校验失败、SQLite 锁都长得一样），该接口额外返回 Run 的 `degraded_reason`、`provider_name`/`model_name`、已记录的 run event 列表和 `trace_json` 末尾的模型/工具步骤，用于定位真实失败原因。`event_limit`/`step_limit` 控制返回条数（默认 200/60）。

论文解析成功、代码分析就绪且 provider 可用后，追溯协调器（`services/tracing/coordinator.py`）自动创建 architecture+trace 任务，无需手动触发；`create_analysis_job` 按 fingerprint 幂等。

分析任务复用现有 Agent provider、Run、Run Event、重试和能力快照，但使用 `kind=analysis` 的隐藏会话，不出现在普通聊天历史。`publish_architecture_graph` 与 `publish_trace_candidates` 只在对应分析任务中可见；它们只能保存可重算 artifact 和 proposed trace，不能修改代码或代替用户接受追溯。

导入完成后的**自动后台追溯只创建 `trace` 任务**：架构 Agent 任务是可选上下文（流程图由本地静态分析生成，不消费该 artifact），成本高且在小模型上不稳定，因此不自动运行、也绝不阻塞或延迟双向追溯交付。手动“重新生成”同样只跑 `trace`。

分析任务可选使用比对话模型更强的模型：设置项 `agent.analysis_model`（或 `TRACELAB_LLM_ANALYSIS_MODEL`）留空时复用对话模型，填入（如 `deepseek-v4-pro`）后仅对 `trace`/`architecture` 分析任务生效，用于少量重要追溯的质量提升与成本控制。

分析任务的进度事件（`analysis.tool.started`/`analysis.tool.completed`/`analysis.tool.failed`）携带可审计的 `activity`（如“阅读论文片段 p3-b44”“检索代码 …”“发布 N 条追溯候选并校验证据”）、`step` 与 `budget`，供前端展示实时活动与步数进度，不暴露模型隐式思维链。

`trace` 任务支持**渐进发布**：`publish_trace_candidates` 可被多次调用（每批立即校验、落库、并发 `analysis.published` 事件，携带 `new_links`/`total_links`/`artifact_id`/`code_revision`），前端据此**边分析边渲染**，不必等整轮结束；同一次 run 复用一个 artifact，links 按内容指纹幂等累加。终止不再靠固定步数：模型在发布完所有可辩护候选、且每个 must-inspect 目标 linked 或列入 unresolved 后调用 `finish_analysis` 显式结束；步数只有**启发式软目标**（由论文公式/算法对象数推断，仅用于提醒收敛）与**硬上限**（安全兜底，耗尽时若已产出则定稿为成功、否则失败）。空 payload 的 publish 一律拒绝。`architecture` 仍为单次 publish 即终止。

## 会话

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/conversations` | 按最近更新时间列出会话；`include_archived=true` 包含归档会话 |
| POST | `/conversations` | 新建会话 |
| GET | `/conversations/{conversation_id}` | 读取完整消息历史、工具事件、引用和确认卡片 |
| PATCH | `/conversations/{conversation_id}` | 重命名或归档会话 |
| POST | `/conversations/{conversation_id}/messages` | 兼容同步执行一轮 Agent loop |
| POST | `/conversations/{conversation_id}/runs` | 提交异步 Run，返回用户消息和 `run_id` |
| GET | `/runs/{run_id}/events` | SSE 订阅持久化 Run 事件 |
| GET | `/runs/{run_id}/event-list?after=N` | 从序号 N 后读取事件，供恢复和诊断 |

消息请求可附加当前 IDE 上下文：

```json
{
  "message": "检查当前实现并给出低风险修改",
  "context": {
    "paper_block_id": "p3-b12",
    "code_symbol_id": "models/resnet.py::BasicBlock.forward",
    "file_path": "models/resnet.py",
    "line": 42,
    "trace_id": "trace-...",
    "graph_node_id": "module-block-1",
    "graph_root_symbol": "models/resnet.py::ResNet"
  }
}
```

默认每轮最多执行 18 个模型步骤，可通过 `TRACELAB_AGENT_MAX_LOOP_STEPS` 调整。run trace 持久化模型步骤、工具结果、能力快照和稳定错误码；供应商临时错误最多重试 3 次。原生 function calling 被拒绝时会自动退回结构化 JSON 工具协议。

成功工具调用按工具名和规范化参数生成指纹；相同调用会复用已有结果而不再次访问环境。连续重复后运行时撤销工具目录并要求模型汇总结论。预算耗尽时额外执行一次无工具综合，供应商仍不收敛时返回基于已有证据的降级结论，不再以 `tool_loop_limit` 丢弃本轮。

SSE 事件包括 `run.queued`、`run.started`、`reasoning.summary`、`message.delta`、`message.reset`、`tool.started`、`tool.completed`、`tool.failed`、`tool.reused`、`message.completed` 和终态事件。`reasoning.summary` 是可审计的进度摘要，不传输供应商隐藏思维链；`message.delta` 才是最终回答文本增量。供应商在已输出文本后重试时发送 `message.reset`，前端清空不完整片段。所有事件带单调 `sequence` 并写入 SQLite，前端断线后使用 `after=sequence` 续传。应用重启时会恢复 `queued/running` run，已存在终态助手消息的 run 不会重复执行。

## 记忆

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/memories` | 返回当前项目记忆与全局跨项目记忆 |
| POST | `/memories` | 创建 `project` 或 `global` 范围记忆 |
| DELETE | `/memories/{memory_id}` | 删除一条可见记忆 |

记忆按确定性的关键词/中文双字组相关性和重要度检索。用户使用“记住”“以后都”“remember”等明确表达时，会自动保存偏好；包含“跨项目”“全局”等表达时保存为全局记忆。API 密钥、完整系统提示词和私有工具参数不写入记忆。

## 工具与技能

只读工具自动执行：

- 项目与论文：`get_project_overview`、`search_paper`、`get_paper_block`
- 代码：`search_code`、`read_code_file`、`get_code_symbol`
- 架构：`get_architecture`、`get_graph_node`、`focus_architecture`
- 追溯：`list_trace_links`、`get_trace_detail`
- 记忆与修改准备：`recall_memory`、`propose_code_patch`、`analyze_change_risk`
- UI 交互：`open_code_location`、`open_paper_location`

写工具必须确认：

- `save_code_file`
- `rerun_analysis`
- `update_trace_status`
- `create_trace_link`

代码保存还有一层硬约束：同一 run 中必须先针对同一路径、当前基础 SHA-256 和目标内容成功执行 `propose_code_patch` 与 `analyze_change_risk`，否则 loop 只会收到 `write_preconditions_missing`，不会创建确认请求。静态分析缓存未就绪或期间文件发生变化时，风险证据失效并需重新分析。

技能由能力注册表按描述、触发词和当前 IDE 上下文选择，内置包括论文解释、架构分析、追溯分析、代码修改和风险分析。技能只改变推理与证据要求，不扩大工具权限。

### 外部 Skill

注册表每轮重新发现 `SKILL.md`，因此追加外部能力不需要修改 Python 源码。搜索顺序包括：

1. 内置 `app/services/agent/builtin_skills/`
2. `~/.tracelab/skills/`
3. `~/.openclaw/skills/`
4. TraceLab 仓库根目录 `skills/`
5. `TRACELAB_AGENT_SKILL_ROOTS` 追加的逗号分隔目录

每个目录使用 `<skill-name>/SKILL.md`，最小格式如下：

```markdown
---
name: explain-custom-model
description: Explain AcmeNet internals when users ask about AcmeNet.
metadata:
  tracelab:
    triggers: [acmenet]
    preferred_tools: [search_code, read_code_file]
---
Read the implementation before making architectural claims.
```

`name` 必须为小写 kebab-case。外部 Skill 默认 `enabled=false, trusted=false`，必须通过能力页或 `PATCH /capabilities/{capability_id}` 同时启用和信任。内容按 SHA-256 写入 run 能力快照，便于重放时确认版本。

### 外部 Tool 与 MCP

插件目录默认为仓库 `plugins/` 和 `~/.tracelab/plugins/`，也可由 `TRACELAB_AGENT_PLUGIN_ROOTS` 扩展。清单示例：

```json
{
  "id": "local-analysis",
  "name": "Local Analysis Tools",
  "version": "1.0.0",
  "skills": ["skills"],
  "mcp_servers": [
    {
      "id": "analyzer",
      "transport": "http",
      "url": "http://127.0.0.1:9010/mcp",
      "timeout_seconds": 15
    }
  ]
}
```

清单文件名为 `tracelab.plugin.json`。插件本身先经过启用/信任门，随后通过 MCP `initialize`、`notifications/initialized` 和 `tools/list` 发现工具。TraceLab 对支持的 JSON Schema 子集执行封闭式校验；未知关键字直接拒绝。MCP `readOnlyHint=false` 的工具一律进入人工确认链。当前仅实现 HTTP transport，不执行插件内任意本地脚本。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/capabilities` | 查看 Skill/Tool/Plugin 来源、版本、读写属性和信任状态 |
| PATCH | `/capabilities/{capability_id}` | 更新 `enabled` 与 `trusted` |

## 确认协议

会话内确认使用：

- `POST /conversations/{conversation_id}/confirmations/{confirmation_id}/decision`

兼容接口仍可使用：

- `GET /confirmations/{confirmation_id}`
- `POST /confirmations/{confirmation_id}/decision`

`reject` 只写审计状态，不执行工具。`accept` 按 approved → executed/failed 执行一次；会话接口随后将工具结果重新送回同一个 run，继续生成回答或下一张确认卡片。请求默认 900 秒过期，重复决策返回已有终态。

确认响应只暴露路径、哈希、数量和状态等安全摘要。完整代码内容仅存在私有审计载荷中。保存时重新校验相对路径和基础 SHA-256；成功后仓库修订号递增，相关追溯标记为 stale。

## 配置与降级

Agent 使用应用设置中的 OpenAI-compatible base URL、模型、密钥和超时。LLM 未启用、未配置或请求失败时，用户消息、会话与 run 仍会保存，并返回稳定的 `degraded_reason`，但不会自行创建写确认。

```text
TRACELAB_AGENT_CONFIRMATION_TTL_SECONDS=900
```

日志和响应不得包含 API key、完整私有写参数、堆栈或用户本机绝对路径。
