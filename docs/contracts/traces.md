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

`POST /api/v1/projects/{project_id}/trace-links/suggest`

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

The PATCH body accepts only `accepted` or `rejected`, and only a `proposed` trace can be reviewed.
Repeated or invalid transitions return `409`. `stale` is system-owned.

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
TRACELAB_LLM_TIMEOUT_SECONDS=20
TRACELAB_LLM_MAX_CANDIDATES=10
```

The API key is represented by `SecretStr` and must never be logged or returned.
