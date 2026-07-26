# Trace API contract

All endpoints use the `/api/v1/projects/{project_id}/trace-links` prefix.

## Ownership and integration

- The trace branch owns `routes/traces.py`, `schemas/traces.py`, and `services/tracing/**`.
- Paper and repository modules are read-only dependencies.
- Paper parsing must expose stable block IDs and text. Repository analysis must expose stable
  symbol IDs, relative paths, source lines, comments/calls, and a semantic tensor graph.
- Paper upload, repository upload, code save, and reanalysis must call
  `record_artifact_revision_change` after a successful version change.

## Generate suggestions

追溯由 Agent 独占。论文解析成功、代码分析就绪且 provider 可用后，**协调器自动**在后台创建 `architecture` 与 `trace` 两个 Agent analysis job（无需点击按钮，见 `services/tracing/coordinator.py`；`create_analysis_job` 按 fingerprint 幂等，重复触发不会重复建任务）。手动重跑仍可显式创建 job。完成后通过 list endpoint 读取 `source=agent` 的 proposed links。

```text
POST /api/v1/projects/{project_id}/agent/analysis-jobs
GET  /api/v1/projects/{project_id}/agent/analysis-jobs/{job_id}/events
GET  /api/v1/projects/{project_id}/trace-links
```

分析失败时不生成静态或规则降级候选。旧 revision 结果保留为 stale 供审计。Agent 新结果使用 `source: "agent"`、`static_confidence: 0`。

trace 分析任务内部可将区域取证并行派发给子代理（见 [agent 契约](agent.md) 的 `dispatch_trace_subagents`）；这只影响任务内部执行方式与 SSE 事件流的来源标注，`TraceLink` 数据形状与本契约的对外接口不变。

### 片段级锚点与评分（V1）

每条 link 现在携带独立的 `PaperTarget` / `CodeTarget`（表 `paper_target` / `code_target`），并在 `TraceLink` 上新增 `paper_target_id`、`code_target_id`、`relevance` 列，以及 `score_basis_json` / `provenance_json`。`evidence` 每一侧新增：

- `occurrence`：quote 在所属 block（论文）或引用行范围（代码）内的第几次出现，从 1 计；
- `char_start` / `char_end`：能精确定位时的字符范围（论文为 block 文本内偏移，代码为文件内偏移）；
- 代码侧还有 `match_line_start` / `match_line_end`、`column_start` / `column_end`；当锚点降级到 `normalized` / `approximate`（无 char 偏移）时，`match_line_*` 由 quote 的字母数字签名在文件内重新定位得到，因此始终指向核实过的行；`line_start` / `line_end` 仅在包含该命中时才保留模型声明的上下文区间；
- `quote_hash` / `code_quote_hash`：`sha256(规范化 quote)`，用于跨 revision 的内容一致性；
- 论文侧 `target_type`（formula/variable/constraint/algorithm/figure/method_text）、`salience`；代码侧 `role`。

发布前，`publish_trace_candidates` 在指定 occurrence 处校验 quote 命中并计算上述锚点；命中失败即拒绝，不静默通过。三个分数含义不同：`salience`（目标重要性）、`relevance`（该代码承担实现的程度，边级）、`confidence`（关系判断正确的把握，边级）。一对多列表按 `relevance` 排序。

### Legacy endpoint (retired keyword path)

`POST /api/v1/projects/{project_id}/trace-links/suggest`

**该端点的关键词候选写入已下线**（架构文档 §15）。它仍返回 `200`，但只做 staleness 记账，不再生成或写入任何 `TraceLink`，响应恒为 `degraded=true`、`degraded_reason="static_candidates_retired"`、`items=[]`。候选发现完全交给 Agent（见上）。以下为历史形状，仅供兼容参考：

Request body is optional:

```json
{
  "use_llm": true,
  "paper_document_id": null,
  "code_repository_id": null
}
```

Omitted artifact IDs select the latest versions in the project. The response always reports whether
LLM enhancement was used and whether it degraded:

```json
{
  "mode": "static+llm",
  "degraded": false,
  "degraded_reason": null,
  "items": [
    {
      "id": "trace-8f7b...",
      "project_id": 1,
      "paper_document_id": 2,
      "paper_block_id": "p3-b12",
      "code_repository_id": 4,
      "code_revision": 1,
      "code_symbol_id": "models/resnet.py::BasicBlock.forward",
      "relation_type": "implements",
      "confidence": 0.82,
      "static_confidence": 0.76,
      "llm_confidence": 0.94,
      "source": "static+llm",
      "evidence": [
        {"side": "paper", "ref": "p3-b12", "quote": "..."},
        {"side": "code", "ref": "models/resnet.py::BasicBlock.forward", "quote": "..."}
      ],
      "rationale": "...",
      "uncertainty": {"level": "low", "reasons": []},
      "model": {
        "provider": "openai-compatible",
        "name": "configured-model",
        "prompt_version": "trace-v1"
      },
      "status": "proposed",
      "stale_reason": null,
      "created_at": "2026-07-14T00:00:00Z",
      "updated_at": "2026-07-14T00:00:00Z"
    }
  ]
}
```

Degraded reasons are stable machine-readable codes such as `llm_disabled`, `llm_not_configured`,
`llm_timeout`, `llm_rate_limited`, `llm_upstream_error`, `llm_invalid_json`, and
`llm_evidence_invalid`. Invalid model data is never persisted.

## List and review

- `GET /api/v1/projects/{project_id}/trace-links?status=proposed&source=static`
- `PATCH /api/v1/projects/{project_id}/trace-links/{trace_id}/status`
- `POST /api/v1/projects/{project_id}/trace-links/batch-status`

The PATCH body accepts `accepted`, `rejected`, or `proposed`. `accepted`/`rejected` review a
`proposed` trace; `proposed` **reverts** (撤回) an `accepted`/`rejected` decision back to the
review queue and clears `decided_at`. Repeated or invalid transitions return `409`. `stale` is
system-owned and can be neither set nor reverted.

Batch review accepts `{ "status": "accepted"|"rejected"|"proposed", "trace_ids": [...] | null }`.
`trace_ids` selects a subset; `null`/omitted applies to every eligible link in the project.
`accepted`/`rejected` move only `proposed` links; `proposed` reverts only `accepted`/`rejected`
links (everything else is skipped), so the operation is idempotent. The response is
`{ status, updated_count, skipped_count, updated: [TraceLinkRead...] }`.

Manual creation through `POST /trace-links` remains available for compatibility, but requires both
paper and code evidence and always creates a proposed relation.

## Clearing before a rerun

`DELETE /api/v1/projects/{project_id}/trace-links?scope=proposed|agent|all`

Removes previously generated relations so a rerun starts from a known state. `scope` decides how
much is dropped:

| scope | Deletes | Keeps |
| --- | --- | --- |
| `proposed` (default) | every `proposed` link | all `accepted`/`rejected` decisions |
| `agent` | every link with `source != "manual"` | manually created links |
| `all` | every link in the project | nothing |

Paper/code targets left without any referencing link are pruned in the same transaction, so
repeated regeneration cannot grow `paper_target`/`code_target` without bound. Deletions are mirrored
into the local sync outbox as `operation="delete"`, so a cloud-enabled project does not resurrect
the removed relations on its next sync. The response is `{ scope, deleted_count, kept_count }`, and
repeating the call is a no-op rather than an error.

The workbench asks the user before rerunning ("保留历史记录" / "清空后重新生成"); keeping is the
default because reruns upsert by fingerprint and never overwrite a human decision.

## Version behavior

Trace fingerprints include paper document ID, repository ID/revision, block ID, symbol ID, and
relation type. Reruns update proposed candidates but never overwrite accepted/rejected decisions.
When paper or code versions change, proposed/accepted links from the previous version become stale;
rejected history is retained.

## LLM configuration handoff

The integration owner must add runtime `httpx` and provide:

```text
TRACELAB_LLM_ENABLED=false
TRACELAB_LLM_BASE_URL=
TRACELAB_LLM_API_KEY=
TRACELAB_LLM_MODEL=
TRACELAB_LLM_THINKING_MODE=
TRACELAB_LLM_TIMEOUT_SECONDS=20
TRACELAB_LLM_MAX_CANDIDATES=10
```

The API key is represented by `SecretStr` and must never be logged or returned.
