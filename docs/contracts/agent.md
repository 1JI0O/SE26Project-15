# Agent API contract

The Agent router is exported as `app.api.routes.agent:router`. The architecture integration owner
must register it in the shared API router; the trace branch does not modify that entrypoint.

All endpoints use `/api/v1/projects/{project_id}/agent`.

## Query

`POST /query`

```json
{
  "message": "Update the accepted trace after reviewing this block",
  "context": {
    "paper_block_id": "p3-b12",
    "code_symbol_id": "models/resnet.py::BasicBlock.forward",
    "graph_node_id": "add"
  }
}
```

The Agent is single-turn and may make at most four read-tool steps. It returns either a final answer
or one pending write confirmation. When the LLM is disabled or fails, the response is degraded and
contains no confirmation.

Read-only tools execute immediately:

- `get_paper_block`
- `get_code_symbol`
- `get_graph_node`
- `list_trace_links`
- `propose_code_patch`

Write tools always create a pending confirmation:

- `save_code_file`
- `rerun_analysis`
- `update_trace_status`

There is no shell, arbitrary path, URL fetch, or caller-selected model tool. Unknown tools and extra
arguments are rejected.

## Confirmation protocol

- `GET /confirmations/{confirmation_id}`
- `POST /confirmations/{confirmation_id}/decision`

Decision body:

```json
{"decision": "accept"}
```

`reject` changes the audit row to rejected without execution. `accept` moves through approved and
then executed/failed. Pending requests expire after 900 seconds by default. Repeated decisions return
the existing terminal result and do not intentionally repeat execution.

Confirmation responses expose only a safe summary:

```json
{
  "confirmation_id": "confirm-...",
  "project_id": 1,
  "tool_name": "save_code_file",
  "parameter_summary": {
    "path": "models/resnet.py",
    "characters": 428,
    "base_sha256": "...",
    "target_sha256": "..."
  },
  "status": "pending",
  "user_decision": null,
  "result": null,
  "error_summary": null,
  "expires_at": "2026-07-14T00:15:00Z",
  "created_at": "2026-07-14T00:00:00Z",
  "decided_at": null,
  "executed_at": null
}
```

Full code content is kept in the private audit payload and is never returned by confirmation APIs.
Save execution revalidates the allowed relative path and base SHA-256. A successful save increments
the repository revision and marks affected traces stale.

## Reanalysis integration

The code-analysis owner registers an idempotent callback through
`register_analysis_enqueuer(enqueuer)`. Its inputs are project ID, relative targets, and the
confirmation ID used as the idempotency key. If the callback is not registered, accepted reanalysis
requests fail safely with `analysis_service_not_integrated`; the Agent never fabricates a job result.

## Configuration and logging

```text
TRACELAB_AGENT_CONFIRMATION_TTL_SECONDS=900
```

Logs and responses must not contain the API key, system prompt, full private arguments, stack traces,
or user-local absolute paths. Error summaries use stable reason codes.
