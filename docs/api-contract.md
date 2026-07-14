# TraceLab API 接口总览

统一前缀为 `/api/v1`。后端启动后以 `/docs` 提供实时 OpenAPI；本文件用于说明前后端当前实际使用的能力与实现状态。

## 状态约定

- **已实现**：前后端已接线并纳入联调。
- **兼容**：保留旧调用，新的 UI 不再优先使用。
- **接口预留**：返回稳定演示结构，不代表算法或文件生成已经实现。

## 基础与项目

| 方法 | 路径 | 状态 | 说明 |
| --- | --- | --- | --- |
| GET | `/health` | 已实现 | 健康检查 |
| GET | `/projects` | 已实现 | 项目列表 |
| POST | `/projects` | 已实现 | 创建项目 |
| POST | `/projects/batch-delete` | 已实现 | 批量删除最多 100 个项目及其关联数据，返回已删除和不存在的 ID |
| GET | `/projects/{project_id}` | 已实现 | 项目详情 |
| DELETE | `/projects/{project_id}` | 已实现 | 删除单个项目及其关联数据 |

批量删除请求示例：

```json
{
  "project_ids": [1, 2, 3]
}
```

删除会级联清理论文、代码仓库、追溯关系、Agent 确认记录、解析任务元数据和项目上传目录。接口不可恢复，前端会在执行前显示二次确认。

## 集成设置

| 方法 | 路径 | 状态 | 说明 |
| --- | --- | --- | --- |
| GET | `/settings/integrations` | 已实现 | 读取 Agent/MinerU 非敏感配置及密钥配置状态 |
| PUT | `/settings/integrations` | 已实现 | 保存运行时设置；立即作用于新请求和新解析任务 |

密钥字段只允许写入，响应仅返回 `api_key_configured` 或 `api_token_configured`。写入时省略密钥会保留原值，只有显式提交 `clear_api_key` 或 `clear_api_token` 才会清除。

## 论文与 MinerU

| 方法 | 路径 | 状态 | 说明 |
| --- | --- | --- | --- |
| POST | `/projects/{project_id}/paper-jobs` | 已实现 | 上传 PDF 并提交异步 MinerU 任务 |
| GET | `/projects/{project_id}/paper-jobs/{job_id}` | 已实现 | 查询 queued/running/succeeded/failed 状态 |
| GET | `/projects/{project_id}/paper-jobs/{job_id}/result` | 已实现 | 获取统一文档结构与持久化文档 |
| GET | `/projects/{project_id}/paper` | 已实现 | 获取最新论文元数据 |
| GET | `/projects/{project_id}/workspace/paper-pages` | 已实现 | 获取只读页、正文和锚点 |
| POST | `/projects/{project_id}/paper` | 兼容 | 同步 pypdf 路径，当前 UI 不使用 |

标准化结果会保存 MinerU 的 `parser`、`parser_version`、`pages`、段落与锚点；工作台优先读取该结果，不再用 pypdf 覆盖。详细配置与响应见 [contracts/papers.md](contracts/papers.md)。

## 代码仓库与张量流

| 方法 | 路径 | 状态 | 说明 |
| --- | --- | --- | --- |
| POST | `/projects/{project_id}/code` | 已实现 | 上传并安全分析 ZIP |
| POST | `/projects/{project_id}/code/github` | 已实现 | 导入公开 HTTPS GitHub 仓库 |
| GET | `/projects/{project_id}/code` | 已实现 | 最新仓库与分析摘要 |
| GET | `/projects/{project_id}/code/analysis` | 已实现 | 符号、调用、张量语义图和统计 |
| GET | `/projects/{project_id}/workspace/code-tree` | 已实现 | 过滤后的完整层级文件树 |
| GET | `/projects/{project_id}/workspace/code-files/{file_path}` | 已实现 | 安全读取文本代码文件 |
| PUT | `/projects/{project_id}/workspace/code-files/{file_path}` | 已实现 | 保存编辑、递增修订号并使旧追溯 stale |
| GET | `/projects/{project_id}/workspace/tensor-flow` | 已实现 | 布局后的可交互张量图与代码定位 |

仓库过滤、路径约束和图结构详见 [contracts/repositories.md](contracts/repositories.md)。

## 追溯关系

| 方法 | 路径 | 状态 | 说明 |
| --- | --- | --- | --- |
| GET | `/projects/{project_id}/trace-links` | 已实现 | 按状态/来源读取追溯关系 |
| POST | `/projects/{project_id}/trace-links` | 已实现 | 创建带论文和代码证据的人工关系 |
| POST | `/projects/{project_id}/trace-links/suggest` | 已实现 | 静态基线与可选 LLM 增强，返回降级信息 |
| PATCH | `/projects/{project_id}/trace-links/{trace_id}/status` | 已实现 | 人工接受或拒绝 proposed 关系 |
| GET | `/projects/{project_id}/workspace/trace-matrix` | 已实现 | 工作台兼容矩阵视图 |

候选接口返回信封而非数组：

```json
{
  "mode": "static",
  "degraded": true,
  "degraded_reason": "llm_disabled",
  "items": []
}
```

证据、置信度和 stale 生命周期见 [contracts/traces.md](contracts/traces.md)。

## Agent

| 方法 | 路径 | 状态 | 说明 |
| --- | --- | --- | --- |
| POST | `/projects/{project_id}/agent/query` | 已实现 | 单轮问答、只读工具与写操作提案 |
| GET | `/projects/{project_id}/agent/confirmations/{confirmation_id}` | 已实现 | 查询确认记录 |
| POST | `/projects/{project_id}/agent/confirmations/{confirmation_id}/decision` | 已实现 | accept/reject；仅 accept 执行写工具 |

LLM 未配置或调用失败时返回安全降级响应，不创建写确认。工具白名单与审计字段见 [contracts/agent.md](contracts/agent.md)。

## 工作台聚合与预留能力

| 方法 | 路径 | 状态 | 说明 |
| --- | --- | --- | --- |
| GET | `/projects/{project_id}/workspace` | 已实现 | 聚合当前项目数据 |
| GET | `/projects/{project_id}/workspace/report-summary` | 已实现 | 按真实论文/代码/追溯统计生成摘要卡片 |
| GET | `/projects/{project_id}/workspace/conflicts` | 接口预留 | 返回稳定冲突演示结构 |
| GET | `/projects/{project_id}/workspace/flow-graph` | 接口预留 | 旧流程节点结构；张量流请使用 `tensor-flow` |
| POST | `/projects/{project_id}/workspace/analyze` | 接口预留 | 返回 `202` 和占位 job id |

非数字 `project_id`（例如 `prototype`）只用于 UI 原型兼容；正式联调应始终使用真实项目 ID。
