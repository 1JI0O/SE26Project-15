# Agent API contract

Agent 路由注册在 `/api/v1/projects/{project_id}/agent`。运行时由会话、消息、run trace、记忆、技能路由、环境工具和人工确认组成；旧的 `/query` 单轮接口保留用于兼容。

## 会话

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/conversations` | 按最近更新时间列出会话；`include_archived=true` 包含归档会话 |
| POST | `/conversations` | 新建会话 |
| GET | `/conversations/{conversation_id}` | 读取完整消息历史、工具事件、引用和确认卡片 |
| PATCH | `/conversations/{conversation_id}` | 重命名或归档会话 |
| POST | `/conversations/{conversation_id}/messages` | 在已有上下文中执行一轮 Agent loop |

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

每轮最多执行 10 个模型步骤。run trace 持久化模型步骤、工具结果和稳定错误码；供应商临时错误最多重试 3 次。原生 function calling 被拒绝时会自动退回结构化 JSON 工具协议。重复无效工具、未授权工具和超限循环会停止本轮，但不会丢失会话历史。

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
- UI 交互：`open_code_location`

写工具必须确认：

- `save_code_file`
- `rerun_analysis`
- `update_trace_status`
- `create_trace_link`

代码保存还有一层硬约束：同一 run 中必须先对相同路径和目标内容成功执行 `propose_code_patch` 与 `analyze_change_risk`，否则 loop 只会收到 `write_preconditions_missing`，不会创建确认请求。

技能由确定性触发器选择，当前包括论文解释、架构分析、追溯分析、代码修改和风险分析。技能只改变推理与证据要求，不扩大工具权限。

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
