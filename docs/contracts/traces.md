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

### 片段级锚点与评分（V1）

每条 link 现在携带独立的 `PaperTarget` / `CodeTarget`（表 `paper_target` / `code_target`），并在 `TraceLink` 上新增 `paper_target_id`、`code_target_id`、`relevance` 列，以及 `score_basis_json` / `provenance_json`。`evidence` 每一侧新增：

- `occurrence`：quote 在所属 block（论文）或引用行范围（代码）内的第几次出现，从 1 计；
- `char_start` / `char_end`：能精确定位时的字符范围（论文为 block 文本内偏移，代码为文件内偏移）；
- 代码侧还有 `match_line_start` / `match_line_end`、`column_start` / `column_end`；
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

The PATCH body accepts only `accepted` or `rejected`, and only a `proposed` trace can be reviewed.
Repeated or invalid transitions return `409`. `stale` is system-owned.

Batch review accepts `{ "status": "accepted"|"rejected", "trace_ids": [...] | null }`. `trace_ids`
selects a subset; `null`/omitted applies to every currently-`proposed` link in the project. Only
`proposed` links change (already-decided/stale are skipped), so it is idempotent. The response is
`{ status, updated_count, skipped_count, updated: [TraceLinkRead...] }`.

Manual creation through `POST /trace-links` remains available for compatibility, but requires both
paper and code evidence and always creates a proposed relation.

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
